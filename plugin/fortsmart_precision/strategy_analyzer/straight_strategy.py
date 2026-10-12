# -*- coding: utf-8 -*-
"""Estrategia RETA: varre azimutes [0, 180) com o motor de passadas existente."""

from __future__ import annotations

from collections.abc import Callable

from ..core.line_geometry import point_from_azimuth
from ..core.parallel_pass_engine import ParallelPassError, ParallelPassParams, generate_parallel_passes
from .field_context import FieldContext
from .models import StrategyAnalysisConfig, StrategyCandidate, StrategyLine, StrategyType

ANGLE_DECIMALS = 3


def normalize_angle(angle_deg: float) -> float:
    """Reta e simetrica: 180 == 0. Resultado em [0, 180)."""
    value = round(float(angle_deg) % 180.0, ANGLE_DECIMALS)
    return 0.0 if value >= 180.0 else value


def coarse_angles(config: StrategyAnalysisConfig) -> list[float]:
    angles: list[float] = []
    step = config.straight_angle_step
    count = int((config.straight_angle_end - config.straight_angle_start) / step + 1e-9)
    for index in range(count + 1):
        angle = normalize_angle(config.straight_angle_start + index * step)
        if angle not in angles:
            angles.append(angle)
    return angles


def refine_angles(centers: list[float], span_deg: float, step_deg: float) -> list[float]:
    angles: list[float] = []
    if step_deg <= 0:
        return angles
    count = int(round(span_deg / step_deg))
    for center in centers:
        for index in range(-count, count + 1):
            angle = normalize_angle(center + index * step_deg)
            if angle not in angles:
                angles.append(angle)
    return angles


def candidate_id_for_angle(angle_deg: float) -> str:
    return f"STRAIGHT_{angle_deg:07.3f}".replace(".", "_")


def generate_straight_candidate(context: FieldContext, angle_deg: float) -> StrategyCandidate:
    """Mesmo motor do gerador: miolo define as passadas, recorte = limite + extensao (cacheado)."""
    angle = normalize_angle(angle_deg)
    origin = context.origin
    ab_end = point_from_azimuth(origin, angle, max(context.diagonal_m, 100.0))
    candidate = StrategyCandidate(
        candidate_id=candidate_id_for_angle(angle),
        strategy_type=StrategyType.STRAIGHT,
        lines=(),
        angle_deg=angle,
    )
    try:
        passes = generate_parallel_passes(
            ParallelPassParams(
                polygons=context.work_area,
                ab_start=origin,
                ab_end=ab_end,
                pass_spacing_m=context.pass_spacing_m,
                operation_width_m=context.operation_width_m,
                extension_m=0.0,
                operation_id=context.operation_id,
                clip_boundary=context.allowed_area,
            )
        )
    except ParallelPassError as exc:
        candidate.valid = False
        candidate.warnings.append(str(exc))
        return candidate
    candidate.lines = tuple(
        StrategyLine(
            points=tuple(item.line_points()),
            pass_no=item.pass_no,
            length_m=item.length_m,
            spacing_m=item.spacing_m,
            width_m=item.width_m,
        )
        for item in passes
    )
    return candidate


def search_straight(
    context: FieldContext,
    config: StrategyAnalysisConfig,
    evaluate: Callable[[StrategyCandidate], StrategyCandidate],
    rank_key: Callable[[StrategyCandidate], tuple],
    *,
    progress: Callable[[int, int], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> list[StrategyCandidate]:
    """Busca grossa no passo configurado e refino em torno dos melhores (1 grau, depois 0,5)."""
    tested: dict[float, StrategyCandidate] = {}

    def run(angles: list[float]) -> None:
        pending = [angle for angle in angles if angle not in tested]
        for index, angle in enumerate(pending, start=1):
            if is_cancelled is not None and is_cancelled():
                return
            tested[angle] = evaluate(generate_straight_candidate(context, angle))
            if progress is not None:
                progress(index, len(pending))

    def best_angles(limit: int) -> list[float]:
        valid = sorted((item for item in tested.values() if item.valid), key=rank_key)
        return [item.angle_deg for item in valid[:limit]]

    if config.straight_fixed_angle is not None:
        run([normalize_angle(config.straight_fixed_angle)])
        return list(tested.values())
    run(coarse_angles(config))
    if not config.refine:
        return sorted(tested.values(), key=lambda item: item.angle_deg)
    refine_step = min(config.refine_step_deg, config.straight_angle_step)
    if refine_step < config.straight_angle_step:
        span = max(config.straight_angle_step - refine_step, config.refine_span_deg)
        run(refine_angles(best_angles(max(1, config.refine_top_k)), span, refine_step))
    if 0 < config.fine_step_deg < refine_step:
        run(refine_angles(best_angles(1), refine_step, config.fine_step_deg))
    return sorted(tested.values(), key=lambda item: item.angle_deg)
