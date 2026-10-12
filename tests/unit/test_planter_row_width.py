# -*- coding: utf-8 -*-
"""Largura de trabalho informada = fonte de verdade; linhas x espacamento so analisam."""

from __future__ import annotations

import math
import unittest

from shapely.geometry import LineString, MultiLineString, Polygon

from plugin.fortsmart_precision.core.boundary_engine import build_boundary_plan
from plugin.fortsmart_precision.core.guidance_engine import traffic_pass_spacing_report
from plugin.fortsmart_precision.core.line_geometry import offset_open_polyline
from plugin.fortsmart_precision.core.parallel_pass_engine import (
    ParallelPassParams,
    generate_parallel_passes,
    straight_family_frame,
)
from plugin.fortsmart_precision.core.planter_row_preview import build_row_preview
from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
from plugin.fortsmart_precision.core.spacing_validation import (
    PASS_SPACING_OUT_OF_TOLERANCE,
    validate_adjacent_pass_spacing,
    validate_pass_spacing,
)
from plugin.fortsmart_precision.domain.agricultural_lines import PlantingSetup
from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
from plugin.fortsmart_precision.domain.machine_model import (
    MachineModelError,
    MachineTrack,
    PlanterMachine,
    SprayerMachine,
)
from plugin.fortsmart_precision.domain.planter_geometry import (
    GEOMETRY_WIDTH_MISMATCH,
    INTERPASS_ROW_GAP_OUT_OF_TOLERANCE,
    INVALID_PLANTER_ROW_GEOMETRY,
    PlanterGeometryConfig,
    PlanterGeometryError,
    PlanterGeometryValidator,
    calculate_row_offsets,
    planter_debug_report,
    resolve_effective_working_width,
    validate_interpass_row_gap,
)
from plugin.fortsmart_precision.domain.planting_configuration import PlantingConfiguration
from plugin.fortsmart_precision.domain.precision_project import (
    ABLine,
    FieldGeometry,
    PrecisionOperation,
    PrecisionProject,
)

E0, N0 = 650000.0, 8500000.0


def planter(rows=38, spacing=0.5, width=20.0):
    return PlanterMachine(
        machine_id="p", name="p", row_count=rows, row_spacing_m=spacing,
        track=MachineTrack(track_width_m=3.0, tire_width_m=0.4),
        informed_operational_width_m=width,
    )


