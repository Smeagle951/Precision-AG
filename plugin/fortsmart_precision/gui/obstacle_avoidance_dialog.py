# -*- coding: utf-8 -*-
"""Dialogo de simulacao de desvio de obstaculos (aplicacao + plantio v3)."""

from __future__ import annotations

from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsFeature, QgsGeometry, QgsMapLayerProxyModel, QgsPointXY, QgsProject, QgsVectorLayer
from qgis.gui import QgsMapLayerComboBox

from ..core.crs import CrsValidationError, require_projected_metric
from ..core.precision_lines_engine import run_precision_lines
from ..domain.avoidance_configuration import AvoidanceConfiguration, AvoidanceMode
from ..domain.headland_layout import HeadlandLayout
from ..domain.machine_model import PlanterMachine, load_machine_presets
from ..domain.obstacle_model import obstacle_from_point
from ..domain.planting_avoidance_configuration import (
    PlantingAvoidanceConfiguration,
    PlantingAvoidanceStrategy,
)
from ..domain.planting_kinematics import PlantingKinematics
from ..domain.precision_project import ABLine, FieldGeometry, PrecisionOperation, PrecisionProject
from .agricultural_lines_dialog import qgs_geometry_to_multipolygon
from .maptools.capture_ab_line_tool import CaptureABLineTool


PREVIEW_PREFIX = "_fortsmart_obstacle_"


