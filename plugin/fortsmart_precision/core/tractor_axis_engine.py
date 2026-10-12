# -*- coding: utf-8 -*-
"""Eixos retos do trator: paralelos a A-B, independentes e sem manobras."""

from __future__ import annotations

from dataclasses import dataclass

from .line_geometry import (
    MultiPolygon,
    Point,
    Segment,
    add,
    build_processing_boundary,
    clip_infinite_line_to_multipolygon,
    dot,
    mul,
    normalize,
    perpendicular_left,
    sub,
)


class TractorAxisError(ValueError):
    pass


@dataclass(frozen=True)
class TractorAxis:
    pass_no: int
    source_id: str
    segment_index: int
    spacing_m: float
    width_m: float
    offset_m: float
    path_points: tuple[Point, Point]


def generate_straight_tractor_axes(
    passes,
    *,
    ab_start: Point,
    ab_end: Point,
    operational_boundary: MultiPolygon,
    extension_m: float,
    minimum_length_m: float = 0.05,
) -> list[TractorAxis]:
    """Intersecciona retas paralelas infinitas com talhao + margem externa."""
    if not operational_boundary:
        raise TractorAxisError("Limite operacional vazio para gerar linha do trator.")
    if extension_m < 0:
        raise TractorAxisError("Margem externa nao pode ser negativa.")
    try:
        direction = normalize(sub(ab_end, ab_start))
    except ValueError as exc:
        raise TractorAxisError("Linha A-B curta demais para definir o azimute.") from exc
    normal_left = perpendicular_left(direction)
    processing = build_processing_boundary(operational_boundary, extension_m)
    axes: list[TractorAxis] = []
    for traffic in passes:
        base = add(ab_start, mul(normal_left, float(traffic.offset_m)))
        segments = clip_infinite_line_to_multipolygon(base, direction, processing)
        valid = [segment for segment in segments if segment.length >= minimum_length_m]
        for segment_index, segment in enumerate(valid, start=1):
            start, end = segment.start, segment.end
            if dot(sub(end, start), direction) < 0:
                start, end = end, start
            axes.append(
                TractorAxis(
                    pass_no=int(traffic.pass_no),
                    source_id=str(traffic.fs_id),
                    segment_index=segment_index,
                    spacing_m=float(traffic.spacing_m),
                    width_m=float(traffic.width_m),
                    offset_m=float(traffic.offset_m),
                    path_points=(start, end),
                )
            )
    axes.sort(key=lambda item: (item.offset_m, item.pass_no, item.segment_index))
    return axes

