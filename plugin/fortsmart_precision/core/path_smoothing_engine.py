# -*- coding: utf-8 -*-
"""Suavizacao de todas as linhas operacionais do Precision Lines."""

from __future__ import annotations

from dataclasses import replace

from ..domain.path_smoothing_configuration import PathSmoothingConfiguration, SmoothingLevel
from .boundary_engine import BoundaryPlan
from .guidance_engine import TrafficPass
from .line_geometry import Point, Segment, decimate_polyline, segment_samples
from .obstacle_engine import AvoidedPath
from .row_engine import PlantingRow
from .shutoff_engine import RowShutoffSegment

# Cap duro: suavizacao nao pode explodir vertices (freeze no preview/QGIS).
_SMOOTH_MAX_POINTS = 100
# Contornos fechados (bordadura) precisam de mais vertices para nao retificar curvas.
_CONTOUR_MAX_POINTS = 2000
# Polilinhas ja finalizadas pelo motor de desvio: pular re-suavizacao (evita freeze).
_DENSE_POLYLINE_SKIP_SMOOTH = 48


def _is_closed_contour(points: tuple[Point, ...] | list[Point]) -> bool:
    pts = list(points)
    if len(pts) < 5:
        return False
    dx = pts[0][0] - pts[-1][0]
    dy = pts[0][1] - pts[-1][1]
    return (dx * dx + dy * dy) ** 0.5 <= 0.05


def smooth_polyline(
    points: list[Point] | tuple[Point, ...],
    config: PathSmoothingConfiguration,
) -> tuple[Point, ...]:
    """Suaviza polilinha preservando extremidades (com limite de vertices)."""
    if not config.enabled() or len(points) < 2:
        return tuple(points)

    start = points[0]
    end = points[-1]
    densify = max(5.0, config.resolved_densify_m())
    if len(points) == 2:
        densified = segment_samples(list(points), densify_m=densify)
        if config.level == SmoothingLevel.HIGH and len(densified) >= 3:
            densified = _chaikin_once(densified)
        densified = decimate_polyline(
            densified, min_step_m=densify, max_points=_SMOOTH_MAX_POINTS
        )
        densified[0] = start
        densified[-1] = end
        return tuple(densified)

    work = segment_samples(list(points), densify_m=densify)
    if config.level == SmoothingLevel.HIGH and len(work) >= 3:
        work = _chaikin_once(work)
    work = decimate_polyline(work, min_step_m=densify, max_points=_SMOOTH_MAX_POINTS)
    work[0] = start
    work[-1] = end
    return tuple(work)


def smooth_segment(segment: Segment, config: PathSmoothingConfiguration) -> tuple[Point, ...]:
    return smooth_polyline([segment.start, segment.end], config)


def smooth_traffic_passes(
    passes: list[TrafficPass],
    config: PathSmoothingConfiguration,
    *,
    detoured_pass_nos: set | None = None,
) -> list[TrafficPass]:
    """Com `detoured_pass_nos`, so as passadas desviadas sao re-suavizadas.

    As demais ja sao o offset exato da referencia: Chaikin corta a curva para
    dentro e mudaria a distancia entre passadas vizinhas.
    """
    from .obstacle_contour_path import smooth_avoidance_trajectory

    result: list[TrafficPass] = []
    for item in passes:
        raw = list(item.line_points())
        exact = (
            detoured_pass_nos is not None
            and item.pass_no not in detoured_pass_nos
            and len(raw) >= 3
        )
        # Desvios ja finalizados pelo motor de obstaculo: nao re-suavizar (trava o QGIS).
        if exact or len(raw) >= _DENSE_POLYLINE_SKIP_SMOOTH:
            path_points = tuple(raw)
        elif len(raw) >= 5:
            path_points = tuple(
                smooth_avoidance_trajectory(
                    raw,
                    densify_m=0.75,
                    chaikin_iterations=2,
                    max_points=240,
                    preserve_circular=True,
                )
            )
        elif config.enabled():
            path_points = smooth_polyline(raw, config)
        else:
            path_points = tuple(raw)
        result.append(
            TrafficPass(
                pass_no=item.pass_no,
                fs_id=item.fs_id,
                operation_id=item.operation_id,
                spacing_m=item.spacing_m,
                width_m=item.width_m,
                offset_m=item.offset_m,
                azimuth_deg=item.azimuth_deg,
                direction=item.direction,
                clipped_segment=item.clipped_segment,
                guidance_segment=Segment(path_points[0], path_points[-1]),
                path_points=path_points,
            )
        )
    return result


def smooth_planting_rows(
    rows: list[PlantingRow],
    config: PathSmoothingConfiguration,
) -> list[PlantingRow]:
    if not config.enabled():
        return rows
    result: list[PlantingRow] = []
    for row in rows:
        path_points = smooth_polyline(row.line_points(), config)
        result.append(
            PlantingRow(
                fs_id=row.fs_id,
                row_id=row.row_id,
                pass_id=row.pass_id,
                machine_id=row.machine_id,
                spacing_m=row.spacing_m,
                direction=row.direction,
                offset_m=row.offset_m,
                azimuth_deg=row.azimuth_deg,
                segment=Segment(path_points[0], path_points[-1]),
                path_points=path_points,
            )
        )
    return result


def smooth_shutoff_segments(
    segments: list[RowShutoffSegment],
    config: PathSmoothingConfiguration,
) -> list[RowShutoffSegment]:
    # Shutoff pode ter milhares de trechos: densificar trava o QGIS. Mantem geometria.
    return segments


