# -*- coding: utf-8 -*-
"""Configuracao de plantio e posicoes fisicas da plantadeira."""

from __future__ import annotations

from dataclasses import dataclass

from .operation_width import OperationWidth, WidthComparison
from .planter_geometry import PlanterGeometryConfig, resolve_effective_working_width


class PlantingConfigurationError(ValueError):
    """Erro em parametros de plantio."""


@dataclass(frozen=True)
class PlantingConfiguration:
    row_count: int
    row_spacing_m: float
    informed_width_m: float | None = None
    width_method: str = "count_spacing"
    lateral_offset_m: float = 0.0
    tractor_center_offset_m: float = 0.0
    implement_center_offset_m: float = 0.0
    gnss_offset_m: float = 0.0

    def validate(self) -> None:
        if self.row_count <= 0:
            raise PlantingConfigurationError("Numero de linhas da plantadeira deve ser maior que zero.")
        if self.row_spacing_m <= 0:
            raise PlantingConfigurationError("Espacamento entre linhas deve ser maior que zero.")

    @property
    def geometry_config(self) -> PlanterGeometryConfig:
        return PlanterGeometryConfig(
            row_count=self.row_count,
            row_spacing_m=self.row_spacing_m,
            configured_width_m=self.informed_width_m or None,
        )

    @property
    def calculated_width_m(self) -> float:
        self.validate()
        return self.geometry_config.row_based_width_m

    @property
    def working_width_m(self) -> float:
        self.validate()
        return resolve_effective_working_width(self.geometry_config)

    @property
    def half_width_m(self) -> float:
        return self.working_width_m / 2.0

    def width_comparison(self) -> WidthComparison:
        return OperationWidth(
            informed_width_m=self.working_width_m,
            method=self.width_method,
            count=self.row_count,
            spacing_m=self.row_spacing_m,
            manual_confirmed=self.width_method == "manual",
        ).compare()

    def row_offset_from_center(self, implement_position: int) -> float:
        self.validate()
        if implement_position < 1 or implement_position > self.row_count:
            raise PlantingConfigurationError("Posicao da linha fora da plantadeira.")
        return self.geometry_config.row_offsets()[implement_position - 1]

    def all_row_offsets(self) -> list[float]:
        return [self.row_offset_from_center(pos) for pos in range(1, self.row_count + 1)]

    def meeting_spacing_m(self) -> float:
        offsets = self.all_row_offsets()
        return self.working_width_m + offsets[0] - offsets[-1]

    def meeting_status(self, tolerance_m: float = 0.01) -> dict[str, float | str]:
        gap = self.meeting_spacing_m()
        diff = gap - self.row_spacing_m
        return {
            "internal_spacing_m": self.row_spacing_m,
            "meeting_spacing_m": gap,
            "difference_m": diff,
            "status": "correct" if abs(diff) <= tolerance_m else "review",
        }
