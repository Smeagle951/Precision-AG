# -*- coding: utf-8 -*-
"""Envelope da maquina e zonas seguras dos obstaculos (CRS metrico)."""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from ...domain.obstacle_strategy import GEOMETRY_EPSILON, calculate_machine_width

BUFFER_QUAD_SEGS = 32
# Ponto sem raio fisico vira um disco minimo para ter area mensuravel.
MIN_OBSTACLE_RADIUS_M = 0.01


@dataclass(frozen=True)
class MachineEnvelope:
    row_count: int
    row_spacing: float
    machine_width: float
    half_machine: float
    safety_margin: float
    clearance: float


@dataclass(frozen=True)
class ObstacleGroup:
    """Obstaculos cujas zonas seguras se tocam: um unico desvio."""

    group_id: str
    obstacle_ids: tuple[str, ...]
    core: BaseGeometry
    safe_zone: BaseGeometry


def calculate_machine_envelope(row_count: int, row_spacing: float, safety_margin: float) -> MachineEnvelope:
    width = calculate_machine_width(row_count, row_spacing)
    half = width / 2.0
    return MachineEnvelope(
        row_count=int(row_count),
        row_spacing=float(row_spacing),
        machine_width=width,
        half_machine=half,
        safety_margin=float(safety_margin),
        clearance=half + float(safety_margin),
    )


def obstacle_core(geometry: BaseGeometry, obstacle_radius: float = 0.0) -> BaseGeometry:
    """Obstaculo fisico: pontos/linhas ganham o raio do poste."""
    if geometry is None or geometry.is_empty:
        raise ValueError("Obstaculo sem geometria.")
    if geometry.area > GEOMETRY_EPSILON and obstacle_radius <= 0:
        return geometry
    radius = max(float(obstacle_radius), MIN_OBSTACLE_RADIUS_M)
    return geometry.buffer(radius, quad_segs=BUFFER_QUAD_SEGS)


def build_safe_obstacle(core: BaseGeometry, clearance: float) -> BaseGeometry:
    return core.buffer(float(clearance), quad_segs=BUFFER_QUAD_SEGS)


def detect_obstacle_conflict(master_path: LineString, safe_obstacle: BaseGeometry) -> bool:
    return bool(master_path.intersects(safe_obstacle))


def contour_polygon(core: BaseGeometry, radius: float) -> Polygon:
    """Envoltoria convexa expandida: so arcos convexos, raio de curva >= radius."""
    return core.convex_hull.buffer(float(radius), quad_segs=BUFFER_QUAD_SEGS)


def group_obstacles(
    obstacles: list[tuple[str, BaseGeometry]],
    clearance: float,
) -> list[ObstacleGroup]:
    """Une obstaculos cujas zonas seguras se sobrepoem (buffer A ∩ buffer B)."""
    items = [(str(obstacle_id), core, build_safe_obstacle(core, clearance)) for obstacle_id, core in obstacles]
    if not items:
        return []
    merged = unary_union([safe for _id, _core, safe in items])
    components = list(getattr(merged, "geoms", [merged]))
    groups: list[ObstacleGroup] = []
    for index, component in enumerate(components, start=1):
        members = [item for item in items if item[2].intersects(component)]
        if not members:
            continue
        groups.append(
            ObstacleGroup(
                group_id=f"G{index:03d}",
                obstacle_ids=tuple(member[0] for member in members),
                core=unary_union([member[1] for member in members]),
                safe_zone=unary_union([member[2] for member in members]),
            )
        )
    return groups


def merge_groups(groups: list[ObstacleGroup]) -> ObstacleGroup:
    return ObstacleGroup(
        group_id="+".join(group.group_id for group in groups),
        obstacle_ids=tuple(obstacle_id for group in groups for obstacle_id in group.obstacle_ids),
        core=unary_union([group.core for group in groups]),
        safe_zone=unary_union([group.safe_zone for group in groups]),
    )
