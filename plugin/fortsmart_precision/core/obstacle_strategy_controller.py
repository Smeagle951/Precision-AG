# -*- coding: utf-8 -*-
"""Controlador de estrategia de obstaculo.

STOP_CUT_RESUME delega ao corte existente sem altera-lo. LATERAL_DETOUR usa o
motor isolado em core.lateral_detour e, se inviavel, cai explicitamente (e com
log) no corte existente.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry

from ..domain.obstacle_strategy import (
    DETOUR_NOT_FEASIBLE,
    ObstacleConfig,
    ObstacleHandlingStrategy,
    resolve_strategy,
)
from .lateral_detour.engine import LateralDetourResult, create_lateral_detour
from .planting_line_cut_engine import SafeLineSegment, cut_polyline_by_zones

LOGGER = logging.getLogger("fortsmart_precision.obstacles")

CUT_RESUMED = "CUT_RESUMED"
FALLBACK_TO_CUT = "FALLBACK_TO_CUT"

ExistingStrategy = Callable[[LineString, list[tuple[str, BaseGeometry]], ObstacleConfig], object]


@dataclass(frozen=True)
class ObstacleProcessingResult:
    strategy_requested: ObstacleHandlingStrategy
    strategy_used: ObstacleHandlingStrategy
    status: str
    fallback_used: bool = False
    fallback_reason: str = ""
    detour: LateralDetourResult | None = None
    existing_result: object | None = None
    log: tuple[dict, ...] = field(default_factory=tuple)

    @property
    def final_path(self) -> LineString | None:
        if self.strategy_used == ObstacleHandlingStrategy.LATERAL_DETOUR and self.detour is not None:
            return self.detour.final_path
        return None


def _shapely_to_tuple_polygons(geometry: BaseGeometry):
    polygons = [geometry] if isinstance(geometry, Polygon) else list(getattr(geometry, "geoms", []))
    result = []
    for polygon in polygons:
        if polygon.is_empty or polygon.geom_type != "Polygon":
            continue
        exterior = [(float(x), float(y)) for x, y in polygon.exterior.coords]
        holes = [[(float(x), float(y)) for x, y in ring.coords] for ring in polygon.interiors]
        result.append((exterior, holes))
    return result


CUT_BUFFER_SEGMENTS = 24


def stop_cut_resume_zones(obstacles: list[tuple[str, BaseGeometry]], config: ObstacleConfig):
    """Mesma zona do corte radial da janela: buffer(meia largura + raio + margem, 24)."""
    radius = config.half_machine + config.obstacle_radius + config.safety_margin
    zones = []
    for _obstacle_id, geometry in obstacles:
        zones.extend(_shapely_to_tuple_polygons(geometry.buffer(radius, quad_segs=CUT_BUFFER_SEGMENTS)))
    return zones


def call_existing_strategy(
    path: LineString,
    obstacles: list[tuple[str, BaseGeometry]],
    config: ObstacleConfig,
    *,
    source_id: str = "1",
) -> list[SafeLineSegment]:
    """Chama cut_polyline_by_zones exatamente como existe hoje."""
    points = tuple((float(x), float(y)) for x, y in path.coords)
    return cut_polyline_by_zones(
        points,
        stop_cut_resume_zones(obstacles, config),
        source_id=source_id,
        obstacle_count=len(obstacles),
    )


def apply_obstacle_strategy(
    path: LineString,
    obstacles: list[tuple[str, BaseGeometry]],
    config: ObstacleConfig,
    *,
    allowed_area: BaseGeometry | None = None,
    source_id: str = "1",
    existing_strategy: ExistingStrategy | None = None,
) -> ObstacleProcessingResult:
    """Escolhe a estrategia; sem estrategia definida, o corte existente roda."""
    requested = resolve_strategy(config.strategy)

    def run_existing():
        if existing_strategy is not None:
            return existing_strategy(path, obstacles, config)
        return call_existing_strategy(path, obstacles, config, source_id=source_id)

    if requested == ObstacleHandlingStrategy.STOP_CUT_RESUME:
        return ObstacleProcessingResult(
            strategy_requested=requested,
            strategy_used=requested,
            status=CUT_RESUMED,
            existing_result=run_existing(),
        )

    if requested != ObstacleHandlingStrategy.LATERAL_DETOUR:
        raise ValueError(f"Estrategia de obstaculo nao suportada: {requested}")

    detour = create_lateral_detour(path, obstacles, config, allowed_area=allowed_area)
    if detour.valid:
        return ObstacleProcessingResult(
            strategy_requested=requested,
            strategy_used=requested,
            status=detour.status,
            detour=detour,
            log=detour.log,
        )

    reason = detour.reason or DETOUR_NOT_FEASIBLE
    if not config.allow_fallback:
        LOGGER.warning("Desvio lateral inviavel e fallback desativado: %s", reason)
        return ObstacleProcessingResult(
            strategy_requested=requested,
            strategy_used=requested,
            status=DETOUR_NOT_FEASIBLE,
            fallback_reason=reason,
            detour=detour,
            log=detour.log,
        )

    LOGGER.warning("Desvio lateral inviavel; usando corte e retomada: %s", reason)
    log = tuple({**entry, "fallback_used": True} for entry in detour.log)
    return ObstacleProcessingResult(
        strategy_requested=requested,
        strategy_used=ObstacleHandlingStrategy.STOP_CUT_RESUME,
        status=FALLBACK_TO_CUT,
        fallback_used=True,
        fallback_reason=reason,
        detour=detour,
        existing_result=run_existing(),
        log=log,
    )


process_obstacle = apply_obstacle_strategy
