# -*- coding: utf-8 -*-
"""Cobertura completa em talhao concavo — gerador principal de passadas retas."""

from __future__ import annotations

import time
import unittest
from math import ceil, floor

from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point as ShapelyPoint

from plugin.fortsmart_precision.core.ab_direction import resolve_ab_direction_end
from plugin.fortsmart_precision.core.guidance_engine import generate_traffic_passes
from plugin.fortsmart_precision.core.line_geometry import (
    Segment,
    add,
    bbox_corners,
    build_processing_boundary,
    clip_infinite_line_to_multipolygon,
    mul,
    multipolygon_bbox,
    normalize,
    perpendicular_left,
    point_in_multipolygon,
    signed_projection,
    sub,
)
from plugin.fortsmart_precision.core.parallel_pass_engine import (
    GENERATOR_INCOMPLETE_FIELD_COVERAGE,
    ParallelPassParams,
    build_full_candidate_line,
    compute_polygon_projection_range,
    generate_parallel_passes,
    generate_parallel_passes_with_stats,
    generation_margin,
    merge_continuous_segments,
    pass_segment_layout,
    source_candidate_index_for,
)
from plugin.fortsmart_precision.core.pass_family_coverage import (
    default_coverage_gap_tolerance,
    extract_valid_line_parts,
    validate_family_coverage,
)
from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, PlanterMachine
from plugin.fortsmart_precision.domain.precision_project import (
    ABLine,
    FieldGeometry,
    PrecisionOperation,
    PrecisionProject,
)

WIDTH = 9.0


def field(*outer):
    ring = list(outer)
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return [(ring, [])]


RECTANGLE = field((0, 0), (400, 0), (400, 240), (0, 240))
U_SHAPE = field((0, 0), (300, 0), (300, 300), (200, 300), (200, 100), (100, 100), (100, 300), (0, 300))
C_SHAPE = field((0, 0), (300, 0), (300, 80), (100, 80), (100, 220), (300, 220), (300, 300), (0, 300))
# Reentrancia pela lateral direita: as verticais da direita sao cortadas em duas.
LATERAL_NOTCH = field(
    (0, 0), (400, 0), (400, 120), (250, 120), (250, 180), (400, 180), (400, 300), (0, 300)
)
COMB = field(
    (0, 0), (500, 0), (500, 300), (400, 300), (400, 100), (300, 100), (300, 300),
    (200, 300), (200, 100), (100, 100), (100, 300), (0, 300),
)


def params(polygons, ab, *, spacing=WIDTH, width=WIDTH, extension=0.0, clip=None, min_length=0.0):
    return ParallelPassParams(
        polygons=polygons,
        ab_start=ab[0],
        ab_end=ab[1],
        pass_spacing_m=spacing,
        operation_width_m=width,
        extension_m=extension,
        clip_boundary=clip,
        min_length_m=min_length,
    )


def coverage(passes, polygons, *, stats=None, width=WIDTH, spacing=WIDTH):
    return validate_family_coverage(
        passes, polygons, implement_width_m=width, pass_spacing_m=spacing, stats=stats, label="teste"
    )


def by_pass(passes):
    groups: dict[int, list] = {}
    for item in passes:
        groups.setdefault(item.pass_no, []).append(item)
    return groups


def legacy_straight(p: ParallelPassParams):
    """Algoritmo anterior (bbox + numeracao por posicao) para regressao exata."""
    end = resolve_ab_direction_end(p.ab_start, p.ab_end, p.resolved_master_path())
    direction = normalize(sub(end, p.ab_start))
    normal = perpendicular_left(direction)
    origin = add(p.ab_start, mul(normal, -p.ab_offset_right_m))
    coverage_area = p.coverage_polygons()
    processing = p.processing_polygons()
    corners = [signed_projection(c, origin, normal) for c in bbox_corners(multipolygon_bbox(coverage_area))]
    start = floor((min(corners) - p.pass_spacing_m * 2) / p.pass_spacing_m)
    stop = ceil((max(corners) + p.pass_spacing_m * 2) / p.pass_spacing_m)
    raw = []
    for index in range(start, stop + 1):
        offset = index * p.pass_spacing_m
        base = add(origin, mul(normal, offset))
        if not clip_infinite_line_to_multipolygon(base, direction, coverage_area):
            continue
        for seg in clip_infinite_line_to_multipolygon(base, direction, processing):
            if seg.length >= p.min_length_m:
                raw.append((offset, seg))
    raw.sort(key=lambda item: (item[0], item[1].start[0], item[1].start[1]))
    zero = min(range(len(raw)), key=lambda i: (abs(raw[i][0]), i))
    return [(p.first_pass_no + i - zero, -off, seg.start, seg.end) for i, (off, seg) in enumerate(raw)]


