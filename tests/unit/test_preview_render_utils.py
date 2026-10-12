# -*- coding: utf-8 -*-
"""Preview: ordem de camadas e pontos de passada."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.guidance_engine import TrafficPass
from plugin.fortsmart_precision.core.line_geometry import Segment
from plugin.fortsmart_precision.core.preview_layer_names import NAMED_PREVIEW_LAYERS
from plugin.fortsmart_precision.core.preview_render_utils import (
    PREVIEW_LINE_LAYERS_TOP,
    independent_tractor_paths,
    preview_layer_draw_order,
    preview_line_width_mm,
    traffic_pass_points,
)


class PreviewDrawOrderTest(unittest.TestCase):
    def test_covers_all_named_layers(self):
        order = preview_layer_draw_order()
        self.assertEqual(set(order), set(NAMED_PREVIEW_LAYERS))

    def test_pass_layers_on_top(self):
        order = preview_layer_draw_order()
        for name in ("05_Passadas", "06_Passadas_Plantio"):
            self.assertIn(name, PREVIEW_LINE_LAYERS_TOP)
            self.assertGreater(order.index(name), order.index("01_Limite_Externo"))
            self.assertGreater(order.index(name), order.index("02_Bordadura"))


class TrafficPassPointsTest(unittest.TestCase):
    @staticmethod
    def _traffic(pass_no, points):
        return TrafficPass(
            pass_no=pass_no,
            fs_id=f"t{pass_no}",
            operation_id="planting",
            spacing_m=18.0,
            width_m=18.0,
            offset_m=pass_no * 18.0,
            azimuth_deg=0.0,
            direction="forward",
            clipped_segment=Segment(points[0], points[-1]),
            guidance_segment=Segment(points[0], points[-1]),
            path_points=tuple(points),
        )

    def test_uses_path_points(self):
        traffic = TrafficPass(
            pass_no=0,
            fs_id="t",
            operation_id="spraying",
            spacing_m=36.0,
            width_m=36.0,
            offset_m=0.0,
            azimuth_deg=0.0,
            direction="forward",
            clipped_segment=Segment((0.0, 0.0), (10.0, 0.0)),
            guidance_segment=Segment((0.0, 0.0), (10.0, 0.0)),
            path_points=((0.0, 0.0), (50.0, 0.0), (100.0, 0.0)),
        )
        pts = traffic_pass_points(traffic)
        self.assertEqual(len(pts), 3)

    def test_falls_back_to_clipped_segment(self):
        traffic = TrafficPass(
            pass_no=1,
            fs_id="t",
            operation_id="spraying",
            spacing_m=36.0,
            width_m=36.0,
            offset_m=0.0,
            azimuth_deg=0.0,
            direction="forward",
            clipped_segment=Segment((0.0, 0.0), (100.0, 0.0)),
            guidance_segment=Segment((0.0, 0.0), (100.0, 0.0)),
        )
        pts = traffic_pass_points(traffic)
        self.assertEqual(pts[0], (0.0, 0.0))
        self.assertEqual(pts[-1], (100.0, 0.0))

    def test_tractor_paths_are_independent_and_keep_curves(self):
        first = ((0.0, 0.0), (40.0, 3.0), (100.0, 8.0))
        second = ((0.0, 18.0), (35.0, 21.0), (100.0, 26.0))
        paths = independent_tractor_paths(
            [self._traffic(0, first), self._traffic(1, second)]
        )
        self.assertEqual(paths, (first, second))
        self.assertEqual(len(paths), 2)
        self.assertNotIn((first[-1], second[0]), tuple(zip(paths[0], paths[1])))

    def test_tractor_paths_do_not_add_connector_at_acute_tip(self):
        first = ((0.0, 100.0), (45.0, 5.0))
        second = ((55.0, 5.0), (100.0, 100.0))
        paths = independent_tractor_paths(
            [self._traffic(0, first), self._traffic(1, second)]
        )
        self.assertEqual(paths[0][-1], (45.0, 5.0))
        self.assertEqual(paths[1][0], (55.0, 5.0))
        self.assertNotEqual(paths[0][-1], paths[1][0])


class PreviewLineWidthTest(unittest.TestCase):
    def test_passes_are_thicker(self):
        self.assertGreater(preview_line_width_mm("05_Passadas", 1.0), 1.0)


if __name__ == "__main__":
    unittest.main()
