# -*- coding: utf-8 -*-
"""Motor de linhas fisicas individuais dentro de cada passada."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from ..domain.machine_model import PlanterMachine
from .guidance_engine import TrafficPass
from .line_geometry import Point, Segment, add, clip_infinite_line_to_multipolygon, mul, normalize, perpendicular_left, sub


class RowEngineError(ValueError):
    """Erro no motor de linhas fisicas."""


@dataclass(frozen=True)
class PlantingRow:
    fs_id: str
    row_id: int
    pass_id: int
    machine_id: str
    spacing_m: float
    direction: str
    offset_m: float
    azimuth_deg: float
    segment: Segment
    path_points: tuple[Point, ...] = ()

    def line_points(self) -> tuple[Point, ...]:
        if self.path_points:
            return self.path_points
        return (self.segment.start, self.segment.end)

    def attributes(self) -> dict[str, object]:
        return {
            "fs_id": self.fs_id,
            "row_id": self.row_id,
            "pass_id": self.pass_id,
            "machine_id": self.machine_id,
            "spacing_m": self.spacing_m,
            "direction": self.direction,
            "offset_m": self.offset_m,
            "azimuth_deg": self.azimuth_deg,
            "length_m": self.segment.length,
        }


def generate_planting_rows(
    passes: list[TrafficPass],
    planter: PlanterMachine,
    *,
    work_area,
) -> list[PlantingRow]:
    """Gera linhas fisicas row-by-row para cada passada de plantio."""
    planter.validate()
    if not passes:
        return []

    rows: list[PlantingRow] = []
    for traffic_pass in passes:
        direction_vec = normalize(
            sub(traffic_pass.guidance_segment.end, traffic_pass.guidance_segment.start)
        )
        if traffic_pass.direction == "reverse":
            direction_vec = mul(direction_vec, -1.0)
        normal_left = perpendicular_left(direction_vec)
        base = traffic_pass.guidance_segment.start

        for row_index, row_offset in enumerate(planter.all_row_offsets(), start=1):
            line_base = add(base, mul(normal_left, -row_offset))
            clipped = clip_infinite_line_to_multipolygon(line_base, direction_vec, work_area)
            if not clipped:
                continue
            longest = max(clipped, key=lambda seg: seg.length)
            rows.append(
                PlantingRow(
                    fs_id=str(uuid4()),
                    row_id=row_index,
                    pass_id=traffic_pass.pass_no,
                    machine_id=planter.machine_id,
                    spacing_m=planter.row_spacing_m,
                    direction=traffic_pass.direction,
                    offset_m=row_offset,
                    azimuth_deg=traffic_pass.azimuth_deg,
                    segment=longest,
                )
            )
    return rows
