# -*- coding: utf-8 -*-
"""Desvio lateral na trajetoria mestra (centro da maquina).

Fluxo por grupo de obstaculos: contorno seguro -> entrada/saida -> pontos de
aproximacao e retorno -> transicoes tangentes -> arco necessario -> costura
local. Nada fora de [aproximacao, retorno] e alterado.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.prepared import prep

from ...domain.obstacle_strategy import (
    DETOUR_NOT_FEASIBLE,
    GEOMETRY_EPSILON,
    ContourStrategy,
    DetourSide,
    ObstacleConfig,
    ObstacleHandlingStrategy,
)
from .clearance import (
    MachineEnvelope,
    ObstacleGroup,
    calculate_machine_envelope,
    contour_polygon,
    detect_obstacle_conflict,
    group_obstacles,
    merge_groups,
    obstacle_core,
)
from .contour import (
    arc_span,
    calculate_post_exit_point,
    calculate_pre_entry_point,
    doubled_ring,
    find_entry_exit_points,
    oriented_ring,
    path_tangent,
    unit,
)
from .stitcher import WORK_OFF, WORK_ON, split_work_segments, stitch_local_detour
from .transition import (
    TRANSITION_ALPHAS,
    build_entry_transition,
    build_exit_transition,
    minimum_radius,
    total_heading_change,
    validate_turn_radius,
)
from .validator import DetourValidation, inside_area, moves_forward, validate_final_path

LOGGER = logging.getLogger("fortsmart_precision.obstacles")

NO_CONFLICT = "NO_CONFLICT"
DETOURED = "DETOURED"

# Folga para a linha mais interna da plantadeira nao formar laco na curva.
ROW_LOOP_MARGIN_M = 0.25
DISTANCE_FACTORS = (1.0, 1.5, 2.0)
FORWARD_MIN_DOT = 0.05
SAFE_ZONE_SHRINK_M = 0.02
CURVATURE_WEIGHT = 0.1
BOUNDARY_WEIGHT = 10.0
OBSTACLE_WEIGHT = 5.0
ONE_SIDED_TOLERANCE_M = 0.01

Coord = tuple[float, float]


@dataclass(frozen=True)
class DetourSection:
    group_id: str
    obstacle_ids: tuple[str, ...]
    side: DetourSide
    s_start: float
    s_end: float
    s_entry: float
    s_exit: float
    transition_in: tuple[Coord, ...]
    contour: tuple[Coord, ...]
    transition_out: tuple[Coord, ...]
    minimum_radius: float
    cost: float
    approach_used: float
    return_used: float

    @property
    def coords(self) -> list[Coord]:
        coords: list[Coord] = []
        for part in (self.transition_in, self.contour, self.transition_out):
            for xy in part:
                if not coords or math.dist(coords[-1], xy) > GEOMETRY_EPSILON:
                    coords.append(xy)
        return coords

    @property
    def pre_entry(self) -> Coord:
        return self.transition_in[0]

    @property
    def post_exit(self) -> Coord:
        return self.transition_out[-1]

    @property
    def length(self) -> float:
        return LineString(self.coords).length


@dataclass(frozen=True)
class LateralDetourResult:
    status: str
    original_path: LineString
    final_path: LineString | None
    sections: tuple[DetourSection, ...]
    validation: DetourValidation | None
    work_segments: tuple[tuple[str, LineString], ...]
    envelope: MachineEnvelope
    required_radius: float
    contour_radius: float
    groups: tuple[ObstacleGroup, ...] = ()
    safe_zones: BaseGeometry | None = None
    reason: str = ""
    log: tuple[dict, ...] = field(default_factory=tuple)

    @property
    def valid(self) -> bool:
        if self.status == NO_CONFLICT:
            return True
        return self.status == DETOURED and self.validation is not None and self.validation.valid

    def events(self) -> list[dict]:
        """Pontos WORK_OFF (antes do desvio) e WORK_ON (depois)."""
        result = []
        for state, line in self.work_segments:
            if state == WORK_OFF:
                result.append({"event": WORK_OFF, "point": line.coords[0]})
                result.append({"event": WORK_ON, "point": line.coords[-1]})
        return result


@dataclass
class _Context:
    path: LineString
    config: ObstacleConfig
    envelope: MachineEnvelope
    required_radius: float
    contour_radius: float
    allowed_area: BaseGeometry | None
    allowed_prepared: object | None
    groups: list[ObstacleGroup]
    distance_factors: tuple[float, ...] = DISTANCE_FACTORS
    one_sided: bool = False


def required_turn_radius(config: ObstacleConfig) -> float:
    """Raio minimo efetivo: o da maquina ou o que evita laco na linha interna."""
    return max(float(config.minimum_turn_radius), config.half_machine + ROW_LOOP_MARGIN_M)


def contour_radius_for(config: ObstacleConfig, required_radius: float) -> float:
    if config.contour_strategy == ContourStrategy.CONVEX_TIGHT:
        return config.clearance
    return max(config.clearance, required_radius)


def _clean_path(path: LineString) -> LineString:
    coords: list[Coord] = []
    for xy in path.coords:
        point = (float(xy[0]), float(xy[1]))
        if not coords or math.dist(coords[-1], point) > GEOMETRY_EPSILON:
            coords.append(point)
    if len(coords) < 2:
        raise ValueError("Trajetoria mestra precisa de pelo menos dois pontos distintos.")
    return LineString(coords)


def _vertex_tangent(coords: np.ndarray, index: int) -> Coord:
    delta = coords[index + 1] - coords[index - 1]
    return unit(float(delta[0]), float(delta[1]))


def _forward_run(ctx: _Context, coords: np.ndarray, first: int, last: int) -> tuple[int, int] | None:
    """Maior sequencia de vertices do arco cujo sentido acompanha o trabalho."""
    best: tuple[int, int] | None = None
    run_start: int | None = None
    for index in range(first, last + 2):
        forward = False
        if index <= last:
            tangent = _vertex_tangent(coords, index)
            station = ctx.path.project(Point(coords[index]))
            direction = path_tangent(ctx.path, station)
            forward = tangent[0] * direction[0] + tangent[1] * direction[1] > FORWARD_MIN_DOT
        if forward and run_start is None:
            run_start = index
        elif not forward and run_start is not None:
            if best is None or index - 1 - run_start > best[1] - best[0]:
                best = (run_start, index - 1)
            run_start = None
    return best


def crosses_to_other_side(path: LineString, coords, side: DetourSide, tolerance: float = ONE_SIDED_TOLERANCE_M) -> bool:
    """True se algum ponto fica do lado oposto ao desvio (contra-esterco/bigode)."""
    arr = np.asarray(coords, dtype=float)
    if len(arr) == 0:
        return False
    length = path.length
    stations = shapely.line_locate_point(path, shapely.points(arr))
    feet = shapely.get_coordinates(shapely.line_interpolate_point(path, stations))
    ahead = shapely.get_coordinates(shapely.line_interpolate_point(path, np.minimum(stations + 0.5, length)))
    behind = shapely.get_coordinates(shapely.line_interpolate_point(path, np.maximum(stations - 0.5, 0.0)))
    tangent = ahead - behind
    norm = np.hypot(tangent[:, 0], tangent[:, 1])
    norm[norm <= 1e-12] = 1.0
    cross = (tangent[:, 0] * (arr[:, 1] - feet[:, 1]) - tangent[:, 1] * (arr[:, 0] - feet[:, 0])) / norm
    sign = 1.0 if side == DetourSide.LEFT else -1.0
    return bool(np.any(sign * cross < -tolerance))


def _transition_ok(ctx: _Context, coords: list[Coord], safe_inner, side: DetourSide | None = None) -> bool:
    if not validate_turn_radius(coords, ctx.required_radius):
        return False
    if ctx.one_sided and side is not None and crosses_to_other_side(ctx.path, coords, side):
        return False
    line = LineString(coords)
    if safe_inner is not None and safe_inner.intersects(line):
        return False
    if not moves_forward(ctx.path, coords):
        return False
    if ctx.allowed_prepared is not None and not ctx.allowed_prepared.covers(line):
        return False
    return True


def _section_cost(ctx: _Context, coords: list[Coord], s_start: float, s_end: float, group: ObstacleGroup) -> float:
    line = LineString(coords)
    excess = max(0.0, line.length - (s_end - s_start))
    curvature = total_heading_change(coords) * ctx.required_radius
    boundary = 0.0
    if ctx.allowed_area is not None and ctx.envelope.half_machine > 0:
        swath = line.buffer(ctx.envelope.half_machine, cap_style="flat")
        boundary = swath.difference(ctx.allowed_area).area / ctx.envelope.machine_width
    obstacle = 0.0
    limit = ctx.config.clearance + ctx.config.safety_margin
    for other in ctx.groups:
        if other.group_id == group.group_id or set(other.obstacle_ids) & set(group.obstacle_ids):
            continue
        distance = line.distance(other.core)
        if distance < limit:
            obstacle += limit - distance
    return excess + CURVATURE_WEIGHT * curvature + BOUNDARY_WEIGHT * boundary + OBSTACLE_WEIGHT * obstacle


def _blocking_groups(ctx: _Context, line: LineString, group: ObstacleGroup) -> list[ObstacleGroup]:
    own = set(group.obstacle_ids)
    return [
        other
        for other in ctx.groups
        if not (set(other.obstacle_ids) & own) and line.intersects(other.safe_zone)
    ]


def _build_side_candidate(
    ctx: _Context,
    group: ObstacleGroup,
    side: DetourSide,
    s_in: float,
    s_out: float,
    approach: float,
    ret: float,
    lower: float,
) -> tuple[DetourSection | None, str, list[ObstacleGroup]]:
    path = ctx.path
    contour = contour_polygon(group.core, ctx.contour_radius)
    s_start = calculate_pre_entry_point(path, s_in, approach, lower)
    s_end = calculate_post_exit_point(path, s_out, ret)
    pre = path.interpolate(s_start)
    post = path.interpolate(s_end)
    u_pre = path_tangent(path, s_start)
    u_post = path_tangent(path, s_end)

    ring = oriented_ring(contour, side)
    ring2 = doubled_ring(ring)
    coords = np.asarray(ring2.coords)
    cumulative = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(coords, axis=0).T))])
    p_in, span = arc_span(ring, path.interpolate(s_in), path.interpolate(s_out))
    inside = np.nonzero((cumulative > p_in + GEOMETRY_EPSILON) & (cumulative < p_in + span - GEOMETRY_EPSILON))[0]
    if len(inside) == 0:
        return None, "arco de contorno vazio", []
    run = _forward_run(ctx, coords, int(inside[0]), int(inside[-1]))
    if run is None:
        return None, "contorno sem trecho no sentido do trabalho", []
    first, last = run

    safe_inner = prep(group.safe_zone.buffer(-SAFE_ZONE_SHRINK_M))
    entry: tuple[int, list[Coord]] | None = None
    for index in range(first, last + 1):
        vertex = (float(coords[index][0]), float(coords[index][1]))
        tangent = _vertex_tangent(coords, index)
        following = (float(coords[index + 1][0]), float(coords[index + 1][1]))
        for alpha in TRANSITION_ALPHAS:
            curve = build_entry_transition((pre.x, pre.y), u_pre, vertex, tangent, alpha)
            if _transition_ok(ctx, curve + [following], safe_inner, side):
                entry = (index, curve)
                break
        if entry:
            break
    if entry is None:
        return None, "transicao de entrada nao respeita raio/folga", []

    exit_: tuple[int, list[Coord]] | None = None
    for index in range(last, entry[0] - 1, -1):
        vertex = (float(coords[index][0]), float(coords[index][1]))
        tangent = _vertex_tangent(coords, index)
        previous = (float(coords[index - 1][0]), float(coords[index - 1][1]))
        for alpha in TRANSITION_ALPHAS:
            curve = build_exit_transition(vertex, tangent, (post.x, post.y), u_post, alpha)
            if _transition_ok(ctx, [previous] + curve, safe_inner, side):
                exit_ = (index, curve)
                break
        if exit_:
            break
    if exit_ is None:
        return None, "transicao de saida nao respeita raio/folga", []

    arc = [(float(x), float(y)) for x, y in coords[entry[0] : exit_[0] + 1]]
    section = DetourSection(
        group_id=group.group_id,
        obstacle_ids=group.obstacle_ids,
        side=side,
        s_start=s_start,
        s_end=s_end,
        s_entry=s_in,
        s_exit=s_out,
        transition_in=tuple(entry[1]),
        contour=tuple(arc),
        transition_out=tuple(exit_[1]),
        minimum_radius=0.0,
        cost=0.0,
        approach_used=approach,
        return_used=ret,
    )
    detour = section.coords
    line = LineString(detour)
    radius = minimum_radius(detour)
    if not validate_turn_radius(detour, ctx.required_radius):
        return None, f"raio {radius:.2f} m abaixo do minimo {ctx.required_radius:.2f} m", []
    if not line.is_simple or not moves_forward(path, detour):
        return None, "desvio com laco ou movimento para tras", []
    if line.distance(group.core) < ctx.config.clearance - SAFE_ZONE_SHRINK_M - GEOMETRY_EPSILON:
        return None, "desvio invade a zona segura do obstaculo", []
    if not inside_area(line, ctx.allowed_area):
        return None, "desvio sai da area permitida", []
    blocking = _blocking_groups(ctx, line, group)
    if blocking:
        return None, "desvio atinge outro obstaculo", blocking
    cost = _section_cost(ctx, detour, s_start, s_end, group)
    return (
        DetourSection(**{**section.__dict__, "minimum_radius": radius, "cost": cost}),
        "",
        [],
    )


def choose_detour_side(candidates: dict[DetourSide, DetourSection]) -> DetourSection | None:
    """Menor custo entre os lados validos; empate favorece a esquerda."""
    order = [DetourSide.LEFT, DetourSide.RIGHT]
    valid = [candidates[side] for side in order if candidates.get(side) is not None]
    if not valid:
        return None
    return min(valid, key=lambda section: section.cost)


def _solve_group(ctx: _Context, group: ObstacleGroup, lower: float) -> tuple[DetourSection | None, str, list[ObstacleGroup]]:
    contour = contour_polygon(group.core, ctx.contour_radius)
    stations = find_entry_exit_points(ctx.path, contour)
    if stations is None:
        return None, "trajetoria comeca/termina dentro do contorno do obstaculo", []
    s_in, s_out = stations
    if s_in <= lower + GEOMETRY_EPSILON:
        return None, "sem espaco entre desvios consecutivos", []
    side_option = ctx.config.detour_side
    sides = [DetourSide.LEFT, DetourSide.RIGHT] if side_option == DetourSide.AUTO else [side_option]
    candidates: dict[DetourSide, DetourSection] = {}
    reasons: list[str] = []
    blocking: dict[str, ObstacleGroup] = {}
    for side in sides:
        for factor in ctx.distance_factors:
            section, reason, blockers = _build_side_candidate(
                ctx,
                group,
                side,
                s_in,
                s_out,
                ctx.config.approach_distance * factor,
                ctx.config.return_distance * factor,
                lower,
            )
            if section is not None:
                candidates[side] = section
                break
            if reason:
                reasons.append(f"{side.value}: {reason}")
            for blocker in blockers:
                blocking[blocker.group_id] = blocker
    chosen = choose_detour_side(candidates)
    if chosen is not None:
        return chosen, "", []
    unique = list(dict.fromkeys(reasons))
    return None, "; ".join(unique) or "nenhum lado viavel", list(blocking.values())


def _log_entry(config: ObstacleConfig, ctx: _Context, group: ObstacleGroup, section: DetourSection | None, status: str, reason: str = "") -> dict:
    entry = {
        "obstacle_id": ",".join(group.obstacle_ids),
        "group_id": group.group_id,
        "strategy": ObstacleHandlingStrategy.LATERAL_DETOUR.value,
        "machine_width": round(config.machine_width, 3),
        "safety_margin": config.safety_margin,
        "entry_point": None,
        "exit_point": None,
        "side": None,
        "minimum_radius": None,
        "required_radius": round(ctx.required_radius, 3),
        "status": status,
        "fallback_used": False,
        "reason": reason,
    }
    if section is not None:
        entry.update(
            entry_point=[round(v, 3) for v in section.pre_entry],
            exit_point=[round(v, 3) for v in section.post_exit],
            side=section.side.value,
            minimum_radius=round(section.minimum_radius, 3) if math.isfinite(section.minimum_radius) else None,
        )
    return entry


def create_lateral_detour(
    master_path: LineString,
    obstacles: list[tuple[str, BaseGeometry]],
    config: ObstacleConfig,
    *,
    allowed_area: BaseGeometry | None = None,
    distance_factors: tuple[float, ...] = DISTANCE_FACTORS,
    one_sided_transitions: bool = False,
) -> LateralDetourResult:
    """Desvia a trajetoria mestra dos obstaculos que conflitam com o envelope.

    `distance_factors` multiplica aproximacao/retorno ate achar transicao valida;
    `(1.0,)` usa exatamente as distancias informadas (desvio manual).
    `one_sided_transitions` rejeita transicoes que cruzam para o lado oposto.
    """
    config.validate()
    path = _clean_path(master_path)
    envelope = calculate_machine_envelope(config.row_count, config.row_spacing, config.safety_margin)
    required = required_turn_radius(config)
    rho = contour_radius_for(config, required)
    cores = [(str(obstacle_id), obstacle_core(geometry, config.obstacle_radius)) for obstacle_id, geometry in obstacles]
    all_groups = group_obstacles(cores, envelope.clearance)
    core_union = unary_union([core for _id, core in cores]) if cores else None
    safe_union = unary_union([group.safe_zone for group in all_groups]) if all_groups else None

    ctx = _Context(
        path=path,
        config=config,
        envelope=envelope,
        required_radius=required,
        contour_radius=rho,
        allowed_area=allowed_area,
        allowed_prepared=prep(allowed_area.buffer(GEOMETRY_EPSILON)) if allowed_area is not None else None,
        groups=list(all_groups),
        distance_factors=tuple(distance_factors),
        one_sided=one_sided_transitions,
    )

    def result(status, final, sections, validation, segments, groups, reason="", log=()):
        return LateralDetourResult(
            status=status,
            original_path=path,
            final_path=final,
            sections=tuple(sections),
            validation=validation,
            work_segments=tuple(segments),
            envelope=envelope,
            required_radius=required,
            contour_radius=rho,
            groups=tuple(groups),
            safe_zones=safe_union,
            reason=reason,
            log=tuple(log),
        )

    conflicting = [group for group in all_groups if detect_obstacle_conflict(path, group.safe_zone)]
    if not conflicting:
        return result(NO_CONFLICT, path, [], None, [(WORK_ON, path)], [])

    pending = list(conflicting)
    max_merges = len(all_groups) + 2
    merges = 0
    while True:
        ctx.groups = _current_groups(all_groups, pending)
        ordered = _order_groups(ctx, pending)
        sections: list[DetourSection] = []
        log: list[dict] = []
        failure: tuple[int, str, list[ObstacleGroup]] | None = None
        for index, group in enumerate(ordered):
            lower = sections[-1].s_end if sections else 0.0
            section, reason, blockers = _solve_group(ctx, group, lower)
            if section is None:
                failure = (index, reason, blockers)
                break
            sections.append(section)
            log.append(_log_entry(config, ctx, group, section, DETOURED))
        if failure is None:
            break
        index, reason, blockers = failure
        to_merge = {group.group_id: group for group in blockers}
        if index > 0 and not blockers:
            previous = ordered[index - 1]
            to_merge[previous.group_id] = previous
        failed = ordered[index]
        if not to_merge or merges >= max_merges:
            log.append(_log_entry(config, ctx, failed, None, DETOUR_NOT_FEASIBLE, reason))
            LOGGER.warning("Desvio lateral inviavel (%s): %s", ",".join(failed.obstacle_ids), reason)
            return result(DETOUR_NOT_FEASIBLE, None, [], None, [], ordered, reason, log)
        merges += 1
        merged = merge_groups([failed, *to_merge.values()])
        absorbed = {failed.group_id, *to_merge}
        pending = [group for group in pending if group.group_id not in absorbed] + [merged]

    final = stitch_local_detour(path, sections)
    validation = validate_final_path(
        path,
        final,
        sections,
        core_union,
        half_machine=envelope.half_machine,
        safety_margin=config.safety_margin,
        required_radius=required,
        allowed_area=allowed_area,
    )
    if not validation.valid:
        reason = "; ".join(validation.errors)
        for entry in log:
            entry["status"] = DETOUR_NOT_FEASIBLE
            entry["reason"] = reason
        LOGGER.warning("Desvio lateral reprovado na validacao: %s", reason)
        return result(DETOUR_NOT_FEASIBLE, None, sections, validation, [], ordered, reason, log)

    segments = split_work_segments(path, sections, config.planting_during_detour)
    for entry in log:
        LOGGER.info("Desvio lateral: %s", entry)
    return result(DETOURED, final, sections, validation, segments, ordered, "", log)


def _current_groups(all_groups: list[ObstacleGroup], pending: list[ObstacleGroup]) -> list[ObstacleGroup]:
    """Grupos pendentes (inclusive fundidos) mais os que nao conflitam."""
    used = {obstacle_id for group in pending for obstacle_id in group.obstacle_ids}
    others = [group for group in all_groups if not set(group.obstacle_ids) & used]
    return list(pending) + others


def _order_groups(ctx: _Context, groups: list[ObstacleGroup]) -> list[ObstacleGroup]:
    def key(group: ObstacleGroup) -> float:
        stations = find_entry_exit_points(ctx.path, contour_polygon(group.core, ctx.contour_radius))
        if stations is None:
            return ctx.path.project(group.core.centroid)
        return stations[0]

    return sorted(groups, key=key)
