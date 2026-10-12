# -*- coding: utf-8 -*-
"""Validador de rota no QGIS: camada de avisos, painel e fluxo validar -> simular."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
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

    kinds = {"width_m": "double", "spacing_m": "double", "route_type": "string"}
    spec = "&".join(f"field={name}:{kinds.get(name, 'integer')}" for name in fields)
    layer = QgsVectorLayer(f"LineString?crs={crs}&{spec}", "passadas", "memory")
    items = []
    for points, values in features:
        feature = QgsFeature(layer.fields())
        if points:
            feature.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in points]))
        feature.setAttributes(list(values))
        items.append(feature)
    layer.dataProvider().addFeatures(items)
    layer.updateExtents()
    return layer


def polygon_layer(wkts, crs="EPSG:31982", name="poligonos"):
    from qgis.core import QgsFeature, QgsGeometry, QgsVectorLayer

    layer = QgsVectorLayer(f"Polygon?crs={crs}&field=nome:string", name, "memory")
    items = []
    for label, wkt in wkts:
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt(wkt))
        feature.setAttributes([label])
        items.append(feature)
    layer.dataProvider().addFeatures(items)
    layer.updateExtents()
    return layer


def spaced_passes():
    """P02 a 10,50 m de P01 (esperado 10,00); P03 a 10,00 m de P02."""
    return line_layer([
        (((E0, N0), (E0 + 100, N0)), (1, 0, 10.0)),
        (((E0, N0 + 10.5), (E0 + 100, N0 + 10.5)), (2, 0, 10.0)),
        (((E0, N0 + 20.5), (E0 + 100, N0 + 20.5)), (3, 0, 10.0)),
    ])


def snapshot(layer):
    return sorted((f.id(), f.geometry().asWkt(6), tuple(f.attributes())) for f in layer.getFeatures())


def validate(layer, **kwargs):
    from plugin.fortsmart_precision.gui.route_simulation_source import read_route_source
    from plugin.fortsmart_precision.validator.route_validator_engine import RouteValidatorEngine

    source = read_route_source(layer)
    return source, RouteValidatorEngine().validate(source.passes, **kwargs)


@unittest.skipUnless(HAS_QGIS, "QGIS nao disponivel")
class SourceAndLayerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from qgis.core import QgsProject

        QgsProject.instance().clear()

    def test_source_has_route_type_and_feature_ids(self):
        from plugin.fortsmart_precision.gui.route_simulation_source import read_route_source

        layer = line_layer(
            [
                (((E0, N0), (E0 + 40, N0)), (1, 0, "MAIN")),
                (((E0 + 60, N0), (E0 + 100, N0)), (1, 1, "MAIN")),
                (((E0, N0 + 10), (E0 + 100, N0 + 10)), (2, 0, "border")),
            ],
            fields=("line_number", "segment_index", "route_type"),
        )
        source = read_route_source(layer)

        self.assertEqual([p.route_type for p in source.passes], ["MAIN", "BORDER"])
        self.assertEqual(len(source.feature_ids["P01"]), 2)
        self.assertEqual(len(source.feature_ids["P02"]), 1)

    def test_layer_role_marks_headland_passes_as_border(self):
        from plugin.fortsmart_precision.core.layer_roles import ROLE_PROPERTY
        from plugin.fortsmart_precision.gui.route_simulation_source import read_route_source

        layer = spaced_passes()
        layer.setCustomProperty(ROLE_PROPERTY, "FIELD_HEADLAND_PATH")

        self.assertEqual({p.route_type for p in read_route_source(layer).passes}, {"BORDER"})

    def test_area_and_obstacles_are_read_in_route_crs(self):
        from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry, QgsProject

        from plugin.fortsmart_precision.gui.route_simulation_source import read_allowed_area, read_obstacles

        utm = QgsCoordinateReferenceSystem("EPSG:31982")
        square = QgsGeometry.fromWkt(f"POLYGON(({E0} {N0},{E0+100} {N0},{E0+100} {N0+100},{E0} {N0+100},{E0} {N0}))")
        square.transform(QgsCoordinateTransform(utm, QgsCoordinateReferenceSystem("EPSG:4674"), QgsProject.instance()))
        geo = polygon_layer([("OBS-A", square.asWkt(9))], crs="EPSG:4674")
        before = snapshot(geo)

        area = read_allowed_area(geo, utm)
        obstacles = read_obstacles(geo, utm)

        self.assertAlmostEqual(area.area, 10000.0, delta=5.0)
        self.assertEqual(obstacles[0].id, "OBS-A")
        self.assertEqual(snapshot(geo), before)

    def test_warning_layers_have_fields_style_and_are_replaced(self):
        from qgis.core import QgsCoordinateReferenceSystem, QgsProject

        from plugin.fortsmart_precision.core.layer_roles import is_temporary_preview
        from plugin.fortsmart_precision.gui.route_warning_layer import (
            WARNING_LAYER_NAME,
            RouteWarningLayers,
        )
        from plugin.fortsmart_precision.validator.warning_model import WarningStatus

        _source, result = validate(spaced_passes(), expected_spacing_m=10.0)
        manager = RouteWarningLayers(QgsProject.instance())
        crs = QgsCoordinateReferenceSystem("EPSG:31982")
        manager.show(result, crs)
        points, segments = manager.show(result, crs)

        self.assertEqual(len(QgsProject.instance().mapLayersByName(WARNING_LAYER_NAME)), 1)
        self.assertEqual(points.featureCount(), len(result.warnings))
        self.assertEqual(segments.featureCount(), 1)
        for name in ("warning_id", "warning_type", "severity", "pass_id", "related_id", "message",
                     "expected", "actual", "difference", "status"):
            self.assertIn(name, points.fields().names())
        feature = next(segments.getFeatures())
        self.assertEqual(feature["warning_type"], "SPACING_OUT_OF_TOLERANCE")
        self.assertAlmostEqual(feature["actual"], 10.5, places=6)
        self.assertTrue(is_temporary_preview(points))
        self.assertTrue(points.mapTipTemplate())

        result.set_status(result.warnings[0].id, WarningStatus.RESOLVED)
        manager.sync_status(result)
        self.assertEqual(next(points.getFeatures())["status"], "RESOLVED")
        manager.remove()
        self.assertEqual(QgsProject.instance().mapLayersByName(WARNING_LAYER_NAME), [])


@unittest.skipUnless(HAS_QGIS, "QGIS nao disponivel")
class PanelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from qgis.core import QgsCoordinateReferenceSystem, QgsProject
        from qgis.gui import QgsMapCanvas

        QgsProject.instance().clear()
        self.canvas = QgsMapCanvas()
        self.canvas.resize(800, 600)
        self.canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:31982"))
        self.iface = MagicMock()
        self.iface.mapCanvas.return_value = self.canvas

    def tearDown(self):
        from qgis.core import QgsProject

        QgsProject.instance().clear()

    def panel_for(self, layer, **kwargs):
        from qgis.core import QgsProject

        from plugin.fortsmart_precision.gui.route_warning_panel import RouteWarningPanel

        QgsProject.instance().addMapLayer(layer)
        source, result = validate(layer, **kwargs)
        panel = RouteWarningPanel(self.iface)
        panel.set_result(result, source.crs, {p.id: p.segments for p in source.passes}, source.feature_ids, layer)
        return panel, result

    def test_filter_select_zoom_highlight_and_status(self):
        from shapely.geometry import Point

        from plugin.fortsmart_precision.validator.obstacle_validator import ObstacleInput
        from plugin.fortsmart_precision.validator.warning_model import WarningStatus

        layer = spaced_passes()
        obstacle = Point(E0 + 50, N0 + 20.5).buffer(3.0)
        panel, result = self.panel_for(layer, expected_spacing_m=10.0, obstacles=[ObstacleInput("OBS", obstacle)])

        self.assertIn("CRITICOS: 1", panel.summary_label.text())
        panel.filter_combo.setCurrentIndex(panel.filter_combo.findData("SPACING"))
        self.assertEqual([w.warning_type.value for w in panel.visible_warnings()], ["SPACING_OUT_OF_TOLERANCE"])
        panel.table.selectRow(0)
        warning = panel.selected_warning()
        self.assertEqual(warning.pass_id, "P02")
        self.assertIn("Esperado: 10.00 m", panel.details.toPlainText())
        self.assertAlmostEqual(panel.highlighter.pass_band.asGeometry().length(), 100.0, places=3)
        self.assertAlmostEqual(panel.highlighter.related_band.asGeometry().length(), 100.0, places=3)
        self.assertTrue(self.canvas.extent().contains(E0 + 50, N0 + 10.5))
        self.assertLess(self.canvas.extent().width(), 400.0)

        panel.set_selected_status(WarningStatus.REVIEWED)
        self.assertIs(result.warning(warning.id).status, WarningStatus.REVIEWED)
        self.assertEqual(panel.table.item(0, 5).text(), "Revisado")
        panel.filter_combo.setCurrentIndex(panel.filter_combo.findData("OBSTACLE"))
        self.assertEqual(len(panel.visible_warnings()), 1)
        panel.cleanup()

    def test_fix_only_selects_and_enables_editing(self):
        layer = spaced_passes()
        before = snapshot(layer)
        panel, _result = self.panel_for(layer, expected_spacing_m=10.0)
        panel.table.selectRow(0)

        self.assertTrue(panel.fix_selected())

        self.assertTrue(layer.isEditable())
        self.assertEqual(layer.selectedFeatureCount(), 1)
        self.assertEqual(next(layer.getSelectedFeatures())["line_number"], 2)
        self.assertEqual(snapshot(layer), before)
        layer.rollBack()
        panel.cleanup()

    def test_map_click_selects_warning_and_json_export(self):
        from qgis.core import QgsPointXY

        panel, _result = self.panel_for(spaced_passes(), expected_spacing_m=10.0)

        warning = panel.pick_at(QgsPointXY(E0 + 50, N0 + 10.6), 1.0)

        self.assertEqual(warning.warning_type.value, "SPACING_OUT_OF_TOLERANCE")
        self.assertIs(panel.selected_warning(), warning)
        self.assertIsNone(panel.pick_at(QgsPointXY(E0 + 50, N0 + 60), 1.0))
        with tempfile.TemporaryDirectory() as tmp:
            data = json.loads(panel.export_json(str(Path(tmp) / "v.json")).read_text(encoding="utf-8"))
        self.assertEqual(data["route_count"], 3)
        self.assertEqual(data["warning"], 1)
        panel.cleanup()


@unittest.skipUnless(HAS_QGIS, "QGIS nao disponivel")
class DialogValidationTest(unittest.TestCase):
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
        dialog.speed_spin.setValue(36.0)
        return dialog

    def test_validate_button_then_simulate_with_open_warnings(self):
        from qgis.core import QgsProject

        from plugin.fortsmart_precision.gui.route_warning_layer import WARNING_LAYER_NAME

        layer = spaced_passes()
        area = polygon_layer([("limite", f"POLYGON(({E0-1} {N0-5},{E0+101} {N0-5},{E0+101} {N0+25},{E0-1} {N0+25},{E0-1} {N0-5}))")])
        QgsProject.instance().addMapLayer(area)
        before = snapshot(layer)
        dialog = self.dialog(layer)
        dialog.area_combo.setLayer(area)

        self.assertAlmostEqual(dialog.spacing_spin.value(), 10.0)
        result = dialog.validate_route()

        self.assertEqual((result.critical_count, result.warning_count), (0, 1))
        self.assertEqual(dialog.tabs.currentIndex(), 1)
        self.assertEqual(len(QgsProject.instance().mapLayersByName(WARNING_LAYER_NAME)), 1)
        dialog.start()
        self.assertTrue(dialog.timer.isActive())
        self.assertEqual(dialog.value_labels["warnings"].text(), "1")  # P01 e a vizinha do aviso
        dialog.advance(10.5)
        self.assertIn("P02", dialog.value_labels["pass"].text())
        self.assertEqual(dialog.value_labels["warnings"].text(), "1")
        dialog.advance(10.0)
        self.assertIn("P03", dialog.value_labels["pass"].text())
        self.assertEqual(dialog.value_labels["warnings"].text(), "nenhum")
        dialog.advance(100.0)
        self.assertTrue(dialog.engine.state.is_finished)
        self.assertIs(dialog.validation, result)
        self.assertEqual(snapshot(layer), before)
        dialog.close()

    def test_invalid_geometry_blocks_simulation(self):
        layer = line_layer([(((E0, N0), (E0 + 100, N0)), (1, 0, 1.0)), (((E0, N0 + 20), (E0, N0 + 20)), (2, 0, 1.0))])
        dialog = self.dialog(layer)

        dialog.start()

        self.assertIsNone(dialog.engine)
        self.assertIn("SIMULATION_ROUTE_INVALID", dialog.status_label.text())
        self.assertEqual(dialog.validation.blocked_pass_ids(), ["P02"])
        dialog.close()

    def test_obstacle_crossing_is_reported_but_simulation_runs(self):
        from qgis.core import QgsProject

        layer = spaced_passes()
        obstacles = polygon_layer(
            [("Pivo", f"POLYGON(({E0+45} {N0-3},{E0+55} {N0-3},{E0+55} {N0+3},{E0+45} {N0+3},{E0+45} {N0-3}))")],
            name="obstaculos",
        )
        QgsProject.instance().addMapLayer(obstacles)
        dialog = self.dialog(layer)
        dialog.obstacle_combo.setLayer(obstacles)

        dialog.start()

        self.assertIsNotNone(dialog.engine)
        self.assertEqual(dialog.validation.critical_count, 1)
        self.assertEqual(dialog.value_labels["warnings"].text(), "2 (1 critico(s))")
        dialog.close()


if __name__ == "__main__":
    unittest.main()
