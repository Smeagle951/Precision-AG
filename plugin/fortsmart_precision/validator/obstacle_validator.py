# -*- coding: utf-8 -*-
"""Passadas que atravessam obstaculos ou o buffer de seguranca deles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from shapely.strtree import STRtree

from .route_geometry import PreparedRoute
from .validation_config import ValidationConfig
from .warning_model import RouteWarning, Severity, WarningType


@dataclass(frozen=True)
class ObstacleInput:
    id: str
    geometry: object  # shapely, CRS metrico


def validate_obstacles(
    routes: Sequence[PreparedRoute], obstacles: Sequence[ObstacleInput], config: ValidationConfig
) -> list[RouteWarning]:
    """Sobre o obstaculo: CRITICAL; so dentro do buffer: WARNING. Aviso = route ∩ zona."""
    if not routes or not obstacles:
        return []
    tree = STRtree([route.geometry for route in routes])
    buffer_m = config.obstacle_safety_buffer_m
    warnings = []
    for obstacle in obstacles:
        core = obstacle.geometry
        if core is None or core.is_empty:
            continue
        zone = core.buffer(buffer_m) if buffer_m > 0 else core
        for index in tree.query(zone, predicate="intersects"):
            route = routes[int(index)]
            hit = route.geometry.intersection(core)
            if not hit.is_empty:
                geometry, severity = hit, Severity.CRITICAL
                message = f"Passada {route.id} atravessa o obstaculo {obstacle.id}."
                actual = 0.0
            else:
                geometry, severity = route.geometry.intersection(zone), Severity.WARNING
                actual = route.geometry.distance(core)
                message = (
                    f"Passada {route.id} passa a {actual:.2f} m do obstaculo {obstacle.id} "
                    f"(buffer de seguranca {buffer_m:.2f} m)."
                )
            if geometry.is_empty:
                continue
            start, end = route.stations_of(geometry)
            warnings.append(RouteWarning(
                WarningType.OBSTACLE_INTERSECTION, severity, route.id, message,
                pass_index=route.index, geometry=geometry, distance_m=start, end_distance_m=end,
                obstacle_id=obstacle.id, expected_value=buffer_m, actual_value=actual,
                difference=actual - buffer_m,
            ))
    return warnings
