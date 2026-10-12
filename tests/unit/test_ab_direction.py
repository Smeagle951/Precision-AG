# -*- coding: utf-8 -*-
import unittest

from plugin.fortsmart_precision.core.ab_direction import (
    ab_has_valid_direction,
    resolve_ab_direction_end,
)
from plugin.fortsmart_precision.core.parallel_pass_engine import (
    ParallelPassParams,
    generate_parallel_passes,
)
from plugin.fortsmart_precision.domain.guidance_reference import classify_guidance_mode


class AbDirectionTest(unittest.TestCase):
    def test_closed_loop_uses_farthest_point_for_direction(self):
        ring = [
            (0.0, 0.0),
            (100.0, 0.0),
            (100.0, 50.0),
            (0.0, 50.0),
            (0.0, 0.0),
        ]
        end = resolve_ab_direction_end(ring[0], ring[-1], ring)
        self.assertGreater(end[0], 50.0)

    def test_short_open_segment_still_valid(self):
        self.assertTrue(ab_has_valid_direction((0.0, 0.0), (10.0, 0.0), ()))

    def test_classify_closed_ring_as_curved(self):
        ring = [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 0.0)]
        self.assertIn(classify_guidance_mode(ring), ("curved", "adaptive"))

    def test_parallel_passes_from_closed_ab_reference(self):
        field = [([(0.0, 0.0), (200.0, 0.0), (200.0, 100.0), (0.0, 100.0), (0.0, 0.0)], [])]
        ring = [(0.0, 0.0), (80.0, 0.0), (80.0, 40.0), (0.0, 0.0)]
        params = ParallelPassParams(
            polygons=field,
            ab_start=ring[0],
            ab_end=ring[-1],
            pass_spacing_m=20.0,
            operation_width_m=20.0,
            extension_m=5.0,
            master_path=tuple(ring),
        )
        passes = generate_parallel_passes(params)
        self.assertGreater(len(passes), 0)
        self.assertGreater(max(p.clipped_segment.length for p in passes), 50.0)


    def test_parallel_passes_with_duplicate_vertices_on_curve(self):
        field = [([(0.0, 0.0), (200.0, 0.0), (200.0, 100.0), (0.0, 100.0), (0.0, 0.0)], [])]
        curve = [
            (0.0, 50.0),
            (0.0, 50.0),
            (50.0, 55.0),
            (100.0, 50.0),
            (150.0, 45.0),
            (200.0, 50.0),
            (200.0, 50.0),
        ]
        params = ParallelPassParams(
            polygons=field,
            ab_start=curve[0],
            ab_end=curve[-1],
            pass_spacing_m=20.0,
            operation_width_m=20.0,
            extension_m=5.0,
            master_path=tuple(curve),
        )
        passes = generate_parallel_passes(params)
        self.assertGreater(len(passes), 0)


if __name__ == "__main__":
    unittest.main()
