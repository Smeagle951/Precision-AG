# -*- coding: utf-8 -*-
"""Modelos do desvio manual de obstaculo (uma linha + um obstaculo).

Valores internos do enum sao estaveis (gravados na camada de desvios); os
textos exibidos ficam em DETOUR_TYPE_LABELS.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

Coord = tuple[float, float]


class DetourType(str, Enum):
    LATERAL_LEFT = "LATERAL_LEFT"
    LATERAL_RIGHT = "LATERAL_RIGHT"
    CIRCULAR_LEFT = "CIRCULAR_LEFT"
    CIRCULAR_RIGHT = "CIRCULAR_RIGHT"
    ARC_180 = "ARC_180"
    ARC_360 = "ARC_360"
    CUT_RESUME = "CUT_RESUME"
    CUSTOM = "CUSTOM"


V1_DETOUR_TYPES = (DetourType.LATERAL_LEFT, DetourType.LATERAL_RIGHT, DetourType.CUT_RESUME)

DETOUR_TYPE_LABELS = {
    DetourType.LATERAL_LEFT: "Desvio lateral — esquerda",
    DetourType.LATERAL_RIGHT: "Desvio lateral — direita",
    DetourType.CIRCULAR_LEFT: "Contorno circular — esquerda",
    DetourType.CIRCULAR_RIGHT: "Contorno circular — direita",
    DetourType.ARC_180: "Arco 180°",
    DetourType.ARC_360: "Contorno 360°",
    DetourType.CUT_RESUME: "Corte e retomada",
    DetourType.CUSTOM: "Desvio personalizado",
}


class LineDirection(str, Enum):
    A_TO_B = "A_TO_B"
    B_TO_A = "B_TO_A"


LINE_DIRECTION_LABELS = {
    LineDirection.A_TO_B: "A → B (sentido de digitalização)",
    LineDirection.B_TO_A: "B → A (sentido invertido)",
}


class DetourStatus(str, Enum):
    OK = "OK"
    NO_CONFLICT = "NO_CONFLICT"
    FAILED = "FAILED"


MSG_INVADES_ZONE = "⚠ A trajetória invade a zona de segurança."
MSG_INVALID_GEOMETRY = "⚠ O desvio gera uma geometria inválida."
MSG_NO_TRANSITION = "⚠ Não foi possível criar uma transição válida."
MSG_OVERLAP = "⚠ Desvio gera sobreposição."
MSG_EMPTY_GEOMETRY = "⚠ O desvio gerou geometria vazia."
MSG_ENDPOINT_INSIDE = "⚠ A linha começa ou termina dentro da zona do obstáculo."
MSG_DUPLICATE_SEGMENT = "⚠ O desvio contém segmento duplicado."
MSG_SPIKE = "⚠ O desvio contém ponta (bigode) na transição."
MSG_NO_CONFLICT = "O obstáculo não interfere na linha selecionada; nenhum desvio necessário."
MSG_FIELD_NOT_CHECKED = "Talhão não informado: o limite não foi verificado."


def other_obstacle_warning(obstacle_ids) -> str:
    return "⚠ O desvio passa pela zona de outro obstáculo: " + ", ".join(obstacle_ids) + "."


def outside_field_warning(length_m: float) -> str:
    return f"⚠ O desvio sai do talhão ({length_m:.2f} m de trajeto fora do limite)."


MSG_SWATH_OUTSIDE_FIELD = "⚠ A faixa da plantadeira sai do talhão durante o desvio."

MSG_SELECT_LINE = "Selecione uma linha de plantio."
MSG_SELECT_OBSTACLE = "Selecione um obstáculo."
MSG_SELECT_ONE_EACH = "Selecione somente uma linha e um obstáculo."


def selection_error(line_count: int, obstacle_count: int) -> str | None:
    """Exatamente uma linha e um obstaculo; nunca processa selecoes em massa."""
    if line_count > 1 or obstacle_count > 1:
        return MSG_SELECT_ONE_EACH
    if line_count < 1:
        return MSG_SELECT_LINE
    if obstacle_count < 1:
        return MSG_SELECT_OBSTACLE
    return None


@dataclass(frozen=True)
class DetourParameters:
    """Entradas do operador. Distancias em metros (CRS metrico)."""

    detour_type: DetourType
    obstacle_radius_m: float = 1.0
    safety_margin_m: float = 0.5
    longitudinal_anticipation_m: float = 3.0
    longitudinal_return_m: float = 3.0
    # Distancia trator -> implemento; implemento atras do trator.
    tractor_to_implement_m: float = 0.0
    implement_width_m: float = 0.0
    minimum_turn_radius_m: float = 0.0
    direction: LineDirection = LineDirection.A_TO_B

    @property
    def safety_radius_m(self) -> float:
        """Zona de seguranca = raio do obstaculo + margem; largura e espacamento nao entram."""
        return self.obstacle_radius_m + self.safety_margin_m

    @property
    def half_width_m(self) -> float:
        return self.implement_width_m / 2.0

    @property
    def centerline_clearance_m(self) -> float:
        """Afastamento minimo do centro da plantadeira ate a borda do obstaculo fisico."""
        return self.safety_margin_m + self.half_width_m

    @property
    def reference_to_operation_m(self) -> float:
        """Convencao do MachineWorkGeometry: negativo = operacao atras da referencia."""
        return -self.tractor_to_implement_m

    def errors(self) -> list[str]:
        result: list[str] = []
        if self.detour_type not in V1_DETOUR_TYPES:
            result.append(
                f"Tipo {DETOUR_TYPE_LABELS.get(self.detour_type, self.detour_type)} planejado para versão futura."
            )
        for value, label in (
            (self.obstacle_radius_m, "Raio do obstáculo"),
            (self.safety_margin_m, "Margem de segurança"),
            (self.longitudinal_anticipation_m, "Antecipação"),
            (self.longitudinal_return_m, "Retorno"),
            (self.tractor_to_implement_m, "Distância trator → implemento"),
            (self.minimum_turn_radius_m, "Raio mínimo de curva"),
        ):
            if not math.isfinite(value) or value < 0:
                result.append(f"{label} não pode ser negativo.")
        if not math.isfinite(self.implement_width_m) or self.implement_width_m <= 0:
            result.append("Informe a largura do implemento (m).")
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "detour_type": self.detour_type.value,
            "obstacle_radius_m": self.obstacle_radius_m,
            "safety_margin_m": self.safety_margin_m,
            "safety_radius_m": self.safety_radius_m,
            "longitudinal_anticipation_m": self.longitudinal_anticipation_m,
            "longitudinal_return_m": self.longitudinal_return_m,
            "tractor_to_implement_m": self.tractor_to_implement_m,
            "reference_to_operation_m": self.reference_to_operation_m,
            "implement_width_m": self.implement_width_m,
            "minimum_turn_radius_m": self.minimum_turn_radius_m,
            "direction": self.direction.value,
        }


@dataclass(frozen=True)
class ObstacleDetour:
    """Resultado de um desvio manual; nao altera nenhuma camada."""

    detour_id: str
    line_id: str
    obstacle_id: str
    parameters: DetourParameters
    status: DetourStatus
    original_geometry: Any
    result_geometry: Any
    safety_zone: Any
    clearance_zone: Any
    side: str = ""
    control_points: tuple[Coord, ...] = ()
    conflict_entry_station_m: float | None = None
    conflict_exit_station_m: float | None = None
    maneuver_start_station_m: float | None = None
    maneuver_end_station_m: float | None = None
    implement_start_xy: Coord | None = None
    implement_end_xy: Coord | None = None
    tractor_start_xy: Coord | None = None
    tractor_end_xy: Coord | None = None
    messages: tuple[str, ...] = field(default_factory=tuple)
    # Trecho novo do trajeto (so desvio lateral); base das verificacoes do entorno.
    changed_geometry: Any = None
    # Avisos de entorno: nao bloqueiam, exigem confirmacao explicita do operador.
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.status is DetourStatus.OK

    @property
    def result_parts(self) -> tuple[Any, ...]:
        geometry = self.result_geometry
        if geometry is None or geometry.is_empty:
            return ()
        return tuple(getattr(geometry, "geoms", [geometry]))

    def record_attributes(self, created_at: str) -> dict[str, Any]:
        params = self.parameters
        return {
            "detour_id": self.detour_id,
            "line_id": self.line_id,
            "obstacle_id": self.obstacle_id,
            "detour_type": params.detour_type.value,
            "side": self.side,
            "obstacle_radius_m": params.obstacle_radius_m,
            "safety_margin_m": params.safety_margin_m,
            "anticipation_m": params.longitudinal_anticipation_m,
            "return_m": params.longitudinal_return_m,
            "reference_to_operation_m": params.reference_to_operation_m,
            "created_at": created_at,
        }


@dataclass(frozen=True)
class NearbyObstacle:
    """Outro obstaculo da camada; raio None = usa o raio informado no painel."""

    obstacle_id: str
    geometry: Any
    radius_m: float | None = None
