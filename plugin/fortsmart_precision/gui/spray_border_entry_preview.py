# -*- coding: utf-8 -*-
"""Previa em rubber band do entra-e-sai (Fase 2: nada e persistido)."""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.core import QgsGeometry, QgsPointXY, QgsWkbTypes
from qgis.gui import QgsRubberBand

from ..core.spray_border_entry import STATUS_INFEASIBLE, BorderEntryPlan


class SprayBorderEntryPreview:
    def __init__(self, canvas):
        self.canvas = canvas
        self._bands: list = []

    def clear(self) -> None:
        for band in self._bands:
            try:
                band.reset()
                if self.canvas is not None:
                    self.canvas.scene().removeItem(band)
            except Exception:
                pass
        self._bands.clear()
        try:
            if self.canvas is not None:
                self.canvas.refresh()
        except Exception:
            pass

    def show(self, plan: BorderEntryPlan, *, component: str = "all", turn_id: str = "") -> None:
        self.clear()
        if self.canvas is None:
            return
        for conn in plan.connections:
            if conn.status == STATUS_INFEASIBLE or len(conn.points) < 2:
                continue
            if turn_id and conn.turn_id != turn_id:
                continue
            # Componentes separados comprovam que B-D vem da bordadura real,
            # em vez de uma curva livre ligando diretamente as passadas.
            for part, points, color, width in (
                ("exit", conn.exit_points, QColor(225, 105, 20, 240), 3),
                ("transit", conn.transit_points, QColor(35, 155, 75, 245), 4),
                ("entry", conn.entry_points, QColor(245, 175, 25, 240), 3),
            ):
                if component not in ("all", part):
                    continue
                band = self._line(points, color, width)
                if band is not None:
                    self._bands.append(band)
            for parts, point, color in (
                (("exit",), conn.a, QColor(225, 105, 20)),
                (("exit", "transit"), conn.b, QColor(35, 155, 75)),
                (("transit", "entry"), conn.d, QColor(35, 155, 75)),
                (("entry",), conn.e, QColor(245, 175, 25)),
            ):
                if component != "all" and component not in parts:
                    continue
                marker = self._point(point, color)
                if marker is not None:
                    self._bands.append(marker)
        try:
            self.canvas.refresh()
        except Exception:
            pass

    def _line(self, points, color, width):
        try:
            band = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
        except Exception:
            return None
        band.setColor(color)
        band.setWidth(width)
        try:
            band.setLineStyle(Qt.SolidLine)
        except Exception:
            pass
        geom = QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in points])
        band.setToGeometry(geom, None)
        return band

    def _point(self, point, color):
        if point is None:
            return None
        try:
            band = QgsRubberBand(self.canvas, QgsWkbTypes.PointGeometry)
        except Exception:
            return None
        band.setColor(color)
        band.setWidth(8)
        try:
            band.setIcon(QgsRubberBand.ICON_CIRCLE)
            band.setIconSize(10)
        except Exception:
            pass
        band.setToGeometry(QgsGeometry.fromPointXY(QgsPointXY(point[0], point[1])), None)
        return band
