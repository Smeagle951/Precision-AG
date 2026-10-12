# -*- coding: utf-8 -*-
"""Linhas da plantadeira geradas por offset da trajetoria mestra."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

from ...domain.obstacle_strategy import GEOMETRY_EPSILON

OFFSET_QUAD_SEGS = 16
SPACING_SAMPLE_STEP_M = 1.0
MAX_SPACING_SAMPLES = 400


@dataclass(frozen=True)
class PlanterRow:
    row_index: int
    offset: float
    geometry: LineString
    clipped_parts: tuple[LineString, ...] = ()


@dataclass(frozen=True)
class RowGenerationResult:
    rows: tuple[PlanterRow, ...]
    offsets: tuple[float, ...]
    spacing_ok: bool
    minimum_spacing: float
    maximum_spacing: float
    errors: tuple[str, ...] = ()


def generate_row_offsets(row_count: int, row_spacing: float) -> list[float]:
    """offset_i = (i - (n-1)/2) * espacamento; negativo = esquerda.

    Quantidade par nao tem offset zero; impar tem linha central.
    """
    count = int(row_count)
    if count < 1:
        raise ValueError("row_count deve ser >= 1.")
    if row_spacing <= 0:
        raise ValueError("row_spacing deve ser > 0.")
    center = (count - 1) / 2.0
    return [round((index - center) * float(row_spacing), 9) for index in range(count)]


def create_offset_line(master: LineString, offset: float) -> BaseGeometry:
    """Offset com juncao arredondada; offset positivo fica a direita."""
    if abs(offset) <= GEOMETRY_EPSILON:
        return LineString(master.coords)
    geometry = master.offset_curve(-offset, quad_segs=OFFSET_QUAD_SEGS, join_style="round")
    if geometry.geom_type == "MultiLineString":
        # GEOS pode devolver o offset em partes encadeadas ponta a ponta.
        geometry = shapely.line_merge(geometry, directed=True)
    return geometry


def _sample_points(line: LineString) -> np.ndarray:
    count = int(min(MAX_SPACING_SAMPLES, max(3, math.ceil(line.length / SPACING_SAMPLE_STEP_M))))
    distances = np.linspace(0.0, line.length, count)
    return shapely.get_coordinates(shapely.line_interpolate_point(line, distances))


def validate_row_spacing(rows: list[PlanterRow], row_spacing: float, tolerance: float) -> tuple[bool, float, float]:
    """Distancia de cada linha a vizinha deve ficar em espacamento +/- tolerancia."""
    if len(rows) < 2:
        return True, row_spacing, row_spacing
    minimum, maximum = math.inf, 0.0
    for current, neighbour in zip(rows, rows[1:]):
        points = shapely.points(_sample_points(current.geometry))
        distances = shapely.distance(points, neighbour.geometry)
        minimum = min(minimum, float(np.min(distances)))
        maximum = max(maximum, float(np.max(distances)))
    ok = abs(minimum - row_spacing) <= tolerance and abs(maximum - row_spacing) <= tolerance
    return ok, minimum, maximum


def _clip(line: LineString, allowed_area: BaseGeometry | None) -> tuple[LineString, ...]:
    if allowed_area is None:
        return (line,)
    clipped = line.intersection(allowed_area)
    parts = [part for part in getattr(clipped, "geoms", [clipped]) if part.geom_type == "LineString" and part.length > GEOMETRY_EPSILON]
    return tuple(parts)


def generate_planter_rows(
    master: LineString,
    row_count: int,
    row_spacing: float,
    *,
    spacing_tolerance: float = 0.03,
    allowed_area: BaseGeometry | None = None,
) -> RowGenerationResult:
    """Offset -> validacao de espacamento -> recorte na area permitida (por ultimo)."""
    offsets = generate_row_offsets(row_count, row_spacing)
    rows: list[PlanterRow] = []
    errors: list[str] = []
    for index, offset in enumerate(offsets, start=1):
        geometry = create_offset_line(master, offset)
        if geometry.is_empty or geometry.geom_type != "LineString":
            errors.append(f"Linha {index} (offset {offset:+.3f} m) gerou geometria invalida/multipla.")
            continue
        if not geometry.is_simple:
            errors.append(f"Linha {index} (offset {offset:+.3f} m) com laco.")
        rows.append(PlanterRow(index, offset, geometry))

    spacing_ok, minimum, maximum = validate_row_spacing(rows, row_spacing, spacing_tolerance)
    if not spacing_ok:
        errors.append(
            f"Espacamento entre linhas {minimum:.3f}-{maximum:.3f} m fora de "
            f"{row_spacing:.3f} +/- {spacing_tolerance:.3f} m."
        )
    clipped_rows = tuple(
        PlanterRow(row.row_index, row.offset, row.geometry, _clip(row.geometry, allowed_area)) for row in rows
    )
    return RowGenerationResult(
        rows=clipped_rows,
        offsets=tuple(offsets),
        spacing_ok=spacing_ok and not errors,
        minimum_spacing=minimum,
        maximum_spacing=maximum,
        errors=tuple(errors),
    )