def planter(width=WIDTH):
    return PlanterMachine(
        machine_id="p",
        name="p",
        row_count=int(width / 0.5),
        row_spacing_m=0.5,
        track=MachineTrack(track_width_m=2.0, tire_width_m=0.3),
    )


class HelperFunctionsTest(unittest.TestCase):
    def test_projection_range_uses_every_vertex_including_holes(self):
        hole_field = [([(0, 0), (100, 0), (100, 50), (0, 50), (0, 0)], [[(10, 10), (20, 10), (20, 60), (10, 10)]])]
        lo, hi = compute_polygon_projection_range(hole_field, (0.0, 0.0), (0.0, 1.0))
        self.assertEqual((lo, hi), (0.0, 60.0))

    def test_generation_margin_takes_largest_term(self):
        self.assertEqual(generation_margin(36.0, 9.0), 36.0)
        self.assertEqual(generation_margin(9.0, 9.0), 18.0)
        self.assertAlmostEqual(generation_margin(0.0, 0.0, 0.5), 5.0)

    def test_full_candidate_line_crosses_whole_bbox(self):
        bbox = (1000.0, 2000.0, 1400.0, 2300.0)
        seg = build_full_candidate_line((0.0, 2100.0), (1.0, 0.0), bbox)
        self.assertLess(seg.start[0], bbox[0])
        self.assertGreater(seg.end[0], bbox[2])
        self.assertAlmostEqual(seg.length, 4.0 * 500.0)
        self.assertAlmostEqual(seg.start[1], 2100.0)

    def test_merge_joins_only_touching_parts(self):
        parts = [
            Segment((0.0, 0.0), (100.0, 0.0)),
            Segment((100.0, 0.0), (200.0, 0.0)),
            Segment((250.0, 0.0), (300.0, 0.0)),
        ]
        merged = merge_continuous_segments(parts)
        self.assertEqual(merged, [Segment((0.0, 0.0), (200.0, 0.0)), Segment((250.0, 0.0), (300.0, 0.0))])

    def test_segment_layout_groups_by_pass_and_orders_longitudinally(self):
        class Item:
            def __init__(self, no, start, end):
                self.pass_no, self._pts = no, (start, end)

            def line_points(self):
                return self._pts

        items = [Item(5, (200, 0), (300, 0)), Item(4, (0, -9), (300, -9)), Item(5, (0, 0), (100, 0))]
        self.assertEqual(pass_segment_layout(items), [(1, 2), (0, 1), (0, 2)])

    def test_source_candidate_index_falls_back_to_offset(self):
        class Item:
            source_candidate_index = None
            spacing_m = 9.0
            offset_m = -27.0

        self.assertEqual(source_candidate_index_for(Item()), 3)
        Item.source_candidate_index = 7
        self.assertEqual(source_candidate_index_for(Item()), 7)

    def test_extract_valid_line_parts_recursive(self):
        geometry = GeometryCollection(
            [
                ShapelyPoint(0, 0),
                LineString([(0, 0), (10, 0)]),
                GeometryCollection([MultiLineString([[(20, 0), (30, 0)], [(40, 0), (40.001, 0)]])]),
            ]
        )
        parts = extract_valid_line_parts(geometry)
        self.assertEqual([round(p.length, 3) for p in parts], [10.0, 10.0])
        self.assertEqual(extract_valid_line_parts(LineString()), [])
        self.assertEqual(extract_valid_line_parts(None), [])

    def test_default_gap_tolerance_is_half_inherent_strip(self):
        self.assertAlmostEqual(default_coverage_gap_tolerance(9.0, 9.0), 2.25 + 0.05)


