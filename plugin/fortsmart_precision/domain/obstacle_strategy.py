# -*- coding: utf-8 -*-
"""Estrategias de tratamento de obstaculos para linhas ja geradas.

STOP_CUT_RESUME e o comportamento existente (corta e retoma) e continua sendo
o padrao. LATERAL_DETOUR contorna o obstaculo pela trajetoria mestra e so e
usado quando escolhido explicitamente.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from enum import Enum


# Desliga o desvio lateral em todo o plugin sem tocar no corte existente.
ENABLE_LATERAL_DETOUR = True

GEOMETRY_EPSILON = 0.001
DETOUR_NOT_FEASIBLE = "DETOUR_NOT_FEASIBLE"


class ObstacleHandlingStrategy(str, Enum):
    STOP_CUT_RESUME = "stop_cut_resume"
    LATERAL_DETOUR = "lateral_detour"


class DetourSide(str, Enum):
    AUTO = "auto"
    LEFT = "left"
    RIGHT = "right"


class ContourStrategy(str, Enum):
    # Envoltoria convexa com raio >= raio minimo efetivo: sem U/V em concavidades.
    CONVEX_SMOOTH = "convex_smooth"
    # Envoltoria convexa na folga exata; rejeitada se a curva ficar abaixo do raio.
    CONVEX_TIGHT = "convex_tight"


DEFAULT_STRATEGY = ObstacleHandlingStrategy.STOP_CUT_RESUME


class ObstacleConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ObstacleConfig:
    strategy: ObstacleHandlingStrategy = DEFAULT_STRATEGY
    row_count: int = 0
    row_spacing: float = 0.0
    safety_margin: float = 0.50
    obstacle_radius: float = 0.0
    approach_distance: float = 12.0
    return_distance: float = 12.0
    minimum_turn_radius: float = 8.0
    detour_side: DetourSide = DetourSide.AUTO
    contour_strategy: ContourStrategy = ContourStrategy.CONVEX_SMOOTH
    planting_during_detour: bool = True
    allow_fallback: bool = True
    generate_rows: bool = True
    spacing_tolerance: float = 0.03

    @property
    def machine_width(self) -> float:
        return calculate_machine_width(self.row_count, self.row_spacing)

    @property
    def half_machine(self) -> float:
        return self.machine_width / 2.0

    @property
    def clearance(self) -> float:
        """Afastamento do centro da maquina ate a borda do obstaculo."""
        return self.half_machine + self.safety_margin

    def validate(self) -> "ObstacleConfig":
        if self.strategy == ObstacleHandlingStrategy.STOP_CUT_RESUME:
            return self
        if int(self.row_count) < 1:
            raise ObstacleConfigError("Informe o numero de linhas da plantadeira (>= 1).")
        if self.row_spacing <= 0:
            raise ObstacleConfigError("O espacamento entre linhas deve ser maior que zero.")
        for name in ("safety_margin", "obstacle_radius", "approach_distance", "return_distance"):
            if getattr(self, name) < 0:
                raise ObstacleConfigError(f"{name} nao pode ser negativo.")
        if self.minimum_turn_radius <= 0:
            raise ObstacleConfigError("O raio minimo de curva deve ser maior que zero.")
        if self.spacing_tolerance <= 0:
            raise ObstacleConfigError("A tolerancia de espacamento deve ser maior que zero.")
        return self

    def to_dict(self) -> dict:
        data = asdict(self)
        for key, value in data.items():
            if isinstance(value, Enum):
                data[key] = value.value
        return data


def calculate_machine_width(row_count: int, row_spacing: float) -> float:
    return float(int(row_count)) * float(row_spacing)


def resolve_strategy(value) -> ObstacleHandlingStrategy:
    """Valor ausente ou vazio continua no corte existente (projetos antigos)."""
    if value in (None, ""):
        return DEFAULT_STRATEGY
    if isinstance(value, ObstacleHandlingStrategy):
        strategy = value
    else:
        try:
            strategy = ObstacleHandlingStrategy(str(value).strip().lower())
        except ValueError as exc:
            raise ObstacleConfigError(f"Estrategia de obstaculo desconhecida: {value}") from exc
    if strategy == ObstacleHandlingStrategy.LATERAL_DETOUR and not ENABLE_LATERAL_DETOUR:
        return DEFAULT_STRATEGY
    return strategy


def obstacle_config_from_dict(data: dict | None) -> ObstacleConfig:
    """Carrega configuracao salva; chaves ausentes usam os padroes."""
    data = dict(data or {})
    data["strategy"] = resolve_strategy(data.get("strategy", data.get("obstacle_strategy")))
    data.pop("obstacle_strategy", None)
    if "detour_side" in data:
        data["detour_side"] = DetourSide(str(data["detour_side"]).lower())
    if "contour_strategy" in data:
        data["contour_strategy"] = ContourStrategy(str(data["contour_strategy"]).lower())
    known = {item.name for item in fields(ObstacleConfig)}
    return ObstacleConfig(**{key: value for key, value in data.items() if key in known})
