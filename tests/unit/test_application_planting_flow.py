# -*- coding: utf-8 -*-
"""Testes do fluxo aplicacao -> plantio -> cruzamento (bordadura, extensao, shutoff)."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.boundary_engine import build_boundary_plan
from plugin.fortsmart_precision.core.parallel_pass_engine import ParallelPassParams, generate_parallel_passes
from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
from plugin.fortsmart_precision.core.shutoff_engine import apply_row_shutoff
from plugin.fortsmart_precision.core.tramline_engine import generate_tramline_zones
from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, PlanterMachine, SprayerMachine
from plugin.fortsmart_precision.domain.precision_project import (
    ABLine,
    FieldGeometry,
    PrecisionOperation,
    PrecisionProject,
)
from plugin.fortsmart_precision.core.line_geometry import Segment
from plugin.fortsmart_precision.core.row_engine import PlantingRow


def rectangle(width=400.0, height=240.0, x=0.0, y=0.0):
    outer = [(x, y), (x + width, y), (x + width, y + height), (x, y + height), (x, y)]
    return [(outer, [])]


def planter_18m() -> PlanterMachine:
    return PlanterMachine(
        machine_id="p18",
        name="Plantadeira 18m",
        row_count=36,
        row_spacing_m=0.50,
        track=MachineTrack(track_width_m=1.8, tire_width_m=0.3),
    )


def sprayer_24m() -> SprayerMachine:
    return SprayerMachine(
        machine_id="s24",
        name="Barra 24m",
        nozzle_count=48,
        nozzle_spacing_m=0.50,
        boom_width_m=24.0,
        track=MachineTrack(track_width_m=3.0, tire_width_m=0.35),
        overlap_m=0.0,
    )


class ExtensionAndPassNumberTest(unittest.TestCase):
    def test_default_extension_is_10(self):
        op = PrecisionOperation(operation_id="spray", machine=sprayer_24m())
        self.assertAlmostEqual(op.extension_m, 10.0)

    def test_pass_no_starts_at_zero(self):
        field = rectangle(200, 100)
        passes = generate_parallel_passes(
            ParallelPassParams(
                polygons=field,
                ab_start=(0.0, 50.0),
                ab_end=(200.0, 50.0),
                pass_spacing_m=24.0,
                operation_width_m=24.0,
                extension_m=10.0,
                operation_id="spray",
            )
        )
        self.assertGreater(len(passes), 0)
        # Linha 0 = passada sobre a A-B (nao a primeira da borda).
        nos = [p.pass_no for p in passes]
        self.assertIn(0, nos)
        zero = next(p for p in passes if p.pass_no == 0)
        self.assertAlmostEqual(zero.offset_m, 0.0, places=3)
        # Extensao via buffer: comprimento final = cobertura + 2*extensao.
        self.assertAlmostEqual(zero.guidance_segment.length, 200.0 + 20.0, places=3)
        xs = (
            zero.guidance_segment.start[0],
            zero.guidance_segment.end[0],
        )
        self.assertAlmostEqual(min(xs), -10.0, places=3)
        self.assertAlmostEqual(max(xs), 210.0, places=3)

    def test_pass_numbers_are_contiguous_around_ab(self):
        field = rectangle(200, 100)
        passes = generate_parallel_passes(
            ParallelPassParams(
                polygons=field,
                ab_start=(0.0, 50.0),
                ab_end=(200.0, 50.0),
                pass_spacing_m=24.0,
                operation_width_m=24.0,
                extension_m=10.0,
                operation_id="spray",
            )
        )
        nos = sorted(p.pass_no for p in passes)
        self.assertEqual(nos, list(range(nos[0], nos[-1] + 1)))
        from plugin.fortsmart_precision.core.parallel_pass_engine import line_label_for_pass

        self.assertEqual(line_label_for_pass(0, machine_prefix="P"), "P0")
        self.assertEqual(line_label_for_pass(-2, machine_prefix="A"), "A-2")


class HeadlandUnifiedTest(unittest.TestCase):
    def test_spray_headland_24m_center_at_12(self):
        field = rectangle(400, 240)
        op = PrecisionOperation(
            operation_id="spraying",
            machine=sprayer_24m(),
            headland=HeadlandLayout(pass_count=1, width_m=24.0, mode="parallel_ab"),
            extension_m=10.0,
        )
        boundary = build_boundary_plan(field, op, (0.0, 120.0), (400.0, 120.0))
        self.assertAlmostEqual(boundary.reserved_width_m, 24.0)
        self.assertEqual(len(boundary.headland_centerlines), 1)
        self.assertAlmostEqual(boundary.headland_centerlines[0].offset_from_outer_m, 12.0)
        self.assertEqual(boundary.headland_centerlines[0].pass_no, 0)
        self.assertGreaterEqual(len(boundary.headland_inner_limits), 1)

    def test_planting_headland_18m_center_at_9(self):
        field = rectangle(400, 240)
        op = PrecisionOperation(
            operation_id="planting",
            machine=planter_18m(),
            headland=HeadlandLayout(pass_count=1, width_m=18.0, mode="parallel_ab"),
            extension_m=10.0,
        )
        boundary = build_boundary_plan(field, op, (0.0, 120.0), (400.0, 120.0))
        self.assertAlmostEqual(boundary.reserved_width_m, 18.0)
        self.assertAlmostEqual(boundary.headland_centerlines[0].offset_from_outer_m, 9.0)
        self.assertTrue(boundary.headland_inner_limits)


class ShutoffFlagsTest(unittest.TestCase):
    def test_tramline_shutoff_can_be_disabled(self):
        field = rectangle(400, 240)
        project = PrecisionProject(
            field=FieldGeometry(field_boundary=field, operational_boundary=field, crs_authid="EPSG:31982"),
            ab_line=ABLine(start=(0.0, 120.0), end=(400.0, 120.0)),
            planting=PrecisionOperation(
                operation_id="planting",
                machine=planter_18m(),
                headland=HeadlandLayout(pass_count=1, width_m=18.0, mode="parallel_ab"),
            ),
            spraying=PrecisionOperation(operation_id="spraying", machine=sprayer_24m()),
            shutoff_on_tramlines=False,
            shutoff_on_headland_inner=False,
        )
        result = run_precision_lines(project)
        off = [s for s in result.shutoff_segments if s.shutoff_state == "off"]
        self.assertEqual(len(off), 0)
        self.assertGreater(len(result.shutoff_segments), 0)

    def test_headland_inner_produces_off_when_enabled(self):
        field = rectangle(400, 240)
        project = PrecisionProject(
            field=FieldGeometry(field_boundary=field, operational_boundary=field, crs_authid="EPSG:31982"),
            ab_line=ABLine(start=(0.0, 120.0), end=(400.0, 120.0)),
            planting=PrecisionOperation(
                operation_id="planting",
                machine=planter_18m(),
                headland=HeadlandLayout(pass_count=1, width_m=18.0, mode="parallel_ab"),
            ),
            shutoff_on_tramlines=False,
            shutoff_on_headland_inner=True,
        )
        result = run_precision_lines(project)
        self.assertIsNotNone(result.boundary)
        self.assertTrue(result.boundary.areas.headland_area)
        # Linhas virtuais adiadas ao cruzamento (plantio so, sem pulverizacao).
        self.assertEqual(len(result.planting_rows), 0)
        self.assertGreater(len(result.planting_passes), 0)

    def test_apply_row_shutoff_with_off_area(self):
        row = PlantingRow(
            fs_id="r1",
            row_id=1,
            pass_id=0,
            machine_id="p",
            spacing_m=0.5,
            direction="forward",
            offset_m=0.0,
            azimuth_deg=90.0,
            segment=Segment(start=(0.0, 0.0), end=(100.0, 0.0)),
        )
        # Faixa off cobrindo metade da linha (retangulo).
        off_area = [
            (
                [(40.0, -1.0), (60.0, -1.0), (60.0, 1.0), (40.0, 1.0), (40.0, -1.0)],
                [],
            )
        ]
        segments = apply_row_shutoff([row], [], off_areas=off_area, shutoff_on_tramlines=False)
        states = {s.shutoff_state for s in segments}
        self.assertIn("off", states)
        self.assertIn("on", states)


class PipelineSprayThenPlantTest(unittest.TestCase):
    def test_spray_only_then_plant_enumeration(self):
        field = rectangle(400, 240)
        spray_project = PrecisionProject(
            field=FieldGeometry(field_boundary=field, operational_boundary=field, crs_authid="EPSG:31982"),
            ab_line=ABLine(start=(0.0, 120.0), end=(400.0, 120.0)),
            spraying=PrecisionOperation(
                operation_id="spraying",
                machine=sprayer_24m(),
                headland=HeadlandLayout(pass_count=1, width_m=24.0, mode="parallel_ab"),
                extension_m=10.0,
            ),
        )
        spray_result = run_precision_lines(spray_project)
        self.assertGreater(len(spray_result.spraying_passes), 0)
        spray_nos = [p.pass_no for p in spray_result.spraying_passes]
        self.assertIn(0, spray_nos)
        zero = next(p for p in spray_result.spraying_passes if p.pass_no == 0)
        self.assertAlmostEqual(zero.offset_m, 0.0, places=3)
        self.assertIsNotNone(spray_result.boundary)
        self.assertAlmostEqual(spray_result.boundary.reserved_width_m, 24.0)

        plant_project = PrecisionProject(
            field=FieldGeometry(field_boundary=field, operational_boundary=field, crs_authid="EPSG:31982"),
            ab_line=ABLine(start=(0.0, 120.0), end=(400.0, 120.0)),
            planting=PrecisionOperation(
                operation_id="planting",
                machine=planter_18m(),
                headland=HeadlandLayout(pass_count=1, width_m=18.0, mode="parallel_ab"),
                extension_m=10.0,
            ),
            spraying=PrecisionOperation(operation_id="spraying", machine=sprayer_24m()),
            shutoff_on_tramlines=True,
            shutoff_on_headland_inner=True,
        )
        plant_result = run_precision_lines(plant_project)
        self.assertGreater(len(plant_result.planting_rows), 0)
        self.assertGreater(len(plant_result.tramline_zones), 0)
        zones = generate_tramline_zones(plant_result.spraying_passes, sprayer_24m())
        self.assertGreater(len(zones), 0)


if __name__ == "__main__":
    unittest.main()
