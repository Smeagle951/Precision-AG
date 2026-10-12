# -*- coding: utf-8 -*-
"""Desvio de obstaculos para plantio (cinematica trator + plantadeira)."""

from __future__ import annotations

from math import atan2
from uuid import uuid4

from ..domain.machine_model import PlanterMachine
from ..domain.obstacle_model import Obstacle, ObstacleType
from ..domain.planting_avoidance_configuration import (
    PlantingAvoidanceConfiguration,
    PlantingAvoidanceStrategy,
)
from ..domain.planting_avoidance_result import PlantingAvoidanceResult
from ..domain.planting_kinematics import PlantingKinematics
from .application_obstacle_engine import AvoidanceAction, AvoidedPath
from .guidance_engine import TrafficPass
from .line_geometry import (
    MultiPolygon,
    Point,
    Segment,
    add,
    decimate_polyline,
    distance,
    line_circle_intersections,
    mul,
    normalize,
    perpendicular_left,
    point_at_segment_t,
    point_in_multipolygon,
    sub,
)
from .obstacle_buffer_engine import (
    ForbiddenRegion,
    build_all_planting_forbidden_regions,
    forbidden_hits_segment,
    merge_planting_forbidden_regions,
)
from .planting_coverage_engine import compute_coverage_impact
from .planting_kinematics_engine import (
    heading_from_points,
    tractor_envelope_at,
)
from .spatial_index import UniformGridIndex, build_region_index


class PlantingObstacleEngineError(ValueError):
    """Erro no motor de desvio de plantio."""


class ConflictType:
    IMPLEMENT_EDGE = "implement_edge"
    TRACTOR_CENTER = "tractor_center"
    GROUPED = "grouped"
    POLYGON = "polygon"
    NONE = "none"


def classify_conflict(
    segment: Segment,
    region: ForbiddenRegion,
    kinematics: PlantingKinematics,
    *,
    is_grouped: bool,
    is_polygon: bool,
    path_points: tuple[Point, ...] | list[Point] | None = None,
    at_index: int | None = None,
) -> str:
    """Classifica o tipo de conflito trator/implemento x zona proibida."""
    if is_polygon:
        return ConflictType.POLYGON
    if is_grouped:
        return ConflictType.GROUPED

    mid = point_at_segment_t(segment, 0.5)
    from .line_geometry import segment_travel_direction

    direction = segment_travel_direction(segment, path_points, at_index=at_index)
    heading = atan2(direction[1], direction[0])
    # A regiao ja foi expandida por W/2 em build_planting_forbidden_region.
    # Testar novamente a faixa deslocada somaria a meia largura duas vezes.
    if forbidden_hits_segment(region, segment.start, segment.end):
        tractor_env = tractor_envelope_at(mid, heading, kinematics)
        axis_hits = distance(region.center, mid) <= region.tractor_clearance_radius_m + 0.05
        tractor_hits = _polygon_hits_circle(
            tractor_env, region.center, region.tractor_clearance_radius_m
        )
        if axis_hits or tractor_hits:
            return ConflictType.TRACTOR_CENTER
        return ConflictType.IMPLEMENT_EDGE

    tractor_env = tractor_envelope_at(mid, heading, kinematics)

    tractor_hits = _polygon_hits_circle(tractor_env, region.center, region.tractor_clearance_radius_m)
    # Eixo do trator dentro do raio de bitola.
    axis_hits = distance(region.center, mid) <= region.tractor_clearance_radius_m + 0.05
    # Distancia lateral do centro da trajetoria ao obstaculo.
    lat = _point_line_distance(region.center, segment)

    if axis_hits or tractor_hits:
        return ConflictType.TRACTOR_CENTER
    return ConflictType.NONE


def resolve_strategy(
    conflict_type: str,
    config: PlantingAvoidanceConfiguration,
    *,
    is_polygon: bool = False,
) -> PlantingAvoidanceStrategy:
    if config.strategy != PlantingAvoidanceStrategy.AUTO:
        return config.strategy
    # Sempre contornar o LIMITE do obstaculo (geometria real / raio informado).
    # Nunca gerar anel fechado em volta do obstaculo.
    if conflict_type == ConflictType.IMPLEMENT_EDGE and not is_polygon:
        # Extremidade: ainda pode usar deslocamento lateral suave se pedido;
        # em AUTO preferimos contorno do limite para nao quebrar a linha.
        return PlantingAvoidanceStrategy.CONTOUR
    return PlantingAvoidanceStrategy.CONTOUR


