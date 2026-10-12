# -*- coding: utf-8 -*-
"""Preview da aplicacao (SKILL 3): conjunto de camadas capturado ANTES.

``tests/fixtures/spray_preview_layers_baseline.json`` guarda nome, role,
numero de feicoes e campos de cada camada publicada pelo Workspace ao gerar a
aplicacao com os valores padrao (transpasse antigo, faixa externa 0, desvio
desligado, cabeceira manual) e com o desvio minimo da pulverizacao ligado.
Gravado com o codigo anterior a SKILL 3 (``--capture``).
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
)

from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
from plugin.fortsmart_precision.gui.fortsmart_workspace_dialog import FortSmartWorkspaceDialog

BASELINE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "spray_preview_layers_baseline.json"
FIELD_RING = "0 0,600 0,600 400,300 450,0 400,0 0"
_APP = None


def _setup_qgis():
    global _APP
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if QgsApplication.instance() is None:
        _APP = QgsApplication([], True)
        _APP.initQgis()


class _MapSettings:
    @staticmethod
    def destinationCrs():
        return QgsCoordinateReferenceSystem("EPSG:31982")


class _Canvas:
    def setRenderFlag(self, *_args):
        pass

    def refresh(self):
        pass

    def setExtent(self, *_args):
        pass

    def zoomOut(self):
        pass

    @staticmethod
    def mapSettings():
        return _MapSettings()


class _Iface:
    @staticmethod
    def mainWindow():
        return None

    @staticmethod
    def mapCanvas():
        return _Canvas()

    @staticmethod
    def activeLayer():
        return None


def make_dialog(ring: str = FIELD_RING, post_xy=(300.0, 210.0), ab=((0.0, 200.0), (600.0, 200.0))):
    QgsProject.instance().clear()
    field = QgsVectorLayer("Polygon?crs=EPSG:31982", "talhao_skill3", "memory")
    feature = QgsFeature()
    feature.setGeometry(QgsGeometry.fromWkt(f"POLYGON(({ring}))"))
    field.dataProvider().addFeature(feature)
    obstacles = QgsVectorLayer("Point?crs=EPSG:31982", "Postes", "memory")
    post = QgsFeature()
    post.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*post_xy)))
    obstacles.dataProvider().addFeature(post)
    QgsProject.instance().addMapLayers([field, obstacles])
    dialog = FortSmartWorkspaceDialog(_Iface())
    dialog.field_combo.setLayer(field)
    dialog.obstacle_combo.setLayer(obstacles)
    dialog.ab_start, dialog.ab_end = ab
    dialog.ab_path_points = (dialog.ab_start, dialog.ab_end)
    dialog.ab_source_crs = field.crs()
    dialog.sprayer_widget.nozzle_count_spin.setValue(72)
    dialog.sprayer_widget.nozzle_spacing_spin.setValue(0.50)
    dialog.sprayer_widget.tire_spin.setValue(0.37)
    dialog.sprayer_widget.inner_clearance_spin.setValue(2.70)
    dialog.sprayer_widget.outer_width_spin.setValue(3.43)
    dialog.planter_widget.row_count_spin.setValue(18)
    dialog.planter_widget.row_spacing_spin.setValue(0.50)
    dialog.planter_widget.informed_width_spin.setValue(9.0)
    return dialog


def enable_spray_avoidance(dialog, radius: float = 8.0) -> None:
    combo = dialog.obstacle_operation_combo
    combo.setCurrentIndex(combo.findData("spraying"))
    dialog.spray_avoid_enable_check.setChecked(True)
    dialog.spray_turn_radius_spin.setValue(radius)


def layer_inventory() -> dict[str, dict[str, object]]:
    out = {}
    for layer in QgsProject.instance().mapLayers().values():
        role = layer.customProperty("fortsmart_role", "")
        if not role:
            continue
        out[layer.name()] = {
            "role": role,
            "features": int(layer.featureCount()),
            "fields": sorted(layer.fields().names()),
        }
    return out


def set_spray_turn_mode(dialog, mode: str, radius: float | None = None) -> None:
    widget = dialog.sprayer_widget
    widget.spray_turn_mode_combo.setCurrentIndex(widget.spray_turn_mode_combo.findData(mode))
    if radius is not None:
        dialog.spray_turn_radius_spin.setValue(radius)


def render(dialog):
    project = dialog._build_project(include_planting=False, include_spraying=True)
    result = run_precision_lines(project)
    dialog._render_preview_layers(result)
    return result


def scenario_inventory(name: str) -> dict[str, dict[str, object]]:
    dialog = make_dialog()
    try:
        if name == "spray_minimum":
            enable_spray_avoidance(dialog)
        render(dialog)
        return layer_inventory()
    finally:
        dialog.reject()
        QgsProject.instance().clear()


SCENARIOS = ("spray_default", "spray_minimum")
# Visual do desvio (SKILL 3): entrada, saida/retorno e comprimento original x alternativo.
DETOUR_LAYER = "23_Desvios_Obstaculos"
DETOUR_EXTRA_FIELDS = {"entry_x", "entry_y", "exit_x", "exit_y", "original_length_m", "detour_length_m"}
REQUIRED_PREVIEW_PREFIXES = ("01", "02", "03", "04", "05", "11", "14", "15", "21", "22", "23")
TURN_LAYER = "16_Manobras_Cabeceira"
TURN_OBSTACLE_LAYERS = ("21_Obstaculos_RTK",)


class SprayPreviewLayersBaselineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()
        cls.baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))

    def test_default_preview_layer_set_is_identical(self):
        self.assertEqual(scenario_inventory("spray_default"), self.baseline["spray_default"])

    def test_detour_preview_only_adds_detour_fields(self):
        current = scenario_inventory("spray_minimum")
        baseline = self.baseline["spray_minimum"]
        self.assertEqual(sorted(current), sorted(baseline))
        for name, expected in baseline.items():
            with self.subTest(layer=name):
                self.assertEqual(current[name]["role"], expected["role"])
                self.assertEqual(current[name]["features"], expected["features"])
                extra = set(current[name]["fields"]) - set(expected["fields"])
                self.assertTrue(set(expected["fields"]) <= set(current[name]["fields"]))
                self.assertEqual(extra, DETOUR_EXTRA_FIELDS if name == DETOUR_LAYER else set())

    def test_required_layers_present_without_duplicates(self):
        dialog = make_dialog()
        try:
            enable_spray_avoidance(dialog)
            render(dialog)
            render(dialog)
            names = [layer.name() for layer in QgsProject.instance().mapLayers().values()
                     if layer.customProperty("fortsmart_role", "")]
            self.assertEqual(len(names), len(set(names)))
            for prefix in REQUIRED_PREVIEW_PREFIXES:
                self.assertEqual(len([n for n in names if n.startswith(prefix + "_")]), 1, prefix)
        finally:
            dialog.reject()
            QgsProject.instance().clear()

    def test_automatic_headland_adds_only_turn_layer_and_manual_removes_it(self):
        dialog = make_dialog()
        try:
            set_spray_turn_mode(dialog, "automatic", radius=8.0)
            result = render(dialog)
            turns = result.spray_headland_turns
            self.assertGreater(len(turns.turns), 0)
            auto = layer_inventory()
            render(dialog)
            self.assertEqual(sorted(layer_inventory()), sorted(auto))  # sem duplicar
            baseline = self.baseline["spray_default"]
            self.assertEqual(set(auto) - set(baseline), {TURN_LAYER})
            self.assertEqual(auto[TURN_LAYER]["role"], "HEADLAND_TURN")
            self.assertEqual(auto[TURN_LAYER]["features"], len(turns.turns))
            self.assertIn("radius_m", auto[TURN_LAYER]["fields"])
            for name, expected in baseline.items():
                if name in TURN_OBSTACLE_LAYERS:
                    # O poste vira obstaculo das curvas: mostrado, sem desvio nas passadas.
                    self.assertEqual(auto[name], {**expected, "features": 1}, name)
                else:
                    self.assertEqual(auto[name], expected, name)  # passadas/rastros intactos
            set_spray_turn_mode(dialog, "manual")
            render(dialog)
            manual = layer_inventory()
            self.assertNotIn(TURN_LAYER, manual)
            for name, expected in baseline.items():
                if name not in TURN_OBSTACLE_LAYERS:  # camada vazia mantem o conteudo anterior
                    self.assertEqual(manual[name], expected, name)
        finally:
            dialog.reject()
            QgsProject.instance().clear()


if __name__ == "__main__":
    if "--capture" in sys.argv:
        _setup_qgis()
        BASELINE_PATH.write_text(
            json.dumps({name: scenario_inventory(name) for name in SCENARIOS}, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(f"baseline gravado em {BASELINE_PATH}")
    else:
        unittest.main()
