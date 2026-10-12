# -*- coding: utf-8 -*-
"""Ferramenta de mapa para capturar dois pontos A-B."""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.core import QgsPointXY, QgsWkbTypes
from qgis.gui import QgsMapTool, QgsRubberBand


class CaptureABLineTool(QgsMapTool):
    """Captura dois cliques no canvas e emite a linha A-B."""

    lineCaptured = pyqtSignal(QgsPointXY, QgsPointXY)

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.points: list[QgsPointXY] = []
        self.rubber_band = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self.rubber_band.setColor(QColor(255, 140, 0))
        self.rubber_band.setWidth(3)
        self.setCursor(Qt.CrossCursor)

    def canvasReleaseEvent(self, event):
        point = self.toMapCoordinates(event.pos())
        self.points.append(QgsPointXY(point))
        self._refresh_rubber_band()
        if len(self.points) == 2:
            self.lineCaptured.emit(self.points[0], self.points[1])
            self.points = []

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.reset()

    def deactivate(self):
        self.reset()
        super().deactivate()

    def reset(self):
        self.points = []
        self.rubber_band.reset(QgsWkbTypes.LineGeometry)

    def _refresh_rubber_band(self):
        self.rubber_band.reset(QgsWkbTypes.LineGeometry)
        for point in self.points:
            self.rubber_band.addPoint(point, False)
        self.rubber_band.show()
