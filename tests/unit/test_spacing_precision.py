# -*- coding: utf-8 -*-
"""Precisao de espacamento: 20.000 m continua 20.000 m (passadas, bordaduras, ilhas)."""

from __future__ import annotations

import math
import unittest

import shapely
from shapely.geometry import Polygon

from plugin.fortsmart_precision.core.boundary_engine import build_boundary_plan, master_boundary_geometry
from plugin.fortsmart_precision.core.guidance_engine import traffic_pass_spacing_report
from plugin.fortsmart_precision.core.headland_fidelity_engine import prepare_boundary, progressive_offsets
from plugin.fortsmart_precision.core.line_geometry import (
    ARC_CHORD_TOLERANCE_M,
    densify_closed_ring,
    erosion_quad_segs,
    ring_without_duplicate_close,
    shrink_polygon_components,
)
from plugin.fortsmart_precision.core.parallel_pass_engine import (
    GEOMETRY_TOLERANCE_M,
    ParallelPassParams,
    generate_parallel_passes,
    straight_family_frame,
)
from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
from plugin.fortsmart_precision.core.spacing_validation import (
    AGRONOMIC_SPACING_TOLERANCE_M,
    HEADLAND_OFFSET_OUT_OF_TOLERANCE,
    PASS_SPACING_OUT_OF_TOLERANCE,
    distances_to_boundary,
    ring_samples,
    validate_offset_levels,
    validate_pass_spacing,
)
from plugin.fortsmart_precision.domain.headland_layout import (
    HEADLAND_MODE_FIDELITY,
    HEADLAND_MODE_LEGACY,
    HeadlandLayout,
)
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, PlanterMachine
from plugin.fortsmart_precision.domain.precision_project import (
    ABLine,
    FieldGeometry,
    PrecisionOperation,
    PrecisionProject,
)

E0, N0 = 650000.0, 8500000.0  # UTM SIRGAS 2000 / 21S, coordenadas grandes
SPACING = 20.0
TOL = AGRONOMIC_SPACING_TOLERANCE_M


def planter():
    # 40 linhas x 0,50 m = 20,00 m (parametro informado, nao inventado).
    return PlanterMachine(
        machine_id="p", name="p", row_count=40, row_spacing_m=0.5,
        track=MachineTrack(track_width_m=3.0, tire_width_m=0.4),
    )


