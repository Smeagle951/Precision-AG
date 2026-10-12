# -*- coding: utf-8 -*-
"""Simulador visual de cobertura a partir de linhas ja planejadas.

Nao gera trajetorias, nao altera fontes e nao certifica a operacao. A fonte da
verdade e somente a faixa fisica resultante do buffer de cada trecho WORK_ON.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from shapely.geometry import GeometryCollection, LineString
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union


class VisualCoverageError(ValueError):
    """Entrada invalida para uma simulacao visual de cobertura."""


@dataclass(frozen=True)
class VisualCoverageMetrics:
    work_width_m: float
    pass_count: int
    covered_area_ha: float
    overlap_area_ha: float
    gap_area_ha: float | None


@dataclass(frozen=True)
class VisualCoverageResult:
    """Geometrias derivadas para as tres camadas SIM padrao."""

    normal_coverage: BaseGeometry
    overlap: BaseGeometry
    gap: BaseGeometry | None
    metrics: VisualCoverageMetrics


def _empty() -> BaseGeometry:
    return GeometryCollection()


def simulate_visual_coverage(
    work_lines: Iterable[Sequence[tuple[float, float]]],
    *,
    work_width_m: float,
    analysis_area: BaseGeometry | None = None,
) -> VisualCoverageResult:
    """Cria cobertura, remonte e falha sem modificar as linhas de entrada.

    `work_lines` deve conter somente segmentos WORK_ON. Quando `analysis_area`
    nao e informado, a ferramenta ainda mostra cobertura e remonte, mas nao
    inventa uma area onde deveria existir falha.
    """
    if work_width_m <= 0:
        raise VisualCoverageError("Largura do implemento deve ser maior que zero.")
    if analysis_area is not None and (analysis_area.is_empty or not analysis_area.is_valid):
        raise VisualCoverageError("Area de analise invalida.")

    strips: list[BaseGeometry] = []
    for coordinates in work_lines:
        if len(coordinates) < 2:
            continue
        line = LineString(coordinates)
        if line.is_empty or not line.is_valid or line.length <= 0:
            continue
        strips.append(line.buffer(work_width_m / 2.0, cap_style=2, join_style=2))
    if not strips:
        raise VisualCoverageError("Nenhum trecho WORK_ON valido foi informado.")

    all_coverage = unary_union(strips)
    overlaps: list[BaseGeometry] = []
    for index, strip in enumerate(strips):
        for other in strips[index + 1:]:
            shared = strip.intersection(other)
            if not shared.is_empty:
                overlaps.append(shared)
    overlap = unary_union(overlaps) if overlaps else _empty()

    # Boundary, se existir, apenas recorta a leitura visual do talhao.
    visible_coverage = all_coverage if analysis_area is None else all_coverage.intersection(analysis_area)
    visible_overlap = overlap if analysis_area is None else overlap.intersection(analysis_area)
    normal = visible_coverage.difference(visible_overlap)
    gap = None if analysis_area is None else analysis_area.difference(visible_coverage)
    metrics = VisualCoverageMetrics(
        work_width_m=work_width_m,
        pass_count=len(strips),
        covered_area_ha=visible_coverage.area / 10_000.0,
        overlap_area_ha=visible_overlap.area / 10_000.0,
        gap_area_ha=None if gap is None else gap.area / 10_000.0,
    )
    return VisualCoverageResult(normal, visible_overlap, gap, metrics)
