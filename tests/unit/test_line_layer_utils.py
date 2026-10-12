# -*- coding: utf-8 -*-
"""Testes de classificacao de guiamento por vertices."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.domain.guidance_reference import classify_guidance_mode


class GuidanceModeFromPointsTest(unittest.TestCase):
    def test_straight(self):
        pts = [(0.0, 0.0), (100.0, 0.0)]
        self.assertEqual(classify_guidance_mode(pts), "straight")

    def test_nearly_straight(self):
        pts = [(0.0, 0.0), (50.0, 0.05), (100.0, 0.0)]
        self.assertEqual(classify_guidance_mode(pts), "straight")

    def test_curved(self):
        pts = [(0.0, 0.0), (30.0, 20.0), (60.0, 20.0), (100.0, 0.0)]
        self.assertEqual(classify_guidance_mode(pts), "curved")


if __name__ == "__main__":
    unittest.main()
