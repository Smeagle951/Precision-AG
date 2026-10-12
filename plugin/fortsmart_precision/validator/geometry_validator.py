# -*- coding: utf-8 -*-
"""Geometria das passadas: vazia/invalida, curta, duplicada e quebra brusca de direcao."""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from shapely.geometry import Point
from shapely.strtree import STRtree

from ..core.simulation_route import RoutePassInput
from .route_geometry import PreparedRoute, line_parts
from .validation_config import ValidationConfig
from .warning_model import RouteWarning, Severity, WarningType

ZERO_LENGTH_M = 0.01


def structural_check(
    routes: Sequence[RoutePassInput],
) -> tuple[list[RouteWarning], list[tuple[int, RoutePassInput]]]:
    """EMPTY_ROUTE / INVALID_GEOMETRY / ZERO_LENGTH_ROUTE (CRITICAL); devolve as validas."""
    warnings: list[RouteWarning] = []
    valid: list[tuple[int, RoutePassInput]] = []
    for index, item in enumerate(routes):
        if not item.segments:
            warnings.append(RouteWarning(
                WarningType.EMPTY_ROUTE, Severity.CRITICAL, item.id,
                f"Passada {item.id} sem geometria.", pass_index=index,
            ))
            continue
        bad = [
            part for part in item.segments
            if len(part) < 2 or not all(math.isfinite(c) for point in part for c in point)
        ]
        if bad:
            warnings.append(RouteWarning(
                WarningType.INVALID_GEOMETRY, Severity.CRITICAL, item.id,
                f"Passada {item.id} com geometria invalida (parte com menos de 2 vertices "
                "ou coordenada nao numerica).", pass_index=index,
            ))
            continue
        length = sum(
            math.hypot(b[0] - a[0], b[1] - a[1]) for part in item.segments for a, b in zip(part, part[1:])
        )
        if length <= ZERO_LENGTH_M:
            warnings.append(RouteWarning(
                WarningType.ZERO_LENGTH_ROUTE, Severity.CRITICAL, item.id,
                f"Passada {item.id} com comprimento zero.", pass_index=index,
                geometry=Point(item.segments[0][0]),
            ))
            continue
        valid.append((index, item))
    return warnings, valid


def short_routes(routes: Sequence[PreparedRoute], config: ValidationConfig) -> list[RouteWarning]:
    warnings = []
    for route in routes:
        for part in route.parts:
            if part.length < config.minimum_route_length_m:
                start, end = route.stations_of(part)
                warnings.append(RouteWarning(
                    WarningType.ROUTE_TOO_SHORT, Severity.WARNING, route.id,
                    f"Passada {route.id}: trecho de {part.length:.2f} m (minimo "
                    f"{config.minimum_route_length_m:.2f} m). Possivel residuo de corte.",
                    pass_index=route.index, geometry=part, distance_m=start, end_distance_m=end,
                    expected_value=config.minimum_route_length_m, actual_value=part.length,
                    difference=part.length - config.minimum_route_length_m,
                ))
    return warnings


def duplicated_routes(routes: Sequence[PreparedRoute], config: ValidationConfig) -> list[RouteWarning]:
    """Trechos de passadas diferentes a menos de `duplicate_tolerance_m` um do outro."""
    if len(routes) < 2:
        return []
    tree = STRtree([route.geometry for route in routes])
    tol = config.duplicate_tolerance_m
    warnings = []
    for i, first in enumerate(routes):
        for j in tree.query(first.geometry, predicate="dwithin", distance=tol):
            j = int(j)
            if j <= i:
                continue
            second = routes[j]
            overlap = second.geometry.intersection(first.geometry.buffer(tol, cap_style="flat"))
            parts = [p for p in line_parts(overlap) if p.length > 1e-6]
            length = sum(p.length for p in parts)
            if length < config.duplicate_min_overlap_m:
                continue
            shorter = min(first.length, second.length)
            geometry = parts[0] if len(parts) == 1 else overlap
            start, end = second.stations_of(geometry)
            warnings.append(RouteWarning(
                WarningType.DUPLICATED_ROUTE, Severity.WARNING, second.id,
                f"Passada {second.id} coincide com {first.id} em {length:.2f} m "
                f"({100.0 * length / shorter:.0f}% da menor; tolerancia {tol:.2f} m).",
                pass_index=second.index, geometry=geometry, related_pass_id=first.id,
                distance_m=start, end_distance_m=end, actual_value=length,
            ))
    return warnings


def sharp_direction_changes(routes: Sequence[PreparedRoute], config: ValidationConfig) -> list[RouteWarning]:
    """Mudanca de rumo maior que o limite dentro da janela curta (curva suave nao dispara).

    Em cada vertice compara o rumo de (s - janela -> s) com (s -> s + janela):
    numa curva de raio R a diferenca e ~ janela / R; numa quina e o angulo inteiro.
    """
    window = config.direction_change_window_m
    warnings = []
    for route in routes:
        offset = 0.0
        for part in route.parts:
            coords = np.asarray(part.coords, dtype=float)
            if len(coords) >= 3:
                stations = np.concatenate(([0.0], np.cumsum(np.hypot(*np.diff(coords, axis=0).T))))
                inner = stations[1:-1]
                before = np.clip(inner - window, 0.0, stations[-1])
                after = np.clip(inner + window, 0.0, stations[-1])
                bx, by = np.interp(before, stations, coords[:, 0]), np.interp(before, stations, coords[:, 1])
                ax, ay = np.interp(after, stations, coords[:, 0]), np.interp(after, stations, coords[:, 1])
                vx, vy = coords[1:-1, 0], coords[1:-1, 1]
                heading_in = np.degrees(np.arctan2(vx - bx, vy - by))
                heading_out = np.degrees(np.arctan2(ax - vx, ay - vy))
                change = np.abs((heading_out - heading_in + 180.0) % 360.0 - 180.0)
                flagged = np.flatnonzero(change > config.max_direction_change_deg)
                for cluster in _clusters(flagged, inner, window):
                    worst = cluster[int(np.argmax(change[cluster]))]
                    station = float(inner[worst])
                    warnings.append(RouteWarning(
                        WarningType.SHARP_DIRECTION_CHANGE, Severity.WARNING, route.id,
                        f"Passada {route.id}: mudanca de direcao de {change[worst]:.0f} graus em "
                        f"{2 * window:.1f} m (limite {config.max_direction_change_deg:.0f} graus). "
                        "Possivel V, U, quina artificial ou erro de corte.",
                        pass_index=route.index, geometry=Point(coords[worst + 1]),
                        distance_m=offset + station, end_distance_m=offset + station,
                        expected_value=config.max_direction_change_deg, actual_value=float(change[worst]),
                        difference=float(change[worst]) - config.max_direction_change_deg,
                    ))
            offset += part.length
    return warnings


def _clusters(flagged: np.ndarray, stations: np.ndarray, window: float) -> list[list[int]]:
    groups: list[list[int]] = []
    for index in flagged.tolist():
        if groups and stations[index] - stations[groups[-1][-1]] <= window:
            groups[-1].append(index)
        else:
            groups.append([index])
    return groups
