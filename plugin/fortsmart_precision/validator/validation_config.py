# -*- coding: utf-8 -*-
"""Parametros do validador de rota (limiares de deteccao, nunca parametros de maquina)."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ValidationConfig:
    # Limite: trecho fora encostado na ponta da passada pode ser avanco de cabeceira.
    allow_headland_overrun: bool = True
    max_headland_overrun_m: float | None = None
    boundary_tolerance_m: float = 0.01
    # Obstaculos: buffer de seguranca alem da geometria do obstaculo.
    obstacle_safety_buffer_m: float = 0.0
    # Espacamento.
    spacing_tolerance_m: float = 0.10
    spacing_sample_every_m: float = 5.0
    # Geometria.
    duplicate_tolerance_m: float = 0.05
    duplicate_min_overlap_m: float = 2.0
    minimum_route_length_m: float = 5.0
    max_direction_change_deg: float = 60.0
    direction_change_window_m: float = 5.0
    # Sequencia: salto lateral maior que fator x espacamento de referencia.
    sequence_jump_factor: float = 2.5
    max_transition_distance_m: float | None = None
    allow_simulation_with_warnings: bool = True

    def as_dict(self) -> dict[str, object]:
        return asdict(self)
