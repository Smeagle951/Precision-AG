# -*- coding: utf-8 -*-
"""Offset exato das curvas, recorte exato e preservacao da geometria oficial."""

from __future__ import annotations

import math
import unittest

from shapely.geometry import LineString, Point

from plugin.fortsmart_precision.core.guidance_engine import TrafficPass
from plugin.fortsmart_precision.core.line_geometry import (
    Segment,
    clip_polyline_exact,
    offset_open_polyline_exact,
)
from plugin.fortsmart_precision.core.path_smoothing_engine import smooth_traffic_passes
from plugin.fortsmart_precision.core.precision_lines_engine import _simplify_within_tolerance
from plugin.fortsmart_precision.domain.path_smoothing_configuration import (
    PathSmoothingConfiguration,
    SmoothingLevel,
)


def arc(radius=100.0, start=0.0, end=math.pi, n=40):
    return [(radius * math.cos(start + (end - start) * i / n), radius * math.sin(start + (end - start) * i / n)) for i in range(n + 1)]


def traffic(points, pass_no=1):
    return TrafficPass(
        pass_no=pass_no, fs_id=str(pass_no), operation_id="planting", spacing_m=20.0, width_m=20.0,
        offset_m=-20.0, azimuth_deg=0.0, direction="A->B",
        clipped_segment=Segment(points[0], points[-1]),
        guidance_segment=Segment(points[0], points[-1]),
        path_points=tuple(points),
    )


class ExactOffsetTest(unittest.TestCase):
    def test_every_point_is_at_offset_distance(self):
        master = [(0.0, 0.0), (100.0, 0.0), (150.0, 60.0), (300.0, 60.0)]
        for offset in (20.0, -20.0, 40.0):
            parts = offset_open_polyline_exact(master, offset)
            self.assertEqual(len(parts), 1)
            base = LineString(master)
            line = LineString(parts[0])
            samples = [line.interpolate(t, normalized=True) for t in (i / 400 for i in range(401))]
            distances = [base.distance(p) for p in samples]
            self.assertLessEqual(max(abs(d - abs(offset)) for d in distances), 0.005)

    def test_keeps_master_direction_and_side(self):
        master = [(0.0, 0.0), (100.0, 0.0)]
        left = offset_open_polyline_exact(master, 20.0)[0]
        right = offset_open_polyline_exact(master, -20.0)[0]
        self.assertAlmostEqual(left[0][1], 20.0)
        self.assertAlmostEqual(right[0][1], -20.0)
        self.assertLess(left[0][0], left[-1][0])
        self.assertLess(right[0][0], right[-1][0])

    def test_offset_on_concave_side_keeps_distance(self):
        # Arco CCW de raio 100: o lado esquerdo e o centro (lado concavo).
        master = arc()
        parts = offset_open_polyline_exact(master, 60.0)
        base = LineString(master)
        points = [Point(p) for part in parts for p in part]
        self.assertTrue(points)
        self.assertTrue(all(math.hypot(p.x, p.y) < 50.0 for p in points))
        self.assertLessEqual(max(abs(base.distance(p) - 60.0) for p in points), 0.005)

    def test_zero_offset_returns_master(self):
        master = [(0.0, 0.0), (10.0, 5.0), (20.0, 0.0)]
        self.assertEqual(offset_open_polyline_exact(master, 0.0), [master])


class ExactClipTest(unittest.TestCase):
    square = [([(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0), (0.0, 0.0)], [])]

    def test_ends_on_boundary_and_keeps_vertices(self):
        line = [(-50.0, 50.0), (30.0, 50.0), (60.0, 52.0), (150.0, 52.0)]
        chunks = clip_polyline_exact(line, self.square)
        self.assertEqual(len(chunks), 1)
        chunk = chunks[0]
        self.assertAlmostEqual(chunk[0][0], 0.0, places=9)
        self.assertAlmostEqual(chunk[-1][0], 100.0, places=9)
        self.assertIn((30.0, 50.0), chunk)
        self.assertIn((60.0, 52.0), chunk)

    def test_hole_splits_in_line_order(self):
        field = [(self.square[0][0], [[(40.0, 40.0), (60.0, 40.0), (60.0, 60.0), (40.0, 60.0), (40.0, 40.0)]])]
        chunks = clip_polyline_exact([(150.0, 50.0), (-50.0, 50.0)], field)
        self.assertEqual(len(chunks), 2)
        self.assertAlmostEqual(chunks[0][0][0], 100.0)
        self.assertAlmostEqual(chunks[0][-1][0], 60.0)
        self.assertAlmostEqual(chunks[1][0][0], 40.0)
        self.assertAlmostEqual(chunks[1][-1][0], 0.0)


class OfficialGeometryPreservedTest(unittest.TestCase):
    def test_non_detoured_curved_pass_is_not_smoothed(self):
        points = arc(n=20)
        config = PathSmoothingConfiguration(level=SmoothingLevel.HIGH)
        kept = smooth_traffic_passes([traffic(points)], config, detoured_pass_nos=set())[0]
        self.assertEqual(kept.path_points, tuple(points))
        smoothed = smooth_traffic_passes([traffic(points)], config, detoured_pass_nos={1})[0]
        self.assertNotEqual(smoothed.path_points, tuple(points))

    def test_simplify_stays_within_two_millimetres(self):
        dense = [p for a, b in zip(arc(n=600), arc(n=600)[1:]) for p in (a, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))]
        simplified = _simplify_within_tolerance(dense)
        self.assertLess(len(simplified), len(dense))
        line = LineString(simplified)
        self.assertLessEqual(max(line.distance(Point(p)) for p in dense), 0.002 + 1e-9)


if __name__ == "__main__":
    unittest.main()
