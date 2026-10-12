# -*- coding: utf-8 -*-
"""Bordadura FIDELITY: fiel ao limite real, sem regredir V/U nem o LEGACY."""

from __future__ import annotations

import math
import unittest
from unittest.mock import patch

from shapely.geometry import LineString, Point, Polygon

from plugin.fortsmart_precision.core import boundary_engine
from plugin.fortsmart_precision.core.boundary_engine import (
    build_boundary_plan,
    compare_headland_modes,
    headland_pass_id,
)
from plugin.fortsmart_precision.core.headland_fidelity_engine import (
    HeadlandValidationReport,
    clip_path_to_field,
    distance_tolerance_m,
    point_distances_to_boundary,
    prepare_boundary,
    progressive_offsets,
    validate_fidelity_headland,
)
from plugin.fortsmart_precision.core.line_geometry import line_line_intersection
from plugin.fortsmart_precision.core.path_smoothing_engine import smooth_boundary_plan
from plugin.fortsmart_precision.domain.headland_layout import (
    HEADLAND_CORNER_AUTO,
    HEADLAND_MODE_FIDELITY,
    HEADLAND_MODE_LEGACY,
    HeadlandConfigurationError,
    HeadlandLayout,
)
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, PlanterMachine
from plugin.fortsmart_precision.domain.path_smoothing_configuration import (
    PathSmoothingConfiguration,
    SmoothingLevel,
)
from plugin.fortsmart_precision.domain.precision_project import PrecisionOperation


def _operation(width_m, pass_count=1, mode=HEADLAND_MODE_FIDELITY, corner_mode=HEADLAND_CORNER_AUTO):
    machine = PlanterMachine(
        machine_id="test",
        name="test",
        row_count=max(1, int(round(width_m / 0.5))),
        row_spacing_m=0.5,
        track=MachineTrack(track_width_m=1.8, tire_width_m=0.3),
    )
    return PrecisionOperation(
        operation_id="planting",
        machine=machine,
        headland=HeadlandLayout(
            pass_count=pass_count,
            width_m=width_m,
            effective_spacing_m=width_m,
            mode="follow_boundary",
            corner_mode=corner_mode,
            headland_mode=mode,
        ),
        extension_m=0.0,
    )


def _plan(field, width_m, pass_count=1, mode=HEADLAND_MODE_FIDELITY, **kwargs):
    return build_boundary_plan(field, _operation(width_m, pass_count, mode, **kwargs), (0.0, 0.0), (100.0, 0.0))


def _field(ring, holes=()):
    ring = list(ring)
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return [(ring, [list(h) for h in holes])]


def _rectangle(w, h):
    return _field([(0, 0), (w, 0), (w, h), (0, h)])


def _pivot(radius=300.0, segments=180):
    return _field([
        (radius * math.cos(2 * math.pi * i / segments), radius * math.sin(2 * math.pi * i / segments))
        for i in range(segments)
    ])


def _irregular():
    return _field([(0, 0), (1350, 80), (1500, 520), (1180, 910), (620, 840), (240, 1010), (-60, 610)])


def _gentle_curve():
    """Lado de cima com curva suave desenhada com poucos vertices."""
    top = [(400.0 - 400.0 * i / 8.0, 200.0 + 25.0 * math.sin(math.pi * i / 8.0)) for i in range(9)]
    return _field([(0, 0), (400, 0), *top])


def _step(depth=20.0):
    """Recuo lateral: o limite superior desce `depth` metros a partir de x=300."""
    return _field([(0, 0), (600, 0), (600, 200 - depth), (300, 200 - depth), (300, 200), (0, 200)])


def _pole_notch(width=2000.0, height=1000.0, notch_w=6.0, notch_d=4.0):
    """Desvio de poste ja desenhado no limite inferior (entra no talhao)."""
    x0 = width / 2.0 - notch_w / 2.0
    return _field([
        (0, 0), (x0, 0), (x0, notch_d), (x0 + notch_w, notch_d), (x0 + notch_w, 0),
        (width, 0), (width, height), (0, height),
    ])


