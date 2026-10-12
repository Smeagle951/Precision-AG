# -*- coding: utf-8 -*-
"""Configuracao de pulverizacao."""

from __future__ import annotations

from dataclasses import dataclass

from .operation_width import OperationWidth, WidthComparison


class SprayingConfigurationError(ValueError):
    """Erro em parametros de pulverizacao."""


@dataclass(frozen=True)
class SprayingConfiguration:
    boom_width_m: float
    nozzle_count: int
    nozzle_spacing_m: float
    width_method: str = "count_spacing"
    overlap_value: float = 0.0
    overlap_unit: str = "m"
    overlap_basis: str = "total"

    def validate(self) -> None:
        if self.boom_width_m <= 0:
            raise SprayingConfigurationError("Largura da barra deve ser maior que zero.")
        if self.nozzle_count <= 0:
            raise SprayingConfigurationError("Numero de bicos deve ser maior que zero.")
        if self.nozzle_spacing_m <= 0:
            raise SprayingConfigurationError("Espacamento entre bicos deve ser maior que zero.")
        if self.overlap_value < 0:
            raise SprayingConfigurationError("Remonte nao pode ser negativo.")
        if self.overlap_basis not in {"total", "each_side"}:
            raise SprayingConfigurationError("Base do remonte deve ser total ou por lado.")

    @property
    def width_by_nozzle_count_m(self) -> float:
        self.validate()
        return self.nozzle_count * self.nozzle_spacing_m

    @property
    def width_by_nozzle_intervals_m(self) -> float:
        self.validate()
        if self.nozzle_count <= 1:
            raise SprayingConfigurationError("Metodo por intervalos exige mais de um bico.")
        return (self.nozzle_count - 1) * self.nozzle_spacing_m

    def width_comparison(self) -> WidthComparison:
        self.validate()
        method = "interval_spacing" if self.width_method == "interval_spacing" else "count_spacing"
        return OperationWidth(
            informed_width_m=self.boom_width_m,
            method=method,
            count=self.nozzle_count,
            spacing_m=self.nozzle_spacing_m,
        ).compare()

    @property
    def overlap_total_m(self) -> float:
        self.validate()
        if self.overlap_unit == "percent":
            value_m = self.boom_width_m * self.overlap_value / 100.0
        elif self.overlap_unit == "cm":
            value_m = self.overlap_value / 100.0
        elif self.overlap_unit == "m":
            value_m = self.overlap_value
        else:
            raise SprayingConfigurationError("Unidade de remonte invalida.")
        return value_m * 2.0 if self.overlap_basis == "each_side" else value_m

    @property
    def overlap_each_side_m(self) -> float:
        return self.overlap_total_m / 2.0

    @property
    def effective_spacing_m(self) -> float:
        spacing = self.boom_width_m - self.overlap_total_m
        if spacing <= 0:
            raise SprayingConfigurationError("Remonte deve ser menor que a largura da barra.")
        return spacing

    @property
    def half_boom_width_m(self) -> float:
        return self.boom_width_m / 2.0
