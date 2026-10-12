# -*- coding: utf-8 -*-
"""Camadas temporarias FORTSMART_ROUTE_WARNINGS (pontos + segmentos), so de leitura da rota.

Recriadas a cada validacao; nunca tocam as camadas de origem.
"""

from __future__ import annotations

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsPointXY,
    QgsRendererCategory,
    QgsVectorLayer,
)

from ..core.layer_roles import PREVIEW_SECTION, TEMPORARY_PREVIEW_PROPERTY
from ..validator.route_geometry import line_parts
from ..validator.validation_result import ValidationResult
from ..validator.warning_model import RouteWarning, Severity

WARNING_LAYER_NAME = "FORTSMART_ROUTE_WARNINGS"
WARNING_SEGMENT_LAYER_NAME = "FORTSMART_ROUTE_WARNINGS_SEGMENTS"
WARNING_LAYER_PROPERTY = "fortsmart_route_warnings"
SEVERITY_COLORS = {
    Severity.CRITICAL: QColor(220, 0, 0),
    Severity.WARNING: QColor(255, 140, 0),
    Severity.INFO: QColor(30, 110, 230),
}
FIELDS = (
    ("warning_id", QVariant.String),
    ("warning_type", QVariant.String),
    ("severity", QVariant.String),
    ("pass_id", QVariant.String),
    ("related_id", QVariant.String),
    ("message", QVariant.String),
    ("expected", QVariant.Double),
    ("actual", QVariant.Double),
    ("difference", QVariant.Double),
    ("status", QVariant.String),
    ("start_m", QVariant.Double),
    ("end_m", QVariant.Double),
)
MAP_TIP = (
    "<b>[% \"warning_type\" %]</b> ([% \"severity\" %])<br>"
    "Passada: [% \"pass_id\" %] [% \"related_id\" %]<br>"
    "[% replace(\"message\", '\\n', '<br>') %]<br>Status: [% \"status\" %]"
)


def warning_anchor(warning: RouteWarning):
    """Ponto do aviso no mapa: o proprio ponto ou o meio do trecho afetado."""
    geometry = warning.geometry
    if geometry is None or geometry.is_empty:
        return None
    if geometry.geom_type == "Point":
        return geometry
    parts = line_parts(geometry)
    if parts:
        longest = max(parts, key=lambda part: part.length)
        return longest.interpolate(0.5, normalized=True)
    return geometry.representative_point()


def _attributes(warning: RouteWarning) -> list:
    return [
        warning.id,
        warning.warning_type.value,
        warning.severity.value,
        warning.pass_id,
        warning.related_pass_id or warning.obstacle_id,
        warning.message,
        warning.expected_value,
        warning.actual_value,
        warning.difference,
        warning.status.value,
        warning.distance_m,
        warning.end_distance_m,
    ]


def _memory_layer(geometry: str, name: str, crs) -> QgsVectorLayer:
    layer = QgsVectorLayer(f"{geometry}?crs={crs.authid()}", name, "memory")
    layer.dataProvider().addAttributes([QgsField(field_name, kind) for field_name, kind in FIELDS])
    layer.updateFields()
    layer.setCustomProperty(TEMPORARY_PREVIEW_PROPERTY, True)
    layer.setCustomProperty(WARNING_LAYER_PROPERTY, True)
    layer.setMapTipTemplate(MAP_TIP)
    return layer


def _style(layer: QgsVectorLayer, points: bool) -> None:
    categories = []
    for severity, color in SEVERITY_COLORS.items():
        if points:
            symbol = QgsMarkerSymbol.createSimple(
                {"name": "triangle" if severity is not Severity.INFO else "circle", "size": "4",
                 "color": color.name(), "outline_color": "black"}
            )
        else:
            symbol = QgsLineSymbol.createSimple({"line_color": color.name(), "line_width": "1.4"})
        categories.append(QgsRendererCategory(severity.value, symbol, severity.value))
    layer.setRenderer(QgsCategorizedSymbolRenderer("severity", categories))


def build_warning_layers(result: ValidationResult, crs) -> tuple[QgsVectorLayer, QgsVectorLayer]:
    """Um ponto por aviso + o trecho afetado (avisos lineares) na camada de segmentos."""
    points = _memory_layer("Point", WARNING_LAYER_NAME, crs)
    segments = _memory_layer("MultiLineString", WARNING_SEGMENT_LAYER_NAME, crs)
    point_features, segment_features = [], []
    for warning in result.warnings:
        anchor = warning_anchor(warning)
        if anchor is None:
            continue
        feature = QgsFeature(points.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(anchor.x, anchor.y)))
        feature.setAttributes(_attributes(warning))
        point_features.append(feature)
        lines = [list(part.coords) for part in line_parts(warning.geometry)]
        if lines:
            segment = QgsFeature(segments.fields())
            segment.setGeometry(
                QgsGeometry.fromMultiPolylineXY([[QgsPointXY(x, y) for x, y, *_ in line] for line in lines])
            )
            segment.setAttributes(_attributes(warning))
            segment_features.append(segment)
    points.dataProvider().addFeatures(point_features)
    segments.dataProvider().addFeatures(segment_features)
    for layer, is_point in ((points, True), (segments, False)):
        layer.updateExtents()
        _style(layer, is_point)
    return points, segments


class RouteWarningLayers:
    """Mantem no projeto so a ultima validacao (camadas anteriores sao removidas)."""

    def __init__(self, project):
        self.project = project
        self.layer_ids: list[str] = []

    def layers(self) -> list[QgsVectorLayer]:
        return [layer for layer in (self.project.mapLayer(i) for i in self.layer_ids) if layer is not None]

    def show(self, result: ValidationResult, crs) -> tuple[QgsVectorLayer, QgsVectorLayer]:
        self.remove()
        points, segments = build_warning_layers(result, crs)
        root = self.project.layerTreeRoot()
        group = root.findGroup(PREVIEW_SECTION) or root.insertGroup(0, PREVIEW_SECTION)
        for layer in (segments, points):
            self.project.addMapLayer(layer, False)
            group.insertLayer(0, layer)
        self.layer_ids = [points.id(), segments.id()]
        return points, segments

    def sync_status(self, result: ValidationResult) -> None:
        """Status alterado no painel vai para o atributo (sem sessao de edicao)."""
        status = {item.id: item.status.value for item in result.warnings}
        for layer in self.layers():
            index = layer.fields().indexOf("status")
            changes = {
                feature.id(): {index: status[feature["warning_id"]]}
                for feature in layer.getFeatures()
                if feature["warning_id"] in status and feature["status"] != status[feature["warning_id"]]
            }
            if changes:
                layer.dataProvider().changeAttributeValues(changes)
                layer.triggerRepaint()

    def remove(self) -> None:
        existing = [i for i in self.layer_ids if self.project.mapLayer(i) is not None]
        if existing:
            self.project.removeMapLayers(existing)
        self.layer_ids = []
