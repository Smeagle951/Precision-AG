# -*- coding: utf-8 -*-
"""Polygon -> MultiPolygon: estreitamento separa o miolo e nenhuma parte some."""

from __future__ import annotations

import math
import unittest

from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Point, Polygon

from plugin.fortsmart_precision.core.boundary_engine import build_boundary_plan
from plugin.fortsmart_precision.core.line_geometry import (
    erosion_quad_segs,
    multipolygon_area,
    point_in_multipolygon,
    ring_signed_area,
    shrink_multipolygon,
    shrink_polygon,
    shrink_polygon_components,
)
from plugin.fortsmart_precision.core.parallel_pass_engine import pass_segment_layout
from plugin.fortsmart_precision.core.polygon_components import (
    BORDER_COMPONENT_NOT_COVERED,
    MULTIPART_AREA_LOSS,
    PLANTING_COMPONENT_NOT_COVERED,
    UNEXPECTED_MULTIPART_COMPONENT_LOSS,
    ComponentLossError,
    component_debug_report,
    extract_line_components,
    extract_polygon_components,
    validate_component_area_conservation,
    validate_component_coverage,
)
from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
from plugin.fortsmart_precision.core.spacing_validation import validate_offset_levels
from plugin.fortsmart_precision.domain.boundary_areas import build_inner_and_headland
from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, PlanterMachine
from plugin.fortsmart_precision.domain.precision_project import (
    ABLine,
    FieldGeometry,
    PrecisionOperation,
    PrecisionProject,
)

WIDTH = 9.0
# [ GRANDE ]--corredor de 12 m--[ GRANDE ]
DUMBBELL_RING = [
    (0, 0), (200, 0), (200, 94), (300, 94), (300, 0), (500, 0), (500, 200),
    (300, 200), (300, 106), (200, 106), (200, 200), (0, 200), (0, 0),
]
DUMBBELL = [(DUMBBELL_RING, [])]
U_SHAPE = [([(0, 0), (300, 0), (300, 300), (200, 300), (200, 100), (100, 100), (100, 300), (0, 300), (0, 0)], [])]
C_SHAPE = [([(0, 0), (300, 0), (300, 80), (100, 80), (100, 220), (300, 220), (300, 300), (0, 300), (0, 0)], [])]


def planter():
    return PlanterMachine(
        machine_id="p", name="p", row_count=18, row_spacing_m=0.5,
        track=MachineTrack(track_width_m=2.0, tire_width_m=0.3),
    )


def operation(pass_count=1):
    return PrecisionOperation(
        operation_id="planting",
        machine=planter(),
        extension_m=0.0,
        headland=HeadlandLayout(pass_count=pass_count, width_m=WIDTH, mode="follow_boundary"),
    )


def run(field, ab, pass_count=1):
    project = PrecisionProject(
        field=FieldGeometry(field_boundary=field, operational_boundary=field, crs_authid="EPSG:31982"),
        ab_line=ABLine(start=ab[0], end=ab[1]),
        planting=operation(pass_count),
    )
    return run_precision_lines(project)


def passes_in(passes, polygon):
    shape = Polygon(polygon)
    return [p for p in passes if LineString(p.line_points()).intersects(shape)]


