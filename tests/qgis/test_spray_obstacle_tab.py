# -*- coding: utf-8 -*-
"""Aba 4: seletor Plantio/Pulverizacao e desvio minimo da barra (SKILL 2)."""

from __future__ import annotations

import os
import unittest

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
from plugin.fortsmart_precision.domain.sprayer_overlap import OVERLAP_MODE_NOZZLES
from plugin.fortsmart_precision.gui.fortsmart_workspace_dialog import FortSmartWorkspaceDialog

_APP = None
FIELD_RING = "0 0,600 0,600 400,300 450,0 400,0 0"


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


def _layer_by_role(role: str):
    return next(
        layer
        for layer in QgsProject.instance().mapLayers().values()
        if layer.customProperty("fortsmart_role", "") == role
    )


class SprayObstacleTabTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()

    def setUp(self):
        QgsProject.instance().clear()
        field = QgsVectorLayer("Polygon?crs=EPSG:31982", "talhao_skill2", "memory")
        feature = QgsFeature()
        feature.setGeometry(QgsGeometry.fromWkt(f"POLYGON(({FIELD_RING}))"))
        field.dataProvider().addFeature(feature)
        obstacles = QgsVectorLayer("Point?crs=EPSG:31982", "Postes", "memory")
        post = QgsFeature()
        post.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(300.0, 210.0)))
        obstacles.dataProvider().addFeature(post)
        QgsProject.instance().addMapLayers([field, obstacles])
        self.dialog = FortSmartWorkspaceDialog(_Iface())
        self.dialog.field_combo.setLayer(field)
        self.dialog.obstacle_combo.setLayer(obstacles)
        self.dialog.ab_start = (0.0, 200.0)
        self.dialog.ab_end = (600.0, 200.0)
        self.dialog.ab_path_points = (self.dialog.ab_start, self.dialog.ab_end)
        self.dialog.ab_source_crs = field.crs()
        widget = self.dialog.sprayer_widget
        widget.nozzle_count_spin.setValue(72)
        widget.nozzle_spacing_spin.setValue(0.50)
        widget.tire_spin.setValue(0.37)
        widget.inner_clearance_spin.setValue(2.70)
        widget.outer_width_spin.setValue(3.43)
        widget.overlap_mode_combo.setCurrentIndex(widget.overlap_mode_combo.findData(OVERLAP_MODE_NOZZLES))
        widget.overlap_nozzles_spin.setValue(2)
        self.dialog.planter_widget.row_count_spin.setValue(18)
        self.dialog.planter_widget.row_spacing_spin.setValue(0.50)
        self.dialog.planter_widget.informed_width_spin.setValue(9.0)

    def tearDown(self):
        self.dialog.reject()
        QgsProject.instance().clear()

    def _select_operation(self, operation: str) -> None:
        combo = self.dialog.obstacle_operation_combo
        combo.setCurrentIndex(combo.findData(operation))

    def _enable_spray_avoidance(self, turn_radius: float = 8.0) -> None:
        self._select_operation("spraying")
        self.dialog.spray_avoid_enable_check.setChecked(True)
        self.dialog.spray_turn_radius_spin.setValue(turn_radius)

    def test_operation_selector_defaults_to_planting_flow(self):
        combo = self.dialog.obstacle_operation_combo
        self.assertEqual([combo.itemData(i) for i in range(combo.count())], ["planting", "spraying"])
        self.assertEqual(combo.currentData(), "planting")
        self.assertFalse(self.dialog.planting_obstacle_panel.isHidden())
        self.assertTrue(self.dialog.spray_avoid_box.isHidden())
        self._select_operation("spraying")
        self.assertTrue(self.dialog.planting_obstacle_panel.isHidden())
        self.assertFalse(self.dialog.spray_avoid_box.isHidden())

    def test_spray_panel_reads_sprayer_from_tab_2(self):
        self._select_operation("spraying")
        text = self.dialog.spray_machine_info_label.text()
        self.assertIn("36.000 m", text)
        self.assertIn("72 bicos", text)
        self.assertIn("transpasse 1.000 m", text)
        self.assertIn("passo efetivo 35.000 m", text)
        self.assertEqual(self.dialog.spray_safe_radius_label.text(), "0.50 + 1.00 = 1.50 m")
        self.dialog.spray_safety_margin_spin.setValue(2.0)
        self.assertEqual(self.dialog.spray_safe_radius_label.text(), "0.50 + 2.00 = 2.50 m")

    def test_spray_controls_follow_enable_and_mode(self):
        self._select_operation("spraying")
        self.assertEqual(self.dialog.spray_avoid_mode_combo.currentData(), "minimum_deviation")
        self.assertFalse(self.dialog.spray_turn_radius_spin.isEnabled())
        self.dialog.spray_avoid_enable_check.setChecked(True)
        self.assertTrue(self.dialog.spray_turn_radius_spin.isEnabled())
        self.assertTrue(self.dialog.spray_avoid_side_combo.isEnabled())
        self.assertIn("raio minimo de giro", self.dialog.spray_avoid_status_label.text())
        self.dialog.spray_turn_radius_spin.setValue(8.0)
        self.assertEqual(self.dialog.spray_avoid_status_label.text(), "")
        mode = self.dialog.spray_avoid_mode_combo
        mode.setCurrentIndex(mode.findData("orbit_360"))
        self.assertFalse(self.dialog.spray_avoid_side_combo.isEnabled())

    def test_build_project_requires_sprayer_turn_radius(self):
        self._enable_spray_avoidance(0.0)
        with self.assertRaises(ValueError) as ctx:
            self.dialog._build_project(include_planting=False, include_spraying=True)
        self.assertIn("raio minimo de giro", str(ctx.exception))

    def test_build_project_uses_sprayer_radius_and_spray_obstacle_fields(self):
        self.dialog.planter_widget.turn_radius_spin.setValue(4.0)
        self._enable_spray_avoidance(8.0)
        side = self.dialog.spray_avoid_side_combo
        side.setCurrentIndex(side.findData("right"))
        project = self.dialog._build_project(include_planting=False, include_spraying=True)
        self.assertTrue(project.avoidance.minimum_deviation)
        self.assertEqual(project.avoidance.minimum_turn_radius_m, 8.0)
        self.assertEqual(project.avoidance.side_preference, "right")
        self.assertEqual(project.spraying.machine.sprayer_minimum_turn_radius_m, 8.0)
        self.assertAlmostEqual(project.spraying.machine.boom_width_m, 36.0)
        self.assertEqual(len(project.obstacles), 1)
        self.assertAlmostEqual(project.obstacles[0].obstacle_radius_m, 0.5)
        self.assertAlmostEqual(project.obstacles[0].safety_margin_m, 1.0)

    def test_spray_avoidance_off_never_uses_planter_radius(self):
        self.dialog.planter_widget.turn_radius_spin.setValue(4.0)
        project = self.dialog._build_project(include_planting=False, include_spraying=True)
        self.assertFalse(project.avoidance.enabled())
        self.assertIsNone(project.avoidance.minimum_turn_radius_m)
        self.assertEqual(project.obstacles, ())

    def test_planting_project_unchanged_with_spray_avoidance_on(self):
        baseline = self.dialog._build_project(include_planting=True, include_spraying=False)
        self._enable_spray_avoidance(8.0)
        project = self.dialog._build_project(include_planting=True, include_spraying=False)
        self.assertEqual(project.obstacles, baseline.obstacles)
        self.assertEqual(project.planting_avoidance, baseline.planting_avoidance)
        self.assertEqual(project.planting, baseline.planting)
        self.assertFalse(project.avoidance.enabled())

    def test_preview_materializes_zones_detours_and_pass_attributes(self):
        self._enable_spray_avoidance(8.0)
        project = self.dialog._build_project(include_planting=False, include_spraying=True)
        result = run_precision_lines(project)
        self.assertTrue(result.spray_avoidance_records)
        self.dialog._render_preview_layers(result)

        zones = _layer_by_role("SAFETY_ZONE")
        self.assertEqual(zones.featureCount(), 1)
        zone = next(zones.getFeatures())
        self.assertAlmostEqual(zone["safe_radius_m"], 1.5)
        self.assertEqual(zone["operation"], "spraying")

        detours = _layer_by_role("OBSTACLE_DETOUR")
        kinds = {feature["avoidance_type"] for feature in detours.getFeatures()}
        self.assertTrue(kinds & {"LATERAL", "FULL_CONTOUR"})
        for feature in detours.getFeatures():
            self.assertEqual(feature["operation"], "spraying")
            self.assertAlmostEqual(feature["boom_width_m"], 36.0)
            self.assertAlmostEqual(feature["minimum_turn_radius_m"], 8.0)

        passes = _layer_by_role("GUIDANCE_TRACK")
        self.assertIn("avoidance_type", passes.fields().names())
        self.assertIn("obstacle_ids", passes.fields().names())
        types = {feature["avoidance_type"] for feature in passes.getFeatures()}
        self.assertIn("NONE", types)

    def test_saved_project_persists_spray_avoidance_layers(self):
        import tempfile
        from pathlib import Path

        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.addCleanup(QgsProject.instance().setFileName, "")
        QgsProject.instance().setFileName(str(Path(tmp.name) / "fazenda.qgz"))
        self._enable_spray_avoidance(8.0)
        project = self.dialog._build_project(include_planting=False, include_spraying=True)
        self.dialog._render_preview(run_precision_lines(project))

        zones = _layer_by_role("SAFETY_ZONE")
        detours = _layer_by_role("OBSTACLE_DETOUR")
        passes = _layer_by_role("GUIDANCE_TRACK")
        self.assertEqual(zones.providerType(), "ogr")
        self.assertEqual(zones.name(), "22_Zonas_Seguranca")
        self.assertEqual(detours.name(), "23_Desvios_Obstaculos")
        self.assertEqual(passes.name(), "11_Passadas")
        self.assertAlmostEqual(next(zones.getFeatures())["safe_radius_m"], 1.5)
        self.assertIn("required_offset_m", detours.fields().names())
        self.assertGreater(detours.featureCount(), 0)
        self.assertIn("avoidance_type", passes.fields().names())

        self.dialog.spray_avoid_enable_check.setChecked(False)
        plain = self.dialog._build_project(include_planting=False, include_spraying=True)
        self.dialog._render_preview(run_precision_lines(plain))
        self.assertEqual(len([l for l in QgsProject.instance().mapLayers().values()
                              if l.customProperty("fortsmart_role", "") == "GUIDANCE_TRACK"]), 1)

    def test_preview_without_spray_avoidance_keeps_previous_schema(self):
        project = self.dialog._build_project(include_planting=False, include_spraying=True)
        result = run_precision_lines(project)
        self.assertEqual(result.spray_avoidance_records, [])
        self.dialog._render_preview_layers(result)
        passes = _layer_by_role("GUIDANCE_TRACK")
        self.assertNotIn("avoidance_type", passes.fields().names())
        self.assertEqual(_layer_by_role("SAFETY_ZONE").featureCount(), 0)


if __name__ == "__main__":
    unittest.main()
