# -*- coding: utf-8 -*-
"""Componentes de Polygon/MultiPolygon: nunca reduzir N partes a maior parte.

Estreitamentos mais finos que 2x o buffer interno separam o talhao em partes.
Isso e geometria real; o erro seria descartar uma delas. Estas funcoes extraem
todas as partes, verificam conservacao de area e medem cobertura por parte.
Coordenadas sempre em CRS metrico.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

LOGGER = logging.getLogger("fortsmart_precision.generator")

MULTIPART_AREA_LOSS = "MULTIPART_AREA_LOSS"
UNEXPECTED_MULTIPART_COMPONENT_LOSS = "UNEXPECTED_MULTIPART_COMPONENT_LOSS"
PLANTING_COMPONENT_NOT_COVERED = "PLANTING_COMPONENT_NOT_COVERED"
BORDER_COMPONENT_NOT_COVERED = "BORDER_COMPONENT_NOT_COVERED"

AREA_RELATIVE_TOLERANCE = 1e-6
AREA_ABSOLUTE_TOLERANCE_M2 = 0.01
MINIMUM_COMPONENT_AREA_M2 = 25.0


class ComponentLossError(ValueError):
    """Perda silenciosa de area/componente entre etapas da geometria."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def extract_polygon_components(geometry) -> list:
    """Todas as partes poligonais validas (Polygon/MultiPolygon/Collection recursiva)."""
    if geometry is None or geometry.is_empty:
        return []
    kind = geometry.geom_type
    if kind == "Polygon":
        return [geometry] if geometry.area > 0 else []
    if kind in ("MultiPolygon", "GeometryCollection"):
        parts: list = []
        for item in geometry.geoms:
            parts.extend(extract_polygon_components(item))
        return parts
    return []


def extract_line_components(geometry) -> list:
    """Todas as partes lineares (Line/MultiLine/Collection recursiva)."""
    from .pass_family_coverage import extract_valid_line_parts

    return extract_valid_line_parts(geometry)


def validate_component_area_conservation(
    geometry_area: float,
    component_areas: list[float],
    *,
    code: str = MULTIPART_AREA_LOSS,
) -> float:
    """sum(componentes) deve igualar a area da geometria (tolerancia numerica)."""
    total = float(sum(component_areas))
    expected = float(geometry_area)
    tolerance = max(AREA_ABSOLUTE_TOLERANCE_M2, abs(expected) * AREA_RELATIVE_TOLERANCE)
    if abs(total - expected) > tolerance:
        raise ComponentLossError(
            code,
            f"{expected - total:.2f} m2 desapareceram na extracao de componentes "
            f"(geometria={expected:.2f} m2, componentes={total:.2f} m2).",
        )
    return total


def _shapely_components(polygons) -> list:
    from shapely.geometry import Polygon

    shapes = []
    for outer, holes in polygons:
        if len(outer) < 4:
            continue
        shape = Polygon(outer, [hole for hole in holes if len(hole) >= 4])
        if not shape.is_valid:
            shape = shape.buffer(0)
        shapes.extend(extract_polygon_components(shape))
    return shapes


@dataclass(frozen=True)
class ComponentCoverage:
    index: int
    area_m2: float
    pass_count: int
    covered_m2: float
    border_segments: int = 0

    @property
    def significant(self) -> bool:
        return self.area_m2 > MINIMUM_COMPONENT_AREA_M2


@dataclass
class ComponentCoverageReport:
    components: list[ComponentCoverage] = field(default_factory=list)
    codes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.codes


def validate_component_coverage(
    passes,
    components,
    *,
    implement_width_m: float,
    border_lines=(),
    border_reach_m: float | None = None,
    minimum_component_area_m2: float = MINIMUM_COMPONENT_AREA_M2,
) -> ComponentCoverageReport:
    """Cada componente significativo precisa de passadas (e de bordadura, se houver).

    `components` = MultiPolygon do miolo. Um componente menor que
    `minimum_component_area_m2` ou mais estreito que a largura do implemento
    nao gera aviso (nao cabe passada operacional).
    """
    from shapely.geometry import LineString

    shapes = _shapely_components(components)
    lines = [LineString(item.line_points()) for item in passes if len(item.line_points()) >= 2]
    strips = [line.buffer(implement_width_m / 2.0, cap_style="flat") for line in lines]
    borders = [LineString(points) for points in border_lines if len(points) >= 2]
    reach = float(border_reach_m) if border_reach_m is not None else implement_width_m
    report = ComponentCoverageReport()
    for index, shape in enumerate(shapes):
        touching = [strip for line, strip in zip(lines, strips) if line.intersects(shape)]
        covered = 0.0
        if touching:
            from shapely.ops import unary_union

            covered = unary_union(touching).intersection(shape).area
        border_segments = sum(1 for line in borders if line.distance(shape) <= reach + 1e-6)
        item = ComponentCoverage(
            index=index,
            area_m2=float(shape.area),
            pass_count=len(touching),
            covered_m2=float(covered),
            border_segments=border_segments,
        )
        report.components.append(item)
        fits_implement = shape.buffer(-implement_width_m / 2.0).area > 0
        if item.area_m2 > minimum_component_area_m2 and fits_implement and item.pass_count == 0:
            report.codes.append(f"{PLANTING_COMPONENT_NOT_COVERED}:{index}")
        if borders and item.area_m2 > minimum_component_area_m2 and border_segments == 0:
            report.codes.append(f"{BORDER_COMPONENT_NOT_COVERED}:{index}")
    return report


def component_debug_report(
    label: str,
    boundary,
    inner,
    coverage: ComponentCoverageReport,
    *,
    logical_passes: int,
    features: int,
) -> list[str]:
    """Linhas de log por componente (tipo, area, passadas, bordadura)."""
    from .line_geometry import multipolygon_area

    lines = [
        f"FIELD {label}",
        f"Boundary: type={'MultiPolygon' if len(boundary) > 1 else 'Polygon'} area={multipolygon_area(boundary):.1f}",
        f"Inner buffer: type={'MultiPolygon' if len(inner) > 1 else 'Polygon'} parts={len(inner)} area={multipolygon_area(inner):.1f}",
    ]
    for item in coverage.components:
        lines.append(
            f"Part {item.index}: area={item.area_m2:.1f} planting_passes={item.pass_count} "
            f"border_segments={item.border_segments} covered={item.covered_m2:.1f}"
        )
    lines.append(f"Total logical passes={logical_passes}")
    lines.append(f"Total line features={features}")
    for code in coverage.codes:
        lines.append(code)
    return lines


def log_component_report(lines: list[str], coverage: ComponentCoverageReport) -> None:
    for line in lines:
        LOGGER.info(line)
    if not coverage.ok:
        LOGGER.warning("Componentes sem cobertura: %s", ", ".join(coverage.codes))
