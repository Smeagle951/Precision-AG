# -*- coding: utf-8 -*-
"""Geracao de faixas de cobertura a partir de passadas centrais."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from .line_geometry import Point, Ring, add, close_ring, mul, normalize, perpendicular_left, sub
from .parallel_pass_engine import ParallelPass


class CoverageStripError(ValueError):
    """Erro de configuracao de faixa de cobertura."""


@dataclass(frozen=True)
class CoverageStrip:
    fs_id: str
    pass_no: int
    operation_id: str
    width_m: float
    half_left_m: float
    half_right_m: float
    ring: Ring

    def attributes(self) -> dict[str, object]:
        return {
            "fs_id": self.fs_id,
            "pass_no": self.pass_no,
            "operation_id": self.operation_id,
            "width_m": self.width_m,
            "half_left_m": self.half_left_m,
            "half_right_m": self.half_right_m,
        }


def build_coverage_strip(
    pass_line: ParallelPass,
    half_left_m: float | None = None,
    half_right_m: float | None = None,
) -> CoverageStrip:
    left = pass_line.half_width_m if half_left_m is None else half_left_m
    right = pass_line.half_width_m if half_right_m is None else half_right_m
    if left <= 0 or right <= 0:
        raise CoverageStripError("Meias larguras da faixa devem ser maiores que zero.")

    segment = pass_line.clipped_segment
    direction = normalize(sub(segment.end, segment.start))
    normal_left = perpendicular_left(direction)
    start_left = add(segment.start, mul(normal_left, left))
    end_left = add(segment.end, mul(normal_left, left))
    end_right = add(segment.end, mul(normal_left, -right))
    start_right = add(segment.start, mul(normal_left, -right))
    return CoverageStrip(
        fs_id=str(uuid4()),
        pass_no=pass_line.pass_no,
        operation_id=pass_line.operation_id,
        width_m=left + right,
        half_left_m=left,
        half_right_m=right,
        ring=close_ring([start_left, end_left, end_right, start_right]),
    )


def build_coverage_strips(
    passes: list[ParallelPass],
    half_left_m: float | None = None,
    half_right_m: float | None = None,
) -> list[CoverageStrip]:
    return [
        build_coverage_strip(pass_line, half_left_m=half_left_m, half_right_m=half_right_m)
        for pass_line in passes
    ]
