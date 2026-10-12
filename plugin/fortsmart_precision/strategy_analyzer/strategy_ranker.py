# -*- coding: utf-8 -*-
"""Ordenacao por criterio e linhas comparativas factuais (sem veredito unico)."""

from __future__ import annotations

from collections.abc import Callable

from .models import (
    CRITERION_LINE_COUNT,
    CRITERION_TOTAL_LENGTH,
    CRITERION_TURN_COUNT,
    StrategyCandidate,
    StrategyType,
)

CRITERION_LABELS = {
    CRITERION_LINE_COUNT: "Menor número de passadas",
    CRITERION_TOTAL_LENGTH: "Menor comprimento total",
    CRITERION_TURN_COUNT: "Menos manobras",
}


def _angle_key(candidate: StrategyCandidate) -> float:
    return candidate.angle_deg if candidate.angle_deg is not None else -1.0


def rank_key(criterion: str) -> Callable[[StrategyCandidate], tuple]:
    """Desempate deterministico: criterio, depois as outras metricas, depois o angulo."""
    def key(candidate: StrategyCandidate) -> tuple:
        lines = candidate.line_count
        length = round(candidate.total_length_m, 3)
        turns = candidate.turn_count
        short = candidate.short_segment_count
        if criterion == CRITERION_TOTAL_LENGTH:
            primary = (length, lines, short)
        elif criterion == CRITERION_TURN_COUNT:
            primary = (turns, length, short)
        else:
            primary = (lines, length, short)
        return primary + (_angle_key(candidate),)

    return key


def rank_candidates(candidates: list[StrategyCandidate], criterion: str) -> list[StrategyCandidate]:
    return sorted((item for item in candidates if item.valid), key=rank_key(criterion))


def best_by(candidates: list[StrategyCandidate], criterion: str) -> StrategyCandidate | None:
    ranked = rank_candidates(candidates, criterion)
    return ranked[0] if ranked else None


def angle_distance(a: float, b: float) -> float:
    """Distancia entre direcoes de reta (periodo 180)."""
    delta = abs(a - b) % 180.0
    return min(delta, 180.0 - delta)


def select_preview_candidates(
    candidates: list[StrategyCandidate],
    criterion: str,
    limit: int,
    *,
    min_angle_separation: float = 0.0,
) -> list[StrategyCandidate]:
    """Melhor reta, curva (se valida) e, havendo espaco, a segunda melhor reta.

    A segunda reta precisa diferir da melhor em pelo menos min_angle_separation
    graus; vizinhas do refino (ex.: 90 e 89,5) nao acrescentam comparacao.
    """
    straights = rank_candidates(
        [item for item in candidates if item.strategy_type is StrategyType.STRAIGHT], criterion
    )
    curves = [
        item for item in candidates if item.strategy_type is StrategyType.CURVE and item.valid
    ]
    selected: list[StrategyCandidate] = []
    if straights:
        selected.append(straights[0])
    selected.extend(curves[:1])
    if straights:
        best_angle = straights[0].angle_deg
        second = next(
            (
                item for item in straights[1:]
                if angle_distance(item.angle_deg, best_angle) >= min_angle_separation
            ),
            None,
        )
        if second is not None:
            selected.append(second)
    return selected[: max(1, limit)]


def format_km(length_m: float) -> str:
    return f"{length_m / 1000.0:.1f}".replace(".", ",") + " km"


def summary_rows(candidates: list[StrategyCandidate]) -> list[str]:
    """Vencedor de cada metrica e a diferenca para o segundo: 'Menos passadas: CURVA  -4'."""
    finalists = [item for item in candidates if item.valid]
    if len(finalists) < 2:
        return []
    metrics = (
        ("Menos passadas", lambda item: item.line_count, lambda diff: f"-{diff:d}"),
        ("Menor percurso", lambda item: round(item.total_length_m, 1), lambda diff: f"-{format_km(diff)}"),
        ("Menos manobras", lambda item: item.turn_count, lambda diff: f"-{diff:d}"),
    )
    rows = []
    for title, value, fmt in metrics:
        ordered = sorted(finalists, key=value)
        best, runner = ordered[0], ordered[1]
        if value(best) == value(runner):
            rows.append(f"{title}: empate")
        else:
            rows.append(f"{title}: {best.label}  {fmt(value(runner) - value(best))}")
    return rows


def comparison_rows(candidates: list[StrategyCandidate]) -> list[str]:
    """Ex.: 'Menor número de passadas: CURVA (74)'. Empates listam todos os empatados."""
    finalists = [item for item in candidates if item.valid]
    if not finalists:
        return []
    rows = []
    metrics = (
        (CRITERION_LINE_COUNT, lambda item: item.line_count, "{:d}"),
        (CRITERION_TOTAL_LENGTH, lambda item: round(item.total_length_m, 1), "{:.1f} m"),
        (CRITERION_TURN_COUNT, lambda item: item.turn_count, "{:d}"),
    )
    for criterion, value, fmt in metrics:
        best_value = min(value(item) for item in finalists)
        winners = [item.label for item in finalists if value(item) == best_value]
        rows.append(f"{CRITERION_LABELS[criterion]}: {' = '.join(winners)} ({fmt.format(best_value)})")
    overlap = [item for item in finalists if item.overlap_ha is not None]
    if len(overlap) == len(finalists):
        best_value = min(item.overlap_ha for item in overlap)
        winners = [item.label for item in overlap if item.overlap_ha == best_value]
        rows.append(f"Menor sobreposição: {' = '.join(winners)} ({best_value:.4f} ha)")
    gaps = [item for item in finalists if item.gap_ha is not None]
    if len(gaps) == len(finalists):
        best_value = min(item.gap_ha for item in gaps)
        winners = [item.label for item in gaps if item.gap_ha == best_value]
        rows.append(f"Menor falha: {' = '.join(winners)} ({best_value:.4f} ha)")
    return rows
