# -*- coding: utf-8 -*-
"""Painel compacto MANOBRAS DE CABECEIRA: conecta passadas existentes.

Somente le as passadas e grava a camada derivada ``16_Manobras_Cabeceira``
(role HEADLAND_TURN) em ``FORTSMART - <talhao> / 10_PLANEJAMENTO``.
"""

from __future__ import annotations

import json

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)
from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsLineSymbol,
    QgsMapLayerProxyModel,
    QgsPointXY,
    QgsProject,
    QgsRendererCategory,
    QgsSettings,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgsMapLayerComboBox
from shapely import wkb as shapely_wkb
from shapely.ops import unary_union
from shapely.validation import make_valid

from ..core.crs import CrsValidationError, inspect_authid, require_projected_metric, suggest_sirgas_utm_epsg
from ..core.headland_turn_engine import (
    HEADLAND_TURN_FIELDS,
    STATUS_DIRECTION_CONFLICT,
    STATUS_INFEASIBLE_RADIUS,
    STATUS_OBSTACLE_CONFLICT,
    STATUS_OK,
    STATUS_WARNING_CROSSING,
    HeadlandTurnError,
    PassRecord,
    TurnMode,
    TurnSettings,
    build_logical_passes,
    plan_headland_turns,
)
from ..core.layer_roles import (
    HEADLAND_TURN_ROLE,
    ROLE_PROPERTY,
    apply_qgis_layer_role,
    classify_layer,
    find_layer_by_role,
    layer_field_id,
    layer_role,
    mark_temporary_preview,
)
from ..core.persistence_manager import FortSmartPersistenceManager, PersistenceError
from .layer_tree_organizer import (
    preview_group,
    project_group,
    project_group_of,
    publish_persisted,
    remove_group_if_empty,
)
from ..core.planting_line_cut_engine import (
    is_field_boundary_layer_name,
    line_id_field,
    line_number_field,
    obstacle_layer_priority,
)

TURN_PREVIEW_PROPERTY = "fortsmart_precision/headland_turn_preview"
PREVIEW_SUFFIX = " (pré-visualização)"
SETTINGS_RADIUS = "fortsmart_precision/headland_turns/min_turn_radius_m"
SOURCE_FINAL = "FINAL_WORK_PATH"
SOURCE_PLAN = "WORK_PATH"
OBSTACLE_ROLES = ("OBSTACLE", "SAFETY_ZONE")
FIELD_TYPES = {
    "string": QVariant.String,
    "int": QVariant.Int,
    "double": QVariant.Double,
    "bool": QVariant.Bool,
}
STATUS_STYLE = {
    STATUS_OK: ("30,150,60,255", "solid", 0.8),
    STATUS_WARNING_CROSSING: ("240,150,0,255", "solid", 0.8),
    STATUS_OBSTACLE_CONFLICT: ("200,0,160,255", "dash", 0.8),
    STATUS_INFEASIBLE_RADIUS: ("210,30,30,255", "dash", 0.6),
    STATUS_DIRECTION_CONFLICT: ("120,120,120,255", "dot", 0.6),
}
STATUS_LABELS = {
    STATUS_OK: "OK",
    STATUS_WARNING_CROSSING: "cruzamento",
    STATUS_INFEASIBLE_RADIUS: "inviável (raio/espaço)",
    STATUS_OBSTACLE_CONFLICT: "obstáculo",
    STATUS_DIRECTION_CONFLICT: "sentido",
}


def is_turn_layer(layer) -> bool:
    return layer_role(layer) == HEADLAND_TURN_ROLE.role or bool(
        layer.customProperty(TURN_PREVIEW_PROPERTY, False)
    )


def _to_shapely(geometry: QgsGeometry):
    shape = shapely_wkb.loads(bytes(geometry.asWkb()))
    return shape if shape.is_valid else make_valid(shape)


def _as_int(value):
    try:
        return None if value is None or str(value) in ("", "NULL") else int(value)
    except (TypeError, ValueError):
        return None


def _as_text(value):
    return None if value is None or str(value) in ("", "NULL") else str(value)


