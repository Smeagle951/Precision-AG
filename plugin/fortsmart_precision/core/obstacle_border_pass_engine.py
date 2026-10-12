# -*- coding: utf-8 -*-
"""CUT_FOR_BORDER: corta pela barra ativa e simula a passada de bordadura.

Uma passada de bordadura nunca e assumida como suficiente: a faixa varrida e
comparada com a area deixada sem trabalho, e falha, sobreposicao, colisao e
saida do talhao sao medidas. Todas as geometrias em CRS metrico.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from ..domain.operation_simulation import (
    MachineWorkGeometry,
    ObstacleBorderMode,
    ObstacleStrategy,
    WorkGeometryStatus,
    WorkState,
)
from .crs import require_projected_metric
from .longitudinal_cut_engine import (
    WORK_OFF,
    WORK_ON,
    LongitudinalCutError,
    ObstacleInput,
    ObstacleZone,
    PassCutResult,
    build_obstacle_zones,
    compute_longitudinal_cut,
    cut_breakdown,
)
from .operation_simulator import SimulationStatus
from .planting_line_cut_engine import cut_line_by_station_gaps

Point = tuple[float, float]


@dataclass(frozen=True)
class BorderPassCandidate:
    cluster_id: str
    obstacle_ids: tuple[str, ...]
    trajectory: Any
    swept_area: Any
    target_area: Any
    gap_area: Any
    overlap_area: Any
    collision_area_m2: float
    outside_area_m2: float
    min_turn_radius_estimate_m: float
    status: SimulationStatus
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class ObstacleBorderSimulation:
    strategy: ObstacleStrategy
    geometry: MachineWorkGeometry
    zones: tuple[ObstacleZone, ...]
    passes: tuple[PassCutResult, ...]
    border_passes: tuple[BorderPassCandidate, ...]
    main_work_area: Any
    unworked_area: Any
    final_coverage: Any
    final_gap: Any
    final_overlap: Any
    workable_area: Any
    status: SimulationStatus
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    report: dict[str, object] = field(default_factory=dict)


def _area(geometry: Any) -> float:
    return 0.0 if geometry is None or geometry.is_empty else float(geometry.area)


def polygonal_part(geometry: Any) -> Any:
    """Somente poligonos com area (interseccoes podem gerar linhas/pontos soltos)."""
    if geometry is None or geometry.is_empty:
        return None
    if geometry.geom_type in ("Polygon", "MultiPolygon"):
        return geometry if geometry.area > 0 else None
    parts = shapely.get_parts(geometry)
    while True:
        nested = shapely.get_type_id(parts) == 7
        if not nested.any():
            break
        parts = np.concatenate((parts[~nested], shapely.get_parts(parts[nested])))
    types = shapely.get_type_id(parts)
    keep = parts[((types == 3) | (types == 6)) & (shapely.area(parts) > 0)]
    if not len(keep):
        return None
    return keep[0] if len(keep) == 1 else shapely.union_all(keep)


def polygonal_mask(geometry: Any) -> Any:
    """Mascara segura para overlays de area; pontos/linhas nao retiram area."""
    polygon = polygonal_part(geometry)
    return polygon if polygon is not None else Polygon()


def cluster_zones(zones: list[ObstacleZone], link_distance_m: float) -> list[list[ObstacleZone]]:
    """Agrupa zonas cuja distancia e menor que a faixa da bordadura (componentes conexas)."""
    remaining = list(range(len(zones)))
    clusters: list[list[ObstacleZone]] = []
    while remaining:
        stack = [remaining.pop(0)]
        members: list[int] = []
        while stack:
            current = stack.pop()
            members.append(current)
            for other in list(remaining):
                if zones[current].safety_zone.distance(zones[other].safety_zone) < link_distance_m:
                    remaining.remove(other)
                    stack.append(other)
        clusters.append([zones[index] for index in sorted(members)])
    return clusters


def _multiple_coverage(pieces: list[Any], min_area_m2: float = 0.0) -> Any:
    """Area coberta mais de uma vez; lascas numericas abaixo de min_area_m2 sao ignoradas."""
    geoms = np.array([piece for piece in pieces if piece is not None and not piece.is_empty], dtype=object)
    if len(geoms) < 2:
        return Polygon()
    left, right = shapely.STRtree(geoms).query(geoms, predicate="intersects")
    pairs = left < right
    if not pairs.any():
        return Polygon()
    shared = shapely.intersection(geoms[left[pairs]], geoms[right[pairs]])
    shared = shared[shapely.area(shared) > min_area_m2]
    if not len(shared):
        return Polygon()
    return polygonal_part(shapely.union_all(shared)) or Polygon()


def build_border_pass(
    cluster_id: str,
    cluster: list[ObstacleZone],
    *,
    geometry: MachineWorkGeometry,
    unworked_target: Any,
    main_work_area: Any,
    all_collision: Any,
    all_safety: Any,
    field_polygon: Any,
    min_area_m2: float,
) -> BorderPassCandidate:
    """Centerline a W/2 da zona de seguranca: a borda interna da faixa encosta na zona."""
    half = geometry.half_width_m
    cluster_zone = unary_union([zone.safety_zone for zone in cluster])
    offset = cluster_zone.buffer(half, quad_segs=32)
    outer = offset if offset.geom_type == "Polygon" else max(offset.geoms, key=lambda g: g.area)
    trajectory = LineString(outer.exterior.coords)
    swept = trajectory.buffer(half, quad_segs=32)

    target = unworked_target.difference(all_safety)
    if field_polygon is not None:
        target = target.intersection(field_polygon)
    gap = target.difference(swept)
    overlap = swept.intersection(main_work_area)
    if field_polygon is not None:
        overlap = overlap.intersection(field_polygon)
    collision = _area(swept.intersection(all_collision))
    outside = _area(swept.difference(field_polygon)) if field_polygon is not None else 0.0
    turn_radius = half + min(zone.physical_radius_m + zone.safety_margin_m for zone in cluster)

    issues: list[str] = []
    if collision > min_area_m2:
        issues.append("BORDER_COLLISION")
    if outside > min_area_m2:
        issues.append("BORDER_OUTSIDE_FIELD")
    if _area(gap) > min_area_m2:
        issues.append("BORDER_GAP")
    if geometry.min_turn_radius_m is not None and turn_radius < geometry.min_turn_radius_m:
        issues.append("BORDER_TURN_RADIUS")
    if outer.convex_hull.area - outer.area > min_area_m2:
        issues.append("BORDER_CONCAVE_CORNER")
    if "BORDER_COLLISION" in issues or "BORDER_OUTSIDE_FIELD" in issues:
        status = SimulationStatus.INVALID
    elif issues:
        status = SimulationStatus.VALID_WITH_WARNINGS
    else:
        status = SimulationStatus.VALID
    return BorderPassCandidate(
        cluster_id=cluster_id,
        obstacle_ids=tuple(zone.obstacle_id for zone in cluster),
        trajectory=trajectory,
        swept_area=swept,
        target_area=target,
        gap_area=gap,
        overlap_area=overlap,
        collision_area_m2=collision,
        outside_area_m2=outside,
        min_turn_radius_estimate_m=turn_radius,
        status=status,
        issues=tuple(issues),
    )


def simulate_obstacle_cut(
    passes: Iterable[tuple[str, Iterable[Point]]],
    obstacles: Iterable[ObstacleInput],
    geometry: MachineWorkGeometry,
    *,
    crs_authid: str,
    field_polygon: Any = None,
    safety_margin_m: float = 0.0,
    strategy: ObstacleStrategy = ObstacleStrategy.CUT_FOR_BORDER,
    tolerance_m: float = 0.05,
    group_obstacles: bool = True,
    min_area_m2: float = 0.01,
) -> ObstacleBorderSimulation:
    """MAIN_OPERATION + BORDER_OPERATION validadas sobre a mesma geometria."""
    require_projected_metric(crs_authid, "corte longitudinal por obstaculo")
    geometry.validate()
    if strategy in (ObstacleStrategy.AUTO, ObstacleStrategy.DIRECT_CONTOUR):
        raise LongitudinalCutError(
            f"{strategy.value}: use o fluxo de contorno existente; este motor trata CUT."
        )
    if geometry.status is WorkGeometryStatus.GEOMETRY_INCOMPLETE:
        raise LongitudinalCutError(
            "GEOMETRY_INCOMPLETE: informe a posicao da ultima linha de trabalho antes do corte."
        )
    if strategy is ObstacleStrategy.CUT_FOR_BORDER and geometry.border_mode is ObstacleBorderMode.NONE:
        raise LongitudinalCutError("CUT_FOR_BORDER exige bordadura configurada.")

    zones = build_obstacle_zones(
        obstacles,
        safety_margin_m,
        allow_zero_area=geometry.safety_margin_lateral_m > 0,
    )
    results = [
        compute_longitudinal_cut(pass_id, points, zones, geometry, tolerance_m=tolerance_m)
        for pass_id, points in passes
    ]
    if not results:
        raise LongitudinalCutError("Nenhuma passada informada.")

    def clip(geom: Any) -> Any:
        return geom.intersection(field_polygon) if field_polygon is not None else geom

    all_safety = unary_union([zone.safety_zone for zone in zones]) if zones else Polygon()
    all_safety_area = polygonal_mask(all_safety)
    all_collision = unary_union([zone.collision_zone for zone in zones]) if zones else Polygon()
    main = clip(unary_union([item.main_work_area for item in results]))
    unworked = clip(unary_union([item.unworked_area for item in results])).difference(
        all_safety_area
    )

    border_passes: list[BorderPassCandidate] = []
    if strategy is ObstacleStrategy.CUT_FOR_BORDER:
        affected_ids = {oid for item in results for oid in item.obstacle_ids}
        affected = [zone for zone in zones if zone.obstacle_id in affected_ids]
        link = geometry.work_width_m if group_obstacles else 0.0
        for index, cluster in enumerate(cluster_zones(affected, link), start=1):
            ids = {zone.obstacle_id for zone in cluster}
            target = unary_union([
                interval.swept_area
                for item in results
                for interval in item.intervals
                if set(interval.obstacle_ids) & ids
            ])
            border_passes.append(
                build_border_pass(
                    f"B{index:02d}",
                    cluster,
                    geometry=geometry,
                    unworked_target=target,
                    main_work_area=main,
                    all_collision=all_collision,
                    all_safety=all_safety_area,
                    field_polygon=field_polygon,
                    min_area_m2=min_area_m2,
                )
            )

    border_work = clip(unary_union([item.swept_area for item in border_passes])).difference(all_safety_area) \
        if border_passes else Polygon()
    workable = clip(unary_union([main, unworked])).difference(all_safety_area)
    coverage = unary_union([main, border_work])
    gap = workable.difference(coverage)
    overlap = _multiple_coverage(
        [clip(item.main_work_area) for item in results]
        + [clip(item.swept_area).difference(all_safety_area) for item in border_passes],
        min_area_m2,
    )

    warnings: list[str] = []
    errors: list[str] = []
    for candidate in border_passes:
        for issue in candidate.issues:
            target_list = errors if issue in ("BORDER_COLLISION", "BORDER_OUTSIDE_FIELD") else warnings
            tagged = f"{candidate.cluster_id}:{issue}"
            if tagged not in target_list:
                target_list.append(tagged)
    if strategy is ObstacleStrategy.CUT_ONLY and _area(unworked) > min_area_m2:
        warnings.append("UNWORKED_INTENTIONAL")
    if _area(gap) > min_area_m2 and strategy is ObstacleStrategy.CUT_FOR_BORDER:
        warnings.append("FINAL_GAP")
    if _area(overlap) > min_area_m2:
        warnings.append("FINAL_OVERLAP")
    status = SimulationStatus.INVALID if errors else (
        SimulationStatus.VALID_WITH_WARNINGS if warnings else SimulationStatus.VALID
    )

    simulation = ObstacleBorderSimulation(
        strategy=strategy,
        geometry=geometry,
        zones=tuple(zones),
        passes=tuple(results),
        border_passes=tuple(border_passes),
        main_work_area=main,
        unworked_area=unworked,
        final_coverage=coverage,
        final_gap=gap,
        final_overlap=overlap,
        workable_area=workable,
        status=status,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )
    return replace(simulation, report=build_report(simulation, crs_authid, tolerance_m))


def work_event_records(simulation: ObstacleBorderSimulation, tolerance_m: float) -> list[dict[str, object]]:
    """Atributos de inspecao de cada WORK_OFF/WORK_ON (camada SIM_WORK_OFF_ON)."""
    geometry = simulation.geometry
    records = []
    for item in simulation.passes:
        for event in item.events:
            records.append({
                "event": event.event_type,
                "pass_id": event.pass_id,
                "reference": geometry.reference_type.value,
                "offset_long_m": geometry.reference_to_working_line_longitudinal_m,
                "width_m": geometry.work_width_m,
                "border_target_m": event.target_distance_m,
                "distance_m": round(event.measured_distance_m, 4),
                "tolerance_m": tolerance_m,
                "within_tol": abs(event.measured_distance_m - event.target_distance_m) <= tolerance_m
                or bool(event.note),
                "station_m": round(event.station_m, 4),
                "reference_xy": event.reference_xy,
                "working_xy": event.working_xy,
                "obstacle_ids": ",".join(event.obstacle_ids),
                "note": event.note,
            })
    return records


FOOTER_STATUS = {
    SimulationStatus.VALID.value: "VALID",
    SimulationStatus.VALID_WITH_WARNINGS.value: "WARNING",
    SimulationStatus.INVALID.value: "INVALID",
}


def preview_footer_status(report: dict[str, object]) -> str:
    return FOOTER_STATUS.get(str(report.get("status")), "INVALID")


def preview_footer_lines(report: dict[str, object]) -> list[str]:
    """Rodape compacto exibido apos a pre-visualizacao do corte longitudinal."""
    machine = report.get("machine_geometry") or {}
    offset = machine.get("reference_to_working_line_longitudinal_m")
    coverage = report.get("border_coverage_pct")

    def number(value: object) -> str:
        return f"{float(value):.2f}".replace(".", ",")

    def ok(flag: object) -> str:
        if not report.get("work_event_count"):
            return "sem eventos"
        return "OK" if flag else "FORA DA TOLERANCIA"

    return [
        f"Implemento: {number(machine.get('work_width_m', 0.0))} m",
        "Offset ultima linha: " + ("nao informado" if offset is None else f"{number(offset)} m"),
        f"Bordadura: {number(report.get('border_width_m', 0.0))} m",
        f"Seguranca obstaculo: {number(report.get('obstacle_safety_m', 0.0))} m",
        f"Antecipacao: {number(machine.get('longitudinal_anticipation_m', 0.0))} m",
        "Corte longitudinal: " + (
            "-" if report.get("max_cut_distance_m") is None
            else f"ate {number(report['max_cut_distance_m'])} m"
        ),
        f"WORK_OFF: {ok(report.get('work_off_ok'))}",
        f"WORK_ON: {ok(report.get('work_on_ok'))}",
        "Cobertura da bordadura: " + ("-" if coverage is None else f"{number(coverage)}%"),
        f"Falha: {number(report.get('border_gap_m2', 0.0))} m²",
        f"Sobreposicao: {number(report.get('border_overlap_m2', 0.0))} m²",
        f"Status: {preview_footer_status(report)}",
    ]


def ground_gaps(item: PassCutResult, geometry: MachineWorkGeometry) -> list[tuple[float, float]]:
    """Intervalos da PROPRIA linha sem operacao: WORK_OFF/WORK_ON levados ao chao.

    A barra segue a passada; quando a referencia esta na estacao s a ultima
    linha ativa esta em s + offset (offset negativo = atras).
    """
    offset = geometry.reference_to_working_line_longitudinal_m or 0.0
    return [
        (interval.start_station_m + offset, interval.end_station_m + offset)
        for interval in item.intervals
        if interval.state is WorkState.RAISED
    ]


def cut_work_line_records(
    simulation: ObstacleBorderSimulation, *, min_length_m: float = 0.01
) -> list[dict[str, object]]:
    """Linha existente menos os trechos sem operacao; uma entrada por passada.

    Nao gera linha nova nem recorta pelo talhao: passada sem obstaculo devolve
    exatamente os vertices de entrada; passada cortada devolve os trechos da
    mesma linha, no sentido original.
    """
    records: list[dict[str, object]] = []
    for item in simulation.passes:
        gaps = ground_gaps(item, simulation.geometry)
        segments = cut_line_by_station_gaps(item.reference_path, gaps, min_length_m=min_length_m)
        offs = [e.station_m for e in item.events if e.event_type == WORK_OFF]
        ons = [e.station_m for e in item.events if e.event_type == WORK_ON]
        records.append({
            "pass_id": item.pass_id,
            "affected": item.affected,
            "gaps": [(round(a, 4), round(b, 4)) for a, b in gaps],
            "work_off_m": round(offs[0], 4) if offs else None,
            "work_on_m": round(ons[-1], 4) if ons else None,
            "segments": segments,
        })
    return records


def machine_schematic_text(geometry: MachineWorkGeometry) -> str:
    """Esquema do conjunto para o operador confirmar antes de simular."""
    offset = geometry.reference_to_working_line_longitudinal_m
    width = f"<{'-' * 6}{geometry.work_width_m:.2f} m{'-' * 6}>"
    reference = f"REFERENCIA ({geometry.reference_type.value})"
    if offset is None:
        return (
            "SENTIDO ->\n"
            f"        {reference}\n"
            "            ?\n"
            "  Posicao da ultima linha de trabalho NAO informada\n"
            "  (GEOMETRY_INCOMPLETE)\n"
            f"  {width}"
        )
    bar = "      BARRA DE TRABALHO (ultima linha ativa)"
    link = f"            |  {abs(offset):.2f} m {'atras' if offset < 0 else 'a frente'}"
    if offset < 0:
        lines = ["SENTIDO ->", f"        {reference}", "            *", link, bar]
    else:
        lines = ["SENTIDO ->", bar, link, "            *", f"        {reference}"]
    lines.append(f"  {width}")
    lines.append(f"  Bordadura (faixa lateral): {geometry.desired_border_width_m():.2f} m")
    lines.append(f"  Antecipacao de desligamento: {geometry.longitudinal_anticipation_m:.2f} m")
    return "\n".join(lines)


def build_report(simulation: ObstacleBorderSimulation, crs_authid: str, tolerance_m: float) -> dict[str, object]:
    geometry = simulation.geometry
    swept_by_cluster = unary_union([item.swept_area for item in simulation.border_passes]) \
        if simulation.border_passes else Polygon()
    all_safety = unary_union([zone.safety_zone for zone in simulation.zones]) \
        if simulation.zones else Polygon()
    all_safety_area = polygonal_mask(all_safety)
    zones_by_id = {zone.obstacle_id: zone for zone in simulation.zones}
    pass_rows = []
    cuts = []
    for item in simulation.passes:
        unworked = item.unworked_area.difference(all_safety_area)
        offs = [e for e in item.events if e.event_type == WORK_OFF]
        ons = [e for e in item.events if e.event_type == WORK_ON]
        border_cover = unworked.intersection(swept_by_cluster)
        pass_cuts = [
            cut_breakdown(item.pass_id, interval, zones_by_id, geometry).to_dict()
            for interval in item.intervals
            if interval.state is WorkState.RAISED
        ]
        cuts.extend(pass_cuts)
        pass_rows.append({
            "pass_id": item.pass_id,
            "work_width_m": geometry.work_width_m,
            "working_offset_m": geometry.reference_to_working_line_longitudinal_m,
            "border_mode": geometry.border_mode.value,
            "border_width_m": geometry.desired_border_width_m(),
            "work_off_station": [round(e.station_m, 4) for e in offs],
            "work_on_station": [round(e.station_m, 4) for e in ons],
            "work_off_coordinate": [list(e.reference_xy) for e in offs],
            "work_on_coordinate": [list(e.reference_xy) for e in ons],
            "work_off_distance_m": [round(e.measured_distance_m, 4) for e in offs],
            "work_on_distance_m": [round(e.measured_distance_m, 4) for e in ons],
            "cut_distance_m": [cut["cut_distance_m"] for cut in pass_cuts],
            "anticipated_m": [cut["anticipated_m"] for cut in pass_cuts],
            "unworked_area_m2": round(_area(unworked), 4),
            "border_coverage_m2": round(_area(border_cover), 4),
            "border_gap_m2": round(_area(unworked.difference(swept_by_cluster)), 4)
            if simulation.border_passes else round(_area(unworked), 4),
            "border_overlap_m2": round(_area(item.main_work_area.intersection(swept_by_cluster)), 4),
            "strategy": simulation.strategy.value,
            "validation_status": simulation.status.value,
        })
    events = [event for item in simulation.passes for event in item.events]

    def events_ok(event_type: str) -> bool:
        return all(
            abs(e.measured_distance_m - e.target_distance_m) <= tolerance_m or bool(e.note)
            for e in events if e.event_type == event_type
        )

    border_target = sum(_area(item.target_area) for item in simulation.border_passes)
    border_gap = sum(_area(item.gap_area) for item in simulation.border_passes)
    border_overlap = sum(_area(item.overlap_area) for item in simulation.border_passes)
    return {
        "engine": "longitudinal_cut_v1",
        "crs": crs_authid,
        "strategy": simulation.strategy.value,
        "machine_geometry": geometry.to_dict(),
        "border_width_m": geometry.desired_border_width_m(),
        "obstacle_safety_m": max(
            (zone.physical_radius_m + zone.safety_margin_m for zone in simulation.zones), default=0.0
        ),
        "work_event_count": len(events),
        "work_off_ok": events_ok(WORK_OFF),
        "work_on_ok": events_ok(WORK_ON),
        "border_coverage_pct": round(100.0 * (1.0 - border_gap / border_target), 2)
        if border_target > 0 else None,
        "border_gap_m2": round(border_gap, 4),
        "border_overlap_m2": round(border_overlap, 4),
        "target_distance_m": geometry.required_cut_distance_m(),
        "longitudinal_anticipation_m": geometry.longitudinal_anticipation_m,
        "longitudinal_cut_rule": "barra encosta na zona (raio + margem) - antecipacao; largura/espacamento/bordadura nao entram",
        "max_cut_distance_m": max((cut["cut_distance_m"] for cut in cuts), default=None),
        "longitudinal_cuts": cuts,
        "cut_distance_tolerance_m": tolerance_m,
        "status": simulation.status.value,
        "warnings": list(simulation.warnings),
        "errors": list(simulation.errors),
        "obstacle_count": len(simulation.zones),
        "affected_pass_count": sum(1 for item in simulation.passes if item.affected),
        "border_passes": [
            {
                "cluster_id": item.cluster_id,
                "obstacle_ids": list(item.obstacle_ids),
                "length_m": round(item.trajectory.length, 3),
                "target_area_m2": round(_area(item.target_area), 4),
                "gap_area_m2": round(_area(item.gap_area), 4),
                "overlap_area_m2": round(_area(item.overlap_area), 4),
                "collision_area_m2": round(item.collision_area_m2, 4),
                "outside_area_m2": round(item.outside_area_m2, 4),
                "min_turn_radius_estimate_m": round(item.min_turn_radius_estimate_m, 3),
                "status": item.status.value,
                "issues": list(item.issues),
            }
            for item in simulation.border_passes
        ],
        "main_work_area_m2": round(_area(simulation.main_work_area), 4),
        "unworked_area_m2": round(_area(simulation.unworked_area), 4),
        "workable_area_m2": round(_area(simulation.workable_area), 4),
        "final_coverage_m2": round(_area(simulation.final_coverage), 4),
        "final_gap_m2": round(_area(simulation.final_gap), 4),
        "final_overlap_m2": round(_area(simulation.final_overlap), 4),
        "passes": pass_rows,
        "original_layers_modified": False,
    }
