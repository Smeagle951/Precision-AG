# -*- coding: utf-8 -*-
"""Desvio de obstaculos para pulverizacao (envelope da barra)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import uuid4

from ..domain.avoidance_configuration import AvoidanceConfiguration, AvoidanceMode
from ..domain.machine_model import MachineProfile
from ..domain.obstacle_model import Obstacle
from .guidance_engine import TrafficPass
from .line_geometry import (
    MultiPolygon,
    Point,
    Segment,
    decimate_polyline,
    distance,
    point_at_segment_t,
    sub,
)
from .obstacle_buffer_engine import (
    ObstacleSafetyEnvelope,
    build_all_envelopes,
    envelope_hits_segment,
)
from .obstacle_contour_path import (
    contour_path_around_polygon,
    polyline_envelope_hit_range,
    stitch_avoidance_into_polyline,
)
from .obstacle_grouping_engine import merge_adjacent_envelopes
from .spatial_index import UniformGridIndex, build_envelope_index


class AvoidanceAction(str, Enum):
    NORMAL = "normal"
    AVOID = "avoid"
    RING = "ring"
    CONTOUR = "contour"
    LATERAL = "lateral"


class ApplicationObstacleEngineError(ValueError):
    """Erro no motor de desvio de aplicacao."""


@dataclass(frozen=True)
class AvoidedPath:
    fs_id: str
    source_id: str
    pass_id: int
    row_id: int | None
    operation_id: str
    machine_id: str
    original_segment: Segment
    modified_points: tuple[Point, ...]
    entry_point: Point | None
    exit_point: Point | None
    obstacle_id: str
    application_radius_m: float
    action: str
    returns_to_guidance: bool

    @property
    def guidance_segment(self) -> Segment:
        if len(self.modified_points) < 2:
            return self.original_segment
        return Segment(self.modified_points[0], self.modified_points[-1])

    def attributes(self) -> dict[str, object]:
        return {
            "fs_id": self.fs_id,
            "source_id": self.source_id,
            "pass_id": self.pass_id,
            "row_id": self.row_id,
            "operation_id": self.operation_id,
            "machine_id": self.machine_id,
            "obstacle_id": self.obstacle_id,
            "application_radius_m": self.application_radius_m,
            "action": self.action,
            "returns_to_guidance": self.returns_to_guidance,
            "length_m": _polyline_length(self.modified_points),
        }


def _polyline_length(points: tuple[Point, ...]) -> float:
    total = 0.0
    for a, b in zip(points, points[1:]):
        total += distance(a, b)
    return total


_PASS_POLYLINE_MAX_POINTS = 480
_PASS_CANDIDATE_MARGIN_M = 3.0
_MAX_AVOID_ITERATIONS = 48


def _dedupe(points: list[Point]) -> list[Point]:
    if not points:
        return []
    out = [points[0]]
    for point in points[1:]:
        if distance(out[-1], point) > 1e-6:
            out.append(point)
    return out


def _compact_pass_polyline(
    points: list[Point] | tuple[Point, ...],
    *,
    max_points: int = _PASS_POLYLINE_MAX_POINTS,
) -> list[Point]:
    """Reduz vertices apos costura sem destruir o arco circular do desvio."""
    pts = _dedupe(list(points))
    if len(pts) <= max_points:
        return pts
    return decimate_polyline(
        pts,
        min_step_m=0.75,
        max_points=max_points,
    )


def apply_application_obstacle_avoidance(
    passes: list[TrafficPass],
    obstacles: list[Obstacle],
    machine: MachineProfile,
    config: AvoidanceConfiguration,
    *,
    allowed_area: MultiPolygon | None = None,
    progress=None,
    report: list | None = None,
) -> tuple[list[TrafficPass], list[AvoidedPath]]:
    """Desvio de passadas de pulverizacao baseado no envelope da barra.

    Com `config.minimum_deviation` cada passada x obstaculo e classificada
    (NONE/LATERAL/FULL_CONTOUR/UNRESOLVED) e `report` recebe um
    `SprayConflictRecord` por par analisado.
    """
    if not config.enabled() or not obstacles:
        return passes, []
    if getattr(config, "minimum_deviation", False):
        return _apply_spray_minimum_deviation(
            passes,
            obstacles,
            machine,
            config,
            allowed_area=allowed_area,
            progress=progress,
            report=report,
        )
    envelopes = merge_adjacent_envelopes(
        build_all_envelopes(obstacles, machine),
        config.merge_adjacent_envelopes_m,
    )
    # Indice construido UMA vez: evita varrer todos os obstaculos por passada.
    envelope_index = build_envelope_index(envelopes) if len(envelopes) > 8 else None
    modified_passes: list[TrafficPass] = []
    avoided: list[AvoidedPath] = []
    pass_count = len(passes)
    for pass_index, traffic_pass in enumerate(passes):
        if progress is not None and pass_count > 1:
            from .generation_progress import report_progress

            local = int(100 * pass_index / max(1, pass_count - 1))
            report_progress(
                progress,
                local,
                f"Pulverizacao: passada {pass_index + 1}/{pass_count}",
            )
        pass_avoided = _avoid_traffic_pass(
            traffic_pass,
            obstacles,
            envelopes,
            machine,
            config,
            allowed_area=allowed_area,
            envelope_index=envelope_index,
        )
        if pass_count > 12 and pass_index > 0 and pass_index % 8 == 0:
            _pump_ui_events()
        if not pass_avoided:
            modified_passes.append(traffic_pass)
            continue
        avoided.extend(pass_avoided)
        final = pass_avoided[-1]
        new_seg = Segment(final.modified_points[0], final.modified_points[-1])
        modified_passes.append(
            TrafficPass(
                pass_no=traffic_pass.pass_no,
                fs_id=traffic_pass.fs_id,
                operation_id=traffic_pass.operation_id,
                spacing_m=traffic_pass.spacing_m,
                width_m=traffic_pass.width_m,
                offset_m=traffic_pass.offset_m,
                azimuth_deg=traffic_pass.azimuth_deg,
                direction=traffic_pass.direction,
                clipped_segment=Segment(final.modified_points[0], final.modified_points[-1]),
                guidance_segment=new_seg,
                path_points=final.modified_points,
            )
        )
    return modified_passes, avoided


def _avoid_traffic_pass(
    traffic_pass: TrafficPass,
    obstacles: list[Obstacle],
    envelopes: list[ObstacleSafetyEnvelope],
    machine: MachineProfile,
    config: AvoidanceConfiguration,
    *,
    allowed_area: MultiPolygon | None,
    envelope_index: UniformGridIndex | None = None,
) -> list[AvoidedPath]:
    """Desvio em passada reta ou curva; repete ate nao restar conflito."""
    work_pass = traffic_pass
    avoided_paths: list[AvoidedPath] = []
    processed_envelopes: set[str] = set()
    fail_counts: dict[str, int] = {}
    near_envelopes = _envelopes_near_pass(
        traffic_pass.guidance_segment,
        envelopes,
        machine,
        index=envelope_index,
        path_points=_traffic_pass_points(traffic_pass),
    )
    if _pass_already_clears_envelopes(traffic_pass, near_envelopes, machine):
        return []
    initial_hit_count = sum(
        1
        for envelope in near_envelopes
        if envelope.obstacle_id not in processed_envelopes
        and _envelope_hits_pass(traffic_pass, envelope, machine)
    )
    max_iters = min(max(initial_hit_count, 1) + 2, _MAX_AVOID_ITERATIONS)

    for _ in range(max_iters):
        if len(processed_envelopes) >= len(near_envelopes):
            break
        if initial_hit_count > 0 and len(processed_envelopes) >= initial_hit_count:
            break
        if hasattr(work_pass, "line_points"):
            pts = _traffic_pass_points(work_pass)
        else:
            seg = work_pass.guidance_segment
            pts = [seg.start, seg.end]
        if len(pts) > _PASS_POLYLINE_MAX_POINTS:
            pts = _compact_pass_polyline(pts)
        work_segment = work_pass.guidance_segment
        stitch_range: tuple[int, int] | None = None
        active_envelope: ObstacleSafetyEnvelope | None = None
        stitch_idx = 0

        if len(pts) >= 3:
            active_envelope, stitch_range, work_segment = _locate_envelope_hit_on_polyline(
                pts,
                near_envelopes,
                machine,
                exclude=processed_envelopes,
            )
            if active_envelope is None:
                break
            stitch_idx = stitch_range[0] if stitch_range is not None else 0
        else:
            active_envelope = _first_envelope_hit(
                work_segment,
                near_envelopes,
                machine,
                exclude=processed_envelopes,
            )
            if active_envelope is None:
                break

        build_segment = work_segment
        build_stitch = stitch_range
        if stitch_range is not None and len(pts) >= 3:
            build_segment, build_stitch = _expand_stitch_for_build(
                pts,
                stitch_range,
                min_length_m=_min_spray_build_length_m(active_envelope, machine),
            )
            stitch_idx = build_stitch[0]

        use_finalize = (initial_hit_count - len(processed_envelopes)) <= 1

        result = _avoid_segment(
            build_segment,
            obstacles,
            near_envelopes,
            machine,
            config,
            pass_id=traffic_pass.pass_no,
            row_id=None,
            source_id=traffic_pass.fs_id,
            operation_id=traffic_pass.operation_id,
            allowed_area=allowed_area,
            lateral_limit_m=lateral_limit_for_pass(traffic_pass),
            prefer_envelope=active_envelope,
            path_points=tuple(pts),
            at_index=stitch_idx,
            quick=not use_finalize,
        )
        if result is None:
            # Falha pontual: tenta de novo antes de abandonar o obstaculo.
            oid = active_envelope.obstacle_id
            fail_counts[oid] = fail_counts.get(oid, 0) + 1
            if fail_counts[oid] >= 2:
                processed_envelopes.add(oid)
            continue

        if build_stitch is None or len(pts) < 3:
            # RING (orbita 360°) precisa de vertices densos — 96 pts virava corda
            # e a folga do centro caia abaixo de W/2.
            cap = (
                _PASS_POLYLINE_MAX_POINTS
                if result.action == AvoidanceAction.RING.value
                else 160
            )
            modified = _compact_pass_polyline(result.modified_points, max_points=cap)
        else:
            modified = _compact_pass_polyline(
                stitch_avoidance_into_polyline(
                    pts,
                    build_stitch[0],
                    build_stitch[1],
                    list(result.modified_points),
                ),
                max_points=_PASS_POLYLINE_MAX_POINTS,
            )
        modified = _clip_path_to_allowed_area(modified, allowed_area)
        if len(modified) < 2:
            processed_envelopes.add(active_envelope.obstacle_id)
            continue

        # Orbita 360° clipada demais: nao substituir a passada inteira por um arco.
        from .line_geometry import polyline_length

        orig_len = polyline_length(pts) if len(pts) >= 2 else 0.0
        mod_len = polyline_length(modified)
        if (
            result.action == AvoidanceAction.RING.value
            and bool(getattr(config, "orbit_360", False))
            and orig_len > 20.0
            and mod_len < 0.55 * orig_len
        ):
            short = _build_short_ring_fallback(
                build_segment,
                active_envelope,
                machine,
                path_points=tuple(pts),
                at_index=stitch_idx,
                quick=not use_finalize,
            )
            if short is not None:
                if build_stitch is None or len(pts) < 3:
                    modified = _compact_pass_polyline(short, max_points=160)
                else:
                    modified = _compact_pass_polyline(
                        stitch_avoidance_into_polyline(
                            pts, build_stitch[0], build_stitch[1], short
                        ),
                        max_points=_PASS_POLYLINE_MAX_POINTS,
                    )
                modified = _clip_path_to_allowed_area(modified, allowed_area)
                if len(modified) < 2 or polyline_length(modified) < 0.55 * orig_len:
                    # Mantem a passada original — nao apaga linhas do talhao.
                    processed_envelopes.add(active_envelope.obstacle_id)
                    continue
            else:
                processed_envelopes.add(active_envelope.obstacle_id)
                continue

        avoided_paths.append(
            AvoidedPath(
                fs_id=result.fs_id,
                source_id=result.source_id,
                pass_id=result.pass_id,
                row_id=result.row_id,
                operation_id=result.operation_id,
                machine_id=result.machine_id,
                original_segment=Segment(pts[0], pts[-1]),
                modified_points=tuple(modified),
                entry_point=modified[0] if modified else result.entry_point,
                exit_point=modified[-1] if modified else result.exit_point,
                obstacle_id=result.obstacle_id,
                application_radius_m=result.application_radius_m,
                action=result.action,
                returns_to_guidance=_returns_to_guidance(work_segment, modified),
            )
        )
        processed_envelopes.add(active_envelope.obstacle_id)
        new_seg = Segment(modified[0], modified[-1])
        work_pass = TrafficPass(
            pass_no=traffic_pass.pass_no,
            fs_id=traffic_pass.fs_id,
            operation_id=traffic_pass.operation_id,
            spacing_m=traffic_pass.spacing_m,
            width_m=traffic_pass.width_m,
            offset_m=traffic_pass.offset_m,
            azimuth_deg=traffic_pass.azimuth_deg,
            direction=traffic_pass.direction,
            clipped_segment=Segment(modified[0], modified[-1]),
            guidance_segment=new_seg,
            path_points=tuple(modified),
        )

    if not avoided_paths:
        return []
    return [avoided_paths[-1]]


# Alias legado usado pela fachada e testes de pulverizacao
apply_obstacle_avoidance_to_passes = apply_application_obstacle_avoidance


def _avoid_segment(
    segment: Segment,
    obstacles: list[Obstacle],
    envelopes: list[ObstacleSafetyEnvelope],
    machine: MachineProfile,
    config: AvoidanceConfiguration,
    *,
    pass_id: int,
    row_id: int | None,
    source_id: str,
    operation_id: str,
    allowed_area: MultiPolygon | None,
    lateral_limit_m: float = float("inf"),
    prefer_envelope: ObstacleSafetyEnvelope | None = None,
    path_points: tuple[Point, ...] | list[Point] | None = None,
    at_index: int | None = None,
    quick: bool = False,
) -> AvoidedPath | None:
    hit_envelope: ObstacleSafetyEnvelope | None = None
    hit_obstacle: Obstacle | None = None

    if prefer_envelope is not None:
        hit_envelope = prefer_envelope
        hit_obstacle = _obstacle_for_envelope(prefer_envelope, obstacles)
    else:
        # Envelope ja embute W/2: so eixo vs envelope (sem swath duplo).
        seg = Segment(segment.start, segment.end)
        best_t: float | None = None
        for envelope in envelopes:
            if not envelope_hits_segment(envelope, seg.start, seg.end):
                continue
            t = _project_t(envelope.center, seg)
            if best_t is None or t < best_t:
                best_t = t
                hit_envelope = envelope
                hit_obstacle = _obstacle_for_envelope(envelope, obstacles)
    if hit_envelope is None or hit_obstacle is None:
        return None

    ceiling_m = _lateral_ceiling_m(hit_envelope, lateral_limit_m)
    radii = _radii_within_lateral_limit(hit_envelope, hit_obstacle, machine, ceiling_m)
    turn_r = (
        getattr(config, "minimum_turn_radius_m", None)
        or getattr(machine, "minimum_turn_radius_m", None)
        or 6.0
    )

    if not hit_obstacle.is_circular() and hit_obstacle.polygon is not None:
        # Poligono/linha: contorno da geometria real (nao circulo).
        base_geom = hit_obstacle.polygon
        hitch = float(getattr(machine, "hitch_distance_m", 0.0) or 0.0)
        points = _first_path_within_ceiling(
            (
                contour_path_around_polygon(
                    segment,
                    base_geom,
                    clearance_m=radius,
                    densify_m=1.25 if not quick else 1.5,
                    turn_radius_m=turn_r,
                    hitch_distance_m=hitch,
                    obstacle_reference=hit_obstacle.center,
                    path_points=path_points,
                    at_index=at_index,
                )
                for radius in radii
            ),
            segment,
            ceiling_m,
        )
        if points:
            points = _clip_path_to_allowed_area(points, allowed_area)
            if len(points) < 2:
                return None
            return AvoidedPath(
                fs_id=str(uuid4()),
                source_id=source_id,
                pass_id=pass_id,
                row_id=row_id,
                operation_id=operation_id,
                machine_id=getattr(machine, "machine_id", ""),
                original_segment=segment,
                modified_points=tuple(points),
                entry_point=points[0],
                exit_point=points[-1],
                obstacle_id=hit_obstacle.obstacle_id,
                application_radius_m=hit_envelope.application_radius_m,
                action=AvoidanceAction.CONTOUR.value,
                returns_to_guidance=_returns_to_guidance(segment, points),
            )

    # Circulo / grupo fundido: centro e raio do ENVELOPE (nao do 1o poste).
    # Postes a+b+c com anel no poste A geravam calombo e "passava por cima" de B/C.
    is_group = "+" in str(hit_envelope.obstacle_id)
    if config.mode == AvoidanceMode.CONCENTRIC_RING and (
        hit_obstacle.is_circular() or is_group
    ):
        points = _first_path_within_ceiling(
            (
                _build_concentric_ring(
                    segment,
                    hit_envelope.center,
                    machine,
                    radius,
                    turn_radius_m=turn_r,
                    path_points=path_points,
                    at_index=at_index,
                    quick=quick,
                    orbit_360=bool(getattr(config, "orbit_360", False)),
                )
                for radius in radii
            ),
            segment,
            ceiling_m,
        )
        if points is None:
            return None
        points = _clip_path_to_allowed_area(points, allowed_area)
        if len(points) < 2:
            return None
        return AvoidedPath(
            fs_id=str(uuid4()),
            source_id=source_id,
            pass_id=pass_id,
            row_id=row_id,
            operation_id=operation_id,
            machine_id=getattr(machine, "machine_id", ""),
            original_segment=segment,
            modified_points=tuple(points),
            entry_point=points[0],
            exit_point=points[-1],
            obstacle_id=hit_envelope.obstacle_id,
            application_radius_m=hit_envelope.application_radius_m,
            action=AvoidanceAction.RING.value,
            returns_to_guidance=_returns_to_guidance(segment, points),
        )

    if config.mode == AvoidanceMode.DETOUR:
        from .line_geometry import arc_polyline, perpendicular_left, segment_travel_direction

        mid = point_at_segment_t(segment, 0.5)
        direction = segment_travel_direction(segment, path_points, at_index=at_index)
        left = perpendicular_left(direction)
        bulge = min(hit_envelope.application_radius_m, radii[-1])
        detour_end = (mid[0] + left[0] * bulge * 2, mid[1] + left[1] * bulge * 2)
        arc = arc_polyline(segment.start, detour_end, bulge_left=True, segments=24)
        points = _clip_path_to_allowed_area(list(arc) + [segment.end], allowed_area)
        if len(points) < 2:
            return None
        return AvoidedPath(
            fs_id=str(uuid4()),
            source_id=source_id,
            pass_id=pass_id,
            row_id=row_id,
            operation_id=operation_id,
            machine_id=getattr(machine, "machine_id", ""),
            original_segment=segment,
            modified_points=tuple(points),
            entry_point=points[0],
            exit_point=points[-1],
            obstacle_id=hit_obstacle.obstacle_id,
            application_radius_m=hit_envelope.application_radius_m,
            action=AvoidanceAction.AVOID.value,
            returns_to_guidance=_returns_to_guidance(segment, points),
        )
    return None


def _segment_hits_any_envelope(
    segment: Segment,
    envelopes: list[ObstacleSafetyEnvelope],
    machine: MachineProfile,
    *,
    exclude: set[str] | None = None,
) -> bool:
    return _first_envelope_hit(segment, envelopes, machine, exclude=exclude) is not None


def _first_envelope_hit(
    segment: Segment,
    envelopes: list[ObstacleSafetyEnvelope],
    machine: MachineProfile,
    *,
    exclude: set[str] | None = None,
) -> ObstacleSafetyEnvelope | None:
    """Primeiro envelope que o eixo cruza (envelope ja embute W/2)."""
    del machine
    skip = exclude or set()
    seg = Segment(segment.start, segment.end)
    best: ObstacleSafetyEnvelope | None = None
    best_t: float | None = None
    for envelope in envelopes:
        if envelope.obstacle_id in skip:
            continue
        if not envelope_hits_segment(envelope, seg.start, seg.end):
            continue
        t = _project_t(envelope.center, seg)
        if best_t is None or t < best_t:
            best_t = t
            best = envelope
    return best


def _locate_envelope_hit_on_polyline(
    points: tuple[Point, ...] | list[Point],
    envelopes: list[ObstacleSafetyEnvelope],
    machine: MachineProfile,
    *,
    exclude: set[str] | None = None,
) -> tuple[ObstacleSafetyEnvelope | None, tuple[int, int] | None, Segment]:
    """Envelope mais cedo ao longo da polilinha (envelope ja protege a barra)."""
    del machine
    pts = list(points)
    skip = exclude or set()
    scan_pts = pts
    if len(pts) > 400:
        scan_pts = decimate_polyline(pts, min_step_m=2.0, max_points=320)

    candidates: list[ObstacleSafetyEnvelope] = []
    for envelope in envelopes:
        if envelope.obstacle_id in skip:
            continue
        if polyline_envelope_hit_range(scan_pts, envelope) is not None:
            candidates.append(envelope)

    best: ObstacleSafetyEnvelope | None = None
    best_range: tuple[int, int, Segment] | None = None
    for envelope in candidates:
        hit = polyline_envelope_hit_range(pts, envelope)
        if hit is None:
            continue
        if best_range is None or hit[0] < best_range[0]:
            best = envelope
            best_range = hit
    if best is None or best_range is None:
        return None, None, Segment(pts[0], pts[-1])
    return best, (best_range[0], best_range[1]), best_range[2]


def _expand_stitch_for_build(
    points: tuple[Point, ...] | list[Point],
    stitch_range: tuple[int, int],
    *,
    min_length_m: float,
) -> tuple[Segment, tuple[int, int]]:
    """Amplia trecho costurado pelo arco da polilinha (corda curta em curvas)."""
    from .line_geometry import ensure_segment_span, polyline_length

    pts = list(points)
    left, right = stitch_range
    if right < left:
        left, right = right, left

    def _arc_len(lo: int, hi: int) -> float:
        if hi <= lo:
            return 0.0
        return polyline_length(pts[lo : hi + 1])

    target = max(min_length_m, _arc_len(left, right) * 2.5)
    max_expand_iters = 96
    for _ in range(max_expand_iters):
        if left <= 0 and right >= len(pts) - 1:
            break
        if _arc_len(left, right) >= target:
            break
        grew = False
        if left > 0:
            left -= 1
            grew = True
        if right < len(pts) - 1:
            right += 1
            grew = True
        if not grew:
            break

    chord = Segment(pts[left], pts[right])
    half_span = max(target / 2.0, _arc_len(left, right) / 2.0, 12.0)
    try:
        build_segment = ensure_segment_span(
            chord,
            pts,
            at_index=left,
            half_span_m=half_span,
            min_span_m=1.0,
        )
    except ValueError:
        build_segment = chord
    return build_segment, (left, right)


def _min_spray_build_length_m(
    envelope: ObstacleSafetyEnvelope,
    machine: MachineProfile,
) -> float:
    rmin = float(getattr(machine, "minimum_turn_radius_m", 0.0) or 6.0)
    clearance = float(envelope.application_radius_m or 10.0)
    return max(48.0, 3.0 * rmin + clearance)


def _envelopes_near_pass(
    segment: Segment,
    envelopes: list[ObstacleSafetyEnvelope],
    machine: MachineProfile,
    *,
    margin_m: float = _PASS_CANDIDATE_MARGIN_M,
    index: UniformGridIndex | None = None,
    path_points: list[Point] | None = None,
) -> list[ObstacleSafetyEnvelope]:
    """Filtra envelopes plausiveis para esta passada.

    Em passada CURVA, medir distancia a corda (start→end) ignora obstaculos que
    estao em cima do arco (ex.: 0 m da polilinha, 29 m da corda). Usa a
    polilinha real quando disponivel.
    """
    from .line_geometry import signed_distance_point_to_polyline

    pts = path_points if path_points and len(path_points) >= 2 else [segment.start, segment.end]
    use_poly = len(pts) >= 3

    if index is not None and len(index) > 0:
        # Bbox do envelope ja cobre o raio de aplicacao; so margem tecnica.
        reach = margin_m + index.cell_size_m
        candidates = [item for item in index.query_polyline(pts, reach)]
        if candidates:
            envelopes = candidates

    out: list[ObstacleSafetyEnvelope] = []
    for envelope in envelopes:
        # Envelope ja = obstaculo + W/2 + margem — nao somar meia barra de novo.
        reach = float(envelope.application_radius_m or 0.0) + margin_m
        if use_poly:
            lat = abs(signed_distance_point_to_polyline(envelope.center, pts))
            if lat > reach:
                continue
            out.append(envelope)
            continue
        lat = _point_line_distance(envelope.center, segment)
        if lat > reach:
            continue
        t = _project_t(envelope.center, segment)
        if t < -0.12 or t > 1.12:
            continue
        out.append(envelope)
    if out:
        return out
    if not envelopes:
        return []
    # Fallback bbox no corredor da polilinha (nao so da corda).
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    max_radius = max(
        (float(envelope.application_radius_m or 0.0) for envelope in envelopes),
        default=0.0,
    )
    reach = margin_m + max_radius
    xmin, xmax = min(xs) - reach, max(xs) + reach
    ymin, ymax = min(ys) - reach, max(ys) + reach
    bbox_out: list[ObstacleSafetyEnvelope] = []
    for envelope in envelopes:
        cx, cy = envelope.center
        if xmin <= cx <= xmax and ymin <= cy <= ymax:
            bbox_out.append(envelope)
    return bbox_out


def _traffic_pass_points(traffic_pass: TrafficPass) -> list[Point]:
    try:
        pts = list(traffic_pass.line_points())
        if len(pts) >= 2:
            return pts
    except AttributeError:
        pass
    seg = traffic_pass.guidance_segment
    return [seg.start, seg.end]


def _pass_already_clears_envelopes(
    traffic_pass: TrafficPass,
    envelopes: list[ObstacleSafetyEnvelope],
    machine: MachineProfile,
) -> bool:
    """True quando a trajetoria ja mantem o envelope operacional em todo o percurso.

    O envelope embute a meia largura da barra, entao testar o eixo equivale a
    garantir que as PONTAS passam fora do obstaculo + margem.
    """
    del machine
    pts = _traffic_pass_points(traffic_pass)
    for envelope in envelopes:
        if polyline_envelope_hit_range(pts, envelope) is not None:
            return False
    return True


def _clip_path_to_allowed_area(
    points: list[Point] | tuple[Point, ...],
    allowed_area: MultiPolygon | None,
) -> list[Point]:
    """Recorta trajetoria ao limite operacional + extensao.

    Nao fica so com o maior pedaco: orbita 360° que sai um pouco do talhao
    gerava varios chunks e o max() apagava a passada inteira (so sobrava um
    arco). Concatena os trechos na ordem da polilinha.
    """
    if not allowed_area or len(points) < 2:
        return list(points)
    from .line_geometry import clip_polyline_to_multipolygon, polyline_length

    chunks = clip_polyline_to_multipolygon(list(points), allowed_area)
    if not chunks:
        return []
    if len(chunks) == 1:
        return list(chunks[0])
    # Ordem do clip = ordem ao longo da trajetoria.
    out: list[Point] = list(chunks[0])
    for chunk in chunks[1:]:
        if len(chunk) < 2:
            continue
        # Liga se o buraco (parte fora do talhao) for curto; senao so anexa.
        gap = distance(out[-1], chunk[0])
        if gap > 1e-6:
            # Ponte so se o salto for pequeno (borda do talhao / corda).
            if gap <= 25.0:
                out.append(chunk[0])
        for pt in chunk[1:] if gap <= 1e-6 or gap <= 25.0 else chunk:
            if abs(out[-1][0] - pt[0]) > 1e-9 or abs(out[-1][1] - pt[1]) > 1e-9:
                out.append(pt)
    if len(out) < 2:
        # Fallback: maior pedaco (comportamento antigo).
        return max(chunks, key=lambda c: polyline_length(c) if len(c) > 1 else 0.0)
    return out


def _envelope_hits_pass(
    traffic_pass: TrafficPass,
    envelope: ObstacleSafetyEnvelope,
    machine: MachineProfile,
) -> bool:
    del machine
    pts = _traffic_pass_points(traffic_pass)
    if len(pts) >= 3:
        return polyline_envelope_hit_range(pts, envelope) is not None
    seg = traffic_pass.guidance_segment
    return envelope_hits_segment(envelope, seg.start, seg.end)


def _point_line_distance(point: Point, segment: Segment) -> float:
    t = _project_t(point, segment)
    t = max(0.0, min(1.0, t))
    closest = point_at_segment_t(segment, t)
    return distance(point, closest)


def _obstacle_for_envelope(
    envelope: ObstacleSafetyEnvelope,
    obstacles: list[Obstacle],
) -> Obstacle | None:
    parts = [part for part in envelope.obstacle_id.split("+") if part]
    for obs in obstacles:
        if obs.obstacle_id in parts or obs.obstacle_id in envelope.obstacle_id:
            return obs
    for obs in obstacles:
        if distance(obs.center, envelope.center) < 0.01:
            return obs
    return None


def _pump_ui_events() -> None:
    try:
        from qgis.PyQt.QtWidgets import QApplication

        QApplication.processEvents()
    except Exception:
        pass


def _project_t(point: Point, segment: Segment) -> float:
    dx = segment.end[0] - segment.start[0]
    dy = segment.end[1] - segment.start[1]
    length2 = dx * dx + dy * dy
    if length2 <= 1e-12:
        return 0.0
    return ((point[0] - segment.start[0]) * dx + (point[1] - segment.start[1]) * dy) / length2


def lateral_limit_for_pass(traffic_pass: TrafficPass) -> float:
    """Deslocamento lateral maximo do desvio: meio espacamento entre passadas.

    Acima disso o centro da barra cruzaria a passada vizinha, gerando remonte
    de um lado e falha do outro.
    """
    spacing = float(getattr(traffic_pass, "spacing_m", 0.0) or 0.0)
    if spacing <= 0.0:
        return float("inf")
    return spacing / 2.0


def _lateral_ceiling_m(envelope: ObstacleSafetyEnvelope, limit_m: float) -> float:
    """Teto lateral: meio espacamento ou folga nominal da barra (o que for maior)."""
    if limit_m == float("inf"):
        return float("inf")
    return max(limit_m, float(envelope.application_radius_m))


def _first_path_within_ceiling(candidates, segment: Segment, ceiling_m: float):
    """Primeiro caminho dentro do teto lateral.

    Se o raio de giro obriga a abrir mais que o teto, fica a folga nominal: e o
    melhor caminho dirigivel que existe, encolher so pioraria a curva.
    """
    from .obstacle_contour_path import polyline_max_lateral_offset_m

    nominal = None
    for candidate in candidates:
        if not candidate:
            continue
        if nominal is None:
            nominal = candidate
        if ceiling_m == float("inf"):
            return candidate
        if polyline_max_lateral_offset_m(candidate, segment) <= ceiling_m + 1e-6:
            return candidate
    return nominal


def _radii_within_lateral_limit(
    envelope: ObstacleSafetyEnvelope,
    obstacle: Obstacle,
    machine: MachineProfile,
    ceiling_m: float,
) -> list[float]:
    """Folgas a tentar, da nominal (meia barra) ate o minimo que protege o rodado."""
    ideal = float(envelope.application_radius_m)
    if ceiling_m == float("inf"):
        return [ideal]
    track = getattr(machine, "effective_track", None)
    half_track = float(getattr(track, "track_width_m", 0.0) or 0.0) / 2.0
    floor_r = max(obstacle.safety_zone_radius_m() + half_track, 0.1)
    if floor_r >= ideal:
        return [ideal]
    return [ideal + (floor_r - ideal) * (step / 4.0) for step in range(0, 5)]


def _build_short_ring_fallback(
    segment: Segment,
    envelope: ObstacleSafetyEnvelope,
    machine: MachineProfile,
    *,
    path_points: tuple[Point, ...] | list[Point] | None = None,
    at_index: int | None = None,
    quick: bool = False,
) -> list[Point] | None:
    """Arco curto quando a orbita 360° nao cabe / seria clipada demais."""
    from .obstacle_contour_path import circular_bypass_path

    turn_r = getattr(machine, "minimum_turn_radius_m", None) or 6.0
    hitch = float(getattr(machine, "hitch_distance_m", 0.0) or 0.0)
    return circular_bypass_path(
        segment,
        envelope.center,
        float(envelope.application_radius_m),
        turn_radius_m=turn_r,
        hitch_distance_m=hitch,
        segments=48 if quick else 72,
        path_points=path_points,
        at_index=at_index,
        quick=quick,
    )


def _build_concentric_ring(
    segment: Segment,
    center: Point,
    machine: MachineProfile,
    radius_m: float,
    *,
    turn_radius_m: float | None = None,
    path_points: tuple[Point, ...] | list[Point] | None = None,
    at_index: int | None = None,
    quick: bool = False,
    orbit_360: bool = False,
) -> list[Point] | None:
    """Anel no limite operacional.

    Com `orbit_360=True` (opcao da GUI): entra, da volta completa e sai.
    Caso contrario: arco curto entra/sai (padrao estavel).
    """
    from .obstacle_contour_path import circular_bypass_path, circular_orbit_360_path

    turn_r = turn_radius_m
    if turn_r is None:
        turn_r = getattr(machine, "minimum_turn_radius_m", None) or 6.0
    hitch = float(getattr(machine, "hitch_distance_m", 0.0) or 0.0)

    if orbit_360:
        # Passada curva: orbita no segmento local de costura (nao na corda A-B).
        orbit = circular_orbit_360_path(
            segment,
            center,
            radius_m,
            turn_radius_m=turn_r,
            hitch_distance_m=hitch,
            segments=64 if quick else 96,
            path_points=path_points,
            at_index=at_index,
            quick=quick,
        )
        if orbit is not None and len(orbit) >= 5:
            return orbit

    return circular_bypass_path(
        segment,
        center,
        radius_m,
        turn_radius_m=turn_r,
        hitch_distance_m=hitch,
        segments=48 if quick else 72,
        path_points=path_points,
        at_index=at_index,
        quick=quick,
    )


def _returns_to_guidance(original: Segment, points: list[Point]) -> bool:
    if len(points) < 2:
        return False
    from .line_geometry import segment_travel_direction

    try:
        orig_dir = segment_travel_direction(original)
        end_dir = (
            segment_travel_direction(Segment(points[-2], points[-1]))
            if len(points) >= 2
            else orig_dir
        )
    except ValueError:
        return False
    return abs(orig_dir[0] * end_dir[0] + orig_dir[1] * end_dir[1]) > 0.95


def avoidance_summary(paths: list[AvoidedPath]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in paths:
        rows.append(
            {
                "pass_id": path.pass_id,
                "row_id": path.row_id,
                "obstacle_id": path.obstacle_id,
                "action": path.action.upper(),
                "application_radius_m": path.application_radius_m,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Desvio minimo por passada (pulverizacao): NONE / LATERAL / FULL_CONTOUR /
# UNRESOLVED. Cada passada e analisada contra cada zona de seguranca; o
# contorno FULL_CONTOUR reutiliza o anel do motor acima (_avoid_traffic_pass).
# ---------------------------------------------------------------------------


class SprayAvoidanceType(str, Enum):
    NONE = "NONE"
    LATERAL = "LATERAL"
    FULL_CONTOUR = "FULL_CONTOUR"
    UNRESOLVED = "UNRESOLVED"


SPRAY_AVOIDANCE_SEVERITY = {
    SprayAvoidanceType.NONE.value: 0,
    SprayAvoidanceType.LATERAL.value: 1,
    SprayAvoidanceType.FULL_CONTOUR.value: 2,
    SprayAvoidanceType.UNRESOLVED.value: 3,
}

SPRAY_TURN_RADIUS_MISSING = (
    "Raio minimo de giro do pulverizador nao informado — desvio nao calculado."
)

# Rumo maximo da transicao lateral em relacao a passada (curva S suave).
_LATERAL_MAX_HEADING_DEG = 30.0
# Folga numerica alem da zona de seguranca (o deslocamento minimo e exato).
_LATERAL_CLEARANCE_PAD_M = 0.05
# Anel reutilizado e poligonal: pequeno acrescimo para a ponta nao tocar a zona.
_CONTOUR_RADIUS_PAD_M = 0.10
_CLEARANCE_TOLERANCE_M = 0.02
_ON_LINE_TOLERANCE_M = 0.02
_RAMP_MIN_SAMPLES = 24
_RAMP_MAX_STEP_M = 0.5
_PLATEAU_STEP_M = 2.0
_EXTEND_STEP_M = 0.5
_MAX_EXTEND_ITERATIONS = 160
_BOOM_SAMPLE_STEP_M = 0.5
# Raio de curvatura medido no anel reutilizado (discreto) aceita esta fracao de Rmin.
_CONTOUR_CURVATURE_FACTOR = 0.85


@dataclass(frozen=True)
class SprayConflictRecord:
    """Resultado da analise passada x obstaculo (atributos da camada de desvios)."""

    pass_id: int
    pass_fs_id: str
    obstacle_id: str
    avoidance_type: str
    side: str
    boom_width_m: float
    safe_radius_m: float
    required_offset_m: float
    entry_station_m: float | None
    exit_station_m: float | None
    minimum_turn_radius_m: float | None
    lateral_distance_m: float
    applied_offset_m: float = 0.0
    reason: str = ""
    detour_points: tuple[Point, ...] = ()
    operation: str = "spraying"
    pass_role: str = "pass"

    def attributes(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "pass_id": self.pass_id,
            "obstacle_id": self.obstacle_id,
            "avoidance_type": self.avoidance_type,
            "side": self.side,
            "boom_width_m": round(self.boom_width_m, 3),
            "safe_radius_m": round(self.safe_radius_m, 3),
            "required_offset_m": round(self.required_offset_m, 3),
            "applied_offset_m": round(self.applied_offset_m, 3),
            "entry_station_m": (
                None if self.entry_station_m is None else round(self.entry_station_m, 3)
            ),
            "exit_station_m": (
                None if self.exit_station_m is None else round(self.exit_station_m, 3)
            ),
            "minimum_turn_radius_m": self.minimum_turn_radius_m,
            "lateral_distance_m": round(self.lateral_distance_m, 3),
            "pass_role": self.pass_role,
            "reason": self.reason,
        }

    def corridor_polygon(self):
        """Faixa da barra fisica ao longo do trecho desviado (camada 23)."""
        from .line_geometry import build_polyline_strip_polygon

        if len(self.detour_points) < 2 or self.boom_width_m <= 0:
            return None
        return build_polyline_strip_polygon(
            self.detour_points, half_width_m=self.boom_width_m / 2.0, resample_m=1.0
        )


@dataclass(frozen=True)
class SpraySafetyZone:
    """Zona de seguranca da pulverizacao: raio fisico + margem (sem meia barra)."""

    obstacle_id: str
    center: Point
    safe_radius_m: float
    obstacle_radius_m: float
    safety_margin_m: float
    polygon: object
    circular: bool

    def attributes(self, operation: str = "spraying") -> dict[str, object]:
        return {
            "operation": operation,
            "obstacle_id": self.obstacle_id,
            "obstacle_radius_m": round(self.obstacle_radius_m, 3),
            "safety_margin_m": round(self.safety_margin_m, 3),
            "safe_radius_m": round(self.safe_radius_m, 3),
        }


def build_spray_safety_zones(obstacles: list[Obstacle]) -> list[SpraySafetyZone]:
    """safe_radius_m = obstacle_radius_m + safety_margin_m (ex.: 0,50 + 1,00 = 1,50 m)."""
    from .obstacle_buffer_engine import build_safety_zone

    zones: list[SpraySafetyZone] = []
    for obstacle in obstacles:
        zone = build_safety_zone(obstacle)
        if zone is not None:
            geometry, center, radius = zone.geometry, zone.center, zone.application_radius_m
        elif obstacle.polygon is not None:
            geometry, center, radius = obstacle.polygon, obstacle.center, 0.0
        else:
            continue
        zones.append(
            SpraySafetyZone(
                obstacle_id=obstacle.obstacle_id,
                center=center,
                safe_radius_m=float(radius),
                obstacle_radius_m=float(obstacle.obstacle_radius_m),
                safety_margin_m=float(obstacle.safety_margin_m),
                polygon=geometry,
                circular=obstacle.is_circular(),
            )
        )
    return zones


def resolve_sprayer_turn_radius_m(
    machine: MachineProfile, config: AvoidanceConfiguration
) -> float | None:
    """Raio do PULVERIZADOR; nunca o da plantadeira nem um valor inventado."""
    for value in (
        getattr(machine, "sprayer_minimum_turn_radius_m", None),
        getattr(config, "minimum_turn_radius_m", None),
    ):
        if value is not None and float(value) > 0:
            return float(value)
    return None


def spray_boom_width_m(machine: MachineProfile) -> float:
    """Barra FISICA (nao o passo efetivo barra - transpasse)."""
    boom = float(getattr(machine, "boom_width_m", 0.0) or 0.0)
    return boom if boom > 0 else float(machine.operational_width_m)


def spray_corridor_half_width_m(machine: MachineProfile) -> float:
    """Meia largura do corredor central (rodados externos do pulverizador)."""
    track = getattr(machine, "effective_track", None) or getattr(machine, "track", None)
    if track is None:
        return 0.0
    return (float(track.track_width_m) + float(track.tire_width_m)) / 2.0


def classify_spray_lateral_interval(
    d_min: float,
    d_max: float,
    *,
    half_boom_m: float,
    corridor_half_width_m: float,
) -> SprayAvoidanceType:
    """Classifica a zona [d_min, d_max] (lateral, + = esquerda) contra a barra."""
    if d_min >= half_boom_m or d_max <= -half_boom_m:
        return SprayAvoidanceType.NONE
    if d_min < corridor_half_width_m and d_max > -corridor_half_width_m:
        return SprayAvoidanceType.FULL_CONTOUR
    return SprayAvoidanceType.LATERAL


def classify_spray_conflict(
    lateral_distance_m: float,
    safe_radius_m: float,
    boom_width_m: float,
    *,
    corridor_half_width_m: float = 0.0,
) -> tuple[SprayAvoidanceType, str, float]:
    """(tipo, lado natural, deslocamento minimo) de um obstaculo circular.

    Ex.: barra 36 m, obstaculo 13 m a direita, zona 1,50 m ->
    LATERAL para a esquerda com 18 - 13 + 1,5 = 6,5 m.
    """
    half = boom_width_m / 2.0
    d_min = lateral_distance_m - safe_radius_m
    d_max = lateral_distance_m + safe_radius_m
    kind = classify_spray_lateral_interval(
        d_min, d_max, half_boom_m=half, corridor_half_width_m=corridor_half_width_m
    )
    if kind == SprayAvoidanceType.NONE:
        return kind, "", 0.0
    left, right = d_max + half, half - d_min
    if left <= right:
        return kind, "left", left
    return kind, "right", right


def lateral_ramp_length_m(
    offset_m: float,
    turn_radius_m: float,
    *,
    max_heading_deg: float = _LATERAL_MAX_HEADING_DEG,
) -> float:
    """Comprimento longitudinal da transicao arco -> reta -> arco ate `offset_m`."""
    return _ramp_geometry(abs(offset_m), turn_radius_m, max_heading_deg)[3]


def lateral_ramp_offset_m(
    station_m: float,
    offset_m: float,
    turn_radius_m: float,
    *,
    max_heading_deg: float = _LATERAL_MAX_HEADING_DEG,
) -> float:
    """Deslocamento lateral na transicao: 0 e tangente no inicio, `offset_m` no fim."""
    from math import sqrt, tan

    delta = abs(offset_m)
    theta, arc_len, arc_lat, total = _ramp_geometry(delta, turn_radius_m, max_heading_deg)
    if total <= 0.0:
        return 0.0
    u = max(0.0, min(total, station_m))
    r = turn_radius_m
    if u <= arc_len:
        value = r - sqrt(max(0.0, r * r - u * u))
    elif u >= total - arc_len:
        rest = total - u
        value = delta - (r - sqrt(max(0.0, r * r - rest * rest)))
    else:
        value = arc_lat + (u - arc_len) * tan(theta)
    return value if offset_m >= 0 else -value


def _ramp_geometry(
    delta: float, turn_radius_m: float, max_heading_deg: float
) -> tuple[float, float, float, float]:
    """(rumo, comprimento de cada arco, lateral de cada arco, comprimento total)."""
    from math import acos, cos, radians, sin, tan

    if delta <= 1e-9 or turn_radius_m <= 0:
        return 0.0, 0.0, 0.0, 0.0
    r = turn_radius_m
    theta_max = radians(max_heading_deg)
    arc_lat_max = r * (1.0 - cos(theta_max))
    if delta <= 2.0 * arc_lat_max:
        theta = acos(max(-1.0, 1.0 - delta / (2.0 * r)))
        arc_len = r * sin(theta)
        return theta, arc_len, delta / 2.0, 2.0 * arc_len
    arc_len = r * sin(theta_max)
    straight = (delta - 2.0 * arc_lat_max) / tan(theta_max)
    return theta_max, arc_len, arc_lat_max, 2.0 * arc_len + straight


class _PassFrame:
    """Referencia (estacao, lateral) ao longo da passada ORIGINAL."""

    def __init__(self, points) -> None:
        pts = _dedupe(list(points))
        self.points = pts
        stations = [0.0]
        for a, b in zip(pts, pts[1:]):
            stations.append(stations[-1] + distance(a, b))
        self.stations = stations
        self.length = stations[-1]

    def _segment_index(self, station: float) -> int:
        from bisect import bisect_right

        index = bisect_right(self.stations, station) - 1
        return max(0, min(index, len(self.points) - 2))

    def direction(self, station: float) -> Point:
        i = self._segment_index(station)
        a, b = self.points[i], self.points[i + 1]
        length = self.stations[i + 1] - self.stations[i]
        return ((b[0] - a[0]) / length, (b[1] - a[1]) / length)

    def point(self, station: float, lateral: float = 0.0) -> Point:
        i = self._segment_index(station)
        a = self.points[i]
        ux, uy = self.direction(station)
        along = station - self.stations[i]
        return (a[0] + ux * along - uy * lateral, a[1] + uy * along + ux * lateral)

    def locate(self, point: Point) -> tuple[float, float]:
        """(estacao, lateral com sinal: + = esquerda); extrapola alem das pontas."""
        best: tuple[float, float, float] | None = None
        last = len(self.points) - 2
        for i in range(last + 1):
            a, b = self.points[i], self.points[i + 1]
            length = self.stations[i + 1] - self.stations[i]
            ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
            vx, vy = point[0] - a[0], point[1] - a[1]
            along = vx * ux + vy * uy
            if not (i == 0 and along < 0.0) and not (i == last and along > length):
                along = max(0.0, min(length, along))
            px, py = a[0] + ux * along, a[1] + uy * along
            gap = ((point[0] - px) ** 2 + (point[1] - py) ** 2) ** 0.5
            if best is None or gap < best[0] - 1e-12:
                side = ux * (point[1] - py) - uy * (point[0] - px)
                best = (gap, self.stations[i] + along, gap if side >= 0 else -gap)
        assert best is not None
        return best[1], best[2]


@dataclass(frozen=True)
class SprayZoneConflict:
    """Extensao de uma zona de seguranca no referencial da passada."""

    zone: SpraySafetyZone
    s_min: float
    s_max: float
    d_min: float
    d_max: float
    d_center: float
    avoidance_type: SprayAvoidanceType
    left_required_m: float
    right_required_m: float

    def required_for_side(self, side: str) -> float:
        if side == "left":
            return self.left_required_m
        if side == "right":
            return self.right_required_m
        return min(self.left_required_m, self.right_required_m)


def analyze_spray_pass_conflict(
    pass_points,
    zone: SpraySafetyZone,
    *,
    half_boom_m: float,
    corridor_half_width_m: float,
) -> SprayZoneConflict:
    """Envelope fisico da barra x zona de seguranca para UMA passada."""
    return _analyze_zone(
        pass_points if isinstance(pass_points, _PassFrame) else _PassFrame(pass_points),
        zone,
        half_boom_m=half_boom_m,
        corridor_half_width_m=corridor_half_width_m,
    )


def _analyze_zone(
    frame: _PassFrame,
    zone: SpraySafetyZone,
    *,
    half_boom_m: float,
    corridor_half_width_m: float,
) -> SprayZoneConflict:
    s_c, d_c = frame.locate(zone.center)
    if zone.circular:
        r = zone.safe_radius_m
        s_min, s_max, d_min, d_max = s_c - r, s_c + r, d_c - r, d_c + r
    else:
        located = [frame.locate(p) for p in zone.polygon[0]]
        s_min = min(item[0] for item in located)
        s_max = max(item[0] for item in located)
        d_min = min(item[1] for item in located)
        d_max = max(item[1] for item in located)
    if s_max < 0.0 or s_min > frame.length:
        kind = SprayAvoidanceType.NONE
    else:
        kind = classify_spray_lateral_interval(
            d_min, d_max, half_boom_m=half_boom_m, corridor_half_width_m=corridor_half_width_m
        )
    return SprayZoneConflict(
        zone=zone,
        s_min=s_min,
        s_max=s_max,
        d_min=d_min,
        d_max=d_max,
        d_center=d_c,
        avoidance_type=kind,
        left_required_m=max(0.0, d_max + half_boom_m),
        right_required_m=max(0.0, half_boom_m - d_min),
    )


def spray_boom_clearance_violations(
    path_points,
    zones: list[SpraySafetyZone],
    half_boom_m: float,
    *,
    tolerance_m: float = 0.0,
    step_m: float = _BOOM_SAMPLE_STEP_M,
) -> list[tuple[Point, str, float]]:
    """Amostras onde a barra FISICA (perpendicular ao rumo) invade alguma zona.

    Retorna (centro da maquina, obstacle_id, folga) com folga negativa.
    """
    pts = _dedupe(list(path_points))
    out: list[tuple[Point, str, float]] = []
    if len(pts) < 2 or not zones:
        return out
    reach = [
        (zone, half_boom_m + _zone_extent_m(zone) + step_m) for zone in zones
    ]
    for a, b in zip(pts, pts[1:]):
        length = distance(a, b)
        if length <= 1e-9:
            continue
        ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        nx, ny = -uy, ux
        near = [
            zone
            for zone, limit in reach
            if _point_segment_distance(zone.center, a, b) <= limit
        ]
        if not near:
            continue
        count = max(1, int(length / step_m))
        for k in range(count + 1):
            t = length * k / count
            c = (a[0] + ux * t, a[1] + uy * t)
            tip_l = (c[0] + nx * half_boom_m, c[1] + ny * half_boom_m)
            tip_r = (c[0] - nx * half_boom_m, c[1] - ny * half_boom_m)
            for zone in near:
                if zone.circular:
                    clearance = (
                        _point_segment_distance(zone.center, tip_l, tip_r) - zone.safe_radius_m
                    )
                    if clearance < -tolerance_m:
                        out.append((c, zone.obstacle_id, clearance))
                elif _segment_hits_polygon(tip_l, tip_r, zone.polygon):
                    out.append((c, zone.obstacle_id, -tolerance_m - 1e-6))
    return out


def _zone_extent_m(zone: SpraySafetyZone) -> float:
    if zone.circular:
        return zone.safe_radius_m
    return max(distance(zone.center, p) for p in zone.polygon[0])


def _point_segment_distance(point: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    if length2 <= 1e-18:
        return distance(point, a)
    t = max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length2))
    return distance(point, (a[0] + dx * t, a[1] + dy * t))


def _segment_hits_polygon(a: Point, b: Point, polygon) -> bool:
    from .line_geometry import point_in_polygon

    if point_in_polygon(a, polygon) or point_in_polygon(b, polygon):
        return True
    for ring in [polygon[0], *polygon[1]]:
        for p, q in zip(ring, ring[1:]):
            if _segments_cross(a, b, p, q):
                return True
    return False


def _segments_cross(a: Point, b: Point, c: Point, d: Point) -> bool:
    def orient(p: Point, q: Point, r: Point) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    o1, o2 = orient(a, b, c), orient(a, b, d)
    o3, o4 = orient(c, d, a), orient(c, d, b)
    return (o1 * o2 <= 0.0) and (o3 * o4 <= 0.0) and not (o1 == o2 == 0.0)


def min_turning_radius_m(points) -> float:
    """Menor raio do circulo por 3 vertices consecutivos (curvatura discreta)."""
    pts = _dedupe(list(points))
    best = float("inf")
    for a, b, c in zip(pts, pts[1:], pts[2:]):
        ab, bc, ca = distance(a, b), distance(b, c), distance(c, a)
        area2 = abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
        if area2 <= 1e-12:
            continue
        best = min(best, ab * bc * ca / (2.0 * area2))
    return best


@dataclass(frozen=True)
class _Replacement:
    entry_s: float
    exit_s: float
    points: tuple[Point, ...]
    avoidance_type: SprayAvoidanceType
    side: str
    applied_offset_m: float
    action: str
    application_radius_m: float
    added_length_m: float


@dataclass(frozen=True)
class _GroupResolution:
    avoidance_type: SprayAvoidanceType
    replacement: _Replacement | None
    footprint: tuple[float, float]
    reason: str = ""


@dataclass(frozen=True)
class _SprayPassContext:
    machine: MachineProfile
    config: AvoidanceConfiguration
    obstacles_by_id: dict
    half_boom_m: float
    boom_width_m: float
    corridor_half_m: float
    turn_radius_m: float | None
    allowed_area: MultiPolygon | None


def _apply_spray_minimum_deviation(
    passes: list[TrafficPass],
    obstacles: list[Obstacle],
    machine: MachineProfile,
    config: AvoidanceConfiguration,
    *,
    allowed_area: MultiPolygon | None,
    progress=None,
    report: list | None = None,
) -> tuple[list[TrafficPass], list[AvoidedPath]]:
    zones = build_spray_safety_zones(obstacles)
    boom = spray_boom_width_m(machine)
    ctx = _SprayPassContext(
        machine=machine,
        config=config,
        obstacles_by_id={item.obstacle_id: item for item in obstacles},
        half_boom_m=boom / 2.0,
        boom_width_m=boom,
        corridor_half_m=spray_corridor_half_width_m(machine),
        turn_radius_m=resolve_sprayer_turn_radius_m(machine, config),
        allowed_area=allowed_area,
    )
    out_passes: list[TrafficPass] = []
    avoided: list[AvoidedPath] = []
    pass_count = len(passes)
    for pass_index, traffic_pass in enumerate(passes):
        if progress is not None and pass_count > 1:
            from .generation_progress import report_progress

            report_progress(
                progress,
                int(100 * pass_index / max(1, pass_count - 1)),
                f"Pulverizacao (desvio minimo): passada {pass_index + 1}/{pass_count}",
            )
        new_pass, path, records = _spray_minimum_deviation_for_pass(traffic_pass, zones, ctx)
        out_passes.append(new_pass)
        if path is not None:
            avoided.append(path)
        if report is not None:
            report.extend(records)
        if pass_count > 12 and pass_index > 0 and pass_index % 8 == 0:
            _pump_ui_events()
    return out_passes, avoided


def _with_points(traffic_pass: TrafficPass, points) -> TrafficPass:
    pts = tuple(points)
    return TrafficPass(
        pass_no=traffic_pass.pass_no,
        fs_id=traffic_pass.fs_id,
        operation_id=traffic_pass.operation_id,
        spacing_m=traffic_pass.spacing_m,
        width_m=traffic_pass.width_m,
        offset_m=traffic_pass.offset_m,
        azimuth_deg=traffic_pass.azimuth_deg,
        direction=traffic_pass.direction,
        clipped_segment=Segment(pts[0], pts[-1]),
        guidance_segment=Segment(pts[0], pts[-1]),
        path_points=pts,
    )


def _relevant_zones(frame: _PassFrame, zones: list[SpraySafetyZone], reach_m: float):
    xs = [p[0] for p in frame.points]
    ys = [p[1] for p in frame.points]
    out = []
    for zone in zones:
        extent = _zone_extent_m(zone) + reach_m
        cx, cy = zone.center
        if min(xs) - extent <= cx <= max(xs) + extent and min(ys) - extent <= cy <= max(ys) + extent:
            out.append(zone)
    return out


def _spray_minimum_deviation_for_pass(
    traffic_pass: TrafficPass,
    zones: list[SpraySafetyZone],
    ctx: _SprayPassContext,
) -> tuple[TrafficPass, AvoidedPath | None, list[SprayConflictRecord]]:
    pts = _traffic_pass_points(traffic_pass)
    frame = _PassFrame(pts)
    if len(frame.points) < 2 or frame.length <= 1e-6:
        return traffic_pass, None, []
    # Alem do alcance fisico, registra NONE ate uma barra de distancia (auditoria).
    reach = ctx.half_boom_m + ctx.boom_width_m
    analyses = [
        _analyze_zone(
            frame, zone, half_boom_m=ctx.half_boom_m, corridor_half_width_m=ctx.corridor_half_m
        )
        for zone in _relevant_zones(frame, zones, reach)
    ]
    analyses = [
        item
        for item in analyses
        if item.avoidance_type != SprayAvoidanceType.NONE
        or (
            item.s_max >= 0.0
            and item.s_min <= frame.length
            and min(abs(item.d_min), abs(item.d_max)) <= reach
        )
    ]
    records: list[SprayConflictRecord] = []
    for item in analyses:
        if item.avoidance_type == SprayAvoidanceType.NONE:
            records.append(_record(traffic_pass, item, ctx, SprayAvoidanceType.NONE, None))
    conflicts = sorted(
        (item for item in analyses if item.avoidance_type != SprayAvoidanceType.NONE),
        key=lambda item: item.s_min,
    )
    if not conflicts:
        return traffic_pass, None, records
    if ctx.turn_radius_m is None:
        for item in conflicts:
            records.append(
                _record(
                    traffic_pass,
                    item,
                    ctx,
                    SprayAvoidanceType.UNRESOLVED,
                    _GroupResolution(
                        SprayAvoidanceType.UNRESOLVED,
                        None,
                        (item.s_min, item.s_max),
                        SPRAY_TURN_RADIUS_MISSING,
                    ),
                )
            )
        return traffic_pass, None, records

    free_zones = [item.zone for item in analyses if item.avoidance_type == SprayAvoidanceType.NONE]
    all_zones = [item.zone for item in analyses]
    cache: dict[tuple[str, ...], _GroupResolution] = {}

    def resolve(group: list[SprayZoneConflict]) -> _GroupResolution:
        key = tuple(sorted(item.zone.obstacle_id for item in group))
        if key not in cache:
            cache[key] = _resolve_group(
                frame, traffic_pass, group, free_zones + [item.zone for item in group], ctx
            )
        return cache[key]

    groups: list[list[SprayZoneConflict]] = [[item] for item in conflicts]
    for _ in range(len(conflicts) + 1):
        ordered = sorted(
            ((group, resolve(group)) for group in groups), key=lambda pair: pair[1].footprint[0]
        )
        merged: list[list[SprayZoneConflict]] = []
        current, current_fp = list(ordered[0][0]), ordered[0][1].footprint
        changed = False
        for group, resolution in ordered[1:]:
            if resolution.footprint[0] <= current_fp[1] + 1e-6:
                current = current + list(group)
                current_fp = (current_fp[0], max(current_fp[1], resolution.footprint[1]))
                changed = True
            else:
                merged.append(current)
                current, current_fp = list(group), resolution.footprint
        merged.append(current)
        groups = merged
        if not changed:
            break

    replacements: list[_Replacement] = []
    for group in groups:
        resolution = resolve(group)
        replacement = resolution.replacement
        if replacement is not None:
            residual = spray_boom_clearance_violations(
                replacement.points,
                all_zones,
                ctx.half_boom_m,
                tolerance_m=_CLEARANCE_TOLERANCE_M,
            )
            if residual:
                resolution = _GroupResolution(
                    SprayAvoidanceType.UNRESOLVED,
                    None,
                    resolution.footprint,
                    f"barra invade a zona de {residual[0][1]} no trecho desviado",
                )
                replacement = None
        if replacement is not None:
            replacements.append(replacement)
        for item in group:
            records.append(_record(traffic_pass, item, ctx, resolution.avoidance_type, resolution))

    if not replacements:
        return traffic_pass, None, records
    replacements.sort(key=lambda item: item.entry_s)
    final_points = _assemble_pass(frame, replacements)
    new_pass = _with_points(traffic_pass, final_points)
    resolved_ids = [
        rec.obstacle_id
        for rec in records
        if rec.avoidance_type
        in (SprayAvoidanceType.LATERAL.value, SprayAvoidanceType.FULL_CONTOUR.value)
    ]
    contour = [item for item in replacements if item.avoidance_type == SprayAvoidanceType.FULL_CONTOUR]
    action = contour[0].action if contour else AvoidanceAction.LATERAL.value
    radius = max(item.application_radius_m for item in (contour or replacements))
    path = AvoidedPath(
        fs_id=str(uuid4()),
        source_id=traffic_pass.fs_id,
        pass_id=traffic_pass.pass_no,
        row_id=None,
        operation_id=traffic_pass.operation_id,
        machine_id=getattr(ctx.machine, "machine_id", ""),
        original_segment=Segment(frame.points[0], frame.points[-1]),
        modified_points=tuple(final_points),
        entry_point=final_points[0],
        exit_point=final_points[-1],
        obstacle_id="+".join(dict.fromkeys(resolved_ids)),
        application_radius_m=radius,
        action=action,
        returns_to_guidance=True,
    )
    return new_pass, path, records


def _record(
    traffic_pass: TrafficPass,
    item: SprayZoneConflict,
    ctx: _SprayPassContext,
    kind: SprayAvoidanceType,
    resolution: _GroupResolution | None,
) -> SprayConflictRecord:
    replacement = resolution.replacement if resolution is not None else None
    side = replacement.side if replacement is not None else ""
    if kind == SprayAvoidanceType.NONE:
        required = 0.0
    else:
        required = item.required_for_side(side)
    if kind == SprayAvoidanceType.UNRESOLVED and resolution is not None:
        entry, exit_ = resolution.footprint
    elif replacement is not None:
        entry, exit_ = replacement.entry_s, replacement.exit_s
    else:
        entry = exit_ = None
    if kind == SprayAvoidanceType.UNRESOLVED:
        detour = tuple(_original_stretch(traffic_pass, item))
    else:
        detour = replacement.points if replacement is not None else ()
    return SprayConflictRecord(
        pass_id=traffic_pass.pass_no,
        pass_fs_id=traffic_pass.fs_id,
        obstacle_id=item.zone.obstacle_id,
        avoidance_type=kind.value,
        side=side,
        boom_width_m=ctx.boom_width_m,
        safe_radius_m=item.zone.safe_radius_m,
        required_offset_m=required,
        entry_station_m=entry,
        exit_station_m=exit_,
        minimum_turn_radius_m=ctx.turn_radius_m,
        lateral_distance_m=item.d_center,
        applied_offset_m=replacement.applied_offset_m if replacement is not None else 0.0,
        reason=resolution.reason if resolution is not None else "",
        detour_points=detour,
    )


def _original_stretch(traffic_pass: TrafficPass, item: SprayZoneConflict) -> list[Point]:
    """Trecho original em conflito (desenhado na camada 23 quando UNRESOLVED)."""
    frame = _PassFrame(_traffic_pass_points(traffic_pass))
    lo = max(0.0, item.s_min)
    hi = min(frame.length, item.s_max)
    if hi - lo <= 1e-6:
        return []
    inner = [frame.points[i] for i, s in enumerate(frame.stations) if lo < s < hi]
    return [frame.point(lo)] + inner + [frame.point(hi)]


def _resolve_group(
    frame: _PassFrame,
    traffic_pass: TrafficPass,
    group: list[SprayZoneConflict],
    validation_zones: list[SpraySafetyZone],
    ctx: _SprayPassContext,
) -> _GroupResolution:
    from ..domain.avoidance_configuration import SPRAY_SIDE_AUTO

    s_lo = min(item.s_min for item in group)
    s_hi = max(item.s_max for item in group)
    reasons: list[str] = []
    central = any(item.avoidance_type == SprayAvoidanceType.FULL_CONTOUR for item in group)
    if central:
        reasons.append("obstaculo no corredor central da maquina")
    else:
        preference = getattr(ctx.config, "side_preference", SPRAY_SIDE_AUTO) or SPRAY_SIDE_AUTO
        sides = [
            ("left", 1.0, max(item.left_required_m for item in group)),
            ("right", -1.0, max(item.right_required_m for item in group)),
        ]
        if preference != SPRAY_SIDE_AUTO:
            sides = [entry for entry in sides if entry[0] == preference]
        candidates: list[_Replacement] = []
        for name, sign, required in sides:
            offset = required + _LATERAL_CLEARANCE_PAD_M
            if offset > ctx.boom_width_m + 1e-9:
                reasons.append(f"{name}: deslocamento {offset:.2f} m maior que a barra")
                continue
            replacement, why = _try_lateral(
                frame, name, sign, offset, s_lo, s_hi, validation_zones, ctx
            )
            if replacement is None:
                reasons.append(f"{name}: {why}")
                continue
            candidates.append(replacement)
        if candidates:
            best = min(candidates, key=lambda item: (item.added_length_m, item.applied_offset_m))
            return _GroupResolution(
                SprayAvoidanceType.LATERAL, best, (best.entry_s, best.exit_s)
            )
    replacement, why = _try_contour(frame, traffic_pass, group, validation_zones, ctx)
    if replacement is not None:
        return _GroupResolution(
            SprayAvoidanceType.FULL_CONTOUR,
            replacement,
            (replacement.entry_s, replacement.exit_s),
            "; ".join(reasons),
        )
    reasons.append(f"contorno: {why}")
    return _GroupResolution(SprayAvoidanceType.UNRESOLVED, None, (s_lo, s_hi), "; ".join(reasons))


def _lateral_detour_points(
    frame: _PassFrame,
    sign: float,
    offset: float,
    plateau_start: float,
    plateau_end: float,
    turn_radius: float,
) -> tuple[float, float, list[Point]] | None:
    """original -> transicao -> arco -> trecho seguro -> arco -> transicao -> original."""
    from math import ceil

    ramp = lateral_ramp_length_m(offset, turn_radius)
    entry = plateau_start - ramp
    exit_ = plateau_end + ramp
    if entry < 0.0 or exit_ > frame.length:
        return None
    samples = max(_RAMP_MIN_SAMPLES, int(ceil(ramp / _RAMP_MAX_STEP_M)))
    stations: dict[float, float] = {}
    for k in range(samples + 1):
        u = ramp * k / samples
        stations[entry + u] = lateral_ramp_offset_m(u, offset, turn_radius)
        stations[plateau_end + u] = offset - lateral_ramp_offset_m(u, offset, turn_radius)
    span = plateau_end - plateau_start
    steps = max(1, int(ceil(span / _PLATEAU_STEP_M)))
    for k in range(steps + 1):
        stations[plateau_start + span * k / steps] = offset

    def profile(s: float) -> float:
        if s <= plateau_start:
            return lateral_ramp_offset_m(s - entry, offset, turn_radius)
        if s >= plateau_end:
            return offset - lateral_ramp_offset_m(s - plateau_end, offset, turn_radius)
        return offset

    for s in frame.stations:
        if entry < s < exit_:
            stations[s] = profile(s)
    ordered = sorted(stations)
    points = [frame.point(s, sign * stations[s]) for s in ordered]
    points[0] = frame.point(entry, 0.0)
    points[-1] = frame.point(exit_, 0.0)
    return entry, exit_, _dedupe(points)


def _try_lateral(
    frame: _PassFrame,
    side: str,
    sign: float,
    offset: float,
    s_lo: float,
    s_hi: float,
    validation_zones: list[SpraySafetyZone],
    ctx: _SprayPassContext,
) -> tuple[_Replacement | None, str]:
    from .line_geometry import polyline_length

    prep = float(getattr(ctx.config, "preparation_distance_m", 0.0) or 0.0)
    ret = float(getattr(ctx.config, "return_distance_m", 0.0) or 0.0)
    radius = float(ctx.turn_radius_m)
    for _ in range(_MAX_EXTEND_ITERATIONS):
        plateau_start, plateau_end = s_lo - prep, s_hi + ret
        built = _lateral_detour_points(frame, sign, offset, plateau_start, plateau_end, radius)
        if built is None:
            return None, "sem espaco na passada para a transicao com o raio minimo"
        entry, exit_, points = built
        if ctx.allowed_area and not _points_inside(points, ctx.allowed_area):
            return None, "desvio sai do limite do talhao"
        violations = spray_boom_clearance_violations(points, validation_zones, ctx.half_boom_m)
        if not violations:
            return (
                _Replacement(
                    entry_s=entry,
                    exit_s=exit_,
                    points=tuple(points),
                    avoidance_type=SprayAvoidanceType.LATERAL,
                    side=side,
                    applied_offset_m=offset,
                    action=AvoidanceAction.LATERAL.value,
                    application_radius_m=ctx.half_boom_m
                    + max(zone.safe_radius_m for zone in validation_zones),
                    added_length_m=polyline_length(points) - (exit_ - entry),
                ),
                "",
            )
        grow_prep = grow_ret = False
        for center, _oid, _clearance in violations:
            station, _lat = frame.locate(center)
            if station < plateau_start - 1e-6:
                grow_prep = True
            elif station > plateau_end + 1e-6:
                grow_ret = True
            else:
                return None, f"barra encontra {_oid} no trecho seguro"
        prep += _EXTEND_STEP_M if grow_prep else 0.0
        ret += _EXTEND_STEP_M if grow_ret else 0.0
    return None, "transicao nao libera a barra"


def _points_inside(points, allowed_area: MultiPolygon) -> bool:
    from .line_geometry import points_in_multipolygon

    return all(points_in_multipolygon(list(points), allowed_area))


def tangent_contour_profile(
    s_center: float,
    d_center: float,
    ring_radius_m: float,
    fillet_radius_m: float,
    sign: float,
    *,
    step_m: float = _RAMP_MAX_STEP_M,
) -> list[tuple[float, float]] | None:
    """Contorno em (estacao, lateral): reta -> filete -> arco concentrico -> filete -> reta.

    Os filetes (raio = raio minimo de giro) sao tangentes a linha original e ao
    arco em torno do obstaculo, entao o rumo varia sem quina. ``sign`` = +1
    contorna pela esquerda. None quando exigiria rumo alem de 90 graus (reversao).
    """
    from math import atan2, ceil, cos, pi, sin, sqrt

    rc, rf = float(ring_radius_m), float(fillet_radius_m)
    dc = sign * float(d_center)
    if rc <= 0.0 or rf <= 0.0 or dc + rc <= 0.0 or dc > rf:
        return None
    dx = sqrt((rf + rc) ** 2 - (rf - dc) ** 2)
    f1, f2, o = (s_center - dx, rf), (s_center + dx, rf), (s_center, dc)

    def arc(center: Point, radius: float, start: float, end: float) -> list[Point]:
        sweep = end - start
        count = max(2, int(ceil(abs(sweep) * radius / step_m)))
        return [
            (
                center[0] + radius * cos(start + sweep * k / count),
                center[1] + radius * sin(start + sweep * k / count),
            )
            for k in range(count + 1)
        ]

    fillet_in_end = atan2(o[1] - f1[1], o[0] - f1[0])
    ring_start = atan2(f1[1] - o[1], f1[0] - o[0])
    ring_end = atan2(f2[1] - o[1], f2[0] - o[0])
    while ring_end >= ring_start:
        ring_end -= 2.0 * pi
    fillet_out_start = atan2(o[1] - f2[1], o[0] - f2[0])
    fillet_out_end = -pi / 2.0
    while fillet_out_end <= fillet_out_start:
        fillet_out_end += 2.0 * pi
    profile = arc(f1, rf, -pi / 2.0, fillet_in_end)
    profile += arc(o, rc, ring_start, ring_end)[1:]
    profile += arc(f2, rf, fillet_out_start, fillet_out_end)[1:]
    profile[0] = (f1[0], 0.0)
    profile[-1] = (f2[0], 0.0)
    return [(s, sign * d) for s, d in profile]


def _try_contour(
    frame: _PassFrame,
    traffic_pass: TrafficPass,
    group: list[SprayZoneConflict],
    validation_zones: list[SpraySafetyZone],
    ctx: _SprayPassContext,
) -> tuple[_Replacement | None, str]:
    """FULL_CONTOUR so no trecho em conflito; anel legado so para orbita/poligonos."""
    reasons: list[str] = []
    circular = all(item.zone.circular for item in group)
    if getattr(ctx.config, "orbit_360", False) or not circular:
        replacement, why = _try_ring_contour(frame, traffic_pass, group, ctx)
        if replacement is not None:
            return replacement, ""
        reasons.append(why)
    replacement, why = _try_tangent_contour(frame, group, validation_zones, ctx)
    if replacement is not None:
        return replacement, ""
    reasons.append(why)
    return None, "; ".join(reasons)


def _try_tangent_contour(
    frame: _PassFrame,
    group: list[SprayZoneConflict],
    validation_zones: list[SpraySafetyZone],
    ctx: _SprayPassContext,
) -> tuple[_Replacement | None, str]:
    from ..domain.avoidance_configuration import SPRAY_SIDE_AUTO
    from .line_geometry import polyline_length
    from .obstacle_grouping_engine import enclosing_circle

    covers = [(item.zone.center, _zone_extent_m(item.zone)) for item in group]
    center, radius = enclosing_circle(covers) if len(covers) > 1 else covers[0]
    turn = float(ctx.turn_radius_m)
    ring = max(ctx.half_boom_m + radius + _CONTOUR_RADIUS_PAD_M, turn)
    s_c, d_c = frame.locate(center)
    preference = getattr(ctx.config, "side_preference", SPRAY_SIDE_AUTO) or SPRAY_SIDE_AUTO
    sides = [("left", 1.0), ("right", -1.0)]
    if preference != SPRAY_SIDE_AUTO:
        sides = [entry for entry in sides if entry[0] == preference]
    reasons: list[str] = []
    candidates: list[_Replacement] = []
    for name, sign in sides:
        profile = tangent_contour_profile(s_c, d_c, ring, turn, sign)
        if profile is None:
            reasons.append(f"{name}: contorno exigiria reverter o rumo")
            continue
        entry, exit_ = profile[0][0], profile[-1][0]
        if entry < 0.0 or exit_ > frame.length:
            reasons.append(f"{name}: sem espaco na passada para o contorno")
            continue
        points = _dedupe([frame.point(s, d) for s, d in profile])
        if ctx.allowed_area and not _points_inside(points, ctx.allowed_area):
            reasons.append(f"{name}: contorno sai do limite do talhao")
            continue
        violations = spray_boom_clearance_violations(points, validation_zones, ctx.half_boom_m)
        if violations:
            reasons.append(f"{name}: barra encontra {violations[0][1]} no contorno")
            continue
        candidates.append(
            _Replacement(
                entry_s=entry,
                exit_s=exit_,
                points=tuple(points),
                avoidance_type=SprayAvoidanceType.FULL_CONTOUR,
                side=name,
                applied_offset_m=max(abs(d) for _s, d in profile),
                action=AvoidanceAction.CONTOUR.value,
                application_radius_m=ring,
                added_length_m=polyline_length(points) - (exit_ - entry),
            )
        )
    if not candidates:
        return None, "; ".join(reasons) or "contorno indisponivel"
    return min(candidates, key=lambda item: (item.added_length_m, item.applied_offset_m)), ""


def _try_ring_contour(
    frame: _PassFrame,
    traffic_pass: TrafficPass,
    group: list[SprayZoneConflict],
    ctx: _SprayPassContext,
) -> tuple[_Replacement | None, str]:
    """Anel do motor legado (raio = meia barra + zona), recortado so neste trecho."""
    from dataclasses import replace

    from .line_geometry import polyline_length

    members = [
        ctx.obstacles_by_id[item.zone.obstacle_id]
        for item in group
        if item.zone.obstacle_id in ctx.obstacles_by_id
    ]
    if not members:
        return None, "obstaculo sem geometria"
    inflated = [
        replace(
            obstacle,
            application_radius_override_m=obstacle.application_radius_m(ctx.machine)
            + _CONTOUR_RADIUS_PAD_M,
        )
        for obstacle in members
    ]
    ring_config = replace(
        ctx.config,
        mode=AvoidanceMode.CONCENTRIC_RING,
        minimum_turn_radius_m=ctx.turn_radius_m,
        minimum_deviation=False,
    )
    envelopes = merge_adjacent_envelopes(
        build_all_envelopes(inflated, ctx.machine), ring_config.merge_adjacent_envelopes_m
    )
    base = _with_points(traffic_pass, frame.points)
    try:
        result = _avoid_traffic_pass(
            base, inflated, envelopes, ctx.machine, ring_config, allowed_area=ctx.allowed_area
        )
    except Exception as exc:  # geometria degenerada no anel legado
        return None, f"anel indisponivel ({exc})"
    if not result:
        return None, "anel indisponivel"
    extracted = _extract_replacement(frame, result[-1].modified_points)
    if extracted is None:
        return None, "anel nao retorna a linha original dentro da passada"
    entry, exit_, points = extracted
    from .line_geometry import segment_samples

    # Densificar nao muda o desenho; evita a re-suavizacao (< 48 vertices) do pipeline.
    points = _dedupe(segment_samples(points, densify_m=1.0))
    if ctx.allowed_area and not _points_inside(points, ctx.allowed_area):
        return None, "anel sai do limite do talhao"
    if min_turning_radius_m(points) < _CONTOUR_CURVATURE_FACTOR * float(ctx.turn_radius_m):
        return None, "anel exige raio menor que o raio minimo do pulverizador"
    laterals = [frame.locate(p)[1] for p in points]
    peak = max(laterals, key=abs)
    return (
        _Replacement(
            entry_s=entry,
            exit_s=exit_,
            points=tuple(points),
            avoidance_type=SprayAvoidanceType.FULL_CONTOUR,
            side="left" if peak >= 0 else "right",
            applied_offset_m=abs(peak),
            action=result[-1].action,
            application_radius_m=result[-1].application_radius_m,
            added_length_m=polyline_length(points) - (exit_ - entry),
        ),
        "",
    )


def _extract_replacement(
    frame: _PassFrame, modified
) -> tuple[float, float, list[Point]] | None:
    """Recorta do caminho legado so o trecho fora da linha original."""
    pts = _dedupe(list(modified))
    located = [frame.locate(p) for p in pts]
    off = [
        abs(lat) > _ON_LINE_TOLERANCE_M
        or s < -_ON_LINE_TOLERANCE_M
        or s > frame.length + _ON_LINE_TOLERANCE_M
        for s, lat in located
    ]
    if not any(off):
        return None
    first = off.index(True)
    last = len(off) - 1 - off[::-1].index(True)
    if first == 0 or last == len(pts) - 1:
        return None
    entry = located[first - 1][0]
    exit_ = located[last + 1][0]
    if not (0.0 <= entry < exit_ <= frame.length):
        return None
    points = [frame.point(entry)] + pts[first : last + 1] + [frame.point(exit_)]
    return entry, exit_, _dedupe(points)


def _assemble_pass(frame: _PassFrame, replacements: list[_Replacement]) -> list[Point]:
    """ANTES = original, DURANTE = desvio, DEPOIS = original (sem offset permanente)."""
    out: list[Point] = []
    cursor = 0.0
    for item in replacements:
        out.extend(
            p for p, s in zip(frame.points, frame.stations) if cursor - 1e-9 <= s < item.entry_s - 1e-9
        )
        out.extend(item.points)
        cursor = item.exit_s + 1e-9
    out.extend(p for p, s in zip(frame.points, frame.stations) if s > cursor)
    return _dedupe(out)


def spray_conflict_counts(records: list[SprayConflictRecord]) -> dict[str, int]:
    counts = {kind.value: 0 for kind in SprayAvoidanceType}
    for record in records:
        counts[record.avoidance_type] = counts.get(record.avoidance_type, 0) + 1
    return counts


def spray_pass_avoidance_types(records: list[SprayConflictRecord]) -> dict[int, dict[str, str]]:
    """Pior classificacao por passada (atributos em 11_Passadas)."""
    out: dict[int, dict[str, str]] = {}
    for record in records:
        if record.pass_role != "pass":
            continue
        entry = out.setdefault(record.pass_id, {"avoidance_type": "NONE", "obstacle_ids": ""})
        if (
            SPRAY_AVOIDANCE_SEVERITY[record.avoidance_type]
            > SPRAY_AVOIDANCE_SEVERITY[entry["avoidance_type"]]
        ):
            entry["avoidance_type"] = record.avoidance_type
        if record.avoidance_type != SprayAvoidanceType.NONE.value:
            ids = [item for item in entry["obstacle_ids"].split(",") if item]
            if record.obstacle_id not in ids:
                ids.append(record.obstacle_id)
            entry["obstacle_ids"] = ",".join(ids)
    return out
