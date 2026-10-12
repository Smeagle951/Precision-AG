# -*- coding: utf-8 -*-
"""Contrato canonico de resultados operacionais persistidos e exportaveis."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

Point = tuple[float, float]


class OperationalState(str, Enum):
    WORK_ON = "WORK_ON"
    WORK_OFF = "WORK_OFF"
    GUIDANCE_ONLY = "GUIDANCE_ONLY"
    TRANSITION = "TRANSITION"
    MANEUVER = "MANEUVER"


class OperationalReason(str, Enum):
    SPRAYER_TIRE_TRACK = "SPRAYER_TIRE_TRACK"
    HEADLAND = "HEADLAND"
    OBSTACLE = "OBSTACLE"
    SAFETY_MARGIN = "SAFETY_MARGIN"
    MANEUVER = "MANEUVER"
    USER_OVERRIDE = "USER_OVERRIDE"
    NONE = "NONE"


class GenerationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    STALE = "STALE"
    FAILED = "FAILED"
    DRAFT = "DRAFT"


class CrossSourceMode(str, Enum):
    GENERATED_BASELINE = "GENERATED_BASELINE"
    EXISTING_PASSES = "EXISTING_PASSES"


class OverrideStatus(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    OVERRIDDEN = "OVERRIDDEN"


@dataclass(frozen=True)
class OperationalSegment:
    segment_id: str
    field_id: str
    operation_id: str
    operation_type: str
    source_layer_role: str
    source_feature_id: str
    source_row_id: str
    source_mode: CrossSourceMode
    geometry: tuple[Point, ...]
    station_start_m: float
    station_end_m: float
    length_m: float
    state: OperationalState
    reason: OperationalReason
    created_at: str
    generation_id: str
    algorithm_version: str
    spray_pass_id: str = ""
    spray_source_feature_id: str = ""
    tire_track_id: str = ""
    tire_side: str = ""
    physical_tire_width_m: float = 0.0
    safety_margin_m: float = 0.0
    effective_exclusion_width_m: float = 0.0
    override_status: OverrideStatus = OverrideStatus.VALID
    user_override: bool = False

    def validate(self) -> None:
        if not self.segment_id or not self.generation_id or not self.field_id:
            raise ValueError("Segmento operacional sem identidade persistente.")
        if not self.source_row_id:
            raise ValueError("Segmento operacional sem source_row_id.")
        if len(self.geometry) < 2:
            raise ValueError("Segmento operacional sem geometria linear valida.")
        if self.station_start_m < 0 or self.station_end_m <= self.station_start_m:
            raise ValueError("Intervalo de estacao invalido no segmento operacional.")
        if self.length_m <= 0:
            raise ValueError("Comprimento do segmento operacional deve ser positivo.")
        if self.state == OperationalState.WORK_OFF and self.reason == OperationalReason.NONE:
            raise ValueError("WORK_OFF exige motivo operacional explicito.")
        if self.reason in {
            OperationalReason.SPRAYER_TIRE_TRACK,
            OperationalReason.SAFETY_MARGIN,
        } and not self.tire_track_id:
            raise ValueError("Exclusao por pneu sem tire_track_id causal.")


@dataclass(frozen=True)
class PlantingRowRecord:
    source_row_id: str
    source_feature_id: str
    pass_id: int
    row_id: int
    geometry: tuple[Point, ...]
    length_m: float


@dataclass(frozen=True)
class SprayPassRecord:
    spray_pass_id: str
    source_feature_id: str
    source_layer_id: str
    source_geometry_type: str
    source_mode: CrossSourceMode
    geometry: tuple[Point, ...]


@dataclass(frozen=True)
class TireTrackRecord:
    track_id: str
    generation_id: str
    spray_pass_id: str
    source_feature_id: str
    side: str
    center_offset_m: float
    track_width_m: float
    physical_tire_width_m: float
    safety_margin_m: float
    effective_exclusion_width_m: float
    geometry: tuple[Point, ...]

    def validate(self) -> None:
        if not self.track_id or not self.generation_id or not self.spray_pass_id:
            raise ValueError("Rastro de pneu sem identidade persistente.")
        if self.side not in {"LEFT", "RIGHT"}:
            raise ValueError("Lado do rastro de pneu invalido.")
        if self.physical_tire_width_m <= 0 or self.effective_exclusion_width_m <= 0:
            raise ValueError("Largura de pneu invalida.")
        if self.safety_margin_m < 0:
            raise ValueError("Margem de pneu invalida.")
        if len(self.geometry) < 2:
            raise ValueError("Rastro de pneu sem geometria linear valida.")


@dataclass(frozen=True)
class OperationRelation:
    generation_id: str
    relation_type: str
    parent_role: str
    parent_feature_id: str
    child_role: str
    child_feature_id: str


@dataclass(frozen=True)
class OperationManifest:
    generation_id: str
    field_id: str
    field_name: str
    operation_type: str
    operation_id: str
    created_at: str
    algorithm_version: str
    status: GenerationStatus
    source_mode: CrossSourceMode
    source_crs: str
    working_crs: str
    sprayer_name: str
    planting_layer: str
    spray_layer: str
    selected_spray_count: int
    analyzed_planting_rows: int
    affected_rows_count: int
    intersection_count: int
    excluded_length_m: float
    sprayer_snapshot: dict[str, Any] = field(default_factory=dict)
    cross_snapshot: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.generation_id or not self.field_id or not self.operation_type:
            raise ValueError("Manifesto operacional incompleto.")
        if not self.working_crs:
            raise ValueError("Manifesto operacional sem CRS de trabalho.")
        for value in (
            self.selected_spray_count,
            self.analyzed_planting_rows,
            self.affected_rows_count,
            self.intersection_count,
        ):
            if value < 0:
                raise ValueError("Contagem negativa no manifesto operacional.")
        if self.excluded_length_m < 0:
            raise ValueError("Comprimento excluido negativo.")


@dataclass(frozen=True)
class OperationalGeneration:
    manifest: OperationManifest
    planting_rows: tuple[PlantingRowRecord, ...]
    spray_passes: tuple[SprayPassRecord, ...]
    tire_tracks: tuple[TireTrackRecord, ...]
    segments: tuple[OperationalSegment, ...]
    relations: tuple[OperationRelation, ...]

    def validate(self) -> None:
        self.manifest.validate()
        generation_id = self.manifest.generation_id
        row_ids = {item.source_row_id for item in self.planting_rows}
        if len(row_ids) != len(self.planting_rows):
            raise ValueError("source_row_id duplicado na geracao operacional.")
        track_ids = {item.track_id for item in self.tire_tracks}
        for track in self.tire_tracks:
            track.validate()
            if track.generation_id != generation_id:
                raise ValueError("Rastro pertence a outra geracao.")
        for segment in self.segments:
            segment.validate()
            if segment.generation_id != generation_id:
                raise ValueError("Segmento pertence a outra geracao.")
            if segment.source_row_id not in row_ids:
                raise ValueError("Segmento referencia linha de plantio inexistente.")
            if segment.tire_track_id and segment.tire_track_id not in track_ids:
                raise ValueError("Segmento referencia rastro de pneu inexistente.")


@dataclass(frozen=True)
class ExportOperationBundle:
    manifest: OperationManifest
    planting_rows: tuple[PlantingRowRecord, ...]
    spray_passes: tuple[SprayPassRecord, ...]
    tire_tracks: tuple[TireTrackRecord, ...]
    shutoff_segments: tuple[OperationalSegment, ...]
    relations: tuple[OperationRelation, ...]
    source_crs: str
    working_crs: str
    target_crs: str = ""

    def validate(self, *, require_active: bool = True) -> None:
        generation = OperationalGeneration(
            self.manifest,
            self.planting_rows,
            self.spray_passes,
            self.tire_tracks,
            self.shutoff_segments,
            self.relations,
        )
        generation.validate()
        if require_active and self.manifest.status != GenerationStatus.ACTIVE:
            raise ValueError("Exportacao exige uma geracao operacional ACTIVE.")


@dataclass(frozen=True)
class ExporterCapabilities:
    name: str
    supports_guidance: bool = False
    supports_boundaries: bool = False
    supports_headlands: bool = False
    supports_work_states: bool = False
    supports_variable_sections: bool = False
    supports_tire_tracks: bool = False
    supports_obstacles: bool = False
    supports_turn_paths: bool = False
    auxiliary_layers: bool = False


@dataclass(frozen=True)
class ExportSemanticReport:
    exporter_name: str
    generation_id: str
    warnings: tuple[str, ...]
    native_counts: dict[str, int]
    auxiliary_counts: dict[str, int]
    skipped_counts: dict[str, int]
