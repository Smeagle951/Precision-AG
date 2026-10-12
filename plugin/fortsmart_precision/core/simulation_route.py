# -*- coding: utf-8 -*-
"""Dados da rota do simulador: passadas existentes, ordem, sentido e medidas ao longo da linha.

So le a geometria recebida: nao cria offset, nao recorta, nao suaviza e nao
prolonga. Inverter o sentido de percurso muda apenas a ordem de leitura dos
vertices, nunca as coordenadas. Toda distancia e em CRS metrico.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

Point = tuple[float, float]

SIMULATION_ROUTE_INVALID = "SIMULATION_ROUTE_INVALID"
PASS_END_EPSILON_M = 0.01
HEADING_EPSILON_M = 0.5


class RouteMode(str, Enum):
    SERPENTINE = "SERPENTINE"
    SAME_DIRECTION = "SAME_DIRECTION"
    CUSTOM_SEQUENCE = "CUSTOM_SEQUENCE"


class RouteValidationError(ValueError):
    def __init__(self, problems: Sequence[str]):
        self.code = SIMULATION_ROUTE_INVALID
        self.problems = tuple(problems)
        super().__init__(f"{SIMULATION_ROUTE_INVALID}: " + "; ".join(self.problems))


@dataclass(frozen=True)
class RoutePassInput:
    """Passada ja gerada pelo sistema (uma ou mais partes da mesma passada)."""

    id: str
    segments: tuple[tuple[Point, ...], ...]
    sequence: int | None = None
    field_id: str | None = None
    operation_id: str | None = None
    # MAIN = passada operacional; BORDER/AUXILIARY/TRAMLINE... cruzam de proposito.
    route_type: str | None = None


def _length(points: Sequence[Point]) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:]))


def bearing_deg(a: Point, b: Point) -> float:
    """Rumo de a para b: 0 = norte (+Y), sentido horario."""
    return math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) % 360.0


@dataclass(frozen=True)
class RoutePass:
    """Passada na ordem e no sentido de percurso, com medidas por distancia."""

    id: str
    sequence: int
    index: int
    segments: tuple[tuple[Point, ...], ...]
    reversed: bool = False
    field_id: str | None = None
    operation_id: str | None = None
    _vertex_stations: tuple[tuple[float, ...], ...] = field(default=(), init=False, repr=False, compare=False)
    _segment_starts: tuple[float, ...] = field(default=(), init=False, repr=False, compare=False)
    length_m: float = field(default=0.0, init=False)

    def __post_init__(self):
        stations: list[tuple[float, ...]] = []
        starts: list[float] = []
        total = 0.0
        for points in self.segments:
            starts.append(total)
            local = [total]
            for a, b in zip(points, points[1:]):
                total += math.hypot(b[0] - a[0], b[1] - a[1])
                local.append(total)
            stations.append(tuple(local))
        object.__setattr__(self, "_vertex_stations", tuple(stations))
        object.__setattr__(self, "_segment_starts", tuple(starts))
        object.__setattr__(self, "length_m", total)

    @property
    def start(self) -> Point:
        return self.segments[0][0]

    @property
    def end(self) -> Point:
        return self.segments[-1][-1]

    def _segment_at(self, distance_m: float) -> int:
        return max(0, bisect_right(self._segment_starts, distance_m) - 1)

    def _segment_range(self, segment: int) -> tuple[float, float]:
        stations = self._vertex_stations[segment]
        return stations[0], stations[-1]

    def _point_in_segment(self, segment: int, distance_m: float) -> Point:
        points = self.segments[segment]
        stations = self._vertex_stations[segment]
        d = min(max(distance_m, stations[0]), stations[-1])
        edge = min(max(bisect_right(stations, d) - 1, 0), len(points) - 2)
        span = stations[edge + 1] - stations[edge]
        t = 0.0 if span <= 0 else (d - stations[edge]) / span
        a, b = points[edge], points[edge + 1]
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

    def position_at(self, distance_m: float) -> Point:
        """Ponto interpolado na geometria real a `distance_m` do inicio do percurso."""
        d = min(max(distance_m, 0.0), self.length_m)
        return self._point_in_segment(self._segment_at(d), d)

    def heading_at(self, distance_m: float, epsilon_m: float = HEADING_EPSILON_M) -> float:
        """Rumo local: P1 = posicao(d - eps), P2 = posicao(d + eps), dentro da mesma parte."""
        d = min(max(distance_m, 0.0), self.length_m)
        segment = self._segment_at(d)
        low, high = self._segment_range(segment)
        before = max(low, d - epsilon_m)
        after = min(high, d + epsilon_m)
        if after - before <= 1e-9:
            before, after = low, high
        return bearing_deg(self._point_in_segment(segment, before), self._point_in_segment(segment, after))

    def parts_between(self, start_m: float, end_m: float) -> list[tuple[Point, ...]]:
        """Recorte da passada entre duas distancias (vertices originais preservados)."""
        start_m = min(max(start_m, 0.0), self.length_m)
        end_m = min(max(end_m, 0.0), self.length_m)
        if end_m - start_m <= 1e-9:
            return []
        parts: list[tuple[Point, ...]] = []
        for segment, points in enumerate(self.segments):
            low, high = self._segment_range(segment)
            a, b = max(start_m, low), min(end_m, high)
            if b - a <= 1e-9:
                continue
            stations = self._vertex_stations[segment]
            inner = [points[i] for i, s in enumerate(stations) if a < s < b]
            parts.append(
                (self._point_in_segment(segment, a), *inner, self._point_in_segment(segment, b))
            )
        return parts


@dataclass(frozen=True)
class OrderedRoute:
    passes: tuple[RoutePass, ...]
    mode: RouteMode

    @property
    def route_count(self) -> int:
        return len(self.passes)

    @property
    def total_length_m(self) -> float:
        return sum(item.length_m for item in self.passes)


def validate_route_input(
    passes: Sequence[RoutePassInput],
    *,
    mode: RouteMode = RouteMode.SERPENTINE,
    custom_order: Sequence[str] | None = None,
    crs_authid: str | None = None,
) -> list[str]:
    """Problemas que impedem a simulacao; nada e corrigido aqui."""
    problems: list[str] = []
    if crs_authid is not None:
        from .crs import CrsValidationError, require_projected_metric

        try:
            require_projected_metric(crs_authid, "simulacao de rota")
        except CrsValidationError as exc:
            problems.append(str(exc))
    if not passes:
        return problems + ["Nenhuma passada para simular."]
    seen_ids: set[str] = set()
    seen_sequences: dict[int, str] = {}
    for item in passes:
        label = item.id or "(sem id)"
        if not item.id:
            problems.append("Passada sem id.")
        elif item.id in seen_ids:
            problems.append(f"Passada {label} duplicada.")
        seen_ids.add(item.id)
        if not item.segments:
            problems.append(f"Passada {label}: geometria vazia.")
        for part in item.segments:
            if len(part) < 2:
                problems.append(f"Passada {label}: parte com menos de 2 vertices.")
            elif not all(math.isfinite(c) for point in part for c in point):
                problems.append(f"Passada {label}: coordenada invalida.")
        if item.segments and all(len(p) >= 2 for p in item.segments):
            if sum(_length(p) for p in item.segments) <= PASS_END_EPSILON_M:
                problems.append(f"Passada {label}: comprimento zero.")
        if mode is not RouteMode.CUSTOM_SEQUENCE:
            if item.sequence is None:
                problems.append(f"Passada {label}: sem sequencia definida.")
            elif item.sequence in seen_sequences:
                problems.append(
                    f"Sequencia {item.sequence} repetida ({seen_sequences[item.sequence]} e {label})."
                )
            else:
                seen_sequences[item.sequence] = label
    if mode is RouteMode.CUSTOM_SEQUENCE:
        order = list(custom_order or [])
        if sorted(order) != sorted(item.id for item in passes):
            problems.append("Sequencia personalizada deve conter cada passada exatamente uma vez.")
    return problems


def _chord(segments: tuple[tuple[Point, ...], ...]) -> Point:
    start, end = segments[0][0], segments[-1][-1]
    return (end[0] - start[0], end[1] - start[1])


def _reverse(segments: tuple[tuple[Point, ...], ...]) -> tuple[tuple[Point, ...], ...]:
    return tuple(tuple(reversed(part)) for part in reversed(segments))


def build_ordered_route(
    passes: Sequence[RoutePassInput],
    mode: RouteMode = RouteMode.SERPENTINE,
    *,
    custom_order: Sequence[str] | None = None,
    crs_authid: str | None = None,
) -> OrderedRoute:
    """ordered_route: sequencia definida + sentido de percurso pelo modo.

    SERPENTINE: P01 no sentido da propria passada, P02 oposto, P03 igual a P01...
    SAME_DIRECTION: todas no sentido da P01. CUSTOM_SEQUENCE: ordem informada,
    cada passada no sentido em que foi desenhada.
    """
    problems = validate_route_input(passes, mode=mode, custom_order=custom_order, crs_authid=crs_authid)
    if problems:
        raise RouteValidationError(problems)
    if mode is RouteMode.CUSTOM_SEQUENCE:
        position = {pass_id: i for i, pass_id in enumerate(custom_order or [])}
        ordered = sorted(passes, key=lambda item: position[item.id])
    else:
        ordered = sorted(passes, key=lambda item: item.sequence)
    reference = _chord(ordered[0].segments)
    result: list[RoutePass] = []
    for index, item in enumerate(ordered):
        reverse = False
        if mode is not RouteMode.CUSTOM_SEQUENCE and index > 0:
            sign = -1.0 if mode is RouteMode.SERPENTINE and index % 2 else 1.0
            chord = _chord(item.segments)
            reverse = (chord[0] * reference[0] + chord[1] * reference[1]) * sign < 0
        result.append(
            RoutePass(
                id=item.id,
                sequence=item.sequence if item.sequence is not None else index + 1,
                index=index,
                segments=_reverse(item.segments) if reverse else tuple(item.segments),
                reversed=reverse,
                field_id=item.field_id,
                operation_id=item.operation_id,
            )
        )
    return OrderedRoute(tuple(result), mode)