def _tree_notch(radius=5.0):
    """Desvio de arvore: semicirculo no limite inferior."""
    arc = [
        (200.0 - radius * math.cos(math.pi * i / 16.0), radius * math.sin(math.pi * i / 16.0))
        for i in range(17)
    ]
    return _field([(0, 0), *arc, (400, 0), (400, 200), (0, 200)])


def _sharp_v():
    return _field([(0, 0), (200, 0), (200, 80), (300, 100), (200, 120), (200, 200), (0, 200)])


def _narrow_u():
    cap = [
        (300.0 + 5.0 * math.cos(-math.pi / 2.0 + i * math.pi / 12.0),
         100.0 + 5.0 * math.sin(-math.pi / 2.0 + i * math.pi / 12.0))
        for i in range(13)
    ]
    return _field([(0, 0), (200, 0), (200, 95), *cap, (200, 105), (200, 200), (0, 200)])


def _open_u(radius=60.0):
    cap = [
        (300.0 + radius * math.cos(-math.pi / 2.0 + i * math.pi / 24.0),
         radius + radius * math.sin(-math.pi / 2.0 + i * math.pi / 24.0))
        for i in range(25)
    ]
    return _field([(0, 0), (300, 0), *cap, (300, 2 * radius), (0, 2 * radius)])


def _hourglass():
    """Dois quadrados ligados por um gargalo de 8 m: o offset de 6 m se divide."""
    return _field([
        (0, 0), (100, 0), (100, 46), (140, 46), (140, 0), (240, 0),
        (240, 100), (140, 100), (140, 54), (100, 54), (100, 100), (0, 100),
    ])


def _ys_at_x(line, x):
    """Ordenadas onde a passada cruza a vertical x (independe da densidade de vertices)."""
    hit = LineString(line.line_points()).intersection(LineString([(x, -1e6), (x, 1e6)]))
    points = [hit] if hit.geom_type == "Point" else list(getattr(hit, "geoms", []))
    return sorted(p.y for p in points if p.geom_type == "Point")


def _max_offset_deviation(plan, field):
    boundary = prepare_boundary(field)
    worst = 0.0
    for line in plan.headland_centerlines:
        distances = point_distances_to_boundary(list(line.line_points()), boundary)
        worst = max(worst, max(abs(d - line.offset_from_outer_m) for d in distances))
    return worst


class FidelityAssertions(unittest.TestCase):
    def assertFaithful(self, plan, field):
        self.assertEqual(plan.headland_mode, HEADLAND_MODE_FIDELITY)
        self.assertFalse(plan.headland_fallback, plan.headland_validation)
        self.assertTrue(plan.headland_validation["valid"], plan.headland_validation)
        worst_offset = max(line.offset_from_outer_m for line in plan.headland_centerlines)
        self.assertLess(_max_offset_deviation(plan, field), distance_tolerance_m(worst_offset))
        boundary = prepare_boundary(field)
        for line in plan.headland_centerlines:
            self.assertLess(LineString(line.line_points()).difference(boundary).length, 0.01)


