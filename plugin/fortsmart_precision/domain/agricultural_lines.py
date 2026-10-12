# -*- coding: utf-8 -*-
"""Dominio do Gerador de Linhas Agricolas."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil, floor
from uuid import uuid4

from ..core.line_geometry import (
    MultiPolygon,
    Point,
    Segment,
    add,
    azimuth_degrees,
    bbox_corners,
    clip_infinite_line_to_multipolygon,
    distance,
    extend_segment,
    mul,
    multipolygon_bbox,
    normalize,
    perpendicular_left,
    signed_projection,
    sub,
)


VALID_OPERATIONS = {"custom", "planting", "spraying", "male_female"}


@dataclass(frozen=True)
class SprayingSetup:
    boom_width_m: float
    nozzle_count: int
    nozzle_spacing_m: float
    overlap_value: float = 0.0
    overlap_unit: str = "m"

    @property
    def calculated_width_m(self) -> float:
        return self.nozzle_count * self.nozzle_spacing_m

    @property
    def width_divergence_m(self) -> float:
        return self.boom_width_m - self.calculated_width_m

    @property
    def pass_spacing_m(self) -> float:
        if self.overlap_unit == "percent":
            return self.boom_width_m * (1.0 - self.overlap_value / 100.0)
        if self.overlap_unit == "cm":
            return self.boom_width_m - self.overlap_value / 100.0
        return self.boom_width_m - self.overlap_value


@dataclass(frozen=True)
class PlantingSetup:
    row_count: int
    row_spacing_m: float
    output_mode: str = "both"

    @property
    def working_width_m(self) -> float:
        from .planter_geometry import PlanterGeometryConfig

        return PlanterGeometryConfig(self.row_count, self.row_spacing_m).row_based_width_m


@dataclass(frozen=True)
class MaleFemaleSetup:
    planter_total_rows: int
    female_rows: int
    male_rows: int
    female_spacing_m: float
    male_spacing_m: float
    pattern: tuple[str, ...] = field(default_factory=tuple)

    def normalized_pattern(self) -> tuple[str, ...]:
        if self.pattern:
            return tuple(value.upper() for value in self.pattern)
        return tuple(["F"] * self.female_rows + ["M"] * self.male_rows)


@dataclass(frozen=True)
class AgriculturalLineParams:
    polygons: MultiPolygon
    ab_start: Point
    ab_end: Point
    spacing_m: float
    extension_m: float = 20.0
    min_length_m: float = 0.0
    operation: str = "custom"
    line_type: str = "pass"
    source_ab_id: str = ""
    planting: PlantingSetup | None = None
    spraying: SprayingSetup | None = None
    male_female: MaleFemaleSetup | None = None

    def validate(self) -> None:
        if self.operation not in VALID_OPERATIONS:
            raise ValueError(f"Operacao invalida: {self.operation}")
        if self.spacing_m <= 0:
            raise ValueError("Espacamento deve ser maior que zero.")
        if self.extension_m < 0:
            raise ValueError("Extensao alem do limite nao pode ser negativa.")
        if distance(self.ab_start, self.ab_end) <= 0.01:
            raise ValueError("Linha A-B curta demais.")
        if not self.polygons:
            raise ValueError("Limite operacional vazio.")


@dataclass(frozen=True)
class AgriculturalLine:
    fs_id: str
    line_no: int
    line_type: str
    operation: str
    spacing_m: float
    pass_id: int
    implement_position: int
    sex: str
    azimuth_deg: float
    length_m: float
    direction: str
    source_ab_id: str
    offset_m: float
    segment: Segment

    def attributes(self) -> dict[str, object]:
        return {
            "fs_id": self.fs_id,
            "line_no": self.line_no,
            "line_type": self.line_type,
            "operation": self.operation,
            "spacing_m": self.spacing_m,
            "pass_id": self.pass_id,
            "implement_position": self.implement_position,
            "sex": self.sex,
            "azimuth_deg": self.azimuth_deg,
            "length_m": self.length_m,
            "direction": self.direction,
            "source_ab_id": self.source_ab_id,
        }


def spacing_for_operation(
    operation: str,
    custom_spacing_m: float,
    planting: PlantingSetup | None = None,
    spraying: SprayingSetup | None = None,
    male_female: MaleFemaleSetup | None = None,
) -> float:
    if operation == "planting" and planting is not None:
        return planting.working_width_m
    if operation == "spraying" and spraying is not None:
        return spraying.pass_spacing_m
    if operation == "male_female" and male_female is not None:
        pattern = male_female.normalized_pattern()
        if not pattern:
            raise ValueError("Padrao macho/femea vazio.")
        spacings = [
            male_female.male_spacing_m if value == "M" else male_female.female_spacing_m
            for value in pattern
        ]
        return sum(spacings) / len(spacings)
    return custom_spacing_m


def generate_parallel_agricultural_lines(params: AgriculturalLineParams) -> list[AgriculturalLine]:
    """Gera linhas paralelas cobrindo todo o limite operacional informado."""
    params.validate()
    direction = normalize(sub(params.ab_end, params.ab_start))
    normal = perpendicular_left(direction)
    bbox = multipolygon_bbox(params.polygons)
    corner_offsets = [signed_projection(corner, params.ab_start, normal) for corner in bbox_corners(bbox)]
    min_offset = min(corner_offsets) - params.spacing_m * 2
    max_offset = max(corner_offsets) + params.spacing_m * 2
    start_index = floor(min_offset / params.spacing_m)
    end_index = ceil(max_offset / params.spacing_m)
    azimuth = azimuth_degrees(params.ab_start, params.ab_end)

    raw: list[tuple[float, Segment]] = []
    for index in range(start_index, end_index + 1):
        offset = index * params.spacing_m
        base = add(params.ab_start, mul(normal, offset))
        clipped = clip_infinite_line_to_multipolygon(base, direction, params.polygons)
        for segment in clipped:
            if segment.length < params.min_length_m:
                continue
            extended = extend_segment(segment.start, segment.end, params.extension_m)
            raw.append((offset, extended))

    raw.sort(key=lambda item: (item[0], item[1].start[0], item[1].start[1]))
    pattern = _sex_pattern(params)
    lines: list[AgriculturalLine] = []
    for pos, (offset, segment) in enumerate(raw, start=1):
        sex = pattern[(pos - 1) % len(pattern)] if pattern else ""
        side = "center"
        if offset < -1e-7:
            side = "right"
        elif offset > 1e-7:
            side = "left"
        lines.append(
            AgriculturalLine(
                fs_id=str(uuid4()),
                line_no=pos,
                line_type=params.line_type,
                operation=params.operation,
                spacing_m=params.spacing_m,
                pass_id=pos,
                implement_position=pos,
                sex=sex,
                azimuth_deg=azimuth,
                length_m=segment.length,
                direction=side,
                source_ab_id=params.source_ab_id,
                offset_m=offset,
                segment=segment,
            )
        )
    return lines


def total_length(lines: list[AgriculturalLine]) -> float:
    return sum(line.length_m for line in lines)


def _sex_pattern(params: AgriculturalLineParams) -> tuple[str, ...]:
    if params.operation != "male_female" or params.male_female is None:
        return tuple()
    return params.male_female.normalized_pattern()
