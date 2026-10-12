# -*- coding: utf-8 -*-
"""Transicoes tangentes (Bezier cubica) e verificacao de raio minimo."""

from __future__ import annotations

import math

import numpy as np

from ...domain.obstacle_strategy import GEOMETRY_EPSILON

Coord = tuple[float, float]
Vector = tuple[float, float]

BEZIER_SAMPLES = 48
TRANSITION_ALPHAS = (0.35, 0.45, 0.55)
# Tolerancia numerica da amostragem ao comparar raio com o minimo exigido.
RADIUS_TOLERANCE = 0.02


def cubic_bezier(p0: Coord, p1: Coord, p2: Coord, p3: Coord, samples: int = BEZIER_SAMPLES) -> list[Coord]:
    t = np.linspace(0.0, 1.0, samples)[:, None]
    pts = (
        ((1 - t) ** 3) * np.asarray(p0)
        + 3 * ((1 - t) ** 2) * t * np.asarray(p1)
        + 3 * (1 - t) * (t**2) * np.asarray(p2)
        + (t**3) * np.asarray(p3)
    )
    return [(float(x), float(y)) for x, y in pts]


def build_transition(start: Coord, start_dir: Vector, end: Coord, end_dir: Vector, alpha: float) -> list[Coord]:
    """Curva que sai de start na direcao start_dir e chega em end na direcao end_dir."""
    chord = math.hypot(end[0] - start[0], end[1] - start[1])
    reach = chord * alpha
    c1 = (start[0] + start_dir[0] * reach, start[1] + start_dir[1] * reach)
    c2 = (end[0] - end_dir[0] * reach, end[1] - end_dir[1] * reach)
    return cubic_bezier(start, c1, c2, end)


def build_entry_transition(pre_entry: Coord, path_dir: Vector, contour_point: Coord, contour_dir: Vector, alpha: float) -> list[Coord]:
    return build_transition(pre_entry, path_dir, contour_point, contour_dir, alpha)


def build_exit_transition(contour_point: Coord, contour_dir: Vector, post_exit: Coord, path_dir: Vector, alpha: float) -> list[Coord]:
    return build_transition(contour_point, contour_dir, post_exit, path_dir, alpha)


def _clean(coords) -> np.ndarray:
    arr = np.asarray(coords, dtype=float)
    if len(arr) < 2:
        return arr
    keep = [0]
    for index in range(1, len(arr)):
        if np.hypot(*(arr[index] - arr[keep[-1]])) > GEOMETRY_EPSILON:
            keep.append(index)
    return arr[keep]


def minimum_radius(coords) -> float:
    """Menor raio do circulo por tres vertices consecutivos (inf se reto)."""
    arr = _clean(coords)
    if len(arr) < 3:
        return math.inf
    p0, p1, p2 = arr[:-2], arr[1:-1], arr[2:]
    a = np.hypot(*(p1 - p0).T)
    b = np.hypot(*(p2 - p1).T)
    c = np.hypot(*(p2 - p0).T)
    cross = np.abs((p1 - p0)[:, 0] * (p2 - p0)[:, 1] - (p1 - p0)[:, 1] * (p2 - p0)[:, 0])
    with np.errstate(divide="ignore", invalid="ignore"):
        radii = np.where(cross > 1e-12, (a * b * c) / (2.0 * cross), np.inf)
    return float(np.min(radii)) if len(radii) else math.inf


def validate_turn_radius(coords, required_radius: float) -> bool:
    return minimum_radius(coords) >= required_radius * (1.0 - RADIUS_TOLERANCE)


def total_heading_change(coords) -> float:
    arr = _clean(coords)
    if len(arr) < 3:
        return 0.0
    seg = np.diff(arr, axis=0)
    angles = np.arctan2(seg[:, 1], seg[:, 0])
    delta = np.diff(angles)
    delta = (delta + np.pi) % (2 * np.pi) - np.pi
    return float(np.sum(np.abs(delta)))


def max_heading_jump(coords) -> float:
    """Maior quebra angular entre segmentos consecutivos (detecta quinas)."""
    arr = _clean(coords)
    if len(arr) < 3:
        return 0.0
    seg = np.diff(arr, axis=0)
    angles = np.arctan2(seg[:, 1], seg[:, 0])
    delta = np.diff(angles)
    delta = (delta + np.pi) % (2 * np.pi) - np.pi
    return float(np.max(np.abs(delta)))
