# -*- coding: utf-8 -*-
"""Assistente inicial de importacao do FortSmart Precision."""

from __future__ import annotations

from pathlib import Path

from qgis.PyQt.QtCore import Qt
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
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsVectorLayer

from .controllers.import_controller import DATA_TYPE_TO_LAYER, ImportController
from .widgets.layer_summary_widget import LayerSummaryWidget
from .widgets.validation_results_widget import ValidationResultsWidget


class ImportWizard(QDialog):
    """Assistente compacto: camada ativa, camada aberta ou arquivo."""

    def __init__(self, iface, project_root, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.project_root = Path(project_root)
        self.controller = ImportController(iface)
        self.selected_file = None
        self.inspection = None
        self.validation = None
        self.result = None
        self.internal_layers = []
        self.setWindowTitle("Importar dados - FortSmart Precision")
        self.setMinimumWidth(760)
        self._build_ui()
        self._populate_layers()
        self.refresh_source_summary()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        origin = QGroupBox("1. Origem")
        origin_layout = QVBoxLayout(origin)
        self.radio_active = QRadioButton("Usar camada ativa do QGIS")
        self.radio_open = QRadioButton("Escolher entre camadas abertas")
        self.radio_file = QRadioButton("Selecionar arquivo")
        self.radio_active.setChecked(True)
        for radio in (self.radio_active, self.radio_open, self.radio_file):
            radio.toggled.connect(self.refresh_source_summary)
            origin_layout.addWidget(radio)

        row = QHBoxLayout()
        self.combo_layers = QComboBox()
        self.combo_layers.currentIndexChanged.connect(self.refresh_source_summary)
        row.addWidget(QLabel("Camada aberta:"))
        row.addWidget(self.combo_layers)
        origin_layout.addLayout(row)

        file_row = QHBoxLayout()
        self.inp_file = QLineEdit()
        self.btn_file = QPushButton("Selecionar")
        self.btn_file.clicked.connect(self.choose_file)
        file_row.addWidget(self.inp_file)
        file_row.addWidget(self.btn_file)
        origin_layout.addLayout(file_row)

        internal_row = QHBoxLayout()
        self.lbl_internal = QLabel("Camada interna:")
        self.combo_internal = QComboBox()
        self.combo_internal.currentIndexChanged.connect(self.refresh_source_summary)
        internal_row.addWidget(self.lbl_internal)
        internal_row.addWidget(self.combo_internal)
        origin_layout.addLayout(internal_row)
        layout.addWidget(origin)

        self.layer_summary = LayerSummaryWidget("2. Resumo da origem")
        layout.addWidget(self.layer_summary)

        destination = QGroupBox("3. Tipo de dado e destino")
        dest_form = QFormLayout(destination)
        self.combo_data_type = QComboBox()
        self.combo_data_type.addItems(DATA_TYPE_TO_LAYER.keys())
        self.lbl_target = QLabel(DATA_TYPE_TO_LAYER[self.combo_data_type.currentText()])
        self.combo_data_type.currentTextChanged.connect(lambda text: self.lbl_target.setText(DATA_TYPE_TO_LAYER[text]))
        dest_form.addRow("Tipo de dado:", self.combo_data_type)
        dest_form.addRow("Camada destino:", self.lbl_target)
        layout.addWidget(destination)

        normalization = QGroupBox("4. Normalizacao")
        norm_layout = QVBoxLayout(normalization)
        self.chk_copy = QCheckBox("Copiar original para 00_ORIGINAIS")
        self.chk_multi = QCheckBox("Converter Polygon para MultiPolygon")
        self.chk_reproject = QCheckBox("Reprojetar para o CRS do projeto")
        self.chk_preserve = QCheckBox("Preservar atributos compativeis")
        for chk in (self.chk_copy, self.chk_multi, self.chk_reproject, self.chk_preserve):
            chk.setChecked(True)
            chk.setEnabled(False)
            norm_layout.addWidget(chk)
        layout.addWidget(normalization)

        self.validation_widget = ValidationResultsWidget()
        layout.addWidget(self.validation_widget)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Importar")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.import_selected)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate_layers(self):
        self.combo_layers.clear()
        for layer in self.controller.vector_layers():
            self.combo_layers.addItem(layer.name(), layer.id())

    def choose_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar arquivo",
            "",
            "Vetores (*.shp *.gpkg *.geojson *.json *.kml *.kmz *.csv);;Todos (*.*)",
        )
        if file_path:
            self.selected_file = file_path
            self.inp_file.setText(file_path)
            self.radio_file.setChecked(True)
            self.refresh_source_summary()

    def selected_layer(self):
        if self.radio_active.isChecked():
            return self.controller.active_vector_layer()
        if self.radio_open.isChecked():
            layer_id = self.combo_layers.currentData()
            layer = self.iface.mapCanvas().mapSettings().layers()
            for candidate in self.controller.vector_layers():
                if candidate.id() == layer_id:
                    return candidate
        return None

    def refresh_source_summary(self):
        self.inspection = None
        self.validation = None
        self.validation_widget.set_messages([])
        if not self.radio_file.isChecked():
            self.lbl_internal.setVisible(False)
            self.combo_internal.setVisible(False)

        if self.radio_file.isChecked():
            path = self.inp_file.text().strip()
            if not path:
                self.layer_summary.set_no_layer("Nenhum arquivo selecionado")
                return
            self.inspection, self.validation = self.controller.inspect_path(path)
            self._populate_internal_layers()
            self._show_inspection_summary()
            self.validation_widget.set_messages(self.validation.messages)
            return

        layer = self.selected_layer()
        if not layer:
            self.layer_summary.set_no_layer()
            return
        self.layer_summary.set_layer(layer)
        info = self.controller.inspect_layer(layer)
        messages = []
        if not info["crs_authid"]:
            messages.append({"severity": "error", "code": "CRS_MISSING", "message": "CRS ausente ou desconhecido.", "feature_id": None})
        elif layer.crs().isGeographic():
            messages.append({"severity": "warning", "code": "CRS_GEOGRAPHIC", "message": "CRS geografico; sera reprojetado para o CRS mestre.", "feature_id": None})
        self.validation_widget.set_messages(messages)

    def _show_inspection_summary(self):
        report = self.inspection
        self.layer_summary.lbl_name.setText(Path(report.source_path).name)
        self.layer_summary.lbl_source.setText(report.source_path)
        self.layer_summary.lbl_type.setText(report.geometry_type or report.format or "-")
        self.layer_summary.lbl_crs.setText(report.crs_authid or "desconhecido")
        self.layer_summary.lbl_features.setText(str(report.feature_count) if report.feature_count is not None else "-")
        self.layer_summary.lbl_area.setText("Calculada apos importacao")
        self.layer_summary.lbl_fields.setText(", ".join(report.fields) if report.fields else "-")

    def _populate_internal_layers(self):
        self.combo_internal.blockSignals(True)
        self.combo_internal.clear()
        self.internal_layers = []
        if self.inspection:
            self.internal_layers = [
                layer
                for layer in self.inspection.layers
                if layer.get("name")
            ]
        for layer in self.internal_layers:
            label = layer.get("name")
            if layer.get("geometry_type"):
                label = f"{label} ({layer.get('geometry_type')})"
            self.combo_internal.addItem(label, layer.get("name"))
        has_internal = bool(self.internal_layers)
        self.lbl_internal.setVisible(has_internal)
        self.combo_internal.setVisible(has_internal)
        self.combo_internal.blockSignals(False)

    def selected_internal_layer(self):
        if self.combo_internal.isVisible() and self.combo_internal.count() > 0:
            return self.combo_internal.currentData()
        return None

    def import_selected(self):
        self.progress.setVisible(True)
        self.progress.setValue(10)
        try:
            data_type = self.combo_data_type.currentText()
            if self.radio_file.isChecked():
                path = self.inp_file.text().strip()
                if not path:
                    QMessageBox.warning(self, "FortSmart Precision", "Selecione um arquivo.")
                    return
                self.progress.setValue(40)
                if self.internal_layers and not self.selected_internal_layer():
                    QMessageBox.warning(self, "FortSmart Precision", "Selecione a camada interna antes de importar.")
                    return
                self.result, preview = self.controller.import_file(
                    self.project_root,
                    path,
                    data_type,
                    internal_layer=self.selected_internal_layer(),
                )
            else:
                layer = self.selected_layer()
                if not isinstance(layer, QgsVectorLayer):
                    QMessageBox.warning(self, "FortSmart Precision", "Selecione uma camada vetorial.")
                    return
                self.progress.setValue(40)
                self.result, preview = self.controller.import_layer(self.project_root, layer, data_type)

            self.progress.setValue(90)
            if self.result.status == "INVALID":
                self.validation_widget.set_messages(self.result.validation.messages)
                QMessageBox.warning(self, "FortSmart Precision", "Importacao bloqueada. Veja os erros na tabela.")
                return
            QMessageBox.information(
                self,
                "FortSmart Precision",
                f"Importacao concluida.\nStatus: {self.result.status}\nCamada destino: {self.result.output_layer}",
            )
            self.progress.setValue(100)
            self.accept()
        except Exception as exc:
            QMessageBox.critical(self, "FortSmart Precision", f"Erro na importacao:\n{exc}")
        finally:
            self.progress.setVisible(False)


# Compatibilidade com a versao anterior do painel.
ActiveLayerImportDialog = ImportWizard
