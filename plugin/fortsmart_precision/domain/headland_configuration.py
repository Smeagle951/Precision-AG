# -*- coding: utf-8 -*-
"""Configuracao de criacao e geometria da bordadura."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .headland_layout import HeadlandConfigurationError, HeadlandLayout


class HeadlandCreationMode(str, Enum):
    NONE = "none"
    PASSES_1 = "passes_1"
    PASSES_2 = "passes_2"
    PASSES_3 = "passes_3"
    CUSTOM_COUNT = "custom_count"
    MANUAL_WIDTH = "manual_width"
    EXISTING_LAYER = "existing_layer"


class HeadlandGeometryType(str, Enum):
    FOLLOW_BOUNDARY = "follow_boundary"
    PARALLEL_AB = "parallel_ab"
    HYBRID = "hybrid"
    EXISTING = "existing"


# Modos geometricos disponiveis na Etapa 1 (area por buffer / reserva).
ETAPA1_GEOMETRY_TYPES = {HeadlandGeometryType.PARALLEL_AB}


@dataclass(frozen=True)
class HeadlandConfiguration:
    """Configuracao de alto nivel; gera um `HeadlandLayout` interno."""

    creation_mode: HeadlandCreationMode = HeadlandCreationMode.NONE
    geometry_type: HeadlandGeometryType = HeadlandGeometryType.PARALLEL_AB
    pass_count: int = 0
    width_m: float = 0.0
    effective_spacing_m: float | None = None
    manual_width_m: float | None = None

    def validate(self) -> None:
        if self.creation_mode == HeadlandCreationMode.EXISTING_LAYER:
            raise HeadlandConfigurationError(
                "Bordadura existente ainda nao esta disponivel nesta etapa."
            )
        if self.geometry_type in {
            HeadlandGeometryType.FOLLOW_BOUNDARY,
            HeadlandGeometryType.HYBRID,
            HeadlandGeometryType.EXISTING,
        }:
            raise HeadlandConfigurationError(
                f"Geometria de bordadura '{self.geometry_type.value}' nao disponivel na Etapa 1."
            )
        layout = self.to_layout()
        layout.validate()

    def resolved_pass_count(self) -> int:
        mapping = {
            HeadlandCreationMode.NONE: 0,
            HeadlandCreationMode.PASSES_1: 1,
            HeadlandCreationMode.PASSES_2: 2,
            HeadlandCreationMode.PASSES_3: 3,
            HeadlandCreationMode.CUSTOM_COUNT: self.pass_count,
            HeadlandCreationMode.MANUAL_WIDTH: self.pass_count if self.pass_count > 0 else 1,
            HeadlandCreationMode.EXISTING_LAYER: 0,
        }
        return mapping[self.creation_mode]

    def resolved_width_m(self) -> float:
        if self.creation_mode == HeadlandCreationMode.NONE:
            return 0.0
        if self.creation_mode == HeadlandCreationMode.MANUAL_WIDTH:
            if self.manual_width_m is None or self.manual_width_m <= 0:
                raise HeadlandConfigurationError("Largura manual de bordadura invalida.")
            return self.manual_width_m
        return self.width_m

    def to_layout(self) -> HeadlandLayout:
        count = self.resolved_pass_count()
        mode = "none" if count == 0 else "parallel_ab"
        width = self.resolved_width_m()
        if self.creation_mode == HeadlandCreationMode.MANUAL_WIDTH and count > 0:
            # Largura total manual: uma "passada" conceitual com width = manual.
            return HeadlandLayout(
                pass_count=1,
                width_m=width,
                effective_spacing_m=width,
                mode=mode,
            )
        return HeadlandLayout(
            pass_count=count,
            width_m=width if count else 0.0,
            effective_spacing_m=self.effective_spacing_m,
            mode=mode,
        )

    def center_offsets_m(self) -> list[float]:
        return self.to_layout().center_offsets_m()

    @property
    def reserved_width_m(self) -> float:
        return self.to_layout().reserved_width_m

    def report(self) -> dict[str, object]:
        layout = self.to_layout()
        return {
            "creation_mode": self.creation_mode.value,
            "geometry_type": self.geometry_type.value,
            **layout.report(),
        }
