# -*- coding: utf-8 -*-
"""Validacao de trajetorias com desvio de obstaculos."""

from __future__ import annotations

from math import hypot

from ..domain.avoidance_configuration import AvoidanceConfiguration
from ..domain.obstacle_model import Obstacle
from .line_geometry import MultiPolygon, Point, distance, point_in_multipolygon, segment_samples
from .obstacle_engine import AvoidedPath
from .validation_engine import ValidationIssue, ValidationReport

_MAX_VALIDATE_PATHS = 96


def validate_avoided_paths(
    paths: list[AvoidedPath],
    obstacles: list[Obstacle],
    allowed_area: MultiPolygon | None,
    config: AvoidanceConfiguration,
    *,
    radius_tolerance_m: float = 0.01,
    max_paths: int | None = None,
) -> ValidationReport:
    """Valida as trajetorias desviadas.

    `max_paths` reduz a amostra no modo Rapido. A amostragem e uniforme ao longo
    do talhao (passo constante), nunca as N primeiras: um erro concentrado numa
    borda continua aparecendo.
    """
    report = ValidationReport()
    if not config.enabled():
        report.checks.append("Desvio de obstaculos desabilitado")
        return report

    report.checks.append(f"Trajetorias modificadas: {len(paths)}")
    obstacle_by_id = {item.obstacle_id: item for item in obstacles}

    limit = _MAX_VALIDATE_PATHS if max_paths is None else max(1, int(max_paths))
    paths_to_check = paths
    if len(paths) > limit:
        step = max(1, len(paths) // limit)
        paths_to_check = paths[::step][:limit]
        report.checks.append(
            f"Validacao amostrada: {len(paths_to_check)}/{len(paths)} trajetorias"
        )

    for path in paths_to_check:
        if path.action == "ring" and path.obstacle_id in obstacle_by_id:
            obs = obstacle_by_id[path.obstacle_id]
            if obs.is_circular():
                _validate_ring_radius(path, obs.center, path.application_radius_m, radius_tolerance_m, report)

        if allowed_area is not None:
            for point in segment_samples(list(path.modified_points), densify_m=5.0):
                if _on_original_guidance(point, path.original_segment):
                    continue
                if not point_in_multipolygon(point, allowed_area):
                    report.add_error(
                        "PATH_OUTSIDE_ALLOWED_AREA",
                        f"Passada {path.pass_id} sai da area permitida.",
                    )
                    break

        if not path.returns_to_guidance and path.action != "ring":
            report.add_warning(
                "NO_GUIDANCE_RETURN",
                f"Passada {path.pass_id} pode nao retornar a linha original.",
            )

        inner = _obstacle_inner_zone(obstacles, path.obstacle_id)
        if inner is not None:
            for point in segment_samples(list(path.modified_points), densify_m=3.0):
                if point_in_multipolygon(point, inner):
                    report.add_error(
                        "PATH_THROUGH_OBSTACLE",
                        f"Passada {path.pass_id} atravessa obstaculo {path.obstacle_id}.",
                    )
                    break

    return report


def _validate_ring_radius(
    path: AvoidedPath,
    center: Point,
    expected_radius: float,
    tolerance: float,
    report: ValidationReport,
) -> None:
    cx, cy = center
    ring_points = [
        p for p in path.modified_points if abs(distance(p, center) - expected_radius) < 1.0
    ]
    if not ring_points:
        report.add_warning("RING_NO_ARC", f"Passada {path.pass_id} sem arco mensuravel.")
        return
    for point in ring_points[:: max(1, len(ring_points) // 8)]:
        r = distance(point, center)
        if abs(r - expected_radius) > tolerance:
            report.add_warning(
                "RING_RADIUS_DIVERGENCE",
                f"Raio medido {r:.3f} m difere do esperado {expected_radius:.3f} m.",
            )
            return
    report.checks.append(f"Anel passada {path.pass_id}: raio OK")


def _obstacle_inner_zone(obstacles: list[Obstacle], obstacle_id: str) -> MultiPolygon | None:
    from .line_geometry import circle_ring_polygon

    for obs in obstacles:
        if obs.obstacle_id in obstacle_id or obstacle_id.startswith(obs.obstacle_id):
            inner_r = max(obs.obstacle_radius_m, 0.1)
            return [circle_ring_polygon(obs.center, inner_r)]
    return None


def _on_original_guidance(point: Point, segment, *, tolerance_m: float = 1.0) -> bool:
    from .line_geometry import Segment as Seg

    seg = segment if isinstance(segment, Seg) else segment
    dx = seg.end[0] - seg.start[0]
    dy = seg.end[1] - seg.start[1]
    length = hypot(dx, dy)
    if length <= 1e-9:
        return distance(point, seg.start) <= tolerance_m
    cross_val = abs((point[0] - seg.start[0]) * dy - (point[1] - seg.start[1]) * dx) / length
    if cross_val > tolerance_m:
        return False
    t = ((point[0] - seg.start[0]) * dx + (point[1] - seg.start[1]) * dy) / (length * length)
    return -tolerance_m / length <= t <= 1.0 + tolerance_m / length
