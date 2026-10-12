# -*- coding: utf-8 -*-
"""Selecao explicita das fontes no cruzamento pulverizacao x plantio."""

from __future__ import annotations

import os
import unittest

from qgis.core import QgsApplication, QgsFeature, QgsGeometry, QgsProject, QgsVectorLayer

from plugin.fortsmart_precision.gui.line_import_utils import spray_passes_from_line_layer


_APP = None


def _setup_qgis():
    global _APP
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if QgsApplication.instance() is None:
        _APP = QgsApplication([], True)
        _APP.initQgis()


class ControlledTrafficSelectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()

    def setUp(self):
        self.layer = QgsVectorLayer(
            "LineString?crs=EPSG:31982", "passadas_reais", "memory"
        )
        features = []
        for wkt in (
            "LINESTRING (0 0, 50 0, 100 10)",
            "LINESTRING (0 20, 40 22, 100 35)",
            "LINESTRING (0 40, 100 60)",
        ):
            feature = QgsFeature()
            feature.setGeometry(QgsGeometry.fromWkt(wkt))
            features.append(feature)
        self.layer.dataProvider().addFeatures(features)
        QgsProject.instance().addMapLayer(self.layer)

    def tearDown(self):
        QgsProject.instance().clear()

    def test_no_selection_never_imports_all_features(self):
        passes = spray_passes_from_line_layer(
            self.layer,
            self.layer.crs(),
            width_m=36.0,
            selected_only=True,
        )
        self.assertEqual(passes, [])

    def test_selected_curves_and_multiple_passes_are_preserved(self):
        feature_ids = [feature.id() for feature in self.layer.getFeatures()]
        self.layer.selectByIds(feature_ids[:2])
        passes = spray_passes_from_line_layer(
            self.layer,
            self.layer.crs(),
            width_m=36.0,
            selected_only=True,
        )
        self.assertEqual(len(passes), 2)
        self.assertTrue(all(len(item.path_points) == 3 for item in passes))
        self.assertEqual(len({item.fs_id for item in passes}), 2)

    def test_changing_selection_changes_source_without_touching_geometry(self):
        features = list(self.layer.getFeatures())
        original_wkts = [feature.geometry().asWkt() for feature in features]

        self.layer.selectByIds([features[0].id()])
        first = spray_passes_from_line_layer(
            self.layer, self.layer.crs(), selected_only=True
        )
        self.layer.selectByIds([features[2].id()])
        second = spray_passes_from_line_layer(
            self.layer, self.layer.crs(), selected_only=True
        )

        self.assertNotEqual(first[0].fs_id, second[0].fs_id)
        self.assertEqual(
            original_wkts,
            [feature.geometry().asWkt() for feature in self.layer.getFeatures()],
        )


if __name__ == "__main__":
    unittest.main()
