# -*- coding: utf-8 -*-
"""Transicao entre passadas consecutivas: salto de sequencia e inicio distante."""

from __future__ import annotations

import statistics
from typing import Sequence

from shapely.geometry import LineString
from shapely.ops import nearest_points

from .route_geometry import PreparedRoute
from .validation_config import ValidationConfig
from .warning_model import RouteWarning, Severity, WarningType


def validate_transitions(
    routes: Sequence[PreparedRoute], expected_spacing_m: float | None, config: ValidationConfig
) -> list[RouteWarning]:
    """Nunca reordena: so avisa ROUTE_SEQUENCE_SUSPECT e NEXT_ROUTE_TOO_FAR.

    Salto lateral (distancia entre as passadas) acima de fator x referencia
    sugere ordem errada; referencia = espacamento esperado ou mediana dos saltos.
    Transicao (ponta mais proxima da atual ate a proxima) acima do limite indica
    inicio distante.
    """
    ordered = sorted(routes, key=lambda route: route.index)
    pairs = list(zip(ordered, ordered[1:]))
    if not pairs:
        return []
    lateral = [a.geometry.distance(b.geometry) for a, b in pairs]
    reference = expected_spacing_m or statistics.median(lateral)
    max_transition = config.max_transition_distance_m
    if max_transition is None and reference > 0:
        max_transition = 3.0 * reference
    warnings = []
    for (current, following), jump in zip(pairs, lateral):
        if reference > 0 and jump > config.sequence_jump_factor * reference:
            a, b = nearest_points(current.geometry, following.geometry)
            warnings.append(RouteWarning(
                WarningType.ROUTE_SEQUENCE_SUSPECT, Severity.WARNING, following.id,
                f"Sequencia suspeita: {current.id} -> {following.id} salta {jump:.2f} m "
                f"(referencia {reference:.2f} m). Nenhuma reordenacao foi feita.",
                pass_index=following.index, geometry=LineString([a, b]), related_pass_id=current.id,
                expected_value=reference, actual_value=jump, difference=jump - reference,
            ))
            continue
        if max_transition is None:
            continue
        start, end = min(
            ((p, q) for p in current.endpoints for q in following.endpoints),
            key=lambda pair: pair[0].distance(pair[1]),
        )
        transition = start.distance(end)
        if transition > max_transition:
            warnings.append(RouteWarning(
                WarningType.NEXT_ROUTE_TOO_FAR, Severity.WARNING, following.id,
                f"Inicio de {following.id} a {transition:.2f} m do fim de {current.id} "
                f"(limite {max_transition:.2f} m).",
                pass_index=following.index, geometry=LineString([start, end]),
                related_pass_id=current.id, expected_value=max_transition,
                actual_value=transition, difference=transition - max_transition,
            ))
    return warnings
