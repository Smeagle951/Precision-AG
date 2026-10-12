# -*- coding: utf-8 -*-
"""Tela unica de configuracao da operacao agricola."""

from __future__ import annotations

from pathlib import Path

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QDoubleSpinBox,
)
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsMapLayerProxyModel,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgsMapLayerComboBox

from ..core.coverage_strip_engine import build_coverage_strips
from ..core.crs import inspect_authid, require_projected_metric, suggest_sirgas_utm_epsg
from ..core.parallel_pass_engine import ParallelPass, ParallelPassParams, generate_parallel_passes
from ..core.turn_path_engine import TurnPath, TurnPathResult, generate_turn_paths
from ..domain.boundary_areas import BoundaryAreas, build_inner_and_headland
from ..domain.headland_layout import HeadlandLayout
from ..domain.operation_width import half_width
from ..domain.planting_configuration import PlantingConfiguration
from ..domain.spraying_configuration import SprayingConfiguration
from ..validators.turn_validator import validate_turn_paths
from .agricultural_lines_dialog import qgs_geometry_to_multipolygon, to_qgs_point
from .maptools.capture_ab_line_tool import CaptureABLineTool
from .turns_and_headlands_tab import (
    TurnsAndHeadlandsTab,
    split_valid_invalid,
    turn_paths_memory_layer,
)


OP_PASS_LAYER = "Operacao_Passadas"
OP_STRIP_LAYER = "Operacao_Faixas"
OP_TURN_LAYER = "Operacao_Manobras"
OP_INVALID_TURN_LAYER = "Operacao_Manobras_Invalidas"
OP_INNER_LAYER = "Operacao_Area_Interna"
OP_HEADLAND_LAYER = "Operacao_Cabeceira"
OP_EXTERNAL_LAYER = "Operacao_Manobras_Externas"


def prepare_metric_work_context(field_layer, ab_start, ab_end):
    """Copia geometrias e A-B para um CRS metrico, sem alterar a origem."""
    geometries = [
        QgsGeometry(feature.geometry())
        for feature in field_layer.getFeatures()
        if feature.geometry() and not feature.geometry().isEmpty()
    ]
    if not geometries:
        raise ValueError("Limite vazio.")

    source_crs = field_layer.crs()
    source_authid = source_crs.authid()
    info = inspect_authid(source_authid)
    if info.is_geographic:
        union = geometries[0] if len(geometries) == 1 else QgsGeometry.unaryUnion(geometries)
        center = union.centroid().asPoint()
        geographic_crs = QgsCoordinateReferenceSystem("EPSG:4674")
        if source_crs != geographic_crs:
            center = QgsCoordinateTransform(
                source_crs, geographic_crs, QgsProject.instance()
            ).transform(center)
        target_authid = suggest_sirgas_utm_epsg(center.x(), center.y())
        target_crs = QgsCoordinateReferenceSystem(target_authid)
    else:
        require_projected_metric(source_authid, "configuracao da operacao agricola")
        target_authid = source_authid
        target_crs = source_crs

    if source_crs == target_crs:
        return target_authid, target_crs, geometries, ab_start, ab_end

    transform = QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())
    transformed = []
    for geometry in geometries:
        geometry.transform(transform)
        transformed.append(geometry)
    a = transform.transform(ab_start[0], ab_start[1])
    b = transform.transform(ab_end[0], ab_end[1])
    return target_authid, target_crs, transformed, (a.x(), a.y()), (b.x(), b.y())


def geometries_in_crs(layer, target_crs):
    """Retorna copias das geometrias da camada no CRS de trabalho."""
    transform = None
    if layer.crs() != target_crs:
        transform = QgsCoordinateTransform(layer.crs(), target_crs, QgsProject.instance())
    geometries = []
    for feature in layer.getFeatures():
        if not feature.geometry() or feature.geometry().isEmpty():
            continue
        geometry = QgsGeometry(feature.geometry())
        if transform is not None:
            geometry.transform(transform)
        geometries.append(geometry)
    return geometries