class ConcaveCoverageTest(unittest.TestCase):
    def test_38_rectangle_identical_to_previous_generator(self):
        cases = [
            (RECTANGLE, ((0.0, 120.0), (400.0, 120.0)), 0.0),
            (RECTANGLE, ((10.0, 0.0), (10.0, 40.0)), 10.0),
            (RECTANGLE, ((50.0, 30.0), (90.0, 70.0)), 5.0),
            (field((0, 0), (400, 0), (430, 260), (20, 240)), ((0.0, 5.0), (60.0, 9.0)), 10.0),
        ]
        for polygons, ab, extension in cases:
            p = params(polygons, ab, extension=extension, spacing=12.0, width=12.0)
            new = [(x.pass_no, x.offset_m, x.clipped_segment.start, x.clipped_segment.end) for x in generate_parallel_passes(p)]
            self.assertEqual(new, legacy_straight(p))
            self.assertTrue(all(x.segment_count == 1 for x in generate_parallel_passes(p)))

    def test_39_u_shape_keeps_both_arms_in_one_pass(self):
        passes, stats = generate_parallel_passes_with_stats(params(U_SHAPE, ((0, 10), (60, 10))))
        groups = by_pass(passes)
        arms = [items for items in groups.values() if len(items) == 2]
        self.assertGreater(len(arms), 15)
        for items in arms:
            self.assertEqual([i.segment_index for i in items], [0, 1])
            self.assertLess(items[0].clipped_segment.end[0], items[1].clipped_segment.start[0])
        report = coverage(passes, U_SHAPE, stats=stats)
        self.assertTrue(report.ok, report.as_dict())
        self.assertEqual(report.missing_candidates, 0)

    def test_40_c_shape_covers_both_arms(self):
        passes, stats = generate_parallel_passes_with_stats(params(C_SHAPE, ((10, 0), (10, 40))))
        for x, y in ((250.0, 40.0), (250.0, 260.0), (150.0, 30.0), (150.0, 270.0)):
            self.assertTrue(
                any(abs(p.clipped_segment.start[0] - x) <= WIDTH / 2 and
                    min(p.clipped_segment.start[1], p.clipped_segment.end[1]) <= y <=
                    max(p.clipped_segment.start[1], p.clipped_segment.end[1]) for p in passes),
                (x, y),
            )
        self.assertTrue(coverage(passes, C_SHAPE, stats=stats).ok)

    def test_41_lateral_notch_upper_region_covered(self):
        passes, stats = generate_parallel_passes_with_stats(params(LATERAL_NOTCH, ((10, 0), (10, 40))))
        upper = [p for p in passes if p.clipped_segment.start[0] > 250 and p.clipped_segment.start[1] >= 179]
        self.assertGreater(len(upper), 10)
        for item in upper:
            self.assertEqual(item.segment_index, 1)
            self.assertEqual(item.segment_count, 2)
            self.assertAlmostEqual(item.clipped_segment.end[1], 300.0)
        report = coverage(passes, LATERAL_NOTCH, stats=stats)
        self.assertTrue(report.ok, report.as_dict())
        self.assertGreater(report.multipart_passes, 10)
        self.assertEqual(report.logical_passes, report.candidates_valid)

    def test_42_empty_candidate_between_valid_passes_does_not_stop(self):
        two_blocks = field((0, -5), (300, -5), (300, 102), (0, 102)) + field((0, 118), (300, 118), (300, 200), (0, 200))
        passes, stats = generate_parallel_passes_with_stats(params(two_blocks, ((0, 0), (50, 0)), spacing=10.0, width=10.0))
        numbers = sorted(by_pass(passes))
        self.assertIn(10, numbers)
        self.assertNotIn(11, numbers)
        self.assertIn(12, numbers)
        self.assertGreaterEqual(max(numbers), 19)
        self.assertGreaterEqual(stats.candidates_empty, 1)

    def test_43_three_parts_same_pass_number(self):
        passes = generate_parallel_passes(params(COMB, ((0, 5), (50, 5)), spacing=10.0, width=10.0))
        line = [p for p in passes if abs(p.clipped_segment.start[1] - 205.0) < 1e-6]
        self.assertEqual(len(line), 3)
        self.assertEqual({p.pass_no for p in line}, {20})
        self.assertEqual([p.segment_index for p in line], [0, 1, 2])
        self.assertEqual({p.segment_count for p in line}, {3})
        self.assertEqual({p.source_candidate_index for p in line}, {20})
        self.assertEqual([p.clipped_segment.start[0] for p in line], [0.0, 200.0, 400.0])
        self.assertTrue(all(p.clipped_segment.end[0] > p.clipped_segment.start[0] for p in line))
        neighbours = by_pass(passes)
        self.assertIn(21, neighbours)

    def test_traffic_passes_keep_direction_inside_candidate(self):
        op = PrecisionOperation(operation_id="planting", machine=planter(10.0), extension_m=0.0)
        traffic = generate_traffic_passes(COMB, ABLine(start=(0, 5), end=(50, 5)), op)
        for items in by_pass(traffic).values():
            self.assertEqual(len({t.direction for t in items}), 1)
        directions = {no: items[0].direction for no, items in by_pass(traffic).items()}
        self.assertNotEqual(directions[20], directions[21])

    def test_44_short_ab_covers_whole_field(self):
        passes, stats = generate_parallel_passes_with_stats(params(LATERAL_NOTCH, ((5, 5), (5, 8))))
        self.assertTrue(coverage(passes, LATERAL_NOTCH, stats=stats).ok)
        self.assertAlmostEqual(max(p.clipped_segment.end[1] for p in passes), 300.0)

    def test_45_off_center_ab_outside_field(self):
        passes, stats = generate_parallel_passes_with_stats(params(U_SHAPE, ((-500, 900), (-440, 900))))
        report = coverage(passes, U_SHAPE, stats=stats)
        self.assertTrue(report.ok, report.as_dict())
        groups = by_pass(passes)
        nearest = max(passes, key=lambda p: p.clipped_segment.start[1])
        self.assertEqual(nearest.pass_no, 0)
        self.assertEqual(sorted(groups), list(range(min(groups), 1)))

    def test_46_large_field_with_notch(self):
        big = field((0, 0), (3000, 0), (3000, 900), (1800, 900), (1800, 1300), (3000, 1300), (3000, 2000), (0, 2000))
        start = time.perf_counter()
        passes, stats = generate_parallel_passes_with_stats(params(big, ((0, 10), (0, 50)), spacing=18.0, width=18.0))
        report = coverage(passes, big, stats=stats, width=18.0, spacing=18.0)
        self.assertLess(time.perf_counter() - start, 20.0)
        self.assertTrue(report.ok, report.as_dict())
        self.assertGreater(report.multipart_passes, 50)

    def test_47_multi_field_only_tl13_generated(self):
        tl13 = field((0, 0), (300, 0), (300, 300), (200, 300), (200, 100), (100, 100), (100, 300), (0, 300))
        tl12 = field((400, 0), (700, 0), (700, 300), (400, 300))
        passes = generate_parallel_passes(params(tl13, ((0, 10), (60, 10)), extension=5.0, clip=tl13))
        processing = build_processing_boundary(tl13, 5.0)
        for item in passes:
            for point in (item.clipped_segment.start, item.clipped_segment.end):
                self.assertLessEqual(point[0], 305.0 + 1e-6)
            mid = ((item.clipped_segment.start[0] + item.clipped_segment.end[0]) / 2, item.clipped_segment.start[1])
            self.assertTrue(point_in_multipolygon(mid, processing))
            self.assertFalse(point_in_multipolygon(mid, tl12))

    def test_48_headland_reduced_allowed_area(self):
        op = PrecisionOperation(
            operation_id="planting",
            machine=planter(),
            extension_m=0.0,
            headland=HeadlandLayout(pass_count=1, width_m=WIDTH, mode="follow_boundary"),
        )
        project = PrecisionProject(
            field=FieldGeometry(field_boundary=LATERAL_NOTCH, operational_boundary=LATERAL_NOTCH, crs_authid="EPSG:31982"),
            ab_line=ABLine(start=(20, 20), end=(20, 60)),
            planting=op,
        )
        result = run_precision_lines(project)
        inner = result.boundary.inner_boundary
        self.assertTrue(inner)
        report = coverage(result.planting_passes, inner)
        self.assertTrue(report.ok, report.as_dict())
        self.assertGreater(report.multipart_passes, 5)

    def test_validator_flags_dropped_parts(self):
        passes, stats = generate_parallel_passes_with_stats(params(LATERAL_NOTCH, ((10, 0), (10, 40))))
        longest_only = []
        for items in by_pass(passes).values():
            longest_only.append(max(items, key=lambda p: p.length_m))
        report = coverage(longest_only, LATERAL_NOTCH, stats=stats)
        self.assertFalse(report.ok)
        self.assertEqual(report.code, GENERATOR_INCOMPLETE_FIELD_COVERAGE)
        self.assertGreater(report.missing_area_m2, 100.0 * 100.0)
        self.assertTrue(any(line.startswith("Cobertura: faltante_ha=") for line in report.summary_lines()))


if __name__ == "__main__":
    unittest.main()
