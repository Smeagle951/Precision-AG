# -*- coding: utf-8 -*-
"""Overlay do simulador de rota no canvas (nao cria nem edita camadas do projeto).

Desenha so: passadas ja concluidas (cacheadas), trecho executado e trecho
restante da passada ativa e o marcador da maquina. Passadas planejadas
continuam aparecendo pela propria camada de origem.
"""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.core import QgsGeometry, QgsPointXY, QgsWkbTypes
from qgis.gui import QgsRubberBand

from ..core.route_simulation_engine import RouteSimulationEngine
from ..core.simulation_marker import machine_marker_outline

COMPLETED_COLOR = QColor(0, 140, 60)
EXECUTED_COLOR = QColor(0, 200, 80)
REMAINING_COLOR = QColor(255, 140, 0)
MACHINE_FILL = QColor(220, 30, 30, 200)
MACHINE_STROKE = QColor(90, 0, 0)


def _lines_geometry(parts) -> QgsGeometry:
    polylines = [[QgsPointXY(x, y) for x, y in part] for part in parts if len(part) >= 2]
    if not polylines:
        return QgsGeometry()
    return QgsGeometry.fromMultiPolylineXY(polylines)


class RouteSimulationRenderer:
    def __init__(self, canvas, crs):
        self.canvas = canvas
        self.crs = crs
        self.completed_band = self._band(QgsWkbTypes.LineGeometry, COMPLETED_COLOR, 3)
        self.executed_band = self._band(QgsWkbTypes.LineGeometry, EXECUTED_COLOR, 4)
        self.remaining_band = self._band(QgsWkbTypes.LineGeometry, REMAINING_COLOR, 2)
        self.remaining_band.setLineStyle(Qt.DashLine)
        self.machine_band = self._band(QgsWkbTypes.PolygonGeometry, MACHINE_STROKE, 2)
        self.machine_band.setFillColor(MACHINE_FILL)
        self._completed_count = -1

    def _band(self, geometry_type, color, width):
        band = QgsRubberBand(self.canvas, geometry_type)
        band.setColor(color)
        band.setWidth(width)
        return band

    def bands(self) -> tuple[QgsRubberBand, ...]:
        return (self.completed_band, self.executed_band, self.remaining_band, self.machine_band)

    def render(self, engine: RouteSimulationEngine) -> None:
        state = engine.state
        if state.completed_pass_count != self._completed_count:
            self._completed_count = state.completed_pass_count
            parts = [part for item in engine.completed_passes() for part in item.segments]
            self.completed_band.setToGeometry(_lines_geometry(parts), self.crs)
        self.executed_band.setToGeometry(_lines_geometry(engine.executed_active_parts()), self.crs)
        self.remaining_band.setToGeometry(_lines_geometry(engine.remaining_active_parts()), self.crs)
        profile = engine.machine_profile
        ring = machine_marker_outline(
            state.current_position, state.current_heading_deg, profile.width_m, profile.length_m
        )
        self.machine_band.setToGeometry(
            QgsGeometry.fromPolygonXY([[QgsPointXY(x, y) for x, y in ring]]), self.crs
        )

    def clear(self) -> None:
        for band in self.bands():
            band.reset(self._type_of(band))
        self._completed_count = -1

    def _type_of(self, band) -> int:
        return QgsWkbTypes.PolygonGeometry if band is self.machine_band else QgsWkbTypes.LineGeometry

    def remove(self) -> None:
        for band in self.bands():
            band.reset(self._type_of(band))
            scene = self.canvas.scene()
            if scene is not None:
                scene.removeItem(band)