def lateral_limit_for_pass(traffic_pass: TrafficPass) -> float:
    """Deslocamento lateral maximo do desvio: meio espacamento entre passadas.

    Acima disso o trator cruzaria o centro da passada vizinha, gerando remonte
    de um lado e falha do outro.
    """
    spacing = float(getattr(traffic_pass, "spacing_m", 0.0) or 0.0)
    if spacing <= 0.0:
        return float("inf")
    return spacing / 2.0


def _build_path_within_lateral_limit(
    segment: Segment,
    region: ForbiddenRegion,
    kinematics: PlantingKinematics,
    strategy: PlantingAvoidanceStrategy,
    config: PlantingAvoidanceConfiguration,
    *,
    obstacle_by_id: dict | None,
    lateral_limit_m: float,
    finalize: bool = True,
    path_points: tuple[Point, ...] | list[Point] | None = None,
    at_index: int | None = None,
):
    """Desvio que cabe na faixa sem abrir mao da folga da plantadeira.

    A folga nominal (meia largura do implemento + margem) SEMPRE vale. Plantadeira
    de 20 m -> linha do trator a 10 m do obstaculo; 10 m a esquerda e 10 m a
    direita. O teto lateral (meio espacamento) so evita remonte na passada
    vizinha — NUNCA autoriza encolher o desvio ate a bitola do trator (isso
    colocava a ponta da plantadeira dentro do obstaculo, a 3–7 m).
    """
    from .obstacle_contour_path import polyline_max_lateral_offset_m

    built = _build_path(
        segment,
        region,
        kinematics,
        strategy,
        config,
        obstacle_by_id=obstacle_by_id,
        finalize=finalize,
        path_points=path_points,
        at_index=at_index,
    )
    if built is None or lateral_limit_m == float("inf"):
        return built, False

    ideal_r = max(float(region.implement_clearance_radius_m), 0.1)
    ceiling = max(lateral_limit_m, ideal_r)
    if polyline_max_lateral_offset_m(built[0], segment) <= ceiling + 1e-6:
        return built, False
    # Raio de giro empurrou alem do teto: mantem a folga da plantadeira.
    # Encolher abaixo de W/2 seria colisao do implemento — proibido.
    return built, False


_PASS_POLYLINE_MAX_POINTS = 280
_PASS_CANDIDATE_MARGIN_M = 3.0


