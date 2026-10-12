# -*- coding: utf-8 -*-
"""Configuracao de desvio de obstaculos para plantio."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PlantingAvoidanceStrategy(str, Enum):
    AUTO = "auto"
    LATERAL = "lateral"
    CIRCULAR = "circular"
    CONTOUR = "contour"


class PlantingAvoidanceConfigurationError(ValueError):
    """Erro na configuracao de desvio de plantio."""


@dataclass(frozen=True)
class PlantingAvoidanceConfiguration:
    strategy: PlantingAvoidanceStrategy = PlantingAvoidanceStrategy.AUTO
    inner_margin_m: float = 0.50
    outer_margin_m: float = 0.50
    merge_obstacles_m: float = 2.0
    minimum_turn_radius_m: float | None = None
    enabled: bool = True

    def validate(self) -> None:
        if self.inner_margin_m < 0:
            raise PlantingAvoidanceConfigurationError("Margem interna nao pode ser negativa.")
        if self.outer_margin_m < 0:
            raise PlantingAvoidanceConfigurationError("Margem externa nao pode ser negativa.")
        if self.merge_obstacles_m < 0:
            raise PlantingAvoidanceConfigurationError("Distancia de agrupamento nao pode ser negativa.")
        if self.minimum_turn_radius_m is not None and self.minimum_turn_radius_m <= 0:
            raise PlantingAvoidanceConfigurationError("Raio minimo de curva deve ser maior que zero.")

    def total_margin_m(self) -> float:
        return self.inner_margin_m + self.outer_margin_m

    def is_enabled(self) -> bool:
        return self.enabled
