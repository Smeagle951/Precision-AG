# -*- coding: utf-8 -*-
"""Widget de resumo da camada ativa/selecionada."""

from __future__ import annotations

from qgis.PyQt.QtWidgets import QFormLayout, QGroupBox, QLabel
from qgis.core import QgsRasterLayer, QgsVectorLayer, QgsWkbTypes


class LayerSummaryWidget(QGroupBox):
    def __init__(self, title="CAMADA", parent=None):
        super().__init__(title, parent)
        layout = QFormLayout(self)
        self.lbl_name = QLabel("-")
        self.lbl_source = QLabel("-")
        self.lbl_type = QLabel("-")
        self.lbl_crs = QLabel("-")
        self.lbl_features = QLabel("-")
        self.lbl_area = QLabel("-")
        self.lbl_fields = QLabel("-")
        self.lbl_source.setWordWrap(True)
        self.lbl_fields.setWordWrap(True)
        layout.addRow("Nome:", self.lbl_name)
        layout.addRow("Fonte:", self.lbl_source)
        layout.addRow("Tipo:", self.lbl_type)
        layout.addRow("CRS:", self.lbl_crs)
        layout.addRow("Feicoes:", self.lbl_features)
        layout.addRow("Area:", self.lbl_area)
        layout.addRow("Campos:", self.lbl_fields)

    def set_no_layer(self, message="Nenhuma camada vetorial selecionada"):
        self.lbl_name.setText("-")
        self.lbl_source.setText(message)
        self.lbl_type.setText("-")
        self.lbl_crs.setText("-")
        self.lbl_features.setText("-")
        self.lbl_area.setText("-")
        self.lbl_fields.setText("-")

    def set_layer(self, layer):
        if isinstance(layer, QgsRasterLayer):
            self.lbl_name.setText(layer.name())
            self.lbl_source.setText(layer.source())
            self.lbl_type.setText("Raster")
            self.lbl_crs.setText(layer.crs().authid() or "desconhecido")
            self.lbl_features.setText("-")
            self.lbl_area.setText("-")
            self.lbl_fields.setText("-")
            return

        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            self.set_no_layer("Camada invalida ou nao vetorial")
            return

        self.lbl_name.setText(layer.name())
        self.lbl_source.setText(layer.source())
        self.lbl_type.setText(QgsWkbTypes.displayString(layer.wkbType()))
        self.lbl_crs.setText(layer.crs().authid() or "desconhecido")
        self.lbl_features.setText(str(layer.featureCount()))
        self.lbl_area.setText(self._area_text(layer))
        fields = [field.name() for field in layer.fields()]
        self.lbl_fields.setText(", ".join(fields) if fields else "-")

    def _area_text(self, layer):
        if QgsWkbTypes.geometryType(layer.wkbType()) != QgsWkbTypes.PolygonGeometry:
            return "-"
        if not layer.crs().isValid():
            return "CRS desconhecido"
        if layer.crs().isGeographic():
            return "Requer reprojecao"
        total = 0.0
        for feature in layer.getFeatures():
            geom = feature.geometry()
            if geom and not geom.isEmpty():
                total += geom.area()
        return f"{total / 10000:.4f} ha"