def apply_planting_avoidance_to_passes(
    passes: list[TrafficPass],
    obstacles: list[Obstacle],
    kinematics: PlantingKinematics,
    config: PlantingAvoidanceConfiguration,
    planter: PlanterMachine,
    *,
    allowed_area: MultiPolygon | None = None,
    progress=None,
) -> tuple[list[TrafficPass], list[PlantingAvoidanceResult], list[AvoidedPath]]:
    """Aplica desvio de plantio nas passadas do trator."""
    if not config.is_enabled() or not obstacles:
        return passes, [], []

    kinematics.validate()
    config.validate()

    regions = merge_planting_forbidden_regions(
        build_all_planting_forbidden_regions(obstacles, kinematics, config),
        config.merge_obstacles_m,
    )
    obstacle_by_id = {obs.obstacle_id: obs for obs in obstacles}
    # Indice construido UMA vez: passadas longe de tudo saem sem varrer regioes.
    region_index = build_region_index(regions) if len(regions) > 8 else None

    modified: list[TrafficPass] = []
    results: list[PlantingAvoidanceResult] = []
    avoided: list[AvoidedPath] = []

    pass_count = len(passes)
    for pass_index, traffic_pass in enumerate(passes):
        if progress is not None and pass_count > 1:
            from .generation_progress import report_progress

            local = int(100 * pass_index / max(1, pass_count - 1))
            report_progress(
                progress,
                local,
                f"Plantio: passada {pass_index + 1}/{pass_count}",
            )
        work_pass = traffic_pass
        processed_regions: set[tuple[str, ...]] = set()
        pass_results: list[tuple[PlantingAvoidanceResult, ForbiddenRegion]] = []
        corridor = traffic_pass.guidance_segment
        pass_pts = list(work_pass.line_points())
        if len(pass_pts) >= 2 and corridor.length < 1.0:
            try:
                from .line_geometry import ensure_segment_span

                corridor = ensure_segment_span(corridor, pass_pts, at_index=0)
            except ValueError:
                corridor = Segment(pass_pts[0], pass_pts[min(1, len(pass_pts) - 1)])
        candidate_regions = _regions_near_pass(
            corridor,
            regions,
            kinematics,
            index=region_index,
            path_points=pass_pts,
        )
        initial_hit_count = sum(
            1 for region in candidate_regions if _region_hits_pass(corridor, region, kinematics)
        )
        max_iters = min(max(initial_hit_count, 1) + 1, 48)

        for _ in range(max_iters):
            if len(processed_regions) >= len(candidate_regions):
                break
            if initial_hit_count > 0 and len(processed_regions) >= initial_hit_count:
                break
            pts = work_pass.line_points()
            segment = work_pass.guidance_segment
            hit, stitch_range, segment = _locate_pass_hit(
                pts, segment, candidate_regions, kinematics, exclude=processed_regions
            )
            if hit is None:
                break

            stitch_idx = stitch_range[0] if stitch_range is not None else 0
            try:
                from .line_geometry import ensure_segment_span

                segment = ensure_segment_span(segment, pts, at_index=stitch_idx)
            except ValueError:
                processed_regions.add(tuple(sorted(hit.group_ids)))
                continue

            use_finalize = (initial_hit_count - len(processed_regions)) <= 1

            is_grouped = len(hit.group_ids) > 1
            is_polygon = any(
                obstacle_by_id.get(oid) is not None
                and obstacle_by_id[oid].obstacle_type == ObstacleType.POLYGON
                for oid in hit.group_ids
            )
            conflict = classify_conflict(
                segment,
                hit,
                kinematics,
                is_grouped=is_grouped,
                is_polygon=is_polygon,
                path_points=pts,
                at_index=stitch_idx,
            )
            if conflict == ConflictType.NONE:
                conflict = ConflictType.IMPLEMENT_EDGE

            strategy = resolve_strategy(
                conflict,
                config,
                is_polygon=is_polygon,
            )
            build_segment = segment
            build_stitch = stitch_range
            if stitch_range is not None and len(pts) >= 3:
                build_segment, build_stitch = _expand_stitch_for_build(
                    pts,
                    stitch_range,
                    min_length_m=_min_build_length_m(kinematics, hit),
                )
            built, _limited = _build_path_within_lateral_limit(
                build_segment,
                hit,
                kinematics,
                strategy,
                config,
                obstacle_by_id=obstacle_by_id,
                lateral_limit_m=lateral_limit_for_pass(traffic_pass),
                finalize=use_finalize,
                path_points=pts,
                at_index=build_stitch[0] if build_stitch is not None else stitch_idx,
            )
            if built is None:
                processed_regions.add(tuple(sorted(hit.group_ids)))
                continue

            path_points, entry, arc, exit_pts, return_pts, tractor_radius = built
            if len(pts) >= 3:
                from .obstacle_contour_path import stitch_avoidance_into_polyline

                if build_stitch is None:
                    break
                path_points = list(
                    stitch_avoidance_into_polyline(
                        pts,
                        build_stitch[0],
                        build_stitch[1],
                        _compact_pass_polyline(path_points, max_points=96),
                    )
                )
            else:
                path_points = list(path_points)
            path_points = _compact_pass_polyline(path_points, max_points=_PASS_POLYLINE_MAX_POINTS)
            gap, overlap = 0.0, 0.0
            if len(pass_results) == 0:
                gap, overlap = compute_coverage_impact(
                    original_path=(segment.start, segment.end),
                    avoidance_path=tuple(path_points),
                    region=hit,
                    kinematics=kinematics,
                )
            affected = tuple(range(1, (kinematics.row_count or planter.row_count or 1) + 1))
            result = PlantingAvoidanceResult(
                fs_id=str(uuid4()),
                pass_id=traffic_pass.pass_no,
                obstacle_ids=hit.group_ids,
                strategy_used=strategy,
                conflict_type=conflict,
                original_tractor_path=(segment.start, segment.end),
                avoidance_path=tuple(path_points),
                entry_transition=tuple(entry),
                avoidance_arc=tuple(arc),
                exit_transition=tuple(exit_pts),
                return_path=tuple(return_pts),
                affected_rows=affected,
                coverage_gap_m2=gap,
                overlap_area_m2=overlap,
                returns_to_guidance=_returns_to_guidance(segment, path_points),
                tractor_radius_m=tractor_radius,
            )
            pass_results.append((result, hit))
            processed_regions.add(tuple(sorted(hit.group_ids)))
            new_seg = Segment(path_points[0], path_points[-1])
            work_pass = TrafficPass(
                pass_no=traffic_pass.pass_no,
                fs_id=traffic_pass.fs_id,
                operation_id=traffic_pass.operation_id,
                spacing_m=traffic_pass.spacing_m,
                width_m=traffic_pass.width_m,
                offset_m=traffic_pass.offset_m,
                azimuth_deg=traffic_pass.azimuth_deg,
                direction=traffic_pass.direction,
                clipped_segment=traffic_pass.clipped_segment,
                guidance_segment=new_seg,
                path_points=tuple(path_points),
            )

        if pass_results and work_pass.path_points:
            raw_pts = _dedupe(list(work_pass.path_points))
            corridor_seg = Segment(corridor.start, corridor.end)
            from .obstacle_contour_path import polyline_max_lateral_offset_m, smooth_avoidance_trajectory

            if len(raw_pts) > 72:
                final_pts = list(raw_pts)
            else:
                final_pts = _finalize_avoidance_path(raw_pts)
            final_off = polyline_max_lateral_offset_m(final_pts, corridor_seg)
            raw_off = polyline_max_lateral_offset_m(raw_pts, corridor_seg)
            if final_off > raw_off + 1e-5:
                final_pts = smooth_avoidance_trajectory(
                    raw_pts,
                    densify_m=0.75,
                    chaikin_iterations=0,
                    max_points=240,
                    preserve_circular=True,
                )
            if allowed_area:
                from .line_geometry import clip_polyline_to_multipolygon, polyline_length

                clipped_chunks = clip_polyline_to_multipolygon(final_pts, allowed_area)
                if clipped_chunks:
                    final_pts = max(
                        clipped_chunks,
                        key=lambda chunk: polyline_length(chunk) if len(chunk) > 1 else 0.0,
                    )
                    if len(final_pts) < 3 and len(clipped_chunks) > 1:
                        final_pts = _stitch_clipped_chunks(clipped_chunks)
            work_pass = TrafficPass(
                pass_no=traffic_pass.pass_no,
                fs_id=traffic_pass.fs_id,
                operation_id=traffic_pass.operation_id,
                spacing_m=traffic_pass.spacing_m,
                width_m=traffic_pass.width_m,
                offset_m=traffic_pass.offset_m,
                azimuth_deg=traffic_pass.azimuth_deg,
                direction=traffic_pass.direction,
                clipped_segment=traffic_pass.clipped_segment,
                guidance_segment=Segment(final_pts[0], final_pts[-1]),
                path_points=tuple(final_pts),
            )
            if pass_results:
                last_result, _last_hit = pass_results[-1]
                pass_results[-1] = (
                    PlantingAvoidanceResult(
                        fs_id=last_result.fs_id,
                        pass_id=last_result.pass_id,
                        obstacle_ids=last_result.obstacle_ids,
                        strategy_used=last_result.strategy_used,
                        conflict_type=last_result.conflict_type,
                        original_tractor_path=last_result.original_tractor_path,
                        avoidance_path=tuple(final_pts),
                        entry_transition=last_result.entry_transition,
                        avoidance_arc=last_result.avoidance_arc,
                        exit_transition=last_result.exit_transition,
                        return_path=last_result.return_path,
                        affected_rows=last_result.affected_rows,
                        coverage_gap_m2=last_result.coverage_gap_m2,
                        overlap_area_m2=last_result.overlap_area_m2,
                        returns_to_guidance=_returns_to_guidance(
                            Segment(corridor.start, corridor.end), final_pts
                        ),
                        tractor_radius_m=last_result.tractor_radius_m,
                    ),
                    _last_hit,
                )

        for result, hit in pass_results:
            results.append(result)
        if pass_results:
            final_result, final_hit = pass_results[-1]
            all_obs_ids: list[str] = []
            for item, _ in pass_results:
                for oid in item.obstacle_ids:
                    if oid not in all_obs_ids:
                        all_obs_ids.append(oid)
            merged = PlantingAvoidanceResult(
                fs_id=final_result.fs_id,
                pass_id=final_result.pass_id,
                obstacle_ids=tuple(all_obs_ids),
                strategy_used=final_result.strategy_used,
                conflict_type=final_result.conflict_type,
                original_tractor_path=final_result.original_tractor_path,
                avoidance_path=tuple(work_pass.path_points) if work_pass.path_points else final_result.avoidance_path,
                entry_transition=final_result.entry_transition,
                avoidance_arc=final_result.avoidance_arc,
                exit_transition=final_result.exit_transition,
                return_path=final_result.return_path,
                affected_rows=final_result.affected_rows,
                coverage_gap_m2=final_result.coverage_gap_m2,
                overlap_area_m2=final_result.overlap_area_m2,
                returns_to_guidance=final_result.returns_to_guidance,
                tractor_radius_m=final_result.tractor_radius_m,
            )
            avoided.append(_to_avoided_path(merged, work_pass, planter, final_hit))
        modified.append(work_pass)
        if pass_count > 8 and pass_index > 0 and pass_index % 6 == 0:
            _pump_ui_events()
    return modified, results, avoided


