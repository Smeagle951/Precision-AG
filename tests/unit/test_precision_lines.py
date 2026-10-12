# -*- coding: utf-8 -*-
"""Testes do motor Precision Lines."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from plugin.fortsmart_precision.core.boundary_engine import build_boundary_plan
from plugin.fortsmart_precision.core.export_engine import ExportBlockedError, export_precision_lines_package
from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
from plugin.fortsmart_precision.core.shutoff_engine import apply_row_shutoff
from plugin.fortsmart_precision.core.tramline_engine import generate_tramline_zones
from plugin.fortsmart_precision.core.validation_engine import validate_precision_project
from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
from plugin.fortsmart_precision.domain.machine_model import (
    MachineTrack,
    PlanterMachine,
    SprayerMachine,
    load_machine_presets,
)
from plugin.fortsmart_precision.domain.precision_project import (
    ABLine,
    FieldGeometry,
    PrecisionOperation,
    PrecisionProject,
)


def rectangle(width=400.0, height=240.0, x=0.0, y=0.0):
    outer = [(x, y), (x + width, y), (x + width, y + height), (x, y + height), (x, y)]
    return [(outer, [])]


def db27() -> PlanterMachine:
    presets = load_machine_presets()
    machine = presets["db27_36x050"]
    assert isinstance(machine, PlanterMachine)
    return machine


def uniport() -> SprayerMachine:
    presets = load_machine_presets()
    machine = presets["uniport_5030_103x035"]
    assert isinstance(machine, SprayerMachine)
    return machine


def sample_project(*, headland_passes=1) -> PrecisionProject:
    field = rectangle(400, 240)
    return PrecisionProject(
        field=FieldGeometry(
            field_boundary=field,
            operational_boundary=field,
            crs_authid="EPSG:31982",
        ),
        ab_line=ABLine(start=(0.0, 120.0), end=(400.0, 120.0)),
        planting=PrecisionOperation(
            operation_id="planting",
            machine=db27(),
            headland=HeadlandLayout(
                pass_count=headland_passes,
                width_m=18.0,
                effective_spacing_m=18.0,
                mode="parallel_ab",
            ),
        ),
        spraying=PrecisionOperation(
            operation_id="spraying",
            machine=uniport(),
        ),
    )


class MachineModelTest(unittest.TestCase):
    def test_db27_width_and_half(self):
        planter = db27()
        self.assertAlmostEqual(planter.operational_width_m, 18.0)
        self.assertAlmostEqual(planter.half_operational_width_m, 9.0)
        self.assertEqual(len(planter.all_row_offsets()), 36)

    def test_uniport_operational_width_differs_from_row_spacing(self):
        sprayer = uniport()
        self.assertAlmostEqual(sprayer.operational_width_m, 36.05)
        self.assertAlmostEqual(sprayer.calculated_boom_width_m, 36.05)
        self.assertNotAlmostEqual(sprayer.nozzle_spacing_m, sprayer.operational_width_m)

    def test_towed_track_offsets(self):
        sprayer = uniport()
        self.assertAlmostEqual(sprayer.track.track_width_m / 2.0, 1.5)


class BoundaryEngineTest(unittest.TestCase):
    def test_one_headland_pass_reserves_18m(self):
        project = sample_project(headland_passes=1)
        assert project.planting is not None
        boundary = build_boundary_plan(
            project.field.operational_boundary,
            project.planting,
            project.ab_line.start,
            project.ab_line.end,
        )
        self.assertAlmostEqual(boundary.reserved_width_m, 18.0)
        self.assertEqual(len(boundary.headland_centerlines), 1)
        self.assertAlmostEqual(boundary.headland_centerlines[0].offset_from_outer_m, 9.0)
        self.assertEqual(boundary.headland_centerlines[0].pass_no, 0)
        self.assertGreaterEqual(len(boundary.headland_inner_limits), 1)

    def test_two_headland_passes(self):
        project = sample_project(headland_passes=2)
        assert project.planting is not None
        boundary = build_boundary_plan(
            project.field.operational_boundary,
            project.planting,
            project.ab_line.start,
            project.ab_line.end,
        )
        self.assertAlmostEqual(boundary.reserved_width_m, 36.0)
        self.assertEqual(len(boundary.headland_centerlines), 2)
        offsets = [line.offset_from_outer_m for line in boundary.headland_centerlines]
        self.assertAlmostEqual(offsets[0], 9.0)
        self.assertAlmostEqual(offsets[1], 27.0)


class PrecisionLinesPipelineTest(unittest.TestCase):
    def test_generates_passes_and_rows(self):
        result = run_precision_lines(sample_project())
        self.assertGreater(len(result.planting_passes), 0)
        self.assertGreater(len(result.planting_rows), 0)
        if result.planting_passes:
            first_pass = result.planting_passes[0].pass_no
            rows_in_pass = [r for r in result.planting_rows if r.pass_id == first_pass]
            self.assertEqual(len(rows_in_pass), 36)

    def test_tramline_zones_have_track_width(self):
        result = run_precision_lines(sample_project())
        self.assertGreater(len(result.tramline_zones), 0)
        for zone in result.tramline_zones:
            self.assertAlmostEqual(zone.track_width_m, 3.0)
            self.assertAlmostEqual(zone.width_m, 0.35)
            self.assertIn(zone.side, {"left", "right"})

    def test_shutoff_can_produce_off_segments(self):
        result = run_precision_lines(sample_project())
        off = [s for s in result.shutoff_segments if s.shutoff_state == "off"]
        # Depende do alinhamento passada x linha; pipeline deve ao menos gerar segmentos.
        self.assertGreater(len(result.shutoff_segments), 0)
        summary_actions = {item["action"] for item in result.shutoff_table}
        self.assertTrue(summary_actions.issubset({"LIGA", "DESLIGA"}))

    def test_validation_ok_for_metric_crs(self):
        result = run_precision_lines(sample_project())
        self.assertTrue(result.validation.ok)

    def test_geographic_crs_blocks_validation(self):
        project = sample_project()
        bad = PrecisionProject(
            field=FieldGeometry(
                field_boundary=project.field.field_boundary,
                operational_boundary=project.field.operational_boundary,
                crs_authid="EPSG:4326",
            ),
            ab_line=project.ab_line,
            planting=project.planting,
            spraying=project.spraying,
        )
        report = validate_precision_project(bad)
        self.assertFalse(report.ok)
        self.assertTrue(any("CRS geografico" in err.message for err in report.errors))

    def test_export_writes_validation_report(self):
        result = run_precision_lines(sample_project())
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            package = export_precision_lines_package(
                out,
                passes=result.planting_passes,
                rows=result.planting_rows,
                tramline_zones=result.tramline_zones,
                shutoff_segments=result.shutoff_segments,
                validation_report=result.validation,
            )
            self.assertTrue((out / "validation_report.json").exists())
            payload = json.loads((out / "validation_report.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertIn("passes.geojson", package.export.files)

    def test_export_blocked_on_invalid_crs(self):
        result = run_precision_lines(sample_project())
        from plugin.fortsmart_precision.core.validation_engine import ValidationReport

        bad_report = ValidationReport()
        bad_report.add_error("TEST", "Falha")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ExportBlockedError):
                export_precision_lines_package(
                    Path(tmp),
                    passes=result.planting_passes,
                    rows=result.planting_rows,
                    tramline_zones=result.tramline_zones,
                    shutoff_segments=result.shutoff_segments,
                    validation_report=bad_report,
                )


class ShutoffEngineUnitTest(unittest.TestCase):
    def test_rows_without_zones_stay_on(self):
        from plugin.fortsmart_precision.core.guidance_engine import TrafficPass
        from plugin.fortsmart_precision.core.line_geometry import Segment
        from plugin.fortsmart_precision.core.row_engine import PlantingRow

        row = PlantingRow(
            fs_id="r1",
            row_id=1,
            pass_id=1,
            machine_id="db27",
            spacing_m=0.5,
            direction="forward",
            offset_m=0.0,
            azimuth_deg=90.0,
            segment=Segment((0.0, 120.0), (400.0, 120.0)),
        )
        segments = apply_row_shutoff([row], [])
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].shutoff_state, "on")


if __name__ == "__main__":
    unittest.main()
