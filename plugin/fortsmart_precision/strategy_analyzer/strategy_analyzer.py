# -*- coding: utf-8 -*-
"""Orquestrador: testa estrategias em memoria e devolve metricas; nunca grava camada final."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

from .curve_strategy import generate_curve_candidate
from .field_context import FieldContext
from .models import (
    ANALYSIS_VERSION,
    CRITERION_LINE_COUNT,
    CRITERION_TOTAL_LENGTH,
    CRITERION_TURN_COUNT,
    CURVE_REFERENCE_REQUIRED,
    CURVE_STRATEGY_INVALID,
    STRATEGY_ANALYSIS_NO_VALID_STRAIGHT,
    StrategyAnalysisConfig,
    StrategyAnalysisError,
    StrategyAnalysisResult,
    StrategyCandidate,
    StrategyType,
)
from .strategy_metrics import apply_coverage_metrics, apply_line_metrics, minimum_curve_radius
from .strategy_ranker import best_by, comparison_rows, rank_key, select_preview_candidates
from .strategy_validator import validate_candidate
from .straight_strategy import search_straight

ProgressCallback = Callable[[str], None]


class LineStrategyAnalyzer:
    def __init__(
        self,
        *,
        progress: ProgressCallback | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ):
        self._progress = progress
        self._is_cancelled = is_cancelled

    def _report(self, message: str) -> None:
        if self._progress is not None:
            self._progress(message)

    def _cancelled(self) -> bool:
        return bool(self._is_cancelled is not None and self._is_cancelled())

    def _evaluate(self, context: FieldContext, config: StrategyAnalysisConfig, candidate: StrategyCandidate):
        if not candidate.valid and not candidate.lines:
            return candidate
        is_curve = candidate.strategy_type is StrategyType.CURVE
        apply_line_metrics(
            candidate,
            context.allowed_shape,
            config.tolerances,
            check_crossings=is_curve,
        )
        if is_curve:
            candidate.minimum_curve_radius_m = minimum_curve_radius(
                candidate.lines, min_chord_m=max(1.0, context.pass_spacing_m / 2.0)
            )
        return validate_candidate(candidate, config)

    def analyze(self, context: FieldContext, config: StrategyAnalysisConfig) -> StrategyAnalysisResult:
        config.validate()
        context.validate()
        started = time.perf_counter()
        result = StrategyAnalysisResult(field_id=context.field_id)

        def evaluate(candidate):
            return self._evaluate(context, config, candidate)

        if config.test_straight:
            def straight_progress(done: int, total: int) -> None:
                self._report(f"Analisando retas... {done} / {total}")

            straights = search_straight(
                context,
                config,
                evaluate,
                rank_key(config.ranking_criterion),
                progress=straight_progress,
                is_cancelled=self._cancelled,
            )
            result.candidates.extend(straights)
            result.straight_tested = len(straights)
            result.straight_valid = sum(1 for item in straights if item.valid)
            if not result.straight_valid and not self._cancelled():
                result.add_issue(STRATEGY_ANALYSIS_NO_VALID_STRAIGHT)

        if self._cancelled():
            result.cancelled = True
            result.elapsed_s = time.perf_counter() - started
            return result

        if config.test_curve:
            self._report("Analisando curva...")
            try:
                curve = evaluate(generate_curve_candidate(context, config.tolerances))
            except StrategyAnalysisError as exc:
                result.add_issue(exc.code, str(exc))
            else:
                result.candidates.append(curve)
                if not curve.valid:
                    result.add_issue(CURVE_STRATEGY_INVALID, "; ".join(curve.warnings))

        if self._cancelled():
            result.cancelled = True
            result.elapsed_s = time.perf_counter() - started
            return result

        result.best_by_line_count = best_by(result.candidates, CRITERION_LINE_COUNT)
        result.best_by_total_length = best_by(result.candidates, CRITERION_TOTAL_LENGTH)
        result.best_by_turn_count = best_by(result.candidates, CRITERION_TURN_COUNT)
        result.preview_candidates = select_preview_candidates(
            result.candidates,
            config.ranking_criterion,
            config.max_preview_candidates,
            min_angle_separation=config.straight_angle_step,
        )
        if config.compute_coverage:
            self._report("Calculando cobertura dos finalistas...")
            for candidate in result.preview_candidates:
                if self._cancelled():
                    result.cancelled = True
                    break
                apply_coverage_metrics(candidate, context.work_shape)
        result.elapsed_s = time.perf_counter() - started
        return result


def log_summary(result: StrategyAnalysisResult) -> str:
    """Field: TL-13 / STRAIGHT tested=36 valid=34 best_angle=37 lines=78 length=18240 / CURVE ..."""
    parts = [f"Field: {result.field_id}"]
    straights = [item for item in result.straight_candidates() if item.valid]
    if result.straight_tested:
        best = next((item for item in result.preview_candidates if item.strategy_type is StrategyType.STRAIGHT), None)
        text = f"STRAIGHT tested={result.straight_tested} valid={len(straights)}"
        if best is not None:
            text += f" best_angle={best.angle_deg:g} lines={best.line_count} length={best.total_length_m:.0f}"
        parts.append(text)
    curve = result.curve_candidate()
    if curve is not None:
        text = f"CURVE valid={str(curve.valid).lower()}"
        if curve.lines:
            text += f" lines={curve.line_count} length={curve.total_length_m:.0f}"
        parts.append(text)
    elif CURVE_REFERENCE_REQUIRED in result.issue_codes:
        parts.append(f"CURVE {CURVE_REFERENCE_REQUIRED}")
    parts.append(f"time={result.elapsed_s:.2f}s")
    return " / ".join(parts)


def analysis_report(result: StrategyAnalysisResult, config: StrategyAnalysisConfig) -> dict:
    return {
        "analysis_version": ANALYSIS_VERSION,
        "field_id": result.field_id,
        "elapsed_s": round(result.elapsed_s, 3),
        "cancelled": result.cancelled,
        "config": {
            "test_straight": config.test_straight,
            "test_curve": config.test_curve,
            "straight_angle_start": config.straight_angle_start,
            "straight_angle_end": config.straight_angle_end,
            "straight_angle_step": config.straight_angle_step,
            "ranking_criterion": config.ranking_criterion,
            "minimum_segment_length_m": config.tolerances.minimum_segment_length_m,
        },
        "straight_tested": result.straight_tested,
        "straight_valid": result.straight_valid,
        "best_by_line_count": getattr(result.best_by_line_count, "candidate_id", None),
        "best_by_total_length": getattr(result.best_by_total_length, "candidate_id", None),
        "best_by_turn_count": getattr(result.best_by_turn_count, "candidate_id", None),
        "comparison": comparison_rows(result.preview_candidates),
        "preview_candidates": [item.metrics() for item in result.preview_candidates],
        "candidates": [item.metrics() for item in result.candidates],
        "issues": list(result.issue_codes),
        "warnings": list(result.warnings),
        "summary": log_summary(result),
    }


def write_analysis_report(path: str | Path, result: StrategyAnalysisResult, config: StrategyAnalysisConfig) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(analysis_report(result, config), ensure_ascii=False, indent=2), encoding="utf-8")
    return target