def planting_avoidance_summary(results: list[PlantingAvoidanceResult]) -> list[dict[str, object]]:
    return [item.attributes() for item in results]


def _compact_pass_polyline(
    points: list[Point] | tuple[Point, ...],
    *,
    max_points: int = _PASS_POLYLINE_MAX_POINTS,
) -> list[Point]:
    """Reduz vertices (desvio costurado ou varredura) sem explodir o tempo."""
    pts = _dedupe(list(points))
    if len(pts) <= max_points:
        return pts
    return decimate_polyline(
        pts,
        min_step_m=1.0,
        max_points=max_points,
    )


def _regions_near_pass(
    segment: Segment,
    regions: list[ForbiddenRegion],
    kinematics: PlantingKinematics,
    *,
    margin_m: float = _PASS_CANDIDATE_MARGIN_M,
    index: UniformGridIndex | None = None,
    path_points: list[Point] | None = None,
) -> list[ForbiddenRegion]:
    """Regioes plausiveis para esta passada (ignora obstaculos longe do corredor).

    Com `index`, uma passada distante de tudo devolve lista vazia sem varrer os
    demais obstaculos. Sem indice, mantem o comportamento conservador de
    devolver todas as regioes quando o filtro linear nao encontra candidatas.
    """
    half_w = kinematics.half_operational_width_m
    searched = regions
    indexed = False
    if index is not None and len(index) > 0:
        pts = path_points if path_points and len(path_points) >= 2 else [segment.start, segment.end]
        reach = half_w + margin_m + index.cell_size_m
        searched = list(index.query_polyline(pts, reach))
        indexed = True
        if not searched:
            return []

    out: list[ForbiddenRegion] = []
    use_poly = path_points is not None and len(path_points) >= 3
    for region in searched:
        reach = half_w + region.implement_clearance_radius_m + margin_m
        if use_poly:
            from .line_geometry import signed_distance_point_to_polyline

            lat = abs(signed_distance_point_to_polyline(region.center, path_points))
            if lat > reach:
                continue
            out.append(region)
            continue
        lat = _point_line_distance(region.center, segment)
        if lat > reach:
            continue
        t = _project_t(region.center, segment)
        if t < -0.08 or t > 1.08:
            continue
        out.append(region)
    if out:
        return out
    return [] if indexed else list(regions)


