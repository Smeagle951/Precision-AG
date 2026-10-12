# -*- coding: utf-8 -*-
"""Destaque no canvas do aviso selecionado e da passada relacionada (overlay, sem camadas)."""

from __future__ import annotations

from qgis.PyQt.QtGui import QColor
from qgis.core import QgsGeometry, QgsPointXY, QgsRectangle, QgsWkbTypes
from qgis.gui import QgsRubberBand

from ..validator.route_geometry import line_parts, point_parts
from ..validator.warning_model import RouteWarning
from .route_warning_layer import SEVERITY_COLORS

PASS_COLOR = QColor(255, 230, 0, 200)
RELATED_COLOR = QColor(0, 200, 255, 180)
MIN_ZOOM_SPAN_M = 40.0


def _lines(parts) -> QgsGeometry:
    polylines = [[QgsPointXY(x, y) for x, y, *_ in part] for part in parts if len(part) >= 2]
    return QgsGeometry.fromMultiPolylineXY(polylines) if polylines else QgsGeometry()


def warning_extent(warning: RouteWarning, pass_segments=()) -> QgsRectangle | None:
    """Area para centralizar: o trecho do aviso (ou a passada) com margem minima."""
    geometry = warning.geometry
    if geometry is not None and not geometry.is_empty:
        minx, miny, maxx, maxy = geometry.bounds
    else:
        points = [p for part in pass_segments for p in part]
        if not points:
            return None
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        minx, miny, maxx, maxy = min(xs), min(ys), max(xs), max(ys)
    cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
    half = max(maxx - minx, maxy - miny, MIN_ZOOM_SPAN_M) * 0.75
    return QgsRectangle(cx - half, cy - half, cx + half, cy + half)


class RouteWarningHighlighter:
    def __init__(self, canvas, crs):
        self.canvas = canvas
        self.crs = crs
        self.pass_band = self._band(QgsWkbTypes.LineGeometry, PASS_COLOR, 6)
        self.related_band = self._band(QgsWkbTypes.LineGeometry, RELATED_COLOR, 4)
        self.warning_band = self._band(QgsWkbTypes.LineGeometry, SEVERITY_COLORS[next(iter(SEVERITY_COLORS))], 5)
        self.point_band = self._band(QgsWkbTypes.PointGeometry, QColor(0, 0, 0), 2)
        self.point_band.setIconSize(16)
        self.point_band.setIcon(QgsRubberBand.ICON_CIRCLE)

    def _band(self, geometry_type, color, width):
        band = QgsRubberBand(self.canvas, geometry_type)
        band.setColor(color)
        band.setWidth(width)
        return band

    def bands(self) -> tuple[QgsRubberBand, ...]:
        return (self.pass_band, self.related_band, self.warning_band, self.point_band)

    def show(self, warnings, pass_segments: dict) -> None:
        """Passada principal em amarelo, relacionada em azul, trecho/ponto na cor da severidade."""
        self.clear()
        warnings = list(warnings)
        if not warnings:
            return
        first = warnings[0]
        self.pass_band.setToGeometry(_lines(pass_segments.get(first.pass_id, ())), self.crs)
        if first.related_pass_id:
            self.related_band.setToGeometry(_lines(pass_segments.get(first.related_pass_id, ())), self.crs)
        self.warning_band.setColor(SEVERITY_COLORS[first.severity])
        lines = [list(part.coords) for item in warnings for part in line_parts(item.geometry)]
        self.warning_band.setToGeometry(_lines(lines), self.crs)
        points = [p for item in warnings for p in point_parts(item.geometry)]
        if points:
            self.point_band.setToGeometry(
                QgsGeometry.fromMultiPointXY([QgsPointXY(p.x, p.y) for p in points]), self.crs
            )

    def clear(self) -> None:
        for band in self.bands():
            band.reset(self._type_of(band))

    def _type_of(self, band) -> int:
        return QgsWkbTypes.PointGeometry if band is self.point_band else QgsWkbTypes.LineGeometry

    def remove(self) -> None:
        for band in self.bands():
            band.reset(self._type_of(band))
            scene = self.canvas.scene()
            if scene is not None:
                scene.removeItem(band)
