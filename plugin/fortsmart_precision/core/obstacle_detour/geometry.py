# -*- coding: utf-8 -*-
"""Desvio manual de UMA linha ao redor de UM obstaculo (CRS metrico).

Reaproveita os motores existentes:
- LATERAL_LEFT/RIGHT -> core.lateral_detour.create_lateral_detour com lado
  forcado e antecipacao/retorno exatos (sem fatores automaticos);
- CUT_RESUME -> core.longitudinal_cut_engine.compute_longitudinal_cut.

Modelo da maquina: a linha e o rastro da plantadeira (ponto de operacao). A
zona de seguranca vale para a barra inteira (raio + margem + meia largura no
centro). A plantadeira segue o mesmo rastro do trator, entao a distancia
trator -> implemento nao muda a geometria: desloca a posicao do trator em cada
evento da manobra (o trator chega antes ao ponto de inicio).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import replace
from typing import Iterable

from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import substring

from ...domain.obstacle_strategy import (
    DetourSide,
    ObstacleConfig,
    ObstacleConfigError,
    ObstacleHandlingStrategy,
)
from ...domain.operation_simulation import MachineWorkGeometry, WorkState
from ..lateral_detour.clearance import obstacle_core
from ..lateral_detour.engine import DETOURED, NO_CONFLICT, create_lateral_detour
from ..longitudinal_cut_engine import (
    LongitudinalCutError,
    ObstacleInput,
    build_obstacle_zones,
    compute_longitudinal_cut,
    fill_closed_rings,
)
from .models import (
    MSG_ENDPOINT_INSIDE,
    MSG_FIELD_NOT_CHECKED,
    MSG_INVALID_GEOMETRY,
    MSG_NO_CONFLICT,
    MSG_NO_TRANSITION,
    Coord,
    DetourParameters,
    DetourStatus,
    DetourType,
    LineDirection,
    NearbyObstacle,
    ObstacleDetour,
)
from .validation import surroundings_warnings, validate_cut, validate_lateral

LOGGER = logging.getLogger("fortsmart_precision.obstacle_detour")

EXACT_DISTANCES = (1.0,)
# Raio de curva "sem restricao": prevalece meia largura + folga da linha interna.
UNRESTRICTED_TURN_RADIUS_M = 1e-3
MIN_PART_LENGTH_M = 1e-3
SUGGESTION_STEPS_M = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 15.0, 20.0, 25.0, 30.0, 40.0)


def _flat_line(geometry: BaseGeometry) -> LineString:
    return LineString([(float(x), float(y)) for x, y, *_rest in geometry.coords])


def line_parts(geometry: BaseGeometry) -> list[LineString]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [_flat_line(geometry)]
    if isinstance(geometry, MultiLineString):
        return [_flat_line(part) for part in geometry.geoms if not part.is_empty]
    raise ValueError("A linha de plantio precisa ser LineString ou MultiLineString.")


def obstacle_geometry(geometry: BaseGeometry) -> BaseGeometry:
    """Linha fechada vira area; ponto/linha aberta continuam (raio vem do operador)."""
    if geometry is None or geometry.is_empty:
        raise ValueError("Obstáculo sem geometria.")
    return fill_closed_rings(geometry)


def physical_core(geometry: BaseGeometry, radius_m: float) -> BaseGeometry:
    return obstacle_core(obstacle_geometry(geometry), radius_m)


def safety_zone(geometry: BaseGeometry, params: DetourParameters) -> BaseGeometry:
    """Zona = obstaculo + raio + margem (nunca largura/espacamento)."""
    core = physical_core(geometry, params.obstacle_radius_m)
    return core.buffer(params.safety_margin_m, quad_segs=32) if params.safety_margin_m > 0 else core


def _xy(point: Point) -> Coord:
    return (float(point.x), float(point.y))


def _travel(line: LineString, direction: LineDirection) -> LineString:
    """Sentido de deslocamento <-> sentido gravado (a inversao e simetrica)."""
    return line if direction is LineDirection.A_TO_B else LineString(list(line.coords)[::-1])


def _stored_station(station: float | None, length: float, direction: LineDirection) -> float | None:
    if station is None:
        return None
    return station if direction is LineDirection.A_TO_B else length - station


def _assemble(parts: list[LineString]) -> BaseGeometry:
    if len(parts) == 1:
        return parts[0]
    return MultiLineString([list(part.coords) for part in parts])


def _new_id() -> str:
    return "DV-" + uuid.uuid4().hex[:10].upper()


def lateral_config(params: DetourParameters, side: DetourSide, anticipation: float, ret: float) -> ObstacleConfig:
    return ObstacleConfig(
        strategy=ObstacleHandlingStrategy.LATERAL_DETOUR,
        row_count=1,
        row_spacing=params.implement_width_m,
        safety_margin=params.safety_margin_m,
        obstacle_radius=params.obstacle_radius_m,
        approach_distance=anticipation,
        return_distance=ret,
        minimum_turn_radius=params.minimum_turn_radius_m or UNRESTRICTED_TURN_RADIUS_M,
        detour_side=side,
        allow_fallback=False,
        generate_rows=False,
    )


def build_manual_detour(
    line: BaseGeometry,
    obstacle: BaseGeometry,
    params: DetourParameters,
    *,
    line_id: str,
    obstacle_id: str,
    detour_id: str | None = None,
    nearby_obstacles: Iterable[NearbyObstacle] = (),
    field_area: BaseGeometry | None = None,
) -> ObstacleDetour:
    """Calcula o desvio de uma linha por um obstaculo; nao altera dados.

    `nearby_obstacles` e `field_area` so geram avisos sobre o trecho novo: o
    desvio continua usando apenas o obstaculo escolhido.
    """
    detour_id = detour_id or _new_id()
    parts = line_parts(line)
    base = _assemble(parts) if parts else line
    zone = safety_zone(obstacle, params) if obstacle is not None and not obstacle.is_empty else None

    def failed(*messages: str, clearance=None) -> ObstacleDetour:
        result = ObstacleDetour(
            detour_id, line_id, obstacle_id, params, DetourStatus.FAILED, base, None,
            zone, clearance, messages=tuple(messages),
        )
        LOGGER.info(detour_debug_text(result))
        return result

    errors = params.errors()
    if not parts:
        errors.insert(0, "Selecione uma linha de plantio.")
    if zone is None:
        errors.insert(0, "Selecione um obstáculo.")
    if errors:
        return failed(*errors)

    clearance = zone.buffer(params.half_width_m, quad_segs=32)
    index = min(range(len(parts)), key=lambda i: parts[i].distance(zone))
    target = parts[index]
    travel = _travel(target, params.direction)
    if not travel.intersects(clearance):
        result = ObstacleDetour(
            detour_id, line_id, obstacle_id, params, DetourStatus.NO_CONFLICT, base, base,
            zone, clearance, messages=(MSG_NO_CONFLICT,),
        )
        LOGGER.info(detour_debug_text(result))
        return result

    if params.detour_type is DetourType.CUT_RESUME:
        computed = _cut_resume(travel, obstacle, obstacle_id, params, zone)
    else:
        computed = _lateral(travel, obstacle, obstacle_id, params)
    if isinstance(computed, tuple) and computed and isinstance(computed[0], str):
        return failed(*computed, clearance=clearance)

    new_parts, info = computed
    stored_new = [_travel(part, params.direction) for part in new_parts]
    if params.direction is LineDirection.B_TO_A:
        stored_new.reverse()
    final_parts = parts[:index] + stored_new + parts[index + 1 :]
    length = target.length
    status = DetourStatus.NO_CONFLICT if MSG_NO_CONFLICT in info.get("messages", ()) else DetourStatus.OK
    changed = info.get("changed")
    messages = list(info.get("messages", ()))
    warnings: list[str] = []
    if changed is not None:
        zones = nearby_zones(nearby_obstacles, params, exclude_id=obstacle_id)
        warnings = surroundings_warnings(changed, params.half_width_m, zones, field_area, travel)
        if field_area is None:
            messages.append(MSG_FIELD_NOT_CHECKED)
    result = ObstacleDetour(
        detour_id=detour_id,
        line_id=line_id,
        obstacle_id=obstacle_id,
        parameters=params,
        status=status,
        original_geometry=base,
        result_geometry=_assemble(final_parts),
        safety_zone=zone,
        clearance_zone=clearance,
        side=info.get("side", ""),
        control_points=tuple(info.get("control_points", ())),
        conflict_entry_station_m=_stored_station(info.get("entry"), length, params.direction),
        conflict_exit_station_m=_stored_station(info.get("exit"), length, params.direction),
        maneuver_start_station_m=_stored_station(info.get("start"), length, params.direction),
        maneuver_end_station_m=_stored_station(info.get("end"), length, params.direction),
        implement_start_xy=info.get("implement_start"),
        implement_end_xy=info.get("implement_end"),
        tractor_start_xy=info.get("tractor_start"),
        tractor_end_xy=info.get("tractor_end"),
        messages=tuple(messages),
        changed_geometry=changed,
        warnings=tuple(warnings),
    )
    LOGGER.info(detour_debug_text(result))
    return result


def nearby_zones(
    nearby: Iterable[NearbyObstacle], params: DetourParameters, *, exclude_id: str | None = None
) -> list[tuple[str, BaseGeometry]]:
    """Zona (raio + margem) de cada outro obstaculo; area sem raio usa o proprio contorno."""
    zones = []
    for item in nearby:
        if item.obstacle_id == exclude_id or item.geometry is None or item.geometry.is_empty:
            continue
        geometry = obstacle_geometry(item.geometry)
        radius = item.radius_m
        if radius is None:
            radius = 0.0 if geometry.area > 0 else params.obstacle_radius_m
        zones.append((item.obstacle_id, safety_zone(geometry, replace(params, obstacle_radius_m=radius))))
    return zones


def _lateral(travel: LineString, obstacle: BaseGeometry, obstacle_id: str, params: DetourParameters):
    side = DetourSide.LEFT if params.detour_type is DetourType.LATERAL_LEFT else DetourSide.RIGHT
    config = lateral_config(
        params, side, params.longitudinal_anticipation_m, params.longitudinal_return_m
    )
    try:
        result = create_lateral_detour(
            travel,
            [(obstacle_id, obstacle_geometry(obstacle))],
            config,
            distance_factors=EXACT_DISTANCES,
            one_sided_transitions=True,
        )
    except (ObstacleConfigError, ValueError) as exc:
        return (MSG_INVALID_GEOMETRY, str(exc))
    if result.status == NO_CONFLICT:
        return ([travel], {"messages": (MSG_NO_CONFLICT,)})
    if result.status != DETOURED or result.final_path is None or not result.sections:
        reason = result.reason or "nenhuma transição viável"
        if "dentro do contorno" in reason:
            return (MSG_ENDPOINT_INSIDE, reason)
        return (MSG_NO_TRANSITION, reason)

    section = result.sections[0]
    final = result.final_path
    core = physical_core(obstacle, params.obstacle_radius_m)
    problems = validate_lateral(
        travel,
        final,
        section.coords,
        core,
        centerline_clearance_m=params.centerline_clearance_m,
        side=side.value.upper(),
    )
    if problems:
        return tuple(problems)

    d = params.tractor_to_implement_m
    end_on_final = final.length - (travel.length - section.s_end)
    info = {
        "side": side.value.upper(),
        "entry": section.s_entry,
        "exit": section.s_exit,
        "start": section.s_start,
        "end": section.s_end,
        "control_points": (
            section.pre_entry,
            section.contour[0],
            section.contour[-1],
            section.post_exit,
        ),
        "implement_start": section.pre_entry,
        "implement_end": section.post_exit,
        "tractor_start": _xy(final.interpolate(min(final.length, section.s_start + d))),
        "tractor_end": _xy(final.interpolate(min(final.length, end_on_final + d))),
        "messages": _clamp_messages(section.s_start, section.s_entry, params, travel.length, section.s_end, section.s_exit),
        "changed": substring(final, section.s_start, end_on_final),
    }
    return ([final], info)


def _clamp_messages(start, entry, params, length, end, exit_station) -> tuple[str, ...]:
    messages = []
    if entry - start < params.longitudinal_anticipation_m - 1e-6:
        messages.append(f"Antecipação limitada ao início da linha ({entry - start:.2f} m).")
    if end - exit_station < params.longitudinal_return_m - 1e-6:
        messages.append(f"Retorno limitado ao fim da linha ({end - exit_station:.2f} m).")
    return tuple(messages)


def _cut_resume(
    travel: LineString, obstacle: BaseGeometry, obstacle_id: str, params: DetourParameters, zone: BaseGeometry
):
    geometry = MachineWorkGeometry(
        work_width_m=params.implement_width_m,
        reference_to_working_line_longitudinal_m=0.0,
        longitudinal_anticipation_m=params.longitudinal_anticipation_m,
    )
    try:
        zones = build_obstacle_zones(
            [ObstacleInput(obstacle_id, obstacle_geometry(obstacle), params.obstacle_radius_m)],
            params.safety_margin_m,
            allow_zero_area=True,
        )
        cut = compute_longitudinal_cut("MANUAL", list(travel.coords), zones, geometry)
    except (LongitudinalCutError, ValueError) as exc:
        return (MSG_INVALID_GEOMETRY, str(exc))
    raised = [item for item in cut.intervals if item.state is WorkState.RAISED]
    if not raised:
        return ([travel], {"messages": (MSG_NO_CONFLICT,)})

    length = travel.length
    off = raised[0].start_station_m
    entry = raised[0].zone_entry_station_m if raised[0].zone_entry_station_m is not None else off
    exit_station = raised[-1].end_station_m
    on = min(length, exit_station + params.longitudinal_return_m)
    pieces = []
    if off > MIN_PART_LENGTH_M:
        pieces.append(substring(travel, 0.0, off))
    if length - on > MIN_PART_LENGTH_M:
        pieces.append(substring(travel, on, length))
    if not pieces:
        return ("O corte eliminaria a linha inteira.",)
    problems = validate_cut(pieces, zone, params.half_width_m)
    if problems:
        return tuple(problems)

    d = params.tractor_to_implement_m
    off_xy = _xy(travel.interpolate(off))
    on_xy = _xy(travel.interpolate(on))
    messages = list(_clamp_messages(off, entry, params, length, on, exit_station))
    if off + d > length or on + d > length:
        messages.append("Trator além do fim da linha em algum evento (posição limitada ao fim).")
    info = {
        "side": "",
        "entry": entry,
        "exit": exit_station,
        "start": off,
        "end": on,
        "control_points": (off_xy, on_xy),
        "implement_start": off_xy,
        "implement_end": on_xy,
        "tractor_start": _xy(travel.interpolate(min(length, off + d))),
        "tractor_end": _xy(travel.interpolate(min(length, on + d))),
        "messages": tuple(messages),
    }
    return (pieces, info)


def suggest_lateral_distances(
    line: BaseGeometry, obstacle: BaseGeometry, params: DetourParameters, *, obstacle_id: str = "OBS"
) -> tuple[float, float] | None:
    """Menores antecipacao/retorno (>= os informados) com desvio lateral valido.

    So sugere: o desvio aplicado sempre usa os valores do operador.
    """
    if params.detour_type not in (DetourType.LATERAL_LEFT, DetourType.LATERAL_RIGHT) or params.errors():
        return None
    for step in SUGGESTION_STEPS_M:
        anticipation = max(params.longitudinal_anticipation_m, step)
        ret = max(params.longitudinal_return_m, step)
        if anticipation == params.longitudinal_anticipation_m and ret == params.longitudinal_return_m:
            continue
        candidate = replace(params, longitudinal_anticipation_m=anticipation, longitudinal_return_m=ret)
        previous = LOGGER.disabled
        LOGGER.disabled = True
        try:
            result = build_manual_detour(line, obstacle, candidate, line_id="", obstacle_id=obstacle_id)
        finally:
            LOGGER.disabled = previous
        if result.ok:
            return anticipation, ret
    return None


def detour_debug_text(detour: ObstacleDetour) -> str:
    params = detour.parameters

    def m(value: float | None) -> str:
        return "-" if value is None else f"{value:.2f} m"

    result = detour.status.value
    if detour.messages:
        result += " | " + " | ".join(detour.messages)
    return "\n".join((
        "=== FORTSMART OBSTACLE DETOUR ===",
        f"DETOUR: {detour.detour_id}",
        f"LINE: {detour.line_id}",
        f"OBSTACLE: {detour.obstacle_id}",
        f"TYPE: {params.detour_type.value}",
        f"SIDE: {detour.side or '-'}",
        f"OBSTACLE RADIUS: {m(params.obstacle_radius_m)}",
        f"SAFETY MARGIN: {m(params.safety_margin_m)}",
        f"SAFETY RADIUS: {m(params.safety_radius_m)} (raio + margem)",
        f"IMPLEMENT WIDTH: {m(params.implement_width_m)} (folga do centro = margem + meia largura)",
        f"ANTICIPATION: {m(params.longitudinal_anticipation_m)}",
        f"RETURN: {m(params.longitudinal_return_m)}",
        f"REFERENCE → OPERATION: {m(params.reference_to_operation_m)} (implemento atrás do trator)",
        f"LINE DIRECTION: {params.direction.value}",
        f"CONFLICT: {m(detour.conflict_entry_station_m)} → {m(detour.conflict_exit_station_m)}",
        f"MANEUVER: {m(detour.maneuver_start_station_m)} → {m(detour.maneuver_end_station_m)}",
        f"WARNINGS: {' | '.join(detour.warnings) if detour.warnings else '-'}",
        f"RESULT: {result}",
    ))
