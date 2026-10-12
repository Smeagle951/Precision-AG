# -*- coding: utf-8 -*-
"""Contorno do marcador da maquina (retangulo com bico na frente), sem cobertura."""

from __future__ import annotations

import math

from .simulation_route import Point

# Tamanho so de desenho quando o perfil nao informa largura/comprimento.
VISUAL_DEFAULT_WIDTH_M = 3.0
VISUAL_DEFAULT_LENGTH_M = 6.0


def machine_marker_outline(
    position: Point,
    heading_deg: float,
    width_m: float | None = None,
    length_m: float | None = None,
) -> list[Point]:
    """Anel fechado centrado na posicao, apontando para `heading_deg` (0 = norte)."""
    width = width_m if width_m and width_m > 0 else VISUAL_DEFAULT_WIDTH_M
    length = length_m if length_m and length_m > 0 else VISUAL_DEFAULT_LENGTH_M
    half_w, half_l = width / 2.0, length / 2.0
    nose = min(half_l, half_w)
    # Local: +y = frente, +x = direita.
    local = [
        (-half_w, -half_l),
        (half_w, -half_l),
        (half_w, half_l - nose),
        (0.0, half_l),
        (-half_w, half_l - nose),
        (-half_w, -half_l),
    ]
    angle = math.radians(heading_deg)
    sin_a, cos_a = math.sin(angle), math.cos(angle)
    x0, y0 = position
    # Rumo horario a partir do norte: frente (0, 1) -> (sin, cos).
    return [(x0 + x * cos_a + y * sin_a, y0 - x * sin_a + y * cos_a) for x, y in local]
