# -*- coding: utf-8 -*-
"""Calculos de largura operacional e divergencia de configuracao."""

from __future__ import annotations

from dataclasses import dataclass


class WidthConfigurationError(ValueError):
    """Erro em parametros de largura operacional."""


@dataclass(frozen=True)
class WidthComparison:
    method: str
    calculated_width_m: float
    informed_width_m: float
    difference_m: float
    status: str

    @property
    def is_compatible(self) -> bool:
        return self.status == "compatible"


@dataclass(frozen=True)
class OperationWidth:
    informed_width_m: float
    method: str = "count_spacing"
    count: int | None = None
    spacing_m: float | None = None
    first_last_distance_m: float | None = None
    manual_confirmed: bool = False
    tolerance_m: float = 0.01

    def calculated_width_m(self) -> float:
        if self.informed_width_m <= 0:
            raise WidthConfigurationError("Largura informada deve ser maior que zero.")
        if self.method == "count_spacing":
            if not self.count or self.count <= 0:
                raise WidthConfigurationError("Quantidade deve ser maior que zero.")
            if self.spacing_m is None or self.spacing_m <= 0:
                raise WidthConfigurationError("Espacamento deve ser maior que zero.")
            return self.count * self.spacing_m
        if self.method == "interval_spacing":
            if not self.count or self.count <= 1:
                raise WidthConfigurationError("Quantidade deve ser maior que um para metodo por intervalos.")
            if self.spacing_m is None or self.spacing_m <= 0:
                raise WidthConfigurationError("Espacamento deve ser maior que zero.")
            return (self.count - 1) * self.spacing_m
        if self.method == "first_last_distance":
            if self.first_last_distance_m is None or self.first_last_distance_m <= 0:
                raise WidthConfigurationError("Distancia entre primeira e ultima linha deve ser maior que zero.")
            return self.first_last_distance_m
        if self.method == "manual":
            if not self.manual_confirmed:
                raise WidthConfigurationError("Largura manual exige confirmacao do operador.")
            return self.informed_width_m
        raise WidthConfigurationError(f"Metodo de largura desconhecido: {self.method}")

    def compare(self) -> WidthComparison:
        calculated = self.calculated_width_m()
        difference = self.informed_width_m - calculated
        status = "compatible" if abs(difference) <= self.tolerance_m else "review"
        return WidthComparison(
            method=self.method,
            calculated_width_m=calculated,
            informed_width_m=self.informed_width_m,
            difference_m=difference,
            status=status,
        )


def half_width(width_m: float, lateral_offset_m: float = 0.0) -> tuple[float, float]:
    """Retorna meia largura esquerda/direita.

    Offset positivo significa deslocamento para a direita, conforme a
    especificacao. Assim a cobertura aumenta para a esquerda e reduz para a
    direita em relacao ao centro operacional.
    """
    if width_m <= 0:
        raise WidthConfigurationError("Largura deve ser maior que zero.")
    left = width_m / 2.0 + lateral_offset_m
    right = width_m / 2.0 - lateral_offset_m
    if left <= 0 or right <= 0:
        raise WidthConfigurationError("Offset lateral maior que a meia largura operacional.")
    return left, right
