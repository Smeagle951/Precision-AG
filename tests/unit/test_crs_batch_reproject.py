# -*- coding: utf-8 -*-
"""Testes de lote CRS (sem runtime QGIS)."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.crs import suggest_sirgas_utm_epsg
from plugin.fortsmart_precision.core.zone_converter import build_zone_conversion_plan


class BatchCrsHelpersTest(unittest.TestCase):
    def test_plan_for_multiple_sources_same_target(self):
        """Limite e obstaculo em 4326 devem apontar para o mesmo SIRGAS."""
        target = suggest_sirgas_utm_epsg(-54.2, -15.5)
        plan_field = build_zone_conversion_plan("EPSG:4326", -54.2, -15.5)
        plan_obs = build_zone_conversion_plan("EPSG:4326", -54.1, -15.4)
        self.assertEqual(plan_field.target_authid, target)
        self.assertEqual(plan_obs.target_authid, target)
        self.assertTrue(plan_field.needs_reprojection)
        self.assertTrue(plan_obs.needs_reprojection)
        self.assertEqual(target, "EPSG:31981")

    def test_batch_targets_cover_common_ag_layers(self):
        """Longitudes tipicas → zonas SIRGAS corretas."""
        self.assertEqual(suggest_sirgas_utm_epsg(-56.0, -15.0), "EPSG:31981")
        self.assertEqual(suggest_sirgas_utm_epsg(-54.5, -15.0), "EPSG:31981")
        self.assertEqual(suggest_sirgas_utm_epsg(-52.1, -15.0), "EPSG:31982")

    def test_explain_ab_mismatch_still_detects_4326_vs_utm(self):
        from plugin.fortsmart_precision.core.zone_converter import explain_ab_mismatch

        warning = explain_ab_mismatch(
            "EPSG:31981",
            -54.48,
            -15.38,
            ab_crs_authid="EPSG:4326",
        )
        self.assertTrue(warning)
        self.assertIn("4326", warning)


if __name__ == "__main__":
    unittest.main()
