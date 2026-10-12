# -*- coding: utf-8 -*-
"""Trechos de passada fora da area permitida (so o trecho que saiu vira aviso)."""

from __future__ import annotations

from typing import Sequence

from .route_geometry import PreparedRoute, line_parts
from .validation_config import ValidationConfig
from .warning_model import RouteWarning, Severity, WarningType


def validate_boundary(
    routes: Sequence[PreparedRoute], allowed_area, config: ValidationConfig
) -> list[RouteWarning]:
    """route - allowed_area; trecho encostado na ponta pode ser avanco de cabeceira permitido."""
    if allowed_area is None or allowed_area.is_empty:
        return []
    tol = config.boundary_tolerance_m
    warnings = []
    for route in routes:
        outside = route.geometry.difference(allowed_area)
        ends = route.part_endpoints()
        for piece in line_parts(outside):
            if piece.length <= tol:
                continue
            start, end = route.stations_of(piece)
            at_end = any(piece.distance(point) <= tol for point in ends)
            limit = config.max_headland_overrun_m
            overrun = config.allow_headland_overrun and at_end and (limit is None or piece.length <= limit + tol)
            if overrun:
                severity = Severity.INFO
                message = (
                    f"Passada {route.id}: avanco de cabeceira de {piece.length:.2f} m fora da "
                    "area permitida (permitido pela configuracao)."
                )
            else:
                severity = Severity.CRITICAL
                message = f"Passada {route.id} possui trecho fora da area permitida ({piece.length:.2f} m)."
            warnings.append(RouteWarning(
                WarningType.OUTSIDE_ALLOWED_AREA, severity, route.id, message,
                pass_index=route.index, geometry=piece, distance_m=start, end_distance_m=end,
                actual_value=piece.length,
                expected_value=limit if overrun and limit is not None else 0.0,
            ))
    return warnings
