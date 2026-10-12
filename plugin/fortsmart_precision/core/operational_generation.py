# -*- coding: utf-8 -*-
"""Converte o cruzamento geometrico no contrato operacional canonico."""

from __future__ import annotations

from datetime import datetime, timezone
from math import hypot
from uuid import uuid4

from ..domain.operational_contract import (
    CrossSourceMode,
    GenerationStatus,
    OperationalGeneration,
    OperationalReason,
    OperationalSegment,
    OperationalState,
    OperationManifest,
    OperationRelation,
    PlantingRowRecord,
    SprayPassRecord,
    TireTrackRecord,
)
from .line_geometry import polyline_length

ALGORITHM_VERSION = "spray-plant-cross/1.0"
OPERATION_TYPE = "PLANTING_SHUTOFF"


def new_generation_id(now: datetime | None = None) -> str:
    instant = now or datetime.now(timezone.utc)
    return f"SPRAY_CROSS_{instant.strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6].upper()}"


def _distance_point_to_segment(point, start, end) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length2 = dx * dx + dy * dy
    if length2 <= 1e-18:
        return hypot(point[0] - start[0], point[1] - start[1])
    ratio = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length2
    ratio = max(0.0, min(1.0, ratio))
    projected = (start[0] + ratio * dx, start[1] + ratio * dy)
    return hypot(point[0] - projected[0], point[1] - projected[1])


def _distance_point_to_polyline(point, points) -> float:
    return min(
        _distance_point_to_segment(point, start, end)
        for start, end in zip(points, points[1:])
    )