class ExtractionTest(unittest.TestCase):
    def test_extract_polygon_components_recursive(self):
        a, b = Polygon([(0, 0), (1, 0), (1, 1)]), Polygon([(5, 5), (6, 5), (6, 6)])
        nested = GeometryCollection([Point(0, 0), MultiPolygon([a, b]), LineString([(0, 0), (1, 1)])])
        self.assertEqual(len(extract_polygon_components(nested)), 2)
        self.assertEqual(extract_polygon_components(a), [a])
        self.assertEqual(extract_polygon_components(None), [])

    def test_extract_line_components(self):
        parts = extract_line_components(GeometryCollection([LineString([(0, 0), (3, 0)]), Point(1, 1)]))
        self.assertEqual(len(parts), 1)

    def test_area_conservation_check(self):
        self.assertAlmostEqual(validate_component_area_conservation(100.0, [60.0, 40.0]), 100.0)
        with self.assertRaises(ComponentLossError) as ctx:
            validate_component_area_conservation(108.4e4, [62.0e4])
        self.assertEqual(ctx.exception.code, MULTIPART_AREA_LOSS)

    def test_38_component_areas_sum_to_buffer_area(self):
        components = shrink_polygon_components(DUMBBELL[0], 9.0)
        reference = Polygon(DUMBBELL_RING).buffer(-9.0, quad_segs=erosion_quad_segs(9.0), join_style=1)
        self.assertEqual(len(components), 2)
        self.assertAlmostEqual(multipolygon_area(components), reference.area, delta=0.01)
        self.assertTrue(all(ring_signed_area(ring) > 0 for ring, _h in components))

    def test_single_component_matches_shrink_polygon_within_chord_tolerance(self):
        # Mesma forma; so os arcos tem mais segmentos (flecha <= ARC_CHORD_TOLERANCE_M).
        for polygon in (U_SHAPE[0], C_SHAPE[0]):
            (outer, holes), = shrink_polygon_components(polygon, 9.0)
            legacy = shrink_polygon(polygon, 9.0)
            self.assertEqual(holes, [])
            distance = Polygon(outer).exterior.hausdorff_distance(Polygon(legacy[0]).exterior)
            self.assertLessEqual(distance, 9.0 * (1 - math.cos(math.pi / 96)) + 1e-9)

    def test_island_is_expanded_with_round_joins_at_exact_distance(self):
        island = [(100, 100), (120, 100), (120, 120), (100, 120), (100, 100)]
        polygon = ([(0, 0), (400, 0), (400, 240), (0, 240), (0, 0)], [island])
        (outer, holes), = shrink_polygon_components(polygon, 9.0)
        self.assertEqual(outer, shrink_polygon((polygon[0], []), 9.0)[0])
        self.assertEqual(len(holes), 1)
        report = validate_offset_levels([([*island], [])], [(0, 9.0, holes)])
        self.assertLessEqual(report.max_abs_error_m, 0.005)

    def test_holes_follow_their_component(self):
        hole = [(40, 40), (60, 40), (60, 60), (40, 60), (40, 40)]
        components = shrink_polygon_components((DUMBBELL_RING, [hole]), 9.0)
        owners = [i for i, (_ring, holes) in enumerate(components) if holes]
        self.assertEqual(len(owners), 1)
        self.assertTrue(point_in_multipolygon((30.0, 100.0), [components[owners[0]]]))


class DumbbellTest(unittest.TestCase):
    def test_34_dumbbell_inner_is_two_components_and_both_get_passes(self):
        result = run(DUMBBELL, ((10, 10), (10, 50)))
        inner = result.boundary.inner_boundary
        self.assertEqual(len(inner), 2)
        left = [(0, 0), (200, 0), (200, 200), (0, 200)]
        right = [(300, 0), (500, 0), (500, 200), (300, 200)]
        self.assertGreater(len(passes_in(result.planting_passes, left)), 15)
        self.assertGreater(len(passes_in(result.planting_passes, right)), 15)
        coverage = validate_component_coverage(
            result.planting_passes, inner, implement_width_m=WIDTH,
            border_lines=[c.line_points() for c in result.boundary.headland_centerlines],
            border_reach_m=result.boundary.reserved_width_m,
        )
        self.assertTrue(coverage.ok, coverage.codes)
        self.assertTrue(all(item.pass_count > 0 for item in coverage.components))

    def test_inner_area_matches_geos(self):
        areas = build_inner_and_headland(DUMBBELL, 9.0)
        reference = Polygon(DUMBBELL_RING).buffer(-9.0, quad_segs=erosion_quad_segs(9.0), join_style=1).area
        self.assertAlmostEqual(multipolygon_area(areas.inner_work_area), reference, delta=0.01)
        self.assertEqual(len(areas.headland_area[0][1]), 2)

    def test_39_headland_offset_with_two_components(self):
        plan = build_boundary_plan(DUMBBELL, operation(pass_count=2), (10, 10), (10, 50))
        b2 = [c for c in plan.headland_centerlines if c.pass_no == 1]
        self.assertEqual(len(b2), 2)
        xs = sorted(min(p[0] for p in c.line_points()) for c in b2)
        self.assertLess(xs[0], 50)
        self.assertGreater(xs[1], 300)
        layout = dict(zip(map(id, plan.headland_centerlines), pass_segment_layout(plan.headland_centerlines)))
        self.assertEqual(sorted(layout[id(c)] for c in b2), [(0, 2), (1, 2)])

    def test_40_b3_keeps_components_after_split(self):
        plan = build_boundary_plan(DUMBBELL, operation(pass_count=3), (10, 10), (10, 50))
        for pass_no in (1, 2):
            self.assertEqual(len([c for c in plan.headland_centerlines if c.pass_no == pass_no]), 2)
        self.assertEqual(len(plan.inner_boundary), 2)

    def test_42_debug_report_lists_every_part(self):
        result = run(DUMBBELL, ((10, 10), (10, 50)))
        coverage = validate_component_coverage(result.planting_passes, result.boundary.inner_boundary, implement_width_m=WIDTH)
        lines = component_debug_report("TL-13", DUMBBELL, result.boundary.inner_boundary, coverage,
                                       logical_passes=10, features=12)
        self.assertIn("Inner buffer: type=MultiPolygon parts=2", lines[2])
        self.assertTrue(lines[3].startswith("Part 0:"))
        self.assertTrue(lines[4].startswith("Part 1:"))


