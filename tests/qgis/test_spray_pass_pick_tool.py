# -*- coding: utf-8 -*-
"""Escolha da passada de pulverizacao com clique no mapa (cruzamento)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
)
from qgis.gui import QgsMapCanvas, QgsMapMouseEvent, QgsMapToolPan
from qgis.PyQt.QtCore import QEvent, QPoint, Qt
from qgis.PyQt.QtGui import QKeyEvent

from plugin.fortsmart_precision.gui.fortsmart_workspace_dialog import (
    SPRAY_CROSS_SOURCE_EXISTING_PASSES,
    FortSmartWorkspaceDialog,
)
from plugin.fortsmart_precision.gui.maptools.spray_pass_pick_tool import (
    SprayPassPickTool,
    pick_line_feature,
    spray_pick_candidate_layers,
)
from tests.qgis.test_spray_preview_layers_baseline import _setup_qgis

X0, Y0 = 500000.0, 8670000.0
UTM = "EPSG:31981"
CURVE = [(100, 100), (400, 300), (700, 320)]
STRAIGHT = [(100, 500), (700, 500)]


def _wkt(points):
    return "LINESTRING(" + ", ".join(f"{X0 + x} {Y0 + y}" for x, y in points) + ")"


def _line_layer(name, crs, wkts):
    layer = QgsVectorLayer(f"LineString?crs={crs}", name, "memory")
    features = []
    for wkt in wkts:
        feature = QgsFeature()
        feature.setGeometry(QgsGeometry.fromWkt(wkt))
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    return layer


class _CanvasIface:
    def __init__(self, canvas):
        self.canvas = canvas
        self.bar = MagicMock()

    @staticmethod
    def mainWindow():
        return None

    def mapCanvas(self):
        return self.canvas

    @staticmethod
    def activeLayer():
        return None

    def messageBar(self):
        return self.bar


class SprayPassPickCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()

    def setUp(self):
        project = QgsProject.instance()
        project.clear()
        project.setCrs(QgsCoordinateReferenceSystem(UTM))
        self.utm = _line_layer("Curva adaptada (EPSG:31981)", UTM, [_wkt(CURVE), _wkt(STRAIGHT)])
        to_geo = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem(UTM), QgsCoordinateReferenceSystem("EPSG:4326"), project
        )
        geo_wkts = []
        for feature in self.utm.getFeatures():
            geometry = QgsGeometry(feature.geometry())
            geometry.transform(to_geo)
            geo_wkts.append(geometry.asWkt())
        self.geo = _line_layer("Curva adaptada", "EPSG:4326", geo_wkts)
        self.planting = _line_layer("12_Passadas_Plantio", UTM, [_wkt(CURVE)])
        project.addMapLayers([self.utm, self.geo, self.planting])
        self.set_visible(self.geo, False)
        self.canvas = QgsMapCanvas()
        self.canvas.resize(800, 600)
        self.canvas.setDestinationCrs(QgsCoordinateReferenceSystem(UTM))
        self.canvas.setExtent(QgsRectangle(X0, Y0, X0 + 800, Y0 + 600))
        self.curve_id, self.straight_id = [f.id() for f in self.utm.getFeatures()]

    def tearDown(self):
        self.canvas.deleteLater()
        QgsProject.instance().clear()

    @staticmethod
    def set_visible(layer, visible):
        QgsProject.instance().layerTreeRoot().findLayer(layer.id()).setItemVisibilityChecked(visible)

    def click(self, tool, x, y, *, shift=False, button=Qt.LeftButton):
        pixel = self.canvas.getCoordinateTransform().transform(QgsPointXY(X0 + x, Y0 + y))
        modifiers = Qt.ShiftModifier if shift else Qt.NoModifier
        event = QgsMapMouseEvent(
            self.canvas, QEvent.MouseButtonRelease, QPoint(int(pixel.x()), int(pixel.y())),
            button, button, modifiers,
        )
        tool.canvasReleaseEvent(event)

    def pick(self, x, y):
        return pick_line_feature(
            spray_pick_candidate_layers(),
            QgsPointXY(X0 + x, Y0 + y),
            QgsCoordinateReferenceSystem(UTM),
            tolerance=5.0,
        )


class PickLineFeatureTests(SprayPassPickCase):
    def test_candidates_skip_hidden_and_planting_layers(self):
        self.assertEqual(spray_pick_candidate_layers(), [self.utm])

    def test_pick_nearest_visible_spray_line(self):
        self.assertEqual(self.pick(400, 302), (self.utm, self.curve_id))
        self.assertEqual(self.pick(300, 498), (self.utm, self.straight_id))

    def test_pick_visible_layer_in_other_crs(self):
        self.set_visible(self.utm, False)
        self.set_visible(self.geo, True)
        layer, _fid = self.pick(400, 302)
        self.assertIs(layer, self.geo)

    def test_click_far_from_lines_returns_none(self):
        self.assertIsNone(self.pick(400, 420))


class SprayPassPickToolTests(SprayPassPickCase):
    def make_tool(self):
        tool = SprayPassPickTool(self.canvas)
        self.finished = []
        tool.finished.connect(self.finished.append)
        return tool

    def test_single_click_selects_only_that_pass_and_finishes(self):
        self.utm.selectByIds([self.straight_id])
        tool = self.make_tool()
        self.click(tool, 400, 301)
        self.assertEqual(self.utm.selectedFeatureIds(), [self.curve_id])
        self.assertEqual(self.finished, [self.utm])

    def test_shift_click_adds_passes_until_enter(self):
        tool = self.make_tool()
        self.click(tool, 400, 301, shift=True)
        self.click(tool, 300, 499, shift=True)
        self.assertEqual(self.finished, [])
        self.assertEqual(sorted(self.utm.selectedFeatureIds()), sorted([self.curve_id, self.straight_id]))
        tool.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
        self.assertEqual(self.finished, [self.utm])

    def test_escape_restores_previous_selection(self):
        self.utm.selectByIds([self.straight_id])
        tool = self.make_tool()
        self.click(tool, 400, 301, shift=True)
        tool.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
        self.assertEqual(self.utm.selectedFeatureIds(), [self.straight_id])
        self.assertEqual(self.finished, [None])

    def test_click_on_empty_area_keeps_tool_active(self):
        tool = self.make_tool()
        messages = []
        tool.message.connect(messages.append)
        self.click(tool, 400, 420)
        self.assertEqual(self.finished, [])
        self.assertEqual(self.utm.selectedFeatureCount(), 0)
        self.assertEqual(len(messages), 1)


class WorkspacePickButtonTests(SprayPassPickCase):
    def test_button_picks_on_map_and_returns_to_dialog(self):
        iface = _CanvasIface(self.canvas)
        dialog = FortSmartWorkspaceDialog(iface)
        try:
            pan = QgsMapToolPan(self.canvas)
            self.canvas.setMapTool(pan)
            dialog.spray_line_combo.setLayer(self.planting)

            dialog.pick_spray_pass_btn.click()
            tool = self.canvas.mapTool()
            self.assertIsInstance(tool, SprayPassPickTool)
            self.assertTrue(dialog.isMinimized())
            self.assertEqual(
                dialog.spray_source_mode_combo.currentData(), SPRAY_CROSS_SOURCE_EXISTING_PASSES
            )

            self.click(tool, 400, 301)
            self.assertIs(self.canvas.mapTool(), pan)
            self.assertFalse(dialog.isMinimized())
            self.assertIs(dialog.spray_line_combo.currentLayer(), self.utm)
            self.assertTrue(dialog.spray_passes_selected_only.isChecked())
            self.assertIn("selecionadas: 1 de 2", dialog.spray_cross_selection_summary.text())
            self.assertEqual(self.utm.selectedFeatureIds(), [self.curve_id])
        finally:
            dialog.reject()


if __name__ == "__main__":
    unittest.main()
