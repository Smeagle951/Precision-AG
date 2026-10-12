# -*- coding: utf-8 -*-
"""Cruzamento inesperado entre passadas operacionais (com indice espacial)."""

from __future__ import annotations

from typing import Sequence

from shapely.strtree import STRtree

from .route_geometry import PreparedRoute, point_parts
from .validation_config import ValidationConfig
from .warning_model import RouteWarning, Severity, WarningType

# Tipos que cruzam de proposito: bordadura, ligacao, tramline, linha auxiliar, manobra.
INTENTIONAL_CROSSING_TYPES = frozenset(
    {"BORDER", "HEADLAND", "AUXILIARY", "AUX", "CONNECTION", "TRAMLINE", "TURN"}
)
ENDPOINT_TOLERANCE_M = 0.01


def validate_crossings(routes: Sequence[PreparedRoute], config: ValidationConfig) -> list[RouteWarning]:
    """Pontos onde duas passadas operacionais se cruzam ou uma encosta no meio da outra.

    Ponta com ponta (ligacao) nao e cruzamento; sobreposicao linear fica com
    DUPLICATED_ROUTE.
    """
    operational = [route for route in routes if route.route_type not in INTENTIONAL_CROSSING_TYPES]
    if len(operational) < 2:
        return []
    tree = STRtree([route.geometry for route in operational])
    warnings = []
    for i, first in enumerate(operational):
        for j in tree.query(first.geometry, predicate="intersects"):
            j = int(j)
            if j <= i:
                continue
            second = operational[j]
            first_ends, second_ends = first.part_endpoints(), second.part_endpoints()
            for point in point_parts(first.geometry.intersection(second.geometry)):
                at_first_end = any(point.distance(p) <= ENDPOINT_TOLERANCE_M for p in first_ends)
                at_second_end = any(point.distance(p) <= ENDPOINT_TOLERANCE_M for p in second_ends)
                if at_first_end and at_second_end:
                    continue
                station = first.station(point)
                warnings.append(RouteWarning(
                    WarningType.UNEXPECTED_ROUTE_CROSSING, Severity.WARNING, first.id,
                    f"Passada {first.id} cruza {second.id} em ponto nao planejado.",
                    pass_index=first.index, geometry=point, related_pass_id=second.id,
                    distance_m=station, end_distance_m=station,
                ))
    return warnings
