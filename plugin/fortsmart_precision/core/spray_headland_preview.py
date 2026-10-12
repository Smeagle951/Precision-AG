# -*- coding: utf-8 -*-
"""Resumo e esquema da 1a passada de bordadura da aplicacao (sem Qt)."""

from __future__ import annotations

from ..domain.headland_layout import HeadlandLayout


def format_m(value: float) -> str:
    return f"{value:.2f} m".replace(".", ",")


def spray_headland_summary(layout: HeadlandLayout) -> str:
    """Barra fisica / meia barra / faixa fora / linha central / passo efetivo."""
    return (
        f"Barra fisica: {format_m(layout.width_m)} / "
        f"Meia barra: {format_m(layout.half_width_m)} / "
        f"Faixa fora: {format_m(layout.outside_overlap_m)} / "
        f"Linha central: {format_m(layout.first_center_offset_m)} do limite / "
        f"Passo efetivo: {format_m(layout.spacing_m)}"
    )


def spray_headland_schematic_layout(
    *,
    boom_width_m: float,
    outside_overlap_m: float,
    width_px: float,
    height_px: float,
    margin_px: float = 16.0,
    min_outside_px: float = 3.0,
) -> dict[str, float | bool]:
    """Corte transversal: limite vertical, barra fisica centrada na linha central.

    Metros -> pixels em escala unica; a parte fora do limite ganha largura
    minima visivel quando > 0 (o rotulo mostra o valor real).
    """
    if boom_width_m <= 0:
        return {"valid": False}
    pad = max(1.0, boom_width_m * 0.08)
    left_m = -outside_overlap_m - pad
    span_m = boom_width_m + 2.0 * pad
    scale = max(width_px - 2.0 * margin_px, 1.0) / span_m

    def x(meters: float) -> float:
        return margin_px + (meters - left_m) * scale

    center_m = boom_width_m / 2.0 - outside_overlap_m
    boundary_x = x(0.0)
    boom_left_x = x(-outside_overlap_m)
    if outside_overlap_m > 0 and boundary_x - boom_left_x < min_outside_px:
        boom_left_x = boundary_x - min_outside_px
    return {
        "valid": True,
        "scale_px_per_m": scale,
        "boundary_x": boundary_x,
        "center_x": x(center_m),
        "boom_left_x": boom_left_x,
        "boom_right_x": x(boom_width_m - outside_overlap_m),
        "bar_y": height_px * 0.55,
        "has_outside": outside_overlap_m > 0,
    }
