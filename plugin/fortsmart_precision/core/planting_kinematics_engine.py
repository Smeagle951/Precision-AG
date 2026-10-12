# -*- coding: utf-8 -*-
"""Cinematica: trajetoria do trator -> pose do implemento -> linhas fisicas."""

from __future__ import annotations

from math import atan2, cos, sin
from uuid import uuid4

from ..domain.machine_model import PlanterMachine
from ..domain.planting_kinematics import PlantingKinematics
from .guidance_engine import TrafficPass
from .line_geometry import (
    MultiPolygon,
    Point,
    Polygon,
    Segment,
    add,
    clip_infinite_line_to_multipolygon,
    clip_polyline_to_multipolygon,
    decimate_polyline,
    mul,
    normalize,
    perpendicular_left,
    sub,
)
from .row_engine import PlantingRow


class PlantingKinematicsEngineError(ValueError):
    """Erro na cinematica de plantio."""


def heading_from_points(a: Point, b: Point) -> float:
    return atan2(b[1] - a[1], b[0] - a[0])


def heading_vector(heading_rad: float) -> Point:
    return (cos(heading_rad), sin(heading_rad))


def implement_pose_at(
    tractor_point: Point,
    heading_rad: float,
    kinematics: PlantingKinematics,
) -> Point:
    """Posicao do centro do implemento a partir do centro do trator."""
    kinematics.validate()
    forward = heading_vector(heading_rad)
    left = perpendicular_left(forward)
    # Hitch: implemento atras do trator ao longo do eixo.
    behind = mul(forward, -kinematics.hitch_distance_m)
    lateral = mul(left, kinematics.implement_center_offset_m)
    return add(add(tractor_point, behind), lateral)


def tractor_point_from_guidance(
    guidance_point: Point,
    heading_rad: float,
    kinematics: PlantingKinematics,
) -> Point:
    """Converte ponto de guidance (GNSS) para centro do trator."""
    kinematics.validate()
    forward = heading_vector(heading_rad)
    left = perpendicular_left(forward)
    if kinematics.gnss_reference == "implement_center":
        # GNSS no implemento: voltar hitch + offset lateral GNSS.
        tractor = add(guidance_point, mul(forward, kinematics.hitch_distance_m))
        tractor = add(tractor, mul(left, -kinematics.implement_center_offset_m))
        tractor = add(tractor, mul(left, -kinematics.gnss_offset_m))
        return tractor
    # GNSS no centro do trator (padrao).
    return add(guidance_point, mul(left, -kinematics.gnss_offset_m))


def swath_envelope_at(
    tractor_point: Point,
    heading_rad: float,
    kinematics: PlantingKinematics,
) -> Polygon:
    """Envelope retangular simplificado da plantadeira na pose atual."""
    impl = implement_pose_at(tractor_point, heading_rad, kinematics)
    forward = heading_vector(heading_rad)
    left = perpendicular_left(forward)
    half_w = kinematics.half_operational_width_m
    half_l = max(0.5, kinematics.hitch_distance_m * 0.25 if kinematics.hitch_distance_m > 0 else 0.5)
    corners = [
        add(add(impl, mul(forward, half_l)), mul(left, half_w)),
        add(add(impl, mul(forward, half_l)), mul(left, -half_w)),
        add(add(impl, mul(forward, -half_l)), mul(left, -half_w)),
        add(add(impl, mul(forward, -half_l)), mul(left, half_w)),
    ]
    ring = corners + [corners[0]]
    return (ring, [])


def tractor_envelope_at(
    tractor_point: Point,
    heading_rad: float,
    kinematics: PlantingKinematics,
) -> Polygon:
    """Envelope simplificado do trator (bitola)."""
    forward = heading_vector(heading_rad)
    left = perpendicular_left(forward)
    half_w = kinematics.half_track_width_m
    half_l = (kinematics.tractor_length_m or 4.0) / 2.0
    corners = [
        add(add(tractor_point, mul(forward, half_l)), mul(left, half_w)),
        add(add(tractor_point, mul(forward, half_l)), mul(left, -half_w)),
        add(add(tractor_point, mul(forward, -half_l)), mul(left, -half_w)),
        add(add(tractor_point, mul(forward, -half_l)), mul(left, half_w)),
    ]
    ring = corners + [corners[0]]
    return (ring, [])


def row_points_at(
    tractor_point: Point,
    heading_rad: float,
    kinematics: PlantingKinematics,
) -> list[tuple[int, Point]]:
    """Pontos das linhas fisicas na pose atual (indice 1-based, ponto)."""
    impl = implement_pose_at(tractor_point, heading_rad, kinematics)
    left = perpendicular_left(heading_vector(heading_rad))
    result: list[tuple[int, Point]] = []
    for index, offset in enumerate(kinematics.row_offsets(), start=1):
        # offset positivo = direita da plantadeira (mesmo convenio do row_engine).
        point = add(impl, mul(left, -offset))
        result.append((index, point))
    return result