class FidelityRegressionCasesTest(FidelityAssertions):
    def test_01_rectangle_matches_exact_inset(self):
        plan = _plan(_rectangle(400, 200), 12.0, pass_count=3)
        self.assertFaithful(plan, _rectangle(400, 200))
        self.assertEqual([l.pass_id for l in plan.headland_centerlines], ["HEADLAND_01", "HEADLAND_02", "HEADLAND_03"])
        for line, inset in zip(plan.headland_centerlines, (6.0, 18.0, 30.0)):
            points = line.line_points()
            self.assertEqual(points[0], points[-1])
            self.assertAlmostEqual(line.length_m(), 2 * (400 - 2 * inset) + 2 * (200 - 2 * inset), places=6)

    def test_02_circular_pivot_keeps_constant_radius(self):
        field = _pivot()
        plan = _plan(field, 18.0, pass_count=2)
        self.assertFaithful(plan, field)
        for line, radius in zip(plan.headland_centerlines, (291.0, 273.0)):
            radii = [math.hypot(x, y) for x, y in line.line_points()]
            self.assertAlmostEqual(min(radii), radius, delta=0.6)
            self.assertAlmostEqual(max(radii), radius, delta=0.6)

    def test_03_irregular_field(self):
        field = _irregular()
        plan = _plan(field, 12.0, pass_count=3)
        self.assertFaithful(plan, field)
        self.assertLess(plan.headland_validation["spacing_deviation_m"], distance_tolerance_m(30.0))

    def test_04_gentle_curve_is_not_straightened(self):
        field = _gentle_curve()
        plan = _plan(field, 12.0, pass_count=2)
        self.assertFaithful(plan, field)
        self.assertAlmostEqual(max(_ys_at_x(plan.headland_centerlines[0], 200.0)), 225.0 - 6.0, delta=0.3)

    def test_05_lateral_recess_is_reproduced_by_each_pass(self):
        field = _step(depth=20.0)
        plan = _plan(field, 12.0, pass_count=2)
        self.assertFaithful(plan, field)
        for line, offset in zip(plan.headland_centerlines, (6.0, 18.0)):
            self.assertAlmostEqual(max(_ys_at_x(line, 150.0)), 200.0 - offset, places=3)
            self.assertAlmostEqual(max(_ys_at_x(line, 450.0)), 180.0 - offset, places=3)

    def test_06_pole_bypass_survives_in_large_field(self):
        field = _pole_notch()
        plan = _plan(field, 12.0, pass_count=2)
        self.assertFaithful(plan, field)
        for line, offset in zip(plan.headland_centerlines, (6.0, 18.0)):
            self.assertAlmostEqual(min(_ys_at_x(line, 1000.0)), 4.0 + offset, places=3)
            self.assertAlmostEqual(min(_ys_at_x(line, 900.0)), offset, places=3)

    def test_07_tree_bypass_is_followed_without_double_offset(self):
        field = _tree_notch(radius=5.0)
        plan = _plan(field, 12.0, pass_count=1)
        self.assertFaithful(plan, field)
        self.assertAlmostEqual(min(_ys_at_x(plan.headland_centerlines[0], 200.0)), 5.0 + 6.0, delta=0.1)
        self.assertAlmostEqual(min(_ys_at_x(plan.headland_centerlines[0], 100.0)), 6.0, places=3)

    def test_08_v_tip_keeps_crossing_legs(self):
        plan = _plan(_sharp_v(), 10.0, pass_count=2)
        self.assertFalse(plan.headland_fallback, plan.headland_validation)
        lines = plan.headland_centerlines
        self.assertEqual(len(lines), 2)
        self.assertEqual([l.offset_from_outer_m for l in lines], [5.0, 15.0])
        self.assertEqual(len({l.fs_id for l in lines}), 2)
        for line in lines:
            points = line.line_points()
            self.assertNotEqual(points[0], points[-1])
            crossing = line_line_intersection(points[0], points[1], points[-2], points[-1])
            self.assertIsNotNone(crossing)
            self.assertGreater(crossing[0], 200.0)
            self.assertFalse(LineString(points).is_simple, "o X da ponta deve continuar existindo")

    def test_09_open_u_stays_closed_contour(self):
        field = _open_u()
        plan = _plan(field, 12.0, pass_count=2)
        self.assertFaithful(plan, field)
        for line in plan.headland_centerlines:
            self.assertEqual(line.line_points()[0], line.line_points()[-1])

    def test_10_very_narrow_u_becomes_two_parallel_legs_clipped_at_boundary(self):
        field = _narrow_u()
        plan = _plan(field, 4.0)
        self.assertFalse(plan.headland_fallback, plan.headland_validation)
        self.assertEqual(len(plan.headland_centerlines), 1)
        points = plan.headland_centerlines[0].line_points()
        self.assertNotEqual(points[0], points[-1])
        self.assertAlmostEqual(points[0][1], 103.0, delta=0.25)
        self.assertAlmostEqual(points[-1][1], 97.0, delta=0.25)
        # As pernas seguem retas ate o limite (x ~ 304 a 3 m do eixo do U) sem virar U.
        self.assertGreater(points[0][0], 303.5)
        self.assertGreater(points[-1][0], 303.5)
        self.assertLess(LineString(points).difference(prepare_boundary(field)).length, 0.01)
        cap = [p for p in points[1:-1] if p[0] > 300.5 and 97.5 < p[1] < 102.5]
        self.assertEqual(cap, [])

    def test_11_split_offset_keeps_one_pass_with_independent_segments(self):
        field = _hourglass()
        plan = _plan(field, 12.0, pass_count=1)
        self.assertFaithful(plan, field)
        lines = plan.headland_centerlines
        self.assertEqual([(l.pass_id, l.segment_id) for l in lines], [("HEADLAND_01", 1), ("HEADLAND_01", 2)])
        self.assertEqual({l.pass_no for l in lines}, {0})
        # LEGACY tambem preserva os dois lados do estrangulamento (mesma passada B1).
        legacy = _plan(field, 12.0, pass_count=1, mode=HEADLAND_MODE_LEGACY)
        self.assertEqual(len(legacy.headland_centerlines), 2)
        self.assertEqual({l.pass_no for l in legacy.headland_centerlines}, {0})

    def test_12_multiple_passes_are_progressive_and_parallel(self):
        field = _irregular()
        plan = _plan(field, 12.0, pass_count=5)
        self.assertFaithful(plan, field)
        self.assertEqual(
            [(l.pass_id, l.parent_pass_id) for l in plan.headland_centerlines],
            [("HEADLAND_01", "BOUNDARY")] + [
                (headland_pass_id(i), headland_pass_id(i - 1)) for i in range(1, 5)
            ],
        )
        self.assertLess(plan.headland_validation["spacing_deviation_m"], distance_tolerance_m(54.0))


