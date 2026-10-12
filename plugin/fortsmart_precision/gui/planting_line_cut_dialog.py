# -*- coding: utf-8 -*-
"""Ferramenta visual para interromper linhas em zonas de obstaculos."""

from __future__ import annotations

import json

from qgis.PyQt.QtCore import Qt, QVariant, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsFillSymbol,
    QgsGeometry,
    QgsLineSymbol,
    QgsMapLayerProxyModel,
    QgsMarkerSymbol,
    QgsPointXY,
    QgsProject,
    QgsRendererCategory,
    QgsSingleSymbolRenderer,
    QgsSpatialIndex,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgsMapLayerComboBox

from ..core.crs import inspect_authid, require_projected_metric, suggest_sirgas_utm_epsg
from ..core.obstacle_border_pass_engine import preview_footer_lines, preview_footer_status
from ..core.preview_layer_names import unique_layer_name
from ..core.layer_roles import (
    PREVIEW_SECTION,
    LayerRoleDefinition,
    apply_qgis_layer_role,
    find_layer_by_role,
    mark_temporary_preview,
    simulation_role_definition,
)
from ..core.persistence_manager import FortSmartPersistenceManager, PersistenceError
from .layer_tree_organizer import (
    preview_group,
    project_group,
    publish_persisted,
    remove_group_if_empty,
)
from ..core.planting_line_cut_engine import (
    GEOMETRY_INCOMPLETE,
    PlantingLineCutError,
    calculate_safety_radius,
    cut_polyline_by_zones,
    is_field_boundary_layer_name,
    is_obstacle_layer_name,
    is_safety_zone_layer_name,
    line_id_field,
    line_id_for,
    line_number_field,
    obstacle_layer_priority,
    spatial_line_numbers,
    validate_line_layer_choice,
    validate_obstacle_layer_choice,
)
from .geometry_bridge import qgs_geometry_to_multipolygon
from .lateral_detour_preview import (
    BEHAVIOR as LATERAL_BEHAVIOR,
    PREVIEW_DEFINITIONS as LATERAL_PREVIEW_DEFINITIONS,
    PREVIEW_ORDER as LATERAL_PREVIEW_ORDER,
    LateralDetourPreviewBuilder,
    restore_role_layers,
    save_outputs as lateral_save_outputs,
    snapshot_role_layers,
    style_preview_layer,
)
from .lateral_detour_widget import ObstacleTreatmentBox
from .machine_work_geometry_widget import MachineWorkGeometryBox

SIM_GROUP_NAME = PREVIEW_SECTION
# Uma unica representacao das linhas no preview (a camada cortada); a
# trajetoria da maquina/barra continua disponivel so no Processing.
SIM_OUTPUTS = (
    # chave, nome no painel, visivel
    ("SIM_WORK_LINES", "Linhas cortadas", True),
    ("SIM_WORK_OFF_ON", "WORK_OFF / WORK_ON", True),
    ("SIM_BORDER_PASS", "Bordadura planejada", True),
    ("SIM_BORDER_GAPS", "Falha da bordadura", True),
    ("SIM_BORDER_OVERLAPS", "Sobreposicao", False),
    ("SIM_SAFETY_ZONE", "Zona de seguranca do obstaculo", True),
    ("SIM_UNWORKED_BORDER", "Trecho sem operacao", True),
    ("SIM_BORDER_COVERAGE", "Faixa varrida pela bordadura", False),
    ("SIM_MAIN_WORK_AREA", "Faixa real do implemento", False),
)
LINE_LABEL_EXPRESSION = 'if("segment_index" = 1 or "segment_index" is null, "line_number", NULL)'
LINE_PLAN_ROLES = ("WORK_PATH", "GUIDANCE_TRACK")
# Preview do dialogo de linhas agricolas: ainda sem role proprio.
LINE_PLAN_FALLBACK_NAMES = ("Linhas_Agricolas",)


def _geometry_kind(layer) -> str:
    return {
        QgsWkbTypes.PointGeometry: "point",
        QgsWkbTypes.LineGeometry: "line",
        QgsWkbTypes.PolygonGeometry: "polygon",
    }.get(layer.geometryType(), "unknown")


def is_obstacle_layer(layer) -> bool:
    """Camada candidata a obstaculo: nome reconhecido e nunca o Boundary do talhao."""
    if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
        return False
    if _geometry_kind(layer) == "unknown":
        return False
    return obstacle_layer_priority(layer.name()) is not None