def _pump_ui_events() -> None:
    try:
        from qgis.PyQt.QtWidgets import QApplication

        QApplication.processEvents()
    except Exception:
        pass


def _expand_stitch_for_build(
    points: tuple[Point, ...] | list[Point],
    stitch_range: tuple[int, int],
    *,
    min_length_m: float,
) -> tuple[Segment, tuple[int, int]]:
    """Amplia o trecho costurado ate caber entrada/saida + arco do contorno."""
    from .line_geometry import distance, ensure_segment_span, polyline_length

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


def _min_build_length_m(
    kinematics: PlantingKinematics,
    region: ForbiddenRegion,
) -> float:
    rmin = float(kinematics.minimum_turn_radius_m or 6.0)
    clearance = float(region.implement_clearance_radius_m or 10.0)
    return max(96.0, 4.0 * rmin + 2.0 * clearance)


def _region_hits_pass(
    segment: Segment,
    region: ForbiddenRegion,
    kinematics: PlantingKinematics | None,
) -> bool:
    del kinematics
    # region.implement_clearance_radius_m ja inclui a meia largura da maquina.
    if forbidden_hits_segment(region, segment.start, segment.end):
        return True
    lat = _point_line_distance(region.center, segment)
    if lat <= region.implement_clearance_radius_m:
        t = _project_t(region.center, segment)
        if 0.0 <= t <= 1.0:
            return True
    return False