def rotated_rect(width, height, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    pts = [(0, 0), (width, 0), (width, height), (0, height), (0, 0)]
    return [(E0 + x * c - y * s, N0 + x * s + y * c) for x, y in pts], (c, s)


def operation(machine, headland_passes=0):
    width = machine.operational_width_m
    return PrecisionOperation(
        operation_id="planting", machine=machine, extension_m=0.0,
        headland=HeadlandLayout(
            pass_count=headland_passes,
            width_m=width if headland_passes else 0.0,
            effective_spacing_m=width if headland_passes else None,
            mode="follow_boundary" if headland_passes else "none",
            corner_mode="FOLLOW_BOUNDARY",
        ),
    )


def row_union(rows):
    return MultiLineString([LineString(row.points) for row in rows])


def sine_master(amplitude=400.0, period=600.0, length=2000, step=10):
    return [(E0 + x, N0 + amplitude * math.sin(x / period)) for x in range(0, length + 1, step)]


def curved_passes(machine, master, extension=0.0):
    ring = [(E0 - 50, N0 - 700), (E0 + 2050, N0 - 700), (E0 + 2050, N0 + 900),
            (E0 - 50, N0 + 900), (E0 - 50, N0 - 700)]
    params = ParallelPassParams(
        polygons=[(ring, [])], ab_start=master[0], ab_end=master[-1],
        pass_spacing_m=operation(machine).pass_spacing_m,
        operation_width_m=machine.operational_width_m, extension_m=extension,
        master_path=tuple(master),
    )
    return generate_parallel_passes(params)


class GeometryConfigTest(unittest.TestCase):
    def assert_rows(self, rows, spacing, row_width, outer):
        config = PlanterGeometryConfig(rows, spacing)
        self.assertAlmostEqual(config.row_based_width_m, row_width, places=9)
        self.assertAlmostEqual(config.working_width_m, row_width, places=9)
        self.assertAlmostEqual(config.outer_row_offset_m, outer, places=9)
        self.assertAlmostEqual(config.outer_half_margin_m, spacing / 2.0, places=9)
        self.assertTrue(validate_interpass_row_gap(row_width, rows, spacing).ok)

    def test_planter_38x050_rows(self):
        self.assert_rows(38, 0.5, 19.0, 9.25)
        offsets = calculate_row_offsets(38, 0.5)
        self.assertAlmostEqual(offsets[0], -9.25)
        self.assertAlmostEqual(offsets[-1], 9.25)
        self.assertNotIn(0.0, offsets)
        self.assertTrue(all(abs(b - a - 0.5) < 1e-12 for a, b in zip(offsets, offsets[1:])))

    def test_planter_27x045_has_center_row(self):
        self.assert_rows(27, 0.45, 12.15, 5.85)
        self.assertAlmostEqual(calculate_row_offsets(27, 0.45)[13], 0.0, places=12)

    def test_planter_40x050_and_12x045(self):
        self.assert_rows(40, 0.5, 20.0, 9.75)
        self.assert_rows(12, 0.45, 5.40, 2.475)

    def test_interpass_math(self):
        report = validate_interpass_row_gap(19.0, 38, 0.5)
        self.assertAlmostEqual(report.right_outer_row_a_m, 9.25)
        self.assertAlmostEqual(report.left_outer_row_b_m, 9.75)
        self.assertAlmostEqual(report.error_m, 0.0, places=12)
        report = validate_interpass_row_gap(20.0, 38, 0.5)
        self.assertFalse(report.ok)
        self.assertEqual(report.code, INTERPASS_ROW_GAP_OUT_OF_TOLERANCE)
        self.assertAlmostEqual(report.actual_gap_m, 1.5)

    def test_invalid_rows_blocked(self):
        for rows, spacing in ((0, 0.5), (38, 0.0), (-1, 0.5)):
            with self.assertRaises(PlanterGeometryError) as ctx:
                PlanterGeometryConfig(rows, spacing).validate()
            self.assertEqual(ctx.exception.code, INVALID_PLANTER_ROW_GEOMETRY)
        with self.assertRaises(MachineModelError) as ctx:
            planter(rows=0).validate()
        self.assertIn(INVALID_PLANTER_ROW_GEOMETRY, str(ctx.exception))


class WorkingWidthPriorityTest(unittest.TestCase):
    def test_user_width_is_source_of_truth(self):
        config = PlanterGeometryConfig(38, 0.5, configured_width_m=20.0)
        self.assertAlmostEqual(config.working_width_m, 20.0)
        self.assertAlmostEqual(resolve_effective_working_width(config), 20.0)
        self.assertAlmostEqual(resolve_effective_working_width(config, 21.0), 21.0)

    def test_rows_only_without_user_width(self):
        self.assertAlmostEqual(PlanterGeometryConfig(38, 0.5).working_width_m, 19.0)
        self.assertAlmostEqual(planter(width=None).operational_width_m, 19.0)
        self.assertAlmostEqual(resolve_effective_working_width(None, 24.0), 24.0)
        with self.assertRaises(PlanterGeometryError):
            resolve_effective_working_width(None, None)

    def test_planter_machine_keeps_20m(self):
        machine = planter()
        self.assertAlmostEqual(machine.operational_width_m, 20.0)
        self.assertAlmostEqual(machine.effective_pass_spacing_m, 20.0)
        self.assertAlmostEqual(operation(machine).pass_spacing_m, 20.0)
        self.assertEqual(machine.meeting_status()["status"], "gap")

    def test_planting_configuration_and_setup(self):
        self.assertAlmostEqual(PlantingConfiguration(38, 0.5, informed_width_m=20.0).working_width_m, 20.0)
        self.assertAlmostEqual(PlantingConfiguration(38, 0.5).working_width_m, 19.0)
        self.assertAlmostEqual(PlantingSetup(38, 0.5).working_width_m, 19.0)

    def test_sprayer_unchanged(self):
        sprayer = SprayerMachine(
            machine_id="s", name="s", nozzle_count=72, nozzle_spacing_m=0.5, boom_width_m=36.0,
            track=MachineTrack(track_width_m=3.0, tire_width_m=0.4), overlap_m=0.5,
        )
        self.assertAlmostEqual(sprayer.operational_width_m, 36.0)
        self.assertAlmostEqual(PrecisionOperation("spraying", sprayer).pass_spacing_m, 35.5)


class ValidatorTest(unittest.TestCase):
    def test_mismatch_is_warning_with_message(self):
        issues = PlanterGeometryValidator().validate(PlanterGeometryConfig(38, 0.5, 20.0))
        self.assertEqual([(i.level, i.code) for i in issues], [("warning", GEOMETRY_WIDTH_MISMATCH)])
        self.assertTrue(
            issues[0].message.startswith(
                "Largura de trabalho configurada: 20.00 m\n"
                "Largura equivalente pelas linhas: 19.00 m\n"
                "Diferenca: 1.00 m"
            ),
            issues[0].message,
        )
        self.assertIn("Encontro entre passadas: 1.50 m", issues[0].message)

    def test_compatible_or_missing_width_is_silent(self):
        self.assertEqual(PlanterGeometryValidator().validate(PlanterGeometryConfig(38, 0.5, 19.02)), [])
        self.assertEqual(PlanterGeometryValidator().validate(PlanterGeometryConfig(38, 0.5)), [])
        self.assertEqual(PlanterGeometryValidator().validate(PlanterGeometryConfig(40, 0.5, 20.0)), [])

    def test_invalid_rows_issue(self):
        issues = PlanterGeometryValidator().validate(PlanterGeometryConfig(0, 0.5))
        self.assertEqual(issues[0].code, INVALID_PLANTER_ROW_GEOMETRY)

    def test_debug_report(self):
        lines = planter_debug_report(PlanterGeometryConfig(38, 0.5, 20.0))
        for expected in ("Rows=38", "ConfiguredWidth=20.00", "WorkingWidth=20.00",
                         "RowBasedWidth=19.00", "OuterRowOffset=9.25", "P2 center=20.00",
                         "RightRowP1=9.25", "LeftRowP2=10.75", "Gap=1.50",
                         f"WARNING {GEOMETRY_WIDTH_MISMATCH}"):
            self.assertIn(expected, lines)


class StraightPassTest(unittest.TestCase):
    def straight(self, machine, n_passes, deg=37.0):
        spacing = operation(machine).pass_spacing_m
        ring, (c, s) = rotated_rect(1500.0, n_passes * spacing + 5.0, deg)
        a, b = (E0, N0), (E0 + 100.0 * c, N0 + 100.0 * s)
        params = ParallelPassParams(
            polygons=[(ring, [])], ab_start=a, ab_end=b, pass_spacing_m=spacing,
            operation_width_m=machine.operational_width_m, extension_m=0.0, master_path=(a, b),
        )
        passes = generate_parallel_passes(params)
        origin, _d, normal = straight_family_frame(a, b, (a, b))
        report = validate_pass_spacing(
            ((p.source_candidate_index, p.line_points()) for p in passes), origin, normal, spacing
        )
        return passes, report

    def test_20m_with_38x050_stays_20m(self):
        _passes, report = self.straight(planter(), 100)
        offsets = {abs(s.pass_index): abs(s.actual_offset_m) for s in report.samples}
        for index, expected in ((1, 20.0), (2, 40.0), (3, 60.0), (4, 80.0), (100, 2000.0)):
            self.assertAlmostEqual(offsets[index], expected, delta=1e-6)
        self.assertLess(report.max_abs_error_m, 1e-6)

    def test_round_trip_rows_show_real_meeting(self):
        machine = planter()
        passes, _report = self.straight(machine, 4, deg=0.0)
        by_index = {p.source_candidate_index: p for p in passes}
        rows_a = build_row_preview(by_index[1].line_points(), machine.geometry_config, direction="forward")
        rows_b = build_row_preview(by_index[2].line_points(), machine.geometry_config, direction="reverse")
        self.assertEqual(len(rows_a), 38)
        # 20 m entre eixos com 38 x 0,50: as linhas extremas ficam a 1,50 m (aviso, nao correcao).
        self.assertAlmostEqual(row_union(rows_a).distance(row_union(rows_b)), 1.5, places=6)

    def test_reverse_keeps_spatial_distribution(self):
        config = PlanterGeometryConfig(38, 0.5)
        path = [(0.0, 0.0), (100.0, 0.0)]
        forward = build_row_preview(path, config)
        reverse = build_row_preview(path, config, direction="reverse")
        self.assertEqual(
            sorted(round(row.points[0][1], 9) for row in forward),
            sorted(round(row.points[0][1], 9) for row in reverse),
        )
        self.assertAlmostEqual(forward[0].points[0][1], 9.25)
        self.assertAlmostEqual(reverse[0].points[0][1], -9.25)
        self.assertEqual((forward[0].label, forward[-1].label), ("ROW_01", "ROW_38"))


class CurvedPassTest(unittest.TestCase):
    def test_curved_passes_keep_20m_on_local_normal(self):
        passes = curved_passes(planter(), sine_master())
        indexed = [(round(-p.offset_m / 20.0), p.line_points()) for p in passes]
        report = validate_adjacent_pass_spacing(indexed, 20.0)
        self.assertTrue(report.ok, report.errors)
        self.assertGreaterEqual(len(report.pairs), 30)
        self.assertLessEqual(report.max_abs_error_m, 0.01)
        offsets = sorted({round(-p.offset_m, 6) for p in passes})
        self.assertTrue(all(abs(v / 20.0 - round(v / 20.0)) < 1e-9 for v in offsets))

    def test_tight_curve_keeps_20m(self):
        # Raio minimo ~90 m: o offset por bissetriz encurtava a distancia nos vertices.
        master = sine_master(amplitude=250.0, period=300.0, step=25)
        passes = curved_passes(planter(), master)
        report = validate_adjacent_pass_spacing(
            [(round(-p.offset_m / 20.0), p.line_points()) for p in passes], 20.0
        )
        self.assertTrue(report.ok, report.errors)

    def test_successive_offsets_drift_and_are_reported(self):
        master = sine_master(amplitude=250.0, period=300.0, step=25)
        drifting = [(0, master)]
        previous = master
        for index in range(1, 6):
            previous = offset_open_polyline(previous, -20.0)
            drifting.append((index, previous))
        report = validate_adjacent_pass_spacing(drifting, 20.0)
        self.assertFalse(report.ok)
        self.assertEqual(report.code, PASS_SPACING_OUT_OF_TOLERANCE)
        message = report.errors[0]
        self.assertIn("Esperado: 20.00 m", message)
        self.assertIn("Encontrado:", message)
        self.assertRegex(message, r"Passadas: P\d+ / P\d+")
        self.assertRegex(message, r"Trecho: segmento \d+")

    def test_validator_reports_pair_and_segment(self):
        p14 = [(0.0, 0.0), (500.0, 0.0)]
        p15 = [(0.0, 20.0), (240.0, 20.0), (250.0, 18.73), (260.0, 20.0), (500.0, 20.0)]
        report = validate_adjacent_pass_spacing([(14, p14), (15, p15)], 20.0, sample_step_m=0.5)
        self.assertEqual(len(report.errors), 1)
        self.assertIn("Encontrado: 18.73 m", report.errors[0])
        self.assertIn("Passadas: P14 / P15", report.errors[0])
        self.assertIn("da P15", report.errors[0])
        self.assertIn(report.pairs[0].worst_segment, (1, 2))

    def test_validator_ignores_pass_ends(self):
        inner = [(0.0, 0.0), (300.0, 0.0)]
        outer = [(-50.0, 20.0), (400.0, 20.0)]
        report = validate_adjacent_pass_spacing([(0, inner), (1, outer)], 20.0)
        self.assertTrue(report.ok, report.errors)
        self.assertAlmostEqual(report.pairs[0].max_m, 20.0, places=6)

    def test_curved_row_preview_meeting(self):
        machine = planter(width=19.0)
        passes = curved_passes(machine, sine_master())
        by_offset = {round(-p.offset_m / 19.0): p for p in passes}
        rows_a = build_row_preview(by_offset[1].line_points(), machine.geometry_config)
        rows_b = build_row_preview(by_offset[2].line_points(), machine.geometry_config)
        window = Polygon([(E0 + 300, N0 - 700), (E0 + 1700, N0 - 700), (E0 + 1700, N0 + 900), (E0 + 300, N0 + 900)])
        gap = row_union(rows_a).intersection(window).distance(row_union(rows_b).intersection(window))
        self.assertAlmostEqual(gap, 0.5, delta=0.01)


class HeadlandTest(unittest.TestCase):
    def test_headland_passes_are_20m_apart(self):
        ring, _cs = rotated_rect(1200.0, 900.0, 37.0)
        machine = planter()
        plan = build_boundary_plan([(ring, [])], operation(machine, headland_passes=3), (E0, N0), (E0 + 100, N0))
        levels = plan.offset_validation["headland"]["levels"]
        # B0 no eixo a meia largura do limite; B1 e B2 a +20 m e +40 m de B0.
        self.assertEqual([lvl["expected_offset_m"] for lvl in levels], [10.0, 30.0, 50.0])
        centers = [(lvl["min_distance_m"] + lvl["max_distance_m"]) / 2 for lvl in levels]
        for a, b in zip(centers, centers[1:]):
            self.assertAlmostEqual(b - a, 20.0, delta=0.01)
        self.assertAlmostEqual(plan.reserved_width_m, 60.0)


class PipelineTest(unittest.TestCase):
    def project(self, machine, headland=3, ab_line=None):
        ring, (c, s) = rotated_rect(1200.0, 950.0, 37.0)
        field = [(ring, [])]
        return PrecisionProject(
            field=FieldGeometry(field_boundary=field, operational_boundary=field, crs_authid="EPSG:31981"),
            ab_line=ab_line or ABLine(start=(E0, N0), end=(E0 + 100.0 * c, N0 + 100.0 * s)),
            planting=operation(machine, headland_passes=headland),
        )

    def test_pipeline_keeps_20m_and_only_warns(self):
        project = self.project(planter())
        result = run_precision_lines(project)
        self.assertTrue(result.validation.ok, [e.message for e in result.validation.errors])
        report = traffic_pass_spacing_report(result.planting_passes, project.effective_ab_line(), project.planting)
        for value in (report.min_spacing_m, report.mean_spacing_m, report.max_spacing_m):
            self.assertAlmostEqual(value, 20.0, delta=1e-6)
        warnings = [w.code for w in result.validation.warnings]
        self.assertIn(GEOMETRY_WIDTH_MISMATCH, warnings)
        self.assertIn(INTERPASS_ROW_GAP_OUT_OF_TOLERANCE, warnings)
        checks = " | ".join(result.validation.checks)
        self.assertIn("Encontro entre passadas plantio: 1.500 m", checks)
        self.assertIn("Distancia normal entre passadas vizinhas plantio", checks)
        offsets = sorted({line.offset_from_outer_m for line in result.boundary.headland_centerlines})
        self.assertEqual(offsets, [10.0, 30.0, 50.0])

    def test_curved_pipeline_keeps_20m(self):
        ring, (c, s) = rotated_rect(1200.0, 950.0, 37.0)
        local = [(u, 475.0 + 150.0 * math.sin(u / 250.0)) for u in range(0, 1201, 25)]
        path = [(E0 + x * c - y * s, N0 + x * s + y * c) for x, y in local]
        ab = ABLine(start=path[0], end=path[-1], path_points=tuple(path))
        result = run_precision_lines(self.project(planter(), headland=0, ab_line=ab))
        self.assertTrue(result.validation.ok, [e.message for e in result.validation.errors])
        indexed = [(round(-p.offset_m / 20.0), p.line_points()) for p in result.planting_passes]
        report = validate_adjacent_pass_spacing(indexed, 20.0)
        self.assertTrue(report.ok, report.errors)
        self.assertGreaterEqual(len(report.pairs), 20)


if __name__ == "__main__":
    unittest.main()
