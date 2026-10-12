# -*- coding: utf-8 -*-
"""Faixa de cobertura no QGIS: camada temporaria e integracao com a tela do simulador."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from qgis.core import QgsApplication

    HAS_QGIS = True
except ImportError:
    HAS_QGIS = False

E0, N0 = 650000.0, 8500000.0


def _app():
    app = QgsApplication.instance()
    if app is None:
        app = QgsApplication([], True)
        app.initQgis()
    return app


def line_layer(features, crs="EPSG:31982"):
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsVectorLayer

    layer = QgsVectorLayer(
        f"LineString?crs={crs}&field=line_number:integer&field=width_m:double", "passadas", "memory"
    )
    items = []
    for points, values in features:
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in points]))
        feature.setAttributes(list(values))
        items.append(feature)
    layer.dataProvider().addFeatures(items)
    layer.updateExtents()
    return layer


def two_passes(width=12.15, spacing=12.15):
    return line_layer([
        (((E0, N0), (E0 + 100, N0)), (1, width)),
        (((E0, N0 + spacing), (E0 + 100, N0 + spacing)), (2, width)),
    ])


def snapshot(layer):
    return sorted((f.id(), f.geometry().asWkt(6), tuple(f.attributes())) for f in layer.getFeatures())


@unittest.skipUnless(HAS_QGIS, "QGIS nao disponivel")
class CoverageRendererTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from qgis.core import QgsProject

        QgsProject.instance().clear()

    def tearDown(self):
        from qgis.core import QgsProject

        QgsProject.instance().clear()

    def test_one_feature_per_pass_updated_in_place_with_transparent_fill(self):
        from qgis.core import QgsCoordinateReferenceSystem, QgsProject

        from plugin.fortsmart_precision.core.coverage_engine import CoverageEngine, CoverageSettings
        from plugin.fortsmart_precision.core.route_simulation_engine import RouteSimulationEngine
        from plugin.fortsmart_precision.core.simulation_route import RoutePassInput, build_ordered_route
        from plugin.fortsmart_precision.core.layer_roles import is_temporary_preview
        from plugin.fortsmart_precision.domain.machine_profile import MachineProfile
        from plugin.fortsmart_precision.gui.route_coverage_renderer import COVERAGE_LAYER_NAME, CoverageRenderer

        passes = [
            RoutePassInput("P01", (((E0, N0), (E0 + 100, N0)),), 1),
            RoutePassInput("P02", (((E0, N0 + 9), (E0 + 100, N0 + 9)),), 2),
        ]
        engine = RouteSimulationEngine(build_ordered_route(passes), MachineProfile("m", "m", width_m=10.0), 10.0)
        coverage = CoverageEngine(CoverageSettings(10.0))
        renderer = CoverageRenderer(QgsProject.instance(), QgsCoordinateReferenceSystem("EPSG:31982"), 0.10)
        engine.start()
        for _ in range(80):
            engine.advance(0.1)  # 80 quadros de 1 m na P01
            if coverage.update(engine):
                renderer.render(coverage.state)

        layer = renderer.layer
        self.assertEqual(layer.name(), COVERAGE_LAYER_NAME)
        self.assertEqual(layer.featureCount(), 1)
        self.assertAlmostEqual(next(layer.getFeatures()).geometry().area(), 800.0, places=3)
        self.assertTrue(is_temporary_preview(layer))
        symbol_layer = layer.renderer().symbol().symbolLayer(0)
        self.assertAlmostEqual(symbol_layer.color().alphaF(), 0.10, places=2)
        self.assertEqual(symbol_layer.strokeStyle(), 0)  # Qt.NoPen

        engine.advance(7.0)  # fecha a P01 e anda 50 m na P02
        coverage.update(engine)
        renderer.render(coverage.state)
        features = sorted(layer.getFeatures(), key=lambda f: f["pass_index"])
        self.assertEqual([f["status"] for f in features], ["COMPLETED", "ACTIVE"])
        self.assertTrue(features[0].geometry().intersects(features[1].geometry()))  # transpasse de 1 m

        renderer.set_opacity(0.20)
        self.assertAlmostEqual(layer.renderer().symbol().color().alphaF(), 0.20, places=2)
        renderer.clear()
        self.assertEqual(layer.featureCount(), 0)
        renderer.remove()
        self.assertEqual(QgsProject.instance().mapLayersByName(COVERAGE_LAYER_NAME), [])


@unittest.skipUnless(HAS_QGIS, "QGIS nao disponivel")
class DialogCoverageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from qgis.core import QgsProject
        from qgis.gui import QgsMapCanvas

        QgsProject.instance().clear()
        self.canvas = QgsMapCanvas()
        self.iface = MagicMock()
        self.iface.mainWindow.return_value = None
        self.iface.mapCanvas.return_value = self.canvas

    def tearDown(self):
        from qgis.core import QgsProject

        QgsProject.instance().clear()

    def dialog(self, layer):
        from qgis.core import QgsProject

        from plugin.fortsmart_precision.gui.route_simulation_dialog import RouteSimulationDialog

        QgsProject.instance().addMapLayer(layer)
        dialog = RouteSimulationDialog(self.iface)
        dialog.layer_combo.setLayer(layer)
        dialog.speed_spin.setValue(36.0)  # 10 m/s
        return dialog

    def coverage_layer(self):
        from qgis.core import QgsProject

        from plugin.fortsmart_precision.gui.route_coverage_renderer import COVERAGE_LAYER_NAME

        layers = QgsProject.instance().mapLayersByName(COVERAGE_LAYER_NAME)
        return layers[0] if layers else None

    def test_width_from_machine_field_progress_pause_restart(self):
        layer = two_passes()
        before = snapshot(layer)
        dialog = self.dialog(layer)
        self.assertAlmostEqual(dialog.width_spin.value(), 12.15)

        dialog.start()
        self.assertIn("6.075 m para cada lado", dialog.status_label.text())
        dialog.advance(2.5)
        feature = next(self.coverage_layer().getFeatures())
        box = feature.geometry().boundingBox()
        self.assertAlmostEqual(box.width(), 25.0, places=3)
        self.assertAlmostEqual(box.height(), 12.15, places=3)

        dialog.pause()
        frozen = feature.geometry().asWkt(3)
        dialog.advance(5.0)
        self.assertEqual(next(self.coverage_layer().getFeatures()).geometry().asWkt(3), frozen)
        dialog.resume()
        dialog.advance(12.5)  # fim da P01 + 50 m da P02
        self.assertEqual(self.coverage_layer().featureCount(), 2)
        self.assertEqual(dialog.value_labels["coverage"].text(), "0.18 ha (bruta 0.18 ha)")
        self.assertEqual(dialog.value_labels["overlap"].text(), "0.00 ha")
        validation = dialog.validation

        dialog.restart()
        self.assertEqual(self.coverage_layer().featureCount(), 0)
        self.assertEqual(dialog.value_labels["done"].text(), "0.0 m")
        self.assertEqual(dialog.value_labels["coverage"].text(), "0.00 ha (bruta 0.00 ha)")
        self.assertIs(dialog.validation, validation)
        self.assertEqual(snapshot(layer), before)
        dialog.close()
        self.assertIsNone(self.coverage_layer())

    def test_overlap_is_reported_when_spacing_is_smaller_than_width(self):
        dialog = self.dialog(two_passes(width=10.0, spacing=9.0))
        dialog.start()
        dialog.advance(100.0)

        self.assertEqual(dialog.value_labels["overlap"].text(), "0.01 ha")  # 1 m x 100 m
        self.assertEqual(dialog.value_labels["coverage"].text(), "0.19 ha (bruta 0.20 ha)")
        dialog.close()

    def test_changing_width_clears_coverage_and_no_width_draws_nothing(self):
        dialog = self.dialog(two_passes())
        dialog.start()
        dialog.advance(3.0)
        self.assertEqual(self.coverage_layer().featureCount(), 1)

        dialog.width_spin.setValue(0.0)
        self.assertEqual(self.coverage_layer().featureCount(), 0)
        dialog.start()
        dialog.advance(3.0)
        self.assertEqual(self.coverage_layer().featureCount(), 0)
        self.assertIn("informe a largura", dialog.status_label.text())
        self.assertEqual(dialog.value_labels["coverage"].text(), "-")
        dialog.close()

    def test_hide_coverage_and_show_again(self):
        dialog = self.dialog(two_passes())
        dialog.start()
        dialog.advance(3.0)
        dialog.coverage_check.setChecked(False)
        self.assertIsNone(self.coverage_layer())
        dialog.advance(1.0)
        self.assertIsNone(self.coverage_layer())
        dialog.coverage_check.setChecked(True)
        feature = next(self.coverage_layer().getFeatures())
        self.assertAlmostEqual(feature.geometry().boundingBox().width(), 40.0, places=3)
        dialog.close()


if __name__ == "__main__":
    unittest.main()
