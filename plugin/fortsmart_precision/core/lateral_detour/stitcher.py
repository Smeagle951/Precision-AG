# -*- coding: utf-8 -*-
"""Costura local: antes + transicao + contorno + transicao + depois."""

from __future__ import annotations

import math

from shapely.geometry import LineString
from shapely.ops import substring

from ...domain.obstacle_strategy import GEOMETRY_EPSILON

WORK_ON = "WORK_ON"
WORK_OFF = "WORK_OFF"


def _extend(target: list, coords) -> None:
    for xy in coords:
        point = (float(xy[0]), float(xy[1]))
        if not target or math.hypot(point[0] - target[-1][0], point[1] - target[-1][1]) > GEOMETRY_EPSILON:
            target.append(point)


def _original_piece(path: LineString, start: float, end: float) -> list:
    if end - start <= GEOMETRY_EPSILON:
        return []
    piece = substring(path, start, end)
    return list(piece.coords) if piece.geom_type == "LineString" else []


def stitch_local_detour(path: LineString, sections) -> LineString:
    """Substitui somente os trechos [s_start, s_end] de cada desvio."""
    coords: list = []
    cursor = 0.0
    for section in sorted(sections, key=lambda item: item.s_start):
        _extend(coords, _original_piece(path, cursor, section.s_start))
        _extend(coords, section.coords)
        cursor = section.s_end
    _extend(coords, _original_piece(path, cursor, path.length))
    return LineString(coords)


def split_work_segments(path: LineString, sections, planting_during_detour: bool) -> list[tuple[str, LineString]]:
    """Trechos WORK_ON/WORK_OFF do caminho final."""
    if planting_during_detour or not sections:
        return [(WORK_ON, stitch_local_detour(path, sections))]
    result: list[tuple[str, LineString]] = []
    cursor = 0.0
    for section in sorted(sections, key=lambda item: item.s_start):
        before = _original_piece(path, cursor, section.s_start)
        if len(before) >= 2:
            result.append((WORK_ON, LineString(before)))
        detour: list = []
        _extend(detour, section.coords)
        result.append((WORK_OFF, LineString(detour)))
        cursor = section.s_end
    after = _original_piece(path, cursor, path.length)
    if len(after) >= 2:
        result.append((WORK_ON, LineString(after)))
    return result
