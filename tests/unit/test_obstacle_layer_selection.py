# -*- coding: utf-8 -*-
"""Testes: obstaculos ponto/poligono (sem dependencia de QGIS)."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.domain.obstacle_model import (
    ObstacleType,
    obstacle_from_point,
    obstacle_from_polygon,
)


class ObstacleModelHelpersTest(unittest.TestCase):
    def test_obstacle_from_point_is_circular(self):
        obs = obstacle_from_point((10.0, 20.0), obstacle_radius_m=1.0, safety_margin_m=0.5)
        self.assertEqual(obs.obstacle_type, ObstacleType.POINT)
        self.assertTrue(obs.is_circular())
        self.assertAlmostEqual(obs.safety_zone_radius_m(), 1.5)

    def test_obstacle_from_polygon_uses_centroid(self):
        ring = [(0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (0.0, 2.0), (0.0, 0.0)]
        poly = (ring, [])
        obs = obstacle_from_polygon(poly, safety_margin_m=0.5, name="exclusao")
        self.assertEqual(obs.obstacle_type, ObstacleType.POLYGON)
        self.assertFalse(obs.is_circular())
        self.assertIsNotNone(obs.polygon)
        self.assertAlmostEqual(obs.center[0], 2.0)
        self.assertAlmostEqual(obs.center[1], 1.0)
        self.assertEqual(obs.name, "exclusao")


if __name__ == "__main__":
    unittest.main()
