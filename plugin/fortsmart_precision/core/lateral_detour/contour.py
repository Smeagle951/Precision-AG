# -*- coding: utf-8 -*-
"""Entrada/saida no contorno e extracao apenas do arco necessario."""

from __future__ import annotations

import math

import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import substring

from ...domain.obstacle_strategy import GEOMETRY_EPSILON, DetourSide

Vector = tuple[float, float]


def unit(dx: float, dy: float) -> Vector:
    length = math.hypot(dx, dy)
    if length <= GEOMETRY_EPSILON:
        raise ValueError("Vetor de direcao nulo.")
    return dx / length, dy / length


def path_tangent(path: LineString, station: float, window: float = 0.5) -> Vector:
    length = path.length
    a = max(0.0, min(length, station - window))
    b = max(0.0, min(length, station + window))
    if b - a <= GEOMETRY_EPSILON:
        a, b = max(0.0, length - window), length
    pa, pb = path.interpolate(a), path.interpolate(b)
    return unit(pb.x - pa.x, pb.y - pa.y)


def find_entry_exit_points(path: LineString, contour: Polygon) -> tuple[float, float] | None:
    """Estacoes da primeira entrada e ultima saida do caminho no contorno.

    None quando o caminho comeca/termina dentro do contorno (sem espaco para
    desviar) ou nao cruza o contorno.
    """
    start, end = Point(path.coords[0]), Point(path.coords[-1])
    if contour.covers(start) or contour.covers(end):
        return None
    crossing = path.intersection(contour.exterior)
    if crossing.is_empty:
        return None
    points = shapely.get_coordinates(crossing)
    stations = sorted(path.project(Point(xy)) for xy in points)
    s_in, s_out = stations[0], stations[-1]
    if s_out - s_in <= GEOMETRY_EPSILON:
        return None
    return s_in, s_out


def calculate_pre_entry_point(path: LineString, s_in: float, approach_distance: float, lower_bound: float = 0.0) -> float:
    return max(lower_bound, s_in - approach_distance)


def calculate_post_exit_point(path: LineString, s_out: float, return_distance: float, upper_bound: float | None = None) -> float:
    limit = path.length if upper_bound is None else upper_bound
    return min(limit, s_out + return_distance)


def oriented_ring(contour: Polygon, side: DetourSide) -> LineString:
    """Esquerda do sentido de trabalho = horario; direita = anti-horario."""
    ccw = orient(contour, sign=1.0).exterior
    coords = list(ccw.coords)
    if side == DetourSide.LEFT:
        coords = coords[::-1]
    return LineString(coords)


def doubled_ring(ring: LineString) -> LineString:
    """Anel percorrido duas vezes: arcos que cruzam o ponto inicial."""
    coords = list(ring.coords)
    return LineString(coords + coords[1:])


def arc_span(ring: LineString, entry: Point, exit_: Point) -> tuple[float, float]:
    """Posicao inicial e comprimento do arco entre entrada e saida no anel."""
    perimeter = ring.length
    p_in = ring.project(entry)
    p_out = ring.project(exit_)
    span = (p_out - p_in) % perimeter
    if span <= GEOMETRY_EPSILON:
        span = perimeter
    return p_in, span


def extract_obstacle_contour(ring2: LineString, start: float, end: float) -> LineString | None:
    """Trecho do anel duplicado entre duas posicoes (nunca o anel inteiro)."""
    if end - start <= GEOMETRY_EPSILON:
        return None
    return substring(ring2, start, end)


def ring_tangent(ring2: LineString, position: float, window: float = 0.25) -> Vector:
    return path_tangent(ring2, position, window)
