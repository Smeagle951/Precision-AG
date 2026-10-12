# -*- coding: utf-8 -*-
"""Faixa de cobertura progressiva do simulador: rota percorrida + largura do equipamento.

So consome o `RouteSimulationEngine` (passadas concluidas, passada ativa e
distancia atual); nao altera o motor, a rota nem o validador. A faixa nunca
passa da posicao da maquina: e o buffer de ponta plana do trecho ja percorrido,
em CRS metrico.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import LineString, MultiLineString

from .coverage_state import CoverageState, PassCoverage
from .route_simulation_engine import RouteSimulationEngine
from .simulation_route import RoutePass

DEFAULT_UPDATE_STEP_M = 0.5
DEFAULT_QUAD_SEGS = 8


@dataclass(frozen=True)
class CoverageSettings:
    """`working_width_m` vem da tela (Maquina > Largura); nada e assumido."""

    working_width_m: float
    update_step_m: float = DEFAULT_UPDATE_STEP_M
    quad_segs: int = DEFAULT_QUAD_SEGS

    def validate(self) -> None:
        if not (isinstance(self.working_width_m, (int, float)) and math.isfinite(self.working_width_m)):
            raise ValueError("Largura de trabalho invalida.")
        if self.working_width_m <= 0:
            raise ValueError("Largura de trabalho deve ser maior que zero.")
        if self.update_step_m <= 0:
            raise ValueError("Passo de atualizacao da cobertura deve ser maior que zero.")

    @property
    def half_width_m(self) -> float:
        return self.working_width_m / 2.0


def get_travelled_segment(route_pass: RoutePass, start_m: float, current_m: float):
    """Trecho da passada entre duas distancias (sentido de percurso), ou None."""
    parts = [LineString(p) for p in route_pass.parts_between(start_m, current_m) if len(p) >= 2]
    parts = [p for p in parts if p.length > 1e-9]
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else MultiLineString(parts)


def swath_polygon(line, half_width_m: float, quad_segs: int = DEFAULT_QUAD_SEGS):
    """Faixa de meia largura para cada lado; ponta plana (a barra termina na maquina)."""
    return line.buffer(half_width_m, quad_segs=quad_segs, cap_style="flat", join_style="round")


class CoverageEngine:
    def __init__(self, settings: CoverageSettings):
        settings.validate()
        self.settings = settings
        self.state = CoverageState()
        self._last_progress_m = 0.0

    def reset(self) -> None:
        self.state.reset()
        self._last_progress_m = 0.0

    def _pass_coverage(self, route_pass: RoutePass, index: int, distance_m: float, completed: bool) -> PassCoverage:
        line = get_travelled_segment(route_pass, 0.0, distance_m)
        geometry = (
            swath_polygon(line, self.settings.half_width_m, self.settings.quad_segs)
            if line is not None
            else LineString().buffer(0)
        )
        return PassCoverage(route_pass.id, index, geometry, distance_m, completed)

    def update(self, engine: RouteSimulationEngine) -> bool:
        """Sincroniza com o motor; devolve True se alguma faixa mudou.

        Rodando, a faixa ativa so e refeita a cada `update_step_m`; pausada,
        parada ou concluida, alcanca exatamente a posicao da maquina.
        Progresso menor que o anterior (Reiniciar/Iniciar de novo) limpa tudo.
        """
        state = engine.state
        changed = False
        if state.completed_distance_m < self._last_progress_m - 1e-9:
            self.reset()
            changed = True
        self._last_progress_m = state.completed_distance_m
        completed = engine.completed_passes()
        for index in range(len(self.state.completed), len(completed)):
            route_pass = completed[index]
            self.state.complete(self._pass_coverage(route_pass, index, route_pass.length_m, True))
            changed = True
        if state.is_finished:
            if self.state.current is not None:
                self.state.set_current(None)
                changed = True
            return changed
        distance = state.current_distance_m
        current = self.state.current
        if current is not None and current.pass_index != state.current_pass_index:
            current = None
        built = current.distance_m if current is not None else 0.0
        settled = not state.is_running or state.is_paused
        moved = distance - built
        if distance <= 0.0:
            if self.state.current is not None:
                self.state.set_current(None)
                changed = True
            return changed
        if current is None or moved >= self.settings.update_step_m or (settled and abs(moved) > 1e-9):
            self.state.set_current(self._pass_coverage(engine.current_pass, state.current_pass_index, distance, False))
            changed = True
        return changed
