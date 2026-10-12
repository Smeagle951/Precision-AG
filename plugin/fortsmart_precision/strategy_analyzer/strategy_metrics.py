# -*- coding: utf-8 -*-
"""Metricas objetivas de um candidato (CRS metrico do talhao; nunca geografico)."""

from __future__ import annotations

from math import hypot

from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from ..core.visual_coverage_engine import VisualCoverageError, simulate_visual_coverage
from .models import StrategyCandidate, StrategyLine, StrategyTolerances


def _shape(line: StrategyLine) -> LineString:
    return LineString(line.points)


def _circumradius(a, b, c) -> float | None:
    ab = hypot(b[0] - a[0], b[1] - a[1])
    bc = hypot(c[0] - b[0], c[1] - b[1])
    ca = hypot(a[0] - c[0], a[1] - c[1])
    twice_area = abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
    if twice_area <= 1e-9:
        return None
    return ab * bc * ca / (2.0 * twice_area)


def minimum_curve_radius(lines, *, min_chord_m: float) -> float | None:
    """Menor raio entre vertices consecutivos; trechos menores que min_chord_m sao agrupados."""
    best = None
    for line in lines:
        points = [line.points[0]]
        for point in line.points[1:]:
            if hypot(point[0] - points[-1][0], point[1] - points[-1][1]) >= min_chord_m:
                points.append(point)
        for a, b, c in zip(points, points[1:], points[2:]):
            radius = _circumradius(a, b, c)
            if radius is not None and (best is None or radius < best):
                best = radius
    return best


def crossing_count(shapes: list[LineString], tolerance_m: float) -> int:
    """Pares de passadas distintas que se cruzam (offsets corretos nunca se tocam)."""
    if len(shapes) < 2:
        return 0
    tree = STRtree(shapes)
    count = 0
    for index, shape in enumerate(shapes):
        for other in tree.query(shape):
            other = int(other)
            if other <= index:
                continue
            if shape.distance(shapes[other]) <= tolerance_m and shape.intersects(shapes[other]):
                count += 1
    return count


def apply_line_metrics(
    candidate: StrategyCandidate,
    allowed_shape: BaseGeometry,
    tolerances: StrategyTolerances,
    *,
    check_crossings: bool,
) -> StrategyCandidate:
    lines = candidate.lines
    shapes = [_shape(line) for line in lines]
    lengths = [shape.length for shape in shapes]
    candidate.line_count = len(lines)
    candidate.total_length_m = float(sum(lengths))
    candidate.average_length_m = candidate.total_length_m / len(lines) if lines else 0.0
    candidate.turn_count = max(0, len(lines) - 1)
    candidate.short_segment_count = sum(
        1 for length in lengths if length < tolerances.minimum_segment_length_m
    )
    candidate.self_intersection_count = sum(1 for shape in shapes if not shape.is_simple)
    candidate.crossing_count = (
        crossing_count(shapes, tolerances.geometry_tolerance_m) if check_crossings else 0
    )
    allowed = allowed_shape.buffer(tolerances.geometry_tolerance_m)
    candidate.boundary_exit_length_m = float(
        sum(shape.difference(allowed).length for shape in shapes if not shape.within(allowed))
    )
    return candidate


def apply_coverage_metrics(candidate: StrategyCandidate, analysis_area: BaseGeometry) -> StrategyCandidate:
    """Reutiliza o simulador visual (buffer W/2 por linha); nenhuma camada e criada."""
    if not candidate.lines:
        return candidate
    try:
        result = simulate_visual_coverage(
            [line.points for line in candidate.lines],
            work_width_m=candidate.lines[0].width_m,
            analysis_area=analysis_area if not analysis_area.is_empty else None,
        )
    except VisualCoverageError as exc:
        candidate.warnings.append(f"Cobertura não calculada: {exc}")
        return candidate
    metrics = result.metrics
    candidate.coverage_ha = round(metrics.covered_area_ha, 4)
    candidate.overlap_ha = round(metrics.overlap_area_ha, 4)
    candidate.gap_ha = None if metrics.gap_area_ha is None else round(metrics.gap_area_ha, 4)
    return candidate
