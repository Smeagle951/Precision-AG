# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import replace

import pytest

from plugin.fortsmart_precision.core.export_operation_bundle import (
    assess_export_capabilities,
    build_export_operation_bundle,
)
from plugin.fortsmart_precision.core.operational_persistence import (
    OperationalPersistenceError,
    OperationalPersistenceStore,
)
from plugin.fortsmart_precision.core.operational_generation import build_operational_generation
from plugin.fortsmart_precision.core.cross_workflow import run_cross_shutoff
from plugin.fortsmart_precision.core.guidance_engine import TrafficPass
from plugin.fortsmart_precision.core.line_geometry import Segment
from plugin.fortsmart_precision.core.row_engine import PlantingRow
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, PlanterMachine, SprayerMachine
from plugin.fortsmart_precision.domain.sprayer_traffic_configuration import SprayerTrafficConfiguration
from plugin.fortsmart_precision.domain.operational_contract import (
    CrossSourceMode,
    ExporterCapabilities,
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


def _generation(generation_id="G1", excluded=2.0):
    manifest = OperationManifest(
        generation_id=generation_id,
        field_id="talhao_12",
        field_name="Talhao 12",
        operation_type="PLANTING_SHUTOFF",
        operation_id="PLANTING_SHUTOFF:talhao_12",
        created_at="2026-10-08T12:00:00+00:00",
        algorithm_version="test/1",
        status=GenerationStatus.DRAFT,
        source_mode=CrossSourceMode.EXISTING_PASSES,
        source_crs="EPSG:31981",
        working_crs="EPSG:31981",
        sprayer_name="Pulverizador teste",
        planting_layer="plantio",
        spray_layer="aplicacao",
        selected_spray_count=1,
        analyzed_planting_rows=1,
        affected_rows_count=1 if excluded else 0,
        intersection_count=1 if excluded else 0,
        excluded_length_m=excluded,
        sprayer_snapshot={"tire_width_m": 0.4},
        cross_snapshot={"selected_spray_feature_ids": ["spr-83"]},
    )
    row = PlantingRowRecord("row-224", "224", 1, 3, ((0.0, 0.0), (20.0, 0.0)), 20.0)
    spray = SprayPassRecord(
        "18", "spr-83", "layer-spray", "LineString",
        CrossSourceMode.EXISTING_PASSES, ((10.0, -10.0), (10.0, 10.0)),
    )
    track = TireTrackRecord(
        "track-left", generation_id, "18", "spr-83", "LEFT", -1.5, 3.0,
        0.4, 0.1, 0.6, ((10.0, -10.0), (10.0, 10.0)),
    )
    segments = ()
    relations = (OperationRelation(
        generation_id, "SPRAY_PASS_TO_TIRE_TRACK", "SPRAY_PASS", "18",
        "TIRE_TRACK", "track-left",
    ),)
    if excluded:
        segment = OperationalSegment(
            "sh-1", "talhao_12", manifest.operation_id, manifest.operation_type,
            "PLANTING_ROW", "224", "row-224", CrossSourceMode.EXISTING_PASSES,
            ((9.0, 0.0), (11.0, 0.0)), 9.0, 11.0, 2.0,
            OperationalState.WORK_OFF, OperationalReason.SPRAYER_TIRE_TRACK,
            manifest.created_at, generation_id, "test/1", "18", "spr-83",
            "track-left", "LEFT", 0.4, 0.1, 0.6,
        )
        segments = (segment,)
        relations += (
            OperationRelation(generation_id, "PLANTING_ROW_TO_SHUTOFF", "PLANTING_ROW", "row-224", "SHUTOFF", "sh-1"),
            OperationRelation(generation_id, "TIRE_TRACK_TO_SHUTOFF", "TIRE_TRACK", "track-left", "SHUTOFF", "sh-1"),
        )
    return OperationalGeneration(manifest, (row,), (spray,), (track,), segments, relations)


def test_contract_rejects_broken_source_row():
    generation = _generation()
    broken = replace(
        generation,
        segments=(replace(generation.segments[0], source_row_id="missing"),),
    )
    with pytest.raises(ValueError, match="inexistente"):
        broken.validate()


def test_persist_reopen_and_supersede(tmp_path):
    store = OperationalPersistenceStore(tmp_path / "field.gpkg")
    first = store.save_generation(_generation("G1"))
    assert first.manifest.status == GenerationStatus.ACTIVE
    reopened = store.load_active("talhao_12")
    assert reopened == first

    second = store.save_generation(_generation("G2"))
    assert store.load_active("talhao_12") == second
    assert store.load_generation("G1").manifest.status == GenerationStatus.SUPERSEDED


def test_transaction_failure_keeps_previous_active(tmp_path):
    class FailingStore(OperationalPersistenceStore):
        def _validate_written_counts(self, connection, generation):
            raise ValueError("falha simulada apos inserts")

    path = tmp_path / "field.gpkg"
    store = OperationalPersistenceStore(path)
    first = store.save_generation(_generation("G1"))
    with pytest.raises(OperationalPersistenceError, match="falha simulada"):
        FailingStore(path).save_generation(_generation("G2"))
    assert store.load_active("talhao_12") == first
    assert store.load_generation("G2") is None


def test_zero_crossing_is_valid_and_persisted(tmp_path):
    generation = _generation("ZERO", excluded=0.0)
    generation.validate()
    saved = OperationalPersistenceStore(tmp_path / "field.gpkg").save_generation(generation)
    assert saved.manifest.status == GenerationStatus.ACTIVE
    assert saved.manifest.intersection_count == 0
    assert saved.segments == ()


def test_bundle_requires_active_and_reports_unsupported_semantics(tmp_path):
    store = OperationalPersistenceStore(tmp_path / "field.gpkg")
    active = store.save_generation(_generation())
    bundle = build_export_operation_bundle(active)
    report = assess_export_capabilities(
        bundle,
        ExporterCapabilities(name="SEM_SHUTOFF", supports_guidance=True),
    )
    assert report.skipped_counts["SHUTOFF"] == 1
    assert any("sem suporte" in item for item in report.warnings)


def test_generations_are_isolated_by_field(tmp_path):
    store = OperationalPersistenceStore(tmp_path / "multi.gpkg")
    first = store.save_generation(_generation("G1"))
    other = _generation("G2")
    other = replace(
        other,
        manifest=replace(other.manifest, field_id="talhao_13", field_name="Talhao 13"),
        segments=tuple(replace(item, field_id="talhao_13") for item in other.segments),
    )
    store.save_generation(other)
    assert store.load_active("talhao_12").manifest.generation_id == first.manifest.generation_id
    assert store.load_active("talhao_13").manifest.generation_id == "G2"


def test_cross_generation_records_causal_tire_and_physical_margin():
    planter = PlanterMachine("p", "Plantadeira", 1, 0.5, MachineTrack(1.8, 0.3))
    traffic = SprayerTrafficConfiguration(
        boom_width_m=20.0,
        tire_width_m=0.4,
        inner_clearance_m=2.6,
        outer_width_m=3.4,
        safety_margin_m=0.1,
    )
    sprayer = SprayerMachine(
        "s", "Pulverizador", 40, 0.5, 20.0, traffic.to_machine_track(), traffic=traffic
    )
    row = PlantingRow(
        "row-source-7", 1, 7, "p", 0.5, "forward", 0.0, 90.0,
        Segment((0.0, 0.0), (20.0, 0.0)),
    )
    spray = TrafficPass(
        18, "spr-source-83", "spraying", 20.0, 20.0, 0.0, 0.0, "forward",
        Segment((10.0, -10.0), (10.0, 10.0)),
        Segment((10.0, -10.0), (10.0, 10.0)),
    )
    cross = run_cross_shutoff(
        planting_rows=[row], spraying_passes=[spray], planter=planter, sprayer=sprayer,
        plant_source="camada de plantio", spray_source="passadas existentes",
    )
    generation = build_operational_generation(
        cross=cross,
        field_id="talhao_12",
        field_name="Talhao 12",
        source_crs="EPSG:31981",
        working_crs="EPSG:31981",
        source_mode=CrossSourceMode.EXISTING_PASSES,
        sprayer=sprayer,
        planting_layer="plantio",
        spray_layer="spray",
    )
    assert generation.segments
    assert all(item.source_row_id == "row-source-7" for item in generation.segments)
    assert all(item.tire_track_id for item in generation.segments)
    assert {item.tire_side for item in generation.segments} <= {"LEFT", "RIGHT"}
    assert all(item.physical_tire_width_m == pytest.approx(0.4) for item in generation.segments)
    assert all(item.safety_margin_m == pytest.approx(0.1) for item in generation.segments)
    assert all(item.effective_exclusion_width_m == pytest.approx(0.6) for item in generation.segments)
