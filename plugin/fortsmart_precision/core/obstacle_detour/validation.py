# -*- coding: utf-8 -*-
"""Validacao geometrica do desvio manual (CRS metrico)."""

from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np
from shapely.geometry import LineString, Point

from .models import (
    MSG_DUPLICATE_SEGMENT,
    MSG_EMPTY_GEOMETRY,
    MSG_INVADES_ZONE,
    MSG_INVALID_GEOMETRY,
    MSG_OVERLAP,
    MSG_SPIKE,
    MSG_SWATH_OUTSIDE_FIELD,
    Coord,
    other_obstacle_warning,
    outside_field_warning,
)

# Poligonos de buffer sao inscritos no circulo real; 3 cm cobre a corda.
CLEARANCE_TOLERANCE_M = 0.03
SIDE_TOLERANCE_M = 0.01
# Arcos do contorno giram ~3 graus por vertice; acima disso e ponta/bigode.
MAX_VERTEX_TURN_DEG = 25.0
SWATH_OVERLAP_TOLERANCE_M2 = 1e-3
OUTSIDE_FIELD_TOLERANCE_M = 0.01
DUPLICATE_PRECISION = 6


def vertex_turns_deg(coords: Iterable[Coord]) -> list[float]:
    arr = np.asarray(list(coords), dtype=float)
    if len(arr) < 3:
        return []
    delta = np.diff(arr, axis=0)
    headings = np.arctan2(delta[:, 1], delta[:, 0])
    turns = np.diff(headings)
    turns = (turns + math.pi) % (2.0 * math.pi) - math.pi
    return [abs(math.degrees(value)) for value in turns]


def has_duplicate_segment(coords: Iterable[Coord]) -> bool:
    seen: set[frozenset] = set()
    points = [(round(x, DUPLICATE_PRECISION), round(y, DUPLICATE_PRECISION)) for x, y in coords]
    for first, second in zip(points, points[1:]):
        if first == second:
            return True
        key = frozenset((first, second))
        if key in seen:
            return True
        seen.add(key)
    return False


def signed_offset(path: LineString, xy: Coord) -> float:
    """Distancia lateral assinada: positivo = esquerda do sentido de deslocamento."""
    station = path.project(Point(xy))
    window = min(0.5, path.length / 2.0)
    a = path.interpolate(max(0.0, station - window))
    b = path.interpolate(min(path.length, station + window))
    tx, ty = b.x - a.x, b.y - a.y
    norm = math.hypot(tx, ty) or 1.0
    foot = path.interpolate(station)
    return (tx * (xy[1] - foot.y) - ty * (xy[0] - foot.x)) / norm


def side_consistent(path: LineString, coords: Iterable[Coord], side: str) -> bool:
    """O trecho desviado fica inteiro do lado escolhido: nunca cruza a linha original."""
    sign = 1.0 if side == "LEFT" else -1.0
    return all(sign * signed_offset(path, xy) >= -SIDE_TOLERANCE_M for xy in coords)


def validate_lateral(
    original: LineString,
    final: LineString,
    section_coords: list[Coord],
    obstacle_core: Any,
    *,
    centerline_clearance_m: float,
    side: str,
) -> list[str]:
    """Mensagens de reprovacao do desvio lateral (lista vazia = valido)."""
    if final is None or final.is_empty or final.length <= 0:
        return [MSG_EMPTY_GEOMETRY]
    messages: list[str] = []
    if not final.is_valid or not final.is_simple:
        messages.append(MSG_INVALID_GEOMETRY)
    if final.distance(obstacle_core) < centerline_clearance_m - CLEARANCE_TOLERANCE_M:
        messages.append(MSG_INVADES_ZONE)
    if has_duplicate_segment(final.coords):
        messages.append(MSG_DUPLICATE_SEGMENT)
    if section_coords and not side_consistent(original, section_coords, side):
        messages.append(MSG_OVERLAP)
    if any(turn > MAX_VERTEX_TURN_DEG for turn in vertex_turns_deg(section_coords)):
        messages.append(MSG_SPIKE)
    return messages


def surroundings_warnings(
    changed: LineString | None,
    half_width_m: float,
    other_zones: Iterable[tuple[str, Any]] = (),
    field_area: Any = None,
    original: LineString | None = None,
) -> list[str]:
    """Avisos do trecho novo: zona de outro obstaculo e saida do talhao.

    `other_zones` = (id, zona de seguranca ja com raio + margem). Para o talhao
    so conta o que o desvio acrescenta fora do limite (linha de borda ja encosta).
    """
    if changed is None or changed.is_empty:
        return []
    half = max(half_width_m, 1e-6)
    messages: list[str] = []
    swath = changed.buffer(half, cap_style="flat")
    hit = [obstacle_id for obstacle_id, zone in other_zones if swath.intersection(zone).area > SWATH_OVERLAP_TOLERANCE_M2]
    if hit:
        messages.append(other_obstacle_warning(sorted(set(hit))))
    if field_area is not None and not field_area.is_empty:
        allowed = field_area
        original_swath = None
        if original is not None and not original.is_empty:
            allowed = field_area.union(original.buffer(1e-6))
            original_swath = original.buffer(half, cap_style="flat")
        outside = changed.difference(allowed).length
        swath_outside = swath.difference(field_area.buffer(OUTSIDE_FIELD_TOLERANCE_M))
        if original_swath is not None:
            swath_outside = swath_outside.difference(original_swath)
        if outside > OUTSIDE_FIELD_TOLERANCE_M:
            messages.append(outside_field_warning(outside))
        elif swath_outside.area > SWATH_OVERLAP_TOLERANCE_M2:
            messages.append(MSG_SWATH_OUTSIDE_FIELD)
    return messages


def validate_cut(parts: Iterable[LineString], safety_zone: Any, half_width_m: float) -> list[str]:
    """Trechos plantados: a barra da plantadeira nunca encosta na zona de seguranca."""
    parts = [part for part in parts if part is not None and not part.is_empty]
    if not parts:
        return [MSG_EMPTY_GEOMETRY]
    messages: list[str] = []
    if any(not part.is_valid or part.length <= 0 for part in parts):
        messages.append(MSG_INVALID_GEOMETRY)
    if any(has_duplicate_segment(part.coords) for part in parts):
        messages.append(MSG_DUPLICATE_SEGMENT)
    for part in parts:
        swath = part.buffer(max(half_width_m, 1e-6), cap_style="flat")
        if swath.intersection(safety_zone).area > SWATH_OVERLAP_TOLERANCE_M2:
            messages.append(MSG_INVADES_ZONE)
            break
    return messages