class PlantingLineCutDialog(QDialog):
    """Corta linhas existentes antes/depois de postes e outros obstaculos."""

    resultSaved = pyqtSignal(object)

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.safe_layer_id = None
        self.zone_layer_id = None
        self.source_layer_id = None
        self.source_layer_was_visible = True
        self.saved_layer_id = None
        self.last_report = None
        self.sim_layer_ids = []
        self.sim_layers_by_key = {}
        self.preview_valid = False
        self.undo_snapshot = None
        self.setWindowTitle("Cortar linhas por obstaculos")
        self.setMinimumSize(620, 480)
        self._build_ui()
        self._fit_to_available_screen()
        self._select_project_layers()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.content_scroll = QScrollArea(self)
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setFrameShape(QFrame.NoFrame)
        self.content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        content = QWidget(self.content_scroll)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(2, 2, 6, 2)
        content_layout.setSpacing(6)
        self.content_scroll.setWidget(content)
        layout.addWidget(self.content_scroll, 1)

        intro = QLabel(
            "Usa as linhas ja geradas: cada linha mantem geometria, atributos e numero, "
            "e perde somente o trecho que entra na zona do obstaculo. Nada e regerado "
            "nem recortado pelo talhao. As camadas originais nao sao alteradas."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(
            "QLabel { background: #eef4fb; border: 1px solid #c8d9ee; "
            "border-radius: 4px; padding: 6px 8px; color: #20364d; }"
        )
        content_layout.addWidget(intro)

        form = QFormLayout()
        form.setContentsMargins(4, 2, 4, 2)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(4)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.lines_combo = QgsMapLayerComboBox()
        self.lines_combo.setFilters(QgsMapLayerProxyModel.LineLayer)
        form.addRow("Linhas geradas:", self.lines_combo)

        self.field_combo = QgsMapLayerComboBox()
        self.field_combo.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        form.addRow("Talhao:", self.field_combo)

        self.obstacle_combo = QgsMapLayerComboBox()
        self.obstacle_combo.setFilters(QgsMapLayerProxyModel.VectorLayer)
        self.obstacle_combo.setAllowEmptyLayer(True)
        self.obstacle_combo.setLayer(None)
        form.addRow("Postes / obstaculos:", self.obstacle_combo)

        self.selected_lines_check = QCheckBox("Usar somente linhas selecionadas, quando houver")
        self.selected_lines_check.setChecked(False)
        form.addRow(self.selected_lines_check)

        self.selected_obstacles_check = QCheckBox(
            "Usar somente obstaculos selecionados, quando houver"
        )
        self.selected_obstacles_check.setChecked(False)
        form.addRow(self.selected_obstacles_check)

        self.show_numbers_check = QCheckBox("Mostrar numeração das linhas (um número por linha)")
        self.show_numbers_check.setChecked(True)
        form.addRow(self.show_numbers_check)

        self.radius_method = QComboBox()
        self.radius_method.addItem("Meia largura + raio do poste + margem", "half_width_margin")
        self.radius_method.addItem("Raio manual", "manual")
        form.addRow("Distância lateral de segurança:", self.radius_method)

        self.manual_radius = QDoubleSpinBox()
        self.manual_radius.setRange(0.01, 200.0)
        self.manual_radius.setDecimals(2)
        self.manual_radius.setValue(10.0)
        self.manual_radius.setSuffix(" m")
        form.addRow("Raio manual:", self.manual_radius)

        self.implement_width = QDoubleSpinBox()
        self.implement_width.setRange(0.01, 200.0)
        self.implement_width.setDecimals(2)
        self.implement_width.setValue(20.0)
        self.implement_width.setSuffix(" m")
        form.addRow("Largura do implemento:", self.implement_width)

        self.obstacle_radius = QDoubleSpinBox()
        self.obstacle_radius.setRange(0.0, 100.0)
        self.obstacle_radius.setDecimals(2)
        self.obstacle_radius.setValue(0.0)
        self.obstacle_radius.setSuffix(" m")
        form.addRow("Raio fisico do poste:", self.obstacle_radius)

        self.safety_margin = QDoubleSpinBox()
        self.safety_margin.setRange(0.0, 100.0)
        self.safety_margin.setDecimals(2)
        self.safety_margin.setValue(1.0)
        self.safety_margin.setSuffix(" m")
        form.addRow("Margem adicional:", self.safety_margin)

        self.effective_radius = QLabel("")
        self.effective_radius.setWordWrap(True)
        form.addRow("Resultado:", self.effective_radius)
        content_layout.addLayout(form)
        self._form = form

        self.treatment_box = ObstacleTreatmentBox(self)
        content_layout.addWidget(self.treatment_box)

        self.work_geometry_box = MachineWorkGeometryBox(self)
        content_layout.addWidget(self.work_geometry_box)
        content_layout.addStretch(1)

        self.status = QLabel("Selecione as camadas e confira a distancia.")
        self.status.setWordWrap(True)
        self.status.setMaximumHeight(44)
        layout.addWidget(self.status)

        self.footer = QLabel("")
        self.footer.setWordWrap(True)
        self.footer.setMaximumHeight(70)
        self.footer.setStyleSheet("QLabel { border-top: 1px solid #bbb; padding-top: 4px; }")
        self.footer.setVisible(False)
        layout.addWidget(self.footer)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.preview_btn = QPushButton("Pre-visualizar corte")
        self.save_btn = QPushButton("Salvar resultado")
        self.save_btn.setEnabled(False)
        self.undo_btn = QPushButton("Desfazer desvio")
        self.undo_btn.setVisible(False)
        self.close_btn = QPushButton("Fechar")
        actions.addWidget(self.preview_btn)
        actions.addWidget(self.save_btn)
        actions.addWidget(self.undo_btn)
        actions.addStretch(1)
        actions.addWidget(self.close_btn)
        layout.addLayout(actions)

        self.work_geometry_box.changed.connect(self._refresh_radius)
        self.radius_method.currentIndexChanged.connect(self._refresh_radius)
        self.manual_radius.valueChanged.connect(self._refresh_radius)
        self.implement_width.valueChanged.connect(self._refresh_radius)
        self.obstacle_radius.valueChanged.connect(self._refresh_radius)
        self.safety_margin.valueChanged.connect(self._refresh_radius)
        for combo in (self.lines_combo, self.field_combo, self.obstacle_combo):
            combo.layerChanged.connect(self._on_inputs_changed)
        for check in (self.selected_lines_check, self.selected_obstacles_check):
            check.toggled.connect(self._on_inputs_changed)
        self.show_numbers_check.toggled.connect(self._refresh_line_labels)
        self.preview_btn.clicked.connect(self.preview)
        self.save_btn.clicked.connect(self.save)
        self.undo_btn.clicked.connect(self.undo_lateral_detour)
        self.close_btn.clicked.connect(self.reject)
        self.treatment_box.changed.connect(self._on_treatment_changed)
        self._refresh_radius()

    def _fit_to_available_screen(self):
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            self.resize(760, 700)
            return
        available = screen.availableGeometry()
        width = min(820, max(620, int(available.width() * 0.72)))
        height = min(760, max(480, int(available.height() * 0.82)))
        self.resize(width, height)

    def _lateral_mode(self) -> bool:
        box = getattr(self, "treatment_box", None)
        return box is not None and box.is_lateral()

    def _on_treatment_changed(self):
        lateral = self._lateral_mode()
        for widget in (self.radius_method, self.manual_radius, self.implement_width, self.safety_margin):
            widget.setVisible(not lateral)
            label = self._form.labelForField(widget)
            if label is not None:
                label.setVisible(not lateral)
        self.work_geometry_box.setVisible(not lateral)
        self.preview_btn.setText("Pre-visualizar desvio" if lateral else "Pre-visualizar corte")
        self._refresh_radius()

    def _select_project_layers(self):
        active = self.iface.activeLayer()
        line_layers = [
            layer for layer in QgsProject.instance().mapLayers().values()
            if isinstance(layer, QgsVectorLayer) and layer.geometryType() == QgsWkbTypes.LineGeometry
        ]
        plan = find_layer_by_role(
            line_layers, *LINE_PLAN_ROLES, names=LINE_PLAN_FALLBACK_NAMES, non_empty=True
        )
        if isinstance(active, QgsVectorLayer):
            if active.geometryType() == QgsWkbTypes.LineGeometry and not is_obstacle_layer(active):
                self.lines_combo.setLayer(active)
                plan = None
            elif active.geometryType() == QgsWkbTypes.PolygonGeometry:
                self.field_combo.setLayer(active)
        if isinstance(plan, QgsVectorLayer) and plan.geometryType() == QgsWkbTypes.LineGeometry:
            self.lines_combo.setLayer(plan)
        candidates = []
        for layer in QgsProject.instance().mapLayers().values():
            if is_obstacle_layer(layer):
                candidates.append((obstacle_layer_priority(layer.name()), layer.name(), layer))
            elif (
                isinstance(layer, QgsVectorLayer)
                and layer.isValid()
                and is_obstacle_layer_name(layer.name())
                and not is_field_boundary_layer_name(layer.name())
                and not is_safety_zone_layer_name(layer.name())
            ):
                candidates.append((9, layer.name(), layer))
        if candidates:
            self.obstacle_combo.setLayer(min(candidates, key=lambda item: (item[0], item[1]))[2])

    def obstacle_layer_error(self):
        obstacles = self.obstacle_combo.currentLayer()
        field = self.field_combo.currentLayer()
        lines = self.lines_combo.currentLayer()
        if not isinstance(obstacles, QgsVectorLayer) or not obstacles.isValid():
            return "Selecione a camada de obstáculos."
        line_error = validate_line_layer_choice(
            line_layer_id=lines.id() if isinstance(lines, QgsVectorLayer) else None,
            obstacle_layer_id=obstacles.id(),
            line_layer_name=lines.name() if isinstance(lines, QgsVectorLayer) else "",
        )
        if line_error:
            return line_error
        return validate_obstacle_layer_choice(
            obstacle_layer_id=obstacles.id(),
            obstacle_layer_name=obstacles.name(),
            field_layer_id=field.id() if isinstance(field, QgsVectorLayer) else None,
            geometry_kind=_geometry_kind(obstacles),
        )

    def _on_inputs_changed(self, *_args):
        self._invalidate_preview()
        self._update_actions()

    def _invalidate_preview(self):
        if self.preview_valid:
            self.status.setText("Parâmetros alterados: pré-visualize o corte novamente.")
        self.preview_valid = False
        self.save_btn.setEnabled(False)

    def _update_actions(self):
        readiness, message = self.work_geometry_box.readiness()
        if self._lateral_mode():
            blocked = self.treatment_box.config_error(self.obstacle_radius.value()) or self.obstacle_layer_error()
        else:
            blocked = f"{GEOMETRY_INCOMPLETE}: {message}" if readiness == GEOMETRY_INCOMPLETE \
                else self.obstacle_layer_error()
        self.preview_btn.setEnabled(blocked is None)
        self.save_btn.setEnabled(self.preview_valid and blocked is None)
        if blocked:
            self.status.setText(blocked)
            self.status.setStyleSheet("QLabel { color: #b00020; }")
            self.status_blocking = True
            return
        if getattr(self, "status_blocking", False):
            self.status.setStyleSheet("")
            self.status.setText("Pronto para pré-visualizar o corte.")
        self.status_blocking = False

    def _refresh_radius(self, *_args):
        if self._lateral_mode():
            self._invalidate_preview()
            self._update_actions()
            self.obstacle_radius.setEnabled(True)
            self.effective_radius.setText(self.treatment_box.summary(self.obstacle_radius.value()))
            return
        self.work_geometry_box.refresh_schematic(self.implement_width.value())
        longitudinal = self.work_geometry_box.is_longitudinal()
        self.radius_method.setEnabled(not longitudinal)
        self._invalidate_preview()
        self._update_actions()
        if longitudinal:
            self.manual_radius.setEnabled(False)
            self.obstacle_radius.setEnabled(True)
            self.safety_margin.setEnabled(True)
            half = self.implement_width.value() / 2.0
            radius = self.obstacle_radius.value()
            margin = self.safety_margin.value()
            reach = half + radius + margin
            geometry = self.work_geometry_box.work_geometry(self.implement_width.value())
            try:
                border = f"{geometry.desired_border_width_m():.2f} m"
            except ValueError as exc:
                border = str(exc)
            self.effective_radius.setText(
                f"Transversal: meia largura {half:.2f} + raio {radius:.2f} + "
                f"margem {margin:.2f} = {reach:.2f} m (colisão lateral).\n"
                f"Longitudinal: zona = raio {radius:.2f} + margem {margin:.2f} = {radius + margin:.2f} m; "
                f"a última linha ativa desliga {geometry.longitudinal_anticipation_m:.2f} m antes de entrar "
                f"na zona (antecipação) e religa ao sair. Largura, espaçamento e bordadura não entram.\n"
                f"Bordadura do obstáculo: faixa lateral de {border} (passada de contorno)."
            )
            return
        manual = self.radius_method.currentData() == "manual"
        self.manual_radius.setEnabled(manual)
        self.obstacle_radius.setEnabled(not manual)
        self.safety_margin.setEnabled(not manual)
        try:
            radius = self._radius()
        except PlantingLineCutError as exc:
            self.effective_radius.setText(str(exc))
            return
        if manual:
            self.effective_radius.setText(f"Raio manual = {radius:.2f} m")
            return
        self.effective_radius.setText(
            f"Meia largura {self.implement_width.value() / 2.0:.2f} m + "
            f"poste {self.obstacle_radius.value():.2f} m + margem "
            f"{self.safety_margin.value():.2f} m = {radius:.2f} m"
        )

    def _radius(self):
        return calculate_safety_radius(
            method=self.radius_method.currentData(),
            manual_radius_m=self.manual_radius.value(),
            implement_width_m=self.implement_width.value(),
            safety_margin_m=self.safety_margin.value(),
            obstacle_radius_m=self.obstacle_radius.value(),
        )

    def preview(self):
        self._update_actions()
        if not self.preview_btn.isEnabled():
            if self.work_geometry_box.readiness()[0] == GEOMETRY_INCOMPLETE:
                self.work_geometry_box.offset_spin.setFocus()
            return
        self.footer.setVisible(False)
        if self._lateral_mode():
            self._preview_lateral_detour()
            return
        if self.work_geometry_box.is_longitudinal():
            self._preview_longitudinal()
            return
        try:
            safe_layer, zone_layer, report = self._build_result()
        except Exception as exc:
            QMessageBox.critical(self, "FortSmart Precision", str(exc))
            return
        self._remove_preview()
        source_layer = self.lines_combo.currentLayer()
        if isinstance(source_layer, QgsVectorLayer):
            self.source_layer_id = source_layer.id()
            source_node = QgsProject.instance().layerTreeRoot().findLayer(source_layer.id())
            if source_node is not None:
                self.source_layer_was_visible = source_node.isVisible()
                source_node.setItemVisibilityChecked(False)
        safe_definition = simulation_role_definition("SIM_WORK_LINES")
        zone_definition = simulation_role_definition("SIM_SAFETY_ZONE")
        safe_layer.setName(safe_definition.display_name)
        zone_layer.setName(zone_definition.display_name)
        for layer, definition in ((safe_layer, safe_definition), (zone_layer, zone_definition)):
            apply_qgis_layer_role(layer, definition, field_name=self._field_name())
            mark_temporary_preview(layer)
        project = QgsProject.instance()
        group = self._simulation_group()
        project.addMapLayer(zone_layer, False)
        project.addMapLayer(safe_layer, False)
        group.addLayer(zone_layer).setItemVisibilityChecked(True)
        group.addLayer(safe_layer).setItemVisibilityChecked(True)
        self._apply_line_labels(safe_layer)
        self.zone_layer_id = zone_layer.id()
        self.safe_layer_id = safe_layer.id()
        self.last_report = report
        self.preview_valid = True
        self.save_btn.setEnabled(True)
        self.status.setText(
            f"{report['output_logical_line_count']} linha(s) — mesma numeração | "
            f"{report['cut_line_count']} cortada(s) | "
            f"{report['output_segment_count']} segmento(s) | "
            f"{report['obstacle_count']} obstáculo(s) ({report['obstacles_inside_field']} no talhão) | "
            f"raio {report['effective_radius_m']:.2f} m."
        )
        self.iface.mapCanvas().setExtent(safe_layer.extent())
        self.iface.mapCanvas().refresh()

    def _preview_longitudinal(self):
        lines = self.lines_combo.currentLayer()
        field = self.field_combo.currentLayer()
        obstacles = self.obstacle_combo.currentLayer()
        geometry = self.work_geometry_box.work_geometry(self.implement_width.value())
        if not isinstance(lines, QgsVectorLayer) or lines.geometryType() != QgsWkbTypes.LineGeometry:
            QMessageBox.warning(self, "FortSmart Precision", "Selecione a camada de linhas geradas.")
            return
        if not isinstance(field, QgsVectorLayer) or field.geometryType() != QgsWkbTypes.PolygonGeometry:
            QMessageBox.warning(self, "FortSmart Precision", "Selecione a camada poligonal do talhao.")
            return
        error = self.obstacle_layer_error()
        if error:
            QMessageBox.warning(self, "FortSmart Precision", error)
            return

        import processing
        from qgis.core import QgsProcessingFeatureSourceDefinition

        try:
            target_crs = self._metric_crs(field)
        except Exception as exc:
            QMessageBox.critical(self, "FortSmart Precision", str(exc))
            return

        def source(layer, use_selected):
            if use_selected and layer.selectedFeatureCount() > 0:
                return QgsProcessingFeatureSourceDefinition(layer.id(), True)
            return layer

        strategy = self.work_geometry_box.strategy_key()
        border_modes = ["ONE_IMPLEMENT_PASS", "CUSTOM", "NONE"]
        params = {
            "PASSES": self._lines_in_crs(lines, target_crs)
            if lines.crs() != target_crs else source(lines, self.selected_lines_check.isChecked()),
            "FIELD": field,
            "OBSTACLES": source(obstacles, self.selected_obstacles_check.isChecked()),
            "WORK_WIDTH": geometry.work_width_m,
            "REFERENCE_TYPE": [item.value for item in type(geometry.reference_type)].index(
                geometry.reference_type.value
            ),
            "WORKING_OFFSET": geometry.reference_to_working_line_longitudinal_m,
            "BORDER_MODE": border_modes.index(geometry.border_mode.value),
            "BORDER_WIDTH": geometry.obstacle_border_width_m,
            "STRATEGY": 0 if strategy == "CUT_FOR_BORDER" else 1,
            "OBSTACLE_RADIUS": self.obstacle_radius.value(),
            "SAFETY_MARGIN": self.safety_margin.value(),
            "LATERAL_MARGIN": geometry.safety_margin_lateral_m,
            "ANTICIPATION": geometry.longitudinal_anticipation_m,
            "TOLERANCE": 0.05,
            "GROUP": True,
        }
        for key, _name, _visible in SIM_OUTPUTS:
            params[key] = "TEMPORARY_OUTPUT"
        self._remove_preview()
        self.status.setStyleSheet("")
        self.status.setText("Simulando corte pela última linha ativa...")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            result = processing.run("fortsmart_precision:simulate_obstacle_border_cut", params)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            self.status.setText(f"Corte não gerado: {exc}")
            self.status.setStyleSheet("QLabel { color: #b00020; }")
            QMessageBox.critical(self, "FortSmart Precision", str(exc))
            return
        QApplication.restoreOverrideCursor()
        self._load_simulation_layers(result, lines)

        report = json.loads(result.get("REPORT") or "{}")
        self.last_report = report
        footer_status = preview_footer_status(report)
        self.preview_valid = footer_status != "INVALID"
        self.save_btn.setEnabled(self.preview_valid)
        cut_lines = self.sim_layers_by_key.get("SIM_WORK_LINES")
        ignored = report.get("ignored_obstacle_features", 0)
        self.status.setText(
            f"{report.get('output_logical_line_count', 0)} linha(s) — mesma numeração | "
            f"{report.get('cut_line_count', 0)} cortada(s) | "
            f"{report.get('output_segment_count', 0)} segmento(s) | "
            f"numeração: {report.get('line_number_source', '-')} | "
            f"{report.get('obstacle_count', 0)} obstáculo(s)"
            + (f" ({ignored} sem geometria ignorado(s))" if ignored else "")
            + (f" | avisos: {', '.join(report.get('warnings', []))}" if report.get("warnings") else "")
            + (f" | ERROS: {', '.join(report.get('errors', []))}" if report.get("errors") else "")
        )
        self.status.setStyleSheet("QLabel { color: #b00020; }" if footer_status == "INVALID" else "")
        self.footer.setText(" | ".join(preview_footer_lines(report)))
        self.footer.setVisible(True)
        if cut_lines is not None and not cut_lines.extent().isEmpty():
            self.iface.mapCanvas().setExtent(cut_lines.extent())
        self.iface.mapCanvas().refresh()

    def _preview_lateral_detour(self):
        config = self.treatment_box.config(self.obstacle_radius.value())
        self._remove_preview()
        self.status.setStyleSheet("")
        self.status.setText("Calculando desvio lateral na trajetória mestra...")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            layers, report = LateralDetourPreviewBuilder(self, config).build()
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            self.status.setText(f"Desvio não gerado: {exc}")
            self.status.setStyleSheet("QLabel { color: #b00020; }")
            QMessageBox.critical(self, "FortSmart Precision", str(exc))
            return
        QApplication.restoreOverrideCursor()

        project = QgsProject.instance()
        group = self._simulation_group()
        for key, visible in LATERAL_PREVIEW_ORDER:
            layer = layers.get(key)
            if not isinstance(layer, QgsVectorLayer):
                continue
            apply_qgis_layer_role(layer, LATERAL_PREVIEW_DEFINITIONS[key], field_name=self._field_name())
            mark_temporary_preview(layer)
            style_preview_layer(key, layer)
            if key == "SIM_WORK_LINES":
                self._apply_line_labels(layer)
            project.addMapLayer(layer, False)
            group.addLayer(layer).setItemVisibilityChecked(visible)
            self.sim_layer_ids.append(layer.id())
            self.sim_layers_by_key[key] = layer
        source_layer = self.lines_combo.currentLayer()
        if isinstance(source_layer, QgsVectorLayer):
            self.source_layer_id = source_layer.id()
            source_node = project.layerTreeRoot().findLayer(source_layer.id())
            if source_node is not None:
                self.source_layer_was_visible = source_node.isVisible()
                source_node.setItemVisibilityChecked(False)

        self.last_report = report
        self.preview_valid = not report["errors"]
        self.save_btn.setEnabled(self.preview_valid)
        self.status.setText(
            f"{report['output_logical_line_count']} linha(s) | {report['detoured_count']} desviada(s) | "
            f"{report['no_conflict_count']} sem conflito | {report['fallback_count']} cortada(s) por fallback | "
            f"largura {report['machine_width_m']:.2f} m | raio efetivo {report['required_radius_m']:.2f} m"
            + (f" | ERROS: {'; '.join(report['errors'][:3])}" if report["errors"] else "")
        )
        self.status.setStyleSheet("QLabel { color: #b00020; }" if report["errors"] else "")
        master = layers.get("SIM_WORK_LINES")
        if isinstance(master, QgsVectorLayer) and not master.extent().isEmpty():
            self.iface.mapCanvas().setExtent(master.extent())
        self.iface.mapCanvas().refresh()

    def _save_lateral_detour(self):
        project = QgsProject.instance()
        manager = FortSmartPersistenceManager(project)
        field_name = self._field_name()
        try:
            path = manager.get_field_storage_path(field_name)
        except PersistenceError as exc:
            QMessageBox.warning(self, "FortSmart Precision", str(exc))
            return
        outputs = [
            (self.sim_layers_by_key.get(key), definition, allow_empty)
            for key, definition, allow_empty in lateral_save_outputs()
        ]
        outputs = [item for item in outputs if isinstance(item[0], QgsVectorLayer) and item[0].isValid()]
        snapshot = snapshot_role_layers(manager, field_name, [definition for _layer, definition, _empty in outputs])
        stored = []
        try:
            for output_layer, definition, allow_empty in outputs:
                result = manager.persist_layer(output_layer, definition, field_name, allow_empty=allow_empty)
                stored.append((output_layer, definition, result))
        except PersistenceError as exc:
            restore_role_layers(project, manager, field_name, snapshot[: len(stored)], publish_persisted)
            QMessageBox.critical(self, "FortSmart Precision", str(exc))
            return
        saved_names = [definition.display_name for _layer, definition, _result in stored]
        report = dict(self.last_report)
        report.update({"saved_layers": saved_names, "output_file": str(path), "storage": "geopackage"})
        report_path = path.parent / f"{saved_names[0]}.validation.json"
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        for output_layer, definition, result in stored:
            saved = publish_persisted(
                project, output_layer, result.layer,
                reused=result.reused_layer, field_name=field_name, definition=definition,
            )
            if definition.role == "FINAL_WORK_PATH":
                if not result.reused_layer:
                    self._apply_line_labels(saved)
                self.saved_layer_id = saved.id()
        self.undo_snapshot = (field_name, snapshot)
        self.undo_btn.setVisible(True)
        self.preview_valid = False
        self._remove_preview(restore_source=False)
        self.resultSaved.emit(saved_names)
        self._update_actions()
        listing = "\n".join(f"- {name}" for name in saved_names)
        QMessageBox.information(
            self,
            "FortSmart Precision",
            f"Desvio lateral salvo:\n{listing}\nArquivo: {path}\nRelatorio: {report_path}\n"
            "Use 'Desfazer desvio' para voltar ao estado anterior.",
        )

    def undo_lateral_detour(self):
        if not self.undo_snapshot:
            return
        field_name, snapshot = self.undo_snapshot
        project = QgsProject.instance()
        manager = FortSmartPersistenceManager(project)
        try:
            restored = restore_role_layers(project, manager, field_name, snapshot, publish_persisted)
        except PersistenceError as exc:
            QMessageBox.critical(self, "FortSmart Precision", str(exc))
            return
        self.undo_snapshot = None
        self.undo_btn.setVisible(False)
        self.iface.mapCanvas().refresh()
        QMessageBox.information(
            self, "FortSmart Precision", "Desvio desfeito:\n" + "\n".join(f"- {item}" for item in restored)
        )

    def _lines_in_crs(self, lines, target_crs):
        """Copia metrica das passadas; a camada original nao e alterada."""
        use_selected = self.selected_lines_check.isChecked() and lines.selectedFeatureCount() > 0
        features = lines.selectedFeatures() if use_selected else lines.getFeatures()
        copy = QgsVectorLayer(f"MultiLineString?crs={target_crs.authid()}", lines.name(), "memory")
        copy.dataProvider().addAttributes(list(lines.fields()))
        copy.updateFields()
        transform = self._transform(lines.crs(), target_crs)
        output = []
        for feature in features:
            geometry = QgsGeometry(feature.geometry())
            if geometry.isNull() or geometry.isEmpty():
                continue
            if transform is not None:
                geometry.transform(transform)
            item = QgsFeature(copy.fields())
            item.setAttributes(feature.attributes())
            item.setGeometry(geometry)
            output.append(item)
        copy.dataProvider().addFeatures(output)
        copy.updateExtents()
        return copy

    def _load_simulation_layers(self, result, source_layer):
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        group = self._simulation_group()
        for key, name, visible in SIM_OUTPUTS:
            layer = result.get(key)
            if isinstance(layer, str):
                layer = project.mapLayer(layer) or QgsVectorLayer(layer, name, "ogr")
            if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                continue
            output_layers = (
                self._split_work_events(layer)
                if key == "SIM_WORK_OFF_ON"
                else [(key, layer)]
            )
            for output_key, output_layer in output_layers:
                definition = simulation_role_definition(output_key)
                output_layer.setName(definition.display_name)
                apply_qgis_layer_role(output_layer, definition, field_name=self._field_name())
                mark_temporary_preview(output_layer)
                self._style_simulation_layer(output_key, output_layer)
                if output_key == "SIM_WORK_LINES":
                    self._apply_line_labels(output_layer)
                project.addMapLayer(output_layer, False)
                node = group.addLayer(output_layer)
                node.setItemVisibilityChecked(visible)
                self.sim_layer_ids.append(output_layer.id())
                self.sim_layers_by_key[output_key] = output_layer
        if isinstance(source_layer, QgsVectorLayer):
            self.source_layer_id = source_layer.id()
            source_node = root.findLayer(source_layer.id())
            if source_node is not None:
                self.source_layer_was_visible = source_node.isVisible()
                source_node.setItemVisibilityChecked(False)

    def _result_layer_name(self, source_layer) -> str:
        return simulation_role_definition("SIM_WORK_LINES").display_name

    def _field_name(self):
        field = self.field_combo.currentLayer()
        return field.name() if field is not None else None

    def _project_group(self, *, create=True):
        return project_group(QgsProject.instance().layerTreeRoot(), self._field_name(), create=create)

    @staticmethod
    def _direct_child_group(parent, name):
        return next(
            (
                child for child in parent.children()
                if hasattr(child, "name") and child.name() == name
            ),
            None,
        )

    def _simulation_group(self):
        return preview_group(self._project_group())

    @staticmethod
    def _split_work_events(layer):
        """Materializa OFF e ON separadamente para exportacao sem adivinhar categoria."""
        outputs = []
        event_index = layer.fields().indexFromName("event")
        if event_index < 0:
            return outputs
        for event, key in (("WORK_OFF", "SIM_WORK_OFF"), ("WORK_ON", "SIM_WORK_ON")):
            definition = simulation_role_definition(key)
            geometry_name = QgsWkbTypes.displayString(layer.wkbType())
            copy = QgsVectorLayer(
                f"{geometry_name}?crs={layer.crs().authid()}",
                definition.display_name,
                "memory",
            )
            copy.dataProvider().addAttributes(list(layer.fields()))
            copy.updateFields()
            features = []
            for source in layer.getFeatures():
                if str(source[event_index]) != event:
                    continue
                feature = QgsFeature(copy.fields())
                feature.setGeometry(QgsGeometry(source.geometry()))
                feature.setAttributes(source.attributes())
                features.append(feature)
            copy.dataProvider().addFeatures(features)
            copy.updateExtents()
            outputs.append((key, copy))
        return outputs

    def _apply_line_labels(self, layer):
        """Numero da linha uma unica vez (primeiro segmento), nunca por trecho."""
        from qgis.core import QgsPalLayerSettings, QgsTextFormat, QgsVectorLayerSimpleLabeling

        if not isinstance(layer, QgsVectorLayer) or "line_number" not in layer.fields().names():
            return
        settings = QgsPalLayerSettings()
        settings.fieldName = LINE_LABEL_EXPRESSION
        settings.isExpression = True
        try:
            settings.placement = QgsPalLayerSettings.Line
        except AttributeError:
            pass
        text = QgsTextFormat()
        text.setColor(QColor(0, 90, 0))
        text.setSize(9)
        settings.setFormat(text)
        layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
        layer.setLabelsEnabled(self.show_numbers_check.isChecked())
        layer.triggerRepaint()

    def _refresh_line_labels(self, *_args):
        for layer_id in [self.safe_layer_id, *self.sim_layer_ids]:
            layer = QgsProject.instance().mapLayer(layer_id) if layer_id else None
            if isinstance(layer, QgsVectorLayer) and layer.labeling() is not None:
                layer.setLabelsEnabled(self.show_numbers_check.isChecked())
                layer.triggerRepaint()

    @staticmethod
    def _style_simulation_layer(key, layer):
        def line(color, width, style="solid"):
            return QgsLineSymbol.createSimple({"line_color": color, "line_width": str(width), "line_style": style})

        def fill(color, outline="0,0,0,0"):
            return QgsFillSymbol.createSimple({"color": color, "outline_color": outline, "outline_width": "0.2"})

        symbols = {
            "SIM_WORK_LINES": line("30,170,70", 0.9),
            "SIM_BORDER_PASS": line("20,90,220", 0.8),
            "SIM_SAFETY_ZONE": fill("220,40,40,90", "200,30,30,255"),
            "SIM_UNWORKED_BORDER": fill("255,150,30,90"),
            "SIM_BORDER_COVERAGE": fill("20,90,220,60"),
            "SIM_BORDER_GAPS": fill("220,0,200,150"),
            "SIM_BORDER_OVERLAPS": fill("250,220,0,120"),
            "SIM_MAIN_WORK_AREA": fill("30,170,70,50"),
        }
        if key in ("SIM_WORK_OFF_ON", "SIM_WORK_OFF", "SIM_WORK_ON"):
            if key == "SIM_WORK_OFF":
                layer.setRenderer(QgsSingleSymbolRenderer(
                    QgsMarkerSymbol.createSimple({"name": "square", "color": "220,30,30", "size": "2.6"})
                ))
                layer.triggerRepaint()
                return
            if key == "SIM_WORK_ON":
                layer.setRenderer(QgsSingleSymbolRenderer(
                    QgsMarkerSymbol.createSimple({"name": "triangle", "color": "30,170,70", "size": "2.8"})
                ))
                layer.triggerRepaint()
                return
            categories = [
                QgsRendererCategory(
                    "WORK_OFF",
                    QgsMarkerSymbol.createSimple({"name": "square", "color": "220,30,30", "size": "2.6"}),
                    "WORK_OFF",
                ),
                QgsRendererCategory(
                    "WORK_ON",
                    QgsMarkerSymbol.createSimple({"name": "triangle", "color": "30,170,70", "size": "2.8"}),
                    "WORK_ON",
                ),
            ]
            layer.setRenderer(QgsCategorizedSymbolRenderer("event", categories))
        elif key in symbols:
            layer.setRenderer(QgsSingleSymbolRenderer(symbols[key]))
        layer.triggerRepaint()

    def _build_result(self):
        lines = self.lines_combo.currentLayer()
        field = self.field_combo.currentLayer()
        obstacles = self.obstacle_combo.currentLayer()
        if not isinstance(lines, QgsVectorLayer) or lines.geometryType() != QgsWkbTypes.LineGeometry:
            raise ValueError("Selecione a camada de linhas geradas.")
        if not isinstance(field, QgsVectorLayer) or field.geometryType() != QgsWkbTypes.PolygonGeometry:
            raise ValueError("Selecione a camada poligonal do talhao.")
        if not isinstance(obstacles, QgsVectorLayer) or not obstacles.isValid():
            raise ValueError("Selecione a camada de postes/obstaculos.")
        if is_safety_zone_layer_name(obstacles.name()):
            raise ValueError(
                f"'{obstacles.name()}' ja e uma zona de seguranca expandida. "
                "Selecione a camada original dos obstaculos (pontos Flag/poste "
                "ou 09_Obstaculos_RTK) para nao aplicar a distancia duas vezes."
            )
        safe_layer_name = simulation_role_definition("SIM_WORK_LINES").display_name
        zone_layer_name = simulation_role_definition("SIM_SAFETY_ZONE").display_name

        target_crs = self._metric_crs(field)
        field_geom = self._combined_geometry(field, target_crs, selected_first=True)
        if field_geom is None or field_geom.isEmpty() or not field_geom.isGeosValid():
            raise ValueError("A geometria do talhao esta vazia ou invalida.")

        radius = self._radius()
        obstacle_items = self._obstacle_geometries(obstacles, target_crs)
        inside_field = sum(1 for item in obstacle_items if field_geom.intersects(item[1]))
        zones = [item[1].buffer(radius, 24) for item in obstacle_items]
        zones = [zone for zone in zones if zone is not None and not zone.isEmpty()]
        zone_index = QgsSpatialIndex()
        zone_by_id = {}
        for index, zone in enumerate(zones):
            indexed_feature = QgsFeature()
            indexed_feature.setId(index)
            indexed_feature.setGeometry(zone)
            zone_index.addFeature(indexed_feature)
            zone_by_id[index] = (zone, qgs_geometry_to_multipolygon(zone))

        output = QgsVectorLayer(
            f"LineString?crs={target_crs.authid()}", safe_layer_name, "memory"
        )
        provider = output.dataProvider()
        provider.addAttributes(list(lines.fields()))
        self._extra_field_names = self._add_extra_fields(provider, output.fields().names())
        output.updateFields()
        source_names = lines.fields().names()
        self._number_field = line_number_field(source_names)
        self._id_field = line_id_field(source_names)

        transform = self._transform(lines.crs(), target_crs)
        features = (
            lines.selectedFeatures()
            if self.selected_lines_check.isChecked() and lines.selectedFeatureCount() > 0
            else lines.getFeatures()
        )
        records = []
        for feature in features:
            geometry = QgsGeometry(feature.geometry())
            if geometry.isEmpty():
                continue
            if transform is not None:
                geometry.transform(transform)
            parts = geometry.asMultiPolyline() if geometry.isMultipart() else [geometry.asPolyline()]
            source_id = str(feature.id())
            for part_index, part in enumerate(parts, start=1):
                if len(part) < 2:
                    continue
                points = [(point.x(), point.y()) for point in part]
                part_geom = QgsGeometry.fromPolylineXY([QgsPointXY(*point) for point in points])
                part_source = source_id if len(parts) == 1 else f"{source_id}_P{part_index}"
                records.append((feature, source_id, part_source, part_geom, tuple(points)))

        computed_numbers = {} if self._number_field else spatial_line_numbers(
            {source_id: points for _f, source_id, _p, _g, points in reversed(records)}
        )
        output_features = []
        affected_ids = set()
        cut_count = 0
        pass_count = 0
        pieces_by_line: dict[str, list] = {}
        for feature, source_id, part_source, part_geom, points in records:
            candidate_ids = zone_index.intersects(part_geom.boundingBox())
            candidate_zones = [zone_by_id[item] for item in candidate_ids if item in zone_by_id]
            intersecting = [item for item in candidate_zones if part_geom.intersects(item[0])]
            hit_count = len(intersecting)
            pieces = pieces_by_line.setdefault(source_id, [])
            if hit_count == 0:
                pass_count += 1
                pieces.append((feature, part_source, f"{part_source}_S01", points, "PASS", 0))
                continue
            affected_ids.add(source_id)
            cut_count += 1
            exclusion_mp = [polygon for _zone, multipolygon in intersecting for polygon in multipolygon]
            segments = cut_polyline_by_zones(
                points,
                exclusion_mp,
                source_id=part_source,
                obstacle_count=hit_count,
                minimum_length_m=0.05,
                densify_m=min(0.20, max(0.02, radius / 50.0)),
            )
            for segment in segments:
                pieces.append(
                    (feature, segment.source_id, segment.segment_id, segment.path_points, "CUT", hit_count)
                )
        for source_id, pieces in pieces_by_line.items():
            feature = pieces[0][0] if pieces else None
            if feature is None:
                continue
            number = self._line_number(feature, computed_numbers.get(source_id))
            parent_id = self._parent_line_id(feature, number)
            for index, (feat, part_source, segment_id, points, mode, hits) in enumerate(pieces, start=1):
                self._append_output_feature(
                    output_features, output, feat, part_source, segment_id, points, mode, hits,
                    identity={
                        "line_id": parent_id, "line_number": number, "parent_line_id": parent_id,
                        "segment_index": index, "segment_count": len(pieces),
                    },
                )
        provider.addFeatures(output_features)
        output.updateExtents()
        output.renderer().symbol().setColor(QColor(30, 180, 70))
        output.renderer().symbol().setWidth(0.8)

        zone_layer = QgsVectorLayer(
            f"Polygon?crs={target_crs.authid()}", zone_layer_name, "memory"
        )
        zone_provider = zone_layer.dataProvider()
        zone_provider.addAttributes([QgsField("radius_m", QVariant.Double)])
        zone_layer.updateFields()
        zone_features = []
        for zone in zones:
            feature = QgsFeature(zone_layer.fields())
            feature.setGeometry(zone)
            feature.setAttributes([radius])
            zone_features.append(feature)
        zone_provider.addFeatures(zone_features)
        zone_layer.updateExtents()
        zone_layer.renderer().symbol().setColor(QColor(220, 50, 50, 80))

        report = {
            "status": "OK",
            "source_layer": lines.name(),
            "field_layer": field.name(),
            "obstacle_layer": obstacles.name(),
            "working_crs": target_crs.authid(),
            "behavior": "cut",
            "radius_method": self.radius_method.currentData(),
            "obstacle_radius_m": self.obstacle_radius.value(),
            "implement_width_m": self.implement_width.value(),
            "implement_half_width_m": self.implement_width.value() / 2.0,
            "safety_margin_m": self.safety_margin.value(),
            "effective_radius_m": radius,
            "obstacle_count": len(obstacle_items),
            "obstacles_inside_field": inside_field,
            "clipped_by_field": False,
            "line_number_source": self._number_field or "spatial_order",
            "source_line_count": len(records),
            "output_logical_line_count": len(pieces_by_line),
            "cut_line_count": len(affected_ids),
            "affected_line_count": len(affected_ids),
            "pass_count": pass_count,
            "cut_count": cut_count,
            "output_segment_count": len(output_features),
            "original_layers_modified": False,
            "source_geometry_preserved": True,
            "output_layer": safe_layer_name,
            "safety_zone_layer": zone_layer_name,
        }
        return output, zone_layer, report

    @staticmethod
    def _add_extra_fields(provider, existing_names):
        """Acrescenta apenas os campos ausentes; os existentes sao reaproveitados."""
        fields = [
            QgsField("line_id", QVariant.String),
            QgsField("line_number", QVariant.Int),
            QgsField("parent_line_id", QVariant.String),
            QgsField("segment_index", QVariant.Int),
            QgsField("segment_count", QVariant.Int),
            QgsField("source_id", QVariant.String),
            QgsField("segment_id", QVariant.String),
            QgsField("mode", QVariant.String),
            QgsField("obstacle_cut", QVariant.Int),
            QgsField("obstacle_count", QVariant.Int),
            QgsField("machine_width_m", QVariant.Double),
            QgsField("clearance_m", QVariant.Double),
        ]
        existing = {name.lower() for name in existing_names}
        missing = [field for field in fields if field.name().lower() not in existing]
        provider.addAttributes(missing)
        return [field.name() for field in fields]

    def _line_number(self, feature, computed):
        if self._number_field:
            value = feature[self._number_field]
            try:
                return int(value)
            except (TypeError, ValueError):
                return computed
        return computed

    def _parent_line_id(self, feature, number):
        if self._id_field:
            value = feature[self._id_field]
            if value not in (None, "") and str(value) != "NULL":
                return str(value)
        return line_id_for(number) if number is not None else f"F{feature.id()}"

    def _metric_crs(self, field):
        info = inspect_authid(field.crs().authid())
        if not info.is_geographic:
            require_projected_metric(field.crs().authid(), "corte por obstaculos")
            return field.crs()
        geometry = self._combined_geometry(field, field.crs(), selected_first=True)
        center = geometry.centroid().asPoint()
        geographic = QgsCoordinateReferenceSystem("EPSG:4674")
        if field.crs() != geographic:
            center = QgsCoordinateTransform(
                field.crs(), geographic, QgsProject.instance()
            ).transform(center)
        return QgsCoordinateReferenceSystem(
            suggest_sirgas_utm_epsg(center.x(), center.y())
        )

    def _combined_geometry(self, layer, target_crs, *, selected_first=False):
        selected = layer.selectedFeatures() if selected_first else []
        features = selected or list(layer.getFeatures())
        transform = self._transform(layer.crs(), target_crs)
        geometries = []
        for feature in features:
            geometry = QgsGeometry(feature.geometry())
            if geometry.isEmpty():
                continue
            if transform is not None:
                geometry.transform(transform)
            geometries.append(geometry)
        if not geometries:
            return None
        return geometries[0] if len(geometries) == 1 else QgsGeometry.unaryUnion(geometries)

    def _obstacle_geometries(self, layer, target_crs):
        transform = self._transform(layer.crs(), target_crs)
        result = []
        features = (
            layer.selectedFeatures()
            if self.selected_obstacles_check.isChecked() and layer.selectedFeatureCount() > 0
            else layer.getFeatures()
        )
        for feature in features:
            geometry = QgsGeometry(feature.geometry())
            if geometry.isEmpty():
                continue
            if transform is not None:
                geometry.transform(transform)
            result.append((feature.id(), geometry, layer.name()))
        return result

    def _append_output_feature(
        self,
        destination,
        output_layer,
        source_feature,
        source_id,
        segment_id,
        points,
        mode,
        obstacle_count,
        identity=None,
    ):
        if len(points) < 2:
            return
        fields = output_layer.fields()
        feature = QgsFeature(fields)
        feature.setGeometry(
            QgsGeometry.fromPolylineXY([QgsPointXY(*point) for point in points])
        )
        attributes = list(source_feature.attributes())
        attributes += [None] * (fields.count() - len(attributes))
        values = dict(identity or {})
        values.update({
            "source_id": source_id,
            "segment_id": segment_id,
            "mode": mode,
            "obstacle_cut": 1 if mode == "CUT" else 0,
            "obstacle_count": obstacle_count,
            "machine_width_m": self.implement_width.value(),
            "clearance_m": self._radius(),
        })
        inherited = {self._number_field, self._id_field} - {None}
        for name, value in values.items():
            index = fields.lookupField(name)
            if index < 0 or fields.at(index).name() in inherited:
                continue
            attributes[index] = value
        feature.setAttributes(attributes)
        destination.append(feature)

    @staticmethod
    def _transform(source_crs, target_crs):
        if source_crs == target_crs:
            return None
        return QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())

    def save(self):
        if not self.preview_valid:
            self.save_btn.setEnabled(False)
            return
        if (self.last_report or {}).get("behavior") == LATERAL_BEHAVIOR:
            self._save_lateral_detour()
            return
        layer = (
            self.sim_layers_by_key.get("SIM_WORK_LINES")
            if self.sim_layers_by_key
            else QgsProject.instance().mapLayer(self.safe_layer_id or "")
        )
        if not isinstance(layer, QgsVectorLayer) or self.last_report is None:
            return
        project = QgsProject.instance()
        manager = FortSmartPersistenceManager(project)
        field_name = self._field_name()
        try:
            path = manager.get_field_storage_path(field_name)
        except PersistenceError as exc:
            QMessageBox.warning(self, "FortSmart Precision", str(exc))
            return
        # 31/32/33 formam um unico resultado: eventos vazios substituem os anteriores.
        outputs = [(layer, "SIM_WORK_LINES", False)]
        for key in ("SIM_WORK_OFF", "SIM_WORK_ON"):
            events = self.sim_layers_by_key.get(key)
            if isinstance(events, QgsVectorLayer) and events.isValid():
                outputs.append((events, key, True))
        border_layer = self.sim_layers_by_key.get("SIM_BORDER_PASS")
        if (
            isinstance(border_layer, QgsVectorLayer)
            and border_layer.isValid()
            and border_layer.featureCount() > 0
        ):
            outputs.append((border_layer, "FINAL_BORDER_PASS", False))

        stored = []
        try:
            for output_layer, role_key, allow_empty in outputs:
                definition = simulation_role_definition(role_key)
                result = manager.persist_layer(output_layer, definition, field_name, allow_empty=allow_empty)
                stored.append((output_layer, role_key, definition, result))
        except PersistenceError as exc:
            QMessageBox.critical(self, "FortSmart Precision", str(exc))
            return
        saved_names = [definition.display_name for _layer, _key, definition, _result in stored]
        report = dict(self.last_report)
        report.update({
            "saved_layer": saved_names[0],
            "saved_layers": saved_names,
            "output_file": str(path),
            "storage": "geopackage",
            "original_layers_modified": False,
        })
        report_path = path.parent / f"{saved_names[0]}.validation.json"
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        for output_layer, role_key, definition, result in stored:
            saved = publish_persisted(
                project, output_layer, result.layer,
                reused=result.reused_layer, field_name=field_name, definition=definition,
            )
            if role_key == "SIM_WORK_LINES":
                if not result.reused_layer:
                    self._apply_line_labels(saved)
                self.saved_layer_id = saved.id()
        self.preview_valid = False
        self._remove_preview(restore_source=False)
        self.resultSaved.emit(saved_names)
        self._update_actions()
        listing = "\n".join(f"- {name}" for name in saved_names)
        QMessageBox.information(
            self,
            "FortSmart Precision",
            f"Resultado salvo:\n{listing}\nArquivo: {path}\nRelatorio: {report_path}",
        )

    def _remove_preview(self, *, restore_source=True):
        for layer_id in [self.safe_layer_id, self.zone_layer_id, *self.sim_layer_ids]:
            if layer_id and QgsProject.instance().mapLayer(layer_id):
                QgsProject.instance().removeMapLayer(layer_id)
        self.safe_layer_id = None
        self.zone_layer_id = None
        self.sim_layer_ids = []
        self.sim_layers_by_key = {}
        parent = self._project_group(create=False)
        if parent is not None:
            remove_group_if_empty(preview_group(parent, create=False))
            remove_group_if_empty(parent)
        if self.source_layer_id and restore_source:
            source_node = QgsProject.instance().layerTreeRoot().findLayer(self.source_layer_id)
            if source_node is not None:
                source_node.setItemVisibilityChecked(self.source_layer_was_visible)
        self.source_layer_id = None

    def reject(self):
        self._remove_preview()
        super().reject()
