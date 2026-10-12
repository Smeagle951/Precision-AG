# -*- coding: utf-8 -*-
"""Testes: limite real do talhao nao pode virar bbox/quadrado."""

from __future__ import annotations

import math
import unittest

from plugin.fortsmart_precision.core.line_geometry import (
    assert_not_degenerate_field,
    circle_ring_polygon,
    circularity_score,
    looks_like_axis_aligned_bbox,
    polygon_bbox_fill_ratio,
    shrink_polygon,
)


def _densified_square(side: float = 100.0, step: float = 2.0):
    """Simula Bounding Box densificado (muitos vertices, ainda retangulo)."""
    half = side / 2.0
    pts = []
    x = -half
    while x <= half + 1e-9:
        pts.append((x, -half))
        x += step
    y = -half + step
    while y <= half + 1e-9:
        pts.append((half, y))
        y += step
    x = half - step
    while x >= -half - 1e-9:
        pts.append((x, half))
        x -= step
    y = half - step
    while y > -half + 1e-9:
        pts.append((-half, y))
        y -= step
    pts.append(pts[0])
    return (pts, [])


class DegenerateFieldGuardTest(unittest.TestCase):
    def test_rejects_axis_aligned_four_point_square(self):
        square = [
            (
                [
                    (0.0, 0.0),
                    (100.0, 0.0),
                    (100.0, 100.0),
                    (0.0, 100.0),
                    (0.0, 0.0),
                ],
                [],
            )
        ]
        with self.assertRaises(ValueError) as ctx:
            assert_not_degenerate_field(square)
        self.assertIn("retangulo", str(ctx.exception).lower())

    def test_rejects_densified_bbox_square(self):
        densified = [_densified_square(200.0, step=2.0)]
        self.assertTrue(looks_like_axis_aligned_bbox(densified[0]))
        self.assertGreater(polygon_bbox_fill_ratio(densified[0]), 0.98)
        with self.assertRaises(ValueError) as ctx:
            assert_not_degenerate_field(densified)
        self.assertIn("bounding box", str(ctx.exception).lower())

    def test_accepts_circular_ring(self):
        circle = [circle_ring_polygon((0.0, 0.0), 80.0, segments=48)]
        self.assertFalse(looks_like_axis_aligned_bbox(circle[0]))
        self.assertAlmostEqual(polygon_bbox_fill_ratio(circle[0]), math.pi / 4.0, delta=0.02)
        self.assertGreater(circularity_score(circle[0]), 0.95)
        assert_not_degenerate_field(circle)  # nao levanta

    def test_circle_scores_above_densified_bbox(self):
        circle = circle_ring_polygon((0.0, 0.0), 80.0, segments=48)
        square = _densified_square(160.0, step=2.0)
        self.assertGreater(circularity_score(circle), circularity_score(square))

    def test_shrunk_circle_stays_round(self):
        circle = circle_ring_polygon((500.0, 500.0), 200.0, segments=72)
        inner = shrink_polygon(circle, 36.0)
        self.assertIsNotNone(inner)
        radii = [math.hypot(x - 500.0, y - 500.0) for x, y in inner[0][:-1]]
        self.assertAlmostEqual(min(radii), max(radii), delta=0.5)
        self.assertAlmostEqual(min(radii), 164.0, delta=1.0)
        assert_not_degenerate_field([inner])


if __name__ == "__main__":
    unittest.main()