def rotated_rect(width, height, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    pts = [(0, 0), (width, 0), (width, height), (0, height), (0, 0)]
    return [(E0 + x * c - y * s, N0 + x * s + y * c) for x, y in pts], (c, s)


def straight_passes(n_passes, deg=37.0):
    ring, (c, s) = rotated_rect(1500.0, n_passes * SPACING + 5.0, deg)
    a, b = (E0, N0), (E0 + 100.0 * c, N0 + 100.0 * s)
    params = ParallelPassParams(
        polygons=[(ring, [])], ab_start=a, ab_end=b, pass_spacing_m=SPACING,
        operation_width_m=SPACING, extension_m=0.0, master_path=(a, b),
    )
    passes = generate_parallel_passes(params)
    origin, _direction, normal = straight_family_frame(a, b, (a, b))
    report = validate_pass_spacing(
        ((p.source_candidate_index, p.line_points()) for p in passes), origin, normal, SPACING
    )
    return passes, report


def wiggly_field(n=400, radius=1000.0, island=False):
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        r = radius * (1 + 0.08 * math.sin(5 * t) + 0.02 * math.sin(11 * t))
        pts.append((E0 + r * math.cos(t), N0 + r * math.sin(t)))
    pts.append(pts[0])
    holes = []
    if island:
        holes = [[(E0 - 60, N0 - 40), (E0 + 60, N0 - 40), (E0 + 60, N0 + 40), (E0 - 60, N0 + 40), (E0 - 60, N0 - 40)]]
    return [(pts, holes)]


POLYGONAL = [([
    (E0, N0), (E0 + 1800, N0 + 40), (E0 + 1750, N0 + 1300), (E0 + 900, N0 + 1250), (E0 + 850, N0 + 700),
    (E0 + 400, N0 + 720), (E0 + 380, N0 + 1400), (E0 - 50, N0 + 1380), (E0, N0),
], [])]


def headland_plan(field, mode=HEADLAND_MODE_LEGACY, passes=3):
    op = PrecisionOperation(
        operation_id="planting", machine=planter(), extension_m=0.0,
        headland=HeadlandLayout(
            pass_count=passes, width_m=SPACING, mode="follow_boundary",
            headland_mode=mode, corner_mode="FOLLOW_BOUNDARY",
        ),
    )
    return build_boundary_plan(field, op, (E0, N0), (E0 + 100, N0))


def max_level_error(plan, field):
    """Erro medido nas linhas finais de cada B(k) contra o limite REAL."""
    by_pass = {}
    for line in plan.headland_centerlines:
        by_pass.setdefault(line.pass_no, []).extend(line.line_points())
    errors = {}
    for pass_no, points in sorted(by_pass.items()):
        expected = SPACING / 2.0 + pass_no * SPACING
        errors[pass_no] = max(abs(d - expected) for d in distances_to_boundary(points, field))
    return errors


class StraightFamilyTest(unittest.TestCase):
    def test_100_passes_absolute_positions(self):
        _passes, report = straight_passes(100)
        offsets = {abs(s.pass_index): abs(s.actual_offset_m) for s in report.samples}
        for index, expected in ((1, 20.0), (10, 200.0), (50, 1000.0), (100, 2000.0)):
            self.assertAlmostEqual(offsets[index], expected, delta=1e-6)
        self.assertGreaterEqual(len(report.samples), 100)
        self.assertTrue(report.ok, report.errors)
        self.assertLess(report.max_abs_error_m, 1e-6)

    def test_500_passes_do_not_drift(self):
        _passes, report = straight_passes(500)
        self.assertGreaterEqual(len(report.samples), 500)
        self.assertLess(report.max_abs_error_m, 1e-6)
        first, last = report.samples[0], report.samples[-1]
        self.assertLess(abs(first.spacing_error_m - last.spacing_error_m), 1e-6)

    def test_rectangle_min_mean_max_spacing(self):
        _passes, report = straight_passes(60, deg=0.0)
        for value in (report.min_spacing_m, report.mean_spacing_m, report.max_spacing_m):
            self.assertAlmostEqual(value, 20.0, delta=1e-6)

    def test_ab_at_37_degrees_large_utm(self):
        passes, report = straight_passes(80, deg=37.0)
        self.assertTrue(all(p.line_points()[0][0] > 600000 for p in passes))
        for value in (report.min_spacing_m, report.mean_spacing_m, report.max_spacing_m):
            self.assertAlmostEqual(value, 20.0, delta=1e-6)

    def test_straight_family_frame_none_for_curved_master(self):
        self.assertIsNone(straight_family_frame((0, 0), (100, 0), ((0, 0), (50, 20), (100, 0))))
        origin, direction, normal = straight_family_frame((0, 0), (10, 0), ((0, 0), (10, 0)), 2.0)
        self.assertEqual(direction, (1.0, 0.0))
        self.assertEqual(normal, (0.0, 1.0))
        self.assertAlmostEqual(origin[1], -2.0)


class SpacingValidatorTest(unittest.TestCase):
    def test_accumulated_drift_is_detected(self):
        # Simula o defeito antigo: cada passada derivada da anterior com +0,2 mm.
        passes = [(i, [(0.0, i * (SPACING + 0.0002)), (100.0, i * (SPACING + 0.0002))]) for i in range(101)]
        report = validate_pass_spacing(passes, (0.0, 0.0), (0.0, 1.0), SPACING)
        self.assertFalse(report.ok)
        self.assertEqual(report.code, PASS_SPACING_OUT_OF_TOLERANCE)
        self.assertAlmostEqual(report.max_abs_error_m, 0.02, places=6)
        sample = report.samples[-1]
        self.assertEqual(sample.as_dict()["pass_index"], 100)
        self.assertAlmostEqual(sample.expected_offset_m, 2000.0)
        self.assertAlmostEqual(sample.actual_offset_m, 2000.02, places=6)

    def test_tolerances_are_separate(self):
        self.assertEqual(AGRONOMIC_SPACING_TOLERANCE_M, 0.01)
        self.assertIsNot(AGRONOMIC_SPACING_TOLERANCE_M, GEOMETRY_TOLERANCE_M)
        passes = [(0, [(0.0, 0.0)]), (1, [(0.0, 20.009)])]
        self.assertTrue(validate_pass_spacing(passes, (0.0, 0.0), (0.0, 1.0), SPACING).ok)
        passes = [(0, [(0.0, 0.0)]), (1, [(0.0, 20.011)])]
        self.assertFalse(validate_pass_spacing(passes, (0.0, 0.0), (0.0, 1.0), SPACING).ok)

    def test_offset_levels_detect_wrong_headland(self):
        field = [([(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)], [])]
        good = [(10, 10), (90, 10), (90, 90), (10, 90), (10, 10)]
        bad = [(10, 10), (90, 10), (90, 90), (10, 90.5), (10, 10)]
        self.assertTrue(validate_offset_levels(field, [(0, 10.0, [good])]).ok)
        report = validate_offset_levels(field, [(0, 10.0, [bad])])
        self.assertEqual(report.code, HEADLAND_OFFSET_OUT_OF_TOLERANCE)
        self.assertAlmostEqual(report.max_abs_error_m, 0.5, places=6)
        self.assertIn("B1", report.summary_lines()[1])

    def test_ring_samples_include_midpoints(self):
        samples = ring_samples([(0, 0), (2, 0), (2, 2), (0, 0)])
        self.assertIn((1.0, 0.0), samples)
        self.assertEqual(len(samples), 6)


class GeometryHelpersTest(unittest.TestCase):
    def test_erosion_quad_segs_bounds_chord_sag(self):
        self.assertEqual(erosion_quad_segs(2.0), 24)
        for distance in (5.0, 10.0, 30.0, 60.0, 200.0):
            quad = erosion_quad_segs(distance)
            worst_chord = 1.5 * (math.pi / 2.0) / quad
            sag = distance * (1.0 - math.cos(worst_chord / 2.0))
            self.assertLessEqual(sag, ARC_CHORD_TOLERANCE_M + 1e-12, distance)

    def test_densify_preserves_original_vertices(self):
        ring = [(math.cos(2 * math.pi * i / 1000) * 3000, math.sin(2 * math.pi * i / 1000) * 3000) for i in range(1000)]
        ring.append(ring[0])
        kept = densify_closed_ring(ring, max_edge_m=2.0, max_vertices=720, preserve_vertices=True)
        self.assertEqual(ring_without_duplicate_close(kept), ring_without_duplicate_close(ring))
        square = [(0, 0), (5000, 0), (5000, 5000), (0, 5000), (0, 0)]
        dense = ring_without_duplicate_close(
            densify_closed_ring(square, max_edge_m=2.0, max_vertices=720, preserve_vertices=True)
        )
        self.assertLessEqual(len(dense), 720)
        for corner in square[:-1]:
            self.assertIn(corner, dense)

    def test_master_geometry_keeps_real_corners_in_large_field(self):
        master = master_boundary_geometry(POLYGONAL, width_m=SPACING)
        dense = ring_without_duplicate_close(master[0][0])
        for corner in ring_without_duplicate_close(POLYGONAL[0][0]):
            self.assertIn(corner, dense)
        self.assertAlmostEqual(Polygon(dense).area, Polygon(POLYGONAL[0][0]).area, delta=1e-3)

    def test_fidelity_offsets_are_absolute_from_base(self):
        boundary = prepare_boundary(wiggly_field())
        passes = progressive_offsets(boundary, [10.0, 30.0, 50.0])
        for item in passes:
            direct = boundary.buffer(-item.offset_m, quad_segs=erosion_quad_segs(item.offset_m), join_style="round")
            self.assertLess(item.geometry.symmetric_difference(direct).area, 1.0)
            points = [p for ring in item.rings for p in ring_samples(ring)]
            dist = shapely.distance(shapely.points(points), boundary.boundary)
            self.assertLessEqual(float(abs(dist - item.offset_m).max()), TOL)


class HeadlandOffsetTest(unittest.TestCase):
    def test_headland_b1_b2_b3_from_base_polygonal_large_field(self):
        plan = headland_plan(POLYGONAL)
        report = plan.offset_validation["headland"]
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual([lvl["expected_offset_m"] for lvl in report["levels"]], [10.0, 30.0, 50.0])
        self.assertLessEqual(report["max_abs_error_m"], TOL)
        errors = max_level_error(plan, POLYGONAL)
        self.assertLessEqual(max(errors.values()), TOL, errors)

    def test_headland_wiggly_field_both_modes(self):
        field = wiggly_field()
        for mode in (HEADLAND_MODE_LEGACY, HEADLAND_MODE_FIDELITY):
            plan = headland_plan(field, mode)
            self.assertFalse(plan.headland_fallback)
            errors = max_level_error(plan, field)
            self.assertLessEqual(max(errors.values()), TOL, (mode, errors))
            self.assertTrue(plan.offset_validation["inner_limit"]["ok"])

    def test_inner_limit_at_exact_reserved_width(self):
        plan = headland_plan(POLYGONAL)
        inner = plan.offset_validation["inner_limit"]
        self.assertEqual(inner["levels"][0]["expected_offset_m"], 60.0)
        self.assertLessEqual(inner["max_abs_error_m"], TOL)


class IslandTest(unittest.TestCase):
    def test_island_inner_limit_has_no_mitre_error(self):
        field = wiggly_field(island=True)
        plan = headland_plan(field)
        inner = plan.offset_validation["inner_limit"]
        self.assertTrue(inner["ok"], inner["errors"])
        self.assertLessEqual(inner["max_abs_error_m"], TOL)

    def test_island_offsets_are_absolute(self):
        field = wiggly_field(island=True)
        island = field[0][1][0]
        for distance in (10.0, 30.0, 50.0):
            (_outer, holes), = shrink_polygon_components(field[0], distance)
            self.assertEqual(len(holes), 1)
            dist = distances_to_boundary(ring_samples(holes[0]), [(island, [])])
            self.assertLessEqual(max(abs(d - distance) for d in dist), TOL, distance)


class PipelineSpacingTest(unittest.TestCase):
    def _project(self, pass_count=3):
        ring, (c, s) = rotated_rect(1200.0, 1195.0, 37.0)
        field = [(ring, [])]
        op = PrecisionOperation(
            operation_id="planting", machine=planter(), extension_m=0.0,
            headland=HeadlandLayout(pass_count=pass_count, width_m=SPACING, mode="follow_boundary"),
        )
        return PrecisionProject(
            field=FieldGeometry(field_boundary=field, operational_boundary=field, crs_authid="EPSG:31981"),
            ab_line=ABLine(start=(E0, N0), end=(E0 + 100.0 * c, N0 + 100.0 * s)),
            planting=op,
        )

    def test_planting_limits_and_headlands_pass_validation(self):
        project = self._project()
        result = run_precision_lines(project)
        self.assertTrue(result.validation.ok, [e.message for e in result.validation.errors])
        checks = " | ".join(result.validation.checks)
        self.assertIn("Espacamento plantio", checks)
        self.assertIn("Offset bordadura", checks)
        self.assertIn("Offset limite_interno", checks)
        report = traffic_pass_spacing_report(result.planting_passes, project.effective_ab_line(), project.planting)
        self.assertLess(report.max_abs_error_m, 1e-6)
        for value in (report.min_spacing_m, report.mean_spacing_m, report.max_spacing_m):
            self.assertAlmostEqual(value, 20.0, delta=1e-6)

    def test_geographic_crs_is_rejected(self):
        project = self._project()
        bad = PrecisionProject(
            field=FieldGeometry(
                field_boundary=project.field.field_boundary,
                operational_boundary=project.field.operational_boundary,
                crs_authid="EPSG:4674",
            ),
            ab_line=project.ab_line,
            planting=project.planting,
        )
        result = run_precision_lines(bad)
        self.assertFalse(result.validation.ok)
        self.assertTrue(any("CRS geografico" in e.message for e in result.validation.errors))


if __name__ == "__main__":
    unittest.main()