class ObstacleAvoidanceDialog(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.ab_start = None
        self.ab_end = None
        self.setWindowTitle("Desvio de Obstaculos — Precision Lines v3")
        self.resize(760, 720)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._common_tab(), "Entrada")
        tabs.addTab(self._spray_tab(), "Pulverizacao")
        tabs.addTab(self._planting_tab(), "Plantio")
        layout.addWidget(tabs)

        self.simulate_btn = QPushButton("Simular desvio")
        layout.addWidget(self.simulate_btn)

        self.summary = QLabel("")
        layout.addWidget(self.summary)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Passada", "Obstaculo", "Acao/Estrategia", "Conflito", "Raio (m)"]
        )
        layout.addWidget(self.table)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.capture_btn.clicked.connect(self._capture_ab)
        self.simulate_btn.clicked.connect(self._simulate)
        self.planter_combo.currentIndexChanged.connect(self._on_planter_changed)
        self._on_planter_changed()

    def _common_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        self.field_combo = QgsMapLayerComboBox()
        self.field_combo.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        form.addRow("Talhao:", self.field_combo)

        self.obstacle_combo = QgsMapLayerComboBox()
        self.obstacle_combo.setFilters(QgsMapLayerProxyModel.PointLayer)
        form.addRow("Obstaculos (camada QGIS):", self.obstacle_combo)

        ab_row = QHBoxLayout()
        self.capture_btn = QPushButton("Capturar A-B")
        self.ab_label = QLabel("A-B nao definida")
        ab_row.addWidget(self.capture_btn)
        ab_row.addWidget(self.ab_label, 1)
        form.addRow("Linha A-B:", ab_row)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Somente pulverizacao", "spray")
        self.mode_combo.addItem("Somente plantio", "plant")
        self.mode_combo.addItem("Ambos", "both")
        form.addRow("Operacao:", self.mode_combo)

        self.radius_spin = QDoubleSpinBox()
        self.radius_spin.setRange(0.0, 100.0)
        self.radius_spin.setValue(0.0)
        self.radius_spin.setSuffix(" m")
        form.addRow("Raio fisico obstaculo:", self.radius_spin)
        return widget

    def _spray_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        presets = load_machine_presets()
        self.sprayer_combo = QComboBox()
        for machine in presets.values():
            if machine.kind.value == "sprayer":
                self.sprayer_combo.addItem(machine.name, machine.machine_id)
        form.addRow("Pulverizador:", self.sprayer_combo)

        self.spray_margin_spin = QDoubleSpinBox()
        self.spray_margin_spin.setRange(0.0, 50.0)
        self.spray_margin_spin.setValue(0.0)
        self.spray_margin_spin.setSuffix(" m")
        form.addRow("Margem aplicacao:", self.spray_margin_spin)
        return widget

    def _planting_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        kin_box = QGroupBox("Cinematica (GUI)")
        kin = QFormLayout(kin_box)
        presets = load_machine_presets()
        self.planter_combo = QComboBox()
        for machine in presets.values():
            if machine.kind.value == "planter":
                self.planter_combo.addItem(machine.name, machine.machine_id)
        kin.addRow("Plantadeira:", self.planter_combo)

        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(0.5, 50.0)
        self.width_spin.setDecimals(2)
        self.width_spin.setSuffix(" m")
        kin.addRow("Largura operacional:", self.width_spin)

        self.gnss_ref_combo = QComboBox()
        self.gnss_ref_combo.addItem("Centro do trator", "tractor_center")
        self.gnss_ref_combo.addItem("Centro do implemento", "implement_center")
        kin.addRow("Referencia GNSS:", self.gnss_ref_combo)

        self.gnss_offset_spin = QDoubleSpinBox()
        self.gnss_offset_spin.setRange(-5.0, 5.0)
        self.gnss_offset_spin.setDecimals(2)
        self.gnss_offset_spin.setSuffix(" m")
        kin.addRow("Offset GNSS lateral:", self.gnss_offset_spin)

        self.hitch_spin = QDoubleSpinBox()
        self.hitch_spin.setRange(0.0, 20.0)
        self.hitch_spin.setDecimals(2)
        self.hitch_spin.setSuffix(" m")
        kin.addRow("Distancia trator → articulacao:", self.hitch_spin)

        self.impl_offset_spin = QDoubleSpinBox()
        self.impl_offset_spin.setRange(-5.0, 5.0)
        self.impl_offset_spin.setDecimals(2)
        self.impl_offset_spin.setSuffix(" m")
        kin.addRow("Offset lateral implemento:", self.impl_offset_spin)

        self.tractor_len_spin = QDoubleSpinBox()
        self.tractor_len_spin.setRange(0.0, 20.0)
        self.tractor_len_spin.setDecimals(2)
        self.tractor_len_spin.setSuffix(" m")
        self.tractor_len_spin.setSpecialValueText("nao informado")
        kin.addRow("Comprimento do trator:", self.tractor_len_spin)

        self.track_spin = QDoubleSpinBox()
        self.track_spin.setRange(0.5, 10.0)
        self.track_spin.setDecimals(2)
        self.track_spin.setSuffix(" m")
        kin.addRow("Bitola:", self.track_spin)
        layout.addWidget(kin_box)

        avoid_box = QGroupBox("Evasao de plantio")
        avoid = QFormLayout(avoid_box)
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItem("Automatico", PlantingAvoidanceStrategy.AUTO.value)
        self.strategy_combo.addItem("Lateral", PlantingAvoidanceStrategy.LATERAL.value)
        self.strategy_combo.addItem("Circular", PlantingAvoidanceStrategy.CIRCULAR.value)
        self.strategy_combo.addItem("Contorno", PlantingAvoidanceStrategy.CONTOUR.value)
        avoid.addRow("Estrategia:", self.strategy_combo)

        self.inner_margin_spin = QDoubleSpinBox()
        self.inner_margin_spin.setRange(0.0, 5.0)
        self.inner_margin_spin.setDecimals(2)
        self.inner_margin_spin.setValue(0.50)
        self.inner_margin_spin.setSuffix(" m")
        avoid.addRow("Margem interna de seguranca:", self.inner_margin_spin)

        self.outer_margin_spin = QDoubleSpinBox()
        self.outer_margin_spin.setRange(0.0, 5.0)
        self.outer_margin_spin.setDecimals(2)
        self.outer_margin_spin.setValue(0.50)
        self.outer_margin_spin.setSuffix(" m")
        avoid.addRow("Margem externa de seguranca:", self.outer_margin_spin)

        self.merge_spin = QDoubleSpinBox()
        self.merge_spin.setRange(0.0, 50.0)
        self.merge_spin.setDecimals(2)
        self.merge_spin.setValue(2.0)
        self.merge_spin.setSuffix(" m")
        avoid.addRow("Agrupar obstaculos ate:", self.merge_spin)
        layout.addWidget(avoid_box)
        layout.addStretch(1)
        return widget

    def _on_planter_changed(self) -> None:
        presets = load_machine_presets()
        mid = self.planter_combo.currentData()
        if not mid or mid not in presets:
            return
        machine = presets[mid]
        if not isinstance(machine, PlanterMachine):
            return
        self.width_spin.setValue(machine.operational_width_m)
        self.track_spin.setValue(machine.track.track_width_m)
        self.gnss_offset_spin.setValue(machine.gnss_offset_m)
        self.impl_offset_spin.setValue(machine.implement_center_offset_m)

    def _capture_ab(self) -> None:
        tool = CaptureABLineTool(self.iface.mapCanvas())

        def on_line(a, b):
            self.ab_start = (a.x(), a.y())
            self.ab_end = (b.x(), b.y())
            self.ab_label.setText("A-B definida")

        tool.lineCaptured.connect(on_line)
        self.iface.mapCanvas().setMapTool(tool)

    def _build_kinematics(self, planter: PlanterMachine) -> PlantingKinematics:
        tractor_len = self.tractor_len_spin.value()
        return PlantingKinematics(
            operational_width_m=self.width_spin.value(),
            track_width_m=self.track_spin.value(),
            gnss_reference=self.gnss_ref_combo.currentData(),
            gnss_offset_m=self.gnss_offset_spin.value(),
            hitch_distance_m=self.hitch_spin.value(),
            implement_center_offset_m=self.impl_offset_spin.value(),
            tractor_length_m=None if tractor_len <= 0 else tractor_len,
            row_count=planter.row_count,
            row_spacing_m=planter.row_spacing_m,
        )

    def _simulate(self) -> None:
        layer = self.field_combo.currentLayer()
        obs_layer = self.obstacle_combo.currentLayer()
        if layer is None or self.ab_start is None:
            QMessageBox.warning(self, "Obstaculos", "Informe talhao e A-B.")
            return
        try:
            require_projected_metric(layer.crs().authid())
            feature = next(layer.getFeatures())
            operational = qgs_geometry_to_multipolygon(feature.geometry())
            presets = load_machine_presets()
            mode = self.mode_combo.currentData()
            obstacles = []
            if obs_layer is not None:
                layer_name = obs_layer.name().strip() or "Obstaculo"
                for index, feat in enumerate(obs_layer.getFeatures(), start=1):
                    pt = feat.geometry().asPoint()
                    obstacles.append(
                        obstacle_from_point(
                            (pt.x(), pt.y()),
                            obstacle_radius_m=self.radius_spin.value(),
                            safety_margin_m=self.spray_margin_spin.value(),
                            name=f"{layer_name}-{index}",
                            obstacle_id=f"{layer_name}_{feat.id() if feat.id() >= 0 else index}",
                        )
                    )

            spraying = None
            planting = None
            kinematics = None
            planting_avoidance = PlantingAvoidanceConfiguration(enabled=False)

            if mode in {"spray", "both"}:
                sprayer = presets[self.sprayer_combo.currentData()]
                spraying = PrecisionOperation(operation_id="spraying", machine=sprayer)

            if mode in {"plant", "both"}:
                planter = presets[self.planter_combo.currentData()]
                planting = PrecisionOperation(
                    operation_id="planting",
                    machine=planter,
                    headland=HeadlandLayout(
                        pass_count=1,
                        width_m=planter.operational_width_m,
                        effective_spacing_m=planter.operational_width_m,
                        mode="parallel_ab",
                    ),
                )
                kinematics = self._build_kinematics(planter)
                planting_avoidance = PlantingAvoidanceConfiguration(
                    strategy=PlantingAvoidanceStrategy(self.strategy_combo.currentData()),
                    inner_margin_m=self.inner_margin_spin.value(),
                    outer_margin_m=self.outer_margin_spin.value(),
                    merge_obstacles_m=self.merge_spin.value(),
                    enabled=True,
                )

            project = PrecisionProject(
                field=FieldGeometry(
                    field_boundary=operational,
                    operational_boundary=operational,
                    crs_authid=layer.crs().authid(),
                ),
                ab_line=ABLine(start=self.ab_start, end=self.ab_end),
                planting=planting,
                spraying=spraying,
                obstacles=tuple(obstacles),
                avoidance=AvoidanceConfiguration(mode=AvoidanceMode.CONCENTRIC_RING),
                planting_avoidance=planting_avoidance,
                planting_kinematics=kinematics,
            )
            result = run_precision_lines(project)
        except (ValueError, CrsValidationError) as exc:
            QMessageBox.warning(self, "Obstaculos", str(exc))
            return

        self.summary.setText(
            f"Desvios: {len(result.avoided_paths)} | "
            f"Plantio: {len(result.planting_avoidance_results)} | "
            f"Validacao: {'OK' if result.validation.ok else 'FALHOU'}"
        )
        self.table.setRowCount(0)
        for i, row in enumerate(result.avoidance_table):
            self.table.insertRow(i)
            self.table.setItem(i, 0, QTableWidgetItem(str(row.get("pass_id", ""))))
            obs = row.get("obstacle_id") or row.get("obstacle_ids", "")
            self.table.setItem(i, 1, QTableWidgetItem(str(obs)))
            action = row.get("action") or row.get("strategy_used", "")
            self.table.setItem(i, 2, QTableWidgetItem(str(action)))
            self.table.setItem(i, 3, QTableWidgetItem(str(row.get("conflict_type", ""))))
            radius = row.get("application_radius_m", row.get("tractor_radius_m", 0))
            self.table.setItem(i, 4, QTableWidgetItem(f"{float(radius):.2f}"))
        self._render(result, layer.crs().authid())

    def _render(self, result, crs) -> None:
        self._clear()
        if result.avoided_paths:
            layer = QgsVectorLayer(f"LineString?crs={crs}", f"{PREVIEW_PREFIX}modified", "memory")
            feats = []
            for path in result.avoided_paths:
                coords = [QgsPointXY(x, y) for x, y in path.modified_points]
                feat = QgsFeature()
                feat.setGeometry(QgsGeometry.fromPolylineXY(coords))
                feats.append(feat)
            layer.dataProvider().addFeatures(feats)
            layer.renderer().symbol().setColor(QColor(255, 200, 0))
            QgsProject.instance().addMapLayer(layer)
        if result.forbidden_regions:
            layer = QgsVectorLayer(f"Polygon?crs={crs}", f"{PREVIEW_PREFIX}forbidden", "memory")
            feats = []
            for region in result.forbidden_regions:
                ring = [QgsPointXY(x, y) for x, y in region.geometry[0]]
                feat = QgsFeature()
                feat.setGeometry(QgsGeometry.fromPolygonXY([ring]))
                feats.append(feat)
            layer.dataProvider().addFeatures(feats)
            layer.renderer().symbol().setColor(QColor(220, 60, 60, 80))
            QgsProject.instance().addMapLayer(layer)

    def _clear(self) -> None:
        ids = [
            lyr.id()
            for lyr in QgsProject.instance().mapLayers().values()
            if lyr.name().startswith(PREVIEW_PREFIX)
        ]
        if ids:
            QgsProject.instance().removeMapLayers(ids)
