# -*- coding: utf-8 -*-

import unittest

from plugin.fortsmart_precision.core.guidance_engine import TrafficPass
from plugin.fortsmart_precision.core.line_geometry import Segment
from plugin.fortsmart_precision.core.tractor_axis_engine import generate_straight_tractor_axes


def traffic(pass_no=0, offset=0.0, path_points=()):
    return TrafficPass(
        pass_no=pass_no,
        fs_id=f"P{pass_no}",
        operation_id="planting",
        spacing_m=10.0,
        width_m=10.0,
        offset_m=offset,
        azimuth_deg=90.0,
        direction="forward",
        clipped_segment=Segment((0.0, 50.0 + offset), (200.0, 50.0 + offset)),
        guidance_segment=Segment((0.0, 50.0 + offset), (200.0, 50.0 + offset)),
        path_points=tuple(path_points),
    )


class TractorAxisEngineTest(unittest.TestCase):
    def test_curved_work_path_becomes_straight_ab_axis_with_external_margin(self):
        field = [([(0, 0), (200, 0), (200, 100), (0, 100), (0, 0)], [])]
        curved = ((0.0, 50.0), (50.0, 65.0), (100.0, 75.0), (150.0, 62.0), (200.0, 50.0))
        axes = generate_straight_tractor_axes(
            [traffic(path_points=curved)],
            ab_start=(0.0, 50.0),
            ab_end=(200.0, 50.0),
            operational_boundary=field,
            extension_m=20.0,
        )
        self.assertEqual(len(axes), 1)
        self.assertEqual(len(axes[0].path_points), 2)
        start, end = axes[0].path_points
        self.assertAlmostEqual(start[0], -20.0, delta=0.05)
        self.assertAlmostEqual(end[0], 220.0, delta=0.05)
        self.assertAlmostEqual(start[1], 50.0, places=6)
        self.assertAlmostEqual(end[1], 50.0, places=6)

    def test_offsets_stay_parallel_and_independent(self):
        field = [([(0, 0), (200, 0), (200, 100), (0, 100), (0, 0)], [])]
        axes = generate_straight_tractor_axes(
            [traffic(0, 0.0), traffic(1, 10.0), traffic(2, 20.0)],
            ab_start=(0.0, 50.0),
            ab_end=(200.0, 50.0),
            operational_boundary=field,
            extension_m=0.0,
        )
        self.assertEqual(len(axes), 3)
        self.assertEqual([axis.path_points[0][1] for axis in axes], [50.0, 60.0, 70.0])
        self.assertTrue(all(len(axis.path_points) == 2 for axis in axes))

    def test_disjoint_field_keeps_segments_separate(self):
        field = [
            ([(0, 0), (80, 0), (80, 100), (0, 100), (0, 0)], []),
            ([(120, 0), (200, 0), (200, 100), (120, 100), (120, 0)], []),
        ]
        axes = generate_straight_tractor_axes(
            [traffic()],
            ab_start=(0.0, 50.0),
            ab_end=(200.0, 50.0),
            operational_boundary=field,
            extension_m=0.0,
        )
        self.assertEqual(len(axes), 2)
        self.assertEqual([axis.segment_index for axis in axes], [1, 2])


if __name__ == "__main__":
    unittest.main()
