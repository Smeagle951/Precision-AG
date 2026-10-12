# -*- coding: utf-8 -*-
"""Metricas de cobertura / erro de plantio apos desvio."""

from __future__ import annotations

from ..domain.planting_kinematics import PlantingKinematics
from .line_geometry import Point, Segment, distance
from .obstacle_buffer_engine import ForbiddenRegion


def compute_coverage_impact(
    *,
    original_path: tuple[Point, ...],
    avoidance_path: tuple[Point, ...],
    region: ForbiddenRegion,
    kinematics: PlantingKinematics,
) -> tuple[float, float]:
    """
    Estima gap e sobreposicao em m2 de forma conservadora.

    Gap: faixa nao plantada aproximada pelo desvio lateral medio * comprimento do arco.
    Overlap: area das transicoes de entrada/saida onde paths se aproximam.
    """
    if len(original_path) < 2 or len(avoidance_path) < 2:
        return 0.0, 0.0

    original_len = _polyline_length(original_path)
    avoid_len = _polyline_length(avoidance_path)
    extra_len = max(0.0, avoid_len - original_len)

    # Gap aproximado: largura operacional * comprimento extra do desvio / 2
    # (faixa nao coberta entre path original e path desviado).
    mean_offset = _mean_lateral_offset(original_path, avoidance_path)
    gap = mean_offset * extra_len * 0.5

    # Overlap: transicoes curtas (entrada/saida) * espacamento tipico.
    transition_len = min(extra_len * 0.25, region.implement_clearance_radius_m)
    spacing = kinematics.row_spacing_m if kinematics.row_spacing_m > 0 else 0.5
    overlap = transition_len * spacing

    return round(gap, 3), round(overlap, 3)


def _polyline_length(points: tuple[Point, ...] | list[Point]) -> float:
    total = 0.0
    for a, b in zip(points, points[1:]):
        total += distance(a, b)
    return total


def _mean_lateral_offset(
    original: tuple[Point, ...],
    avoided: tuple[Point, ...],
) -> float:
    if len(original) < 2:
        return 0.0
    seg = Segment(original[0], original[-1])
    step = max(1, len(avoided) // 8)
    samples = list(avoided[::step]) or list(avoided)
    if not samples:
        return 0.0
    dists = [_point_line_distance(pt, seg) for pt in samples]
    return sum(dists) / len(dists)


def _point_line_distance(point: Point, segment: Segment) -> float:
    from .line_geometry import cross, hypot, sub

    dx = segment.end[0] - segment.start[0]
    dy = segment.end[1] - segment.start[1]
    length = hypot(dx, dy)
    if length <= 1e-9:
        return distance(point, segment.start)
    return abs(cross(sub(point, segment.start), (dx, dy))) / length
