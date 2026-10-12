# -*- coding: utf-8 -*-
"""Contexto do talhao para a analise: mesmas areas do gerador, calculadas uma unica vez."""

from __future__ import annotations

from dataclasses import dataclass, field

from shapely.geometry import MultiPolygon as ShapelyMultiPolygon, Polygon as ShapelyPolygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from ..core.line_geometry import MultiPolygon, azimuth_degrees, build_processing_boundary, multipolygon_bbox
from .models import (
    STRATEGY_ANALYSIS_NO_BOUNDARY,
    STRATEGY_ANALYSIS_NO_OPERATION,
    Point,
    StrategyAnalysisError,
)


def _to_shapely(polygons: MultiPolygon) -> BaseGeometry:
    shapes = []
    for outer, holes in polygons:
        if len(outer) < 4:
            continue
        shape = ShapelyPolygon(outer, [hole for hole in holes if len(hole) >= 4])
        shapes.append(shape if shape.is_valid else shape.buffer(0))
    if not shapes:
        return ShapelyMultiPolygon()
    return unary_union(shapes)


@dataclass
class FieldContext:
    """work_area define quais passadas existem; allowed_area e o recorte (limite + extensao)."""

    field_id: str
    work_area: MultiPolygon
    allowed_area: MultiPolygon
    operational_boundary: MultiPolygon
    pass_spacing_m: float
    operation_width_m: float
    extension_m: float
    operation_id: str = "planting"
    anchor: Point | None = None
    reference_curve: tuple[Point, ...] = ()
    reference_id: str = ""
    row_spacing_m: float | None = None
    ab_path: tuple[Point, ...] = ()
    ab_azimuth_deg: float | None = None
    _cache: dict = field(default_factory=dict, repr=False)

    def validate(self) -> None:
        if not self.work_area or not self.allowed_area or self.work_shape.is_empty:
            raise StrategyAnalysisError(STRATEGY_ANALYSIS_NO_BOUNDARY)
        if self.pass_spacing_m <= 0 or self.operation_width_m <= 0:
            raise StrategyAnalysisError(STRATEGY_ANALYSIS_NO_OPERATION)

    def _cached(self, key, factory):
        if key not in self._cache:
            self._cache[key] = factory()
        return self._cache[key]

    @property
    def work_shape(self) -> BaseGeometry:
        return self._cached("work_shape", lambda: _to_shapely(self.work_area))

    @property
    def allowed_shape(self) -> BaseGeometry:
        return self._cached("allowed_shape", lambda: _to_shapely(self.allowed_area))

    @property
    def field_shape(self) -> BaseGeometry:
        return self._cached("field_shape", lambda: _to_shapely(self.operational_boundary))

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return self._cached("bbox", lambda: multipolygon_bbox(self.work_area))

    @property
    def diagonal_m(self) -> float:
        min_x, min_y, max_x, max_y = self.bbox
        return ((max_x - min_x) ** 2 + (max_y - min_y) ** 2) ** 0.5

    @property
    def origin(self) -> Point:
        """Ponto pelo qual passa a reta de referencia (linha 0) de cada angulo."""
        if self.anchor is not None:
            return self.anchor
        centroid = self.work_shape.centroid
        return (centroid.x, centroid.y)


def build_field_context(
    project,
    *,
    reference_curve: tuple[Point, ...] = (),
    reference_id: str = "",
) -> FieldContext:
    """Areas exatamente como em run_precision_lines: miolo (sem bordadura) e limite + extensao.

    A bordadura e calculada uma vez com a A-B do projeto e vale para todos os
    candidatos, para que as metricas sejam comparaveis.
    """
    from ..core.boundary_engine import build_boundary_plan
    from ..core.precision_lines_engine import _operation_with_default_headland
    from ..domain.machine_model import PlanterMachine

    if project.planting is None or not isinstance(project.planting.machine, PlanterMachine):
        raise StrategyAnalysisError(STRATEGY_ANALYSIS_NO_OPERATION)
    if not project.field.operational_boundary:
        raise StrategyAnalysisError(STRATEGY_ANALYSIS_NO_BOUNDARY)
    ab_line = project.effective_ab_line()
    work_area = project.effective_application_zone().work_area_for_operation()
    planting = _operation_with_default_headland(project.planting, default_pass_count=0)
    if planting.headland.pass_count > 0:
        plan = build_boundary_plan(
            project.field.operational_boundary,
            planting,
            ab_line.start,
            ab_line.end,
            field_boundary=project.field.field_boundary,
        )
        if plan.inner_boundary:
            work_area = plan.inner_boundary
    machine = project.planting.machine
    context = FieldContext(
        field_id=project.field.field_id,
        work_area=work_area,
        allowed_area=build_processing_boundary(project.field.operational_boundary, project.planting.extension_m),
        operational_boundary=project.field.operational_boundary,
        pass_spacing_m=project.planting.pass_spacing_m,
        operation_width_m=machine.operational_width_m,
        extension_m=project.planting.extension_m,
        operation_id=project.planting.operation_id,
        anchor=ab_line.start,
        reference_curve=tuple(reference_curve),
        reference_id=reference_id,
        row_spacing_m=getattr(machine, "row_spacing_m", None),
        ab_path=tuple(ab_line.line_points()),
        ab_azimuth_deg=azimuth_degrees(ab_line.start, ab_line.end),
    )
    context.validate()
    return context