def _locate_pass_hit(
    pts: tuple[Point, ...] | list[Point],
    segment: Segment,
    regions: list[ForbiddenRegion],
    kinematics: PlantingKinematics,
    *,
    exclude: set[tuple[str, ...]] | None = None,
) -> tuple[ForbiddenRegion | None, tuple[int, int] | None, Segment]:
    """Obstaculo mais cedo ao longo da passada (polilinha ou segmento reto)."""
    from .obstacle_contour_path import polyline_forbidden_hit_range

    skip = exclude or set()
    best: ForbiddenRegion | None = None
    best_stitch: tuple[int, int] | None = None
    best_segment = segment
    best_key: float | None = None

    if len(pts) >= 3:
        scan_pts = pts
        if len(pts) > 320:
            scan_pts = decimate_polyline(pts, min_step_m=2.0, max_points=320)
        candidates: list[ForbiddenRegion] = []
        for region in regions:
            if tuple(sorted(region.group_ids)) in skip:
                continue
            # Zona ja embute W/2: nao deslocar a faixa de novo (evita 2x meia largura).
            if polyline_forbidden_hit_range(scan_pts, region, half_width_m=0.0) is not None:
                candidates.append(region)
        search_regions = candidates if candidates else [
            r for r in regions if tuple(sorted(r.group_ids)) not in skip
        ]
        for region in search_regions:
            if tuple(sorted(region.group_ids)) in skip:
                continue
            hit_range = polyline_forbidden_hit_range(
                pts, region, half_width_m=0.0
            )
            if hit_range is None:
                continue
            key = float(hit_range[0])
            if best_key is None or key < best_key:
                best_key = key
                best = region
                best_stitch = (hit_range[0], hit_range[1])
                best_segment = hit_range[2]
        return best, best_stitch, best_segment

    for region in regions:
        if tuple(sorted(region.group_ids)) in skip:
            continue
        if not _region_hits_pass(segment, region, kinematics):
            continue
        t = _project_t(region.center, segment)
        key = max(0.0, min(1.0, t))
        if best_key is None or key < best_key:
            best_key = key
            best = region
            best_stitch = None
            best_segment = segment

    return best, best_stitch, best_segment


def _first_hit_region(
    segment: Segment,
    regions: list[ForbiddenRegion],
    kinematics: PlantingKinematics | None = None,
) -> ForbiddenRegion | None:
    if kinematics is None:
        for region in regions:
            if _region_hits_pass(segment, region, None):
                return region
        return None
    hit, _, _ = _locate_pass_hit((), segment, regions, kinematics)
    return hit


def _build_path(
    segment: Segment,
    region: ForbiddenRegion,
    kinematics: PlantingKinematics,
    strategy: PlantingAvoidanceStrategy,
    config: PlantingAvoidanceConfiguration,
    *,
    obstacle_by_id: dict | None = None,
    finalize: bool = True,
    path_points: tuple[Point, ...] | list[Point] | None = None,
    at_index: int | None = None,
) -> tuple[list[Point], list[Point], list[Point], list[Point], list[Point], float] | None:
    obstacle = None
    if obstacle_by_id:
        for oid in region.group_ids:
            obstacle = obstacle_by_id.get(oid)
            if obstacle is not None:
                break
    if strategy == PlantingAvoidanceStrategy.LATERAL:
        return _build_lateral(
            segment,
            region,
            kinematics,
            finalize=finalize,
            path_points=path_points,
            at_index=at_index,
        )
    if strategy == PlantingAvoidanceStrategy.CONTOUR:
        return _build_contour(
            segment,
            region,
            kinematics,
            obstacle=obstacle,
            finalize=finalize,
            path_points=path_points,
            at_index=at_index,
        )
    return _build_circular(
        segment,
        region,
        kinematics,
        config,
        finalize=finalize,
        path_points=path_points,
        at_index=at_index,
    )


def _build_lateral(
    segment: Segment,
    region: ForbiddenRegion,
    kinematics: PlantingKinematics,
    *,
    finalize: bool = True,
    path_points: tuple[Point, ...] | list[Point] | None = None,
    at_index: int | None = None,
) -> tuple[list[Point], list[Point], list[Point], list[Point], list[Point], float] | None:
    del finalize
    from .line_geometry import segment_travel_direction

    direction = segment_travel_direction(segment, path_points, at_index=at_index)
    left = perpendicular_left(direction)
    # Lado do obstaculo relativamente a linha.
    to_obs = sub(region.center, segment.start)
    side = 1.0 if (left[0] * to_obs[0] + left[1] * to_obs[1]) >= 0 else -1.0
    # Deslocar para o lado oposto ao obstaculo.
    shift_dir = mul(left, -side)

    lat = _point_line_distance(region.center, segment)
    needed = region.implement_clearance_radius_m - lat
    if needed <= 0:
        needed = 0.5
    shift = needed + 0.05

    t_center = _project_t(region.center, segment)
    t_entry = max(0.0, t_center - 0.15)
    t_exit = min(1.0, t_center + 0.15)
    p_entry = point_at_segment_t(segment, t_entry)
    p_exit = point_at_segment_t(segment, t_exit)
    p_mid = point_at_segment_t(segment, t_center)

    shifted_entry = add(p_entry, mul(shift_dir, shift))
    shifted_mid = add(p_mid, mul(shift_dir, shift))
    shifted_exit = add(p_exit, mul(shift_dir, shift))

    entry = [segment.start, p_entry, shifted_entry] if t_entry > 1e-6 else [segment.start, shifted_entry]
    arc = [shifted_entry, shifted_mid, shifted_exit]
    exit_pts = [shifted_exit, p_exit]
    return_pts = [p_exit, segment.end] if t_exit < 1.0 - 1e-6 else [segment.end]
    raw = entry + arc[1:] + exit_pts[1:] + return_pts[1:]
    path = _dedupe(raw)
    return path, entry, arc, exit_pts, return_pts, shift


