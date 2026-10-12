# -*- coding: utf-8 -*-
"""Dialogo Precision Lines: simulador de cruzamento plantio x tramlines."""

from __future__ import annotations

from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsMapLayerProxyModel,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
)
from qgis.gui import QgsMapLayerComboBox

from ..core.crs import CrsValidationError, require_projected_metric
from ..core.planting_line_cut_engine import line_id_for
from ..core.precision_lines_engine import run_precision_lines
from ..core.preview_layer_names import PREVIEW_LAYER_PROPERTY, unique_layer_name
from ..domain.headland_layout import HeadlandLayout
from ..domain.machine_model import load_machine_presets
from ..domain.precision_project import ABLine, FieldGeometry, PrecisionOperation, PrecisionProject
from .agricultural_lines_dialog import qgs_geometry_to_multipolygon
from .maptools.capture_ab_line_tool import CaptureABLineTool


PREVIEW_GROUP = "_fortsmart_precision_lines"


class PrecisionLinesDialog(QDialog):
    """Simulador visual: plantio, tramlines, shutoff e tabela DESLIGA/LIGA."""

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.ab_start = None
        self.ab_end = None
        self.capture_tool = None
        self.previous_map_tool = None
        self.last_result = None
        self.setWindowTitle("FortSmart Precision Lines")
        self.resize(760, 620)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Motor de planejamento linha a linha (plantio + tramlines + shutoff)."))

        form_box = QGroupBox("Entrada")
        form = QFormLayout(form_box)
        self.field_combo = QgsMapLayerComboBox()
        self.field_combo.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        form.addRow("Talhao:", self.field_combo)

        ab_row = QHBoxLayout()
        self.capture_btn = QPushButton("Capturar A-B")
        self.ab_label = QLabel("A-B nao definida")
        ab_row.addWidget(self.capture_btn)
        ab_row.addWidget(self.ab_label, 1)
        form.addRow("Linha A-B:", ab_row)

        presets = load_machine_presets()
        self.planter_combo = QComboBox()
        self.sprayer_combo = QComboBox()
        for machine in presets.values():
            target = self.planter_combo if machine.kind.value == "planter" else self.sprayer_combo
            target.addItem(machine.name, machine.machine_id)
        form.addRow("Plantadeira:", self.planter_combo)
        form.addRow("Pulverizador:", self.sprayer_combo)

        self.headland_spin = QSpinBox()
        self.headland_spin.setRange(0, 10)
        self.headland_spin.setValue(1)
        form.addRow("Passadas bordadura:", self.headland_spin)
        layout.addWidget(form_box)

        actions = QHBoxLayout()
        self.simulate_btn = QPushButton("Simular cruzamento")
        self.clear_btn = QPushButton("Limpar preview")
        actions.addWidget(self.simulate_btn)
        actions.addWidget(self.clear_btn)
        layout.addLayout(actions)

        self.summary_label = QLabel("")
        layout.addWidget(self.summary_label)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Passada", "Linha", "Acao"])
        layout.addWidget(self.table)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.capture_btn.clicked.connect(self._start_capture)
        self.simulate_btn.clicked.connect(self._simulate)
        self.clear_btn.clicked.connect(self._clear_preview)

    def _start_capture(self) -> None:
        self.previous_map_tool = self.iface.mapCanvas().mapTool()
        self.capture_tool = CaptureABLineTool(self.iface.mapCanvas())

        def on_captured(start, end):
            self.ab_start = (start.x(), start.y())
            self.ab_end = (end.x(), end.y())
            self.ab_label.setText(
                f"A-B ({start.x():.1f}, {start.y():.1f}) -> ({end.x():.1f}, {end.y():.1f})"
            )
            if self.previous_map_tool is not None:
                self.iface.mapCanvas().setMapTool(self.previous_map_tool)

        self.capture_tool.lineCaptured.connect(on_captured)
        self.iface.mapCanvas().setMapTool(self.capture_tool)

    def _build_project(self) -> PrecisionProject:
        layer = self.field_combo.currentLayer()
        if layer is None:
            raise ValueError("Selecione um talhao.")
        if self.ab_start is None or self.ab_end is None:
            raise ValueError("Capture a linha A-B.")

        require_projected_metric(layer.crs().authid())
        feature = next(layer.getFeatures(), None)
        if feature is None:
            raise ValueError("Talhao sem geometria.")

        operational = qgs_geometry_to_multipolygon(feature.geometry())
        presets = load_machine_presets()
        planter = presets[self.planter_combo.currentData()]
        sprayer = presets[self.sprayer_combo.currentData()]

        return PrecisionProject(
            field=FieldGeometry(
                field_boundary=operational,
                operational_boundary=operational,
                crs_authid=layer.crs().authid(),
            ),
            ab_line=ABLine(start=self.ab_start, end=self.ab_end),
            planting=PrecisionOperation(
                operation_id="planting",
                machine=planter,
                headland=HeadlandLayout(
                    pass_count=self.headland_spin.value(),
                    width_m=planter.operational_width_m,
                    effective_spacing_m=planter.operational_width_m,
                    mode="parallel_ab",
                ),
            ),
            spraying=PrecisionOperation(operation_id="spraying", machine=sprayer),
        )

    def _simulate(self) -> None:
        try:
            project = self._build_project()
            self.last_result = run_precision_lines(project)
        except (ValueError, CrsValidationError) as exc:
            QMessageBox.warning(self, "Precision Lines", str(exc))
            return

        result = self.last_result
        self.summary_label.setText(
            f"Passadas: {len(result.planting_passes)} | "
            f"Linhas virtuais (motor): {len(result.planting_rows)} | "
            f"Shutoff: {sum(1 for s in result.shutoff_segments if s.shutoff_state == 'off')} | "
            f"Tramlines: {len(result.tramline_zones)} | "
            f"Validacao: {'OK' if result.validation.ok else 'FALHOU'}"
        )

        self.table.setRowCount(0)
        for row_index, item in enumerate(result.shutoff_table):
            self.table.insertRow(row_index)
            self.table.setItem(row_index, 0, QTableWidgetItem(str(item["pass_id"])))
            self.table.setItem(row_index, 1, QTableWidgetItem(str(item["row_id"])))
            action_item = QTableWidgetItem(str(item["action"]))
            if item["action"] == "DESLIGA":
                action_item.setForeground(QColor(200, 40, 40))
            else:
                action_item.setForeground(QColor(40, 140, 40))
            self.table.setItem(row_index, 2, action_item)

        self._render_preview(result)

    def _segment_geometry(self, segment):
        return QgsGeometry.fromPolylineXY(
            [
                QgsPointXY(segment.start[0], segment.start[1]),
                QgsPointXY(segment.end[0], segment.end[1]),
            ]
        )

    def _render_preview(self, result) -> None:
        self._clear_preview()
        layer = self.field_combo.currentLayer()
        if layer is None:
            return
        crs = layer.crs().authid()

        row_layer = self._new_preview_layer(f"LineString?crs={crs}", "Passadas_Plantio")
        row_layer.dataProvider().addAttributes(
            [QgsField("line_id", QVariant.String), QgsField("line_number", QVariant.Int)]
        )
        row_layer.updateFields()
        row_feats = []
        for traffic in result.planting_passes:
            feat = QgsFeature(row_layer.fields())
            pts = traffic.line_points()
            if len(pts) < 2:
                continue
            feat.setGeometry(
                QgsGeometry.fromPolylineXY([QgsPointXY(p[0], p[1]) for p in pts])
            )
            feat.setAttributes([line_id_for(traffic.pass_no), traffic.pass_no])
            row_feats.append(feat)
        row_layer.dataProvider().addFeatures(row_feats)
        row_layer.renderer().symbol().setColor(QColor(40, 160, 60))
        row_layer.renderer().symbol().setWidth(1.2)
        QgsProject.instance().addMapLayer(row_layer)

        from ..core.shutoff_engine import aggregate_shutoff_on_passes

        off_layer = self._new_preview_layer(f"LineString?crs={crs}", "Shutoff")
        off_feats = []
        for visual in aggregate_shutoff_on_passes(
            list(result.planting_passes),
            list(result.shutoff_segments),
        ):
            if len(visual.path_points) < 2:
                continue
            feat = QgsFeature()
            feat.setGeometry(
                QgsGeometry.fromPolylineXY(
                    [QgsPointXY(p[0], p[1]) for p in visual.path_points]
                )
            )
            off_feats.append(feat)
        off_layer.dataProvider().addFeatures(off_feats)
        off_layer.renderer().symbol().setColor(QColor(220, 50, 50))
        off_layer.renderer().symbol().setWidth(2.0)
        QgsProject.instance().addMapLayer(off_layer)

        tram_layer = self._new_preview_layer(f"Polygon?crs={crs}", "Tramlines")
        tram_feats = []
        for zone in result.tramline_zones:
            outer, _ = zone.polygon
            ring = [QgsPointXY(x, y) for x, y in outer]
            feat = QgsFeature()
            feat.setGeometry(QgsGeometry.fromPolygonXY([ring]))
            tram_feats.append(feat)
        tram_layer.dataProvider().addFeatures(tram_feats)
        sym = tram_layer.renderer().symbol()
        sym.setColor(QColor(60, 120, 220, 80))
        sym.symbolLayer(0).setStrokeColor(QColor(40, 80, 200))
        QgsProject.instance().addMapLayer(tram_layer)

    @staticmethod
    def _new_preview_layer(uri: str, name: str) -> QgsVectorLayer:
        taken = [layer.name() for layer in QgsProject.instance().mapLayers().values()]
        layer = QgsVectorLayer(uri, unique_layer_name(name, taken), "memory")
        layer.setCustomProperty(PREVIEW_LAYER_PROPERTY, PREVIEW_GROUP)
        return layer

    def _clear_preview(self) -> None:
        to_remove = [
            layer.id()
            for layer in QgsProject.instance().mapLayers().values()
            if layer.customProperty(PREVIEW_LAYER_PROPERTY, "") == PREVIEW_GROUP
            or layer.name().startswith(PREVIEW_GROUP)
        ]
        if to_remove:
            QgsProject.instance().removeMapLayers(to_remove)
