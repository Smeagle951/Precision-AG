# -*- coding: utf-8 -*-
"""Referencia de guiamento: reta, curva ou adaptativa."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4

from ..core.line_geometry import Point, distance, sanitize_master_polyline


class GuidanceMode(str, Enum):
    STRAIGHT = "straight"
    CURVED = "curved"
    ADAPTIVE = "adaptive"


class GuidanceReferenceError(ValueError):
    """Erro na referencia de guiamento."""


@dataclass(frozen=True)
class GuidanceReference:
    mode: GuidanceMode = GuidanceMode.STRAIGHT
    start: Point = (0.0, 0.0)
    end: Point = (0.0, 0.0)
    control_points: tuple[Point, ...] = ()
    reference_id: str = field(default_factory=lambda: str(uuid4()))

    def validate(self) -> None:
        if self.mode == GuidanceMode.STRAIGHT:
            if distance(self.start, self.end) <= 0.01:
                raise GuidanceReferenceError("Referencia reta exige dois pontos validos.")
        if self.mode in {GuidanceMode.CURVED, GuidanceMode.ADAPTIVE} and len(self.control_points) < 2:
            raise GuidanceReferenceError("Referencia curva/adaptativa exige pontos de controle.")

    @classmethod
    def from_ab(cls, start: Point, end: Point) -> GuidanceReference:
        return cls(mode=GuidanceMode.STRAIGHT, start=start, end=end)

    def ab_line(self) -> tuple[Point, Point]:
        """Compatibilidade com pipeline v1: usa start/end."""
        return self.start, self.end

    def full_path_points(self) -> tuple[Point, ...]:
        """Polilinha mestra completa — nunca colapsa curva em reta start/end."""
        if not self.control_points:
            return (self.start, self.end)
        pts = list(self.control_points)
        if pts[0] != self.start:
            pts = [self.start] + pts
        if pts[-1] != self.end:
            pts = pts + [self.end]
        if len(pts) < 2:
            return (self.start, self.end)
        return tuple(sanitize_master_polyline(pts))


_REVERSAL_COS = -0.5  # ~120 graus: so conta manobra de cabeceira, nao curva suave
_SERPENTINE_LENGTH_RATIO = 2.5


def looks_like_adaptive_serpentine(points: list[Point] | tuple[Point, ...]) -> bool:
    """Distingue AdaptiveCurve (serpentina) de uma A-B curva suave.

    Contar vertices nao serve: uma A-B curva densificada tem centenas de pontos
    e continua sendo UMA passada de referencia. O que caracteriza a serpentina
    e o trajeto de ida-e-volta:

    - inversoes de sentido (manobra de cabeceira, viragem > ~120 graus);
    - comprimento percorrido muito maior que a corda inicio->fim.

    Tratar uma A-B curva como serpentina faria o motor gerar passadas a partir
    de um traçado que ja e ida-e-volta, duplicando a cobertura.
    """
    pts = [pt for pt in points]
    if len(pts) < 4:
        return False

    headings: list[tuple[float, float]] = []
    total_length = 0.0
    for a, b in zip(pts, pts[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = (dx * dx + dy * dy) ** 0.5
        if length <= 1e-9:
            continue
        total_length += length
        headings.append((dx / length, dy / length))

    reversals = 0
    for prev, cur in zip(headings, headings[1:]):
        if prev[0] * cur[0] + prev[1] * cur[1] <= _REVERSAL_COS:
            reversals += 1
    if reversals >= 2:
        return True

    chord = distance(pts[0], pts[-1])
    if chord <= 1e-6:
        return total_length > 1e-6
    return total_length / chord >= _SERPENTINE_LENGTH_RATIO


def classify_guidance_mode(points: list[Point] | tuple[Point, ...]) -> str:
    """Classifica reta / curva / adaptativa a partir dos vertices."""
    if len(points) <= 2:
        return "straight"
    if looks_like_adaptive_serpentine(points):
        return "adaptive"
    start, end = points[0], points[-1]
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length2 = dx * dx + dy * dy
    if length2 <= 1e-12:
        return "curved"
    max_off = 0.0
    for x, y in points[1:-1]:
        cross = abs((x - start[0]) * dy - (y - start[1]) * dx)
        max_off = max(max_off, cross / (length2 ** 0.5))
    if max_off <= 0.25:
        return "straight"
    return "curved"