class HeadlandTurnsDialog(QDialog):
    """Pre-visualiza e salva manobras U entre passadas consecutivas."""

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.preview_layer_id = None
        self.last_plan = None
        self.last_source_name = ""
        self.setWindowTitle("Manobras de cabeceira")
        self.resize(460, 420)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>MANOBRAS DE CABECEIRA</b>"))
        intro = QLabel(
            "Liga o fim de cada passada ao início da próxima com curva tangente "
            "(raio ≥ mínimo). As passadas não são alteradas; o que não couber "
            "sai marcado como inviável."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.source_combo = QComboBox()
        self.source_combo.addItem("Linhas finais após obstáculos", SOURCE_FINAL)
        self.source_combo.addItem("Planejamento original", SOURCE_PLAN)
        form.addRow("Fonte das passadas:", self.source_combo)
        self.pass_combo = QgsMapLayerComboBox()
        self.pass_combo.setFilters(QgsMapLayerProxyModel.LineLayer)
        form.addRow("Passadas:", self.pass_combo)
        self.area_combo = QgsMapLayerComboBox()
        self.area_combo.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        self.area_combo.setAllowEmptyLayer(True)
        form.addRow("Área de manobra:", self.area_combo)
        self.boundary_combo = QgsMapLayerComboBox()
        self.boundary_combo.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        self.boundary_combo.setAllowEmptyLayer(True)
        form.addRow("Limite externo:", self.boundary_combo)
        self.type_combo = QComboBox()
        self.type_combo.addItem("Automático", TurnMode.AUTO.value)
        self.type_combo.addItem("U-turn", TurnMode.U_TURN.value)
        form.addRow("Tipo:", self.type_combo)
        self.radius_spin = QDoubleSpinBox()
        self.radius_spin.setRange(0.0, 500.0)
        self.radius_spin.setDecimals(2)
        self.radius_spin.setSuffix(" m")
        self.radius_spin.setSpecialValueText("Não informado")
        self.radius_spin.setToolTip("Raio mínimo de giro do conjunto (dado da máquina; não é estimado).")
        self.radius_spin.setValue(float(QgsSettings().value(SETTINGS_RADIUS, 0.0) or 0.0))
        form.addRow("Raio mínimo:", self.radius_spin)
        layout.addLayout(form)

        self.keep_inside_check = QCheckBox("Manter dentro da área de manobra")
        self.obstacles_check = QCheckBox("Considerar obstáculos")
        self.direction_check = QCheckBox("Respeitar sentido das passadas")
        for check in (self.keep_inside_check, self.obstacles_check, self.direction_check):
            check.setChecked(True)
            layout.addWidget(check)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        actions = QHBoxLayout()
        self.preview_btn = QPushButton("Pré-visualizar")
        self.save_btn = QPushButton("Salvar")
        self.close_btn = QPushButton("Fechar")
        for button in (self.preview_btn, self.save_btn, self.close_btn):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.preview_btn.clicked.connect(self.preview)
        self.save_btn.clicked.connect(self.save)
        self.close_btn.clicked.connect(self.reject)

        self._auto_select()
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        for combo in (self.pass_combo, self.area_combo, self.boundary_combo):
            combo.layerChanged.connect(self._invalidate)
        self.type_combo.currentIndexChanged.connect(self._invalidate)
        self.radius_spin.valueChanged.connect(self._invalidate)
        for check in (self.keep_inside_check, self.obstacles_check, self.direction_check):
            check.toggled.connect(self._invalidate)
        self._update_actions()

    # ------------------------------------------------------------ selecao ----
    def _vector_layers(self, geometry_type):
        return [
            layer for layer in QgsProject.instance().mapLayers().values()
            if isinstance(layer, QgsVectorLayer) and layer.isValid()
            and layer.geometryType() == geometry_type and not is_turn_layer(layer)
        ]

    def _pass_layer_for(self, source, *, non_empty=False):
        lines = self._vector_layers(QgsWkbTypes.LineGeometry)
        return find_layer_by_role(lines, source, non_empty=non_empty)

    def _auto_select(self):
        # Linhas finais so vencem se tiverem feicoes (camada vazia = EMPTY_ROLE_LAYER).
        final = self._pass_layer_for(SOURCE_FINAL, non_empty=True)
        source = SOURCE_FINAL if final is not None else SOURCE_PLAN
        self.source_combo.setCurrentIndex(self.source_combo.findData(source))
        layer = final or self._pass_layer_for(SOURCE_PLAN)
        if layer is not None:
            self.pass_combo.setLayer(layer)
        field_id = layer_field_id(layer) if layer is not None else ""
        polygons = [
            polygon for polygon in self._vector_layers(QgsWkbTypes.PolygonGeometry)
            if not field_id or layer_field_id(polygon) in ("", field_id)
        ]
        self.area_combo.setLayer(find_layer_by_role(polygons, "HEADLAND"))
        boundary = find_layer_by_role(polygons, "EXTERNAL_BOUNDARY") or next(
            (layer for layer in polygons if is_field_boundary_layer_name(layer.name())), None
        )
        self.boundary_combo.setLayer(boundary)
        self.pass_combo.setExceptedLayerList(
            [layer for layer in QgsProject.instance().mapLayers().values() if is_turn_layer(layer)]
        )

    def _on_source_changed(self, *_args):
        source = self.source_combo.currentData()
        layer = self._pass_layer_for(source)
        if layer is not None:
            self.pass_combo.setLayer(layer)
        self._invalidate()
        if layer is None:
            self.status.setText(f"Nenhuma camada com role {source} no projeto; escolha em 'Passadas'.")

    def _blocking_reason(self) -> str | None:
        layer = self.pass_combo.currentLayer()
        if not isinstance(layer, QgsVectorLayer):
            return "Escolha a camada de passadas."
        if is_turn_layer(layer):
            return "A camada de passadas não pode ser a própria camada de manobras."
        if self.radius_spin.value() <= 0:
            return "Informe o raio mínimo de manobra da máquina."
        return None

    def _update_actions(self):
        reason = self._blocking_reason()
        self.preview_btn.setEnabled(reason is None)
        preview = QgsProject.instance().mapLayer(self.preview_layer_id or "")
        self.save_btn.setEnabled(reason is None and self.last_plan is not None and preview is not None)
        if reason:
            self.status.setText(reason)

    def _invalidate(self, *_args):
        if self.last_plan is not None:
            self.status.setText("Parâmetros alterados — pré-visualize novamente.")
        self.last_plan = None
        self._update_actions()

    # ------------------------------------------------------------ calculo ----
    @staticmethod
    def _metric_crs(layer):
        info = inspect_authid(layer.crs().authid())
        if not info.is_geographic:
            require_projected_metric(layer.crs().authid(), "manobras de cabeceira")
            return layer.crs()
        center = layer.extent().center()
        geographic = QgsCoordinateReferenceSystem("EPSG:4674")
        if layer.crs() != geographic:
            center = QgsCoordinateTransform(layer.crs(), geographic, QgsProject.instance()).transform(center)
        return QgsCoordinateReferenceSystem(suggest_sirgas_utm_epsg(center.x(), center.y()))

    @staticmethod
    def _transform(source_crs, target_crs):
        if source_crs == target_crs:
            return None
        return QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())

    def _geometries(self, layer, target_crs):
        transform = self._transform(layer.crs(), target_crs)
        for feature in layer.getFeatures():
            geometry = QgsGeometry(feature.geometry())
            if geometry.isNull() or geometry.isEmpty():
                continue
            if transform is not None:
                geometry.transform(transform)
            yield feature, geometry

    def _pass_records(self, layer, target_crs):
        names = layer.fields().names()
        number_field = line_number_field(names)
        id_field = line_id_field(names)
        segment_field = "segment_index" if "segment_index" in names else None
        layer_role_value = layer_role(layer)
        records = []
        for feature, geometry in self._geometries(layer, target_crs):
            attributes = dict(zip(names, feature.attributes()))
            if layer_role_value and not _as_text(attributes.get(ROLE_PROPERTY)):
                attributes[ROLE_PROPERTY] = layer_role_value
            number = _as_int(attributes.get(number_field)) if number_field else None
            line_id = _as_text(attributes.get(id_field)) if id_field else None
            segment = _as_int(attributes.get(segment_field)) if segment_field else None
            parts = geometry.asMultiPolyline() if geometry.isMultipart() else [geometry.asPolyline()]
            if len(parts) > 1:
                segment = None
                if line_id is None and number is None:
                    line_id = f"fid{feature.id()}"
            for part in parts:
                if len(part) >= 2:
                    records.append(PassRecord(
                        tuple((point.x(), point.y()) for point in part), line_id, number, segment, attributes,
                    ))
        return records

    def _union(self, layer, target_crs, *, point_buffer_m=0.0):
        shapes = []
        for _feature, geometry in self._geometries(layer, target_crs):
            shape = _to_shapely(geometry)
            if shape.geom_type in ("Point", "MultiPoint", "LineString", "MultiLineString"):
                shape = shape.buffer(point_buffer_m) if point_buffer_m > 0 else shape
            shapes.append(shape)
        return unary_union(shapes) if shapes else None

    def _turning_area(self, target_crs):
        if not self.keep_inside_check.isChecked():
            return None, "disabled"
        area_layer = self.area_combo.currentLayer()
        if isinstance(area_layer, QgsVectorLayer):
            return self._union(area_layer, target_crs), f"layer:{area_layer.name()}"
        boundary = self.boundary_combo.currentLayer()
        if not isinstance(boundary, QgsVectorLayer):
            return None, "none"
        area = self._union(boundary, target_crs)
        inner = find_layer_by_role(self._vector_layers(QgsWkbTypes.PolygonGeometry), "INTERNAL_BOUNDARY")
        if isinstance(inner, QgsVectorLayer) and area is not None:
            inner_shape = self._union(inner, target_crs)
            if inner_shape is not None:
                return area.difference(inner_shape), f"boundary-minus:{inner.name()}"
        return area, f"boundary:{boundary.name()}"

    def _obstacles(self, target_crs, settings):
        if not self.obstacles_check.isChecked():
            return None, []
        used, shapes = [], []
        pass_layer = self.pass_combo.currentLayer()
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer) or layer is pass_layer or is_turn_layer(layer):
                continue
            by_role = classify_layer(layer)[0] in OBSTACLE_ROLES
            by_name = obstacle_layer_priority(layer.name()) is not None
            if not (by_role or by_name):
                continue
            shape = self._union(layer, target_crs, point_buffer_m=settings.geometry_tolerance_m)
            if shape is not None and not shape.is_empty:
                shapes.append(shape)
                used.append(layer.name())
        return (unary_union(shapes) if shapes else None), used

    def _ab_heading(self, target_crs):
        ab = find_layer_by_role(self._vector_layers(QgsWkbTypes.LineGeometry), "AB_LINE")
        if not isinstance(ab, QgsVectorLayer):
            return None
        for _feature, geometry in self._geometries(ab, target_crs):
            parts = geometry.asMultiPolyline() if geometry.isMultipart() else [geometry.asPolyline()]
            if parts and len(parts[0]) >= 2:
                a, b = parts[0][0], parts[0][-1]
                return (b.x() - a.x(), b.y() - a.y())
        return None

    def _compute(self):
        layer = self.pass_combo.currentLayer()
        settings = TurnSettings(
            min_turn_radius_m=self.radius_spin.value(),
            mode=TurnMode(self.type_combo.currentData()),
            keep_inside=self.keep_inside_check.isChecked(),
            respect_direction=self.direction_check.isChecked(),
        )
        settings.validate()
        target_crs = self._metric_crs(layer)
        passes, number_source = build_logical_passes(self._pass_records(layer, target_crs))
        area, area_source = self._turning_area(target_crs)
        obstacles, obstacle_layers = self._obstacles(target_crs, settings)
        plan = plan_headland_turns(
            passes, settings, turning_area=area, obstacles=obstacles,
            ab_heading=self._ab_heading(target_crs), source_layer=layer.name(),
        )
        plan.report.update({
            "working_crs": target_crs.authid(),
            "line_number_source": number_source,
            "turning_area_source": area_source,
            "obstacle_layers": obstacle_layers,
        })
        return plan, target_crs

    # ------------------------------------------------------------- camadas ----
    def _turns_layer(self, plan, crs, name, source_name):
        layer = QgsVectorLayer(f"LineString?crs={crs.authid()}", name, "memory")
        layer.dataProvider().addAttributes(
            [QgsField(field_name, FIELD_TYPES[kind]) for field_name, kind in HEADLAND_TURN_FIELDS]
        )
        layer.updateFields()
        features = []
        for turn in plan.turns:
            feature = QgsFeature(layer.fields())
            values = turn.attributes(source_name)
            feature.setAttributes([values[field_name] for field_name, _kind in HEADLAND_TURN_FIELDS])
            if len(turn.points) >= 2:
                feature.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in turn.points]))
            features.append(feature)
        layer.dataProvider().addFeatures(features)
        layer.updateExtents()
        apply_qgis_layer_role(layer, HEADLAND_TURN_ROLE, field_name=self._field_name())
        self._style(layer)
        return layer

    @staticmethod
    def _style(layer):
        categories = []
        for status, (color, style, width) in STATUS_STYLE.items():
            symbol = QgsLineSymbol.createSimple({"line_color": color, "line_width": str(width), "line_style": style})
            categories.append(QgsRendererCategory(status, symbol, STATUS_LABELS[status]))
        layer.setRenderer(QgsCategorizedSymbolRenderer("status", categories))

    def _field_name(self):
        """Talhao da camada de passadas (grupo FORTSMART ou metadado), senao do limite."""
        layer = self.pass_combo.currentLayer()
        if layer is not None:
            owner = project_group_of(QgsProject.instance().layerTreeRoot(), layer)
            if owner is not None:
                return owner.name()
            if layer_field_id(layer):
                return layer_field_id(layer)
        boundary = self.boundary_combo.currentLayer()
        return boundary.name() if boundary is not None else None

    def _project_group(self, *, create=True):
        return project_group(QgsProject.instance().layerTreeRoot(), self._field_name(), create=create)

    def _remove_preview(self):
        project = QgsProject.instance()
        for layer in list(project.mapLayers().values()):
            if layer.customProperty(TURN_PREVIEW_PROPERTY, False):
                project.removeMapLayer(layer.id())
        self.preview_layer_id = None
        parent = self._project_group(create=False)
        if parent is not None:
            remove_group_if_empty(preview_group(parent, create=False))

    # --------------------------------------------------------------- acoes ----
    def preview(self):
        self._update_actions()
        if not self.preview_btn.isEnabled():
            return
        QgsSettings().setValue(SETTINGS_RADIUS, self.radius_spin.value())
        try:
            plan, crs = self._compute()
        except (HeadlandTurnError, CrsValidationError, ValueError) as exc:
            self.status.setText(f"Manobras não geradas: {exc}")
            self.status.setStyleSheet("QLabel { color: #b00020; }")
            return
        self.status.setStyleSheet("")
        self._remove_preview()
        source_name = self.pass_combo.currentLayer().name()
        layer = self._turns_layer(plan, crs, HEADLAND_TURN_ROLE.display_name + PREVIEW_SUFFIX, source_name)
        layer.setCustomProperty(TURN_PREVIEW_PROPERTY, True)
        mark_temporary_preview(layer)
        QgsProject.instance().addMapLayer(layer, False)
        preview_group(self._project_group()).addLayer(layer)
        self.pass_combo.setExceptedLayerList([layer])
        self.preview_layer_id = layer.id()
        self.last_plan = plan
        self.last_source_name = source_name
        self.status.setText(self._summary(plan.report))
        self._update_actions()
        canvas = self.iface.mapCanvas()
        if canvas is not None and not layer.extent().isEmpty():
            canvas.refresh()

    @staticmethod
    def _summary(report) -> str:
        counts = report.get("status_counts", {})
        parts = [f"{report['turn_count']} manobra(s) para {report['pass_count']} passada(s)"]
        parts += [f"{STATUS_LABELS[key]}: {counts[key]}" for key in STATUS_LABELS if counts.get(key)]
        parts.append(f"sentido: {report['direction_source']}")
        if report.get("border_passes_ignored"):
            parts.append(f"bordadura fora da sequência: {report['border_passes_ignored']}")
        text = " | ".join(parts)
        if counts.get(STATUS_INFEASIBLE_RADIUS) and report.get("turning_area_used"):
            text += (
                "\nPassadas que terminam na borda da área de manobra não têm espaço à frente "
                "para virar sem sair dela (as passadas não são encurtadas)."
            )
        return text

    def save(self):
        project = QgsProject.instance()
        preview = project.mapLayer(self.preview_layer_id or "")
        if self.last_plan is None or not isinstance(preview, QgsVectorLayer):
            self._update_actions()
            return
        name = HEADLAND_TURN_ROLE.display_name
        field_name = self._field_name()
        manager = FortSmartPersistenceManager(project)
        try:
            path = manager.get_field_storage_path(field_name)
            action = "create" if manager.table_feature_count(path, name) is None else "update"
            result = manager.persist_layer(preview, HEADLAND_TURN_ROLE, field_name)
        except PersistenceError as exc:
            QMessageBox.warning(self, "FortSmart Precision", str(exc))
            return
        saved = publish_persisted(
            project, preview, result.layer,
            reused=result.reused_layer, field_name=field_name, definition=HEADLAND_TURN_ROLE,
        )
        saved.removeCustomProperty(TURN_PREVIEW_PROPERTY)
        report = dict(self.last_plan.report)
        report.update({
            "saved_layer": name,
            "output_file": str(path),
            "storage": "geopackage",
            "save_action": action,
        })
        report_path = path.parent / f"{name}.validation.json"
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        self._remove_preview()
        self.last_plan = None
        self._update_actions()
        detail = f"\n{result.message}" if result.message else ""
        QMessageBox.information(
            self,
            "FortSmart Precision",
            f"Manobras salvas em '{name}' ({'atualizada' if action == 'update' else 'criada'})."
            f"{detail}\nArquivo: {path}\nRelatório: {report_path}",
        )

    def reject(self):
        self._remove_preview()
        super().reject()
