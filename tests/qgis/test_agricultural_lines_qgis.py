import unittest

try:
    from qgis.core import QgsApplication, QgsFeature, QgsGeometry, QgsVectorLayer  # noqa: F401
except Exception as exc:  # pragma: no cover - QGIS nao existe no runtime comum.
    raise unittest.SkipTest(f"QGIS nao disponivel neste runtime: {exc}")

from plugin.fortsmart_precision.gui.operation_configuration_dialog import prepare_metric_work_context


class AgriculturalLinesQgisTest(unittest.TestCase):
    def test_qgis_runtime_placeholder(self):
        """Executado apenas dentro do ambiente QGIS."""
        self.assertTrue(True)

    def test_geographic_field_is_copied_to_automatic_metric_crs(self):
        layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "field", "memory")
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt(
            "POLYGON((-55 -15, -54.99 -15, -54.99 -14.99, -55 -14.99, -55 -15))"
        ))
        layer.dataProvider().addFeature(feature)

        authid, _crs, geometries, start, end = prepare_metric_work_context(
            layer, (-55.0, -15.0), (-54.99, -15.0)
        )

        self.assertEqual(authid, "EPSG:31981")
        self.assertFalse(geometries[0].isEmpty())
        self.assertGreater(abs(end[0] - start[0]), 100.0)


if __name__ == "__main__":
    unittest.main()
