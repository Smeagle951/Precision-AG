# -*- coding: utf-8 -*-
"""Extracao de vertices de linhas/curvas QGIS para A-B e guiamento."""

from __future__ import annotations

from qgis.core import QgsGeometry, QgsWkbTypes

from ..domain.guidance_reference import classify_guidance_mode


def extract_line_vertices(geometry: QgsGeometry) -> list[tuple[float, float]]:
    """
    Extrai vertices 2D de LineString, MultiLineString, CircularString,
    CompoundCurve e variantes com Z/M.

    Curvas sao densificadas via curveToLine antes da leitura.
    """
    if geometry is None or geometry.isEmpty():
        return []

    geom = QgsGeometry(geometry)
    try:
        geom.get().dropZValue()
        geom.get().dropMValue()
    except Exception:
        pass

    wkb = geom.wkbType()
    if QgsWkbTypes.isCurvedType(wkb):
        try:
            curve = geom.constGet()
            linear = curve.curveToLine()
            geom = QgsGeometry(linear.clone())
        except Exception:
            converted = geom.convertToType(QgsWkbTypes.LineGeometry, geom.isMultipart())
            if converted and not converted.isEmpty():
                geom = converted

    geom_type = QgsWkbTypes.geometryType(geom.wkbType())
    if geom_type != QgsWkbTypes.LineGeometry:
        converted = geom.convertToType(QgsWkbTypes.LineGeometry, False)
        if converted is None or converted.isEmpty():
            converted = geom.convertToType(QgsWkbTypes.LineGeometry, True)
        if converted is None or converted.isEmpty():
            return []
        geom = converted

    points: list[tuple[float, float]] = []
    if geom.isMultipart():
        parts = geom.asMultiPolyline()
        if not parts:
            return []
        part = max(parts, key=len)
        points = [(float(p.x()), float(p.y())) for p in part]
    else:
        poly = geom.asPolyline()
        points = [(float(p.x()), float(p.y())) for p in poly]

    cleaned: list[tuple[float, float]] = []
    for pt in points:
        if not cleaned or (abs(cleaned[-1][0] - pt[0]) > 1e-9 or abs(cleaned[-1][1] - pt[1]) > 1e-9):
            cleaned.append(pt)
    return cleaned


guidance_mode_from_points = classify_guidance_mode