def implement_path_along_tractor(
    tractor_path: list[Point] | tuple[Point, ...],
    kinematics: PlantingKinematics,
) -> list[Point]:
    """
    Simula a trajetoria do centro da plantadeira ao longo da guiagem do trator.

    Em cada amostra: implemento = trator - hitch*heading + offset_lateral.
    Esse atraso e o que obriga antecipar a entrada do desvio.
    """
    kinematics.validate()
    pts = list(tractor_path)
    hitch = kinematics.hitch_distance_m
    if len(pts) < 2:
        return pts
    if hitch <= 1e-6 and abs(kinematics.implement_center_offset_m) <= 1e-6:
        return pts

    out: list[Point] = []
    for i, tractor in enumerate(pts):
        if i < len(pts) - 1:
            heading = heading_from_points(tractor, pts[i + 1])
        elif i > 0:
            heading = heading_from_points(pts[i - 1], tractor)
        else:
            heading = 0.0
        out.append(implement_pose_at(tractor, heading, kinematics))
    return out


def implement_tip_points_at(
    tractor_point: Point,
    heading_rad: float,
    kinematics: PlantingKinematics,
) -> tuple[Point, Point, Point]:
    """Centro + extremos esquerdo/direito da barra (envelope operacional)."""
    impl = implement_pose_at(tractor_point, heading_rad, kinematics)
    left = perpendicular_left(heading_vector(heading_rad))
    half_w = kinematics.half_operational_width_m
    return (
        impl,
        add(impl, mul(left, half_w)),
        add(impl, mul(left, -half_w)),
    )


