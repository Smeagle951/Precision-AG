# -*- coding: utf-8 -*-
"""Corte longitudinal real: WORK_OFF/WORK_ON pela posicao da ultima linha ativa.

A fonte da verdade e a barra de trabalho (WORKING_ELEMENT_PATH), nao a
referencia da maquina. A trajetoria da maquina permanece continua; o corte
apenas registra intervalos WORKING/RAISED. Todas as medidas em CRS metrico.

Corte longitudinal = barra encostando na zona (obstaculo + raio + margem),
antecipado no sentido da passada pela antecipacao configurada. Largura do
implemento, espacamento entre passadas e bordadura nunca entram nessa conta.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Any, Iterable

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from ..domain.operation_simulation import (
    MachineWorkGeometry,
    WorkGeometryStatus,
    WorkState,
)

Point = tuple[float, float]

LOGGER = logging.getLogger("fortsmart_precision.obstacle_cut")

WORK_OFF = "WORK_OFF"
WORK_ON = "WORK_ON"


class LongitudinalCutError(ValueError):
    """Entrada invalida para o corte longitudinal."""


@dataclass(frozen=True)
class ObstacleInput:
    obstacle_id: str
    geometry: Any
    physical_radius_m: float = 0.0


@dataclass(frozen=True)
class ObstacleZone:
    """OBSTACLE_COLLISION_ZONE e zona de seguranca derivada (buffer isotropico pequeno)."""

    obstacle_id: str
    collision_zone: Any
    safety_zone: Any
    physical_radius_m: float
    safety_margin_m: float


@dataclass(frozen=True)
class WorkEvent:
    event_type: str
    pass_id: str
    station_m: float
    reference_xy: Point
    working_xy: Point
    measured_distance_m: float
    target_distance_m: float
    obstacle_ids: tuple[str, ...]
    note: str = ""


@dataclass(frozen=True)
class WorkInterval:
    start_station_m: float
    end_station_m: float
    state: WorkState
    obstacle_ids: tuple[str, ...] = ()
    swept_area: Any = None
    working_points: tuple[Point, ...] = ()
    zone_entry_station_m: float | None = None


@dataclass(frozen=True)
class PassCutResult:
    pass_id: str
    reference_path: tuple[Point, ...]
    working_path: tuple[Point, ...]
    events: tuple[WorkEvent, ...]
    intervals: tuple[WorkInterval, ...]
    main_work_area: Any
    unworked_area: Any
    target_distance_m: float
    obstacle_ids: tuple[str, ...] = field(default_factory=tuple)

    @property
    def affected(self) -> bool:
        return any(item.state is WorkState.RAISED for item in self.intervals)


def build_obstacle_zones(
    obstacles: Iterable[ObstacleInput],
    safety_margin_m: float,
    *,
    quad_segs: int = 32,
    allow_zero_area: bool = False,
) -> list[ObstacleZone]:
    """Zona de colisao = obstaculo + raio fisico; seguranca = colisao + margem.

    Geometrias sem area so sao aceitas quando o chamador possui outra margem
    lateral explicita no envelope da maquina. Isso evita inventar um raio para
    pontos/linhas e evita aplicar a mesma margem duas vezes.
    """
    if safety_margin_m < 0:
        raise LongitudinalCutError("Margem de seguranca nao pode ser negativa.")
    zones: list[ObstacleZone] = []
    for item in obstacles:
        if item.physical_radius_m < 0:
            raise LongitudinalCutError("Raio fisico do obstaculo nao pode ser negativo.")
        geometry = fill_closed_rings(item.geometry)
        if geometry is None or geometry.is_empty:
            continue
        collision = (
            geometry.buffer(item.physical_radius_m, quad_segs=quad_segs)
            if item.physical_radius_m > 0
            else geometry
        )
        if collision.area <= 0:
            if safety_margin_m <= 0 and not allow_zero_area:
                raise LongitudinalCutError(
                    f"Obstaculo {item.obstacle_id} sem area: informe raio fisico, "
                    "margem do obstaculo ou margem lateral da maquina."
                )
            collision = geometry
        safety = (
            collision.buffer(safety_margin_m, quad_segs=quad_segs)
            if safety_margin_m > 0
            else collision
        )
        zones.append(
            ObstacleZone(
                obstacle_id=str(item.obstacle_id),
                collision_zone=collision,
                safety_zone=safety,
                physical_radius_m=item.physical_radius_m,
                safety_margin_m=safety_margin_m,
            )
        )
    return zones


class _ReferencePath:
    def __init__(self, points: Iterable[Point]):
        cleaned: list[Point] = []
        for point in points:
            xy = (float(point[0]), float(point[1]))
            if not cleaned or xy != cleaned[-1]:
                cleaned.append(xy)
        if len(cleaned) < 2:
            raise LongitudinalCutError("A trajetoria da referencia precisa de dois pontos.")
        self.points = tuple(cleaned)
        self._xy = np.asarray(cleaned, dtype=float)
        self._cumulative = np.concatenate(
            ([0.0], np.cumsum(np.hypot(*np.diff(self._xy, axis=0).T)))
        )
        self.length = float(self._cumulative[-1])
        if self.length <= 0:
            raise LongitudinalCutError("A trajetoria da referencia tem comprimento zero.")
        start, end = self._xy[0], self._xy[-1]
        chord = end - start
        norm = float(np.hypot(*chord))
        self._fallback = chord / norm if norm > 1e-12 else np.array([1.0, 0.0])

    def positions(self, stations) -> np.ndarray:
        s = np.clip(np.asarray(stations, dtype=float), 0.0, self.length)
        return np.column_stack(
            (np.interp(s, self._cumulative, self._xy[:, 0]), np.interp(s, self._cumulative, self._xy[:, 1]))
        )

    def tangents(self, stations, half_window_m: float = 0.5) -> np.ndarray:
        s = np.asarray(stations, dtype=float)
        delta = self.positions(s + half_window_m) - self.positions(s - half_window_m)
        norm = np.hypot(delta[:, 0], delta[:, 1])
        degenerate = norm <= 1e-12
        norm[degenerate] = 1.0
        result = delta / norm[:, None]
        result[degenerate] = self._fallback
        return result

    def position(self, station: float) -> Point:
        x, y = self.positions([station])[0]
        return (float(x), float(y))

    def tangent(self, station: float, half_window_m: float = 0.5) -> Point:
        tx, ty = self.tangents([station], half_window_m)[0]
        return (float(tx), float(ty))


def _working_offset(geometry: MachineWorkGeometry) -> float:
    offset = geometry.reference_to_working_line_longitudinal_m
    if offset is None:
        raise LongitudinalCutError(
            "GEOMETRY_INCOMPLETE: posicao da ultima linha de trabalho nao informada."
        )
    return offset


def working_centers(path: _ReferencePath, stations, geometry: MachineWorkGeometry):
    """Vetorizado: (referencias, centros da barra ativa, tangentes) por estacao."""
    offset = _working_offset(geometry)
    references = path.positions(stations)
    tangents = path.tangents(stations)
    normals = np.column_stack((tangents[:, 1], -tangents[:, 0]))
    centers = references + tangents * offset + normals * geometry.working_lateral_offset_m
    return references, centers, tangents


def working_element_pose(
    path: _ReferencePath, station: float, geometry: MachineWorkGeometry
) -> tuple[Point, Point, Point]:
    """W(s) = R(s) + T(s)*offset_long + N(s)*offset_lateral, com tangente local."""
    references, centers, tangents = working_centers(path, [station], geometry)
    return (
        (float(references[0][0]), float(references[0][1])),
        (float(centers[0][0]), float(centers[0][1])),
        (float(tangents[0][0]), float(tangents[0][1])),
    )


def _working_bars(path: _ReferencePath, stations, geometry: MachineWorkGeometry, half: float | None = None):
    _references, centers, tangents = working_centers(path, stations, geometry)
    half = geometry.half_width_m if half is None else half
    normals = np.column_stack((tangents[:, 1], -tangents[:, 0])) * half
    coords = np.stack((centers - normals, centers + normals), axis=1)
    return shapely.linestrings(coords)


def working_bar(
    path: _ReferencePath, station: float, geometry: MachineWorkGeometry, half: float | None = None
) -> LineString:
    _reference, center, (tx, ty) = working_element_pose(path, station, geometry)
    nx, ny = ty, -tx
    half = geometry.half_width_m if half is None else half
    return LineString(
        [(center[0] - nx * half, center[1] - ny * half), (center[0] + nx * half, center[1] + ny * half)]
    )


def _interval_centers(
    path: _ReferencePath, geometry: MachineWorkGeometry, start: float, end: float, step: float
) -> tuple[Point, ...]:
    count = max(1, int((end - start) / step))
    stations = np.linspace(start, end, count + 1)
    _references, centers, _tangents = working_centers(path, stations, geometry)
    return tuple((float(x), float(y)) for x, y in centers)


def _swept_from_centers(centers: tuple[Point, ...], geometry: MachineWorkGeometry):
    if len(centers) < 2:
        return Polygon()
    return _simplified(centers).buffer(geometry.half_width_m, cap_style="flat", quad_segs=16)


def _simplified(points) -> LineString:
    """Remove vertices colineares da amostragem densa (erro <= 1 mm)."""
    return LineString(points).simplify(0.001, preserve_topology=False)


def _path_stations(length: float, step: float) -> np.ndarray:
    count = max(1, int(length / step + 0.5))
    return np.linspace(0.0, length, count + 1)


def fill_closed_rings(geometry: Any) -> Any:
    """Circulo/contorno marcado como linha fechada representa a area do obstaculo."""
    if geometry is None or geometry.is_empty:
        return geometry
    if geometry.geom_type == "LineString":
        coords = list(geometry.coords)
        if len(coords) >= 4 and geometry.is_closed:
            polygon = Polygon(coords)
            if polygon.is_valid and polygon.area > 0:
                return polygon
        return geometry
    if geometry.geom_type == "MultiLineString":
        parts = [fill_closed_rings(part) for part in geometry.geoms]
        return unary_union(parts)
    return geometry


def compute_longitudinal_cut(
    pass_id: str,
    reference_points: Iterable[Point],
    zones: list[ObstacleZone],
    geometry: MachineWorkGeometry,
    *,
    sample_step_m: float | None = None,
    tolerance_m: float = 0.05,
) -> PassCutResult:
    """Encontra WORK_OFF/WORK_ON pela distancia real barra ativa -> zona."""
    geometry.validate()
    if geometry.status is WorkGeometryStatus.GEOMETRY_INCOMPLETE:
        raise LongitudinalCutError(
            "GEOMETRY_INCOMPLETE: informe a posicao da ultima linha de trabalho."
        )
    if tolerance_m <= 0:
        raise LongitudinalCutError("Tolerancia do corte deve ser maior que zero.")
    path = _ReferencePath(reference_points)
    target = geometry.required_cut_distance_m()
    threshold = max(target, 1e-9)
    anticipation = geometry.longitudinal_anticipation_m
    step = sample_step_m or min(0.5, max(0.05, geometry.work_width_m / 80.0))

    stations = _path_stations(path.length, step)
    _references, centers, _tangents = working_centers(path, stations, geometry)
    working_points = tuple((float(x), float(y)) for x, y in centers)
    clearance_half = geometry.half_width_m + geometry.safety_margin_lateral_m
    corridor = _simplified(working_points).buffer(clearance_half, cap_style="flat", quad_segs=16)
    # LONGITUDINAL_CUT_ZONE: so a parte da zona que entra na faixa da passada.
    clipped: list[tuple[str, Any]] = []
    for zone in zones:
        if not zone.safety_zone.intersects(corridor):
            continue
        part = zone.safety_zone.intersection(corridor)
        if not part.is_empty:
            clipped.append((zone.obstacle_id, part))

    clipped_union = unary_union([part for _oid, part in clipped]) if clipped else None
    if clipped_union is not None:
        shapely.prepare(clipped_union)

    def distance(station: float) -> float:
        if clipped_union is None:
            return float("inf")
        return float(working_bar(path, station, geometry, clearance_half).distance(clipped_union))

    def raised(station: float) -> bool:
        return distance(station) < threshold

    boundaries: list[tuple[float, float]] = []
    if clipped:
        stations = [float(s) for s in stations]
        flags = list(
            shapely.distance(_working_bars(path, stations, geometry, clearance_half), clipped_union) < threshold
        )
        start = stations[0] if flags[0] else None
        for previous, current, prev_flag, flag in zip(stations, stations[1:], flags, flags[1:]):
            if prev_flag == flag:
                continue
            edge = _bisect(raised, previous, current, prev_flag, precision=min(1e-3, tolerance_m / 50.0))
            if flag:
                start = edge
            else:
                boundaries.append((start if start is not None else stations[0], edge))
                start = None
        if start is not None:
            boundaries.append((start, path.length))

    events: list[WorkEvent] = []
    intervals: list[WorkInterval] = []
    cursor = 0.0
    all_ids: set[str] = set()
    def interval(
        start: float, end: float, state: WorkState, ids: tuple[str, ...] = (), entry: float | None = None
    ) -> WorkInterval:
        points = _interval_centers(path, geometry, start, end, step)
        simplified = tuple(_simplified(points).coords) if len(points) >= 2 else points
        return WorkInterval(start, end, state, ids, _swept_from_centers(points, geometry), simplified, entry)

    for raised_start, raised_end, zone_entry, merged in _anticipate(boundaries, anticipation):
        if raised_start - cursor > 1e-9:
            intervals.append(interval(cursor, raised_start, WorkState.WORKING))
        swept = _swept_from_centers(
            _interval_centers(path, geometry, raised_start, raised_end, step), geometry
        )
        ids = tuple(
            sorted({oid for oid, part in clipped if swept.buffer(tolerance_m).intersects(part)})
        )
        all_ids.update(ids)
        intervals.append(interval(raised_start, raised_end, WorkState.RAISED, ids, zone_entry))
        off_note = (
            "START_RAISED" if raised_start <= 1e-9
            else "ANTICIPATION_MERGED" if merged
            else ""
        )
        for event_type, station, note, event_target in (
            (WORK_OFF, raised_start, off_note, target + (zone_entry - raised_start)),
            (WORK_ON, raised_end, "END_RAISED" if raised_end >= path.length - 1e-9 else "", target),
        ):
            reference, center, _tangent = working_element_pose(path, station, geometry)
            events.append(
                WorkEvent(
                    event_type=event_type,
                    pass_id=str(pass_id),
                    station_m=station,
                    reference_xy=reference,
                    working_xy=center,
                    measured_distance_m=distance(station),
                    target_distance_m=event_target,
                    obstacle_ids=ids,
                    note=note,
                )
            )
        cursor = raised_end
    if path.length - cursor > 1e-9:
        intervals.append(interval(cursor, path.length, WorkState.WORKING))

    if LOGGER.isEnabledFor(logging.INFO):
        zones_by_id = {zone.obstacle_id: zone for zone in zones}
        for item in intervals:
            if item.state is WorkState.RAISED:
                LOGGER.info(cut_debug_text(cut_breakdown(str(pass_id), item, zones_by_id, geometry)))

    main = unary_union([i.swept_area for i in intervals if i.state is WorkState.WORKING])
    unworked = unary_union([i.swept_area for i in intervals if i.state is WorkState.RAISED])
    return PassCutResult(
        pass_id=str(pass_id),
        reference_path=path.points,
        working_path=tuple(_simplified(working_points).coords),
        events=tuple(events),
        intervals=tuple(intervals),
        main_work_area=main,
        unworked_area=unworked,
        target_distance_m=target,
        obstacle_ids=tuple(sorted(all_ids)),
    )


def _bisect(predicate, low: float, high: float, low_value: bool, *, precision: float) -> float:
    """Estacao da transicao; o evento fica sempre do lado seguro (fora da zona)."""
    while high - low > precision:
        middle = (low + high) / 2.0
        if predicate(middle) == low_value:
            low = middle
        else:
            high = middle
    return high if low_value else low


def _anticipate(
    spans: list[tuple[float, float]], anticipation_m: float
) -> list[tuple[float, float, float, bool]]:
    """(WORK_OFF, WORK_ON, entrada na zona, fundido) com o desligamento antecipado.

    As estacoes crescem no sentido de deslocamento da passada, entao a
    antecipacao sempre recua o WORK_OFF para antes da entrada, seja qual for o
    sentido de digitalizacao. O WORK_ON fica na saida da zona.
    """
    result: list[tuple[float, float, float, bool]] = []
    for entry, exit_station in spans:
        start = max(0.0, entry - anticipation_m)
        if result and start <= result[-1][1] + 1e-9:
            previous_start, _previous_end, previous_entry, _merged = result[-1]
            result[-1] = (previous_start, exit_station, previous_entry, True)
            continue
        result.append((start, exit_station, entry, False))
    return result


@dataclass(frozen=True)
class LongitudinalCutBreakdown:
    """Origem de cada valor do corte longitudinal de uma passada (debug e relatorio)."""

    pass_id: str
    obstacle_ids: tuple[str, ...]
    working_width_m: float
    obstacle_radius_m: float
    safety_margin_m: float
    longitudinal_clearance_m: float
    anticipation_m: float
    reference_type: str
    reference_to_operation_m: float
    zone_entry_station_m: float
    work_off_station_m: float
    work_on_station_m: float

    @property
    def safety_zone_m(self) -> float:
        return self.obstacle_radius_m + self.safety_margin_m

    @property
    def anticipated_m(self) -> float:
        return self.zone_entry_station_m - self.work_off_station_m

    @property
    def cut_distance_m(self) -> float:
        return self.work_on_station_m - self.work_off_station_m

    def to_dict(self) -> dict[str, object]:
        return {
            "pass_id": self.pass_id,
            "obstacle_ids": list(self.obstacle_ids),
            "working_width_m": self.working_width_m,
            "obstacle_radius_m": self.obstacle_radius_m,
            "safety_margin_m": self.safety_margin_m,
            "safety_zone_m": round(self.safety_zone_m, 4),
            "longitudinal_clearance_m": self.longitudinal_clearance_m,
            "anticipation_m": self.anticipation_m,
            "reference_type": self.reference_type,
            "reference_to_operation_m": self.reference_to_operation_m,
            "zone_entry_station_m": round(self.zone_entry_station_m, 4),
            "work_off_station_m": round(self.work_off_station_m, 4),
            "work_on_station_m": round(self.work_on_station_m, 4),
            "anticipated_m": round(self.anticipated_m, 4),
            "cut_distance_m": round(self.cut_distance_m, 4),
        }


def cut_breakdown(
    pass_id: str,
    interval: WorkInterval,
    zones_by_id: dict[str, ObstacleZone],
    geometry: MachineWorkGeometry,
) -> LongitudinalCutBreakdown:
    zones = [zones_by_id[oid] for oid in interval.obstacle_ids if oid in zones_by_id]
    entry = interval.zone_entry_station_m
    return LongitudinalCutBreakdown(
        pass_id=pass_id,
        obstacle_ids=interval.obstacle_ids,
        working_width_m=geometry.work_width_m,
        obstacle_radius_m=max((zone.physical_radius_m for zone in zones), default=0.0),
        safety_margin_m=max((zone.safety_margin_m for zone in zones), default=0.0),
        longitudinal_clearance_m=geometry.required_cut_distance_m(),
        anticipation_m=geometry.longitudinal_anticipation_m,
        reference_type=geometry.reference_type.value,
        reference_to_operation_m=_working_offset(geometry),
        zone_entry_station_m=interval.start_station_m if entry is None else entry,
        work_off_station_m=interval.start_station_m,
        work_on_station_m=interval.end_station_m,
    )


def cut_debug_text(item: LongitudinalCutBreakdown) -> str:
    def m(value: float) -> str:
        return f"{value:.2f} m"

    side = "a frente" if item.reference_to_operation_m > 0 else "atras" if item.reference_to_operation_m < 0 else "alinhado"
    return "\n".join((
        "=== FORTSMART OBSTACLE CUT DEBUG ===",
        f"PASSADA: {item.pass_id}  OBSTACULOS: {','.join(item.obstacle_ids) or '-'}",
        f"WORKING WIDTH: {m(item.working_width_m)} (Largura do implemento; so faixa lateral/corredor)",
        "SPACING: nao usado no corte longitudinal",
        f"OBSTACLE RADIUS: {m(item.obstacle_radius_m)} (Raio fisico do poste)",
        f"SAFETY MARGIN: {m(item.safety_margin_m)} (Margem adicional do obstaculo)",
        f"LONGITUDINAL CLEARANCE: {m(item.longitudinal_clearance_m)} (Margem longitudinal adicional)",
        f"LONGITUDINAL ANTICIPATION: {m(item.anticipation_m)} (Antecipacao de desligamento)",
        f"REFERENCE POINT: {item.reference_type}",
        f"REFERENCE -> OPERATION: {m(item.reference_to_operation_m)} ({side}; Offset da ultima linha ativa)",
        f"CALCULATED SAFETY ZONE: {m(item.safety_zone_m)} (raio + margem)",
        f"ZONE ENTRY STATION: {m(item.zone_entry_station_m)}",
        f"WORK_OFF STATION: {m(item.work_off_station_m)} (antecipado {m(item.anticipated_m)})",
        f"WORK_ON STATION: {m(item.work_on_station_m)}",
        f"CALCULATED CUT DISTANCE: {m(item.cut_distance_m)}",
    ))


def calculate_longitudinal_cut_distance(
    route: Iterable[Point],
    obstacle: ObstacleInput,
    machine_config: MachineWorkGeometry,
    *,
    safety_margin_m: float = 0.0,
    pass_id: str = "P",
) -> LongitudinalCutBreakdown | None:
    """Trecho desligado de uma passada por um obstaculo; None se a barra nao encosta na zona."""
    zones = build_obstacle_zones(
        [obstacle], safety_margin_m, allow_zero_area=machine_config.safety_margin_lateral_m > 0
    )
    result = compute_longitudinal_cut(pass_id, route, zones, machine_config)
    raised = [item for item in result.intervals if item.state is WorkState.RAISED]
    if not raised:
        return None
    first, last = raised[0], raised[-1]
    merged = replace(first, end_station_m=last.end_station_m)
    return cut_breakdown(pass_id, merged, {zone.obstacle_id: zone for zone in zones}, machine_config)