def _orientation(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segment_distance(a0, a1, b0, b1) -> float:
    o1 = _orientation(a0, a1, b0)
    o2 = _orientation(a0, a1, b1)
    o3 = _orientation(b0, b1, a0)
    o4 = _orientation(b0, b1, a1)
    boxes_overlap = not (
        max(a0[0], a1[0]) < min(b0[0], b1[0])
        or max(b0[0], b1[0]) < min(a0[0], a1[0])
        or max(a0[1], a1[1]) < min(b0[1], b1[1])
        or max(b0[1], b1[1]) < min(a0[1], a1[1])
    )
    if boxes_overlap and o1 * o2 <= 0.0 and o3 * o4 <= 0.0:
        return 0.0
    return min(
        _distance_point_to_segment(a0, b0, b1),
        _distance_point_to_segment(a1, b0, b1),
        _distance_point_to_segment(b0, a0, a1),
        _distance_point_to_segment(b1, a0, a1),
    )


def _polyline_distance(first, second) -> float:
    return min(
        _segment_distance(a0, a1, b0, b1)
        for a0, a1 in zip(first, first[1:])
        for b0, b1 in zip(second, second[1:])
    )


def _causal_track(segment, tracks):
    points = tuple(segment.line_points())
    candidates = []
    for track in tracks:
        if len(track.points) < 2:
            continue
        gap = _polyline_distance(points, track.points)
        candidates.append((gap, track))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def build_operational_generation(
    *,
    cross,
    field_id: str,
    field_name: str,
    source_crs: str,
    working_crs: str,
    source_mode: CrossSourceMode,
    sprayer,
    planting_layer: str,
    spray_layer: str,
    spray_source_layer_id: str = "",
    selected_spray_feature_ids: tuple[str, ...] = (),
    generation_id: str | None = None,
) -> OperationalGeneration:
    """Cria uma geracao DRAFT sem alterar linhas ou resultados de origem."""
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    generation_id = generation_id or new_generation_id()
    operation_id = f"{OPERATION_TYPE}:{field_id}"

    rows = tuple(
        PlantingRowRecord(
            source_row_id=row.fs_id,
            source_feature_id=row.fs_id,
            pass_id=row.pass_id,
            row_id=row.row_id,
            geometry=tuple(row.line_points()),
            length_m=polyline_length(list(row.line_points())),
        )
        for row in cross.planting_rows
    )
    spray_passes = tuple(
        SprayPassRecord(
            spray_pass_id=str(item.pass_no),
            source_feature_id=item.fs_id,
            source_layer_id=spray_source_layer_id,
            source_geometry_type="LineString",
            source_mode=source_mode,
            geometry=tuple(item.line_points()),
        )
        for item in cross.spraying_passes
    )
    source_by_pass = {int(item.spray_pass_id): item.source_feature_id for item in spray_passes}
    track_records = tuple(
        TireTrackRecord(
            track_id=track.track_id or f"TT_{track.pass_id}_{track.side.upper()}_{uuid4().hex[:8]}",
            generation_id=generation_id,
            spray_pass_id=str(track.pass_id),
            source_feature_id=track.source_feature_id or source_by_pass.get(track.pass_id, ""),
            side=track.side.upper(),
            center_offset_m=track.offset_m,
            track_width_m=track.track_width_m,
            physical_tire_width_m=track.physical_tire_width_m or track.tire_width_m,
            safety_margin_m=track.safety_margin_m,
            effective_exclusion_width_m=track.tire_width_m,
            geometry=tuple(track.points),
        )
        for track in cross.tire_tracks
    )
    record_by_object = {
        id(track): track_records[index] for index, track in enumerate(cross.tire_tracks)
    }

    segments = []
    relations = []
    for item in cross.tire_shutoff_segments:
        track = _causal_track(item, cross.tire_tracks)
        record = record_by_object.get(id(track)) if track is not None else None
        reason = OperationalReason.SPRAYER_TIRE_TRACK
        if record is not None and record.safety_margin_m > 0:
            gap = _polyline_distance(item.line_points(), track.points)
            if gap > record.physical_tire_width_m / 2.0:
                reason = OperationalReason.SAFETY_MARGIN
        segment_id = f"SH_{uuid4().hex.upper()}"
        points = tuple(item.line_points())
        segments.append(
            OperationalSegment(
                segment_id=segment_id,
                field_id=field_id,
                operation_id=operation_id,
                operation_type=OPERATION_TYPE,
                source_layer_role="PLANTING_ROW",
                source_feature_id=item.source_row_id,
                source_row_id=item.source_row_id,
                source_mode=source_mode,
                geometry=points,
                station_start_m=item.station_start_m,
                station_end_m=item.station_end_m,
                length_m=polyline_length(list(points)),
                state=OperationalState.WORK_OFF,
                reason=reason,
                created_at=created_at,
                generation_id=generation_id,
                algorithm_version=ALGORITHM_VERSION,
                spray_pass_id=record.spray_pass_id if record else "",
                spray_source_feature_id=record.source_feature_id if record else "",
                tire_track_id=record.track_id if record else "",
                tire_side=record.side if record else "",
                physical_tire_width_m=record.physical_tire_width_m if record else 0.0,
                safety_margin_m=record.safety_margin_m if record else 0.0,
                effective_exclusion_width_m=(record.effective_exclusion_width_m if record else 0.0),
            )
        )
        relations.append(OperationRelation(
            generation_id, "PLANTING_ROW_TO_SHUTOFF", "PLANTING_ROW",
            item.source_row_id, "SHUTOFF", segment_id,
        ))
        if record is not None:
            relations.append(OperationRelation(
                generation_id, "TIRE_TRACK_TO_SHUTOFF", "TIRE_TRACK",
                record.track_id, "SHUTOFF", segment_id,
            ))

    for track in track_records:
        relations.append(OperationRelation(
            generation_id, "SPRAY_PASS_TO_TIRE_TRACK", "SPRAY_PASS",
            track.spray_pass_id, "TIRE_TRACK", track.track_id,
        ))

    affected = {item.source_row_id for item in segments}
    snapshot = sprayer.to_dict()
    manifest = OperationManifest(
        generation_id=generation_id,
        field_id=field_id,
        field_name=field_name,
        operation_type=OPERATION_TYPE,
        operation_id=operation_id,
        created_at=created_at,
        algorithm_version=ALGORITHM_VERSION,
        status=GenerationStatus.DRAFT,
        source_mode=source_mode,
        source_crs=source_crs,
        working_crs=working_crs,
        sprayer_name=sprayer.name,
        planting_layer=planting_layer,
        spray_layer=spray_layer,
        selected_spray_count=len(spray_passes),
        analyzed_planting_rows=len(rows),
        affected_rows_count=len(affected),
        intersection_count=len(segments),
        excluded_length_m=sum(item.length_m for item in segments),
        sprayer_snapshot=snapshot,
        cross_snapshot={
            "source_mode": source_mode.value,
            "selected_spray_feature_ids": list(selected_spray_feature_ids),
            "selected_planting_source": planting_layer,
        },
    )
    generation = OperationalGeneration(
        manifest=manifest,
        planting_rows=rows,
        spray_passes=spray_passes,
        tire_tracks=track_records,
        segments=tuple(segments),
        relations=tuple(relations),
    )
    generation.validate()
    return generation