class OperationConfigurationDialog(QDialog):
    """Configuracao visual de plantio, pulverizacao e operacoes customizadas."""

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.ab_start = None
        self.ab_end = None
        self.previous_map_tool = None
        self.capture_tool = None
        self.pass_layer_id = None
        self.strip_layer_id = None
        self.turn_layer_id = None
        self.invalid_turn_layer_id = None
        self.inner_layer_id = None
        self.headland_layer_id = None
        self.external_layer_id = None
        self.generated_passes: list[ParallelPass] = []
        self.generated_turns: list[TurnPath] = []
        self.turn_result: TurnPathResult | None = None
        self.boundary_areas: BoundaryAreas | None = None
        self.working_crs_authid = None
        self.setWindowTitle("Configuracao da Operacao Agricola")
        self.resize(760, 680)
        self._build_ui()
        self._connect()
        self.refresh_info()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._project_tab(), "Projeto")
        self.tabs.addTab(self._operation_tab(), "Operacao")
        self.tabs.addTab(self._machine_tab(), "Maquina")
        self.tabs.addTab(self._planting_tab(), "Plantio")
        self.tabs.addTab(self._spraying_tab(), "Pulverizacao")
        self.tabs.addTab(self._headland_tab(), "Bordadura")
        self.turns_tab = TurnsAndHeadlandsTab()
        self.tabs.addTab(self.turns_tab, "Voltas e Manobras")
        self.tabs.addTab(self._ab_tab(), "Linha A-B")
        self.tabs.addTab(self._output_tab(), "Saida")
        layout.addWidget(self.tabs)

        self.status_label = QLabel("Configure a operacao e gere uma pre-visualizacao.")
        layout.addWidget(self.status_label)
        row = QHBoxLayout()
        self.btn_preview = QPushButton("Pre-visualizar")
        self.btn_save = QPushButton("Salvar")
        self.btn_close = QPushButton("Fechar")
        self.btn_save.setEnabled(False)
        row.addWidget(self.btn_preview)
        row.addWidget(self.btn_save)
        row.addStretch()
        row.addWidget(self.btn_close)
        layout.addLayout(row)

    def _project_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)
        self.farm_edit = QLineEdit()
        self.field_name_edit = QLineEdit()
        self.season_edit = QLineEdit("2026/27")
        self.operation_name_edit = QLineEdit("Operacao agricola")
        self.field_layer_combo = QgsMapLayerComboBox()
        self.field_layer_combo.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        self.field_crs_label = QLabel("-")
        form.addRow("Fazenda:", self.farm_edit)
        form.addRow("Talhao:", self.field_name_edit)
        form.addRow("Safra:", self.season_edit)
        form.addRow("Nome da operacao:", self.operation_name_edit)
        form.addRow("Limite do talhao:", self.field_layer_combo)
        form.addRow("CRS:", self.field_crs_label)
        return tab

    def _operation_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)
        self.operation_combo = QComboBox()
        self.operation_combo.addItem("Plantio", "planting")
        self.operation_combo.addItem("Pulverizacao", "spraying")
        self.operation_combo.addItem("Adubacao", "fertilizing")
        self.operation_combo.addItem("Personalizado", "custom")
        form.addRow("Tipo:", self.operation_combo)
        return tab

    def _machine_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)
        self.machine_type_edit = QLineEdit()
        self.manufacturer_edit = QLineEdit()
        self.model_edit = QLineEdit()
        self.machine_name_edit = QLineEdit()
        self.informed_width_spin = QDoubleSpinBox()
        self.informed_width_spin.setRange(0.01, 1000.0)
        self.informed_width_spin.setValue(18.0)
        self.informed_width_spin.setSuffix(" m")
        self.lateral_offset_spin = QDoubleSpinBox()
        self.lateral_offset_spin.setRange(-500.0, 500.0)
        self.lateral_offset_spin.setValue(0.0)
        self.lateral_offset_spin.setSuffix(" m")
        self.ab_offset_spin = QDoubleSpinBox()
        self.ab_offset_spin.setRange(-500.0, 500.0)
        self.ab_offset_spin.setValue(0.0)
        self.ab_offset_spin.setSuffix(" m")
        self.machine_width_info = QLabel("-")
        form.addRow("Tipo:", self.machine_type_edit)
        form.addRow("Fabricante:", self.manufacturer_edit)
        form.addRow("Modelo:", self.model_edit)
        form.addRow("Nome:", self.machine_name_edit)
        form.addRow("Largura informada:", self.informed_width_spin)
        form.addRow("Offset lateral (+ direita):", self.lateral_offset_spin)
        form.addRow("Offset A-B (+ direita):", self.ab_offset_spin)
        form.addRow("Largura:", self.machine_width_info)
        return tab

    def _planting_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)
        self.plant_rows_spin = QSpinBox()
        self.plant_rows_spin.setRange(1, 240)
        self.plant_rows_spin.setValue(40)
        self.plant_spacing_spin = QDoubleSpinBox()
        self.plant_spacing_spin.setRange(0.01, 10.0)
        self.plant_spacing_spin.setValue(0.45)
        self.plant_spacing_spin.setSuffix(" m")
        self.plant_width_method = QComboBox()
        self.plant_width_method.addItem("Numero de linhas x espacamento", "count_spacing")
        self.plant_width_method.addItem("Largura manual informada", "manual")
        self.plant_info = QLabel("-")
        form.addRow("Numero de linhas:", self.plant_rows_spin)
        form.addRow("Espacamento:", self.plant_spacing_spin)
        form.addRow("Metodo de largura:", self.plant_width_method)
        form.addRow("Resultado:", self.plant_info)
        return tab

    def _spraying_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)
        self.nozzle_count_spin = QSpinBox()
        self.nozzle_count_spin.setRange(1, 1000)
        self.nozzle_count_spin.setValue(72)
        self.nozzle_spacing_spin = QDoubleSpinBox()
        self.nozzle_spacing_spin.setRange(0.01, 10.0)
        self.nozzle_spacing_spin.setValue(0.5)
        self.nozzle_spacing_spin.setSuffix(" m")
        self.spray_width_method = QComboBox()
        self.spray_width_method.addItem("Bicos x espacamento", "count_spacing")
        self.spray_width_method.addItem("(Bicos - 1) x espacamento", "interval_spacing")
        self.overlap_spin = QDoubleSpinBox()
        self.overlap_spin.setRange(0.0, 1000.0)
        self.overlap_spin.setValue(0.0)
        self.overlap_unit_combo = QComboBox()
        self.overlap_unit_combo.addItem("m", "m")
        self.overlap_unit_combo.addItem("cm", "cm")
        self.overlap_unit_combo.addItem("%", "percent")
        self.overlap_basis_combo = QComboBox()
        self.overlap_basis_combo.addItem("Total", "total")
        self.overlap_basis_combo.addItem("Por lado", "each_side")
        self.spray_info = QLabel("-")
        form.addRow("Numero de bicos:", self.nozzle_count_spin)
        form.addRow("Espacamento entre bicos:", self.nozzle_spacing_spin)
        form.addRow("Metodo:", self.spray_width_method)
        form.addRow("Remonte:", self.overlap_spin)
        form.addRow("Unidade:", self.overlap_unit_combo)
        form.addRow("Base:", self.overlap_basis_combo)
        form.addRow("Resultado:", self.spray_info)
        return tab

    def _headland_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)
        self.headland_count_spin = QSpinBox()
        self.headland_count_spin.setRange(0, 20)
        self.headland_count_spin.setValue(0)
        self.headland_mode_combo = QComboBox()
        self.headland_mode_combo.addItem("Sem bordadura", "none")
        self.headland_mode_combo.addItem("Acompanhar limite", "follow_boundary")
        self.headland_mode_combo.addItem("Seguir linha A-B", "parallel_ab")
        self.headland_info = QLabel("-")
        form.addRow("Passadas:", self.headland_count_spin)
        form.addRow("Modo:", self.headland_mode_combo)
        form.addRow("Relatorio:", self.headland_info)
        return tab

    def _ab_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)
        self.line_layer_combo = QgsMapLayerComboBox()
        self.line_layer_combo.setFilters(QgsMapLayerProxyModel.LineLayer)
        self.btn_read_line = QPushButton("Usar linha selecionada")
        self.btn_capture = QPushButton("Desenhar linha")
        self.btn_invert = QPushButton("Inverter sentido")
        row = QHBoxLayout()
        row.addWidget(self.btn_read_line)
        row.addWidget(self.btn_capture)
        row.addWidget(self.btn_invert)
        self.extension_spin = QDoubleSpinBox()
        self.extension_spin.setRange(0.0, 1000.0)
        self.extension_spin.setValue(20.0)
        self.extension_spin.setSuffix(" m")
        self.ab_info = QLabel("-")
        form.addRow("Camada da linha:", self.line_layer_combo)
        form.addRow("A-B:", row)
        form.addRow("Extensao fora do limite:", self.extension_spin)
        form.addRow("Info:", self.ab_info)
        return tab

    def _output_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)
        self.output_guidance_check = QCheckBox("Gerar linhas centrais")
        self.output_guidance_check.setChecked(True)
        self.output_strips_check = QCheckBox("Gerar faixas")
        self.output_strips_check.setChecked(True)
        self.output_headland_check = QCheckBox("Gerar bordadura")
        self.output_inner_check = QCheckBox("Gerar limite interno")
        self.output_report_check = QCheckBox("Gerar relatorio")
        for widget in (
            self.output_guidance_check,
            self.output_strips_check,
            self.output_headland_check,
            self.output_inner_check,
            self.output_report_check,
        ):
            form.addRow("", widget)
        return tab

    def _connect(self):
        self.btn_preview.clicked.connect(self.preview)
        self.btn_save.clicked.connect(self.save)
        self.btn_close.clicked.connect(self.reject)
        self.btn_read_line.clicked.connect(self.read_selected_line)
        self.btn_capture.clicked.connect(self.activate_capture)
        self.btn_invert.clicked.connect(self.invert_ab)
        self.turns_tab.request_space_calc.connect(self.calculate_turn_space)
        self.turns_tab.request_preview.connect(self.preview)
        self.turns_tab.request_validate.connect(self.validate_turns)
        self.turns_tab.request_remove_invalid.connect(self.remove_invalid_turns)
        for widget in (
            self.field_layer_combo,
            self.operation_combo,
            self.informed_width_spin,
            self.lateral_offset_spin,
            self.plant_rows_spin,
            self.plant_spacing_spin,
            self.plant_width_method,
            self.nozzle_count_spin,
            self.nozzle_spacing_spin,
            self.spray_width_method,
            self.overlap_spin,
            self.overlap_unit_combo,
            self.overlap_basis_combo,
            self.headland_count_spin,
            self.headland_mode_combo,
        ):
            signal = getattr(widget, "valueChanged", None) or getattr(widget, "currentIndexChanged", None) or getattr(widget, "layerChanged", None)
            if signal:
                signal.connect(self.refresh_info)

    def refresh_info(self):
        layer = self.field_layer_combo.currentLayer()
        if isinstance(layer, QgsVectorLayer):
            self.field_crs_label.setText(layer.crs().authid() or "CRS desconhecido")
        planting = self._planting_config()
        plant_cmp = planting.width_comparison()
        self.plant_info.setText(
            f"calc {plant_cmp.calculated_width_m:.2f} m | inf {plant_cmp.informed_width_m:.2f} m | "
            f"encontro {planting.meeting_spacing_m():.3f} m"
        )
        spraying = self._spraying_config()
        spray_cmp = spraying.width_comparison()
        self.spray_info.setText(
            f"bicos {spraying.width_by_nozzle_count_m:.2f} m | intervalos {spraying.width_by_nozzle_intervals_m:.2f} m | "
            f"efetivo {spraying.effective_spacing_m:.2f} m | dif {spray_cmp.difference_m:.2f} m"
        )
        width, spacing = self._width_and_spacing()
        left, right = half_width(width, self.lateral_offset_spin.value())
        self.machine_width_info.setText(f"largura {width:.2f} m | meia esq {left:.2f} m | meia dir {right:.2f} m | passadas {spacing:.2f} m")
        headland = HeadlandLayout(
            pass_count=self.headland_count_spin.value(),
            width_m=width,
            effective_spacing_m=spacing,
            mode=self.headland_mode_combo.currentData(),
        )
        self.headland_info.setText(str(headland.report()))

    def _planting_config(self):
        return PlantingConfiguration(
            row_count=self.plant_rows_spin.value(),
            row_spacing_m=self.plant_spacing_spin.value(),
            informed_width_m=self.informed_width_spin.value(),
            width_method=self.plant_width_method.currentData(),
            lateral_offset_m=self.lateral_offset_spin.value(),
        )

    def _spraying_config(self):
        return SprayingConfiguration(
            boom_width_m=self.informed_width_spin.value(),
            nozzle_count=self.nozzle_count_spin.value(),
            nozzle_spacing_m=self.nozzle_spacing_spin.value(),
            width_method=self.spray_width_method.currentData(),
            overlap_value=self.overlap_spin.value(),
            overlap_unit=self.overlap_unit_combo.currentData(),
            overlap_basis=self.overlap_basis_combo.currentData(),
        )

    def _width_and_spacing(self):
        operation = self.operation_combo.currentData()
        if operation == "planting":
            planting = self._planting_config()
            return planting.working_width_m, planting.working_width_m
        if operation == "spraying":
            spraying = self._spraying_config()
            return spraying.boom_width_m, spraying.effective_spacing_m
        return self.informed_width_spin.value(), self.informed_width_spin.value()

    def activate_capture(self):
        canvas = self.iface.mapCanvas()
        self.previous_map_tool = canvas.mapTool()
        self.capture_tool = CaptureABLineTool(canvas)
        self.capture_tool.lineCaptured.connect(self.set_ab_from_canvas)
        canvas.setMapTool(self.capture_tool)

    def set_ab_from_canvas(self, start, end):
        layer = self.field_layer_combo.currentLayer()
        if not isinstance(layer, QgsVectorLayer):
            QMessageBox.warning(self, "FortSmart Precision", "Selecione o talhao primeiro.")
            return
        src_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        self._set_ab((start.x(), start.y()), (end.x(), end.y()), src_crs, layer.crs())
        if self.previous_map_tool:
            self.iface.mapCanvas().setMapTool(self.previous_map_tool)

    def read_selected_line(self):
        line_layer = self.line_layer_combo.currentLayer()
        field_layer = self.field_layer_combo.currentLayer()
        if not isinstance(line_layer, QgsVectorLayer) or not isinstance(field_layer, QgsVectorLayer):
            QMessageBox.warning(self, "FortSmart Precision", "Selecione talhao e camada de linha.")
            return
        features = line_layer.selectedFeatures() or list(line_layer.getFeatures())
        if not features:
            QMessageBox.warning(self, "FortSmart Precision", "Nenhuma linha encontrada.")
            return
        geom = features[0].geometry()
        points = geom.asMultiPolyline()[0] if geom.isMultipart() else geom.asPolyline()
        if len(points) < 2:
            QMessageBox.warning(self, "FortSmart Precision", "Linha A-B invalida.")
            return
        self._set_ab((points[0].x(), points[0].y()), (points[-1].x(), points[-1].y()), line_layer.crs(), field_layer.crs())

    def _set_ab(self, start, end, source_crs, target_crs):
        if source_crs != target_crs:
            transform = QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())
            a = transform.transform(start[0], start[1])
            b = transform.transform(end[0], end[1])
            start = (a.x(), a.y())
            end = (b.x(), b.y())
        self.ab_start = start
        self.ab_end = end
        self.ab_info.setText(f"A=({start[0]:.2f}, {start[1]:.2f}) B=({end[0]:.2f}, {end[1]:.2f})")

    def invert_ab(self):
        if self.ab_start and self.ab_end:
            self.ab_start, self.ab_end = self.ab_end, self.ab_start
            self.ab_info.setText("Linha A-B invertida.")

    def preview(self):
        try:
            layers = self._build_layers()
        except Exception as exc:
            QMessageBox.critical(self, "FortSmart Precision", str(exc))
            return
        for layer_id in (
            self.pass_layer_id,
            self.strip_layer_id,
            self.turn_layer_id,
            self.invalid_turn_layer_id,
            self.inner_layer_id,
            self.headland_layer_id,
            self.external_layer_id,
        ):
            self._remove(layer_id)
        pass_layer = layers["passes"]
        QgsProject.instance().addMapLayer(pass_layer)
        self.pass_layer_id = pass_layer.id()
        if layers.get("strips"):
            QgsProject.instance().addMapLayer(layers["strips"])
            self.strip_layer_id = layers["strips"].id()
        if layers.get("headland"):
            QgsProject.instance().addMapLayer(layers["headland"])
            self.headland_layer_id = layers["headland"].id()
        if layers.get("inner"):
            QgsProject.instance().addMapLayer(layers["inner"])
            self.inner_layer_id = layers["inner"].id()
        if layers.get("external"):
            QgsProject.instance().addMapLayer(layers["external"])
            self.external_layer_id = layers["external"].id()
        if layers.get("turns"):
            QgsProject.instance().addMapLayer(layers["turns"])
            self.turn_layer_id = layers["turns"].id()
        if layers.get("invalid_turns"):
            QgsProject.instance().addMapLayer(layers["invalid_turns"])
            self.invalid_turn_layer_id = layers["invalid_turns"].id()
        self.btn_save.setEnabled(True)
        turn_count = len(self.generated_turns)
        self.status_label.setText(
            f"{len(self.generated_passes)} passadas | {turn_count} voltas geradas."
        )
        self.iface.mapCanvas().setExtent(pass_layer.extent())
        self.iface.mapCanvas().refresh()

    def calculate_turn_space(self):
        try:
            self._ensure_operation_context()
        except Exception as exc:
            QMessageBox.critical(self, "FortSmart Precision", str(exc))
            return
        config = self.turns_tab.build_configuration()
        width, spacing = self._width_and_spacing()
        outside = config.requires_external_area()
        available = (
            config.resolved_extension_after_m()
            if outside
            else (self.boundary_areas.reserved_width_m if self.boundary_areas else 0.0)
        )
        required = config.required_turn_width_m(spacing)
        clearance = None if required is None else available - required
        ext = config.extension_status()
        extension_text = (
            f"config {ext['configured_m']:.2f} m | minima "
            f"{'-' if ext['minimum_m'] is None else f'{ext['minimum_m']:.2f} m'} | {ext['status']}"
        )
        if outside and ext["status"] == "insufficient":
            status = "Extensao insuficiente"
        elif required is None:
            status = "Dados insuficientes (raio nao informado)"
        elif clearance is not None and clearance < 0:
            status = "Insuficiente / impossivel"
        elif clearance is not None and clearance < config.safety.recommended_clearance_m:
            status = "Valida com margem baixa"
        else:
            status = "Valida"
        self.turns_tab.update_space_labels(available, required, clearance, status, extension_text)

    def validate_turns(self):
        if self.turn_result is None:
            QMessageBox.information(self, "FortSmart Precision", "Gere a pre-visualizacao primeiro.")
            return
        config = self.turns_tab.build_configuration()
        report = validate_turn_paths(self.turn_result, config, self.boundary_areas)
        text = (
            f"Erros: {len(report.errors)}\n"
            f"Avisos: {len(report.warnings)}\n"
            f"Salvaveis: {report.savable_count}\n"
            f"Invalidas: {report.invalid_count}\n"
            f"Estimadas: {report.estimated_count}\n\n"
            + "\n".join(report.errors + report.warnings)
        )
        self.turns_tab.show_report_message(
            "Validacao de voltas",
            text or "Nenhuma volta para validar.",
            critical=bool(report.errors),
        )

    def remove_invalid_turns(self):
        valid, _invalid = split_valid_invalid(self.generated_turns)
        self.generated_turns = valid
        if self.turn_result is not None:
            self.turn_result = TurnPathResult(
                turns=valid,
                connections=self.turn_result.connections,
                report={**self.turn_result.report, "turn_count": len(valid)},
            )
        self._remove(self.invalid_turn_layer_id)
        self.invalid_turn_layer_id = None
        self._remove(self.turn_layer_id)
        if valid and self.field_layer_combo.currentLayer():
            crs = self.field_layer_combo.currentLayer().crs().authid()
            layer = turn_paths_memory_layer(OP_TURN_LAYER, crs, valid)
            layer.renderer().symbol().setColor(QColor(0, 160, 70))
            QgsProject.instance().addMapLayer(layer)
            self.turn_layer_id = layer.id()
        self.status_label.setText(f"{len(valid)} voltas validas mantidas.")

    def _ensure_operation_context(self):
        """Garante areas/passadas atuais sem obrigatoriamente criar camadas."""
        self._build_layers(preview_only_compute=True)

    def _build_layers(self, preview_only_compute: bool = False):
        field_layer = self.field_layer_combo.currentLayer()
        if not isinstance(field_layer, QgsVectorLayer):
            raise ValueError("Selecione o limite do talhao.")
        if self.ab_start is None or self.ab_end is None:
            raise ValueError("Defina a linha A-B.")
        crs, working_crs, geometries, ab_start, ab_end = prepare_metric_work_context(
            field_layer, self.ab_start, self.ab_end
        )
        self.working_crs_authid = crs
        source_authid = field_layer.crs().authid()
        if source_authid != crs:
            self.field_crs_label.setText(f"{source_authid} -> {crs} (automatico, temporario)")
        operational_qgs = geometries[0] if len(geometries) == 1 else QgsGeometry.unaryUnion(geometries)
        operational = qgs_geometry_to_multipolygon(operational_qgs)
        width, spacing = self._width_and_spacing()
        headland = HeadlandLayout(
            pass_count=self.headland_count_spin.value(),
            width_m=width,
            effective_spacing_m=spacing,
            mode=self.headland_mode_combo.currentData(),
        )
        reserved = headland.reserved_width_m
        work_geometry = operational_qgs
        if self.output_inner_check.isChecked() or headland.pass_count > 0 or reserved > 0:
            if reserved > 0:
                work_geometry = operational_qgs.buffer(-reserved, 16)
                if work_geometry.isEmpty():
                    raise ValueError("A bordadura eliminou o talhao.")

        # Areas tipadas (dominio puro com shrink para checks metricos coerentes em retangulos).
        external_poly = None
        external_qgs = None
        external_layer = self.turns_tab.external_layer()
        if external_layer is not None:
            external_geoms = geometries_in_crs(external_layer, working_crs)
            if external_geoms:
                external_qgs = external_geoms[0] if len(external_geoms) == 1 else QgsGeometry.unaryUnion(external_geoms)
                external_poly = qgs_geometry_to_multipolygon(external_qgs)
        self.boundary_areas = build_inner_and_headland(
            operational,
            reserved,
            external_turn_area=external_poly,
        )

        passes = generate_parallel_passes(
            ParallelPassParams(
                polygons=qgs_geometry_to_multipolygon(work_geometry),
                ab_start=ab_start,
                ab_end=ab_end,
                pass_spacing_m=spacing,
                operation_width_m=width,
                extension_m=self.extension_spin.value(),
                ab_offset_right_m=self.ab_offset_spin.value(),
                lateral_offset_m=self.lateral_offset_spin.value(),
                operation_id=self.operation_name_edit.text() or "operation",
            )
        )
        self.generated_passes = passes

        turn_config = self.turns_tab.build_configuration()
        self.turn_result = generate_turn_paths(passes, turn_config, self.boundary_areas)
        self.generated_turns = list(self.turn_result.turns)
        outside = turn_config.requires_external_area()
        available = (
            turn_config.resolved_extension_after_m()
            if outside
            else self.boundary_areas.reserved_width_m
        )
        required = turn_config.required_turn_width_m(spacing)
        clearance = None if required is None else available - required
        ext = turn_config.extension_status()
        extension_text = (
            f"config {ext['configured_m']:.2f} m | minima "
            f"{'-' if ext['minimum_m'] is None else f'{ext['minimum_m']:.2f} m'} | {ext['status']}"
        )
        if not turn_config.generate_turns:
            status = "Sem volta automatica"
        elif outside and ext["status"] == "insufficient":
            status = "Extensao insuficiente"
        elif required is None:
            status = "Estimada / dados insuficientes"
        elif clearance is not None and clearance < 0:
            status = "Impossivel"
        elif clearance is not None and clearance < turn_config.safety.recommended_clearance_m:
            status = "Valida com margem baixa"
        else:
            status = "Valida"
        self.turns_tab.update_space_labels(available, required, clearance, status, extension_text)

        if preview_only_compute:
            return {}

        layers = {
            "passes": operation_pass_memory_layer(OP_PASS_LAYER, crs, passes),
        }
        layers["passes"].renderer().symbol().setColor(QColor(30, 90, 200))
        if self.output_strips_check.isChecked():
            left, right = half_width(width, self.lateral_offset_spin.value())
            layers["strips"] = coverage_strip_memory_layer(
                OP_STRIP_LAYER, crs, build_coverage_strips(passes, left, right)
            )
        if self.output_inner_check.isChecked() and reserved > 0 and not work_geometry.isEmpty():
            layers["inner"] = polygon_memory_layer(OP_INNER_LAYER, crs, work_geometry, QColor(180, 180, 180, 60))
        if self.output_headland_check.isChecked() and reserved > 0:
            headland_geom = operational_qgs.difference(work_geometry)
            if not headland_geom.isEmpty():
                layers["headland"] = polygon_memory_layer(
                    OP_HEADLAND_LAYER, crs, headland_geom, QColor(230, 140, 40, 90)
                )
        if external_layer is not None and external_poly is not None:
            if external_qgs is not None:
                layers["external"] = polygon_memory_layer(
                    OP_EXTERNAL_LAYER, crs, ext_qgs, QColor(140, 60, 180, 70)
                )
        if self.generated_turns:
            valid, invalid = split_valid_invalid(self.generated_turns)
            if valid:
                layers["turns"] = turn_paths_memory_layer(OP_TURN_LAYER, crs, valid)
                layers["turns"].renderer().symbol().setColor(QColor(0, 160, 70))
            if invalid:
                layers["invalid_turns"] = turn_paths_memory_layer(OP_INVALID_TURN_LAYER, crs, invalid)
                layers["invalid_turns"].renderer().symbol().setColor(QColor(200, 40, 40))
        return layers

    def save(self):
        layer = QgsProject.instance().mapLayer(self.pass_layer_id)
        if not isinstance(layer, QgsVectorLayer):
            return
        if self.generated_turns:
            report = validate_turn_paths(
                self.turn_result or TurnPathResult([], [], {}),
                self.turns_tab.build_configuration(),
                self.boundary_areas,
            )
            if report.invalid_count:
                answer = QMessageBox.question(
                    self,
                    "FortSmart Precision",
                    "Existem voltas invalidas. Salvar apenas as voltas validas?",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                )
                if answer == QMessageBox.Cancel:
                    return
                if answer == QMessageBox.Yes:
                    self.remove_invalid_turns()
        path, _ = QFileDialog.getSaveFileName(self, "Salvar operacao agricola", str(Path.home() / "operacao.gpkg"), "GeoPackage (*.gpkg);;Shapefile (*.shp)")
        if not path:
            return
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "ESRI Shapefile" if Path(path).suffix.lower() == ".shp" else "GPKG"
        if options.driverName == "GPKG":
            options.layerName = "operation_guidance_lines"
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        result = QgsVectorFileWriter.writeAsVectorFormatV3(layer, path, QgsProject.instance().transformContext(), options)
        code = result[0] if isinstance(result, tuple) else result
        if code != QgsVectorFileWriter.NoError:
            QMessageBox.critical(self, "FortSmart Precision", "Erro ao salvar passadas.")
            return
        turn_layer = QgsProject.instance().mapLayer(self.turn_layer_id)
        if isinstance(turn_layer, QgsVectorLayer) and options.driverName == "GPKG":
            turn_options = QgsVectorFileWriter.SaveVectorOptions()
            turn_options.driverName = "GPKG"
            turn_options.layerName = "operation_turn_paths"
            turn_options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
            QgsVectorFileWriter.writeAsVectorFormatV3(
                turn_layer, path, QgsProject.instance().transformContext(), turn_options
            )
        if self.output_report_check.isChecked() and self.turn_result is not None:
            report = validate_turn_paths(
                self.turn_result,
                self.turns_tab.build_configuration(),
                self.boundary_areas,
                allow_save_invalid=True,
            )
            report_path = Path(path).with_suffix(".turn_report.txt")
            report_path.write_text(
                "\n".join(
                    [
                        "Relatorio de validacao de voltas",
                        str(report.as_dict()),
                        str(self.turn_result.report),
                    ]
                ),
                encoding="utf-8",
            )
        QMessageBox.information(self, "FortSmart Precision", "Operacao salva com sucesso.")

    def _remove(self, layer_id):
        if layer_id and QgsProject.instance().mapLayer(layer_id):
            QgsProject.instance().removeMapLayer(layer_id)

    def reject(self):
        for layer_id in (
            self.pass_layer_id,
            self.strip_layer_id,
            self.turn_layer_id,
            self.invalid_turn_layer_id,
            self.inner_layer_id,
            self.headland_layer_id,
            self.external_layer_id,
        ):
            self._remove(layer_id)
        super().reject()