class LegacyPreservationTest(unittest.TestCase):
    def test_default_mode_is_legacy_and_output_is_unchanged(self):
        field = _irregular()
        default = build_boundary_plan(field, _operation(12.0, 2, mode=HEADLAND_MODE_LEGACY), (0, 0), (100, 0))
        explicit_op = _operation(12.0, 2, mode=HEADLAND_MODE_LEGACY)
        self.assertEqual(HeadlandLayout().headland_mode, HEADLAND_MODE_LEGACY)
        explicit = build_boundary_plan(field, explicit_op, (0, 0), (100, 0))
        self.assertEqual(
            [l.line_points() for l in default.headland_centerlines],
            [l.line_points() for l in explicit.headland_centerlines],
        )
        self.assertFalse(default.headland_fallback)
        self.assertIsNone(default.headland_validation)
        self.assertEqual(
            set(default.headland_centerlines[0].attributes()),
            {"fs_id", "pass_no", "offset_from_outer_m", "azimuth_deg", "length_m", "role"},
        )

    def test_fidelity_exports_identity_attributes(self):
        plan = _plan(_rectangle(400, 200), 12.0)
        attrs = plan.headland_centerlines[0].attributes()
        self.assertEqual(
            (attrs["pass_id"], attrs["parent_pass_id"], attrs["segment_id"]), ("HEADLAND_01", "BOUNDARY", 1)
        )
        self.assertEqual(plan.report()["headland_mode"], HEADLAND_MODE_FIDELITY)
        self.assertFalse(plan.report()["HEADLAND_FALLBACK"])

    def test_invalid_mode_is_rejected(self):
        with self.assertRaises(HeadlandConfigurationError):
            HeadlandLayout(pass_count=1, width_m=12.0, mode="follow_boundary", headland_mode="X").validate()


