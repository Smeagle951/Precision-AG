# -*- coding: utf-8 -*-
"""Configuracao de desvio de obstaculos."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .path_smoothing_configuration import SmoothingLevel

__all__ = [
    "AvoidanceMode",
    "SmoothingLevel",
    "AvoidanceConfiguration",
    "AvoidanceConfigurationError",
    "SPRAY_SIDE_AUTO",
    "SPRAY_SIDE_LEFT",
    "SPRAY_SIDE_RIGHT",
    "SPRAY_SIDE_PREFERENCES",
]

SPRAY_SIDE_AUTO = "auto"
SPRAY_SIDE_LEFT = "left"
SPRAY_SIDE_RIGHT = "right"
SPRAY_SIDE_PREFERENCES = (SPRAY_SIDE_AUTO, SPRAY_SIDE_LEFT, SPRAY_SIDE_RIGHT)


class AvoidanceConfigurationError(ValueError):
    """Erro na configuracao de desvio."""


class AvoidanceMode(str, Enum):
    NONE = "none"
    DETOUR = "detour"
    CONCENTRIC_RING = "concentric_ring"


@dataclass(frozen=True)
class AvoidanceConfiguration:
    mode: AvoidanceMode = AvoidanceMode.CONCENTRIC_RING
    smoothing: SmoothingLevel = SmoothingLevel.MED
    minimum_turn_radius_m: float | None = None
    merge_adjacent_envelopes_m: float = 2.0
    # True = pulverizacao da uma volta completa (360°) no obstaculo circular.
    orbit_360: bool = False
    # True = classificacao por passada x obstaculo (NONE/LATERAL/FULL_CONTOUR/
    # UNRESOLVED) com o menor desvio seguro; False = anel em toda passada (legado).
    minimum_deviation: bool = False
    side_preference: str = SPRAY_SIDE_AUTO
    # Trecho minimo ja deslocado antes/depois da zona de seguranca (0 = automatico).
    preparation_distance_m: float = 0.0
    return_distance_m: float = 0.0

    def validate(self) -> None:
        if self.minimum_turn_radius_m is not None and self.minimum_turn_radius_m <= 0:
            raise AvoidanceConfigurationError("Raio minimo de curva deve ser maior que zero.")
        if self.merge_adjacent_envelopes_m < 0:
            raise AvoidanceConfigurationError("Distancia de fusao nao pode ser negativa.")
        if self.side_preference not in SPRAY_SIDE_PREFERENCES:
            raise AvoidanceConfigurationError(
                "Lado do desvio deve ser 'auto', 'left' ou 'right'."
            )
        if self.preparation_distance_m < 0 or self.return_distance_m < 0:
            raise AvoidanceConfigurationError(
                "Distancias de preparacao/retorno nao podem ser negativas."
            )

    def enabled(self) -> bool:
        return self.mode != AvoidanceMode.NONE
