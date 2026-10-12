# -*- coding: utf-8 -*-
"""Cinematica trator + plantadeira (configuravel na GUI)."""

from __future__ import annotations

from dataclasses import dataclass


class PlantingKinematicsError(ValueError):
    """Erro na cinematica de plantio."""


@dataclass(frozen=True)
class PlantingKinematics:
    """Parametros fisicos trator/implemento informados pelo usuario."""

    operational_width_m: float
    track_width_m: float
    gnss_reference: str = "tractor_center"
    gnss_offset_m: float = 0.0
    hitch_distance_m: float = 0.0
    implement_center_offset_m: float = 0.0
    tractor_length_m: float | None = None
    minimum_turn_radius_m: float | None = None
    row_count: int = 0
    row_spacing_m: float = 0.0

    def validate(self) -> None:
        if self.operational_width_m <= 0:
            raise PlantingKinematicsError("Largura operacional deve ser maior que zero.")
        if self.track_width_m < 0:
            raise PlantingKinematicsError("Bitola nao pode ser negativa.")
        if self.gnss_reference not in {"tractor_center", "implement_center"}:
            raise PlantingKinematicsError("Referencia GNSS invalida.")
        if self.hitch_distance_m < 0:
            raise PlantingKinematicsError("Distancia de articulacao nao pode ser negativa.")
        if self.tractor_length_m is not None and self.tractor_length_m <= 0:
            raise PlantingKinematicsError("Comprimento do trator deve ser maior que zero.")
        if self.minimum_turn_radius_m is not None and self.minimum_turn_radius_m <= 0:
            raise PlantingKinematicsError("Raio minimo de curva deve ser maior que zero.")
        if self.row_count < 0:
            raise PlantingKinematicsError("Numero de linhas nao pode ser negativo.")
        if self.row_spacing_m < 0:
            raise PlantingKinematicsError("Espacamento entre linhas nao pode ser negativo.")

    @property
    def half_operational_width_m(self) -> float:
        return self.operational_width_m / 2.0

    @property
    def half_track_width_m(self) -> float:
        # 0 = bitola nao informada (plantio usa hitch + raio de giro).
        return self.track_width_m / 2.0 if self.track_width_m > 0 else 0.0

    def row_offsets(self) -> list[float]:
        """Offsets laterais das linhas fisicas a partir do centro do implemento."""
        self.validate()
        if self.row_count <= 0 or self.row_spacing_m <= 0:
            # Fallback: extremos da largura operacional (2 "linhas" virtuais).
            half = self.half_operational_width_m
            return [-half, half]
        return [
            (i - (self.row_count + 1) / 2.0) * self.row_spacing_m
            for i in range(1, self.row_count + 1)
        ]
