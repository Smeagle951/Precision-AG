# -*- coding: utf-8 -*-
"""Fluxo profissional: cruzamento plantio × pulverizacao / shutoff."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from ..core.guidance_engine import TrafficPass
from ..core.line_geometry import MultiPolygon, Segment, build_processing_boundary, simplify_multipolygon_for_pip
from ..core.planting_kinematics_engine import generate_rows_from_tractor_paths, kinematics_from_planter
from ..core.row_engine import PlantingRow
from ..core.shutoff_engine import RowShutoffSegment, apply_row_shutoff, shutoff_summary
from ..core.sprayer_traffic_engine import calculate_planting_shutoff
from ..core.tire_track_engine import generate_tire_tracks, generate_tire_tracks_from_traffic
from ..core.tramline_engine import generate_tramline_zones
from ..domain.machine_model import PlanterMachine, SprayerMachine
from ..domain.planting_kinematics import PlantingKinematics


@dataclass(frozen=True)
class CrossWorkflowInputs:
    planting_rows: list[PlantingRow]
    spraying_passes: list[TrafficPass]
    tire_tracks: list
    source_plant: str
    source_spray: str


@dataclass(frozen=True)
class CrossShutoffResult:
    """Resultado do cruzamento shutoff (etapas separadas no workspace)."""

    planting_rows: list[PlantingRow]
    shutoff_segments: list[RowShutoffSegment]
    shutoff_table: list[dict[str, object]]
    tire_tracks: list
    tramline_zones: list
    plant_source: str
    tire_shutoff_segments: list[RowShutoffSegment]
    spraying_passes: list[TrafficPass]
    spray_source: str


def passes_to_planting_rows(
    passes: list[TrafficPass],
    planter: PlanterMachine,
) -> list[PlantingRow]:
    """Converte passadas de plantio (mapa) em linhas para shutoff (fallback 1 linha/passada)."""
    rows: list[PlantingRow] = []
    for traffic in passes:
        pts = traffic.line_points()
        if len(pts) < 2:
            continue
        rows.append(
            PlantingRow(
                fs_id=str(uuid4()),
                row_id=1,
                pass_id=traffic.pass_no,
                machine_id=planter.machine_id,
                spacing_m=planter.row_spacing_m if planter.row_spacing_m > 0 else 0.5,
                direction=traffic.direction,
                offset_m=traffic.offset_m,
                azimuth_deg=traffic.azimuth_deg,
                segment=Segment(pts[0], pts[-1]),
                path_points=pts if len(pts) > 2 else (),
            )
        )
    return rows


def _rows_are_virtual_enough(rows: list[PlantingRow], planter: PlanterMachine) -> bool:
    """True quando ja existem linhas de semente (N offsets), nao so eixo do trator."""
    if not rows:
        return False
    if planter.row_count <= 1:
        return True
    max_row_id = max(item.row_id for item in rows)
    if max_row_id <= 1 and len(rows) < planter.row_count:
        return False
    return len(rows) >= max(2, planter.row_count // 2) and max_row_id > 1


def ensure_virtual_planting_rows(
    passes: list[TrafficPass],
    planter: PlanterMachine,
    kinematics: PlantingKinematics | None = None,
    *,
    work_area: MultiPolygon | None = None,
) -> list[PlantingRow]:
    """
    Deriva N linhas de semente por passada do trator (pos-desvio).

    Essencial para shutoff profissional: OFF sobre rastro de pneu, ON no miolo
    entre eixos. Sem isso o cruzamento usa 1 linha/passada e o desligamento falha.
    """
    if not passes:
        return []
    kin = kinematics or kinematics_from_planter(planter)
    area: MultiPolygon = list(work_area or [])
    if area:
        area = simplify_multipolygon_for_pip(area, max_vertices=200, min_edge_m=2.5)
    return generate_rows_from_tractor_paths(passes, planter, kin, work_area=area)


def resolve_planting_rows_for_cross(
    *,
    session_rows: list[PlantingRow] | None,
    session_passes: list[TrafficPass] | None,
    imported_rows: list[PlantingRow] | None,
    planter: PlanterMachine,
    prefer_imported: bool = False,
    kinematics: PlantingKinematics | None = None,
    work_area: MultiPolygon | None = None,
) -> tuple[list[PlantingRow], str]:
    """
    Resolve linhas de plantio para cruzamento.

    prefer_imported=True: usa a camada selecionada pelo usuario (nao a sessao).
    Quando a sessao so tem passadas (etapa 2), gera linhas virtuais completas.
    """
    if prefer_imported and imported_rows:
        return list(imported_rows), "camada de plantio"
    if session_rows and _rows_are_virtual_enough(session_rows, planter):
        return list(session_rows), "sessao (linhas virtuais)"
    if session_passes:
        virtual = ensure_virtual_planting_rows(
            session_passes,
            planter,
            kinematics,
            work_area=work_area,
        )
        if virtual:
            return virtual, "sessao (linhas virtuais geradas)"
        return passes_to_planting_rows(session_passes, planter), "sessao (passadas plantio)"
    if imported_rows:
        return list(imported_rows), "camada de plantio"
    if session_rows:
        return list(session_rows), "sessao (linhas virtuais)"
    return [], "nenhuma"


def resolve_cross_shutoff_areas(
    *,
    off_areas: MultiPolygon | None,
    boundary,
    shutoff_on_headland_inner: bool,
) -> tuple[MultiPolygon | None, MultiPolygon | None]:
    """
    off_areas: desliga dentro (anel de bordadura, obstaculo).
    on_areas: desliga fora (miolo — semente so no inner_work_area).
    """
    on_areas = None
    if shutoff_on_headland_inner and boundary is not None:
        inner = getattr(getattr(boundary, "areas", None), "inner_work_area", None)
        if inner:
            on_areas = list(inner)
    return off_areas, on_areas


def ensure_tire_tracks(spraying_passes: list[TrafficPass], sprayer: SprayerMachine) -> list:
    """Gera rastros de pneu a partir das passadas de pulverizacao (cruzamento)."""
    if not spraying_passes:
        return []
    if sprayer.traffic is not None:
        return generate_tire_tracks_from_traffic(spraying_passes, sprayer.traffic)
    track = sprayer.effective_track
    return generate_tire_tracks(
        spraying_passes,
        track_width_m=track.track_width_m,
        tire_width_m=track.tire_width_m,
    )


def enrich_shutoff_table_with_traffic(
    shutoff_table: list[dict[str, object]],
    planter: PlanterMachine,
    sprayer: SprayerMachine,
) -> None:
    """Marca linhas estaticamente sobre zona de pneu (offset lateral × trafego)."""
    if sprayer.traffic is None:
        return
    classifications = calculate_planting_shutoff(planter, sprayer.traffic)
    by_row = {item.row_id: item for item in classifications}
    for item in shutoff_table:
        row_id = item.get("row_id")
        if row_id not in by_row:
            continue
        cls = by_row[int(row_id)]
        item["offset_m"] = round(cls.offset_m, 3)
        item["zone_side"] = cls.zone_side or ""
        if cls.action == "DESLIGA" and item.get("action") == "LIGA":
            item["action"] = "DESLIGA"
            item["detail"] = f"zona pneu {cls.zone_side}"


def run_cross_shutoff(
    *,
    planting_rows: list[PlantingRow],
    spraying_passes: list[TrafficPass],
    planter: PlanterMachine,
    sprayer: SprayerMachine,
    plant_source: str,
    spray_source: str = "camada de pulverizacao",
    shutoff_on_tramlines: bool = True,
    shutoff_on_headland_inner: bool = False,
    off_areas: MultiPolygon | None = None,
    boundary=None,
    existing_tire_tracks: list | None = None,
    clip_area: MultiPolygon | None = None,
) -> CrossShutoffResult:
    """
    Orquestra cruzamento shutoff apos etapas separadas (plantio + pulverizacao).

    - Rastros de pneu do pulverizador → OFF espacial nas linhas virtuais.
    - Miolo entre eixos → ON (classificacao estatica + trechos fora do rastro).
    - Bordadura/obstaculo via off_areas / on_areas (inner_work_area).
    """
    tire_tracks = list(existing_tire_tracks or [])
    if shutoff_on_tramlines and not tire_tracks:
        tire_tracks = ensure_tire_tracks(spraying_passes, sprayer)

    tramline_zones = generate_tramline_zones(
        spraying_passes,
        sprayer,
        clip_area=clip_area,
    )
    off_main, on_main = resolve_cross_shutoff_areas(
        off_areas=off_areas,
        boundary=boundary,
        shutoff_on_headland_inner=shutoff_on_headland_inner,
    )

    shutoff_segments = apply_row_shutoff(
        planting_rows,
        tramline_zones if shutoff_on_tramlines else [],
        off_areas=off_main,
        on_areas=on_main,
        shutoff_on_tramlines=shutoff_on_tramlines,
        tire_tracks=tire_tracks if shutoff_on_tramlines else None,
    )
    tire_shutoff_segments = []
    if shutoff_on_tramlines and tire_tracks:
        tire_shutoff_segments = [
            item
            for item in apply_row_shutoff(
                planting_rows,
                [],
                shutoff_on_tramlines=True,
                tire_tracks=tire_tracks,
            )
            if item.shutoff_state == "off"
        ]
    shutoff_table = shutoff_summary(shutoff_segments)
    enrich_shutoff_table_with_traffic(shutoff_table, planter, sprayer)

    return CrossShutoffResult(
        planting_rows=planting_rows,
        shutoff_segments=shutoff_segments,
        shutoff_table=shutoff_table,
        tire_tracks=tire_tracks,
        tramline_zones=tramline_zones,
        plant_source=plant_source,
        tire_shutoff_segments=tire_shutoff_segments,
        spraying_passes=spraying_passes,
        spray_source=spray_source if spraying_passes else "nenhuma",
    )


def resolve_spraying_passes_for_cross(
    *,
    session_passes: list[TrafficPass] | None,
    imported_passes: list[TrafficPass] | None,
    prefer_imported: bool = False,
) -> tuple[list[TrafficPass], str]:
    """
    Resolve passadas de pulverizacao para cruzamento.

    prefer_imported=True: usa a camada selecionada (nunca misturar com plantio).
    """
    if prefer_imported and imported_passes:
        return list(imported_passes), "camada de pulverizacao"
    if session_passes:
        return list(session_passes), "sessao (aplicacao)"
    if imported_passes:
        return list(imported_passes), "camada de pulverizacao"
    return [], "nenhuma"


def build_cross_work_area(
    operational_boundary: MultiPolygon | None,
    extension_m: float,
) -> MultiPolygon:
    """Limite operacional para clip das linhas virtuais no cruzamento."""
    if not operational_boundary:
        return []
    return build_processing_boundary(operational_boundary, extension_m)


def session_ready_for_cross(last_result) -> bool:
    if last_result is None:
        return False
    has_spray = bool(last_result.spraying_passes)
    has_plant = bool(last_result.planting_rows or last_result.planting_passes)
    return has_spray and has_plant