def polygon_memory_layer(name: str, crs_authid: str, geometry: QgsGeometry, color: QColor) -> QgsVectorLayer:
    layer = QgsVectorLayer(f"Polygon?crs={crs_authid}", name, "memory")
    provider = layer.dataProvider()
    feature = QgsFeature(layer.fields())
    feature.setGeometry(QgsGeometry(geometry))
    provider.addFeatures([feature])
    layer.updateExtents()
    symbol = layer.renderer().symbol()
    symbol.setColor(color)
    return layer


def operation_pass_memory_layer(name: str, crs_authid: str, passes: list[ParallelPass]) -> QgsVectorLayer:
    layer = QgsVectorLayer(f"LineString?crs={crs_authid}", name, "memory")
    provider = layer.dataProvider()
    provider.addAttributes([
        QgsField("fs_id", QVariant.String),
        QgsField("operation_id", QVariant.String),
        QgsField("pass_no", QVariant.Int),
        QgsField("spacing_m", QVariant.Double),
        QgsField("width_m", QVariant.Double),
        QgsField("half_width_m", QVariant.Double),
        QgsField("offset_m", QVariant.Double),
        QgsField("azimuth_deg", QVariant.Double),
        QgsField("length_m", QVariant.Double),
        QgsField("is_headland", QVariant.Bool),
    ])
    layer.updateFields()
    features = []
    for pass_line in passes:
        feature = QgsFeature(layer.fields())
        attrs = pass_line.attributes()
        feature.setAttributes([
            attrs["fs_id"], attrs["operation_id"], attrs["pass_no"], attrs["spacing_m"],
            attrs["width_m"], attrs["half_width_m"], attrs["offset_m"], attrs["azimuth_deg"],
            attrs["length_m"], attrs["is_headland"],
        ])
        feature.setGeometry(QgsGeometry.fromPolylineXY([to_qgs_point(pass_line.guidance_segment.start), to_qgs_point(pass_line.guidance_segment.end)]))
        features.append(feature)
    provider.addFeatures(features)
    layer.updateExtents()
    layer.renderer().symbol().setColor(QColor(0, 0, 0))
    return layer


def coverage_strip_memory_layer(name: str, crs_authid: str, strips) -> QgsVectorLayer:
    layer = QgsVectorLayer(f"Polygon?crs={crs_authid}", name, "memory")
    provider = layer.dataProvider()
    provider.addAttributes([
        QgsField("fs_id", QVariant.String),
        QgsField("pass_no", QVariant.Int),
        QgsField("operation_id", QVariant.String),
        QgsField("width_m", QVariant.Double),
        QgsField("half_left_m", QVariant.Double),
        QgsField("half_right_m", QVariant.Double),
    ])
    layer.updateFields()
    features = []
    for strip in strips:
        feature = QgsFeature(layer.fields())
        attrs = strip.attributes()
        feature.setAttributes([
            attrs["fs_id"], attrs["pass_no"], attrs["operation_id"],
            attrs["width_m"], attrs["half_left_m"], attrs["half_right_m"],
        ])
        feature.setGeometry(QgsGeometry.fromPolygonXY([[to_qgs_point(point) for point in strip.ring]]))
        features.append(feature)
    provider.addFeatures(features)
    layer.updateExtents()
    symbol = layer.renderer().symbol()
    symbol.setColor(QColor(40, 160, 90, 70))
    return layer
