# -*- coding: utf-8 -*-
"""Motor do simulador de rota: onde a maquina estaria agora seguindo estas passadas.

Nao conhece tela nem QGIS: recebe a rota ordenada, o perfil da maquina e a
velocidade, avanca por tempo (`advance(delta_time_s)`) e entrega um
`SimulationState`. O trecho executado e sempre um recorte por distancia da
passada ativa; nenhuma passada aparece concluida antes de ser percorrida.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from enum import Enum

from ..domain.machine_profile import MachineProfile
from .simulation_route import PASS_END_EPSILON_M, OrderedRoute, Point, RoutePass

LOGGER = logging.getLogger("fortsmart_precision.simulation")

SIMULATION_PREMATURE_COMPLETION = "SIMULATION_PREMATURE_COMPLETION"
SPEED_MULTIPLIERS = (1.0, 2.0, 5.0, 10.0)


class PassVisualState(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class SimulationError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class SimulationState:
    is_running: bool
    is_paused: bool
    is_finished: bool
    current_pass_index: int
    current_pass_id: str
    current_distance_m: float
    current_pass_length_m: float
    current_position: Point
    current_heading_deg: float
    speed_m_s: float
    speed_multiplier: float
    elapsed_time_s: float
    total_route_distance_m: float
    completed_distance_m: float
    remaining_distance_m: float
    progress_percent: float
    route_count: int
    completed_pass_count: int
    active_pass_count: int
    planned_pass_count: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class RouteSimulationEngine:
    def __init__(
        self,
        route: OrderedRoute,
        machine_profile: MachineProfile,
        speed_m_s: float,
        *,
        speed_multiplier: float = 1.0,
    ):
        if route.route_count == 0:
            raise ValueError("Rota vazia.")
        if speed_m_s <= 0:
            raise ValueError("Velocidade deve ser maior que zero.")
        machine_profile.validate()
        self.route = route
        self.machine_profile = machine_profile
        self.speed_m_s = float(speed_m_s)
        self.speed_multiplier = 1.0
        self.set_speed_multiplier(speed_multiplier)
        self._reset()

    # ------------------------------------------------------------ estado ----
    def _reset(self) -> None:
        self._started = False
        self._running = False
        self._paused = False
        self._finished = False
        self._index = 0
        self._distance = 0.0
        self._completed_length = 0.0
        self._elapsed = 0.0

    @property
    def current_pass(self) -> RoutePass:
        return self.route.passes[self._index]

    @property
    def completed_pass_count(self) -> int:
        return self.route.route_count if self._finished else self._index

    def pass_visual_state(self, index: int) -> PassVisualState:
        if not self._started:
            return PassVisualState.PLANNED
        if index < self.completed_pass_count:
            return PassVisualState.COMPLETED
        if index == self._index:
            return PassVisualState.ACTIVE
        return PassVisualState.PLANNED

    def completed_passes(self) -> tuple[RoutePass, ...]:
        return self.route.passes[: self.completed_pass_count]

    def executed_active_parts(self) -> list[tuple[Point, ...]]:
        """Trecho percorrido da passada ativa: de 0 ate a distancia atual."""
        if not self._started or self._finished:
            return []
        return self.current_pass.parts_between(0.0, self._distance)

    def remaining_active_parts(self) -> list[tuple[Point, ...]]:
        """Trecho ainda nao percorrido da passada ativa."""
        if not self._started or self._finished:
            return []
        return self.current_pass.parts_between(self._distance, self.current_pass.length_m)

    @property
    def state(self) -> SimulationState:
        current = self.current_pass
        total = self.route.total_length_m
        completed = self._completed_length + (0.0 if self._finished else self._distance)
        completed_count = self.completed_pass_count
        active = 1 if self._started and not self._finished else 0
        if self._started and not self._finished and completed_count == self.route.route_count:
            raise SimulationError(
                SIMULATION_PREMATURE_COMPLETION,
                "todas as passadas marcadas como concluidas antes do fim da simulacao.",
            )
        return SimulationState(
            is_running=self._running,
            is_paused=self._paused,
            is_finished=self._finished,
            current_pass_index=self._index,
            current_pass_id=current.id,
            current_distance_m=self._distance,
            current_pass_length_m=current.length_m,
            current_position=current.position_at(self._distance),
            current_heading_deg=current.heading_at(self._distance),
            speed_m_s=self.speed_m_s,
            speed_multiplier=self.speed_multiplier,
            elapsed_time_s=self._elapsed,
            total_route_distance_m=total,
            completed_distance_m=completed,
            remaining_distance_m=max(0.0, total - completed),
            progress_percent=100.0 if self._finished else (100.0 * completed / total if total > 0 else 0.0),
            route_count=self.route.route_count,
            completed_pass_count=completed_count,
            active_pass_count=active,
            planned_pass_count=self.route.route_count - completed_count - active,
        )

    # ---------------------------------------------------------- controles ----
    def set_speed_multiplier(self, multiplier: float) -> None:
        if multiplier <= 0:
            raise ValueError("Multiplicador deve ser maior que zero.")
        self.speed_multiplier = float(multiplier)

    def start(self) -> SimulationState:
        """Inicia do comeco (ou continua, se pausado)."""
        if self._running and self._paused:
            return self.resume()
        if self._running:
            return self.state
        self._reset()
        self._started = True
        self._running = True
        LOGGER.info(
            "SIMULATION START route_count=%d total_length_m=%.2f speed_m_s=%.3f mode=%s",
            self.route.route_count,
            self.route.total_length_m,
            self.speed_m_s,
            self.route.mode.value,
        )
        return self.state

    def pause(self) -> SimulationState:
        if self._running and not self._finished:
            self._paused = True
        return self.state

    def resume(self) -> SimulationState:
        if self._running and self._paused:
            self._paused = False
        return self.state

    def stop(self) -> SimulationState:
        """Encerra a execucao; o ponto atual fica visivel ate Iniciar/Reiniciar."""
        self._running = False
        self._paused = False
        return self.state

    def restart(self) -> SimulationState:
        self._running = False
        return self.start()

    # ---------------------------------------------------------- avanco ----
    def advance(self, delta_time_s: float) -> SimulationState:
        """Avanca `velocidade x delta x multiplicador` metros ao longo da rota."""
        if delta_time_s < 0:
            raise ValueError("delta_time_s nao pode ser negativo.")
        if not self._running or self._paused or self._finished:
            return self.state
        to_move = self.speed_m_s * delta_time_s * self.speed_multiplier
        while to_move > 0.0 and not self._finished:
            current = self.current_pass
            step = min(to_move, current.length_m - self._distance)
            self._distance += step
            to_move -= step
            self._elapsed += step / self.speed_m_s
            if self._distance >= current.length_m - PASS_END_EPSILON_M:
                self._complete_current_pass()
        if not LOGGER.isEnabledFor(logging.DEBUG):
            return self.state
        LOGGER.debug(
            "pass_id=%s pass_index=%d distance_m=%.2f pass_length_m=%.2f heading=%.1f progress=%.2f",
            self.current_pass.id,
            self._index,
            self._distance,
            self.current_pass.length_m,
            self.current_pass.heading_at(self._distance),
            self.state.progress_percent,
        )
        return self.state

    def _complete_current_pass(self) -> None:
        current = self.current_pass
        self._completed_length += current.length_m
        LOGGER.info("PASS COMPLETED pass_id=%s pass_index=%d", current.id, self._index)
        if self._index + 1 >= self.route.route_count:
            self._finished = True
            self._running = False
            self._paused = False
            self._distance = current.length_m
            LOGGER.info(
                "SIMULATION FINISHED route_count=%d total_length_m=%.2f elapsed_time_s=%.1f",
                self.route.route_count,
                self.route.total_length_m,
                self._elapsed,
            )
            return
        self._index += 1
        self._distance = 0.0
        LOGGER.info("NEXT PASS pass_id=%s pass_index=%d", self.current_pass.id, self._index)
