# -*- coding: utf-8 -*-
"""Validacao de candidatos e da curva de referencia; invalido = descartado da escolha."""

from __future__ import annotations

from shapely.geometry import LineString

from ..core.line_geometry import sanitize_master_polyline
from .models import StrategyAnalysisConfig, StrategyCandidate


def reference_curve_problems(points, tolerance_m: float) -> list[str]:
    """Problemas que impedem usar a curva como linha mestre (a camada original nao e lida aqui)."""
    raw = [tuple(point) for point in points]
    if len(raw) < 2:
        return ["Curva de referência com menos de 2 vértices."]
    problems = []
    if len(raw) > 2 and LineString(raw).length > 0:
        if (abs(raw[0][0] - raw[-1][0]) <= tolerance_m and abs(raw[0][1] - raw[-1][1]) <= tolerance_m):
            problems.append("Curva de referência fechada (loop).")
        elif not LineString(raw).is_simple:
            problems.append("Curva de referência com auto-interseção.")
    master = sanitize_master_polyline(raw)
    if len(master) < 3:
        problems.append("Referência sem curvatura (reta): use a estratégia reta.")
    return problems


def validate_candidate(candidate: StrategyCandidate, config: StrategyAnalysisConfig) -> StrategyCandidate:
    tolerances = config.tolerances
    errors = []
    if candidate.line_count == 0:
        errors.append("Nenhuma passada gerada dentro da área.")
    if candidate.self_intersection_count:
        errors.append(f"{candidate.self_intersection_count} passada(s) com auto-interseção/loop.")
    if candidate.crossing_count:
        errors.append(f"{candidate.crossing_count} par(es) de passadas se cruzando (offset quebrado).")
    if candidate.boundary_exit_length_m > tolerances.geometry_tolerance_m * max(1, candidate.line_count):
        errors.append(f"{candidate.boundary_exit_length_m:.2f} m fora da área permitida.")
    if (
        config.min_curve_radius_m is not None
        and candidate.minimum_curve_radius_m is not None
        and candidate.minimum_curve_radius_m < config.min_curve_radius_m
    ):
        errors.append(
            f"Raio mínimo {candidate.minimum_curve_radius_m:.1f} m < {config.min_curve_radius_m:.1f} m."
        )
    if candidate.short_segment_count:
        candidate.warnings.append(
            f"{candidate.short_segment_count} segmento(s) < {tolerances.minimum_segment_length_m:g} m."
        )
    candidate.warnings.extend(errors)
    candidate.valid = not errors
    return candidate
