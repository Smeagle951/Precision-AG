# -*- coding: utf-8 -*-
"""Etapa 0E: leitor da selecao nativa e gerenciador central de previas, num QGIS real."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsProject,
    QgsVectorLayer,
)
from qgis.gui import QgsMapCanvas, QgsRubberBand
from qgis.PyQt.QtCore import QVariant

from plugin.fortsmart_precision import feature_flags
from plugin.fortsmart_precision.core import selection_reader as sr
from plugin.fortsmart_precision.gui import preview_manager as pm
from plugin.fortsmart_precision.gui.agrocad_panel import AgroCadPanel
from plugin.fortsmart_precision.gui.preview_manager import PreviewManager, PreviewStyle
from tests.qgis.test_agrocad_panel_qgis import (
    CRS,
    LINES,
    SQUARE,
    _Base,
    _Iface,
    _layer,
    _properties,
    _role_layer,
    _setup_qgis,
    _tree_signature,
    _wait,
)

PREVIEW_ON = (lambda name, settings=None: name == feature_flags.ENABLE_PREVIEW_MANAGER_V1)
ALL_OFF = (lambda name, settings=None: False)


def _with_ids(layer, values, name="fs_id"):
    layer.dataProvider().addAttributes([QgsField(name, QVariant.String)])
    layer.updateFields()
    index = layer.fields().indexOf(name)
    changes = {feature.id(): {index: value} for feature, value in zip(layer.getFeatures(), values)}
    layer.dataProvider().changeAttributeValues(changes)
    return layer


def _write_ogr(path, driver, table="linhas"):
    from osgeo import ogr, osr

    source = ogr.GetDriverByName(driver).CreateDataSource(str(path))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(31981)
    target = source.CreateLayer(table, srs, ogr.wkbLineString)
    for wkt in LINES:
        feature = ogr.Feature(target.GetLayerDefn())
        feature.SetGeometry(ogr.CreateGeometryFromWkt(wkt))
        target.CreateFeature(feature)
        feature = None
    source = None


def _scene_bands(canvas):
    return [item for item in canvas.scene().items() if isinstance(item, QgsRubberBand)]


def _canvas():
    canvas = QgsMapCanvas()
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem(CRS))
    return canvas


class _CanvasIface(_Iface):
    def __init__(self, canvas, **kwargs):
        super().__init__(**kwargs)
        self._canvas = canvas

    def mapCanvas(self):
        return self._canvas


class SelectionReaderQgisTest(_Base):
    def _service(self):
        from plugin.fortsmart_precision.core.project_context import ProjectContextService

        return ProjectContextService(self.project)

    def test_one_and_many_lines_with_role_field_and_crs(self):
        layer = _with_ids(_role_layer("05_Passadas", "TL-1", "LineString", LINES), ["P1", "P2", "P3"])
        self._place(layer, "TL-1", "10_PLANEJAMENTO")
        ids = [feature.id() for feature in layer.getFeatures()]
        layer.selectByIds(ids[:1])
        one = sr.read_selection(layer, self._service())
        self.assertTrue(one.single_line)
        self.assertEqual(one.layer_id, layer.id())
        self.assertEqual(one.role, "GUIDANCE_TRACK")
        self.assertEqual(one.field.field_id, "TL-1")
        self.assertEqual(one.crs.authid, CRS)
        self.assertEqual([item.key for item in one.features], ["ATTRIBUTE:P1"])
        layer.selectByIds(ids)
        many = sr.read_selection(layer, self._service())
        self.assertTrue(many.multiple_lines)
        self.assertEqual([item.value for item in many.features], ["P1", "P2", "P3"])
        self.assertEqual(many.diagnostics, ())

    def test_reading_follows_qgis_and_keeps_no_parallel_selection(self):
        layer = _layer("LineString", "linhas", LINES)
        self.project.addMapLayer(layer)
        ids = [feature.id() for feature in layer.getFeatures()]
        layer.selectByIds(ids[:2])
        first = sr.read_selection(layer, self._service())
        self.assertEqual(first.fids, tuple(ids[:2]))
        layer.selectByIds(ids[2:])
        self.assertEqual(sr.read_selection(layer, self._service()).fids, tuple(ids[2:]))
        self.assertEqual(sorted(layer.selectedFeatureIds()), ids[2:])
        self.assertFalse(layer.isModified())
        self.assertEqual({item.source for item in first.features}, {sr.ID_SESSION})

    def test_geopackage_uses_the_file_key_and_shapefile_is_unstable(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        _write_ogr(tmp / "linhas.gpkg", "GPKG")
        _write_ogr(tmp / "linhas.shp", "ESRI Shapefile")
        gpkg = QgsVectorLayer(f"{tmp / 'linhas.gpkg'}|layername=linhas", "gpkg", "ogr")
        shp = QgsVectorLayer(str(tmp / "linhas.shp"), "shp", "ogr")
        self.project.addMapLayers([gpkg, shp])
        for layer in (gpkg, shp):
            layer.selectAll()
        self.assertEqual({item.source for item in sr.read_selection(gpkg, self._service()).features},
                         {sr.ID_PROVIDER_KEY})
        unstable = sr.read_selection(shp, self._service())
        self.assertEqual({item.source for item in unstable.features}, {sr.ID_UNSTABLE})
        self.assertIn(sr.UNSTABLE_IDENTITY, {item.code for item in unstable.diagnostics})
        self.project.removeAllMapLayers()

    def test_new_features_duplicates_and_limit(self):
        layer = _with_ids(_layer("LineString", "linhas", LINES), ["A", "A", ""])
        self.project.addMapLayer(layer)
        layer.startEditing()
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt("LineString(40 0, 40 100)"))
        layer.addFeature(feature)
        layer.selectAll()
        info = sr.read_selection(layer, self._service())
        self.assertEqual(info.count, 4)
        sources = sorted(item.source for item in info.features)
        self.assertEqual(sources, [sr.ID_ATTRIBUTE, sr.ID_ATTRIBUTE, sr.ID_NEW, sr.ID_SESSION])
        codes = {item.code for item in info.diagnostics}
        self.assertTrue({sr.DUPLICATE_IDENTITY, sr.UNSAVED_FEATURES, sr.SESSION_IDENTITY} <= codes)
        limited = sr.read_selection(layer, self._service(), limit=2)
        self.assertTrue(limited.truncated)
        self.assertEqual(len(limited.features), 2)
        layer.rollBack()

    def test_raster_or_no_layer_returns_none(self):
        self.assertIsNone(sr.read_selection(None, self._service()))
        self.assertEqual(sr.selected_geometries(None), [])


class PreviewManagerQgisTest(_Base):
    def setUp(self):
        super().setUp()
        self.canvas = _canvas()
        self.addCleanup(self.canvas.deleteLater)
        self.manager = PreviewManager(self.canvas, project=self.project)
        self.addCleanup(self.manager.dispose)

    def test_lines_polygons_and_points_get_distinct_bands_without_layers_or_files(self):
        before_layers = len(self.project.mapLayers())
        before_files = set(self.tmp.iterdir())
        line = QgsGeometry.fromWkt(LINES[0])
        polygon = QgsGeometry.fromWkt(SQUARE)
        point = QgsGeometry.fromWkt("Point(5 5)")
        self.assertEqual(self.manager.show_geometries([line, polygon, point], ["line", "polygon", "point"]), 3)
        self.assertEqual(self.manager.count, 3)
        self.assertEqual(self.manager.band_count, 3)
        self.assertEqual(len(_scene_bands(self.canvas)), 3)
        self.assertEqual(len(self.project.mapLayers()), before_layers)
        self.assertEqual(set(self.tmp.iterdir()), before_files)

    def test_categories_are_visually_distinct(self):
        line = QgsGeometry.fromWkt(LINES[0])
        self.manager.show_geometry(line, pm.STYLE_HIGHLIGHT)
        self.manager.show_geometry(line, pm.STYLE_REFERENCE)
        colors = {band.strokeColor().name() for band in _scene_bands(self.canvas)}
        self.assertEqual(len(colors), 2)
        self.manager.show_geometry(QgsGeometry.fromWkt(LINES[1]), pm.STYLE_HIGHLIGHT)
        self.assertEqual(self.manager.band_count, 2)
        self.assertEqual(self.manager.count, 3)

    def test_future_categories_are_registered_not_hardcoded(self):
        self.manager.register_style("rastro_exemplo", PreviewStyle((10, 20, 30, 255), 4.0, line="dash"))
        self.assertTrue(self.manager.show_geometry(QgsGeometry.fromWkt(LINES[0]), "rastro_exemplo"))
        with self.assertRaises(KeyError):
            self.manager.show_geometry(QgsGeometry.fromWkt(LINES[0]), "nao_existe")
        with self.assertRaises(ValueError):
            self.manager.show_geometries([QgsGeometry.fromWkt(LINES[0])], ["line", "line"])

    def test_geometry_is_reprojected_to_the_canvas(self):
        geographic = QgsGeometry.fromWkt("LineString(-54.6 -20.4, -54.6 -20.3)")
        self.manager.show_geometry(geographic, crs=QgsCoordinateReferenceSystem("EPSG:4326"))
        point = _scene_bands(self.canvas)[0].asGeometry().asPolyline()[0]
        self.assertGreater(point.x(), 100000)
        self.assertGreater(point.y(), 1000000)

    def test_clear_removes_bands_and_signals(self):
        for _ in range(10):
            self.manager.show_geometry(QgsGeometry.fromWkt(LINES[0]))
            self.assertEqual(self.manager.connection_count, 4)
            self.manager.clear()
            self.assertEqual(self.manager.connection_count, 0)
        self.assertEqual(_scene_bands(self.canvas), [])
        self.assertEqual(self.manager.count, 0)
        self.assertEqual(self.manager.clear(), 0)

    def test_project_switch_clears(self):
        self.manager.show_geometry(QgsGeometry.fromWkt(LINES[0]))
        self.project.clear()
        self.assertEqual(self.manager.count, 0)
        self.assertEqual(_scene_bands(self.canvas), [])

    def test_removing_the_source_layer_clears_only_its_previews(self):
        first = _layer("LineString", "a", LINES)
        second = _layer("LineString", "b", LINES)
        self.project.addMapLayers([first, second])
        self.manager.show_geometry(QgsGeometry.fromWkt(LINES[0]), source_layer_id=first.id())
        self.manager.show_geometry(QgsGeometry.fromWkt(LINES[1]), source_layer_id=second.id())
        self.manager.show_geometry(QgsGeometry.fromWkt(LINES[2]))
        self.project.removeMapLayer(first.id())
        self.assertEqual(self.manager.count, 2)
        self.assertEqual(len(_scene_bands(self.canvas)), 2)

    def test_dispose_is_final_and_idempotent(self):
        self.manager.show_geometry(QgsGeometry.fromWkt(LINES[0]))
        self.manager.dispose()
        self.manager.dispose()
        self.assertTrue(self.manager.disposed)
        self.assertEqual(self.manager.connection_count, 0)
        self.assertEqual(_scene_bands(self.canvas), [])
        with self.assertRaises(RuntimeError):
            self.manager.show_geometry(QgsGeometry.fromWkt(LINES[0]))

    def test_empty_geometries_are_not_drawn(self):
        self.assertFalse(self.manager.show_geometry(QgsGeometry()))
        self.assertEqual(self.manager.connection_count, 0)


class PanelPreviewQgisTest(_Base):
    def setUp(self):
        super().setUp()
        self.canvas = _canvas()
        self.addCleanup(self.canvas.deleteLater)
        self.layer = _with_ids(_role_layer("05_Passadas", "TL-1", "LineString", LINES), ["P1", "P2", "P3"])
        self._place(self.layer, "TL-1", "10_PLANEJAMENTO")
        self.iface = _CanvasIface(self.canvas)
        self.iface.layer = self.layer

    def _select(self, count):
        self.layer.selectByIds([feature.id() for feature in self.layer.getFeatures()][:count])
        _wait()

    def test_flag_off_keeps_the_0d_panel(self):
        with mock.patch.object(feature_flags, "is_enabled", ALL_OFF):
            panel = self._panel(self.iface)
            self._select(2)
            self.assertEqual(panel.selection_label.text(), "2 feições selecionadas")
            self.assertFalse(panel.btn_preview.isEnabled())
            self.assertEqual(panel.preview_selection(), 0)
        self.assertIsNone(panel.preview)
        self.assertEqual(_scene_bands(self.canvas), [])

    def test_preview_shows_the_selection_and_writes_nothing(self):
        tree, props = _tree_signature(self.root), _properties(self.project)
        with mock.patch.object(feature_flags, "is_enabled", PREVIEW_ON):
            panel = self._panel(self.iface)
            self.assertFalse(panel.btn_preview.isEnabled())
            self._select(2)
            self.assertIn("2 linhas selecionadas · ID: atributo FortSmart · P1, P2", panel.selection_label.text())
            self.assertTrue(panel.btn_preview.isEnabled())
            self.assertEqual(panel.preview_selection(), 2)
            self.assertEqual(panel.preview.count, 6)
            self.assertEqual(len(_scene_bands(self.canvas)), 3)
            self.assertIn("nada foi gravado", panel.status_label.text())
            self.assertTrue(panel.btn_cancel.isEnabled())
            self.assertEqual(panel.current_selection().fids, tuple(sorted(self.layer.selectedFeatureIds())))
        self.assertEqual(_tree_signature(self.root), tree)
        self.assertEqual(_properties(self.project), props)
        self.assertFalse(self.layer.isModified())

    def test_preview_is_cleared_on_cancel_selection_layer_and_project_changes(self):
        with mock.patch.object(feature_flags, "is_enabled", PREVIEW_ON):
            panel = self._panel(self.iface)
            self._select(1)
            panel.preview_selection()
            panel.cancel()
            self.assertEqual(panel.preview.count, 0)
            self.assertIn("prévia limpa", panel.status_label.text())

            panel.preview_selection()
            self._select(2)
            self.assertEqual(panel.preview.count, 0)

            panel.preview_selection()
            self.iface.setActiveLayer(None)
            _wait()
            self.assertEqual(panel.preview.count, 0)

            self.iface.setActiveLayer(self.layer)
            _wait()
            panel.preview_selection()
            self.project.removeMapLayer(self.layer.id())
            _wait()
            self.assertEqual(panel.preview.count, 0)
            self.assertEqual(_scene_bands(self.canvas), [])

    def test_hide_clears_and_shutdown_disposes(self):
        with mock.patch.object(feature_flags, "is_enabled", PREVIEW_ON):
            panel = self._panel(self.iface)
            self._select(3)
            panel.preview_selection()
            manager = panel.preview
            panel.hide()
            QgsApplication.processEvents()
            self.assertEqual(manager.count, 0)
            self.assertEqual(manager.connection_count, 0)
            panel.show()
            QgsApplication.processEvents()
            for _ in range(5):
                panel.preview_selection()
                self.assertEqual(manager.connection_count, 4)
            self.assertIs(panel.preview, manager)
            panel.shutdown()
        self.assertTrue(manager.disposed)
        self.assertIsNone(panel.preview)
        self.assertEqual(_scene_bands(self.canvas), [])

    def test_without_map_canvas_preview_stays_disabled(self):
        iface = _Iface()
        iface.layer = self.layer
        with mock.patch.object(feature_flags, "is_enabled", PREVIEW_ON):
            panel = self._panel(iface)
            self._select(1)
            self.assertFalse(panel.btn_preview.isEnabled())
            self.assertIn("Mapa", panel.btn_preview.toolTip())


if __name__ == "__main__":
    unittest.main()
