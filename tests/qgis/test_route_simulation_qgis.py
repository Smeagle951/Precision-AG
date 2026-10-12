# -*- coding: utf-8 -*-
"""Simulador de rota no QGIS: leitura da camada, overlay e tela de controle."""

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


def line_layer(features, crs="EPSG:31982", fields=("line_number", "segment_index", "width_m")):
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsVectorLayer

    spec = "&".join(
        f"field={name}:{'double' if name == 'width_m' else 'integer'}" for name in fields
    )
    layer = QgsVectorLayer(f"LineString?crs={crs}&{spec}", "passadas", "memory")
    provider = layer.dataProvider()
    items = []
    for points, values in features:
        feature = QgsFeature(layer.fields())
        if points:
            feature.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in points]))
        feature.setAttributes(list(values))
        items.append(feature)
    provider.addFeatures(items)
    layer.updateExtents()
    return layer


def three_passes():
    return line_layer([
        (((E0, N0), (E0 + 100, N0)), (1, 0, 20.0)),
        (((E0, N0 + 20), (E0 + 40, N0 + 20)), (2, 0, 20.0)),
        (((E0 + 60, N0 + 20), (E0 + 100, N0 + 20)), (2, 1, 20.0)),
        (((E0, N0 + 40), (E0 + 100, N0 + 40)), (3, 0, 20.0)),
    ])


def snapshot(layer):
    return sorted((f.id(), f.geometry().asWkt(6), tuple(f.attributes())) for f in layer.getFeatures())


@unittest.skipUnless(HAS_QGIS, "QGIS nao disponivel")
class RouteSourceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_reads_logical_passes_without_editing_layer(self):
        from plugin.fortsmart_precision.gui.route_simulation_source import read_route_source

        layer = three_passes()
        before = snapshot(layer)
        source = read_route_source(layer)
        self.assertEqual([p.id for p in source.passes], ["P01", "P02", "P03"])
        self.assertEqual(len(source.passes[1].segments), 2)
        self.assertEqual(source.sequence_source, "attribute")
        self.assertEqual(source.crs.authid(), "EPSG:31982")
        self.assertEqual(snapshot(layer), before)

    def test_geographic_layer_is_measured_in_utm(self):
        from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY, QgsProject

        from plugin.fortsmart_precision.core.simulation_route import build_ordered_route
        from plugin.fortsmart_precision.gui.route_simulation_source import read_route_source

        to_geo = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem("EPSG:31982"), QgsCoordinateReferenceSystem("EPSG:4674"), QgsProject.instance()
        )
        a = to_geo.transform(QgsPointXY(E0, N0))
        b = to_geo.transform(QgsPointXY(E0 + 100, N0))
        layer = line_layer([(((a.x(), a.y()), (b.x(), b.y())), (1, 0, 20.0))], crs="EPSG:4674")
        source = read_route_source(layer)
        self.assertFalse(source.crs.isGeographic())
        route = build_ordered_route(source.passes, crs_authid=source.crs.authid())
        self.assertAlmostEqual(route.total_length_m, 100.0, delta=0.5)

    def test_unnumbered_layer_reports_spatial_order_and_empty_geometry_is_invalid(self):
        from plugin.fortsmart_precision.core.simulation_route import RouteValidationError, build_ordered_route
        from plugin.fortsmart_precision.gui.route_simulation_source import read_route_source

        layer = line_layer(
            [(((E0, N0 + 20), (E0 + 100, N0 + 20)), (5.0,)), (((E0, N0), (E0 + 100, N0)), (5.0,))],
            fields=("width_m",),
        )
        self.assertIn("spatial_order", read_route_source(layer).sequence_source)
        broken = line_layer([(((E0, N0), (E0 + 100, N0)), (1, 0, 1.0)), ((), (2, 0, 1.0))])
        with self.assertRaises(RouteValidationError) as ctx:
            build_ordered_route(read_route_source(broken).passes)
        self.assertTrue(any("geometria vazia" in p for p in ctx.exception.problems))


