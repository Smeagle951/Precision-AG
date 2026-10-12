# -*- coding: utf-8 -*-
"""Modelos do analisador: configuracao, candidatos, resultado e erros padronizados."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

Point = tuple[float, float]

STRATEGY_ANALYSIS_NO_BOUNDARY = "STRATEGY_ANALYSIS_NO_BOUNDARY"
STRATEGY_ANALYSIS_NO_OPERATION = "STRATEGY_ANALYSIS_NO_OPERATION"
STRATEGY_ANALYSIS_NO_VALID_STRAIGHT = "STRATEGY_ANALYSIS_NO_VALID_STRAIGHT"
CURVE_REFERENCE_REQUIRED = "CURVE_REFERENCE_REQUIRED"
CURVE_STRATEGY_INVALID = "CURVE_STRATEGY_INVALID"
STRATEGY_PREVIEW_FAILED = "STRATEGY_PREVIEW_FAILED"
STRATEGY_SAVE_FAILED = "STRATEGY_SAVE_FAILED"

ERROR_MESSAGES = {
    STRATEGY_ANALYSIS_NO_BOUNDARY: "Talhão sem limite/área de trabalho para analisar.",
    STRATEGY_ANALYSIS_NO_OPERATION: "Configure a plantadeira (operação de plantio) antes de analisar.",
    STRATEGY_ANALYSIS_NO_VALID_STRAIGHT: "Nenhum ângulo de reta gerou um candidato válido.",
    CURVE_REFERENCE_REQUIRED: "Selecione uma curva de referência para testar a estratégia curva.",
    CURVE_STRATEGY_INVALID: "A curva de referência gerou passadas inválidas.",
    STRATEGY_PREVIEW_FAILED: "Não foi possível criar o preview da estratégia.",
    STRATEGY_SAVE_FAILED: "Não foi possível salvar a estratégia escolhida.",
}

CRITERION_LINE_COUNT = "line_count"
CRITERION_TOTAL_LENGTH = "total_length"
CRITERION_TURN_COUNT = "turn_count"
CRITERIA = (CRITERION_LINE_COUNT, CRITERION_TOTAL_LENGTH, CRITERION_TURN_COUNT)

ANALYSIS_VERSION = 1


class StrategyAnalysisError(ValueError):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or ERROR_MESSAGES.get(code, code))
        self.code = code


class StrategyType(str, Enum):
    STRAIGHT = "STRAIGHT"
    CURVE = "CURVE"
    # Reservados; ainda sem implementacao.
    CONTOUR = "CONTOUR"
    TERRAIN = "TERRAIN"
    HYBRID = "HYBRID"


IMPLEMENTED_STRATEGIES = (StrategyType.STRAIGHT, StrategyType.CURVE)


@dataclass(frozen=True)
class StrategyTolerances:
    geometry_tolerance_m: float = 0.05
    angle_tolerance_deg: float = 0.01
    spacing_tolerance_m: float = 0.01
    minimum_segment_length_m: float = 20.0


@dataclass(frozen=True)
class StrategyAnalysisConfig:
    test_straight: bool = True
    test_curve: bool = True
    straight_angle_start: float = 0.0
    straight_angle_end: float = 180.0
    straight_angle_step: float = 5.0
    # Angulo unico (ex.: direcao da A-B); desliga a busca.
    straight_fixed_angle: float | None = None
    refine: bool = True
    refine_top_k: int = 2
    refine_span_deg: float = 3.0
    refine_step_deg: float = 1.0
    fine_step_deg: float = 0.5
    ranking_criterion: str = CRITERION_LINE_COUNT
    compare_line_count: bool = True
    compare_total_length: bool = True
    compare_turn_count: bool = True
    compare_overlap: bool = True
    compare_gap: bool = True
    max_preview_candidates: int = 3
    min_curve_radius_m: float | None = None
    tolerances: StrategyTolerances = field(default_factory=StrategyTolerances)

    def validate(self) -> None:
        if not self.test_straight and not self.test_curve:
            raise ValueError("Marque ao menos uma estratégia (reta ou curva).")
        if self.straight_angle_step <= 0:
            raise ValueError("Passo de ângulo deve ser maior que zero.")
        if self.straight_angle_end < self.straight_angle_start:
            raise ValueError("Ângulo final deve ser maior ou igual ao inicial.")
        if self.ranking_criterion not in CRITERIA:
            raise ValueError(f"Critério desconhecido: {self.ranking_criterion}")
        if self.max_preview_candidates < 1:
            raise ValueError("Mostre ao menos um preview.")

    @property
    def compute_coverage(self) -> bool:
        return self.compare_overlap or self.compare_gap


@dataclass(frozen=True)
class StrategyLine:
    points: tuple[Point, ...]
    pass_no: int
    length_m: float
    spacing_m: float
    width_m: float


@dataclass
class StrategyCandidate:
    candidate_id: str
    strategy_type: StrategyType
    lines: tuple[StrategyLine, ...]
    angle_deg: float | None = None
    reference_id: str = ""
    line_count: int = 0
    total_length_m: float = 0.0
    average_length_m: float = 0.0
    turn_count: int = 0
    short_segment_count: int = 0
    self_intersection_count: int = 0
    crossing_count: int = 0
    boundary_exit_length_m: float = 0.0
    minimum_curve_radius_m: float | None = None
    coverage_ha: float | None = None
    overlap_ha: float | None = None
    gap_ha: float | None = None
    valid: bool = True
    warnings: list[str] = field(default_factory=list)

    @property
    def geometry(self) -> tuple[StrategyLine, ...]:
        return self.lines

    @property
    def label(self) -> str:
        if self.strategy_type is StrategyType.STRAIGHT and self.angle_deg is not None:
            return f"RETA {self.angle_deg:g}°"
        return "CURVA" if self.strategy_type is StrategyType.CURVE else self.strategy_type.value

    def metrics(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "strategy_type": self.strategy_type.value,
            "angle_deg": self.angle_deg,
            "reference_id": self.reference_id,
            "line_count": self.line_count,
            "total_length_m": round(self.total_length_m, 3),
            "average_length_m": round(self.average_length_m, 3),
            "turn_count": self.turn_count,
            "short_segment_count": self.short_segment_count,
            "self_intersection_count": self.self_intersection_count,
            "crossing_count": self.crossing_count,
            "boundary_exit_length_m": round(self.boundary_exit_length_m, 3),
            "minimum_curve_radius_m": self.minimum_curve_radius_m,
            "coverage_ha": self.coverage_ha,
            "overlap_ha": self.overlap_ha,
            "gap_ha": self.gap_ha,
            "valid": self.valid,
            "warnings": list(self.warnings),
        }


@dataclass
class StrategyAnalysisResult:
    field_id: str
    candidates: list[StrategyCandidate] = field(default_factory=list)
    best_by_line_count: StrategyCandidate | None = None
    best_by_total_length: StrategyCandidate | None = None
    best_by_turn_count: StrategyCandidate | None = None
    preview_candidates: list[StrategyCandidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    issue_codes: list[str] = field(default_factory=list)
    straight_tested: int = 0
    straight_valid: int = 0
    elapsed_s: float = 0.0
    cancelled: bool = False

    def straight_candidates(self) -> list[StrategyCandidate]:
        return [item for item in self.candidates if item.strategy_type is StrategyType.STRAIGHT]

    def curve_candidate(self) -> StrategyCandidate | None:
        return next((item for item in self.candidates if item.strategy_type is StrategyType.CURVE), None)

    def candidate(self, candidate_id: str) -> StrategyCandidate | None:
        return next((item for item in self.candidates if item.candidate_id == candidate_id), None)

    def add_issue(self, code: str, message: str | None = None) -> None:
        if code not in self.issue_codes:
            self.issue_codes.append(code)
        self.warnings.append(f"{code}: {message or ERROR_MESSAGES.get(code, code)}")
