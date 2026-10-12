# -*- coding: utf-8 -*-
"""Modelo de obstaculos e envelopes de seguranca."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4

from ..core.line_geometry import MultiPolygon, Point, Polygon
from .machine_model import MachineProfile


class ObstacleType(str, Enum):
    POINT = "point"
    CIRCLE = "circle"
    POLYGON = "polygon"
    LINE = "line"


class ObstacleModelError(ValueError):
    """Erro no modelo de obstaculo."""


@dataclass(frozen=True)
class Obstacle:
    obstacle_id: str
    obstacle_type: ObstacleType
    center: Point
    obstacle_radius_m: float = 0.0
    safety_margin_m: float = 0.0
    application_radius_override_m: float | None = None
    name: str = ""
    polygon: Polygon | None = None

    def validate(self) -> None:
        if not self.obstacle_id:
            raise ObstacleModelError("obstacle_id obrigatorio.")
        if self.obstacle_radius_m < 0:
            raise ObstacleModelError("Raio do obstaculo nao pode ser negativo.")
        if self.safety_margin_m < 0:
            raise ObstacleModelError("Margem de seguranca nao pode ser negativa.")
        if self.obstacle_type in {ObstacleType.POINT, ObstacleType.CIRCLE} and self.obstacle_radius_m <= 0:
            if self.obstacle_type == ObstacleType.CIRCLE:
                raise ObstacleModelError("Obstaculo circular exige raio fisico maior que zero.")

    def safety_zone_radius_m(self) -> float:
        """Raio da zona de seguranca: obstaculo + margem (sem meia largura da maquina)."""
        self.validate()
        return self.obstacle_radius_m + self.safety_margin_m

    def application_radius_m(self, machine: MachineProfile) -> float:
        """Raio da linha de centro da maquina ao redor do obstaculo."""
        self.validate()
        if self.application_radius_override_m is not None:
            return self.application_radius_override_m
        return (
            self.obstacle_radius_m
            + machine.half_operational_width_m
            + self.safety_margin_m
        )

    def is_circular(self) -> bool:
        return self.obstacle_type in {ObstacleType.POINT, ObstacleType.CIRCLE}


@dataclass(frozen=True)
class ObstacleSafetyEnvelope:
    obstacle_id: str
    geometry: Polygon
    application_radius_m: float
    center: Point

    def as_multipolygon(self) -> MultiPolygon:
        return [self.geometry]


def obstacle_from_point(
    center: Point,
    *,
    obstacle_radius_m: float = 0.0,
    safety_margin_m: float = 0.0,
    name: str = "",
    obstacle_id: str | None = None,
) -> Obstacle:
    return Obstacle(
        obstacle_id=obstacle_id or str(uuid4()),
        obstacle_type=ObstacleType.POINT,
        center=center,
        obstacle_radius_m=obstacle_radius_m,
        safety_margin_m=safety_margin_m,
        name=name,
    )


def obstacle_from_polygon(
    polygon: Polygon,
    *,
    center: Point | None = None,
    obstacle_radius_m: float = 0.0,
    safety_margin_m: float = 0.0,
    name: str = "",
    obstacle_id: str | None = None,
) -> Obstacle:
    """Obstaculo poligonal (area fisica); margem aplica buffer no envelope."""
    outer = polygon[0]
    if center is None:
        pts = list(outer)
        if len(pts) >= 2 and pts[0] == pts[-1]:
            pts = pts[:-1]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        center = (sum(xs) / len(xs), sum(ys) / len(ys))
    return Obstacle(
        obstacle_id=obstacle_id or str(uuid4()),
        obstacle_type=ObstacleType.POLYGON,
        center=center,
        obstacle_radius_m=obstacle_radius_m,
        safety_margin_m=safety_margin_m,
        name=name,
        polygon=polygon,
    )
