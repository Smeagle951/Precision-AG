# -*- coding: utf-8 -*-
"""Geometria da plantadeira: largura de trabalho x linhas da maquina.

A largura de trabalho informada pelo usuario e a fonte de verdade da
distancia entre passadas (P_n = n x largura). Quantidade de linhas e
espacamento so descrevem a maquina: posicao das linhas, encontro entre
passadas e avisos de incompatibilidade. Nunca alteram a largura informada.
Sem largura informada, a largura equivalente pelas linhas e usada.
"""

from __future__ import annotations

from dataclasses import dataclass

INVALID_PLANTER_ROW_GEOMETRY = "INVALID_PLANTER_ROW_GEOMETRY"
GEOMETRY_WIDTH_MISMATCH = "GEOMETRY_WIDTH_MISMATCH"
INTERPASS_ROW_GAP_OUT_OF_TOLERANCE = "INTERPASS_ROW_GAP_OUT_OF_TOLERANCE"

WIDTH_MISMATCH_TOLERANCE_M = 0.02
INTERPASS_GAP_TOLERANCE_M = 0.01


class PlanterGeometryError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def calculate_row_offsets(row_count: int, row_spacing_m: float) -> list[float]:
    """offset_i = (i - (N - 1) / 2) * S, i = 0..N-1 (positivo = direita do sentido)."""
    _require_rows(row_count, row_spacing_m)
    center = (row_count - 1) / 2.0
    return [(index - center) * row_spacing_m for index in range(row_count)]


def _require_rows(row_count: int, row_spacing_m: float) -> None:
    if row_count is None or int(row_count) <= 0:
        raise PlanterGeometryError(
            INVALID_PLANTER_ROW_GEOMETRY, "Numero de linhas deve ser maior que zero."
        )
    if row_spacing_m is None or float(row_spacing_m) <= 0:
        raise PlanterGeometryError(
            INVALID_PLANTER_ROW_GEOMETRY, "Espacamento entre linhas deve ser maior que zero."
        )


@dataclass(frozen=True)
class PlanterGeometryConfig:
    row_count: int
    row_spacing_m: float
    # Largura de trabalho informada pelo usuario (fonte de verdade das passadas).
    configured_width_m: float | None = None

    def validate(self) -> None:
        _require_rows(self.row_count, self.row_spacing_m)
        if self.configured_width_m is not None and self.configured_width_m <= 0:
            raise PlanterGeometryError(
                INVALID_PLANTER_ROW_GEOMETRY, "Largura de trabalho deve ser maior que zero."
            )

    @property
    def row_based_width_m(self) -> float:
        """Largura equivalente pelas linhas (analise; nao posiciona passadas)."""
        _require_rows(self.row_count, self.row_spacing_m)
        return self.row_count * self.row_spacing_m

    @property
    def working_width_m(self) -> float:
        return resolve_effective_working_width(self)

    @property
    def outer_half_margin_m(self) -> float:
        _require_rows(self.row_count, self.row_spacing_m)
        return self.row_spacing_m / 2.0

    @property
    def outer_row_offset_m(self) -> float:
        _require_rows(self.row_count, self.row_spacing_m)
        return (self.row_count - 1) * self.row_spacing_m / 2.0

    def row_offsets(self) -> list[float]:
        return calculate_row_offsets(self.row_count, self.row_spacing_m)


def resolve_effective_working_width(
    config: PlanterGeometryConfig | None,
    manual_width_m: float | None = None,
) -> float:
    """Largura que posiciona as passadas: 1) informada pelo usuario; 2) linhas x espacamento."""
    for value in (manual_width_m, config.configured_width_m if config is not None else None):
        if value is not None and value > 0:
            return float(value)
    if config is not None:
        return config.row_based_width_m
    raise PlanterGeometryError(
        INVALID_PLANTER_ROW_GEOMETRY,
        "Implemento sem largura de trabalho informada e sem linhas validas.",
    )


