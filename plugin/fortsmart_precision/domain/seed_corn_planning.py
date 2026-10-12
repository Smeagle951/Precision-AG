# -*- coding: utf-8 -*-
"""Motor de milho semente macho/femea com padrao global entre passadas."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from ..core.line_geometry import MultiPolygon, Point, Segment, add, mul, normalize, perpendicular_left, signed_projection, sub
from ..core.parallel_pass_engine import ParallelPass, ParallelPassParams, generate_parallel_passes
from ..core.line_geometry import (
    azimuth_degrees,
    bbox_corners,
    clip_infinite_line_to_multipolygon,
    extend_segment,
    multipolygon_bbox,
)
from .planting_configuration import PlantingConfiguration


class SeedCornPlanningError(ValueError):
    """Erro em configuracao de milho semente."""


@dataclass(frozen=True)
class SeedCornPattern:
    positions: tuple[str, ...] = ("F", "F", "F", "F", "F", "F", "M1")
    initial_cycle_position: int = 1
    spacing_after_position_m: tuple[float, ...] = tuple()

    def validate(self) -> None:
        if not self.positions:
            raise SeedCornPlanningError("Padrao macho/femea vazio.")
        allowed = {"F", "M", "M1", "M2", "D", "C"}
        if any(role.upper() not in allowed for role in self.positions):
            raise SeedCornPlanningError("Padrao contem posicao desconhecida.")
        if not any(role.upper() == "F" for role in self.positions):
            raise SeedCornPlanningError("Padrao precisa possuir ao menos uma linha femea.")
        if self.initial_cycle_position < 1 or self.initial_cycle_position > len(self.positions):
            raise SeedCornPlanningError("Posicao inicial do ciclo fora do padrao.")
        if self.spacing_after_position_m and len(self.spacing_after_position_m) != len(self.positions):
            raise SeedCornPlanningError("Matriz de espacamentos deve ter o mesmo tamanho do padrao.")
        if any(value <= 0 for value in self.spacing_after_position_m):
            raise SeedCornPlanningError("Espacamentos do padrao devem ser maiores que zero.")

    def role_for_global_no(self, global_no: int) -> str:
        self.validate()
        idx = (global_no - 1 + self.initial_cycle_position - 1) % len(self.positions)
        role = self.positions[idx].upper()
        return "M1" if role == "M" else role

    def cycle_position_for_global_no(self, global_no: int) -> int:
        return ((global_no - 1 + self.initial_cycle_position - 1) % len(self.positions)) + 1

    def spacing_after_global_no(self, global_no: int, default_spacing_m: float) -> float:
        if not self.spacing_after_position_m:
            return default_spacing_m
        idx = (global_no - 1 + self.initial_cycle_position - 1) % len(self.positions)
        return self.spacing_after_position_m[idx]


@dataclass(frozen=True)
class SeedCornParams:
    polygons: MultiPolygon
    ab_start: Point
    ab_end: Point
    planter: PlantingConfiguration
    pattern: SeedCornPattern
    ab_reference: str = "center_tractor"
    ab_offset_right_m: float = 0.0
    extension_m: float = 20.0
    min_length_m: float = 0.0
    tractor_center_offset_m: float = 0.0
    source_ab_id: str = ""

    def validate(self) -> None:
        self.planter.validate()
        self.pattern.validate()
        if self.ab_reference not in {"center_tractor", "center_planter", "first_physical_row", "male_row"}:
            raise SeedCornPlanningError("Significado da linha A-B invalido.")


@dataclass(frozen=True)
class SeedCornRow:
    fs_id: str
    row_no: int
    global_no: int
    row_role: str
    sex: str
    male_operation: str
    block_no: int
    cycle_position: int
    pass_no: int
    implement_position: int
    spacing_left_m: float
    spacing_right_m: float
    offset_from_ab_m: float
    azimuth_deg: float
    length_m: float
    segment: Segment

    def attributes(self) -> dict[str, object]:
        return {
            "fs_id": self.fs_id,
            "row_no": self.row_no,
            "global_no": self.global_no,
            "row_role": self.row_role,
            "sex": self.sex,
            "male_operation": self.male_operation,
            "block_no": self.block_no,
            "cycle_position": self.cycle_position,
            "pass_no": self.pass_no,
            "implement_position": self.implement_position,
            "spacing_left_m": self.spacing_left_m,
            "spacing_right_m": self.spacing_right_m,
            "offset_from_ab_m": self.offset_from_ab_m,
            "azimuth_deg": self.azimuth_deg,
            "length_m": self.length_m,
        }


@dataclass(frozen=True)
class SeedCornPlan:
    female_rows: list[SeedCornRow]
    male_rows_1: list[SeedCornRow]
    male_rows_2: list[SeedCornRow]
    disabled_rows: list[SeedCornRow]
    corridor_rows: list[SeedCornRow]
    passes: list[ParallelPass]

    @property
    def rows(self) -> list[SeedCornRow]:
        return sorted(
            self.female_rows + self.male_rows_1 + self.male_rows_2 + self.disabled_rows + self.corridor_rows,
            key=lambda row: row.global_no,
        )

    def summary(self) -> dict[str, int]:
        return {
            "female_rows": len(self.female_rows),
            "male_rows_1": len(self.male_rows_1),
            "male_rows_2": len(self.male_rows_2),
            "passes": len(self.passes),
        }


def generate_seed_corn_plan(params: SeedCornParams) -> SeedCornPlan:
    params.validate()
    if params.ab_reference in {"center_tractor", "center_planter"}:
        return _generate_by_planter_passes(params)
    return _generate_by_physical_rows(params)


def _generate_by_planter_passes(params: SeedCornParams) -> SeedCornPlan:
    ab_right_offset = params.ab_offset_right_m
    if params.ab_reference == "center_tractor":
        ab_right_offset += params.tractor_center_offset_m + params.planter.implement_center_offset_m
    passes = generate_parallel_passes(
        ParallelPassParams(
            polygons=params.polygons,
            ab_start=params.ab_start,
            ab_end=params.ab_end,
            pass_spacing_m=params.planter.working_width_m,
            operation_width_m=params.planter.working_width_m,
            extension_m=params.extension_m,
            ab_offset_right_m=ab_right_offset,
            min_length_m=params.min_length_m,
            operation_id="seed_corn",
        )
    )
    direction = normalize(sub(params.ab_end, params.ab_start))
    normal_left = perpendicular_left(direction)
    raw_rows: list[tuple[float, Segment, int, int, float]] = []
    for pass_line in passes:
        center_left = -pass_line.offset_m
        for implement_position, row_offset in enumerate(params.planter.all_row_offsets(), start=1):
            row_left = center_left + row_offset
            base = add(params.ab_start, mul(normal_left, row_left))
            for segment in clip_infinite_line_to_multipolygon(base, direction, params.polygons):
                if segment.length >= params.min_length_m:
                    raw_rows.append(
                        (
                            row_left,
                            extend_segment(segment.start, segment.end, params.extension_m),
                            pass_line.pass_no,
                            implement_position,
                            row_offset,
                        )
                    )
    return _build_plan_from_raw_rows(params, raw_rows, passes)


def _generate_by_physical_rows(params: SeedCornParams) -> SeedCornPlan:
    direction = normalize(sub(params.ab_end, params.ab_start))
    normal_left = perpendicular_left(direction)
    bbox = multipolygon_bbox(params.polygons)
    corner_offsets = [signed_projection(corner, params.ab_start, normal_left) for corner in bbox_corners(bbox)]
    min_left = min(corner_offsets) - params.planter.row_spacing_m * 2
    max_left = max(corner_offsets) + params.planter.row_spacing_m * 2
    initial_left = -params.ab_offset_right_m
    if params.ab_reference == "male_row":
        male_idx = _first_male_index(params.pattern)
        initial_left -= (male_idx - 1) * params.planter.row_spacing_m

    offsets = _uniform_offsets_covering_range(initial_left, min_left, max_left, params.planter.row_spacing_m)
    raw_rows: list[tuple[float, Segment, int, int, float]] = []
    for row_index, row_left in enumerate(offsets, start=1):
        base = add(params.ab_start, mul(normal_left, row_left))
        pass_no = ((row_index - 1) // params.planter.row_count) + 1
        implement_position = ((row_index - 1) % params.planter.row_count) + 1
        implement_offset = params.planter.row_offset_from_center(implement_position)
        for segment in clip_infinite_line_to_multipolygon(base, direction, params.polygons):
            if segment.length >= params.min_length_m:
                raw_rows.append(
                    (
                        row_left,
                        extend_segment(segment.start, segment.end, params.extension_m),
                        pass_no,
                        implement_position,
                        implement_offset,
                    )
                )
    pass_offsets = sorted({item[2] for item in raw_rows})
    passes = []
    for pass_no in pass_offsets:
        rows = [item for item in raw_rows if item[2] == pass_no]
        if not rows:
            continue
        center_left = sum(row[0] for row in rows) / len(rows)
        base = add(params.ab_start, mul(normal_left, center_left))
        clipped = clip_infinite_line_to_multipolygon(base, direction, params.polygons)
        if clipped:
            guidance = extend_segment(clipped[0].start, clipped[0].end, params.extension_m)
            passes.append(
                ParallelPass(
                    fs_id=str(uuid4()),
                    operation_id="seed_corn",
                    pass_no=pass_no,
                    spacing_m=params.planter.working_width_m,
                    width_m=params.planter.working_width_m,
                    half_width_m=params.planter.half_width_m,
                    offset_m=-center_left,
                    azimuth_deg=azimuth_degrees(params.ab_start, params.ab_end),
                    length_m=guidance.length,
                    is_headland=False,
                    clipped_segment=clipped[0],
                    guidance_segment=guidance,
                )
            )
    return _build_plan_from_raw_rows(params, raw_rows, passes)


def _build_plan_from_raw_rows(
    params: SeedCornParams,
    raw_rows: list[tuple[float, Segment, int, int, float]],
    passes: list[ParallelPass],
) -> SeedCornPlan:
    raw_rows.sort(key=lambda item: (item[0], item[2], item[3]))
    female: list[SeedCornRow] = []
    male1: list[SeedCornRow] = []
    male2: list[SeedCornRow] = []
    disabled: list[SeedCornRow] = []
    corridors: list[SeedCornRow] = []
    for global_no, (row_left, segment, pass_no, implement_position, _implement_offset) in enumerate(raw_rows, start=1):
        role = params.pattern.role_for_global_no(global_no)
        sex, male_operation = _role_to_sex_and_operation(role)
        spacing_left = params.pattern.spacing_after_global_no(global_no - 1, params.planter.row_spacing_m) if global_no > 1 else 0.0
        spacing_right = params.pattern.spacing_after_global_no(global_no, params.planter.row_spacing_m)
        row = SeedCornRow(
            fs_id=str(uuid4()),
            row_no=global_no,
            global_no=global_no,
            row_role=role,
            sex=sex,
            male_operation=male_operation,
            block_no=((global_no - 1) // len(params.pattern.positions)) + 1,
            cycle_position=params.pattern.cycle_position_for_global_no(global_no),
            pass_no=pass_no,
            implement_position=implement_position,
            spacing_left_m=spacing_left,
            spacing_right_m=spacing_right,
            offset_from_ab_m=-row_left,
            azimuth_deg=azimuth_degrees(params.ab_start, params.ab_end),
            length_m=segment.length,
            segment=segment,
        )
        if role == "F":
            female.append(row)
        elif role == "M1":
            male1.append(row)
        elif role == "M2":
            male2.append(row)
        elif role == "C":
            corridors.append(row)
        else:
            disabled.append(row)
    return SeedCornPlan(
        female_rows=female,
        male_rows_1=male1,
        male_rows_2=male2,
        disabled_rows=disabled,
        corridor_rows=corridors,
        passes=passes,
    )


def _role_to_sex_and_operation(role: str) -> tuple[str, str]:
    if role == "F":
        return "F", ""
    if role == "M1":
        return "M", "M1"
    if role == "M2":
        return "M", "M2"
    return role, ""


def _first_male_index(pattern: SeedCornPattern) -> int:
    for index, role in enumerate(pattern.positions, start=1):
        if role.upper() in {"M", "M1", "M2"}:
            return index
    raise SeedCornPlanningError("Padrao nao possui linha macho para alinhar A-B.")


def _uniform_offsets_covering_range(start_left: float, min_left: float, max_left: float, spacing_m: float) -> list[float]:
    values = [start_left]
    current = start_left
    while current - spacing_m >= min_left:
        current -= spacing_m
        values.append(current)
    current = start_left
    while current + spacing_m <= max_left:
        current += spacing_m
        values.append(current)
    return sorted(values)