def smooth_boundary_plan(boundary: BoundaryPlan, config: PathSmoothingConfiguration) -> BoundaryPlan:
    if not config.enabled():
        return boundary
    centerlines = []
    for line in boundary.headland_centerlines:
        raw = line.line_points()
        is_closed = _is_closed_contour(raw)
        # Toda bordadura ja e a geometria final calculada pelo offset do limite.
        # Isso tambem vale para uma bordadura aberta por STRAIGHT_THROUGH: passar
        # essa linha pelo suavizador generico (maximo de 100 pontos) cria cordas
        # diagonais e destroi tanto a precisao do contorno quanto os headings da
        # ponta. Apenas contornos fechados muito densos recebem decimacao fina.
        if is_closed:
            pts = list(raw)
            # FIDELITY (pass_id) ja sai limpo do offset; decimar apagaria recuos pequenos.
            if len(pts) > 500 and not line.pass_id:
                path_points = tuple(
                    decimate_polyline(pts, min_step_m=0.35, max_points=_CONTOUR_MAX_POINTS)
                )
            else:
                path_points = tuple(pts)
            if path_points[0] != path_points[-1]:
                path_points = path_points + (path_points[0],)
        elif len(raw) == 2:
            # Bordadura legada parallel_ab e uma reta simples e ainda precisa
            # da densificacao solicitada pela configuracao de suavizacao.
            path_points = smooth_polyline(raw, config)
        else:
            path_points = tuple(raw)
        centerlines.append(
            replace(
                line,
                segment=Segment(path_points[0], path_points[-1]),
                path_points=path_points,
            )
        )
    return boundary.with_centerlines(tuple(centerlines))


def smooth_avoided_path(path: AvoidedPath, config: PathSmoothingConfiguration) -> AvoidedPath:
    """Desvios sempre recebem suavizacao alta (fluidez da maquina), mesmo com OFF global."""
    from .obstacle_contour_path import smooth_avoidance_trajectory

    if len(path.modified_points) >= _DENSE_POLYLINE_SKIP_SMOOTH:
        return path

    # Sempre suaviza desvio: nao pode ficar com quinas que a maquina nao executa.
    densify = 1.5
    if config.enabled():
        densify = min(densify, max(1.0, config.resolved_densify_m()))
    smoothed = tuple(
        smooth_avoidance_trajectory(
            path.modified_points,
            densify_m=densify,
            chaikin_iterations=3,
            max_points=180,
        )
    )
    return AvoidedPath(
        fs_id=path.fs_id,
        source_id=path.source_id,
        pass_id=path.pass_id,
        row_id=path.row_id,
        operation_id=path.operation_id,
        machine_id=path.machine_id,
        original_segment=path.original_segment,
        modified_points=smoothed,
        entry_point=path.entry_point,
        exit_point=path.exit_point,
        obstacle_id=path.obstacle_id,
        application_radius_m=path.application_radius_m,
        action=path.action,
        returns_to_guidance=path.returns_to_guidance,
    )


def smooth_avoided_paths(
    paths: list[AvoidedPath],
    config: PathSmoothingConfiguration,
) -> list[AvoidedPath]:
    return [smooth_avoided_path(item, config) for item in paths]


def smooth_guidance_layers(
    *,
    planting_passes: list[TrafficPass],
    planting_rows: list[PlantingRow],
    spraying_passes: list[TrafficPass],
    avoided_paths: list[AvoidedPath],
    boundary: BoundaryPlan | None,
    config: PathSmoothingConfiguration,
    planting_detoured: set | None = None,
    spraying_detoured: set | None = None,
) -> tuple[list[TrafficPass], list[PlantingRow], list[TrafficPass], list[AvoidedPath], BoundaryPlan | None]:
    """Suaviza passadas/desvios/bordadura. Linhas virtuais de plantio nao sao densificadas."""
    # Desvios sempre suavizados; passadas com contorno tambem (mesmo OFF global).
    avoided = smooth_avoided_paths(avoided_paths, config)
    planting = smooth_traffic_passes(planting_passes, config, detoured_pass_nos=planting_detoured)
    spraying = (
        smooth_traffic_passes(spraying_passes, config, detoured_pass_nos=spraying_detoured)
        if config.enabled()
        else spraying_passes
    )
    if not config.enabled():
        return planting, planting_rows, spraying, avoided, boundary
    return (
        planting,
        planting_rows,
        spraying,
        avoided,
        smooth_boundary_plan(boundary, config) if boundary else None,
    )


def smooth_all_lines(
    *,
    planting_passes: list[TrafficPass],
    planting_rows: list[PlantingRow],
    spraying_passes: list[TrafficPass],
    shutoff_segments: list[RowShutoffSegment],
    avoided_paths: list[AvoidedPath],
    boundary: BoundaryPlan | None,
    config: PathSmoothingConfiguration,
) -> tuple[list[TrafficPass], list[PlantingRow], list[TrafficPass], list[RowShutoffSegment], list[AvoidedPath], BoundaryPlan | None]:
    """Aplica suavizacao uniforme incluindo segmentos shutoff."""
    planting, rows, spray, avoided, boundary = smooth_guidance_layers(
        planting_passes=planting_passes,
        planting_rows=planting_rows,
        spraying_passes=spraying_passes,
        avoided_paths=avoided_paths,
        boundary=boundary,
        config=config,
    )
    shutoff = smooth_shutoff_segments(shutoff_segments, config)
    return planting, rows, spray, shutoff, avoided, boundary


def _chaikin_once(points: list[Point]) -> list[Point]:
    if len(points) < 3:
        return points
    result = [points[0]]
    for a, b in zip(points, points[1:]):
        q = (0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1])
        r = (0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1])
        result.extend([q, r])
    result.append(points[-1])
    return result
