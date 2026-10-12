# -*- coding: utf-8 -*-
"""Dialogo visual do Gerador de Linhas Agricolas."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QRadioButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QDoubleSpinBox,
)
from qgis.core import (
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

from ..core.crs import CrsValidationError, require_projected_metric
from ..core.line_geometry import MultiPolygon, Point, azimuth_degrees
from ..core.preview_layer_names import unique_layer_name
from ..domain.agricultural_lines import (
    AgriculturalLine,
    AgriculturalLineParams,
    MaleFemaleSetup,
    PlantingSetup,
    SprayingSetup,
    generate_parallel_agricultural_lines,
    spacing_for_operation,
    total_length,
)
from .maptools.capture_ab_line_tool import CaptureABLineTool


PREVIEW_LAYER_NAME = "Linhas_Agricolas"
AB_LAYER_NAME = "Linha_AB"


class AgriculturalLinesDialog(QDialog):
    """Tela principal do primeiro recurso agricola funcional."""

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.preview_layer_id = None
        self.ab_layer_id = None
        self.ab_start: Point | None = None
        self.ab_end: Point | None = None
        self.capture_tool = None
        self.previous_map_tool = None
        self.generated_lines: list[AgriculturalLine] = []
        self.setWindowTitle("Gerador de Linhas Agricolas")
        self.resize(720, 560)
        self._build_ui()
        self._connect()
        self.refresh_layers()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_field_tab(), "Talhao")
        self.tabs.addTab(self._build_ab_tab(), "Linha A-B")
        self.tabs.addTab(self._build_headland_tab(), "Bordadura")
        self.tabs.addTab(self._build_operation_tab(), "Operacao")
        layout.addWidget(self.tabs)

        status_row = QHBoxLayout()
        self.summary_label = QLabel("Sem pre-visualizacao.")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        status_row.addWidget(self.summary_label, 1)
        status_row.addWidget(self.progress)
        layout.addLayout(status_row)

        buttons = QHBoxLayout()
        self.btn_preview = QPushButton("Pre-visualizar")
        self.btn_save = QPushButton("Salvar resultado")
        self.btn_close = QPushButton("Fechar")
        self.btn_save.setEnabled(False)
        buttons.addWidget(self.btn_preview)
        buttons.addWidget(self.btn_save)
        buttons.addStretch()
        buttons.addWidget(self.btn_close)
        layout.addLayout(buttons)

    def _build_field_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)
        self.field_layer_combo = QgsMapLayerComboBox()
        self.field_layer_combo.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        self.use_selected_field = QRadioButton("Usar feicoes selecionadas")
        self.use_all_field = QRadioButton("Usar toda a camada")
        self.use_selected_field.setChecked(True)
        field_mode = QVBoxLayout()
        field_mode.addWidget(self.use_selected_field)
        field_mode.addWidget(self.use_all_field)
        self.field_crs_label = QLabel("-")
        self.field_area_label = QLabel("-")
        form.addRow("Camada poligonal:", self.field_layer_combo)
        form.addRow("Escopo:", field_mode)
        form.addRow("CRS:", self.field_crs_label)
        form.addRow("Area:", self.field_area_label)
        return tab

    def _build_ab_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)
        self.line_layer_combo = QgsMapLayerComboBox()
        self.line_layer_combo.setFilters(QgsMapLayerProxyModel.LineLayer)
        self.use_selected_line = QCheckBox("Usar feicao selecionada da camada de linha")
        self.use_selected_line.setChecked(True)
        self.btn_use_line_selection = QPushButton("Ler linha selecionada")
        self.btn_capture_ab = QPushButton("Desenhar pontos A e B")
        self.btn_invert_ab = QPushButton("Inverter direcao")
        ab_buttons = QHBoxLayout()
        ab_buttons.addWidget(self.btn_use_line_selection)
        ab_buttons.addWidget(self.btn_capture_ab)
        ab_buttons.addWidget(self.btn_invert_ab)
        self.azimuth_label = QLabel("-")
        self.extension_spin = QDoubleSpinBox()
        self.extension_spin.setDecimals(2)
        self.extension_spin.setRange(0.0, 1000.0)
        self.extension_spin.setValue(20.0)
        self.extension_spin.setSuffix(" m")
        form.addRow("Camada de linha:", self.line_layer_combo)
        form.addRow("", self.use_selected_line)
        form.addRow("A-B:", ab_buttons)
        form.addRow("Azimute:", self.azimuth_label)
        form.addRow("Extensao alem do limite:", self.extension_spin)
        return tab

    def _build_headland_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)
        self.headland_none = QRadioButton("Sem bordadura")
        self.headland_manual = QRadioButton("Largura manual")
        self.headland_machine = QRadioButton("Largura da maquina x numero de voltas")
        self.headland_existing = QRadioButton("Usar camada de bordadura existente")
        self.headland_none.setChecked(True)
        self.headland_width_spin = QDoubleSpinBox()
        self.headland_width_spin.setRange(0.0, 500.0)
        self.headland_width_spin.setValue(0.0)
        self.headland_width_spin.setSuffix(" m")
        self.machine_width_spin = QDoubleSpinBox()
        self.machine_width_spin.setRange(0.0, 500.0)
        self.machine_width_spin.setValue(36.0)
        self.machine_width_spin.setSuffix(" m")
        self.turns_spin = QSpinBox()
        self.turns_spin.setRange(1, 20)
        self.turns_spin.setValue(1)
        self.headland_layer_combo = QgsMapLayerComboBox()
        self.headland_layer_combo.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        modes = QVBoxLayout()
        for widget in (
            self.headland_none,
            self.headland_manual,
            self.headland_machine,
            self.headland_existing,
        ):
            modes.addWidget(widget)
        form.addRow("Modo:", modes)
        form.addRow("Largura manual:", self.headland_width_spin)
        form.addRow("Largura da maquina:", self.machine_width_spin)
        form.addRow("Voltas:", self.turns_spin)
        form.addRow("Camada existente:", self.headland_layer_combo)
        return tab

    def _build_operation_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.operation_combo = QComboBox()
        self.operation_combo.addItem("Personalizado", "custom")
        self.operation_combo.addItem("Plantio", "planting")
        self.operation_combo.addItem("Pulverizacao", "spraying")
        self.operation_combo.addItem("Milho macho e femea", "male_female")
        layout.addWidget(self.operation_combo)

        custom_box = QGroupBox("Parametros")
        form = QFormLayout(custom_box)
        self.spacing_spin = QDoubleSpinBox()
        self.spacing_spin.setRange(0.01, 1000.0)
        self.spacing_spin.setValue(18.0)
        self.spacing_spin.setDecimals(3)
        self.spacing_spin.setSuffix(" m")
        self.min_length_spin = QDoubleSpinBox()
        self.min_length_spin.setRange(0.0, 1000.0)
        self.min_length_spin.setValue(0.0)
        self.min_length_spin.setSuffix(" m")
        self.planter_rows_spin = QSpinBox()
        self.planter_rows_spin.setRange(1, 120)
        self.planter_rows_spin.setValue(12)
        self.planter_spacing_spin = QDoubleSpinBox()
        self.planter_spacing_spin.setRange(0.01, 10.0)
        self.planter_spacing_spin.setValue(0.5)
        self.planter_spacing_spin.setSuffix(" m")
        self.planting_output_combo = QComboBox()
        self.planting_output_combo.addItem("Gerar ambos", "both")
        self.planting_output_combo.addItem("Gerar linhas fisicas", "physical")
        self.planting_output_combo.addItem("Gerar passadas centrais", "passes")
        self.boom_width_spin = QDoubleSpinBox()
        self.boom_width_spin.setRange(0.01, 500.0)
        self.boom_width_spin.setValue(36.0)
        self.boom_width_spin.setSuffix(" m")
        self.nozzle_count_spin = QSpinBox()
        self.nozzle_count_spin.setRange(1, 500)
        self.nozzle_count_spin.setValue(72)
        self.nozzle_spacing_spin = QDoubleSpinBox()
        self.nozzle_spacing_spin.setRange(0.01, 10.0)
        self.nozzle_spacing_spin.setValue(0.5)
        self.nozzle_spacing_spin.setSuffix(" m")
        self.overlap_spin = QDoubleSpinBox()
        self.overlap_spin.setRange(0.0, 100.0)
        self.overlap_spin.setValue(0.0)
        self.overlap_unit_combo = QComboBox()
        self.overlap_unit_combo.addItem("m", "m")
        self.overlap_unit_combo.addItem("cm", "cm")
        self.overlap_unit_combo.addItem("%", "percent")
        self.spraying_info_label = QLabel("-")
        self.total_rows_spin = QSpinBox()
        self.total_rows_spin.setRange(1, 120)
        self.total_rows_spin.setValue(7)
        self.female_rows_spin = QSpinBox()
        self.female_rows_spin.setRange(0, 120)
        self.female_rows_spin.setValue(6)
        self.male_rows_spin = QSpinBox()
        self.male_rows_spin.setRange(0, 120)
        self.male_rows_spin.setValue(1)
        self.female_spacing_spin = QDoubleSpinBox()
        self.female_spacing_spin.setRange(0.01, 10.0)
        self.female_spacing_spin.setValue(0.5)
        self.female_spacing_spin.setSuffix(" m")
        self.male_spacing_spin = QDoubleSpinBox()
        self.male_spacing_spin.setRange(0.01, 10.0)
        self.male_spacing_spin.setValue(0.5)
        self.male_spacing_spin.setSuffix(" m")
        self.pattern_combo = QComboBox()
        self.pattern_combo.addItem("6 femeas + 1 macho", "FFFFFFM")
        self.pattern_combo.addItem("2 machos configurados", "MFFFFFM")
        self.pattern_combo.setEditable(True)

        form.addRow("Espacamento personalizado:", self.spacing_spin)
        form.addRow("Comprimento minimo:", self.min_length_spin)
        form.addRow("Linhas da plantadeira:", self.planter_rows_spin)
        form.addRow("Espacamento entre linhas:", self.planter_spacing_spin)
        form.addRow("Saida plantio:", self.planting_output_combo)
        form.addRow("Largura da barra:", self.boom_width_spin)
        form.addRow("Numero de bicos:", self.nozzle_count_spin)
        form.addRow("Espacamento entre bicos:", self.nozzle_spacing_spin)
        form.addRow("Remonte:", self.overlap_spin)
        form.addRow("Unidade remonte:", self.overlap_unit_combo)
        form.addRow("Pulverizacao:", self.spraying_info_label)
        form.addRow("Total linhas plantadeira:", self.total_rows_spin)
        form.addRow("Linhas femea:", self.female_rows_spin)
        form.addRow("Linhas macho:", self.male_rows_spin)
        form.addRow("Espacamento femea:", self.female_spacing_spin)
        form.addRow("Espacamento macho:", self.male_spacing_spin)
        form.addRow("Editor visual M/F:", self.pattern_combo)
        layout.addWidget(custom_box)
        layout.addStretch()
        return tab

    def _connect(self):
        self.btn_close.clicked.connect(self.reject)
        self.btn_preview.clicked.connect(self.preview)
        self.btn_save.clicked.connect(self.save_result)
        self.btn_capture_ab.clicked.connect(self.activate_capture)
        self.btn_use_line_selection.clicked.connect(self.read_selected_line)
        self.btn_invert_ab.clicked.connect(self.invert_ab)
        self.field_layer_combo.layerChanged.connect(self.refresh_field_info)
        self.use_selected_field.toggled.connect(self.refresh_field_info)
        self.operation_combo.currentIndexChanged.connect(self.refresh_operation_info)
        self.boom_width_spin.valueChanged.connect(self.refresh_operation_info)
        self.nozzle_count_spin.valueChanged.connect(self.refresh_operation_info)
        self.nozzle_spacing_spin.valueChanged.connect(self.refresh_operation_info)
        self.overlap_spin.valueChanged.connect(self.refresh_operation_info)
        self.overlap_unit_combo.currentIndexChanged.connect(self.refresh_operation_info)

    def refresh_layers(self):
        active = self.iface.activeLayer()
        if isinstance(active, QgsVectorLayer):
            if active.geometryType() == QgsWkbTypes.PolygonGeometry:
                self.field_layer_combo.setLayer(active)
            elif active.geometryType() == QgsWkbTypes.LineGeometry:
                self.line_layer_combo.setLayer(active)
        self.refresh_field_info()
        self.refresh_operation_info()

    def refresh_field_info(self):
        layer = self.field_layer_combo.currentLayer()
        if not isinstance(layer, QgsVectorLayer):
            self.field_crs_label.setText("-")
            self.field_area_label.setText("-")
            return
        self.field_crs_label.setText(layer.crs().authid() or "CRS desconhecido")
        area = 0.0
        features = layer.selectedFeatures() if self.use_selected_field.isChecked() and layer.selectedFeatureCount() else layer.getFeatures()
        try:
            for feature in features:
                geom = feature.geometry()
                if geom and not geom.isEmpty():
                    area += geom.area()
            self.field_area_label.setText(f"{area:,.2f} m2 ({area / 10000.0:,.4f} ha)")
        except Exception:
            self.field_area_label.setText("Area indisponivel")

    def refresh_operation_info(self):
        setup = self._spraying_setup()
        self.spraying_info_label.setText(
            "largura calculada: "
            f"{setup.calculated_width_m:.2f} m | distancia entre passadas: "
            f"{setup.pass_spacing_m:.2f} m | divergencia: {setup.width_divergence_m:.2f} m"
        )

    def activate_capture(self):
        canvas = self.iface.mapCanvas()
        self.previous_map_tool = canvas.mapTool()
        self.capture_tool = CaptureABLineTool(canvas)
        self.capture_tool.lineCaptured.connect(self.set_ab_from_canvas)
        canvas.setMapTool(self.capture_tool)
        QMessageBox.information(self, "FortSmart Precision", "Clique dois pontos no mapa para definir A e B.")

    def set_ab_from_canvas(self, start, end):
        layer = self.field_layer_combo.currentLayer()
        if not isinstance(layer, QgsVectorLayer):
            QMessageBox.warning(self, "FortSmart Precision", "Selecione primeiro a camada do talhao.")
            return
        src_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        self._set_ab_points((start.x(), start.y()), (end.x(), end.y()), src_crs, layer.crs())
        if self.previous_map_tool is not None:
            self.iface.mapCanvas().setMapTool(self.previous_map_tool)

    def read_selected_line(self):
        line_layer = self.line_layer_combo.currentLayer()
        field_layer = self.field_layer_combo.currentLayer()
        if not isinstance(line_layer, QgsVectorLayer) or not isinstance(field_layer, QgsVectorLayer):
            QMessageBox.warning(self, "FortSmart Precision", "Selecione uma camada de talhao e uma camada de linha.")
            return
        features = line_layer.selectedFeatures() if self.use_selected_line.isChecked() else list(line_layer.getFeatures())
        if not features:
            QMessageBox.warning(self, "FortSmart Precision", "Nenhuma linha selecionada/encontrada.")
            return
        geom = features[0].geometry()
        points = geom.asMultiPolyline()[0] if geom.isMultipart() else geom.asPolyline()
        if len(points) < 2:
            QMessageBox.warning(self, "FortSmart Precision", "A feicao de linha nao possui dois vertices.")
            return
        self._set_ab_points(
            (points[0].x(), points[0].y()),
            (points[-1].x(), points[-1].y()),
            line_layer.crs(),
            field_layer.crs(),
        )

    def invert_ab(self):
        if self.ab_start is None or self.ab_end is None:
            return
        self.ab_start, self.ab_end = self.ab_end, self.ab_start
        self._refresh_ab_labels()
        self._update_ab_layer()

    def _set_ab_points(self, start: Point, end: Point, source_crs, target_crs):
        if source_crs != target_crs:
            transform = QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())
            start_q = transform.transform(start[0], start[1])
            end_q = transform.transform(end[0], end[1])
            start = (start_q.x(), start_q.y())
            end = (end_q.x(), end_q.y())
        self.ab_start = start
        self.ab_end = end
        self._refresh_ab_labels()
        self._update_ab_layer()

    def _refresh_ab_labels(self):
        if self.ab_start is None or self.ab_end is None:
            self.azimuth_label.setText("-")
            return
        self.azimuth_label.setText(f"{azimuth_degrees(self.ab_start, self.ab_end):.2f} graus")

    def preview(self):
        self.progress.setValue(5)
        try:
            lines, layer = self._build_preview_layer()
        except Exception as exc:
            self.progress.setValue(0)
            QMessageBox.critical(self, "FortSmart Precision", str(exc))
            return
        self._remove_layer(self.preview_layer_id)
        QgsProject.instance().addMapLayer(layer)
        self.preview_layer_id = layer.id()
        self.generated_lines = lines
        self.btn_save.setEnabled(bool(lines))
        self.summary_label.setText(
            f"{len(lines)} linhas | comprimento total {total_length(lines):,.2f} m"
        )
        self.progress.setValue(100)
        self.iface.mapCanvas().setExtent(layer.extent())
        self.iface.mapCanvas().refresh()

    def _build_preview_layer(self):
        field_layer = self.field_layer_combo.currentLayer()
        if not isinstance(field_layer, QgsVectorLayer) or field_layer.geometryType() != QgsWkbTypes.PolygonGeometry:
            raise ValueError("Selecione uma camada poligonal de talhao.")
        require_projected_metric(field_layer.crs().authid(), "geracao de linhas agricolas")
        if self.ab_start is None or self.ab_end is None:
            raise ValueError("Defina a linha A-B por camada selecionada ou desenho no mapa.")
        geometry = self._selected_field_geometry(field_layer)
        headland = self._headland_width()
        if headland > 0:
            geometry = geometry.buffer(-headland, 16)
            if geometry.isEmpty():
                raise ValueError("A bordadura eliminou todo o limite operacional.")
        polygons = qgs_geometry_to_multipolygon(geometry)
        operation = self.operation_combo.currentData()
        planting = self._planting_setup()
        spraying = self._spraying_setup()
        male_female = self._male_female_setup()
        lines = self._generate_lines_for_operation(
            polygons,
            operation,
            planting,
            spraying,
            male_female,
        )
        layer = create_lines_memory_layer(
            self._free_layer_name(PREVIEW_LAYER_NAME), field_layer.crs().authid(), lines
        )
        return lines, layer

    def _free_layer_name(self, name: str) -> str:
        own = {self.preview_layer_id, self.ab_layer_id}
        taken = [
            layer.name() for layer in QgsProject.instance().mapLayers().values()
            if layer.id() not in own
        ]
        return unique_layer_name(name, taken)

    def _generate_lines_for_operation(self, polygons, operation, planting, spraying, male_female):
        base_kwargs = {
            "polygons": polygons,
            "ab_start": self.ab_start,
            "ab_end": self.ab_end,
            "extension_m": self.extension_spin.value(),
            "min_length_m": self.min_length_spin.value(),
            "operation": operation,
            "source_ab_id": "gui_ab",
            "planting": planting,
            "spraying": spraying,
            "male_female": male_female,
        }
        if operation == "planting":
            generated: list[AgriculturalLine] = []
            output_mode = planting.output_mode
            if output_mode in {"passes", "both"}:
                generated.extend(
                    generate_parallel_agricultural_lines(
                        AgriculturalLineParams(
                            **base_kwargs,
                            spacing_m=planting.working_width_m,
                            line_type="pass",
                        )
                    )
                )
            if output_mode in {"physical", "both"}:
                generated.extend(
                    generate_parallel_agricultural_lines(
                        AgriculturalLineParams(
                            **base_kwargs,
                            spacing_m=planting.row_spacing_m,
                            line_type="physical",
                        )
                    )
                )
            return renumber_lines(generated)

        spacing = spacing_for_operation(
            operation,
            self.spacing_spin.value(),
            planting=planting,
            spraying=spraying,
            male_female=male_female,
        )
        if spacing <= 0:
            raise ValueError("Espacamento calculado deve ser maior que zero.")
        return generate_parallel_agricultural_lines(
            AgriculturalLineParams(
                **base_kwargs,
                spacing_m=spacing,
                line_type="pass",
            )
        )

    def _selected_field_geometry(self, layer):
        features = layer.selectedFeatures() if self.use_selected_field.isChecked() and layer.selectedFeatureCount() else list(layer.getFeatures())
        geometries = [feature.geometry() for feature in features if feature.geometry() and not feature.geometry().isEmpty()]
        if not geometries:
            raise ValueError("Nenhuma geometria valida encontrada no talhao.")
        if len(geometries) == 1:
            return QgsGeometry(geometries[0])
        return QgsGeometry.unaryUnion(geometries)

    def _headland_width(self):
        if self.headland_manual.isChecked():
            return self.headland_width_spin.value()
        if self.headland_machine.isChecked():
            return self.machine_width_spin.value() * self.turns_spin.value()
        if self.headland_existing.isChecked():
            QMessageBox.information(
                self,
                "FortSmart Precision",
                "Camada de bordadura existente sera consolidada em etapa seguinte; usando sem bordadura agora.",
            )
        return 0.0

    def _planting_setup(self):
        return PlantingSetup(
            row_count=self.planter_rows_spin.value(),
            row_spacing_m=self.planter_spacing_spin.value(),
            output_mode=self.planting_output_combo.currentData(),
        )

    def _spraying_setup(self):
        return SprayingSetup(
            boom_width_m=self.boom_width_spin.value(),
            nozzle_count=self.nozzle_count_spin.value(),
            nozzle_spacing_m=self.nozzle_spacing_spin.value(),
            overlap_value=self.overlap_spin.value(),
            overlap_unit=self.overlap_unit_combo.currentData(),
        )

    def _male_female_setup(self):
        pattern = tuple(str(self.pattern_combo.currentText()).strip().upper())
        pattern = tuple(value for value in pattern if value in {"M", "F"})
        return MaleFemaleSetup(
            planter_total_rows=self.total_rows_spin.value(),
            female_rows=self.female_rows_spin.value(),
            male_rows=self.male_rows_spin.value(),
            female_spacing_m=self.female_spacing_spin.value(),
            male_spacing_m=self.male_spacing_spin.value(),
            pattern=pattern,
        )

    def save_result(self):
        layer = QgsProject.instance().mapLayer(self.preview_layer_id)
        if not isinstance(layer, QgsVectorLayer) or not self.generated_lines:
            QMessageBox.warning(self, "FortSmart Precision", "Gere a pre-visualizacao antes de salvar.")
            return
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "Salvar linhas agricolas",
            str(Path.home() / f"{layer.name()}.gpkg"),
            "GeoPackage (*.gpkg);;Shapefile (*.shp)",
        )
        if not path:
            return
        options = QgsVectorFileWriter.SaveVectorOptions()
        suffix = Path(path).suffix.lower()
        options.driverName = "ESRI Shapefile" if suffix == ".shp" else "GPKG"
        if options.driverName == "GPKG":
            options.layerName = Path(path).stem
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        transform_context = QgsProject.instance().transformContext()
        result = QgsVectorFileWriter.writeAsVectorFormatV3(layer, path, transform_context, options)
        code = result[0] if isinstance(result, tuple) else result
        if code != QgsVectorFileWriter.NoError:
            message = result[1] if isinstance(result, tuple) and len(result) > 1 else "Erro desconhecido"
            QMessageBox.critical(self, "FortSmart Precision", f"Erro ao salvar:\n{message}")
            return
        saved_name = Path(path).stem
        saved = QgsVectorLayer(f"{path}|layername={options.layerName}", saved_name, "ogr") if options.driverName == "GPKG" else QgsVectorLayer(path, saved_name, "ogr")
        if saved.isValid():
            QgsProject.instance().addMapLayer(saved)
            self.iface.mapCanvas().setExtent(saved.extent())
            self.iface.mapCanvas().refresh()
        QMessageBox.information(self, "FortSmart Precision", "Linhas salvas com sucesso.")

    def _update_ab_layer(self):
        self._remove_layer(self.ab_layer_id)
        if self.ab_start is None or self.ab_end is None:
            return
        field_layer = self.field_layer_combo.currentLayer()
        if not isinstance(field_layer, QgsVectorLayer):
            return
        layer = QgsVectorLayer(
            f"LineString?crs={field_layer.crs().authid()}", self._free_layer_name(AB_LAYER_NAME), "memory"
        )
        provider = layer.dataProvider()
        feature = QgsFeature()
        feature.setGeometry(QgsGeometry.fromPolylineXY([to_qgs_point(self.ab_start), to_qgs_point(self.ab_end)]))
        provider.addFeatures([feature])
        layer.updateExtents()
        symbol = layer.renderer().symbol()
        symbol.setColor(QColor(255, 140, 0))
        symbol.setWidth(1.2)
        QgsProject.instance().addMapLayer(layer)
        self.ab_layer_id = layer.id()

    def _remove_layer(self, layer_id):
        if layer_id and QgsProject.instance().mapLayer(layer_id):
            QgsProject.instance().removeMapLayer(layer_id)

    def reject(self):
        self._remove_layer(self.preview_layer_id)
        self._remove_layer(self.ab_layer_id)
        super().reject()


def qgs_geometry_to_multipolygon(geometry: QgsGeometry) -> MultiPolygon:
    """Compat: delega para geometry_bridge (densifica curvas, sem bbox)."""
    from .geometry_bridge import qgs_geometry_to_multipolygon as _convert

    return _convert(geometry)


def create_lines_memory_layer(name: str, crs_authid: str, lines: list[AgriculturalLine]) -> QgsVectorLayer:
    layer = QgsVectorLayer(f"LineString?crs={crs_authid}", name, "memory")
    provider = layer.dataProvider()
    provider.addAttributes(
        [
            QgsField("fs_id", QVariant.String),
            QgsField("line_no", QVariant.Int),
            QgsField("line_type", QVariant.String),
            QgsField("operation", QVariant.String),
            QgsField("spacing_m", QVariant.Double),
            QgsField("pass_id", QVariant.Int),
            QgsField("implement_position", QVariant.Int),
            QgsField("sex", QVariant.String),
            QgsField("azimuth_deg", QVariant.Double),
            QgsField("length_m", QVariant.Double),
            QgsField("direction", QVariant.String),
            QgsField("source_ab_id", QVariant.String),
        ]
    )
    layer.updateFields()
    features = []
    for line in lines:
        feature = QgsFeature(layer.fields())
        attrs = line.attributes()
        feature.setAttributes(
            [
                attrs["fs_id"],
                attrs["line_no"],
                attrs["line_type"],
                attrs["operation"],
                attrs["spacing_m"],
                attrs["pass_id"],
                attrs["implement_position"],
                attrs["sex"],
                attrs["azimuth_deg"],
                attrs["length_m"],
                attrs["direction"],
                attrs["source_ab_id"],
            ]
        )
        feature.setGeometry(
            QgsGeometry.fromPolylineXY(
                [to_qgs_point(line.segment.start), to_qgs_point(line.segment.end)]
            )
        )
        features.append(feature)
    provider.addFeatures(features)
    layer.updateExtents()
    symbol = layer.renderer().symbol()
    symbol.setColor(QColor(20, 125, 90))
    symbol.setWidth(0.7)
    return layer


def to_qgs_point(point: Point):
    from qgis.core import QgsPointXY

    return QgsPointXY(point[0], point[1])


def renumber_lines(lines: list[AgriculturalLine]) -> list[AgriculturalLine]:
    sorted_lines = sorted(lines, key=lambda line: (line.line_type, line.offset_m, line.segment.start[0], line.segment.start[1]))
    return [
        replace(line, line_no=index, pass_id=index, implement_position=index)
        for index, line in enumerate(sorted_lines, start=1)
    ]
