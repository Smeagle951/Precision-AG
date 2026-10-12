# -*- coding: utf-8 -*-
"""Orquestrador Precision Lines v3: boundary -> guidance -> obstacle (spray|plant) -> rows -> smooth."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace

from .generation_progress import ProgressCallback, report_progress, scaled_progress

from ..domain.boundary_areas import BoundaryAreas
from ..domain.headland_layout import HeadlandLayout
from ..domain.machine_model import PlanterMachine, SprayerMachine
from ..domain.planting_avoidance_result import PlantingAvoidanceResult
from ..domain.precision_project import (
    SPRAY_HEADLAND_TURN_AUTOMATIC,
    PrecisionOperation,
    PrecisionProject,
)
from ..domain.turn_configuration import TurnConfiguration, TurnFinishMode, TurnType
from .boundary_engine import BoundaryPlan, HeadlandCenterline, build_boundary_plan
from .boundary_simplify import simplify_dense_boundary
from .export_engine import ExportBlockedError, ExportPackageResult, export_precision_lines_package
from .guidance_engine import TrafficPass, generate_traffic_passes
from .obstacle_buffer_engine import (
    ForbiddenRegion,
    ObstacleSafetyEnvelope,
    build_all_envelopes,
    build_all_planting_forbidden_regions,
    merge_planting_forbidden_regions,
)
from .obstacle_engine import AvoidedPath, apply_application_obstacle_avoidance, avoidance_summary
from .obstacle_grouping_engine import merge_adjacent_envelopes
from .obstacle_validation_engine import validate_avoided_paths
from .parallel_pass_engine import ParallelPass
from .path_smoothing_engine import smooth_guidance_layers, smooth_shutoff_segments
from .planting_kinematics_engine import generate_rows_from_tractor_paths, kinematics_from_planter
from .planting_obstacle_engine import apply_planting_avoidance_to_passes, planting_avoidance_summary
from .line_geometry import (
    MultiPolygon,
    Point,
    Segment,
    build_processing_boundary,
    clip_polyline_to_multipolygon,
    multipolygon_bbox,
)
from .row_engine import PlantingRow, generate_planting_rows
from .shutoff_engine import RowShutoffSegment, apply_row_shutoff, shutoff_summary
from .sprayer_traffic_engine import calculate_planting_shutoff
from .tire_track_engine import TireTrack, generate_tire_tracks, generate_tire_tracks_from_traffic
from .tramline_engine import TramlineZone, generate_tramline_zones, generate_tramline_zones_from_tire_tracks
from .turn_path_engine import TurnPath, TurnPathResult, generate_turn_paths
from .tractor_axis_engine import TractorAxis, generate_straight_tractor_axes
from .validation_engine import ValidationReport, validate_precision_project


class PrecisionLinesError(ValueError):
    """Erro no pipeline Precision Lines."""


@dataclass(frozen=True)
class PrecisionLinesResult:
    project: PrecisionProject
    boundary: BoundaryPlan | None
    planting_passes: list[TrafficPass]
    planting_rows: list[PlantingRow]
    spraying_passes: list[TrafficPass]
    tramline_zones: list[TramlineZone]
    shutoff_segments: list[RowShutoffSegment]
    shutoff_table: list[dict[str, object]]
    avoided_paths: list[AvoidedPath] = field(default_factory=list)
    obstacle_envelopes: list[ObstacleSafetyEnvelope] = field(default_factory=list)
    avoidance_table: list[dict[str, object]] = field(default_factory=list)
    planting_avoidance_results: list[PlantingAvoidanceResult] = field(default_factory=list)
    forbidden_regions: list[ForbiddenRegion] = field(default_factory=list)
    validation: ValidationReport = field(default_factory=ValidationReport)
    spraying_boundary: BoundaryPlan | None = None
    turn_paths: list[TurnPath] = field(default_factory=list)
    tire_tracks: list[TireTrack] = field(default_factory=list)
    tractor_axes: list[TractorAxis] = field(default_factory=list)
    # Desvio minimo da pulverizacao: um registro por passada x obstaculo analisado.
    spray_avoidance_records: list = field(default_factory=list)
    # Cabeceira automatica da pulverizacao (None = Extensao reta / operador).
    spray_headland_turns: object | None = None

    def report(self) -> dict[str, object]:
        return {
            "planting_pass_count": len(self.planting_passes),
            "planting_row_count": len(self.planting_rows),
            "spraying_pass_count": len(self.spraying_passes),
            "tramline_zone_count": len(self.tramline_zones),
            "shutoff_segment_count": len(self.shutoff_segments),
            "avoided_path_count": len(self.avoided_paths),
            "planting_avoidance_count": len(self.planting_avoidance_results),
            "turn_path_count": len(self.turn_paths),
            "tire_track_count": len(self.tire_tracks),
            "tractor_axis_count": len(self.tractor_axes),
            "validation_ok": self.validation.ok,
            "boundary": self.boundary.report() if self.boundary else {},
        }


def _operation_with_default_headland(
    operation: PrecisionOperation,
    *,
    default_pass_count: int,
) -> PrecisionOperation:
    headland = operation.headland
    width = operation.machine.operational_width_m
    if headland.pass_count <= 0 and headland.width_m <= 0 and default_pass_count > 0:
        headland = HeadlandLayout(
            pass_count=default_pass_count,
            width_m=width,
            effective_spacing_m=width,
            mode="follow_boundary",
            corner_mode=headland.corner_mode,
            sharp_angle_threshold_deg=headland.sharp_angle_threshold_deg,
            heading_sample_m=headland.heading_sample_m,
            extension_length_m=headland.extension_length_m,
            headland_mode=headland.headland_mode,
            outside_overlap_m=headland.outside_overlap_m,
        )
    elif headland.pass_count > 0:
        headland = HeadlandLayout(
            pass_count=headland.pass_count,
            width_m=width if headland.width_m <= 0 else headland.width_m,
            effective_spacing_m=headland.spacing_m,
            mode=headland.mode if headland.mode != "none" else "follow_boundary",
            corner_mode=headland.corner_mode,
            sharp_angle_threshold_deg=headland.sharp_angle_threshold_deg,
            heading_sample_m=headland.heading_sample_m,
            extension_length_m=headland.extension_length_m,
            headland_mode=headland.headland_mode,
            outside_overlap_m=headland.outside_overlap_m,
        )
    return PrecisionOperation(
        operation_id=operation.operation_id,
        machine=operation.machine,
        headland=headland,
        extension_m=operation.extension_m,
    )


def _with_simplified_boundary(project: PrecisionProject) -> PrecisionProject:
    """Limite superamostrado entra reduzido (desvio <= 2 mm) em todo o pipeline."""
    operational, summary = simplify_dense_boundary(project.field.operational_boundary)
    if project.field.field_boundary is project.field.operational_boundary:
        field_boundary = operational
    else:
        field_boundary, _ = simplify_dense_boundary(project.field.field_boundary)
    if not summary.applied and field_boundary is project.field.field_boundary:
        return project
    return replace(
        project,
        field=replace(project.field, operational_boundary=operational, field_boundary=field_boundary),
    )


def run_precision_lines(
    project: PrecisionProject,
    *,
    progress: ProgressCallback | None = None,
) -> PrecisionLinesResult:
    """Executa pipeline completo do projeto (v3: motores spray/plant separados)."""
    report_progress(progress, 2, "Validando projeto...")
    project.validate()
    project = _with_simplified_boundary(project)
    report_progress(progress, 5, "Calculando bordadura e area de trabalho...")
    ab_line = project.effective_ab_line()
    app_zone = project.effective_application_zone()
    allowed_area = app_zone.work_area_for_operation()

    planting_boundary: BoundaryPlan | None = None
    spraying_boundary: BoundaryPlan | None = None
    planting_work_area = allowed_area
    spraying_work_area = allowed_area

    if project.planting is not None:
        planting_op = _operation_with_default_headland(project.planting, default_pass_count=0)
        if planting_op.headland.pass_count > 0:
            planting_boundary = build_boundary_plan(
                project.field.operational_boundary,
                planting_op,
                ab_line.start,
                ab_line.end,
                field_boundary=project.field.field_boundary,
            )
            if planting_boundary.inner_boundary:
                planting_work_area = planting_boundary.inner_boundary

    if project.spraying is not None:
        spraying_op = _operation_with_default_headland(project.spraying, default_pass_count=0)
        if spraying_op.headland.pass_count > 0:
            spraying_boundary = build_boundary_plan(
                project.field.operational_boundary,
                spraying_op,
                ab_line.start,
                ab_line.end,
                field_boundary=project.field.field_boundary,
            )
            if spraying_boundary.inner_boundary:
                spraying_work_area = spraying_boundary.inner_boundary

    # Preferencia de bordadura primaria: plantio (shutoff no limite interno).
    boundary = planting_boundary or spraying_boundary

    planting_passes: list[TrafficPass] = []
    if project.planting is not None:
        report_progress(progress, 10, "Gerando passadas de plantio...")
        planting_passes = generate_traffic_passes(
            planting_work_area,
            ab_line,
            project.planting,
            clip_boundary=project.field.operational_boundary,
        )
        _log_component_coverage(
            project.field.operational_boundary,
            planting_work_area,
            planting_passes,
            project.planting,
            planting_boundary,
        )

    spraying_passes: list[TrafficPass] = []
    if project.spraying is not None:
        report_progress(progress, 14, "Gerando passadas de pulverizacao...")
        spray_area = spraying_work_area
        if project.application_zone and project.application_zone.continuous_spray_across_fields:
            spray_area = allowed_area
        spraying_passes = generate_traffic_passes(
            spray_area,
            ab_line,
            project.spraying,
            clip_boundary=project.field.operational_boundary,
        )

    obstacles = list(project.obstacles)
    avoided_paths: list[AvoidedPath] = []
    envelopes: list[ObstacleSafetyEnvelope] = []
    planting_results: list[PlantingAvoidanceResult] = []
    forbidden: list[ForbiddenRegion] = []
    # Passadas com desvio de obstaculo saem da reta de proposito.
    detoured_passes: dict[str, set] = {"plantio": set(), "pulverizacao": set()}

    # Limite + extensao e caro (buffer do anel real) e era refeito 4-5x com os
    # mesmos parametros. Uma entrada por extensao basta para todo o pipeline.
    _process_area_cache: dict[float, MultiPolygon] = {}

    def process_area(extension_m: float) -> MultiPolygon:
        key = round(float(extension_m), 4)
        cached = _process_area_cache.get(key)
        if cached is None:
            cached = build_processing_boundary(
                project.field.operational_boundary,
                extension_m,
            )
            _process_area_cache[key] = cached
        return cached

    spray_process_area: MultiPolygon | None = None
    if project.spraying is not None:
        spray_process_area = process_area(project.spraying.extension_m)

    spray_records: list = []
    # Pulverizacao: motor de aplicacao (barra)
    if obstacles and project.avoidance.enabled() and project.spraying is not None:
        report_progress(progress, 18, "Desvio de obstaculos (pulverizacao)...")
        sprayer = project.spraying.machine
        assert isinstance(sprayer, SprayerMachine)
        envelopes = merge_adjacent_envelopes(
            build_all_envelopes(obstacles, sprayer),
            project.avoidance.merge_adjacent_envelopes_m,
        )
        spraying_passes, spray_avoided = apply_application_obstacle_avoidance(
            spraying_passes,
            obstacles,
            sprayer,
            project.avoidance,
            allowed_area=spray_process_area or allowed_area,
            progress=scaled_progress(progress, 20, 38),
            report=spray_records,
        )
        avoided_paths.extend(spray_avoided)
        detoured_passes["pulverizacao"].update(item.pass_id for item in spray_avoided)
        _pump_ui_events()
        if spraying_boundary is not None and spraying_boundary.headland_centerlines:
            spraying_boundary, headland_avoided = _apply_spray_avoidance_to_boundary(
                spraying_boundary,
                obstacles,
                sprayer,
                project,
                allowed_area=allowed_area,
                report=spray_records,
            )
            avoided_paths.extend(headland_avoided)
            if planting_boundary is None:
                boundary = spraying_boundary

    # Plantio: motor de cinematica (trator -> implemento -> linhas)
    planting_rows: list[PlantingRow] = []
    if project.planting is not None:
        planter = project.planting.machine
        assert isinstance(planter, PlanterMachine)
        kinematics = project.planting_kinematics or kinematics_from_planter(planter)

        if obstacles and project.planting_avoidance.is_enabled():
            report_progress(progress, 40, "Desvio de obstaculos (plantio)...")
            forbidden = merge_planting_forbidden_regions(
                build_all_planting_forbidden_regions(
                    obstacles, kinematics, project.planting_avoidance
                ),
                project.planting_avoidance.merge_obstacles_m,
            )
            plant_process = process_area(project.planting.extension_m)
            planting_passes, planting_results, plant_avoided = apply_planting_avoidance_to_passes(
                planting_passes,
                obstacles,
                kinematics,
                project.planting_avoidance,
                planter,
                allowed_area=plant_process or planting_work_area,
                progress=scaled_progress(progress, 42, 68),
            )
            avoided_paths.extend(plant_avoided)
            detoured_passes["plantio"].update(item.pass_id for item in plant_avoided)
            detoured_passes["plantio"].update(item.pass_id for item in planting_results)
            _pump_ui_events()
            if planting_boundary is not None and planting_boundary.headland_centerlines:
                planting_boundary, headland_plant_avoided = _apply_planting_avoidance_to_boundary(
                    planting_boundary,
                    obstacles,
                    kinematics,
                    project.planting_avoidance,
                    planter,
                )
                avoided_paths.extend(headland_plant_avoided)
                boundary = planting_boundary
            if not envelopes:
                envelopes = merge_adjacent_envelopes(
                    build_all_envelopes(obstacles, planter),
                    project.planting_avoidance.merge_obstacles_m,
                )

        obstacle_off_areas = _obstacle_shutoff_areas(obstacles)
        full_shutoff = project.planting is not None and project.spraying is not None
        # Geracao lazy: so materializa as N linhas de semente quando alguem vai
        # consumi-las (shutoff completo, zona de obstaculo ou desvio aplicado).
        # No modo Rapido as linhas ficam apenas no motor (row_id/offset), pois o
        # mapa mostra a trajetoria do trator, nao as 80 linhas da plantadeira.
        need_virtual_rows = (
            full_shutoff or bool(obstacle_off_areas) or bool(planting_results)
        ) and project.processing.materialize_virtual_rows
        if need_virtual_rows:
            report_progress(progress, 70, "Gerando linhas virtuais de plantio (shutoff)...")
            row_clip_area = process_area(project.planting.extension_m)
            row_passes = planting_passes
            if not full_shutoff and (obstacle_off_areas or planting_results):
                row_passes = (
                    _passes_near_multipolygon(
                        planting_passes,
                        obstacle_off_areas,
                        margin_m=30.0,
                    )
                    if obstacle_off_areas
                    else []
                )
                if not row_passes and planting_results:
                    hit_ids = {item.pass_id for item in planting_results}
                    row_passes = [p for p in planting_passes if p.pass_no in hit_ids]
            planting_rows = generate_rows_from_tractor_paths(
                row_passes,
                planter,
                kinematics,
                work_area=row_clip_area or planting_work_area,
            )
            _pump_ui_events()
            if not planting_rows and row_passes:
                planting_rows = generate_planting_rows(
                    row_passes,
                    planter,
                    work_area=row_clip_area or planting_work_area,
                )
        else:
            report_progress(
                progress,
                70,
                "Linhas virtuais adiadas (calculadas no cruzamento shutoff)...",
            )

        # Bordadura: so trajetoria do trator no mapa (centerlines).
        # Linhas de semente do anel ficam virtuais se necessario no futuro;
        # nao geramos N offsets visiveis ao redor do pivo.

    report_progress(progress, 76, "Suavizando trajetorias...")
    planting_passes, planting_rows, spraying_passes, avoided_paths, boundary = smooth_guidance_layers(
        planting_passes=planting_passes,
        planting_rows=planting_rows,
        spraying_passes=spraying_passes,
        avoided_paths=avoided_paths,
        boundary=boundary,
        config=project.line_smoothing,
        planting_detoured=detoured_passes["plantio"],
        spraying_detoured=detoured_passes["pulverizacao"],
    )
    # A suavizacao preserva o desenho da curva, mas pode deixar as pontas antes
    # do buffer externo em linhas curvas. Reabre e recorta o eixo do plantio no
    # mesmo limite operacional + extensao informado na GUI.
    if project.planting is not None and planting_passes:
        planting_clip_area = process_area(project.planting.extension_m)
        planting_passes = _reclip_traffic_passes(
            planting_passes,
            planting_clip_area,
            extension_m=project.planting.extension_m,
        )
    # Re-clipa linhas virtuais apos suavizacao (calculo; nao vao ao mapa).
    if project.planting is not None and planting_rows:
        row_clip_area = process_area(project.planting.extension_m)
        planting_rows = _reclip_planting_rows(planting_rows, row_clip_area)
    if project.spraying is not None and spraying_passes:
        spray_clip_area = spray_process_area or process_area(
            project.spraying.extension_m
        )
        spraying_passes = _reclip_traffic_passes(
            spraying_passes,
            spray_clip_area,
            extension_m=project.spraying.extension_m,
        )
    tractor_axes: list[TractorAxis] = []
    if project.planting is not None and planting_passes:
        tractor_axes = generate_straight_tractor_axes(
            planting_passes,
            ab_start=ab_line.start,
            ab_end=ab_line.end,
            operational_boundary=project.field.operational_boundary,
            extension_m=project.planting.extension_m,
        )
    if planting_boundary is None:
        spraying_boundary = boundary

    tramline_zones: list[TramlineZone] = []
    tire_tracks: list[TireTrack] = []
    if project.spraying is not None:
        report_progress(progress, 82, "Rastros de pneu...")
        sprayer = project.spraying.machine
        assert isinstance(sprayer, SprayerMachine)
        spray_for_tracks = list(spraying_passes)
        if spraying_boundary is not None and spraying_boundary.headland_centerlines:
            spray_for_tracks.extend(
                _centerline_as_pass(line, project.spraying)
                for line in spraying_boundary.headland_centerlines
            )
        if sprayer.traffic is not None:
            tire_tracks = generate_tire_tracks_from_traffic(spray_for_tracks, sprayer.traffic)
        else:
            eff = sprayer.effective_track
            tire_tracks = generate_tire_tracks(
                spray_for_tracks,
                track_width_m=eff.track_width_m,
                tire_width_m=eff.tire_width_m,
            )
        # Tramlines so quando plantio+aplicacao no mesmo projeto (cruzamento shutoff).
        # Etapa 1 so pulverizacao: rastros no mapa; tramlines no botao Cruzar.
        if project.planting is not None:
            tramline_zones = generate_tramline_zones_from_tire_tracks(
                tire_tracks,
                machine_id=sprayer.machine_id,
                operation_id=project.spraying.operation_id,
                clip_area=allowed_area,
            )

    # Shutoff espacial (ROW × rastro / miolo): so quando plantio E pulverizacao
    # estao no mesmo projeto. Etapas separadas usam o botao Cruzar — evita freeze.
    shutoff_segments: list[RowShutoffSegment] = []
    report_progress(progress, 88, "Shutoff e zonas de desligamento...")
    # Zona do obstaculo desliga a semeadura: quando o desvio nao cabe na faixa,
    # o trator passa perto e as linhas sobre o obstaculo saem de operacao.
    obstacle_off_areas = _obstacle_shutoff_areas(obstacles)
    full_shutoff = project.planting is not None and project.spraying is not None
    if planting_rows and (full_shutoff or obstacle_off_areas):
        on_main = None
        off_main = None
        if full_shutoff and (
            project.shutoff_on_headland_inner
            and planting_boundary is not None
            and planting_boundary.areas.inner_work_area
        ):
            on_main = planting_boundary.areas.inner_work_area
        elif full_shutoff and (
            project.shutoff_on_headland_inner
            and planting_boundary is not None
            and planting_boundary.areas.headland_area
        ):
            off_main = planting_boundary.areas.headland_area
        if obstacle_off_areas:
            off_main = list(off_main or []) + obstacle_off_areas
        shutoff_segments = apply_row_shutoff(
            planting_rows,
            tramline_zones if (full_shutoff and project.shutoff_on_tramlines) else [],
            off_areas=off_main,
            on_areas=on_main,
            shutoff_on_tramlines=full_shutoff and project.shutoff_on_tramlines,
            tire_tracks=tire_tracks if (full_shutoff and project.shutoff_on_tramlines) else None,
        )
    shutoff_segments = smooth_shutoff_segments(shutoff_segments, project.line_smoothing)
    shutoff_table = shutoff_summary(shutoff_segments)
    if (
        project.planting is not None
        and project.spraying is not None
        and isinstance(project.spraying.machine, SprayerMachine)
        and project.spraying.machine.traffic is not None
        and isinstance(project.planting.machine, PlanterMachine)
    ):
        classifications = calculate_planting_shutoff(
            project.planting.machine,
            project.spraying.machine.traffic,
        )
        by_row = {item.row_id: item for item in classifications}
        for item in shutoff_table:
            row_id = item.get("row_id")
            if row_id in by_row:
                cls = by_row[int(row_id)]
                item["offset_m"] = round(cls.offset_m, 3)
                item["zone_side"] = cls.zone_side or ""
                if cls.action == "DESLIGA" and item.get("action") == "LIGA":
                    item["action"] = "DESLIGA"
                    item["detail"] = f"zona pneu {cls.zone_side}"
    avoidance_table = avoidance_summary(avoided_paths)
    if planting_results:
        avoidance_table.extend(planting_avoidance_summary(planting_results))

    turn_paths: list[TurnPath] = []
    if (
        project.headland_turn_mode == "offset_turn"
        and planting_passes
        and planting_boundary is not None
        and planting_boundary.areas.headland_area
    ):
        turn_paths = _generate_offset_turns(planting_passes, planting_boundary.areas, project)

    spray_headland_turns = None
    if (
        project.spraying is not None
        and spraying_passes
        and project.spray_headland_turn_mode == SPRAY_HEADLAND_TURN_AUTOMATIC
    ):
        report_progress(progress, 90, "Cabeceira automatica da pulverizacao...")
        spray_headland_turns = _plan_spray_headland_turns(
            project,
            spraying_passes,
            work_area=spraying_work_area,
            operational_area=spray_process_area or process_area(project.spraying.extension_m),
            ab_line=ab_line,
        )

    report_progress(progress, 92, "Validando geometrias...")
    validation = validate_precision_project(
        project,
        boundary=boundary,
        planting_passes=planting_passes,
        planting_rows=planting_rows,
        tramline_zones=tramline_zones,
        shutoff_segments=shutoff_segments,
    )
    if avoided_paths:
        obs_report = validate_avoided_paths(
            avoided_paths,
            obstacles,
            allowed_area,
            project.avoidance,
            max_paths=project.processing.validation_sample or None,
        )
        validation.checks.extend(obs_report.checks)
        validation.warnings.extend(obs_report.warnings)
        validation.errors.extend(obs_report.errors)
        if obs_report.errors:
            validation.ok = False
    if spray_records:
        _apply_spray_conflict_validation(validation, spray_records)
    if spray_headland_turns is not None:
        _apply_spray_headland_validation(validation, spray_headland_turns)
    _apply_spacing_validation(
        validation,
        project,
        ab_line,
        planting_passes=planting_passes,
        spraying_passes=spraying_passes,
        plans=(planting_boundary, spraying_boundary),
        detoured_passes=detoured_passes,
    )

    report_progress(progress, 100, "Geracao concluida.")
    return PrecisionLinesResult(
        project=project,
        boundary=boundary,
        planting_passes=planting_passes,
        planting_rows=planting_rows,
        spraying_passes=spraying_passes,
        tramline_zones=tramline_zones,
        shutoff_segments=shutoff_segments,
        shutoff_table=shutoff_table,
        avoided_paths=avoided_paths,
        obstacle_envelopes=envelopes,
        avoidance_table=avoidance_table,
        planting_avoidance_results=planting_results,
        forbidden_regions=forbidden,
        validation=validation,
        spraying_boundary=spraying_boundary,
        turn_paths=turn_paths,
        tire_tracks=tire_tracks,
        tractor_axes=tractor_axes,
        spray_avoidance_records=spray_records,
        spray_headland_turns=spray_headland_turns,
    )


def _plan_spray_headland_turns(project, spraying_passes, *, work_area, operational_area, ab_line):
    """Manobra automatica: raio do PULVERIZADOR, nunca o da plantadeira."""
    from .application_obstacle_engine import build_spray_safety_zones
    from .spray_headland_turns import machine_half_outer_width_m, plan_spray_headland_turns

    sprayer = project.spraying.machine
    zones = build_spray_safety_zones(list(project.obstacles))
    return plan_spray_headland_turns(
        spraying_passes,
        work_area=work_area,
        operational_area=operational_area,
        radius_m=sprayer.sprayer_minimum_turn_radius_m,
        clearance_m=machine_half_outer_width_m(sprayer),
        obstacles=[zone.polygon for zone in zones if zone.polygon is not None],
        ab_heading=(ab_line.end[0] - ab_line.start[0], ab_line.end[1] - ab_line.start[1]),
    )


def _apply_spray_headland_validation(validation: ValidationReport, turns) -> None:
    """Curva que nao cabe vira aviso (nunca e forcada nem bloqueia a aplicacao)."""
    validation.checks.append(
        f"Cabeceira automatica: {len(turns.turns)} curva(s) aceita(s), "
        f"{len(turns.rejected)} recusada(s)"
    )
    code = str(turns.report.get("status") or "SPRAY_HEADLAND_TURN")
    for message in turns.warnings:
        validation.add_warning(code if code not in ("OK", "PARTIAL") else "SPRAY_HEADLAND_TURN", message)


def _apply_spray_conflict_validation(validation: ValidationReport, records: list) -> None:
    """Desvio minimo: resumo NONE/LATERAL/FULL_CONTOUR e falha segura UNRESOLVED."""
    from .application_obstacle_engine import (
        SPRAY_TURN_RADIUS_MISSING,
        SprayAvoidanceType,
        spray_conflict_counts,
    )

    counts = spray_conflict_counts(records)
    validation.checks.append(
        "Desvio pulverizacao (por passada): "
        + ", ".join(f"{name}={counts.get(name, 0)}" for name in (
            SprayAvoidanceType.NONE.value,
            SprayAvoidanceType.LATERAL.value,
            SprayAvoidanceType.FULL_CONTOUR.value,
            SprayAvoidanceType.UNRESOLVED.value,
        ))
    )
    if any(item.reason == SPRAY_TURN_RADIUS_MISSING for item in records):
        validation.add_warning("SPRAYER_TURN_RADIUS_MISSING", SPRAY_TURN_RADIUS_MISSING)
    for item in records:
        if item.avoidance_type != SprayAvoidanceType.UNRESOLVED.value:
            continue
        where = "bordadura" if item.pass_role == "headland" else "passada"
        validation.add_error(
            "SPRAY_AVOIDANCE_UNRESOLVED",
            f"Pulverizacao: {where} {item.pass_id} x {item.obstacle_id} sem desvio seguro"
            + (f" ({item.reason})" if item.reason else "")
            + " — trajetoria original mantida; revise antes de operar.",
        )


def _polyline_bbox(points: tuple[Point, ...] | list[Point]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _bboxes_intersect(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    *,
    margin_m: float = 0.0,
) -> bool:
    return not (
        a[2] + margin_m < b[0]
        or b[2] + margin_m < a[0]
        or a[3] + margin_m < b[1]
        or b[3] + margin_m < a[1]
    )


def _passes_near_multipolygon(
    passes: list[TrafficPass],
    areas: MultiPolygon,
    *,
    margin_m: float = 30.0,
) -> list[TrafficPass]:
    """Filtra passadas cujo corredor cruza (ou passa perto) das zonas off/on."""
    if not passes or not areas:
        return []
    zone_bbox = multipolygon_bbox(areas)
    out: list[TrafficPass] = []
    for item in passes:
        pts = item.line_points()
        if len(pts) < 2:
            continue
        if _bboxes_intersect(_polyline_bbox(pts), zone_bbox, margin_m=margin_m):
            out.append(item)
    return out


def _reclip_planting_rows(
    rows: list[PlantingRow],
    clip_area: MultiPolygon | None,
) -> list[PlantingRow]:
    """Garante que linhas fisicas fiquem dentro do limite operacional+extensao (ou anel)."""
    if not rows or not clip_area:
        return rows
    from uuid import uuid4

    out: list[PlantingRow] = []
    for row in rows:
        pts = list(row.line_points())
        if len(pts) < 2:
            continue
        chunks = clip_polyline_to_multipolygon(pts, clip_area)
        if not chunks:
            continue
        for chunk in chunks:
            if len(chunk) < 2:
                continue
            out.append(
                PlantingRow(
                    fs_id=str(uuid4()),
                    row_id=row.row_id,
                    pass_id=row.pass_id,
                    machine_id=row.machine_id,
                    spacing_m=row.spacing_m,
                    direction=row.direction,
                    offset_m=row.offset_m,
                    azimuth_deg=row.azimuth_deg,
                    segment=Segment(chunk[0], chunk[-1]),
                    path_points=tuple(chunk) if len(chunk) >= 2 else (),
                )
            )
    return out


def _reclip_traffic_passes(
    passes: list[TrafficPass],
    clip_area: MultiPolygon | None,
    *,
    extension_m: float = 0.0,
) -> list[TrafficPass]:
    """Mantem passadas dentro do limite operacional + extensao, sem encurtar pontas.

    Apos suavizacao/desvio o clip amostral pode cortar metros antes da borda.
    Re-estende as pontas e recorta no processing_boundary (= talhao + extensao GUI).
    """
    if not passes or not clip_area:
        return passes
    from .line_geometry import clip_polyline_exact, extend_polyline_ends

    out: list[TrafficPass] = []
    for item in passes:
        pts = list(item.line_points())
        if len(pts) < 2:
            continue
        # Reabre as pontas antes do clip final para nao deixar falha na borda.
        extend_by = max(float(extension_m), item.spacing_m * 0.5 if item.spacing_m else 0.0)
        if extend_by > 0:
            pts = extend_polyline_ends(pts, extend_by)
        chunks = clip_polyline_exact(pts, clip_area)
        if not chunks:
            continue
        for chunk in chunks:
            if len(chunk) < 2:
                continue
            if len(chunk) > 480:
                chunk = _simplify_within_tolerance(chunk)
            path = tuple(chunk) if len(chunk) >= 2 else ()
            out.append(
                TrafficPass(
                    pass_no=item.pass_no,
                    fs_id=item.fs_id,
                    operation_id=item.operation_id,
                    spacing_m=item.spacing_m,
                    width_m=item.width_m,
                    offset_m=item.offset_m,
                    azimuth_deg=item.azimuth_deg,
                    direction=item.direction,
                    clipped_segment=Segment(chunk[0], chunk[-1]),
                    guidance_segment=Segment(chunk[0], chunk[-1]),
                    path_points=path,
                )
            )
    return out if out else passes


# Simplificacao das passadas: desvio maximo da geometria exata.
_PASS_SIMPLIFY_TOLERANCE_M = 0.002


def _simplify_within_tolerance(points: list[Point]) -> list[Point]:
    """Remove vertices redundantes sem afastar a passada mais que 2 mm da exata.

    Reduzir por passo fixo cria cordas em curva e muda a distancia entre passadas.
    """
    try:
        from shapely.geometry import LineString as _ShapelyLine

        simplified = _ShapelyLine(points).simplify(
            _PASS_SIMPLIFY_TOLERANCE_M, preserve_topology=False
        )
        coords = [(float(x), float(y)) for x, y in simplified.coords]
        if len(coords) >= 2:
            return coords
    except Exception:
        pass
    from .line_geometry import decimate_polyline

    return list(decimate_polyline(points, min_step_m=0.75, max_points=480))


def _log_component_coverage(
    boundary: MultiPolygon,
    work_area: MultiPolygon,
    passes: list[TrafficPass],
    operation: PrecisionOperation,
    plan: BoundaryPlan | None,
) -> None:
    """Diagnostico por componente do miolo (somente log, nunca interrompe)."""
    from .polygon_components import (
        component_debug_report,
        log_component_report,
        validate_component_coverage,
    )

    try:
        border_lines = [line.line_points() for line in plan.headland_centerlines] if plan else []
        coverage = validate_component_coverage(
            passes,
            work_area,
            implement_width_m=operation.machine.operational_width_m,
            border_lines=border_lines,
            border_reach_m=plan.reserved_width_m if plan else None,
        )
        lines = component_debug_report(
            operation.operation_id or "talhao",
            boundary,
            work_area,
            coverage,
            logical_passes=len({item.pass_no for item in passes}),
            features=len(passes),
        )
    except Exception as exc:
        logging.getLogger("fortsmart_precision.generator").debug(
            "Diagnostico de componentes indisponivel: %s", exc
        )
        return
    log_component_report(lines, coverage)


def _apply_spacing_validation(
    validation: ValidationReport,
    project: PrecisionProject,
    ab_line,
    *,
    planting_passes: list[TrafficPass],
    spraying_passes: list[TrafficPass],
    plans: tuple[BoundaryPlan | None, ...],
    detoured_passes: dict[str, set] | None = None,
) -> None:
    """Espacamento medido (passadas, bordadura, limite interno) entra na validacao.

    Passadas com desvio de obstaculo ficam fora da medida da reta oficial.
    """
    from .guidance_engine import traffic_pass_spacing_report
    from .spacing_validation import (
        HEADLAND_OFFSET_OUT_OF_TOLERANCE,
        PASS_SPACING_OUT_OF_TOLERANCE,
        log_spacing_report,
        validate_adjacent_pass_spacing,
    )

    crs = project.field.crs_authid
    for label, passes, operation in (
        ("plantio", planting_passes, project.planting),
        ("pulverizacao", spraying_passes, project.spraying),
    ):
        detoured = (detoured_passes or {}).get(label, set())
        passes = [item for item in passes if item.pass_no not in detoured]
        if operation is None or not passes:
            continue
        spacing = operation.pass_spacing_m
        try:
            report = traffic_pass_spacing_report(passes, ab_line, operation, label=label)
            adjacent = validate_adjacent_pass_spacing(
                ((round(-item.offset_m / spacing), item.line_points()) for item in passes),
                spacing,
                label=label,
            )
        except Exception as exc:  # medicao nunca derruba a geracao
            logging.getLogger("fortsmart_precision.spacing").debug("Espacamento indisponivel: %s", exc)
            continue
        if report is not None:
            log_spacing_report(report, crs_authid=crs)
            validation.checks.append(
                f"Espacamento {label}: erro maximo {report.max_abs_error_m:.6f} m "
                f"(tolerancia {report.tolerance_m:.3f} m; {len(detoured)} passada(s) com "
                "desvio de obstaculo fora da medida)"
            )
            for message in report.errors:
                validation.add_error(PASS_SPACING_OUT_OF_TOLERANCE, message)
        log_spacing_report(adjacent, crs_authid=crs)
        validation.checks.append(
            f"Distancia normal entre passadas vizinhas {label}: "
            f"min {adjacent.min_spacing_m:.4f} m, max {adjacent.max_spacing_m:.4f} m "
            f"(esperado {spacing:.2f} m; {len(adjacent.pairs)} par(es))"
        )
        for message in adjacent.errors:
            validation.add_error(PASS_SPACING_OUT_OF_TOLERANCE, message)
        if label != "plantio":
            continue
        if report is not None and len(report.samples) >= 2:
            measured = (report.min_spacing_m, report.max_spacing_m)
        elif adjacent.pairs:
            measured = (adjacent.min_spacing_m, adjacent.max_spacing_m)
        else:
            continue
        _apply_interpass_gap(validation, operation.machine, measured, "plantio")
    for plan in plans:
        for item in ((plan.offset_validation or {}) if plan else {}).values():
            validation.checks.append(
                f"Offset {item['label']}: erro maximo {item['max_abs_error_m']:.6f} m"
            )
            for message in item["errors"]:
                validation.add_error(HEADLAND_OFFSET_OUT_OF_TOLERANCE, message)
    planting_plan = plans[0] if plans else None
    if (
        project.planting is not None
        and planting_plan is not None
        and _headland_uses_planter_width(project.planting)
    ):
        levels = ((planting_plan.offset_validation or {}).get("headland") or {}).get("levels") or []
        centers = [(lvl["min_distance_m"] + lvl["max_distance_m"]) / 2.0 for lvl in levels]
        distances = [b - a for a, b in zip(centers, centers[1:])]
        if distances:
            _apply_interpass_gap(
                validation, project.planting.machine, (min(distances), max(distances)), "bordadura"
            )


def _headland_uses_planter_width(operation: PrecisionOperation) -> bool:
    """Bordadura feita pela mesma plantadeira (passo = largura operacional dela)."""
    headland = operation.headland
    width = operation.machine.operational_width_m
    spacing = headland.spacing_m if headland.width_m > 0 else width
    return abs(spacing - width) <= 1e-6


def _apply_interpass_gap(
    validation: ValidationReport,
    machine,
    center_distances: tuple[float, ...],
    label: str,
) -> None:
    """Encontro entre a ultima linha de uma passada e a primeira da vizinha."""
    from ..domain.planter_geometry import (
        INTERPASS_ROW_GAP_OUT_OF_TOLERANCE,
        planter_debug_report,
        validate_interpass_row_gap,
    )

    geometry = getattr(machine, "geometry_config", None)
    if geometry is None:
        return
    reports = [
        validate_interpass_row_gap(distance, geometry.row_count, geometry.row_spacing_m)
        for distance in center_distances
    ]
    worst = max(reports, key=lambda item: abs(item.error_m))
    logger = logging.getLogger("fortsmart_precision.spacing")
    if label == "plantio":
        for line in planter_debug_report(geometry, (0.0, worst.center_distance_m)):
            logger.info(line)
    validation.checks.append(
        f"Encontro entre passadas {label}: {worst.actual_gap_m:.3f} m "
        f"(esperado {worst.expected_gap_m:.3f} m; {geometry.row_count} linhas x "
        f"{geometry.row_spacing_m:.2f} m; eixo a eixo {geometry.working_width_m:.2f} m)"
    )
    if worst.ok:
        return
    # Linhas da maquina so analisam: a largura informada continua valendo.
    validation.add_warning(INTERPASS_ROW_GAP_OUT_OF_TOLERANCE, f"{label}: {worst.message()}")


def _obstacle_shutoff_areas(obstacles) -> list:
    """Zonas onde a semeadura desliga: geometria do obstaculo + margem.

    Nao inclui meia largura do implemento — quem decide o desligamento e a
    linha individual passar sobre o obstaculo, nao o centro da maquina.
    """
    from .obstacle_buffer_engine import build_safety_zone

    areas = []
    for obstacle in obstacles or []:
        try:
            zone = build_safety_zone(obstacle)
        except Exception:
            continue
        if zone is not None:
            areas.append(zone.geometry)
    return areas


def _pump_ui_events() -> None:
    try:
        from qgis.PyQt.QtWidgets import QApplication

        QApplication.processEvents()
    except Exception:
        pass


def _decimate_pass_for_headland_avoidance(
    traffic_pass: TrafficPass,
    *,
    max_points: int = 720,
) -> TrafficPass:
    """Prepara o anel de bordadura para desvio sem destruir a forma do talhao.

    A linha do trator precisa permanecer a mesma polilinha (offset) da bordadura.
    Decimar grosso (passo 1 m / 180 pts) cria cordas retas — o trator 'corta' a
    curva e deixa de acompanhar a camada 02_Bordadura. Densificacao fina
    (0,35 m, ate 720 pts) e a mesma da geometria mestre.
    """
    from .line_geometry import decimate_polyline

    pts = list(traffic_pass.line_points())
    if len(pts) <= max_points:
        return traffic_pass
    closed = len(pts) >= 4 and pts[0] == pts[-1]
    dec = decimate_polyline(pts, min_step_m=0.35, max_points=max_points)
    if closed and dec and dec[0] != dec[-1]:
        dec = list(dec) + [dec[0]]
    return TrafficPass(
        pass_no=traffic_pass.pass_no,
        fs_id=traffic_pass.fs_id,
        operation_id=traffic_pass.operation_id,
        spacing_m=traffic_pass.spacing_m,
        width_m=traffic_pass.width_m,
        offset_m=traffic_pass.offset_m,
        azimuth_deg=traffic_pass.azimuth_deg,
        direction=traffic_pass.direction,
        clipped_segment=traffic_pass.clipped_segment,
        guidance_segment=Segment(dec[0], dec[-1]),
        path_points=tuple(dec),
    )


def _centerline_as_pass(line: HeadlandCenterline, operation: PrecisionOperation) -> TrafficPass:
    pts = line.line_points()
    return TrafficPass(
        pass_no=line.pass_no,
        fs_id=line.fs_id,
        operation_id=operation.operation_id,
        spacing_m=operation.pass_spacing_m,
        width_m=operation.machine.operational_width_m,
        offset_m=line.offset_from_outer_m,
        azimuth_deg=line.azimuth_deg,
        direction="forward",
        clipped_segment=line.segment,
        guidance_segment=line.segment,
        path_points=pts if len(pts) >= 2 else (),
    )


def _pass_to_centerline(original: HeadlandCenterline, traffic_pass: TrafficPass) -> HeadlandCenterline:
    pts = list(traffic_pass.line_points())
    # Anel de bordadura deve permanecer fechado (mesma topologia da polilinha).
    if (
        original.path_points
        and len(original.path_points) >= 4
        and original.path_points[0] == original.path_points[-1]
        and len(pts) >= 3
        and pts[0] != pts[-1]
    ):
        pts = pts + [pts[0]]
    return replace(
        original,
        segment=traffic_pass.guidance_segment,
        path_points=tuple(pts) if len(pts) >= 2 else (),
    )


def _apply_spray_avoidance_to_boundary(
    plan: BoundaryPlan,
    obstacles,
    sprayer: SprayerMachine,
    project: PrecisionProject,
    *,
    allowed_area,
    report: list | None = None,
) -> tuple[BoundaryPlan, list]:
    if project.spraying is None:
        return plan, []
    fake_passes = [
        _decimate_pass_for_headland_avoidance(_centerline_as_pass(line, project.spraying))
        for line in plan.headland_centerlines
    ]
    headland_records: list = []
    modified, avoided = apply_application_obstacle_avoidance(
        fake_passes,
        obstacles,
        sprayer,
        project.avoidance,
        allowed_area=allowed_area,
        report=headland_records,
    )
    if report is not None:
        report.extend(replace(item, pass_role="headland") for item in headland_records)
    by_id = {item.fs_id: item for item in modified}
    updated = tuple(
        _pass_to_centerline(line, by_id.get(line.fs_id, fake_passes[index]))
        for index, line in enumerate(plan.headland_centerlines)
    )
    return plan.with_centerlines(updated), avoided


def _apply_planting_avoidance_to_boundary(
    plan: BoundaryPlan,
    obstacles,
    kinematics,
    config,
    planter: PlanterMachine,
) -> tuple[BoundaryPlan, list]:
    if not plan.headland_centerlines:
        return plan, []
    from ..domain.precision_project import PrecisionOperation

    fake_op = PrecisionOperation(operation_id="planting_headland", machine=planter)
    fake_passes = [
        _decimate_pass_for_headland_avoidance(_centerline_as_pass(line, fake_op))
        for line in plan.headland_centerlines
    ]
    modified, _results, avoided = apply_planting_avoidance_to_passes(
        fake_passes,
        obstacles,
        kinematics,
        config,
        planter,
    )
    by_id = {item.fs_id: item for item in modified}
    updated = tuple(
        _pass_to_centerline(line, by_id.get(line.fs_id, fake_passes[index]))
        for index, line in enumerate(plan.headland_centerlines)
    )
    return plan.with_centerlines(updated), avoided


def _generate_offset_turns(
    planting_passes: list[TrafficPass],
    areas: BoundaryAreas,
    project: PrecisionProject,
) -> list[TurnPath]:
    """Gera voltas em U na bordadura (modo offset_turn)."""
    parallel = [
        ParallelPass(
            fs_id=item.fs_id,
            operation_id=item.operation_id,
            pass_no=item.pass_no,
            spacing_m=item.spacing_m,
            width_m=item.width_m,
            half_width_m=item.width_m / 2.0,
            offset_m=item.offset_m,
            azimuth_deg=item.azimuth_deg,
            length_m=item.guidance_segment.length,
            is_headland=False,
            clipped_segment=item.clipped_segment,
            guidance_segment=item.guidance_segment,
        )
        for item in planting_passes
    ]
    turn_radius = None
    if project.planting_kinematics is not None:
        turn_radius = project.planting_kinematics.minimum_turn_radius_m
    config = TurnConfiguration(
        finish_mode=TurnFinishMode.INSIDE_HEADLAND,
        turn_type=TurnType.U,
        generate_turns=True,
        min_turn_radius_m=turn_radius,
    )
    try:
        result: TurnPathResult = generate_turn_paths(parallel, config, areas)
    except Exception:
        return []
    return list(result.turns)


def run_and_export(project: PrecisionProject, output_dir) -> ExportPackageResult:
    """Pipeline + exportacao; levanta ExportBlockedError se validacao falhar."""
    result = run_precision_lines(project)
    if not result.validation.ok:
        raise ExportBlockedError(
            "Validacao falhou: " + "; ".join(item.message for item in result.validation.errors)
        )
    from pathlib import Path

    return export_precision_lines_package(
        Path(output_dir),
        passes=result.planting_passes,
        rows=result.planting_rows,
        tramline_zones=result.tramline_zones,
        shutoff_segments=result.shutoff_segments,
        validation_report=result.validation,
        avoided_paths=result.avoided_paths,
        obstacle_envelopes=result.obstacle_envelopes,
        boundary=result.boundary,
        planting_avoidance_results=result.planting_avoidance_results,
        forbidden_regions=result.forbidden_regions,
        tire_tracks=result.tire_tracks,
    )
