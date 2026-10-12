# -*- coding: utf-8 -*-
"""Configuracao de finalizacao de passadas e tipos de volta."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TurnConfigurationError(ValueError):
    """Erro em configuracao de voltas."""


class TurnFinishMode(str, Enum):
    NONE = "none"
    INSIDE_HEADLAND = "inside_headland"
    OUTSIDE_BOUNDARY = "outside_boundary"
    MANEUVER_AREA = "maneuver_area"
    CUSTOM = "custom"


class TurnType(str, Enum):
    U = "u"
    DROP = "drop"
    OMEGA = "omega"
    THREE_POINT = "three_point"
    SKIP_PASS = "skip_pass"


class PassSequenceMode(str, Enum):
    SEQUENTIAL = "sequential"
    ALTERNATING = "alternating"
    SKIP_ONE = "skip_one"
    SKIP_TWO = "skip_two"
    BLOCKS = "blocks"
    CUSTOM = "custom"


class TurnStatus(str, Enum):
    VALID = "valid"
    VALID_LOW_MARGIN = "valid_low_margin"
    IMPOSSIBLE = "impossible"
    INSUFFICIENT_DATA = "insufficient_data"


# Suporte real ate a Etapa 4.
SUPPORTED_FINISH_MODES = {
    TurnFinishMode.NONE,
    TurnFinishMode.INSIDE_HEADLAND,
    TurnFinishMode.OUTSIDE_BOUNDARY,
    TurnFinishMode.MANEUVER_AREA,
}
SUPPORTED_TURN_TYPES = {
    TurnType.U,
    TurnType.DROP,
    TurnType.SKIP_PASS,
    TurnType.OMEGA,
    TurnType.THREE_POINT,
}
SUPPORTED_SEQUENCE_MODES = {
    PassSequenceMode.SEQUENTIAL,
    PassSequenceMode.ALTERNATING,
    PassSequenceMode.SKIP_ONE,
    PassSequenceMode.SKIP_TWO,
    PassSequenceMode.BLOCKS,
    PassSequenceMode.CUSTOM,
}

# Alias legado (Etapa 1).
ETAPA1_FINISH_MODES = {TurnFinishMode.NONE, TurnFinishMode.INSIDE_HEADLAND}
ETAPA1_TURN_TYPES = {TurnType.U}
ETAPA1_SEQUENCE_MODES = {PassSequenceMode.SEQUENTIAL}

DEFAULT_EXTERNAL_EXTENSION_M = 20.0


class AllowedTurnSide(str, Enum):
    BOTH = "both"
    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True)
class SafetyMargins:
    outer_boundary_m: float = 0.0
    obstacle_m: float = 3.0
    channel_m: float = 2.0
    fence_m: float = 2.0
    power_line_m: float = 5.0
    planted_area_m: float = 0.5
    recommended_clearance_m: float = 2.0

    def validate(self) -> None:
        for name, value in (
            ("outer_boundary_m", self.outer_boundary_m),
            ("obstacle_m", self.obstacle_m),
            ("channel_m", self.channel_m),
            ("fence_m", self.fence_m),
            ("power_line_m", self.power_line_m),
            ("planted_area_m", self.planted_area_m),
            ("recommended_clearance_m", self.recommended_clearance_m),
        ):
            if value < 0:
                raise TurnConfigurationError(f"Margem {name} nao pode ser negativa.")


@dataclass(frozen=True)
class TurnConfiguration:
    finish_mode: TurnFinishMode = TurnFinishMode.NONE
    turn_type: TurnType = TurnType.U
    sequence_mode: PassSequenceMode = PassSequenceMode.SEQUENTIAL
    generate_turns: bool = False
    min_turn_radius_m: float | None = None
    tractor_length_m: float | None = None
    implement_length_m: float | None = None
    wheelbase_m: float | None = None
    implement_mounted: bool | None = None
    skip_passes: int = 0
    block_size: int = 4
    external_extension_m: float = DEFAULT_EXTERNAL_EXTENSION_M
    extension_before_m: float | None = None
    extension_after_m: float | None = None
    max_outside_distance_m: float | None = None
    allowed_side: AllowedTurnSide = AllowedTurnSide.BOTH
    surface_type: str = ""
    external_area_id: str = ""
    allow_outside_boundary: bool = False
    allow_inside_headland: bool = True
    use_maneuver_area: bool = False
    avoid_planted_area: bool = True
    avoid_obstacles: bool = True
    safety: SafetyMargins = field(default_factory=SafetyMargins)
    custom_sequence: tuple[int, ...] = ()

    def validate(self) -> None:
        self.safety.validate()
        if self.skip_passes < 0:
            raise TurnConfigurationError("Numero de faixas puladas nao pode ser negativo.")
        if self.block_size < 1:
            raise TurnConfigurationError("Tamanho de bloco deve ser pelo menos 1.")
        if self.external_extension_m < 0:
            raise TurnConfigurationError("Extensao externa nao pode ser negativa.")
        if self.extension_before_m is not None and self.extension_before_m < 0:
            raise TurnConfigurationError("Extensao antes do limite nao pode ser negativa.")
        if self.extension_after_m is not None and self.extension_after_m < 0:
            raise TurnConfigurationError("Extensao depois do limite nao pode ser negativa.")
        if self.max_outside_distance_m is not None and self.max_outside_distance_m < 0:
            raise TurnConfigurationError("Distancia maxima fora do limite nao pode ser negativa.")
        if self.min_turn_radius_m is not None and self.min_turn_radius_m <= 0:
            raise TurnConfigurationError("Raio de giro deve ser maior que zero quando informado.")
        for name, value in (
            ("tractor_length_m", self.tractor_length_m),
            ("implement_length_m", self.implement_length_m),
            ("wheelbase_m", self.wheelbase_m),
        ):
            if value is not None and value < 0:
                raise TurnConfigurationError(f"{name} nao pode ser negativo.")

        if not self.generate_turns or self.finish_mode == TurnFinishMode.NONE:
            return

        if self.finish_mode not in SUPPORTED_FINISH_MODES:
            raise TurnConfigurationError(
                f"Modo de finalizacao '{self.finish_mode.value}' nao disponivel nesta etapa."
            )
        if self.finish_mode == TurnFinishMode.INSIDE_HEADLAND and not self.allow_inside_headland:
            raise TurnConfigurationError("Volta dentro da bordadura nao foi autorizada.")
        if self.finish_mode in {TurnFinishMode.OUTSIDE_BOUNDARY, TurnFinishMode.MANEUVER_AREA}:
            if not self.allow_outside_boundary and self.finish_mode == TurnFinishMode.OUTSIDE_BOUNDARY:
                raise TurnConfigurationError("Saida do limite exige autorizacao explicita.")
            if self.finish_mode == TurnFinishMode.MANEUVER_AREA and not self.use_maneuver_area:
                raise TurnConfigurationError("Area de manobra especifica nao foi habilitada.")
        if self.turn_type not in SUPPORTED_TURN_TYPES:
            raise TurnConfigurationError(
                f"Tipo de volta '{self.turn_type.value}' nao disponivel nesta etapa."
            )
        effective_sequence = self.effective_sequence_mode()
        if effective_sequence not in SUPPORTED_SEQUENCE_MODES:
            raise TurnConfigurationError(
                f"Sequencia '{effective_sequence.value}' nao disponivel nesta etapa."
            )
        if self.turn_type == TurnType.SKIP_PASS and self.resolved_skip_passes() < 1:
            raise TurnConfigurationError("Volta pula-faixa exige pular ao menos uma faixa.")
        if effective_sequence == PassSequenceMode.CUSTOM and not self.custom_sequence:
            raise TurnConfigurationError("Sequencia personalizada exige custom_sequence.")

    def resolved_extension_before_m(self) -> float:
        if self.extension_before_m is not None:
            return self.extension_before_m
        return self.external_extension_m

    def resolved_extension_after_m(self) -> float:
        if self.extension_after_m is not None:
            return self.extension_after_m
        return self.external_extension_m

    def effective_sequence_mode(self) -> PassSequenceMode:
        """SKIP_PASS implica sequencia com salto se ainda estiver sequencial."""
        if self.turn_type == TurnType.SKIP_PASS and self.sequence_mode == PassSequenceMode.SEQUENTIAL:
            skip = self.resolved_skip_passes()
            if skip >= 2:
                return PassSequenceMode.SKIP_TWO
            return PassSequenceMode.SKIP_ONE
        return self.sequence_mode

    def resolved_skip_passes(self) -> int:
        if self.turn_type == TurnType.SKIP_PASS and self.skip_passes < 1:
            return 1
        if self.sequence_mode == PassSequenceMode.SKIP_ONE and self.skip_passes < 1:
            return 1
        if self.sequence_mode == PassSequenceMode.SKIP_TWO and self.skip_passes < 2:
            return 2
        return self.skip_passes

    def has_complete_machine_params(self) -> bool:
        return self.min_turn_radius_m is not None and self.min_turn_radius_m > 0

    def requires_headland(self) -> bool:
        return self.generate_turns and self.finish_mode == TurnFinishMode.INSIDE_HEADLAND

    def requires_external_area(self) -> bool:
        return self.generate_turns and self.finish_mode in {
            TurnFinishMode.OUTSIDE_BOUNDARY,
            TurnFinishMode.MANEUVER_AREA,
        }

    def is_special_maneuver(self) -> bool:
        return self.turn_type == TurnType.THREE_POINT

    def is_towed_implement(self) -> bool:
        return self.implement_mounted is False

    def minimum_extension_m(self) -> float | None:
        """Extensao minima estimada alem do limite; None se faltarem dados de maquina."""
        if not self.has_complete_machine_params():
            return None
        assert self.min_turn_radius_m is not None
        tractor = self.tractor_length_m or 0.0
        implement = self.implement_length_m or 0.0
        ensemble = tractor + implement
        base = (
            self.min_turn_radius_m
            + max(ensemble * 0.5, self.min_turn_radius_m * 0.5)
            + self.safety.outer_boundary_m
        )
        if self.is_towed_implement():
            # Rebocado precisa de mais espaco longitudinal para nao cortar caminho.
            base += max(implement * 0.35, self.min_turn_radius_m * 0.25)
        if self.turn_type == TurnType.OMEGA:
            base += self.min_turn_radius_m * 0.5
        return base

    def extension_status(self) -> dict[str, object]:
        """Compara extensao configurada com a minima estimada."""
        configured = max(self.resolved_extension_before_m(), self.resolved_extension_after_m())
        minimum = self.minimum_extension_m()
        if minimum is None:
            return {
                "configured_m": configured,
                "minimum_m": None,
                "status": "insufficient_data",
                "is_estimated": True,
            }
        if configured + 1e-9 < minimum:
            status = "insufficient"
        else:
            status = "ok"
        return {
            "configured_m": configured,
            "minimum_m": minimum,
            "status": status,
            "is_estimated": False,
        }

    def required_turn_width_m(self, pass_spacing_m: float) -> float | None:
        """Largura/profundidade minima estimada; None se faltarem dados."""
        if not self.has_complete_machine_params():
            return None
        assert self.min_turn_radius_m is not None
        diameter = 2.0 * self.min_turn_radius_m
        planted = self.safety.planted_area_m
        if self.turn_type == TurnType.DROP:
            required = diameter + planted
        elif self.turn_type == TurnType.OMEGA:
            # Curva mais ampla para reduzir angulo de articulacao.
            required = max(pass_spacing_m, diameter * 1.5) + planted
        elif self.turn_type == TurnType.THREE_POINT:
            # Manobra especial: cabe em espaco lateral menor, exige mais comprimento.
            required = max(pass_spacing_m * 0.75, diameter * 0.85) + planted
        else:
            required = max(pass_spacing_m, diameter) + planted
        if self.is_towed_implement():
            required += (self.implement_length_m or 0.0) * 0.2
        return required

    def report(self) -> dict[str, object]:
        return {
            "finish_mode": self.finish_mode.value,
            "turn_type": self.turn_type.value,
            "sequence_mode": self.sequence_mode.value,
            "effective_sequence_mode": self.effective_sequence_mode().value,
            "skip_passes": self.resolved_skip_passes(),
            "block_size": self.block_size,
            "generate_turns": self.generate_turns,
            "min_turn_radius_m": self.min_turn_radius_m,
            "has_complete_machine_params": self.has_complete_machine_params(),
            "implement_mounted": self.implement_mounted,
            "is_towed_implement": self.is_towed_implement(),
            "is_special_maneuver": self.is_special_maneuver(),
            "external_extension_m": self.external_extension_m,
            "extension_before_m": self.resolved_extension_before_m(),
            "extension_after_m": self.resolved_extension_after_m(),
            "extension_status": self.extension_status(),
            "max_outside_distance_m": self.max_outside_distance_m,
            "allowed_side": self.allowed_side.value,
            "surface_type": self.surface_type,
            "external_area_id": self.external_area_id,
            "allow_outside_boundary": self.allow_outside_boundary,
            "use_maneuver_area": self.use_maneuver_area,
        }
