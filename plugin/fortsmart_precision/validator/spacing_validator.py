# -*- coding: utf-8 -*-
"""Espacamento real entre passadas vizinhas, amostrado ao longo da linha (nunca por centroide)."""

from __future__ import annotations

from typing import Sequence

import numpy as np
import shapely
from shapely.geometry import MultiPoint
from shapely.strtree import STRtree

from .route_geometry import PreparedRoute
from .validation_config import ValidationConfig
from .warning_model import RouteWarning, Severity, WarningType

# Vizinha = distancia mediana entre 0,5x e 1,5x o espacamento esperado.
NEIGHBOUR_RANGE = (0.5, 1.5)


def _samples(route: PreparedRoute, step: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Pontos a cada `step` metros (meio de cada intervalo), estacao e indice da parte."""
    points, stations, part_ids = [], [], []
    offset = 0.0
    for part_id, part in enumerate(route.parts):
        count = max(1, int(part.length // step))
        local = (np.arange(count) + 0.5) * (part.length / count)
        coords = shapely.get_coordinates(shapely.line_interpolate_point(part, local))
        points.append(coords)
        stations.append(offset + local)
        part_ids.append(np.full(count, part_id))
        offset += part.length
    return np.vstack(points), np.concatenate(stations), np.concatenate(part_ids)


def validate_spacing(
    routes: Sequence[PreparedRoute], expected_spacing_m: float | None, config: ValidationConfig
) -> list[RouteWarning]:
    """Para cada par de vizinhas, mede da passada posterior ate a anterior a cada amostra.

    Vizinhas vem do indice espacial (passadas a ate 1,5x o espacamento), nao da
    numeracao. Amostras cujo pe cai na ponta da vizinha nao tem vizinha na normal.
    """
    if not expected_spacing_m or expected_spacing_m <= 0 or len(routes) < 2:
        return []
    tree = STRtree([route.geometry for route in routes])
    tolerance = config.spacing_tolerance_m
    step = config.spacing_sample_every_m
    low, high = (factor * expected_spacing_m for factor in NEIGHBOUR_RANGE)
    sample_cache: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    warnings = []
    for i, route in enumerate(routes):
        for j in tree.query(route.geometry, predicate="dwithin", distance=high):
            j = int(j)
            if j == i:
                continue
            neighbour = routes[j]
            if neighbour.route_type != route.route_type or (neighbour.index, neighbour.id) > (route.index, route.id):
                continue
            if i not in sample_cache:
                sample_cache[i] = _samples(route, step)
            coords, stations, part_ids = sample_cache[i]
            points = shapely.points(coords)
            distances = shapely.distance(points, neighbour.geometry)
            to_ends = shapely.distance(points, MultiPoint(neighbour.part_endpoints()))
            valid = to_ends - distances > 1e-6
            if valid.sum() < 2:
                continue
            median = float(np.median(distances[valid]))
            if not low <= median <= high:
                continue
            bad = valid & (np.abs(distances - expected_spacing_m) > tolerance + 1e-9)
            for run in _runs(np.flatnonzero(bad), part_ids):
                worst = run[int(np.argmax(np.abs(distances[run] - expected_spacing_m)))]
                start = max(0.0, float(stations[run[0]]) - step / 2.0)
                end = min(route.length, float(stations[run[-1]]) + step / 2.0)
                measured = float(distances[worst])
                deviation = measured - expected_spacing_m
                warnings.append(RouteWarning(
                    WarningType.SPACING_OUT_OF_TOLERANCE, Severity.WARNING, route.id,
                    f"Passada {route.id}: espacamento fora do padrao com {neighbour.id}\n"
                    f"Esperado: {expected_spacing_m:.2f} m\nMedido: {measured:.2f} m\n"
                    f"Desvio: {deviation:+.2f} m (tolerancia {tolerance:.2f} m)",
                    pass_index=route.index, geometry=route.between(start, end),
                    related_pass_id=neighbour.id, distance_m=start, end_distance_m=end,
                    expected_value=expected_spacing_m, actual_value=measured, difference=deviation,
                ))
    return warnings


def _runs(indices: np.ndarray, part_ids: np.ndarray) -> list[np.ndarray]:
    """Amostras consecutivas da mesma parte formam um trecho."""
    if indices.size == 0:
        return []
    breaks = np.flatnonzero((np.diff(indices) != 1) | (np.diff(part_ids[indices]) != 0)) + 1
    return np.split(indices, breaks)
