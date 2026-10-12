# -*- coding: utf-8 -*-
"""GUI do pulverizador: modo de transpasse, faixa para fora e _build_project."""

from __future__ import annotations

import os
import unittest

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsGeometry,
    QgsProject,
    QgsVectorLayer,
)

from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
from plugin.fortsmart_precision.domain.sprayer_overlap import (
    OVERLAP_MODE_METERS,
    OVERLAP_MODE_NONE,
    OVERLAP_MODE_NOZZLES,
)
from plugin.fortsmart_precision.gui.fortsmart_workspace_dialog import FortSmartWorkspaceDialog
from plugin.fortsmart_precision.gui.machine_config_widgets import SprayerConfigWidget

_APP = None
FIELD_RING = "0 0,600 0,600 400,300 450,0 400,0 0"


def _setup_qgis():
    global _APP
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if QgsApplication.instance() is None:
        _APP = QgsApplication([], True)
        _APP.initQgis()


def _select_mode(widget: SprayerConfigWidget, mode: str) -> None:
    widget.overlap_mode_combo.setCurrentIndex(widget.overlap_mode_combo.findData(mode))


def _acceptance_widget(outside: float = 0.5) -> SprayerConfigWidget:
    widget = SprayerConfigWidget()
    widget.nozzle_count_spin.setValue(72)
    widget.nozzle_spacing_spin.setValue(0.50)
    widget.tire_spin.setValue(0.37)
    widget.inner_clearance_spin.setValue(2.70)
    widget.outer_width_spin.setValue(3.43)
    _select_mode(widget, OVERLAP_MODE_NOZZLES)
    widget.overlap_nozzles_spin.setValue(2)
    widget.headland_outside_overlap_spin.setValue(outside)
    return widget


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


class SprayerOverlapWidgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()

    def test_mode_combo_items_and_default(self):
        widget = SprayerConfigWidget()
        combo = widget.overlap_mode_combo
        self.assertEqual(
            [combo.itemText(i) for i in range(combo.count())],
            ["Sem transpasse", "Em metros", "Em numero de bicos"],
        )
        self.assertEqual(widget.overlap_mode(), OVERLAP_MODE_METERS)
        self.assertEqual(widget.overlap_nozzles_spin.value(), 0)

    def test_empty_widget_requires_real_measurements(self):
        widget = SprayerConfigWidget()
        self.assertEqual(widget.nozzle_count_spin.value(), 0)
        self.assertEqual(widget.boom_spin.value(), 0.0)
        self.assertEqual(widget.tire_spin.value(), 0.0)
        self.assertEqual(widget.inner_clearance_spin.value(), 0.0)
        self.assertEqual(widget.outer_width_spin.value(), 0.0)
        with self.assertRaisesRegex(ValueError, "largura real da barra"):
            widget.build_machine()

    def test_manual_boom_without_nozzle_count(self):
        widget = SprayerConfigWidget()
        widget.boom_spin.setValue(25.3)
        widget.tire_spin.setValue(0.4)
        widget.inner_clearance_spin.setValue(2.6)
        widget.outer_width_spin.setValue(3.4)
        machine = widget.build_machine()
        self.assertAlmostEqual(machine.boom_width_m, 25.3)
        self.assertAlmostEqual(machine.effective_pass_spacing_m, 25.3)
        self.assertEqual(machine.nozzle_count, 0)
        self.assertEqual(machine.width_comparison().method, "manual")
        self.assertIn("sem calculo por bicos", widget.auto_overlap_hint.text())

    def test_nozzle_overlap_waits_for_nozzle_measurements(self):
        widget = SprayerConfigWidget()
        widget.boom_spin.setValue(25.3)
        _select_mode(widget, OVERLAP_MODE_NOZZLES)
        self.assertIn("Bicos de transpasse", widget.auto_overlap_hint.text())
        with self.assertRaisesRegex(ValueError, "Transpasse em bicos exige"):
            widget.build_machine()

    def test_mode_controls_visibility(self):
        widget = SprayerConfigWidget()
        expectations = {
            OVERLAP_MODE_NONE: (True, True),
            OVERLAP_MODE_METERS: (False, True),
            OVERLAP_MODE_NOZZLES: (True, False),
        }
        for mode, (meters_hidden, nozzles_hidden) in expectations.items():
            with self.subTest(mode=mode):
                _select_mode(widget, mode)
                self.assertEqual(widget.overlap_spin.isHidden(), meters_hidden)
                self.assertEqual(widget.overlap_label.isHidden(), meters_hidden)
                self.assertEqual(widget.overlap_nozzles_spin.isHidden(), nozzles_hidden)
                self.assertEqual(widget.overlap_nozzles_label.isHidden(), nozzles_hidden)

    def test_nozzle_spin_range_follows_nozzle_count(self):
        widget = SprayerConfigWidget()
        widget.nozzle_count_spin.setValue(72)
        self.assertEqual(widget.overlap_nozzles_spin.minimum(), 0)
        self.assertEqual(widget.overlap_nozzles_spin.maximum(), 71)
        widget.nozzle_count_spin.setValue(10)
        self.assertEqual(widget.overlap_nozzles_spin.maximum(), 9)

    def test_nozzle_mode_spacing_table(self):
        widget = _acceptance_widget(outside=0.0)
        for nozzles, spacing in ((0, 36.0), (1, 35.5), (2, 35.0), (3, 34.5), (4, 34.0)):
            with self.subTest(nozzles=nozzles):
                widget.overlap_nozzles_spin.setValue(nozzles)
                machine = widget.build_machine()
                self.assertAlmostEqual(machine.boom_width_m, 36.0)
                self.assertAlmostEqual(machine.effective_pass_spacing_m, spacing)
                self.assertAlmostEqual(widget.effective_width_m(), spacing)

    def test_build_machine_acceptance_values(self):
        machine = _acceptance_widget().build_machine()
        self.assertEqual(machine.overlap_mode, OVERLAP_MODE_NOZZLES)
        self.assertEqual(machine.overlap_nozzle_count, 2)
        self.assertAlmostEqual(machine.overlap_m, 1.0)
        self.assertAlmostEqual(machine.resolved_overlap_m, 1.0)
        self.assertAlmostEqual(machine.boom_width_m, 36.0)
        self.assertAlmostEqual(machine.effective_pass_spacing_m, 35.0)

    def test_traffic_measures_are_free_and_margin_reaches_machine(self):
        widget = SprayerConfigWidget()
        # Preenche primeiro a medida externa para nao criar um estado fisico
        # intermediario impossivel enquanto os sinais da GUI atualizam a previa.
        widget.outer_width_spin.setValue(14.0)
        widget.tire_spin.setValue(2.5)
        widget.inner_clearance_spin.setValue(9.0)
        widget.boom_spin.setValue(120.0)
        widget.tire_safety_margin_spin.setValue(0.25)

        machine = widget.build_machine()
        self.assertIsNotNone(machine.traffic)
        self.assertAlmostEqual(machine.traffic.tire_width_m, 2.5)
        self.assertAlmostEqual(machine.traffic.inner_clearance_m, 9.0)
        self.assertAlmostEqual(machine.traffic.outer_width_m, 14.0)
        self.assertAlmostEqual(machine.traffic.safety_margin_m, 0.25)
        self.assertAlmostEqual(machine.traffic.exclusion_width_m, 3.0)

        widget.nozzle_count_spin.setValue(600)
        widget.nozzle_spacing_spin.setValue(2.5)
        widget.boom_spin.setValue(120.0)
        widget.overlap_spin.setValue(25.0)
        self.assertEqual(widget.nozzle_count_spin.value(), 600)
        self.assertAlmostEqual(widget.nozzle_spacing_spin.value(), 2.5)
        self.assertAlmostEqual(widget.boom_spin.value(), 120.0)
        self.assertAlmostEqual(widget.overlap_spin.value(), 25.0)

    def test_transient_inconsistent_traffic_measure_does_not_break_widget(self):
        widget = SprayerConfigWidget()
        widget.inner_clearance_spin.setValue(20.0)
        self.assertTrue(widget.measure_status_label.text())
        self.assertEqual(widget.zones_preview_label.text(), "")

    def test_meters_mode_keeps_legacy_auto_overlap(self):
        widget = _acceptance_widget()
        widget.nozzle_count_spin.setValue(72)
        widget.boom_spin.setValue(35.0)
        self.assertAlmostEqual(widget.resolved_overlap_m(), 1.0)
        machine = widget.build_machine()
        self.assertAlmostEqual(machine.overlap_m, 1.0)
        self.assertAlmostEqual(machine.effective_pass_spacing_m, 34.0)
        _select_mode(widget, OVERLAP_MODE_NONE)
        self.assertEqual(widget.resolved_overlap_m(), 0.0)
        self.assertAlmostEqual(widget.build_machine().effective_pass_spacing_m, 35.0)

    def test_explicit_prior_values_reproduce_previous_result(self):
        widget = SprayerConfigWidget()
        widget.nozzle_count_spin.setValue(40)
        widget.nozzle_spacing_spin.setValue(0.50)
        widget.tire_spin.setValue(0.37)
        widget.inner_clearance_spin.setValue(2.70)
        widget.outer_width_spin.setValue(3.43)
        machine = widget.build_machine()
        self.assertAlmostEqual(machine.boom_width_m, 20.0)
        self.assertEqual(machine.overlap_m, 0.0)
        self.assertAlmostEqual(machine.effective_pass_spacing_m, 20.0)

    def test_headland_labels_use_physical_boom(self):
        widget = _acceptance_widget()
        self.assertEqual(widget.half_boom_label.text(), "18.000 m")
        self.assertEqual(
            widget.headland_summary_label.text(),
            "Barra fisica: 36,00 m / Meia barra: 18,00 m / Faixa fora: 0,50 m / "
            "Linha central: 17,50 m do limite / Passo efetivo: 35,00 m",
        )
        self.assertIn("17,50 m", widget.headland_band_label.text())
        self.assertAlmostEqual(widget.headland_schematic.boom_width_m, 36.0)
        self.assertAlmostEqual(widget.headland_schematic.outside_overlap_m, 0.5)
        self.assertAlmostEqual(widget.headland_schematic.center_offset_m, 17.5)
        widget.headland_schematic.resize(400, 110)
        widget.headland_schematic.grab()

    def test_outside_spin_is_limited_below_half_boom(self):
        widget = _acceptance_widget()
        self.assertLess(widget.headland_outside_overlap_spin.maximum(), 18.0)
        widget.headland_outside_overlap_spin.setValue(50.0)
        widget.build_headland_layout().validate()

    def test_build_headland_layout(self):
        widget = _acceptance_widget()
        widget.headland_width_spin.setValue(100.0)
        machine = widget.build_machine()
        layout = widget.build_headland_layout(machine)
        self.assertEqual(layout.pass_count, 3)
        self.assertAlmostEqual(layout.width_m, 36.0)
        self.assertAlmostEqual(layout.spacing_m, 35.0)
        self.assertAlmostEqual(layout.outside_overlap_m, 0.5)
        self.assertEqual(layout.center_offsets_m(), [17.5, 52.5, 87.5])
        widget.headland_check.setChecked(False)
        empty = widget.build_headland_layout(machine)
        self.assertEqual(empty.pass_count, 0)
        self.assertEqual(empty.mode, "none")


class BuildProjectSprayHeadlandTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()

    def setUp(self):
        QgsProject.instance().clear()
        layer = QgsVectorLayer("Polygon?crs=EPSG:31982", "talhao_skill1", "memory")
        feature = QgsFeature()
        # Convexo e nao retangular: o dialogo rejeita limite com cara de bbox.
        feature.setGeometry(QgsGeometry.fromWkt(f"POLYGON(({FIELD_RING}))"))
        layer.dataProvider().addFeature(feature)
        QgsProject.instance().addMapLayer(layer)
        self.layer = layer
        self.dialog = FortSmartWorkspaceDialog(_Iface())
        self.dialog.planter_widget.row_count_spin.setValue(18)
        self.dialog.planter_widget.row_spacing_spin.setValue(0.50)
        self.dialog.planter_widget.informed_width_spin.setValue(9.0)
        self.dialog.field_combo.setLayer(layer)
        self.dialog.ab_start = (0.0, 200.0)
        self.dialog.ab_end = (600.0, 200.0)
        self.dialog.ab_path_points = (self.dialog.ab_start, self.dialog.ab_end)
        self.dialog.ab_source_crs = layer.crs()

    def tearDown(self):
        self.dialog.reject()
        QgsProject.instance().clear()

    def _configure_sprayer(self, outside: float = 0.5) -> None:
        widget = self.dialog.sprayer_widget
        widget.nozzle_count_spin.setValue(72)
        widget.nozzle_spacing_spin.setValue(0.50)
        widget.tire_spin.setValue(0.37)
        widget.inner_clearance_spin.setValue(2.70)
        widget.outer_width_spin.setValue(3.43)
        _select_mode(widget, OVERLAP_MODE_NOZZLES)
        widget.overlap_nozzles_spin.setValue(2)
        widget.headland_outside_overlap_spin.setValue(outside)
        widget.headland_width_spin.setValue(70.0)

    def test_spraying_headland_uses_physical_boom_effective_spacing_and_outside(self):
        self._configure_sprayer()
        project = self.dialog._build_project(include_planting=False, include_spraying=True)
        headland = project.spraying.headland
        self.assertEqual(headland.pass_count, 2)
        self.assertAlmostEqual(headland.width_m, 36.0)
        self.assertAlmostEqual(headland.spacing_m, 35.0)
        self.assertAlmostEqual(headland.outside_overlap_m, 0.5)
        self.assertAlmostEqual(project.spraying.machine.boom_width_m, 36.0)

        result = run_precision_lines(project)
        lines = sorted(result.boundary.headland_centerlines, key=lambda line: line.pass_no)
        self.assertEqual([round(line.offset_from_outer_m, 3) for line in lines], [17.5, 52.5])
        ring = QgsGeometry.fromWkt(f"LINESTRING({FIELD_RING})")
        for line, expected in zip(lines, (17.5, 52.5)):
            for x, y in line.line_points():
                self.assertAlmostEqual(
                    ring.distance(QgsGeometry.fromWkt(f"POINT({x} {y})")), expected, places=3
                )

        self.dialog._render_preview_layers(result)
        passes_layer = next(
            layer
            for layer in QgsProject.instance().mapLayers().values()
            if layer.customProperty("fortsmart_role", "") == "GUIDANCE_TRACK"
        )
        names = passes_layer.fields().names()
        for name in ("direction", "overlap_side", "overlap_nozzles", "overlap_m"):
            self.assertIn(name, names)
        sides = {feature["overlap_side"] for feature in passes_layer.getFeatures()}
        self.assertEqual(sides, {"none", "left", "right"})
        overlapping = [f for f in passes_layer.getFeatures() if f["overlap_side"] != "none"]
        self.assertTrue(all(f["overlap_nozzles"] == 2 for f in overlapping))
        self.assertTrue(all(abs(f["overlap_m"] - 1.0) < 1e-9 for f in overlapping))

    def test_planting_headland_unchanged(self):
        self._configure_sprayer()
        project = self.dialog._build_project(include_planting=True, include_spraying=True)
        planting = project.planting.headland
        width = project.planting.machine.operational_width_m
        self.assertGreater(planting.pass_count, 0)
        self.assertAlmostEqual(planting.width_m, width)
        self.assertAlmostEqual(planting.spacing_m, width)
        self.assertEqual(planting.outside_overlap_m, 0.0)
        self.assertAlmostEqual(project.spraying.headland.outside_overlap_m, 0.5)


if __name__ == "__main__":
    unittest.main()