@unittest.skipUnless(HAS_QGIS, "QGIS nao disponivel")
class RendererTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_overlay_shows_only_travelled_part(self):
        from qgis.core import QgsCoordinateReferenceSystem
        from qgis.gui import QgsMapCanvas

        from plugin.fortsmart_precision.core.route_simulation_engine import RouteSimulationEngine
        from plugin.fortsmart_precision.core.simulation_route import build_ordered_route
        from plugin.fortsmart_precision.domain.machine_profile import MachineProfile
        from plugin.fortsmart_precision.gui.route_simulation_renderer import RouteSimulationRenderer
        from plugin.fortsmart_precision.gui.route_simulation_source import read_route_source

        crs = QgsCoordinateReferenceSystem("EPSG:31982")
        canvas = QgsMapCanvas()
        canvas.setDestinationCrs(crs)
        source = read_route_source(three_passes())
        engine = RouteSimulationEngine(build_ordered_route(source.passes), MachineProfile("m", "m", width_m=20.0), 10.0)
        renderer = RouteSimulationRenderer(canvas, crs)
        engine.start()
        engine.advance(3.0)
        renderer.render(engine)
        self.assertTrue(renderer.completed_band.asGeometry().isEmpty())
        self.assertAlmostEqual(renderer.executed_band.asGeometry().length(), 30.0, places=3)
        self.assertAlmostEqual(renderer.remaining_band.asGeometry().length(), 70.0, places=3)
        from qgis.core import QgsGeometry, QgsPointXY

        machine = renderer.machine_band.asGeometry()
        self.assertTrue(machine.contains(QgsGeometry.fromPointXY(QgsPointXY(E0 + 30.0, N0))))
        self.assertAlmostEqual(machine.boundingBox().height(), 20.0, places=3)
        engine.advance(8.0)
        renderer.render(engine)
        self.assertAlmostEqual(renderer.completed_band.asGeometry().length(), 100.0, places=3)
        self.assertAlmostEqual(renderer.executed_band.asGeometry().length(), 10.0, places=3)
        renderer.remove()
        self.assertTrue(all(band.scene() is None for band in renderer.bands()))


@unittest.skipUnless(HAS_QGIS, "QGIS nao disponivel")
class DialogTest(unittest.TestCase):
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

    def test_controls_and_progress(self):
        layer = three_passes()
        before = snapshot(layer)
        dialog = self.dialog(layer)
        self.assertAlmostEqual(dialog.width_spin.value(), 20.0)
        dialog.start()
        self.assertTrue(dialog.timer.isActive())
        self.assertEqual(dialog.value_labels["passes"].text(), "0 / 1 / 2")
        dialog.advance(5.0)
        self.assertIn("P01 (1/3) 50.0 / 100.0 m", dialog.value_labels["pass"].text())
        self.assertEqual(dialog.value_labels["total"].text(), "280.0 m")  # P02 = 2 trechos de 40 m
        self.assertEqual(dialog.value_labels["percent"].text(), "17.9 %")
        dialog.pause()
        self.assertFalse(dialog.timer.isActive())
        dialog.advance(5.0)
        self.assertIn("50.0 / 100.0", dialog.value_labels["pass"].text())
        dialog.resume()
        self.assertTrue(dialog.timer.isActive())
        dialog.advance(6.0)
        self.assertEqual(dialog.value_labels["passes"].text(), "1 / 1 / 1")
        dialog.restart()
        self.assertEqual(dialog.value_labels["percent"].text(), "0.0 %")
        dialog.stop()
        self.assertFalse(dialog.timer.isActive())
        dialog.start()
        dialog.advance(100.0)
        self.assertEqual(dialog.value_labels["percent"].text(), "100.0 %")
        self.assertFalse(dialog.timer.isActive())
        self.assertIn("concluida", dialog.status_label.text())
        self.assertEqual(snapshot(layer), before)
        dialog.close()
        self.assertIsNone(dialog.renderer)

    def test_invalid_route_is_reported(self):
        layer = line_layer([(((E0, N0), (E0 + 100, N0)), (1, 0, 1.0)), (((E0, N0 + 20), (E0, N0 + 20)), (2, 0, 1.0))])
        dialog = self.dialog(layer)
        dialog.start()
        self.assertIsNone(dialog.engine)
        self.assertIn("SIMULATION_ROUTE_INVALID", dialog.status_label.text())
        dialog.close()


if __name__ == "__main__":
    unittest.main()
