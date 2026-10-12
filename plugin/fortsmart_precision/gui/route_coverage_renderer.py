# -*- coding: utf-8 -*-
"""Camada temporaria FORTSMART_SIMULATION_COVERAGE: uma feicao por passada, semitransparente.

A feicao da passada ativa tem a geometria atualizada (nao cria poligono por
quadro). Cada passada e desenhada separada, entao o transpasse soma a
transparencia e fica mais intenso. Nunca toca as camadas de origem.
"""

from __future__ import annotations

from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsFeature,
    QgsFillSymbol,
    QgsGeometry,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
)

from ..core.coverage_state import CoverageState, PassCoverage
from ..core.layer_roles import PREVIEW_SECTION, TEMPORARY_PREVIEW_PROPERTY

COVERAGE_LAYER_NAME = "FORTSMART_SIMULATION_COVERAGE"
COVERAGE_LAYER_PROPERTY = "fortsmart_simulation_coverage"
COVERAGE_OPACITIES = (0.05, 0.10, 0.15, 0.20)
DEFAULT_COVERAGE_OPACITY = 0.10
COVERAGE_COLOR = QColor(0, 170, 255)
FIELDS = (
    ("pass_id", "string"),
    ("pass_index", "integer"),
    ("status", "string"),
    ("distance_m", "double"),
    ("area_m2", "double"),
)


def coverage_symbol(opacity: float) -> QgsFillSymbol:
    color = QColor(COVERAGE_COLOR)
    color.setAlphaF(opacity)
    symbol = QgsFillSymbol.createSimple({"style": "solid", "outline_style": "no"})
    symbol.setColor(color)
    return symbol


def _geometry(item: PassCoverage) -> QgsGeometry:
    return QgsGeometry() if item.geometry.is_empty else QgsGeometry.fromWkt(item.geometry.wkt)


def _attributes(item: PassCoverage) -> list:
    return [
        item.pass_id,
        item.pass_index,
        "COMPLETED" if item.completed else "ACTIVE",
        round(item.distance_m, 3),
        round(item.area_m2, 3),
    ]


class CoverageRenderer:
    def __init__(self, project, crs, opacity: float = DEFAULT_COVERAGE_OPACITY):
        self.project = project
        self.crs = crs
        self.opacity = opacity
        self.layer_id: str | None = None
        self._features: dict[int, int] = {}
        self._drawn: dict[int, object] = {}

    @property
    def layer(self) -> QgsVectorLayer | None:
        return self.project.mapLayer(self.layer_id) if self.layer_id else None

    def _ensure_layer(self) -> QgsVectorLayer:
        layer = self.layer
        if layer is not None:
            return layer
        spec = "&".join(f"field={name}:{kind}" for name, kind in FIELDS)
        layer = QgsVectorLayer(f"Polygon?crs={self.crs.authid()}&{spec}", COVERAGE_LAYER_NAME, "memory")
        layer.setCustomProperty(TEMPORARY_PREVIEW_PROPERTY, True)
        layer.setCustomProperty(COVERAGE_LAYER_PROPERTY, True)
        layer.setRenderer(QgsSingleSymbolRenderer(coverage_symbol(self.opacity)))
        self.project.addMapLayer(layer, False)
        root = self.project.layerTreeRoot()
        group = root.findGroup(PREVIEW_SECTION) or root.insertGroup(0, PREVIEW_SECTION)
        group.insertLayer(0, layer)
        self.layer_id = layer.id()
        self._features.clear()
        self._drawn.clear()
        return layer

    def render(self, state: CoverageState) -> None:
        """Sincroniza a camada com o estado: so muda o que mudou desde o ultimo desenho."""
        current = {item.pass_index: item for item in state.passes() if not item.geometry.is_empty}
        if not current and self.layer is None:
            return
        layer = self._ensure_layer()
        provider = layer.dataProvider()
        gone = [index for index in self._features if index not in current]
        if gone:
            provider.deleteFeatures([self._features.pop(index) for index in gone])
            for index in gone:
                self._drawn.pop(index, None)
        geometries, attributes, new = {}, {}, []
        for index, item in current.items():
            if self._drawn.get(index) is item:
                continue
            self._drawn[index] = item
            fid = self._features.get(index)
            if fid is None:
                feature = QgsFeature(layer.fields())
                feature.setGeometry(_geometry(item))
                feature.setAttributes(_attributes(item))
                new.append((index, feature))
            else:
                geometries[fid] = _geometry(item)
                attributes[fid] = dict(enumerate(_attributes(item)))
        if geometries:
            provider.changeGeometryValues(geometries)
            provider.changeAttributeValues(attributes)
        if new:
            ok, added = provider.addFeatures([feature for _index, feature in new])
            if ok:
                for (index, _feature), feature in zip(new, added):
                    self._features[index] = feature.id()
        if gone or geometries or new:
            layer.updateExtents()
            layer.triggerRepaint()

    def set_opacity(self, opacity: float) -> None:
        self.opacity = opacity
        layer = self.layer
        if layer is not None:
            layer.setRenderer(QgsSingleSymbolRenderer(coverage_symbol(opacity)))
            layer.triggerRepaint()

    def clear(self) -> None:
        layer = self.layer
        if layer is not None and self._features:
            layer.dataProvider().deleteFeatures(list(self._features.values()))
            layer.updateExtents()
            layer.triggerRepaint()
        self._features.clear()
        self._drawn.clear()

    def remove(self) -> None:
        if self.layer is not None:
            self.project.removeMapLayer(self.layer_id)
        self.layer_id = None
        self._features.clear()
        self._drawn.clear()
