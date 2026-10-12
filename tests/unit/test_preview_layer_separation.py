# -*- coding: utf-8 -*-
"""Testes de match de nomes de preview e prioridade plantio vs pulverizacao."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.cross_workflow import (
    passes_to_planting_rows,
    resolve_planting_rows_for_cross,
    resolve_spraying_passes_for_cross,
)
from plugin.fortsmart_precision.core.guidance_engine import TrafficPass
from plugin.fortsmart_precision.core.line_geometry import Segment
from plugin.fortsmart_precision.core.preview_layer_names import (
    PREVIEW_LAYER_PROPERTY,
    PREVIEW_PREFIX,
    find_preview_layer,
    is_planting_preview_line_layer,
    is_plugin_preview_layer,
    is_spraying_preview_line_layer,
    match_preview_layer_name,
    preview_group_name,
    preview_layer_base_name,
    unique_layer_name,
)
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, PlanterMachine


class _FakeLayer:
    def __init__(self, name: str):
        self._name = name

    def name(self) -> str:
        return self._name


def _planter() -> PlanterMachine:
    return PlanterMachine(
        machine_id="p",
        name="9m",
        row_count=18,
        row_spacing_m=0.5,
        track=MachineTrack(track_width_m=2.0, tire_width_m=0.3),
    )


def _spray_pass(fs_id: str, *, azimuth: float = 0.0) -> TrafficPass:
    return TrafficPass(
        pass_no=0 if fs_id == "s0" else 1,
        fs_id=fs_id,
        operation_id="spraying",
        spacing_m=36.0,
        width_m=36.0,
        offset_m=0.0,
        azimuth_deg=azimuth,
        direction="forward",
        clipped_segment=Segment((0.0, 0.0), (100.0, 0.0)),
        guidance_segment=Segment((0.0, 0.0), (100.0, 0.0)),
    )


def _plant_pass(fs_id: str, y: float = 120.0, pass_no: int = 0) -> TrafficPass:
    return TrafficPass(
        pass_no=pass_no,
        fs_id=fs_id,
        operation_id="planting",
        spacing_m=9.0,
        width_m=9.0,
        offset_m=0.0,
        azimuth_deg=0.0,
        direction="forward",
        clipped_segment=Segment((0.0, y), (400.0, y)),
        guidance_segment=Segment((0.0, y), (400.0, y)),
    )


class PreviewLayerNameMatchTest(unittest.TestCase):
    def test_matches_name_with_feature_count_suffix(self):
        base = f"{PREVIEW_PREFIX}05_Passadas"
        self.assertTrue(match_preview_layer_name(base, "05_Passadas"))
        self.assertTrue(match_preview_layer_name(f"{base} (12)", "05_Passadas"))
        self.assertFalse(
            match_preview_layer_name(f"{PREVIEW_PREFIX}06_Passadas_Plantio (3)", "05_Passadas")
        )

    def test_find_prefers_spray_not_planting(self):
        layers = [
            _FakeLayer(f"{PREVIEW_PREFIX}06_Passadas_Plantio (40)"),
            _FakeLayer(f"{PREVIEW_PREFIX}05_Passadas (18)"),
            _FakeLayer(f"{PREVIEW_PREFIX}07_Linha_Trator (2)"),
        ]
        found = find_preview_layer(layers, "05_Passadas", "spray")
        self.assertIsNotNone(found)
        self.assertIn("05_Passadas", found.name())

    def test_planting_preview_detector(self):
        plant = _FakeLayer(f"{PREVIEW_PREFIX}06_Passadas_Plantio (9)")
        spray = _FakeLayer(f"{PREVIEW_PREFIX}05_Passadas (9)")
        self.assertTrue(is_planting_preview_line_layer(plant))
        self.assertFalse(is_planting_preview_line_layer(spray))
        self.assertTrue(is_spraying_preview_line_layer(spray))
        self.assertFalse(is_spraying_preview_line_layer(plant))


class _MarkedLayer(_FakeLayer):
    def __init__(self, name: str, role: str | None):
        super().__init__(name)
        self._role = role

    def customProperty(self, key, default=None):
        return self._role if key == PREVIEW_LAYER_PROPERTY and self._role else default


class CleanPreviewNamesTest(unittest.TestCase):
    def test_display_name_has_no_prefix_or_count(self):
        name = preview_layer_base_name("06_Passadas_Plantio")
        self.assertEqual(name, "12_Passadas_Plantio")
        self.assertNotIn("fortsmart", name.casefold())
        self.assertNotIn("(", name)

    def test_unique_name_creates_copy_only_when_needed(self):
        self.assertEqual(unique_layer_name("05_Passadas", ["Boundary"]), "05_Passadas")
        self.assertEqual(unique_layer_name("05_Passadas", ["05_Passadas"]), "05_Passadas_2")
        self.assertEqual(
            unique_layer_name("05_Passadas", ["05_Passadas", "05_Passadas_2"]), "05_Passadas_3"
        )

    def test_match_accepts_clean_copy_and_legacy_names(self):
        for name in ("05_Passadas", "05_Passadas_2", f"{PREVIEW_PREFIX}05_Passadas (12)"):
            self.assertTrue(match_preview_layer_name(name, "05_Passadas"), name)
        self.assertFalse(match_preview_layer_name("06_Passadas_Plantio", "05_Passadas"))
        self.assertFalse(match_preview_layer_name("05_Passadas_antiga", "05_Passadas"))
        self.assertTrue(match_preview_layer_name("12_Passadas_Plantio", "06_Passadas_Plantio"))

    def test_plugin_marked_layer_wins_over_user_layer_with_same_name(self):
        user = _MarkedLayer("06_Passadas_Plantio", None)
        ours = _MarkedLayer("06_Passadas_Plantio_2", "06_Passadas_Plantio")
        self.assertIs(find_preview_layer([user, ours], "06_Passadas_Plantio"), ours)
        self.assertTrue(is_plugin_preview_layer(ours))
        self.assertFalse(is_plugin_preview_layer(user))
        self.assertTrue(is_plugin_preview_layer(_FakeLayer(f"{PREVIEW_PREFIX}05_Passadas (3)")))

    def test_group_name_follows_field_without_brand(self):
        self.assertEqual(preview_group_name("talhao_11"), "FORTSMART - talhao_11")
        self.assertEqual(preview_group_name(None), "FORTSMART - PROJETO")


class CrossPreferImportedTest(unittest.TestCase):
    def test_prefer_imported_spray_over_session(self):
        out, src = resolve_spraying_passes_for_cross(
            session_passes=[_spray_pass("s0")],
            imported_passes=[_spray_pass("s1", azimuth=90.0)],
            prefer_imported=True,
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].fs_id, "s1")
        self.assertIn("camada", src)

    def test_prefer_imported_planting_over_session(self):
        planter = _planter()
        imported = passes_to_planting_rows([_plant_pass("p2", y=200.0, pass_no=2)], planter)
        out, src = resolve_planting_rows_for_cross(
            session_rows=None,
            session_passes=[_plant_pass("p0", y=120.0, pass_no=0)],
            imported_rows=imported,
            planter=planter,
            prefer_imported=True,
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].pass_id, 2)
        self.assertIn("camada", src)


if __name__ == "__main__":
    unittest.main()