def implement_clears_circle(
    tractor_path: list[Point] | tuple[Point, ...],
    kinematics: PlantingKinematics,
    center: Point,
    *,
    clearance_radius_m: float,
) -> bool:
    """
    True se o envelope da plantadeira fica fora do circulo de clearance.

    clearance_radius_m ja inclui meia-largura (obstacle + margem + half_w).
    Checa centro e pontas da barra em cada pose (durante a curva as pontas
    podem aproximar mais que o centro).
    """
    from .line_geometry import distance

    kinematics.validate()
    pts = list(tractor_path)
    if len(pts) < 2:
        return True
    # Nucleo fisico aproximado (sem meia-barra): pontas precisam respeitar isto.
    core_r = max(0.5, clearance_radius_m - kinematics.half_operational_width_m)
    safe_center = clearance_radius_m * 0.995
    safe_tip = core_r * 0.995
    step = 1 if len(pts) <= 96 else max(1, len(pts) // 64)

    for i, tractor in enumerate(pts):
        if i % step != 0 and i != len(pts) - 1:
            continue
        if i < len(pts) - 1:
            heading = heading_from_points(tractor, pts[i + 1])
        else:
            heading = heading_from_points(pts[i - 1], tractor) if i > 0 else 0.0
        center_pt, left_tip, right_tip = implement_tip_points_at(tractor, heading, kinematics)
        if distance(center_pt, center) < safe_center:
            return False
        if distance(left_tip, center) < safe_tip or distance(right_tip, center) < safe_tip:
            return False
    return True


def implement_clears_polygon(
    tractor_path: list[Point] | tuple[Point, ...],
    kinematics: PlantingKinematics,
    polygon_geometry,
) -> bool:
    """True se centro e pontas da plantadeira ficam fora do poligono (envelope)."""
    from .line_geometry import point_in_multipolygon

    kinematics.validate()
    pts = list(tractor_path)
    if len(pts) < 2:
        return True
    for i, tractor in enumerate(pts):
        if i < len(pts) - 1:
            heading = heading_from_points(tractor, pts[i + 1])
        else:
            heading = heading_from_points(pts[i - 1], tractor) if i > 0 else 0.0
        for tip in implement_tip_points_at(tractor, heading, kinematics):
            if point_in_multipolygon(tip, [polygon_geometry], check_boundary=False):
                return False
    return True


def generate_rows_from_tractor_paths(
    passes: list[TrafficPass],
    planter: PlanterMachine,
    kinematics: PlantingKinematics,
    *,
    work_area: MultiPolygon,
) -> list[PlantingRow]:
    """
    Deriva linhas fisicas a partir das trajetorias do trator (pos-desvio).

    Se a passada tiver path_points (polilinha desviada), as linhas sao offsets
    laterais amostrados ao longo da polilinha. Caso contrario, usa clip reto.
    """
    planter.validate()
    kinematics.validate()
    if not passes:
        return []

    if work_area:
        from .line_geometry import simplify_multipolygon_for_pip

        work_area = simplify_multipolygon_for_pip(
            list(work_area),
            max_vertices=180,
            min_edge_m=2.5,
        )

    # Preferir offsets da cinematica (GUI); fallback para a plantadeira.
    offsets = kinematics.row_offsets()
    if kinematics.row_count <= 0 and planter.row_count > 0:
        offsets = planter.all_row_offsets()

    rows: list[PlantingRow] = []
    for traffic_pass in passes:
        points = traffic_pass.line_points()
        if len(points) >= 3:
            rows.extend(
                _rows_from_polyline(
                    points,
                    traffic_pass,
                    planter,
                    offsets,
                    work_area=work_area,
                )
            )
            continue

        direction_vec = normalize(sub(traffic_pass.guidance_segment.end, traffic_pass.guidance_segment.start))
        if traffic_pass.direction == "reverse":
            direction_vec = mul(direction_vec, -1.0)
        normal_left = perpendicular_left(direction_vec)
        base = traffic_pass.guidance_segment.start
        for row_index, row_offset in enumerate(offsets, start=1):
            line_base = add(base, mul(normal_left, -row_offset))
            clipped = clip_infinite_line_to_multipolygon(line_base, direction_vec, work_area)
            if not clipped:
                continue
            longest = max(clipped, key=lambda seg: seg.length)
            rows.append(
                PlantingRow(
                    fs_id=str(uuid4()),
                    row_id=row_index,
                    pass_id=traffic_pass.pass_no,
                    machine_id=planter.machine_id,
                    spacing_m=planter.row_spacing_m if planter.row_spacing_m > 0 else kinematics.row_spacing_m,
                    direction=traffic_pass.direction,
                    offset_m=row_offset,
                    azimuth_deg=traffic_pass.azimuth_deg,
                    segment=longest,
                )
            )
    return rows


def _rows_from_polyline(
    tractor_points: tuple[Point, ...] | list[Point],
    traffic_pass: TrafficPass,
    planter: PlanterMachine,
    offsets: list[float],
    *,
    work_area: MultiPolygon | None = None,
) -> list[PlantingRow]:
    """Offsets laterais ao longo da polilinha, clipados no limite operacional+extensao."""
    # Decima trajetoria do trator antes de N offsets (evita milhoes de vertices).
    tractor_points = decimate_polyline(tractor_points, min_step_m=5.0, max_points=80)
    rows: list[PlantingRow] = []
    for row_index, row_offset in enumerate(offsets, start=1):
        row_pts: list[Point] = []
        for i, point in enumerate(tractor_points):
            if i + 1 < len(tractor_points):
                heading = heading_from_points(point, tractor_points[i + 1])
            else:
                heading = heading_from_points(tractor_points[i - 1], point)
            left = perpendicular_left(heading_vector(heading))
            row_pts.append(add(point, mul(left, -row_offset)))
        if len(row_pts) < 2:
            continue

        chunks: list[list[Point]]
        if work_area:
            chunks = clip_polyline_to_multipolygon(row_pts, work_area)
        else:
            chunks = [row_pts]

        for chunk in chunks:
            if len(chunk) < 2:
                continue
            # Virtual: guarda so extremos se quase reta; senao polilinha ja decimada.
            path = tuple(chunk) if len(chunk) > 2 else ()
            rows.append(
                PlantingRow(
                    fs_id=str(uuid4()),
                    row_id=row_index,
                    pass_id=traffic_pass.pass_no,
                    machine_id=planter.machine_id,
                    spacing_m=planter.row_spacing_m,
                    direction=traffic_pass.direction,
                    offset_m=row_offset,
                    azimuth_deg=traffic_pass.azimuth_deg,
                    segment=Segment(chunk[0], chunk[-1]),
                    path_points=path,
                )
            )
    return rows


def kinematics_from_planter(
    planter: PlanterMachine,
    *,
    hitch_distance_m: float = 0.0,
    tractor_length_m: float | None = None,
    gnss_reference: str = "tractor_center",
    operational_width_m: float | None = None,
) -> PlantingKinematics:
    """Helper para testes / fallback a partir do preset da plantadeira."""
    return PlantingKinematics(
        operational_width_m=operational_width_m or planter.operational_width_m,
        track_width_m=planter.track.track_width_m if planter.track is not None else 0.0,
        gnss_reference=gnss_reference,
        gnss_offset_m=planter.gnss_offset_m,
        hitch_distance_m=hitch_distance_m,
        implement_center_offset_m=planter.implement_center_offset_m,
        tractor_length_m=tractor_length_m,
        row_count=planter.row_count,
        row_spacing_m=planter.row_spacing_m,
    )
