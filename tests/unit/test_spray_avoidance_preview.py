# -*- coding: utf-8 -*-
"""Feicoes/atributos do desvio da pulverizacao para as camadas 10/11/05 do preview."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.application_obstacle_engine import (
    SPRAY_TURN_RADIUS_MISSING,
    apply_application_obstacle_avoidance,
)
from plugin.fortsmart_precision.core.spray_avoidance_preview import (
    SPRAY_DETOUR_FIELDS,
    SPRAY_PASS_FIELDS,
    SPRAY_ZONE_FIELDS,
    detour_geometry_attributes,
    spray_avoidance_summary,
    spray_detour_features,
    spray_machine_summary,
    spray_pass_attributes,
    spray_safe_radius_text,
    spray_safety_zone_features,
)
from tests.unit.test_spray_minimum_deviation import FIELD, _config, _obstacle, _pass, _sprayer


def _records(turn_radius=8.0):
    records: list = []
    apply_application_obstacle_avoidance(
        [_pass(225.0, 1), _pass(208.0, 2), _pass(200.5, 3)],
        [_obstacle(300.0, 200.0, "poste_1")],
        _sprayer(turn_radius),
        _config(),
        allowed_area=FIELD,
        report=records,
    )
    return records


class SprayAvoidancePreviewTests(unittest.TestCase):
    def test_spec_attributes_present_in_detour_fields(self):
        names = [name for name, _kind in SPRAY_DETOUR_FIELDS]
        for key in (
            "operation",
            "pass_id",
            "obstacle_id",
            "avoidance_type",
            "side",
            "boom_width_m",
            "safe_radius_m",
            "required_offset_m",
            "entry_station_m",
            "exit_station_m",
            "minimum_turn_radius_m",
        ):
            self.assertIn(key, names)
        self.assertEqual([name for name, _ in SPRAY_PASS_FIELDS], ["avoidance_type", "obstacle_ids"])
        self.assertIn("safe_radius_m", [name for name, _ in SPRAY_ZONE_FIELDS])

    def test_safety_zone_features(self):
        features = spray_safety_zone_features([_obstacle(300.0, 200.0, "poste_1")])
        self.assertEqual(len(features), 1)
        polygon, attrs = features[0]
        self.assertGreaterEqual(len(polygon[0]), 4)
        self.assertEqual(attrs["obstacle_id"], "poste_1")
        self.assertAlmostEqual(attrs["safe_radius_m"], 1.5)
        self.assertEqual(attrs["operation"], "spraying")

    def test_detour_features_skip_none(self):
        features = spray_detour_features(_records())
        kinds = sorted(attrs["avoidance_type"] for _pts, attrs in features)
        self.assertEqual(kinds, ["FULL_CONTOUR", "LATERAL"])
        for pts, attrs in features:
            self.assertGreaterEqual(len(pts), 2)
            self.assertEqual(attrs["operation"], "spraying")

    def test_detour_features_show_entry_exit_and_alternative_length(self):
        names = [name for name, _kind in SPRAY_DETOUR_FIELDS]
        for key in ("entry_x", "entry_y", "exit_x", "exit_y", "original_length_m", "detour_length_m"):
            self.assertIn(key, names)
        for pts, attrs in spray_detour_features(_records()):
            with self.subTest(avoidance=attrs["avoidance_type"]):
                self.assertEqual((attrs["entry_x"], attrs["entry_y"]), (round(pts[0][0], 3), round(pts[0][1], 3)))
                self.assertEqual((attrs["exit_x"], attrs["exit_y"]), (round(pts[-1][0], 3), round(pts[-1][1], 3)))
                # Sai e retorna sobre a mesma passada original (y=208 ou y=200,5).
                self.assertIn(attrs["entry_y"], (208.0, 200.5))
                self.assertEqual(attrs["exit_y"], attrs["entry_y"])
                self.assertAlmostEqual(attrs["original_length_m"], abs(attrs["exit_x"] - attrs["entry_x"]), places=2)
                self.assertGreater(attrs["detour_length_m"], attrs["original_length_m"])

    def test_detour_geometry_attributes(self):
        attrs = detour_geometry_attributes(((0.0, 0.0), (3.0, 4.0), (6.0, 0.0)))
        self.assertEqual(
            attrs,
            {"entry_x": 0.0, "entry_y": 0.0, "exit_x": 6.0, "exit_y": 0.0,
             "original_length_m": 6.0, "detour_length_m": 10.0},
        )

    def test_unresolved_draws_original_conflict_stretch(self):
        features = spray_detour_features(_records(None))
        self.assertTrue(features)
        self.assertTrue(all(attrs["avoidance_type"] == "UNRESOLVED" for _pts, attrs in features))
        self.assertTrue(all(attrs["reason"] == SPRAY_TURN_RADIUS_MISSING for _pts, attrs in features))

    def test_pass_attributes(self):
        attrs = spray_pass_attributes(_records())
        self.assertEqual(attrs[1]["avoidance_type"], "NONE")
        self.assertEqual(attrs[2]["avoidance_type"], "LATERAL")
        self.assertEqual(attrs[3], {"avoidance_type": "FULL_CONTOUR", "obstacle_ids": "poste_1"})

    def test_summary_and_unresolved_warnings(self):
        self.assertEqual(spray_avoidance_summary([]), ("", []))
        text, warnings = spray_avoidance_summary(_records())
        self.assertIn("LATERAL=1", text)
        self.assertIn("FULL_CONTOUR=1", text)
        self.assertEqual(warnings, [])
        text, warnings = spray_avoidance_summary(_records(None))
        self.assertIn("UNRESOLVED=2", text)
        self.assertEqual(len(warnings), 2)
        self.assertIn("sem desvio seguro", warnings[0])

    def test_machine_and_safe_radius_text(self):
        self.assertEqual(
            spray_machine_summary(boom_width_m=36.0, nozzle_count=72, nozzle_spacing_m=0.5, overlap_m=1.0),
            "Barra fisica 36.000 m (72 bicos x 0.500 m) | transpasse 1.000 m | passo efetivo 35.000 m",
        )
        self.assertEqual(spray_safe_radius_text(0.5, 1.0), "0.50 + 1.00 = 1.50 m")


if __name__ == "__main__":
    unittest.main()
