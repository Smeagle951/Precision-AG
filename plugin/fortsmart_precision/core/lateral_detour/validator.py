# -*- coding: utf-8 -*-
"""Validacao do caminho mestre final apos o desvio."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

from ...domain.obstacle_strategy import GEOMETRY_EPSILON
from .transition import RADIUS_TOLERANCE, minimum_radius

CLEARANCE_TOLERANCE = 0.01
# Recuo tolerado na projecao sobre a trajetoria original (ruido numerico).
FORWARD_TOLERANCE = 0.05


@dataclass(frozen=True)
class DetourValidation:
    valid: bool
    minimum_clearance: float
    minimum_radius: float
    inside_allowed_area: bool
    self_intersection: bool
    spacing_ok: bool = True
    continuity_ok: bool = True
    forward_motion: bool = True
    errors: tuple[str, ...] = ()


def moves_forward(path: LineString, coords, tolerance: float = FORWARD_TOLERANCE) -> bool:
    """Sem marcha a re: a projecao na trajetoria original nunca recua."""
    arr = np.asarray(coords, dtype=float)
    if len(arr) < 2:
        return True
    stations = shapely.line_locate_point(path, shapely.points(arr))
    return bool(np.all(np.diff(stations) >= -tolerance))


def inside_area(geometry: BaseGeometry, allowed_area: BaseGeometry | None) -> bool:
    if allowed_area is None:
        return True
    return bool(allowed_area.buffer(GEOMETRY_EPSILON).covers(geometry))


def validate_final_path(
    original: LineString,
    final: LineString,
    sections,
    obstacle_cores: BaseGeometry | None,
    *,
    half_machine: float,
    safety_margin: float,
    required_radius: float,
    allowed_area: BaseGeometry | None = None,
    spacing_ok: bool = True,
) -> DetourValidation:
    errors: list[str] = []

    if obstacle_cores is None or obstacle_cores.is_empty:
        clearance = math.inf
    else:
        clearance = float(final.distance(obstacle_cores)) - half_machine
    if clearance < safety_margin - CLEARANCE_TOLERANCE:
        errors.append(f"Folga minima {clearance:.2f} m menor que a margem {safety_margin:.2f} m.")

    radius = min((minimum_radius(section.coords) for section in sections), default=math.inf)
    if radius < required_radius * (1.0 - RADIUS_TOLERANCE):
        errors.append(f"Raio minimo {radius:.2f} m menor que o exigido {required_radius:.2f} m.")

    inside = all(inside_area(LineString(section.coords), allowed_area) for section in sections)
    if not inside:
        errors.append("Desvio sai da area permitida.")

    self_intersection = not final.is_simple
    if self_intersection:
        errors.append("Trajetoria final com auto-intersecao (laco).")

    start_ok = math.dist(final.coords[0], original.coords[0]) <= GEOMETRY_EPSILON
    end_ok = math.dist(final.coords[-1], original.coords[-1]) <= GEOMETRY_EPSILON
    continuity = start_ok and end_ok
    if not continuity:
        errors.append("Trajetoria final nao preserva inicio/fim da original.")

    forward = all(moves_forward(original, section.coords) for section in sections)
    if not forward:
        errors.append("Desvio com movimento para tras.")

    if not spacing_ok:
        errors.append("Espacamento entre linhas da plantadeira fora da tolerancia.")

    return DetourValidation(
        valid=not errors,
        minimum_clearance=clearance,
        minimum_radius=radius,
        inside_allowed_area=inside,
        self_intersection=self_intersection,
        spacing_ok=spacing_ok,
        continuity_ok=continuity,
        forward_motion=forward,
        errors=tuple(errors),
    )