class ShapesTest(unittest.TestCase):
    def test_35_u_passes_cross_both_arms(self):
        result = run(U_SHAPE, ((20, 20), (60, 20)))
        arms = [items for items in _by_pass(result.planting_passes).values() if len(items) == 2]
        self.assertGreater(len(arms), 10)

    def test_36_c_shape_no_outer_part_lost(self):
        result = run(C_SHAPE, ((20, 20), (20, 60)))
        self.assertGreater(len(passes_in(result.planting_passes, [(100, 0), (300, 0), (300, 80), (100, 80)])), 10)
        self.assertGreater(len(passes_in(result.planting_passes, [(100, 220), (300, 220), (300, 300), (100, 300)])), 10)

    def test_37_explicit_multipolygon_input(self):
        field = [
            ([(0, 0), (200, 0), (200, 200), (0, 200), (0, 0)], []),
            ([(300, 0), (500, 0), (500, 200), (300, 200), (300, 0)], []),
        ]
        shrunk = shrink_multipolygon(field, 9.0)
        self.assertEqual(len(shrunk), 2)
        result = run(field, ((10, 10), (10, 50)))
        self.assertEqual(len(result.boundary.inner_boundary), 2)
        self.assertGreater(len(passes_in(result.planting_passes, [(300, 0), (500, 0), (500, 200), (300, 200)])), 15)

    def test_41_component_without_passes_is_flagged(self):
        inner = build_inner_and_headland(DUMBBELL, 9.0).inner_work_area
        result = run(DUMBBELL, ((10, 10), (10, 50)))
        left_only = [p for p in result.planting_passes if p.line_points()[0][0] < 250]
        report = validate_component_coverage(left_only, inner, implement_width_m=WIDTH, border_lines=[((0, -50), (10, -50))])
        self.assertIn(PLANTING_COMPONENT_NOT_COVERED, " ".join(report.codes))
        self.assertIn(BORDER_COMPONENT_NOT_COVERED, " ".join(report.codes))
        micro = [([(0, 0), (4, 0), (4, 4), (0, 4), (0, 0)], [])]
        self.assertTrue(validate_component_coverage([], micro, implement_width_m=WIDTH).ok)

    def test_43_component_loss_guard_code(self):
        self.assertEqual(UNEXPECTED_MULTIPART_COMPONENT_LOSS, "UNEXPECTED_MULTIPART_COMPONENT_LOSS")
        from plugin.fortsmart_precision.domain import boundary_areas

        original = boundary_areas.shrink_polygon_components
        try:
            boundary_areas.shrink_polygon_components = lambda polygon, d: original(polygon, d)[:1]
            with self.assertRaises(ComponentLossError) as ctx:
                build_inner_and_headland(DUMBBELL, 9.0)
            self.assertEqual(ctx.exception.code, UNEXPECTED_MULTIPART_COMPONENT_LOSS)
        finally:
            boundary_areas.shrink_polygon_components = original


def _by_pass(passes):
    groups: dict[int, list] = {}
    for item in passes:
        groups.setdefault(item.pass_no, []).append(item)
    return groups


if __name__ == "__main__":
    unittest.main()
