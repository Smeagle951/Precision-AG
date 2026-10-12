import math
import random
import time
import unittest

from plugin.fortsmart_precision.core.guidance_engine import generate_traffic_passes
from plugin.fortsmart_precision.core.line_geometry import (
    point_in_multipolygon,
    points_in_multipolygon,
    signed_distance_point_to_polyline,
    signed_distances_to_polyline,
)
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, PlanterMachine
from plugin.fortsmart_precision.domain.precision_project import ABLine, PrecisionOperation


def _circle(cx, cy, radius, count):
    ring = [
        (cx + radius * math.cos(2 * math.pi * i / count), cy + radius * math.sin(2 * math.pi * i / count))
        for i in range(count)
    ]
    return ring + [ring[0]]


class PointsInMultipolygonTest(unittest.TestCase):
    def test_matches_python_ray_casting_with_holes_and_parts(self):
        polygons = [
            (_circle(0, 0, 100, 180), [_circle(0, 0, 30, 90)]),
            ([(200, -50), (300, -50), (300, 50), (200, 50), (200, -50)], []),
        ]
        rng = random.Random(7)
        points = [(rng.uniform(-150, 350), rng.uniform(-150, 150)) for _ in range(2000)]
        expected = [point_in_multipolygon(p, polygons) for p in points]
        self.assertEqual(points_in_multipolygon(points, polygons), expected)

    def test_boundary_counts_as_inside(self):
        square = [([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)], [])]
        points = [(10.0, 5.0)] * 40 + [(5.0, 5.0)] * 40 + [(20.0, 5.0)] * 40
        result = points_in_multipolygon(points, square)
        self.assertTrue(all(result[:80]))
        self.assertFalse(any(result[80:]))

    def test_small_input_and_empty(self):
        square = [([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)], [])]
        self.assertEqual(points_in_multipolygon([], square), [])
        self.assertEqual(points_in_multipolygon([(5, 5), (50, 5)], square), [True, False])


class SignedDistancesTest(unittest.TestCase):
    def test_matches_loop_on_curved_polyline(self):
        master = [(x, 30 * math.sin(x / 80.0)) for x in range(-400, 401, 4)]
        rng = random.Random(3)
        points = [(rng.uniform(-350, 350), rng.uniform(-200, 200)) for _ in range(1500)]
        fast = signed_distances_to_polyline(points, master)
        for point, value in zip(points, fast):
            self.assertAlmostEqual(value, signed_distance_point_to_polyline(point, master), places=6)

    def test_left_is_positive(self):
        master = [(0.0, 0.0), (100.0, 0.0)]
        points = [(50.0, 10.0)] * 20 + [(50.0, -10.0)] * 20
        values = signed_distances_to_polyline(points, master)
        self.assertTrue(all(abs(v - 10.0) < 1e-9 for v in values[:20]))
        self.assertTrue(all(abs(v + 10.0) < 1e-9 for v in values[20:]))


class CurvedPassPerformanceTest(unittest.TestCase):
    def test_dense_boundary_and_curved_ab_do_not_hang(self):
        field = [(_circle(0, 0, 450, 3000), [])]
        ab = [(-600 + 1200 * i / 1999, 40 * math.sin(i / 1999 * math.pi)) for i in range(2000)]
        planter = PlanterMachine(
            machine_id="p", name="p", row_count=40, row_spacing_m=0.5,
            track=MachineTrack(track_width_m=3.0, tire_width_m=0.5),
        )
        operation = PrecisionOperation(operation_id="planting", machine=planter)
        start = time.perf_counter()
        passes = generate_traffic_passes(
            field, ABLine(start=ab[0], end=ab[-1], path_points=tuple(ab)), operation,
            clip_boundary=field,
        )
        self.assertEqual(len(passes), 45)
        self.assertLess(time.perf_counter() - start, 15.0)


if __name__ == "__main__":
    unittest.main()
