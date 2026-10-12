import unittest

from plugin.fortsmart_precision.core.crs import (
    CrsValidationError,
    describe_sirgas_utm_zone,
    inspect_authid,
    list_sirgas_utm_south_standards,
    normalize_authid,
    recommended_sirgas_targets,
    require_projected_metric,
    sirgas_utm_standard_summary,
    suggest_sirgas_utm_epsg,
)
from plugin.fortsmart_precision.core.zone_converter import build_zone_conversion_plan


class CrsRulesTest(unittest.TestCase):
    def test_normalize_epsg_values(self):
        self.assertEqual(normalize_authid("4326"), "EPSG:4326")
        self.assertEqual(normalize_authid("epsg:31981"), "EPSG:31981")
        self.assertEqual(normalize_authid(" EPSG 32722 "), "EPSG:32722")

    def test_geographic_crs_is_rejected_for_metric_operations(self):
        with self.assertRaises(CrsValidationError):
            require_projected_metric("EPSG:4326", "calculo de area")

    def test_missing_crs_is_rejected(self):
        with self.assertRaises(CrsValidationError):
            require_projected_metric("", "buffer")

    def test_projected_metric_crs_is_accepted(self):
        info = require_projected_metric("EPSG:31981", "calculo de area")
        self.assertTrue(info.is_projected_metric)

    def test_inspect_authid_marks_known_geographic(self):
        info = inspect_authid("EPSG:4674")
        self.assertTrue(info.is_known)
        self.assertTrue(info.is_geographic)
        self.assertFalse(info.is_projected_metric)

    def test_suggest_sirgas_utm_epsg_for_brazil_south(self):
        self.assertEqual(suggest_sirgas_utm_epsg(-55.0, -15.0), "EPSG:31981")
        self.assertEqual(suggest_sirgas_utm_epsg(-49.0, -23.0), "EPSG:31982")

    def test_suggest_sirgas_utm_rejects_northern_hemisphere_for_mvp(self):
        with self.assertRaises(CrsValidationError):
            suggest_sirgas_utm_epsg(-54.0, 2.0)

    def test_describe_zone_21s_centro_oeste(self):
        text = describe_sirgas_utm_zone(21)
        self.assertIn("31981", text)
        self.assertIn("21S", text)

    def test_standard_summary_mentions_longitude_not_state(self):
        summary = sirgas_utm_standard_summary()
        self.assertIn("LONGITUDE", summary)
        self.assertIn("31981", summary)
        self.assertIn("estado", summary.lower())
        self.assertIn("SIRGAS 2000", summary)

    def test_official_standards_are_only_sirgas_utm_south(self):
        standards = list_sirgas_utm_south_standards()
        self.assertEqual(len(standards), 8)
        authids = [a for a, _z, _h in standards]
        self.assertEqual(authids[0], "EPSG:31978")
        self.assertEqual(authids[-1], "EPSG:31985")
        # Nao inclui WGS84/UTM nem Web Mercator.
        self.assertNotIn("EPSG:32721", authids)
        self.assertNotIn("EPSG:3857", authids)

    def test_recommended_targets_mark_primary_by_longitude(self):
        items = recommended_sirgas_targets(-54.5, -15.0)
        primary = [item for item in items if item["is_primary"]]
        self.assertEqual(len(primary), 1)
        self.assertEqual(primary[0]["authid"], "EPSG:31981")
        self.assertEqual(items[0]["authid"], "EPSG:31981")

    def test_conversion_plan_rejects_non_standard_preferred(self):
        with self.assertRaises(CrsValidationError):
            build_zone_conversion_plan(
                "EPSG:4326",
                -54.0,
                -15.0,
                preferred_target="EPSG:3857",
            )

    def test_conversion_plan_accepts_official_preferred(self):
        plan = build_zone_conversion_plan(
            "EPSG:4326",
            -54.0,
            -15.0,
            preferred_target="EPSG:31981",
        )
        self.assertEqual(plan.target_authid, "EPSG:31981")
        self.assertTrue(plan.needs_reprojection)
        self.assertGreaterEqual(len(plan.recommended_targets), 8)


if __name__ == "__main__":
    unittest.main()
