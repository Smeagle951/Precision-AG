# -*- coding: utf-8 -*-
"""Estrategia CURVA: offsets paralelos da curva mestre explicita, pelo motor existente."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import atan2, hypot, pi, radians

from shapely.geometry import Polygon as ShapelyPolygon

from ..core.parallel_pass_engine import ParallelPassError, ParallelPassParams, generate_parallel_passes
from .field_context import FieldContext
from .models import (
    CURVE_REFERENCE_REQUIRED,
    CURVE_STRATEGY_INVALID,
    Point,
    StrategyAnalysisError,
    StrategyCandidate,
    StrategyLine,
    StrategyTolerances,
    StrategyType,
)
from .strategy_validator import reference_curve_problems

CURVE_CANDIDATE_ID = "CURVE_REFERENCE"

CURVE_SOURCE_AUTO = "auto"
CURVE_SOURCE_AB = "ab"
CURVE_SOURCE_BOUNDARY = "boundary"
CURVE_SOURCE_LAYER = "layer"
CURVE_SOURCE_LABELS = {
    CURVE_SOURCE_AB: "curva A/B atual",
    CURVE_SOURCE_BOUNDARY: "borda do talhão",
    CURVE_SOURCE_LAYER: "linha selecionada",
}


@dataclass(frozen=True)
class CurveReference:
    points: tuple[Point, ...]
    source: str
    reference_id: str = ""
    description: str = ""


def ab_curve_usable(points, tolerances: StrategyTolerances) -> bool:
    return len(points) >= 3 and not reference_curve_problems(points, tolerances.geometry_tolerance_m)


def _wrap(angle: float) -> float:
    while angle <= -pi:
        angle += 2 * pi
    while angle > pi:
        angle -= 2 * pi
    return angle


def boundary_reference_curve(
    polygons,
    *,
    simplify_tolerance_m: float = 1.0,
    max_vertex_turn_deg: float = 45.0,
    max_heading_span_deg: float = 100.0,
    max_vertices: int = 600,
) -> tuple[Point, ...]:
    """Trecho continuo mais longo da borda sem quina forte nem virada total excessiva.

    Quinas (> max_vertex_turn_deg) quebram o trecho; o rumo acumulado nao pode
    variar mais que max_heading_span_deg, para os offsets nao dobrarem sobre si.
    """
    shapes = [ShapelyPolygon(outer, holes) for outer, holes in polygons if len(outer) >= 4]
    if not shapes:
        return ()
    shape = max(shapes, key=lambda item: item.area)
    tolerance = simplify_tolerance_m
    ring = list(shape.exterior.simplify(tolerance, preserve_topology=False).coords)[:-1]
    while len(ring) > max_vertices:
        tolerance *= 2.0
        ring = list(shape.exterior.simplify(tolerance, preserve_topology=False).coords)[:-1]
    count = len(ring)
    if count < 3:
        return ()
    headings = []
    lengths = []
    for index in range(count):
        a, b = ring[index], ring[(index + 1) % count]
        headings.append(atan2(b[1] - a[1], b[0] - a[0]))
        lengths.append(hypot(b[0] - a[0], b[1] - a[1]))
    max_turn = radians(max_vertex_turn_deg)
    max_span = radians(max_heading_span_deg)
    best = (0.0, 0, 0)
    for start in range(count):
        cumulative = low = high = 0.0
        length = lengths[start]
        segments = 1
        for step in range(1, count):
            index = (start + step) % count
            turn = _wrap(headings[index] - headings[(index - 1) % count])
            if abs(turn) > max_turn:
                break
            cumulative += turn
            low, high = min(low, cumulative), max(high, cumulative)
            if high - low > max_span:
                break
            length += lengths[index]
            segments += 1
        if length > best[0]:
            best = (length, start, segments)
    _length, start, segments = best
    return tuple(tuple(ring[(start + offset) % count]) for offset in range(segments + 1))


def choose_curve_reference(
    source: str,
    *,
    ab_points=(),
    boundary_polygons=(),
    layer_points=(),
    layer_id: str = "",
    tolerances: StrategyTolerances | None = None,
) -> CurveReference:
    """Automatica: curva A/B quando ela e curva valida; senao a borda do talhao."""
    tolerances = tolerances or StrategyTolerances()
    if source == CURVE_SOURCE_AUTO:
        source = CURVE_SOURCE_AB if ab_curve_usable(tuple(ab_points), tolerances) else CURVE_SOURCE_BOUNDARY
    if source == CURVE_SOURCE_AB:
        points = tuple(ab_points) if len(ab_points) >= 3 else ()
        return CurveReference(points, source, "AB", CURVE_SOURCE_LABELS[source])
    if source == CURVE_SOURCE_BOUNDARY:
        points = boundary_reference_curve(boundary_polygons)
        return CurveReference(points, source, "BOUNDARY", CURVE_SOURCE_LABELS[source])
    if source == CURVE_SOURCE_LAYER:
        return CurveReference(tuple(layer_points), source, layer_id, CURVE_SOURCE_LABELS[source])
    raise ValueError(f"Origem de curva desconhecida: {source}")


def with_curve_reference(context: FieldContext, reference: CurveReference) -> FieldContext:
    return replace(context, reference_curve=tuple(reference.points), reference_id=reference.reference_id)


def generate_curve_candidate(context: FieldContext, tolerances: StrategyTolerances) -> StrategyCandidate:
    """A curva e copiada (tupla imutavel); a camada de referencia nunca e alterada."""
    reference = tuple(tuple(point) for point in context.reference_curve)
    if len(reference) < 2:
        raise StrategyAnalysisError(CURVE_REFERENCE_REQUIRED)
    candidate = StrategyCandidate(
        candidate_id=CURVE_CANDIDATE_ID,
        strategy_type=StrategyType.CURVE,
        lines=(),
        reference_id=context.reference_id,
    )
    problems = reference_curve_problems(reference, tolerances.geometry_tolerance_m)
    if problems:
        candidate.valid = False
        candidate.warnings.extend(f"{CURVE_STRATEGY_INVALID}: {problem}" for problem in problems)
        return candidate
    try:
        passes = generate_parallel_passes(
            ParallelPassParams(
                polygons=context.work_area,
                ab_start=reference[0],
                ab_end=reference[-1],
                pass_spacing_m=context.pass_spacing_m,
                operation_width_m=context.operation_width_m,
                extension_m=context.extension_m,
                operation_id=context.operation_id,
                master_path=reference,
                clip_boundary=context.operational_boundary,
            )
        )
    except (ParallelPassError, ValueError) as exc:
        candidate.valid = False
        candidate.warnings.append(f"{CURVE_STRATEGY_INVALID}: {exc}")
        return candidate
    candidate.lines = tuple(
        StrategyLine(
            points=tuple(item.line_points()),
            pass_no=item.pass_no,
            length_m=item.length_m,
            spacing_m=item.spacing_m,
            width_m=item.width_m,
        )
        for item in passes
    )
    return candidate