class FallbackTest(unittest.TestCase):
    def _legacy_points(self, field):
        return [l.line_points() for l in _plan(field, 12.0, 2, mode=HEADLAND_MODE_LEGACY).headland_centerlines]

    def test_exception_falls_back_to_legacy(self):
        field = _irregular()
        with patch.object(boundary_engine, "build_fidelity_headland_centerlines", side_effect=RuntimeError("boom")):
            plan = _plan(field, 12.0, 2)
        self.assertTrue(plan.headland_fallback)
        self.assertTrue(plan.report()["HEADLAND_FALLBACK"])
        self.assertIn("EXCEPTION: boom", plan.headland_validation["errors"])
        self.assertEqual([l.line_points() for l in plan.headland_centerlines], self._legacy_points(field))

    def test_invalid_validation_falls_back_to_legacy(self):
        field = _irregular()
        failing = HeadlandValidationReport(
            pass_count=2, segment_count=2, outside_length_m=5.0, spacing_deviation_m=0.0,
            fidelity_deviation_m=0.0, invalid_geometry_count=0, loop_count=0, spike_count=0,
            short_segment_count=0, duplicate_id_count=0, empty_pass_count=0,
            errors=("OUTSIDE_FIELD: teste",),
        )
        with patch(
            "plugin.fortsmart_precision.core.headland_fidelity_engine.validate_fidelity_headland",
            return_value=failing,
        ):
            plan = _plan(field, 12.0, 2)
        self.assertTrue(plan.headland_fallback)
        self.assertEqual(plan.headland_validation["errors"], ["OUTSIDE_FIELD: teste"])
        self.assertEqual([l.line_points() for l in plan.headland_centerlines], self._legacy_points(field))


class ComparisonTest(unittest.TestCase):
    def test_rectangle_modes_agree_on_topology(self):
        result = compare_headland_modes(_rectangle(400, 200), _operation(12.0, 3), (0, 0), (100, 0))
        legacy, fidelity = result[HEADLAND_MODE_LEGACY], result[HEADLAND_MODE_FIDELITY]
        for key in ("line_count", "pass_ids", "open_lines", "crossing_lines", "inner_area_ha"):
            self.assertEqual(legacy[key], fidelity[key], key)
        self.assertAlmostEqual(legacy["total_length_m"], fidelity["total_length_m"], delta=0.5)
        self.assertFalse(fidelity["headland_fallback"])

    def test_v_tip_modes_agree_on_crossings_and_open_ends(self):
        result = compare_headland_modes(_sharp_v(), _operation(10.0, 2), (0, 0), (100, 0))
        self.assertNotIn("crossing_lines", result["differences"])
        self.assertNotIn("open_lines", result["differences"])
        self.assertEqual(result[HEADLAND_MODE_FIDELITY]["crossing_lines"], 2)

    def test_narrow_u_difference_is_only_the_clip_at_the_boundary(self):
        field = _narrow_u()
        result = compare_headland_modes(field, _operation(4.0, 1), (0, 0), (100, 0))
        self.assertEqual(set(result["differences"]) - {"endpoints", "total_length_m", "max_offset_deviation_m"}, set())
        boundary = prepare_boundary(field)
        (legacy_start, legacy_end), = result[HEADLAND_MODE_LEGACY]["endpoints"]
        (fid_start, fid_end), = result[HEADLAND_MODE_FIDELITY]["endpoints"]
        self.assertFalse(boundary.covers(Point(legacy_start)))
        self.assertTrue(boundary.buffer(0.01).covers(Point(fid_start)))
        self.assertTrue(boundary.buffer(0.01).covers(Point(fid_end)))

    def test_large_field_keeps_pole_bypass_in_both_modes(self):
        # Antes a reamostragem de 720 vertices apagava o recorte de 6 m no LEGACY.
        result = compare_headland_modes(_pole_notch(), _operation(12.0, 2), (0, 0), (100, 0))
        legacy_dev = result[HEADLAND_MODE_LEGACY]["max_offset_deviation_m"]
        fidelity_dev = result[HEADLAND_MODE_FIDELITY]["max_offset_deviation_m"]
        self.assertLessEqual(max(legacy_dev.values()), 0.01)
        self.assertLess(max(fidelity_dev.values()), distance_tolerance_m(18.0))