@dataclass(frozen=True)
class InterpassGapReport:
    center_distance_m: float
    row_spacing_m: float
    outer_row_offset_m: float
    right_outer_row_a_m: float
    left_outer_row_b_m: float
    expected_gap_m: float
    actual_gap_m: float
    error_m: float
    tolerance_m: float

    @property
    def ok(self) -> bool:
        return abs(self.error_m) <= self.tolerance_m

    @property
    def code(self) -> str:
        return "" if self.ok else INTERPASS_ROW_GAP_OUT_OF_TOLERANCE

    def message(self) -> str:
        return (
            f"{INTERPASS_ROW_GAP_OUT_OF_TOLERANCE}: encontro {self.actual_gap_m:.3f} m "
            f"(espacamento entre linhas {self.expected_gap_m:.3f} m, diferenca "
            f"{self.error_m:+.3f} m) com {self.center_distance_m:.3f} m entre eixos."
        )


def validate_interpass_row_gap(
    center_distance_m: float,
    row_count: int,
    row_spacing_m: float,
    *,
    tolerance_m: float = INTERPASS_GAP_TOLERANCE_M,
) -> InterpassGapReport:
    """Passada A no eixo 0, B no eixo `center_distance_m`: gap entre linhas extremas."""
    outer = PlanterGeometryConfig(row_count, row_spacing_m).outer_row_offset_m
    right_a = outer
    left_b = center_distance_m - outer
    gap = left_b - right_a
    return InterpassGapReport(
        center_distance_m=center_distance_m,
        row_spacing_m=row_spacing_m,
        outer_row_offset_m=outer,
        right_outer_row_a_m=right_a,
        left_outer_row_b_m=left_b,
        expected_gap_m=row_spacing_m,
        actual_gap_m=gap,
        error_m=gap - row_spacing_m,
        tolerance_m=tolerance_m,
    )


@dataclass(frozen=True)
class PlanterGeometryIssue:
    level: str
    code: str
    message: str


class PlanterGeometryValidator:
    """Cadastro: linhas validas e compatibilidade da largura informada com as linhas."""

    def __init__(self, mismatch_tolerance_m: float = WIDTH_MISMATCH_TOLERANCE_M):
        self.mismatch_tolerance_m = mismatch_tolerance_m

    def validate(self, config: PlanterGeometryConfig) -> list[PlanterGeometryIssue]:
        try:
            config.validate()
        except PlanterGeometryError as exc:
            return [PlanterGeometryIssue("error", exc.code, str(exc))]
        configured = config.configured_width_m
        if configured is None:
            return []
        row_width = config.row_based_width_m
        difference = configured - row_width
        if abs(difference) <= self.mismatch_tolerance_m:
            return []
        gap = validate_interpass_row_gap(configured, config.row_count, config.row_spacing_m)
        return [
            PlanterGeometryIssue(
                "warning",
                GEOMETRY_WIDTH_MISMATCH,
                f"Largura de trabalho configurada: {configured:.2f} m\n"
                f"Largura equivalente pelas linhas: {row_width:.2f} m\n"
                f"Diferenca: {abs(difference):.2f} m\n"
                f"Encontro entre passadas: {gap.actual_gap_m:.2f} m "
                f"(espacamento entre linhas {config.row_spacing_m:.2f} m)",
            )
        ]


def planter_debug_report(
    config: PlanterGeometryConfig,
    centers_m: tuple[float, float] | None = None,
) -> list[str]:
    """Relatorio IMPLEMENT / CALCULATED / PASS / INTERPASS / STATUS."""
    width = config.working_width_m
    first, second = centers_m if centers_m is not None else (0.0, width)
    gap = validate_interpass_row_gap(second - first, config.row_count, config.row_spacing_m)
    configured = f"{config.configured_width_m:.2f}" if config.configured_width_m else "-"
    return [
        "IMPLEMENT:",
        "Type=PLANTER",
        f"Rows={config.row_count}",
        f"RowSpacing={config.row_spacing_m:.2f}",
        f"ConfiguredWidth={configured}",
        "CALCULATED:",
        f"WorkingWidth={width:.2f}",
        f"RowBasedWidth={config.row_based_width_m:.2f}",
        f"OuterRowOffset={config.outer_row_offset_m:.2f}",
        f"EdgeMargin={config.outer_half_margin_m:.2f}",
        "PASS:",
        f"P1 center={first:.2f}",
        f"P2 center={second:.2f}",
        "INTERPASS:",
        f"RightRowP1={first + gap.right_outer_row_a_m:.2f}",
        f"LeftRowP2={first + gap.left_outer_row_b_m:.2f}",
        f"Gap={gap.actual_gap_m:.2f}",
        "STATUS:",
        "PASS" if gap.ok else f"WARNING {GEOMETRY_WIDTH_MISMATCH}",
    ]
