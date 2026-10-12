# -*- coding: utf-8 -*-
"""Cenarios da simulacao visual: faixa, remonte, falha e WORK_OFF."""

import unittest

from shapely.geometry import Polygon

from plugin.fortsmart_precision.core.visual_coverage_engine import (
    VisualCoverageError,
    simulate_visual_coverage,
)


class VisualCoverageEngineTest(unittest.TestCase):
    def test_ten_meter_implement_extends_five_meters_each_side(self):
        result = simulate_visual_coverage([[(0.0, 0.0), (0.0, 100.0)]], work_width_m=10.0)
        self.assertAlmostEqual(result.metrics.covered_area_ha, 0.1)
        self.assertAlmostEqual(result.metrics.overlap_area_ha, 0.0)
        self.assertIsNone(result.metrics.gap_area_ha)

    def test_overlap_is_the_shared_swept_area(self):
        result = simulate_visual_coverage(
            [[(0.0, 0.0), (0.0, 100.0)], [(8.0, 0.0), (8.0, 100.0)]],
            work_width_m=10.0,
        )
        self.assertAlmostEqual(result.metrics.overlap_area_ha, 0.02)
        self.assertAlmostEqual(result.metrics.covered_area_ha, 0.18)

    def test_gap_is_calculated_only_inside_optional_boundary(self):
        area = Polygon([(0, 0), (30, 0), (30, 100), (0, 100)])
        result = simulate_visual_coverage(
            [[(5.0, 0.0), (5.0, 100.0)], [(25.0, 0.0), (25.0, 100.0)]],
            work_width_m=10.0,
            analysis_area=area,
        )
        self.assertAlmostEqual(result.metrics.gap_area_ha or 0.0, 0.1)

    def test_work_off_segments_are_not_passed_to_coverage(self):
        result = simulate_visual_coverage([[(0.0, 0.0), (0.0, 40.0)]], work_width_m=10.0)
        self.assertAlmostEqual(result.metrics.covered_area_ha, 0.04)

    def test_requires_positive_width_and_work_on_segment(self):
        with self.assertRaises(VisualCoverageError):
            simulate_visual_coverage([[(0.0, 0.0), (0.0, 1.0)]], work_width_m=0.0)
        with self.assertRaises(VisualCoverageError):
            simulate_visual_coverage([], work_width_m=10.0)