class FidelityGeometryHelpersTest(unittest.TestCase):
    def test_prepare_boundary_fixes_self_intersection_without_simplifying(self):
        bowtie = _field([(0, 0), (100, 100), (100, 0), (0, 100)])
        fixed = prepare_boundary(bowtie)
        self.assertTrue(fixed.is_valid)
        self.assertAlmostEqual(fixed.area, 5000.0, places=6)
        detailed = prepare_boundary(_pole_notch())
        self.assertEqual(len(detailed.exterior.coords), 9)

    def test_progressive_offsets_equal_direct_offsets(self):
        boundary = prepare_boundary(_irregular())
        passes = progressive_offsets(boundary, [6.0, 18.0, 30.0])
        for item in passes:
            direct = boundary.buffer(-item.offset_m, quad_segs=24, join_style="round")
            self.assertLess(item.geometry.symmetric_difference(direct).area / direct.area, 1e-4)

    def test_clip_preserves_self_crossing_and_trims_outside(self):
        field = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
        path = ((-10.0, 10.0), (80.0, 90.0), (80.0, 10.0), (-10.0, 90.0))
        pieces = clip_path_to_field(path, field)
        self.assertEqual(len(pieces), 1)
        self.assertFalse(LineString(pieces[0]).is_simple)
        self.assertAlmostEqual(pieces[0][0][0], 0.0, places=6)
        self.assertAlmostEqual(pieces[0][-1][0], 0.0, places=6)
        inside = ((10.0, 10.0), (90.0, 10.0), (90.0, 90.0), (10.0, 10.0))
        self.assertEqual(clip_path_to_field(inside, field), [inside])

    def test_validation_detects_outside_and_duplicate_ids(self):
        from plugin.fortsmart_precision.core.headland_fidelity_engine import FinalHeadlandPath

        boundary = prepare_boundary(_rectangle(100, 100))
        passes = progressive_offsets(boundary, [5.0])
        finals = [
            FinalHeadlandPath("HEADLAND_01", 1, ((5.0, 5.0), (120.0, 5.0))),
            FinalHeadlandPath("HEADLAND_01", 1, ((5.0, 50.0), (50.0, 50.0))),
        ]
        report = validate_fidelity_headland(boundary, passes, finals)
        self.assertFalse(report.valid)
        self.assertTrue(any(e.startswith("OUTSIDE_FIELD") for e in report.errors))
        self.assertTrue(any(e.startswith("DUPLICATE_ID") for e in report.errors))

    def test_distance_helpers(self):
        self.assertAlmostEqual(distance_tolerance_m(0.0), 0.05)
        self.assertGreater(distance_tolerance_m(100.0), distance_tolerance_m(10.0))
        boundary = prepare_boundary(_rectangle(100, 100))
        self.assertEqual(point_distances_to_boundary([(10.0, 50.0)], boundary), [10.0])
        self.assertEqual(headland_pass_id(0), "HEADLAND_01")


