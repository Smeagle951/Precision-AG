# -*- coding: utf-8 -*-
"""Testes de utilitarios de combo de camadas."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

try:
    from qgis.core import QgsWkbTypes

    from plugin.fortsmart_precision.gui.layer_combo_utils import (
        extract_points_from_geometry,
        is_line_like_vector_layer,
        is_point_like_vector_layer,
        is_polygon_like_vector_layer,
    )

    HAS_QGIS = True
except ImportError:
    HAS_QGIS = False


@unittest.skipUnless(HAS_QGIS, "QGIS nao disponivel")
class LayerComboUtilsTest(unittest.TestCase):
    def test_is_point_like_vector_layer_accepts_point_geometry(self):
        from qgis.core import QgsVectorLayer

        layer = MagicMock(spec=QgsVectorLayer)
        layer.geometryType.return_value = QgsWkbTypes.PointGeometry
        self.assertTrue(is_point_like_vector_layer(layer))

    def test_is_point_like_vector_layer_rejects_polygon_geometry(self):
        from qgis.core import QgsVectorLayer

        layer = MagicMock(spec=QgsVectorLayer)
        layer.geometryType.return_value = QgsWkbTypes.PolygonGeometry
        self.assertFalse(is_point_like_vector_layer(layer))

    def test_is_line_like_vector_layer_accepts_line(self):
        from qgis.core import QgsVectorLayer

        layer = MagicMock(spec=QgsVectorLayer)
        layer.isValid.return_value = True
        layer.geometryType.return_value = QgsWkbTypes.LineGeometry
        self.assertTrue(is_line_like_vector_layer(layer))

    def test_is_polygon_like_vector_layer(self):
        from qgis.core import QgsVectorLayer

        layer = MagicMock(spec=QgsVectorLayer)
        layer.geometryType.return_value = QgsWkbTypes.PolygonGeometry
        self.assertTrue(is_polygon_like_vector_layer(layer))

    def test_is_point_like_vector_layer_rejects_non_vector(self):
        layer = MagicMock()
        self.assertFalse(is_point_like_vector_layer(layer))

    def test_extract_points_from_geometry_multipart(self):
        geom = MagicMock()
        geom.isEmpty.return_value = False
        geom.type.return_value = QgsWkbTypes.PointGeometry
        geom.isMultipart.return_value = True
        p1 = MagicMock()
        p1.x.return_value = 1.0
        p1.y.return_value = 2.0
        p2 = MagicMock()
        p2.x.return_value = 3.0
        p2.y.return_value = 4.0
        geom.asMultiPoint.return_value = [p1, p2]
        self.assertEqual(extract_points_from_geometry(geom), [(1.0, 2.0), (3.0, 4.0)])

    def test_prefer_metric_polygon_skips_empty_twin(self):
        """Nao fica em Boundary (EPSG:31981) com 0 feicoes se existe original."""
        from qgis.core import QgsFeature, QgsGeometry, QgsProject, QgsVectorLayer

        from plugin.fortsmart_precision.gui.layer_combo_utils import prefer_metric_polygon_layer

        project = QgsProject.instance()
        # Limpa camadas previas do teste (projeto compartilhado).
        for layer_id in list(project.mapLayers().keys()):
            name = project.mapLayer(layer_id).name()
            if name.startswith("Boundary PV 1"):
                project.removeMapLayer(layer_id)

        empty_twin = QgsVectorLayer(
            "Polygon?crs=EPSG:31981",
            "Boundary PV 1 (EPSG:31981)",
            "memory",
        )
        original = QgsVectorLayer(
            "Polygon?crs=EPSG:4326",
            "Boundary PV 1",
            "memory",
        )
        feat = QgsFeature()
        feat.setGeometry(
            QgsGeometry.fromWkt(
                "POLYGON((-54.48 -15.39, -54.47 -15.39, -54.47 -15.38, -54.48 -15.38, -54.48 -15.39))"
            )
        )
        original.dataProvider().addFeatures([feat])
        original.updateExtents()

        project.addMapLayer(empty_twin, False)
        project.addMapLayer(original, False)

        combo = MagicMock()
        combo.currentLayer.return_value = empty_twin
        chosen = prefer_metric_polygon_layer(combo)

        self.assertIs(chosen, original)
        combo.setLayer.assert_called_with(original)
        self.assertGreater(int(original.featureCount() or 0), 0)
        self.assertEqual(int(empty_twin.featureCount() or 0), 0)

        project.removeMapLayer(empty_twin.id())
        project.removeMapLayer(original.id())


if __name__ == "__main__":
    unittest.main()
