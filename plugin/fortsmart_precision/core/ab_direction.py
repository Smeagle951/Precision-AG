# -*- coding: utf-8 -*-
"""Direcao A-B quando inicio e fim coincidem (linha fechada / anel)."""

from __future__ import annotations

from .line_geometry import Point, distance

_MIN_DIRECTION_SPAN_M = 0.5


def resolve_ab_direction_end(
    start: Point,
    end: Point,
    path_points: tuple[Point, ...] | list[Point] = (),
    *,
    min_span_m: float = _MIN_DIRECTION_SPAN_M,
) -> Point:
    """Retorna um ponto B util para azimute quando A≈B (anel fechado).

    A extensao externa (buffer) nao define direcao — so amplia o limite de clip.
    As passadas paralelas ja atravessam o talhao inteiro a partir da direcao A-B.
    """
    if distance(start, end) >= min_span_m:
        return end

    pts = list(path_points) if path_points else [start, end]
    if len(pts) < 2:
        pts = [start, end]

    closed = len(pts) >= 3 and distance(pts[0], pts[-1]) < min_span_m
    candidates = pts[1:-1] if closed else pts[1:]
    if not candidates:
        candidates = pts[1:]

    if candidates:
        far = max(candidates, key=lambda p: distance(start, p))
        if distance(start, far) >= min_span_m:
            return far
        for candidate in candidates:
            if distance(start, candidate) >= min_span_m:
                return candidate

    raise ValueError(
        "Linha A-B curta demais para definir a direcao das passadas.\n\n"
        "O que aconteceu: os pontos A e B estao no mesmo lugar (comum em linha "
        "FECHADA de bordadura, ou dois cliques no mesmo ponto).\n\n"
        "O que NAO resolve: 'Extensao externa' — ela so amplia o limite de "
        "processamento para alem do talhao; nao substitui a direcao A-B.\n\n"
        "Como corrigir:\n"
        "  • Capture A e B em pontos separados que cruzem o talhao, OU\n"
        "  • Use uma linha ABERTA (nao fechada) na camada de referencia, OU\n"
        "  • Converta o talhao para CRS metrico (SIRGAS UTM) antes de capturar."
    )


def ab_has_valid_direction(
    start: Point,
    end: Point,
    path_points: tuple[Point, ...] | list[Point] = (),
    *,
    min_span_m: float = _MIN_DIRECTION_SPAN_M,
) -> bool:
    try:
        resolve_ab_direction_end(start, end, path_points, min_span_m=min_span_m)
        return True
    except ValueError:
        return False
