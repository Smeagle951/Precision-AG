# -*- coding: utf-8 -*-
"""Aviso do validador de rota: o que esta errado, onde, em qual passada e com qual gravidade."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class WarningStatus(str, Enum):
    OPEN = "OPEN"
    REVIEWED = "REVIEWED"
    RESOLVED = "RESOLVED"
    IGNORED = "IGNORED"


class WarningType(str, Enum):
    OUTSIDE_ALLOWED_AREA = "OUTSIDE_ALLOWED_AREA"
    OBSTACLE_INTERSECTION = "OBSTACLE_INTERSECTION"
    UNEXPECTED_ROUTE_CROSSING = "UNEXPECTED_ROUTE_CROSSING"
    SPACING_OUT_OF_TOLERANCE = "SPACING_OUT_OF_TOLERANCE"
    DUPLICATED_ROUTE = "DUPLICATED_ROUTE"
    ROUTE_TOO_SHORT = "ROUTE_TOO_SHORT"
    INVALID_GEOMETRY = "INVALID_GEOMETRY"
    EMPTY_ROUTE = "EMPTY_ROUTE"
    ZERO_LENGTH_ROUTE = "ZERO_LENGTH_ROUTE"
    SHARP_DIRECTION_CHANGE = "SHARP_DIRECTION_CHANGE"
    NEXT_ROUTE_TOO_FAR = "NEXT_ROUTE_TOO_FAR"
    ROUTE_SEQUENCE_SUSPECT = "ROUTE_SEQUENCE_SUSPECT"


# Filtros do painel.
WARNING_CATEGORIES: dict[str, tuple[WarningType, ...]] = {
    "SPACING": (WarningType.SPACING_OUT_OF_TOLERANCE,),
    "OBSTACLE": (WarningType.OBSTACLE_INTERSECTION,),
    "BOUNDARY": (WarningType.OUTSIDE_ALLOWED_AREA,),
    "CROSSING": (WarningType.UNEXPECTED_ROUTE_CROSSING,),
    "GEOMETRY": (
        WarningType.DUPLICATED_ROUTE,
        WarningType.ROUTE_TOO_SHORT,
        WarningType.INVALID_GEOMETRY,
        WarningType.EMPTY_ROUTE,
        WarningType.ZERO_LENGTH_ROUTE,
        WarningType.SHARP_DIRECTION_CHANGE,
    ),
    "SEQUENCE": (WarningType.NEXT_ROUTE_TOO_FAR, WarningType.ROUTE_SEQUENCE_SUSPECT),
}

# Sem estes a passada nao pode ser simulada.
STRUCTURAL_TYPES = (WarningType.EMPTY_ROUTE, WarningType.INVALID_GEOMETRY, WarningType.ZERO_LENGTH_ROUTE)


def category_of(warning_type: WarningType) -> str:
    for category, types in WARNING_CATEGORIES.items():
        if warning_type in types:
            return category
    return "GEOMETRY"


@dataclass
class RouteWarning:
    warning_type: WarningType
    severity: Severity
    pass_id: str
    message: str
    pass_index: int | None = None
    # Geometria shapely no CRS metrico da validacao (so o trecho/ponto do problema).
    geometry: object = None
    distance_m: float | None = None
    end_distance_m: float | None = None
    expected_value: float | None = None
    actual_value: float | None = None
    difference: float | None = None
    related_pass_id: str | None = None
    obstacle_id: str | None = None
    id: str = ""
    status: WarningStatus = WarningStatus.OPEN
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    @property
    def category(self) -> str:
        return category_of(self.warning_type)

    def involves(self, pass_id: str) -> bool:
        return pass_id in (self.pass_id, self.related_pass_id)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "warning_type": self.warning_type.value,
            "severity": self.severity.value,
            "status": self.status.value,
            "pass_id": self.pass_id,
            "pass_index": self.pass_index,
            "related_pass_id": self.related_pass_id,
            "obstacle_id": self.obstacle_id,
            "message": self.message,
            "distance_m": self.distance_m,
            "end_distance_m": self.end_distance_m,
            "expected_value": self.expected_value,
            "actual_value": self.actual_value,
            "difference": self.difference,
            "created_at": self.created_at,
            "geometry_wkt": None if self.geometry is None else self.geometry.wkt,
        }