def _build_circular(
    segment: Segment,
    region: ForbiddenRegion,
    kinematics: PlantingKinematics,
    config: PlantingAvoidanceConfiguration,
    *,
    finalize: bool = True,
    path_points: tuple[Point, ...] | list[Point] | None = None,
    at_index: int | None = None,
) -> tuple[list[Point], list[Point], list[Point], list[Point], list[Point], float] | None:
    """Anel do buffer + hitch: trajetoria do trator segura para a plantadeira."""
    from .obstacle_contour_path import plan_circular_avoidance_for_implement

    clearance_r = region.implement_clearance_radius_m
    path = plan_circular_avoidance_for_implement(
        segment,
        region.center,
        clearance_r,
        kinematics,
        segments=96 if finalize else 64,
        quick=not finalize,
        path_points=path_points,
        at_index=at_index,
    )
    if path is None or len(path) < 3:
        return None
    return path, [path[0]], path, [path[-1]], [path[-1]], clearance_r


def _build_contour(
    segment: Segment,
    region: ForbiddenRegion,
    kinematics: PlantingKinematics,
    *,
    obstacle: Obstacle | None = None,
    finalize: bool = True,
    path_points: tuple[Point, ...] | list[Point] | None = None,
    at_index: int | None = None,
) -> tuple[list[Point], list[Point], list[Point], list[Point], list[Point], float] | None:
    """Contorno validado no envelope da plantadeira (atraso de hitch)."""
    from .obstacle_contour_path import (
        plan_circular_avoidance_for_implement,
        plan_polygon_avoidance_for_implement,
    )

    is_group = len(region.group_ids) > 1
    half_w = kinematics.half_operational_width_m
    # Folga do CENTRO do trator = raio_obstaculo + W/2 + margem.
    # Plantadeira 20 m -> 10 m de cada lado; nunca W/4 nem 0.15*W/2.
    implement_r = max(float(region.implement_clearance_radius_m), half_w)

    # Poste unico / grupo circular: planejador com hitch.
    if obstacle is not None and obstacle.is_circular() and obstacle.polygon is None:
        center = region.center if is_group else obstacle.center
        path = plan_circular_avoidance_for_implement(
            segment,
            center,
            implement_r,
            kinematics,
            segments=96 if finalize else 64,
            quick=not finalize,
            path_points=path_points,
            at_index=at_index,
        )
        if path is None:
            return _build_circular(
                segment,
                region,
                kinematics,
                PlantingAvoidanceConfiguration(strategy=PlantingAvoidanceStrategy.CONTOUR),
                finalize=finalize,
                path_points=path_points,
                at_index=at_index,
            )
        return path, [path[0]], path, [path[-1]], [path[-1]], implement_r

    if not is_group and obstacle is not None and obstacle.polygon is not None:
        # Contorno da feicao REAL com buffer = meia plantadeira + margem.
        # Antes usava so a margem (safety - half_w) e pulava a validacao das
        # pontas quando hitch=0 — trator a 3–7 m em plantadeira de 20 m.
        base_geom = obstacle.polygon
        clearance = implement_r
        ref = obstacle.center if obstacle.center else region.center
    elif is_group:
        # Geometria do grupo ja inclui W/2: o trator segue o anel (folga tecnica).
        base_geom = region.geometry
        clearance = 0.05
        ref = region.center
    else:
        # Fallback: geometria da zona ja expandida por implement_clearance.
        base_geom = region.geometry
        clearance = 0.05
        ref = region.center

    path = plan_polygon_avoidance_for_implement(
        segment,
        base_geom,
        clearance_m=clearance,
        kinematics=kinematics,
        densify_m=1.25,
        obstacle_reference=ref,
        path_points=path_points,
        at_index=at_index,
    )
    if path is None:
        return _build_circular(
            segment,
            region,
            kinematics,
            PlantingAvoidanceConfiguration(strategy=PlantingAvoidanceStrategy.CONTOUR),
            finalize=finalize,
            path_points=path_points,
            at_index=at_index,
        )
    return path, [path[0]], path, [path[-1]], [path[-1]], implement_r


