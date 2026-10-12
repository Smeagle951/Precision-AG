# -*- coding: utf-8 -*-
"""Processing + tela: antecipacao editavel e largura fora da distancia de corte longitudinal."""

from __future__ import annotations

import json
import os
import unittest

from qgis.core import (
    QgsApplication,
    QgsFeature,
    QgsGeometry,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsVectorLayer,
)

from plugin.fortsmart_precision.algorithms.simulate_obstacle_border_cut import SimulateObstacleBorderCutAlgorithm

_APP = None
CRS = "EPSG:31981"


def _setup_qgis():
    global _APP
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if QgsApplication.instance() is None:
        _APP = QgsApplication([], True)
        _APP.initQgis()


def _layer(uri, name, wkts):
    layer = QgsVectorLayer(uri, name, "memory")
    features = []
    for wkt in wkts:
        feature = QgsFeature()
        feature.setGeometry(QgsGeometry.fromWkt(wkt))
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    return layer


class ObstacleCutAnticipationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()

    def run_cut(self, width, anticipation):
        lines = _layer(f"LineString?crs={CRS}", "linhas", ["LINESTRING(0 0, 300 0)"])
        posts = _layer(f"Point?crs={CRS}", "Flag", ["POINT(150 0)"])
        algorithm = SimulateObstacleBorderCutAlgorithm().create()
        results, ok = algorithm.run(
            {
                "PASSES": lines, "OBSTACLES": posts, "WORK_WIDTH": width, "REFERENCE_TYPE": 4,
                "WORKING_OFFSET": -8.0, "OBSTACLE_RADIUS": 1.0, "SAFETY_MARGIN": 2.0,
                "ANTICIPATION": anticipation, "STRATEGY": 1, "SIM_WORK_LINES": "TEMPORARY_OUTPUT",
            },
            QgsProcessingContext(), QgsProcessingFeedback(),
        )
        self.assertTrue(ok)
        return json.loads(results["REPORT"])

    def test_processing_cut_uses_zone_and_anticipation_not_width(self):
        wide = self.run_cut(20.0, 2.0)
        narrow = self.run_cut(10.0, 2.0)
        self.assertAlmostEqual(wide["max_cut_distance_m"], 8.0, delta=0.06)
        self.assertAlmostEqual(narrow["max_cut_distance_m"], wide["max_cut_distance_m"], delta=1e-3)
        (detail,) = wide["longitudinal_cuts"]
        self.assertEqual(detail["reference_type"], "TRACTOR_FRONT")
        self.assertEqual(detail["anticipation_m"], 2.0)
        self.assertAlmostEqual(self.run_cut(20.0, 0.0)["max_cut_distance_m"], 6.0, delta=0.06)

    def test_widget_feeds_anticipation_into_machine_geometry(self):
        from plugin.fortsmart_precision.gui.machine_work_geometry_widget import MachineWorkGeometryBox

        box = MachineWorkGeometryBox()
        box.offset_spin.setValue(-8.0)
        box.anticipation_spin.setValue(2.5)
        geometry = box.work_geometry(20.0)
        self.assertEqual(geometry.longitudinal_anticipation_m, 2.5)
        self.assertEqual(geometry.required_cut_distance_m(), 0.0)
        reopened = MachineWorkGeometryBox()
        self.assertEqual(reopened.anticipation_spin.value(), 2.5)  # persistido
        box.anticipation_spin.setValue(0.0)


if __name__ == "__main__":
    unittest.main()
