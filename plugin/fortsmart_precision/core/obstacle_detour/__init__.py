# -*- coding: utf-8 -*-
"""Desvio manual de obstaculo: uma linha + um obstaculo, decidido pelo operador."""

from .geometry import build_manual_detour, detour_debug_text, safety_zone, suggest_lateral_distances
from .models import (
    DETOUR_TYPE_LABELS,
    LINE_DIRECTION_LABELS,
    V1_DETOUR_TYPES,
    DetourParameters,
    DetourStatus,
    DetourType,
    LineDirection,
    NearbyObstacle,
    ObstacleDetour,
    selection_error,
)

__all__ = [
    "NearbyObstacle",
    "selection_error",
    "DETOUR_TYPE_LABELS",
    "LINE_DIRECTION_LABELS",
    "V1_DETOUR_TYPES",
    "DetourParameters",
    "DetourStatus",
    "DetourType",
    "LineDirection",
    "ObstacleDetour",
    "build_manual_detour",
    "detour_debug_text",
    "safety_zone",
    "suggest_lateral_distances",
]
