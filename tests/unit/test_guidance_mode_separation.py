# -*- coding: utf-8 -*-
"""A-B curva nao deve ser confundida com AdaptiveCurve/serpentina."""

from __future__ import annotations

import math
import unittest

from plugin.fortsmart_precision.domain.guidance_reference import (
    classify_guidance_mode,
    looks_like_adaptive_serpentine,
)


class GuidanceModeSeparationTest(unittest.TestCase):
    def test_gentle_curve_ab_is_curved_not_adaptive(self):
        # Arco suave com sag > 25 m — ainda e A-B curva (comprimento ~ corda).
        pts = []
        for i in range(40):
            t = i / 39.0
            x = 500.0 * t
            y = 40.0 * math.sin(math.pi * t)
            pts.append((x, y))
        self.assertFalse(looks_like_adaptive_serpentine(pts))
        self.assertEqual(classify_guidance_mode(pts), "curved")

    def test_serpentine_is_adaptive(self):
        pts = []
        for pass_i in range(6):
            y = 20.0 + pass_i * 36.0
            if pass_i % 2 == 0:
                xs = [10.0 + j * 10.0 for j in range(20)]
            else:
                xs = [200.0 - j * 10.0 for j in range(20)]
            for x in xs:
                pts.append((x, y))
            if pass_i < 5:
                # U na cabeceira
                pts.append((xs[-1], y + 18.0))
        self.assertTrue(looks_like_adaptive_serpentine(pts))
        self.assertEqual(classify_guidance_mode(pts), "adaptive")

    def test_straight_ab(self):
        pts = [(0.0, 0.0), (100.0, 0.0), (200.0, 0.0)]
        self.assertEqual(classify_guidance_mode(pts), "straight")


if __name__ == "__main__":
    unittest.main()