class PipelinePropagationTest(unittest.TestCase):
    def test_default_headland_operation_keeps_mode(self):
        from plugin.fortsmart_precision.core.precision_lines_engine import _operation_with_default_headland

        op = _operation(12.0, 2)
        self.assertEqual(
            _operation_with_default_headland(op, default_pass_count=0).headland.headland_mode,
            HEADLAND_MODE_FIDELITY,
        )

    def test_status_note(self):
        from plugin.fortsmart_precision.core.boundary_engine import headland_status_note

        legacy = _plan(_rectangle(400, 200), 12.0, mode=HEADLAND_MODE_LEGACY)
        fidelity = _plan(_rectangle(400, 200), 12.0)
        self.assertEqual(headland_status_note(plantio=legacy, aplicacao=None), "")
        self.assertEqual(headland_status_note(plantio=fidelity), "Bordadura plantio: FIDELITY")
        with patch.object(boundary_engine, "build_fidelity_headland_centerlines", side_effect=RuntimeError("x")):
            failed = _plan(_rectangle(400, 200), 12.0)
        self.assertEqual(
            headland_status_note(aplicacao=failed),
            "Bordadura aplicacao: FIDELITY falhou, usado LEGACY (EXCEPTION: x)",
        )


class EndToEndPipelineTest(unittest.TestCase):
    def test_run_precision_lines_with_fidelity_headland(self):
        from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
        from plugin.fortsmart_precision.domain.machine_model import SprayerMachine
        from plugin.fortsmart_precision.domain.precision_project import ABLine, FieldGeometry, PrecisionProject

        field = _pole_notch(width=600.0, height=300.0)
        sprayer = SprayerMachine(
            machine_id="s24", name="Barra 24m", nozzle_count=48, nozzle_spacing_m=0.5, boom_width_m=24.0,
            track=MachineTrack(track_width_m=3.0, tire_width_m=0.35), overlap_m=0.0,
        )
        headland = dict(mode="follow_boundary", headland_mode=HEADLAND_MODE_FIDELITY)
        project = PrecisionProject(
            field=FieldGeometry(field_boundary=field, operational_boundary=field, crs_authid="EPSG:31982"),
            ab_line=ABLine(start=(0.0, 150.0), end=(600.0, 150.0)),
            planting=PrecisionOperation(
                operation_id="planting", machine=_operation(12.0).machine,
                headland=HeadlandLayout(pass_count=2, width_m=12.0, effective_spacing_m=12.0, **headland),
            ),
            spraying=PrecisionOperation(
                operation_id="spraying", machine=sprayer,
                headland=HeadlandLayout(pass_count=1, width_m=24.0, effective_spacing_m=24.0, **headland),
            ),
        )
        result = run_precision_lines(project)
        for plan in (result.boundary, result.spraying_boundary):
            self.assertEqual(plan.headland_mode, HEADLAND_MODE_FIDELITY)
            self.assertFalse(plan.headland_fallback, plan.headland_validation)
            self.assertTrue(all(line.pass_id for line in plan.headland_centerlines))
        bumps = [min(_ys_at_x(line, 300.0)) for line in result.boundary.headland_centerlines]
        self.assertAlmostEqual(bumps[0], 4.0 + 6.0, places=2)
        self.assertAlmostEqual(bumps[1], 4.0 + 18.0, places=2)


class FidelitySmoothingTest(unittest.TestCase):
    def test_smoothing_keeps_fidelity_detail_and_identity(self):
        field = _pivot(segments=2000)
        plan = _plan(field, 18.0, pass_count=1)
        self.assertGreater(len(plan.headland_centerlines[0].line_points()), 500)
        smoothed = smooth_boundary_plan(plan, PathSmoothingConfiguration(level=SmoothingLevel.LOW))
        line = smoothed.headland_centerlines[0]
        self.assertEqual(line.line_points(), plan.headland_centerlines[0].line_points())
        self.assertEqual(line.pass_id, "HEADLAND_01")
        self.assertEqual(smoothed.headland_mode, HEADLAND_MODE_FIDELITY)


if __name__ == "__main__":
    unittest.main()
