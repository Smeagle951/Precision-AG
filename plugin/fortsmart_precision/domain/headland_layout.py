# -*- coding: utf-8 -*-
"""Regras de bordadura por largura operacional."""

from __future__ import annotations

from dataclasses import dataclass


HEADLAND_CORNER_FOLLOW_BOUNDARY = "FOLLOW_BOUNDARY"
HEADLAND_CORNER_STRAIGHT_THROUGH = "STRAIGHT_THROUGH"
HEADLAND_CORNER_AUTO = "AUTO"
HEADLAND_CORNER_MODES = {
    HEADLAND_CORNER_FOLLOW_BOUNDARY,
    HEADLAND_CORNER_STRAIGHT_THROUGH,
    HEADLAND_CORNER_AUTO,
}

HEADLAND_MODE_LEGACY = "LEGACY"
HEADLAND_MODE_FIDELITY = "FIDELITY"
HEADLAND_MODES = {HEADLAND_MODE_LEGACY, HEADLAND_MODE_FIDELITY}


class HeadlandConfigurationError(ValueError):
    """Erro em configuracao de bordadura."""


@dataclass(frozen=True)
class HeadlandLayout:
    pass_count: int = 0
    width_m: float = 0.0
    effective_spacing_m: float | None = None
    mode: str = "none"
    corner_mode: str = HEADLAND_CORNER_AUTO
    sharp_angle_threshold_deg: float = 70.0
    heading_sample_m: float = 0.0
    extension_length_m: float = 0.0
    headland_mode: str = HEADLAND_MODE_LEGACY
    # Metros da barra FISICA que podem ficar fora do limite na 1a passada de
    # bordadura. Nao e a extensao externa das passadas (extension_m).
    outside_overlap_m: float = 0.0

    def validate(self) -> None:
        if self.headland_mode not in HEADLAND_MODES:
            raise HeadlandConfigurationError("Modo de geracao da bordadura desconhecido.")
        if self.pass_count < 0:
            raise HeadlandConfigurationError("Numero de passadas de bordadura nao pode ser negativo.")
        if self.outside_overlap_m < 0:
            raise HeadlandConfigurationError("Faixa permitida para fora do limite nao pode ser negativa.")
        if self.pass_count == 0:
            return
        if self.width_m <= 0:
            raise HeadlandConfigurationError("Largura da bordadura deve ser maior que zero.")
        if self.spacing_m <= 0:
            raise HeadlandConfigurationError("Espacamento efetivo da bordadura deve ser maior que zero.")
        if self.outside_overlap_m >= self.half_width_m:
            raise HeadlandConfigurationError(
                "Faixa permitida para fora do limite deve ser menor que meia barra."
            )
        if self.mode not in {"none", "follow_boundary", "parallel_ab", "perimeter"}:
            raise HeadlandConfigurationError("Modo de bordadura desconhecido.")
        if self.corner_mode not in HEADLAND_CORNER_MODES:
            raise HeadlandConfigurationError("Modo de canto da bordadura desconhecido.")
        if not 0 < self.sharp_angle_threshold_deg < 180:
            raise HeadlandConfigurationError("Limiar de ponta aguda deve estar entre 0 e 180 graus.")
        if self.heading_sample_m < 0 or self.extension_length_m < 0:
            raise HeadlandConfigurationError("Amostra de heading e prolongamento nao podem ser negativos.")

    @property
    def spacing_m(self) -> float:
        return self.effective_spacing_m if self.effective_spacing_m is not None else self.width_m

    @property
    def half_width_m(self) -> float:
        return self.width_m / 2.0

    @property
    def first_center_offset_m(self) -> float:
        """Limite -> linha central da 1a passada: meia barra - faixa para fora."""
        return self.half_width_m - self.outside_overlap_m

    def center_offsets_m(self) -> list[float]:
        self.validate()
        return [
            self.first_center_offset_m + index * self.spacing_m
            for index in range(self.pass_count)
        ]

    @property
    def reserved_width_m(self) -> float:
        """Limite -> borda interna fisica da barra na ultima passada de bordadura."""
        if self.pass_count <= 0:
            return 0.0
        # = 1o centro + (n-1) x passo + meia barra; escrito assim para que,
        # com faixa para fora 0, o valor seja bit a bit o anterior.
        return self.width_m - self.outside_overlap_m + (self.pass_count - 1) * self.spacing_m

    def report(self) -> dict[str, object]:
        return {
            "pass_count": self.pass_count,
            "width_m": self.width_m,
            "effective_spacing_m": self.spacing_m,
            "outside_overlap_m": self.outside_overlap_m,
            "first_center_offset_m": self.first_center_offset_m,
            "center_offsets_m": self.center_offsets_m(),
            "reserved_width_m": self.reserved_width_m,
            "mode": self.mode,
            "corner_mode": self.corner_mode,
            "sharp_angle_threshold_deg": self.sharp_angle_threshold_deg,
            "heading_sample_m": self.heading_sample_m,
            "extension_length_m": self.extension_length_m,
            "headland_mode": self.headland_mode,
        }


def passes_for_total_width(total_width_m: float, machine_width_m: float) -> int:
    """Passadas necessarias para cobrir a faixa de bordadura informada.

    A faixa e informada em metros (ex.: 18 m) e a maquina cobre `machine_width_m`
    por passada. Arredonda para cima: faltar bordadura e pior que sobrar.
    """
    if machine_width_m <= 0:
        raise HeadlandConfigurationError("Largura da maquina deve ser maior que zero.")
    if total_width_m <= 0:
        return 0
    ratio = total_width_m / machine_width_m
    count = int(ratio)
    if ratio - count > 1e-6:
        count += 1
    return max(1, count)