def _segment_zone_crossings(segment: Segment, region: ForbiddenRegion) -> tuple[float, float]:
    """Parametros t de entrada/saida da passada na zona proibida."""
    from .line_geometry import point_in_multipolygon, segment_samples

    samples = segment_samples([segment.start, segment.end], densify_m=1.0)
    if len(samples) < 2:
        return 0.25, 0.75

    n = len(samples) - 1
    inside_flags = [
        forbidden_hits_segment(region, pt, pt)
        or point_in_multipolygon(pt, [region.geometry], check_boundary=True)
        for pt in samples
    ]
    first_in = None
    last_in = None
    for i, flag in enumerate(inside_flags):
        if not flag:
            continue
        t = i / n if n else 0.0
        if first_in is None:
            first_in = t
        last_in = t
    if first_in is not None and last_in is not None and last_in - first_in > 1e-6:
        margin = min(0.08, 0.25 * (last_in - first_in))
        return max(0.0, first_in - margin), min(1.0, last_in + margin)

    # Fallback: intersecao com circulo de seguranca.
    ts = line_circle_intersections(segment, region.center, region.safety_radius_m)
    if len(ts) >= 2:
        return ts[0], ts[1]
    return 0.2, 0.8


def _stitch_clipped_chunks(chunks: list[list[Point]]) -> list[Point]:
    """Concatena trechos clipados mantendo continuidade aproximada."""
    if not chunks:
        return []
    ordered = sorted(chunks, key=lambda c: len(c), reverse=True)
    out = list(ordered[0])
    for chunk in ordered[1:]:
        if not chunk:
            continue
        if distance(out[-1], chunk[0]) > 1.0 and distance(out[-1], chunk[-1]) <= 1.0:
            out.extend(reversed(chunk[1:]))
        elif distance(out[-1], chunk[0]) <= 1.0:
            out.extend(chunk[1:])
        elif distance(out[-1], chunk[-1]) <= 1.0:
            out.extend(reversed(chunk[:-1]))
    return _dedupe(out)


def _to_avoided_path(
    result: PlantingAvoidanceResult,
    traffic_pass: TrafficPass,
    planter: PlanterMachine,
    region: ForbiddenRegion,
) -> AvoidedPath:
    action = AvoidanceAction.RING.value
    if result.strategy_used == PlantingAvoidanceStrategy.LATERAL:
        action = AvoidanceAction.AVOID.value
    return AvoidedPath(
        fs_id=result.fs_id,
        source_id=traffic_pass.fs_id,
        pass_id=result.pass_id,
        row_id=None,
        operation_id="planting",
        machine_id=planter.machine_id,
        original_segment=Segment(result.original_tractor_path[0], result.original_tractor_path[-1]),
        modified_points=result.avoidance_path,
        entry_point=result.avoidance_path[0] if result.avoidance_path else None,
        exit_point=result.avoidance_path[-1] if result.avoidance_path else None,
        obstacle_id="+".join(result.obstacle_ids),
        application_radius_m=result.tractor_radius_m or region.implement_clearance_radius_m,
        action=action,
        returns_to_guidance=result.returns_to_guidance,
    )


def _point_line_distance(point: Point, segment: Segment) -> float:
    from .line_geometry import cross, hypot

    dx = segment.end[0] - segment.start[0]
    dy = segment.end[1] - segment.start[1]
    length = hypot(dx, dy)
    if length <= 1e-9:
        return distance(point, segment.start)
    return abs(cross(sub(point, segment.start), (dx, dy))) / length


def _project_t(point: Point, segment: Segment) -> float:
    dx = segment.end[0] - segment.start[0]
    dy = segment.end[1] - segment.start[1]
    length2 = dx * dx + dy * dy
    if length2 <= 1e-12:
        return 0.0
    return ((point[0] - segment.start[0]) * dx + (point[1] - segment.start[1]) * dy) / length2


def _polygon_hits_circle(polygon: tuple, center: Point, radius_m: float) -> bool:
    outer = polygon[0]
    for pt in outer:
        if distance(pt, center) <= radius_m:
            return True
    if point_in_multipolygon(center, [polygon]):
        return True
    return False


def _returns_to_guidance(original: Segment, points: list[Point]) -> bool:
    if len(points) < 2:
        return False
    end_dist = distance(points[-1], original.end)
    return end_dist < 1.0


def _dedupe(points: list[Point]) -> list[Point]:
    if not points:
        return points
    out = [points[0]]
    for pt in points[1:]:
        if distance(out[-1], pt) > 1e-6:
            out.append(pt)
    return out


def _finalize_avoidance_path(points: list[Point]) -> list[Point]:
    """Suaviza desvio de plantio (entrada/saida menos secas)."""
    from .obstacle_contour_path import smooth_avoidance_trajectory

    return smooth_avoidance_trajectory(
        _dedupe(points),
        densify_m=0.75,
        chaikin_iterations=2,
        max_points=240,
        preserve_circular=True,
    )
