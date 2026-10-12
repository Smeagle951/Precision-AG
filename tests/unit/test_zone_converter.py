# -*- coding: utf-8 -*-
"""Testes do conversor de zonas UTM / coordenadas."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.crs import CrsValidationError
from plugin.fortsmart_precision.core.zone_converter import (
    CoordinateKind,
    build_zone_conversion_plan,
    classify_coordinate_pair,
    crs_status,
    explain_ab_mismatch,
    sirgas_utm_authid,
    utm_zone_from_longitude,
)


class ZoneConverterTest(unittest.TestCase):
    def test_utm_zone_from_longitude(self):
        self.assertEqual(utm_zone_from_longitude(-55.0), 21)
        self.assertEqual(utm_zone_from_longitude(-49.0), 22)

    def test_sirgas_utm_authid(self):
        self.assertEqual(sirgas_utm_authid(21), "EPSG:31981")

    def test_classify_geographic(self):
        sample = classify_coordinate_pair(-49.0, -16.0)
        self.assertEqual(sample.kind, CoordinateKind.GEOGRAPHIC)

    def test_classify_web_mercator(self):
        sample = classify_coordinate_pair(-6060219.0, -1728521.0)
        self.assertEqual(sample.kind, CoordinateKind.WEB_MERCATOR)

    def test_classify_utm_like(self):
        sample = classify_coordinate_pair(500000.0, 7500000.0)
        self.assertEqual(sample.kind, CoordinateKind.PROJECTED_METRIC)

    def test_build_plan_geographic_needs_reprojection(self):
        plan = build_zone_conversion_plan("EPSG:4326", -49.0, -16.0)
        self.assertTrue(plan.needs_reprojection)
        self.assertEqual(plan.target_authid, "EPSG:31982")
        self.assertEqual(plan.utm_zone, 22)

    def test_build_plan_already_ok(self):
        plan = build_zone_conversion_plan("EPSG:31981", -55.0, -15.0)
        self.assertFalse(plan.needs_reprojection)

    def test_crs_status(self):
        self.assertEqual(crs_status("EPSG:4326").value, "geographic")
        self.assertEqual(crs_status("EPSG:31981").value, "ok")

    def test_explain_ab_mismatch_web_mercator_vs_4326(self):
        msg = explain_ab_mismatch("EPSG:4326", -6060219.0, -1728521.0)
        self.assertIsNotNone(msg)
        self.assertIn("Web Mercator", msg)

    def test_explain_ab_mismatch_none_when_ok(self):
        self.assertIsNone(explain_ab_mismatch("EPSG:31981", 500000.0, 7500000.0))


if __name__ == "__main__":
    unittest.main()
