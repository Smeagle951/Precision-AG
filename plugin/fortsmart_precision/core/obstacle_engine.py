# -*- coding: utf-8 -*-
"""Fachada de desvio de obstaculos: roteia aplicacao vs plantio."""

from __future__ import annotations

from ..domain.avoidance_configuration import AvoidanceConfiguration
from ..domain.machine_model import MachineProfile, PlanterMachine, SprayerMachine
from ..domain.obstacle_model import Obstacle
from ..domain.planting_avoidance_configuration import PlantingAvoidanceConfiguration
from ..domain.planting_avoidance_result import PlantingAvoidanceResult
from ..domain.planting_kinematics import PlantingKinematics
from .application_obstacle_engine import (
    AvoidanceAction,
    AvoidedPath,
    apply_application_obstacle_avoidance,
    apply_obstacle_avoidance_to_passes,
    avoidance_summary,
)
from .guidance_engine import TrafficPass
from .line_geometry import MultiPolygon
from .row_engine import PlantingRow

# Reexportes para compatibilidade com importadores existentes
__all__ = [
    "AvoidanceAction",
    "AvoidedPath",
    "ObstacleEngineError",
    "apply_obstacle_avoidance_to_passes",
    "apply_obstacle_avoidance_to_rows",
    "apply_application_obstacle_avoidance",
    "apply_planting_obstacle_avoidance",
    "avoidance_summary",
]


class ObstacleEngineError(ValueError):
    """Erro no motor de obstaculos."""


def apply_obstacle_avoidance_to_rows(
    rows: list[PlantingRow],
    obstacles: list[Obstacle],
    machine: MachineProfile,
    config: AvoidanceConfiguration,
    *,
    allowed_area: MultiPolygon | None = None,
) -> tuple[list[PlantingRow], list[AvoidedPath]]:
    """
    Legado: desvio linha a linha (preferir planting_obstacle_engine + cinematica).

    Mantido apenas para regressao / compatibilidade; o pipeline v3 deriva linhas
    a partir da trajetoria do trator.
    """
    from .application_obstacle_engine import _avoid_segment
    from .obstacle_buffer_engine import build_all_envelopes
    from .obstacle_grouping_engine import merge_adjacent_envelopes

    if not config.enabled() or not obstacles:
        return rows, []
    envelopes = merge_adjacent_envelopes(
        build_all_envelopes(obstacles, machine),
        config.merge_adjacent_envelopes_m,
    )
    modified_rows: list[PlantingRow] = []
    avoided: list[AvoidedPath] = []
    for row in rows:
        result = _avoid_segment(
            row.segment,
            obstacles,
            envelopes,
            machine,
            config,
            pass_id=row.pass_id,
            row_id=row.row_id,
            source_id=row.fs_id,
            operation_id="planting",
            allowed_area=allowed_area,
        )
        if result is None:
            modified_rows.append(row)
            continue
        avoided.append(result)
        new_seg = result.guidance_segment
        modified_rows.append(
            PlantingRow(
                fs_id=row.fs_id,
                row_id=row.row_id,
                pass_id=row.pass_id,
                machine_id=row.machine_id,
                spacing_m=row.spacing_m,
                direction=row.direction,
                offset_m=row.offset_m,
                azimuth_deg=row.azimuth_deg,
                segment=new_seg,
                path_points=result.modified_points,
            )
        )
    return modified_rows, avoided


def apply_planting_obstacle_avoidance(
    passes: list[TrafficPass],
    obstacles: list[Obstacle],
    kinematics: PlantingKinematics,
    config: PlantingAvoidanceConfiguration,
    planter: PlanterMachine,
    *,
    allowed_area: MultiPolygon | None = None,
) -> tuple[list[TrafficPass], list[PlantingAvoidanceResult], list[AvoidedPath]]:
    """Desvio de plantio com cinematica trator+implemento."""
    from .planting_obstacle_engine import apply_planting_avoidance_to_passes

    return apply_planting_avoidance_to_passes(
        passes,
        obstacles,
        kinematics,
        config,
        planter,
        allowed_area=allowed_area,
    )


def route_obstacle_avoidance(
    *,
    spraying_passes: list[TrafficPass] | None,
    planting_passes: list[TrafficPass] | None,
    obstacles: list[Obstacle],
    sprayer: SprayerMachine | None,
    planter: PlanterMachine | None,
    spray_config: AvoidanceConfiguration,
    planting_config: PlantingAvoidanceConfiguration,
    kinematics: PlantingKinematics | None,
    allowed_area: MultiPolygon | None = None,
) -> tuple[
    list[TrafficPass],
    list[TrafficPass],
    list[AvoidedPath],
    list[PlantingAvoidanceResult],
]:
    """Roteia desvio de pulverizacao e plantio pelos motores especializados."""
    spray_out = list(spraying_passes or [])
    plant_out = list(planting_passes or [])
    avoided: list[AvoidedPath] = []
    planting_results: list[PlantingAvoidanceResult] = []

    if spray_out and sprayer is not None and obstacles and spray_config.enabled():
        spray_out, spray_avoided = apply_application_obstacle_avoidance(
            spray_out,
            obstacles,
            sprayer,
            spray_config,
            allowed_area=allowed_area,
        )
        avoided.extend(spray_avoided)

    if (
        plant_out
        and planter is not None
        and kinematics is not None
        and obstacles
        and planting_config.is_enabled()
    ):
        plant_out, planting_results, plant_avoided = apply_planting_obstacle_avoidance(
            plant_out,
            obstacles,
            kinematics,
            planting_config,
            planter,
            allowed_area=allowed_area,
        )
        avoided.extend(plant_avoided)

    return spray_out, plant_out, avoided, planting_results
