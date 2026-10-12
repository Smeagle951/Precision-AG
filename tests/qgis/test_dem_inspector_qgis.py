# -*- coding: utf-8 -*-
"""Etapa 0F: Inspetor DEM num QGIS real (rasters sinteticos, somente leitura)."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsProject,
    QgsRasterLayer,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QMainWindow

from plugin.fortsmart_precision import feature_flags
from plugin.fortsmart_precision.core import dem_inspector as dem
from plugin.fortsmart_precision.core.project_context import ProjectContextService
from plugin.fortsmart_precision.gui.dem_inspector_widget import DemInspectorWidget
from tests.qgis.test_agrocad_panel_qgis import _Base, _Iface, _properties, _role_layer, _tree_signature

X0, Y0, SIDE = 500000.0, 7700000.0, 1000.0
FIELD = f"Polygon(({X0} {Y0}, {X0 + SIDE} {Y0}, {X0 + SIDE} {Y0 + SIDE}, {X0} {Y0 + SIDE}, {X0} {Y0}))"
BOWTIE = f"Polygon(({X0} {Y0}, {X0 + SIDE} {Y0 + SIDE}, {X0 + SIDE} {Y0}, {X0} {Y0 + SIDE}, {X0} {Y0}))"
DEM_ON = (lambda name, settings=None: name in (
    feature_flags.ENABLE_AGROCAD_PANEL_V1, feature_flags.ENABLE_DEM_INSPECTOR_V1))
AGROCAD_ONLY = (lambda name, settings=None: name == feature_flags.ENABLE_AGROCAD_PANEL_V1)


def _tif(path, *, origin=(X0 - 100, Y0 + SIDE + 100), size=(120, 120), res=10.0, bands=1, dtype="Float32",
         epsg=31981, nodata=-9999.0, unit="m", nodata_left=False, value=500.0):
    import numpy
    from osgeo import gdal, osr

    types = {"Float32": gdal.GDT_Float32, "Byte": gdal.GDT_Byte, "Int16": gdal.GDT_Int16}
    cols, rows = size
    dataset = gdal.GetDriverByName("GTiff").Create(str(path), cols, rows, bands, types[dtype])
    dataset.SetGeoTransform((origin[0], res, 0, origin[1], 0, -res))
    if epsg:
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(epsg)
        dataset.SetProjection(srs.ExportToWkt())
    for index in range(1, bands + 1):
        band = dataset.GetRasterBand(index)
        data = numpy.full((rows, cols), value, dtype="float64") + numpy.arange(cols) * 0.1
        if nodata is not None:
            band.SetNoDataValue(nodata)
            if nodata_left:
                data[:, : cols // 2] = nodata
        if unit:
            band.SetUnitType(unit)
        band.WriteArray(data.astype(dtype.lower() if dtype != "Byte" else "uint8"))
    dataset.FlushCache()
    dataset = None
    return path


def _digests(folder):
    return {item.name: hashlib.sha256(item.read_bytes()).hexdigest() for item in Path(folder).iterdir()}


class _DemBase(_Base):
    def setUp(self):
        super().setUp()
        self.data = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.data, True)
        self.service = ProjectContextService(self.project)
        self.boundary = self._place(_role_layer("01_Limite_Externo", "TL-1", wkts=(FIELD,)), "TL-1", "00_REFERENCIAS")
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            widget.shutdown()
            widget.deleteLater()
        QgsApplication.processEvents()
        super().tearDown()

    def _raster(self, name, **kwargs):
        path = _tif(self.data / f"{name}.tif", **kwargs)
        layer = QgsRasterLayer(str(path), name)
        self.assertTrue(layer.isValid(), name)
        self.project.addMapLayer(layer)
        return layer

    def _widget(self, field_id="TL-1"):
        widget = DemInspectorWidget(None, self.service)
        self.widgets.append(widget)
        widget.show()
        QgsApplication.processEvents()
        widget.set_field(field_id)
        return widget

    def _check(self, widget, layer):
        widget.select_raster(layer.id())
        started = widget.check()
        deadline = time.time() + 15
        while started and widget.task is not None and time.time() < deadline:
            QgsApplication.processEvents()
            time.sleep(0.01)
        self.assertIsNone(widget.task, "verificação não terminou")
        return widget.coverage


class DemValidationQgisTest(_DemBase):
    def test_valid_dem_full_coverage_and_nothing_is_written(self):
        layer = self._raster("dem")
        before = _digests(self.data)
        tree, props = _tree_signature(self.root), _properties(self.project)
        widget = self._widget()
        coverage = self._check(widget, layer)
        self.assertEqual(coverage.status, dem.COVERAGE_COMPLETE)
        low, high, _mean = coverage.elevation
        self.assertGreaterEqual(low, 500.0)
        self.assertLessEqual(high, 512.0)
        labels = {key: label.text() for key, label in widget.labels.items()}
        self.assertEqual(labels["crs"], "EPSG:31981")
        self.assertEqual(labels["resolution"], "10 × 10 metros")
        self.assertEqual(labels["nodata"], "-9999")
        self.assertEqual(labels["vertical"], "metros (metadado da banda)")
        self.assertEqual(labels["horizontal"], "metros")
        self.assertIn("Completa", labels["coverage"])
        self.assertIn("metros — amostra no talhão", labels["elevation"])
        self.assertIn("nada foi gravado", widget.status_label.text())
        self.assertFalse({dem.RASTER_WITHOUT_CRS, dem.VERTICAL_UNIT_UNCONFIRMED} & widget.diagnostic_codes)
        self.assertEqual(_digests(self.data), before)
        self.assertEqual(_tree_signature(self.root), tree)
        self.assertEqual(_properties(self.project), props)

    def test_non_elevation_raster_is_listed_last_and_explained(self):
        self._raster("imagem", bands=3, dtype="Byte", nodata=None, unit="")
        layer = self._raster("dem")
        widget = self._widget()
        items = [widget.raster_combo.itemText(i) for i in range(widget.raster_combo.count())]
        self.assertEqual(items[1:], ["dem", "imagem (não recomendado)"])
        image = next(item for item in self.project.mapLayersByName("imagem"))
        widget.select_raster(image.id())
        self.assertFalse(widget.metadata.suitability.candidate)
        self.assertIn(dem.NOT_ELEVATION_CANDIDATE, widget.diagnostic_codes)
        self.assertIn("Não recomendado", widget.labels["suitability"].text())
        widget.select_raster(layer.id())
        self.assertTrue(widget.metadata.suitability.candidate)

    def test_raster_without_crs_cannot_be_checked(self):
        layer = self._raster("semcrs", epsg=None)
        widget = self._widget()
        widget.select_raster(layer.id())
        if layer.crs().isValid():
            self.skipTest("QGIS atribuiu CRS padrão ao raster sem projeção")
        self.assertIn(dem.RASTER_WITHOUT_CRS, widget.diagnostic_codes)
        self.assertFalse(widget.check())
        self.assertEqual(widget.coverage.status, dem.COVERAGE_UNKNOWN)

    def test_unknown_vertical_unit_and_session_declaration(self):
        layer = self._raster("semunidade", unit="")
        before = _digests(self.data)
        keys = layer.customPropertyKeys()
        widget = self._widget()
        widget.select_raster(layer.id())
        self.assertEqual(widget.labels["vertical"].text(), "Unidade vertical não confirmada")
        self.assertIn(dem.VERTICAL_UNIT_UNCONFIRMED, widget.diagnostic_codes)
        widget.vertical_combo.setCurrentIndex(widget.vertical_combo.findData(dem.UNIT_METERS))
        self.assertEqual(widget.labels["vertical"].text(), "metros (declarada pelo usuário nesta sessão)")
        self.assertNotIn(dem.VERTICAL_UNIT_UNCONFIRMED, widget.diagnostic_codes)
        self.assertEqual(layer.customPropertyKeys(), keys)
        self.assertEqual(_digests(self.data), before)

    def test_partial_and_absent_coverage(self):
        half = self._raster("metade", size=(60, 120))
        far = self._raster("longe", origin=(X0 + 50000, Y0 + 50000))
        widget = self._widget()
        partial = self._check(widget, half)
        self.assertEqual(partial.status, dem.COVERAGE_PARTIAL)
        self.assertAlmostEqual(partial.covered_fraction, 0.5, delta=0.02)
        absent = self._check(widget, far)
        self.assertEqual(absent.status, dem.COVERAGE_NONE)
        self.assertIn("Ausente", widget.labels["coverage"].text())

    def test_nodata_inside_the_field(self):
        layer = self._raster("buraco", nodata_left=True)
        widget = self._widget()
        coverage = self._check(widget, layer)
        self.assertEqual(coverage.status, dem.COVERAGE_PARTIAL)
        self.assertAlmostEqual(coverage.nodata_fraction, 0.45, delta=0.08)
        self.assertIn(dem.NODATA_IN_FIELD, widget.diagnostic_codes)

    def test_raster_in_another_crs_is_checked_in_memory(self):
        transform = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem("EPSG:31981"), QgsCoordinateReferenceSystem("EPSG:4326"), self.project
        )
        box = QgsGeometry.fromWkt(FIELD)
        box.transform(transform)
        rect = box.boundingBox().buffered(0.01)
        res = 0.0001
        layer = self._raster(
            "geografico", epsg=4326, res=res, origin=(rect.xMinimum(), rect.yMaximum()),
            size=(int(rect.width() / res) + 1, int(rect.height() / res) + 1),
        )
        boundary_wkt = self.boundary.getFeature(1).geometry().asWkt()
        widget = self._widget()
        coverage = self._check(widget, layer)
        self.assertEqual(coverage.status, dem.COVERAGE_COMPLETE)
        self.assertTrue({dem.CRS_DIFFERS_FROM_FIELD, dem.HORIZONTAL_IN_DEGREES} <= widget.diagnostic_codes)
        self.assertIn("aprox.", widget.labels["resolution"].text())
        self.assertEqual(self.boundary.getFeature(1).geometry().asWkt(), boundary_wkt)
        self.assertEqual(layer.crs().authid(), "EPSG:4326")

    def test_boundary_missing_ambiguous_and_invalid(self):
        layer = self._raster("dem")
        widget = self._widget("TL-2")
        self._place(_role_layer("02_Bordadura", "TL-2", wkts=(FIELD,)), "TL-2", "00_REFERENCIAS")
        widget.select_raster(layer.id())
        self.assertFalse(widget.check())
        self.assertIn(dem.FIELD_BOUNDARY_MISSING, widget.diagnostic_codes)
        self._place(_role_layer("01_Limite_Externo", "TL-1", wkts=(FIELD,)), "TL-1", "00_REFERENCIAS")
        widget.set_field("TL-1")
        self.assertFalse(widget.check())
        self.assertIn(dem.FIELD_BOUNDARY_AMBIGUOUS, widget.diagnostic_codes)
        self._place(_role_layer("01_Limite_Externo", "TL-3", wkts=(BOWTIE,)), "TL-3", "00_REFERENCIAS")
        widget.set_field("TL-3")
        coverage = self._check(widget, layer)
        self.assertNotEqual(coverage.status, dem.COVERAGE_UNKNOWN)
        self.assertIn(dem.FIELD_GEOMETRY_INVALID, widget.diagnostic_codes)
        widget.set_field(None)
        self.assertFalse(widget.check())
        self.assertIn(dem.FIELD_NOT_SELECTED, widget.diagnostic_codes)


class DemLifecycleQgisTest(_DemBase):
    def test_switching_dem_invalidates_and_ignores_the_old_task(self):
        first = self._raster("dem")
        second = self._raster("metade", size=(60, 120))
        widget = self._widget()
        widget.select_raster(first.id())
        self.assertTrue(widget.check())
        old_task = widget.task
        widget.select_raster(second.id())
        self.assertIsNone(widget.task)
        self.assertIsNone(old_task.on_done)
        deadline = time.time() + 5
        while time.time() < deadline and QgsApplication.taskManager().countActiveTasks():
            QgsApplication.processEvents()
        QgsApplication.processEvents()
        self.assertIsNone(widget.coverage)
        self.assertIn("a fonte DEM mudou", widget.status_label.text())

    def test_removing_the_dem(self):
        layer = self._raster("dem")
        widget = self._widget()
        self._check(widget, layer)
        bound = widget.connection_count
        self.project.removeMapLayer(layer.id())
        QgsApplication.processEvents()
        self.assertIsNone(widget.layer_id)
        self.assertIsNone(widget.metadata)
        self.assertIsNone(widget.coverage)
        self.assertLess(widget.connection_count, bound)
        self.assertEqual(widget.raster_combo.count(), 1)
        self.assertFalse(widget.btn_check.isEnabled())

    def test_field_change_crs_change_and_project_switch_invalidate(self):
        layer = self._raster("dem")
        widget = self._widget()
        self._check(widget, layer)
        widget.set_field("TL-2")
        self.assertIsNone(widget.coverage)
        self.assertIn("talhão mudou", widget.status_label.text())
        self._check(widget, layer)
        layer.setCrs(QgsCoordinateReferenceSystem("EPSG:31982"))
        self.assertIsNone(widget.coverage)
        self.assertIn("CRS do raster mudou", widget.status_label.text())
        widget.vertical_combo.setCurrentIndex(widget.vertical_combo.findData(dem.UNIT_FEET))
        self.project.clear()
        QgsApplication.processEvents()
        self.assertIsNone(widget.layer_id)
        self.assertEqual(widget.raster_combo.count(), 1)
        self.assertIn("projeto trocado", widget.status_label.text())
        self.assertEqual(widget._declared, {})

    def test_raster_added_later_appears(self):
        widget = self._widget()
        self.assertEqual(widget.raster_combo.count(), 1)
        self._raster("dem")
        QgsApplication.processEvents()
        self.assertEqual(widget.raster_combo.itemText(1), "dem")


class DemPanelQgisTest(_DemBase):
    def _dock(self, enabled):
        from plugin.fortsmart_precision.gui.main_dock import FortSmartDock

        window = QMainWindow()
        iface = _Iface(window)
        with mock.patch.object(feature_flags, "is_enabled", enabled):
            dock = FortSmartDock(iface)
        window.addDockWidget(Qt.RightDockWidgetArea, dock)
        self.addCleanup(window.deleteLater)
        return window, iface, dock

    def test_flag_off_keeps_the_0d_terrain_section(self):
        _window, _iface, dock = self._dock(AGROCAD_ONLY)
        self.assertIsNone(dock.agrocad.dem_inspector)
        for key in ("dem_inspector", "slope", "contours"):
            self.assertFalse(dock.agrocad.tool_buttons[key].isHidden())
            self.assertFalse(dock.agrocad.tool_buttons[key].isEnabled())

    def test_flag_toggles_the_inspector_inside_terrain(self):
        _window, _iface, dock = self._dock(AGROCAD_ONLY)
        with mock.patch.object(feature_flags, "is_enabled", DEM_ON):
            dock.refresh()
        self.assertIsNotNone(dock.agrocad.dem_inspector)
        self.assertTrue(dock.agrocad.tool_buttons["slope"].isHidden())
        with mock.patch.object(feature_flags, "is_enabled", AGROCAD_ONLY):
            dock.refresh()
        self.assertIsNone(dock.agrocad.dem_inspector)
        self.assertFalse(dock.agrocad.tool_buttons["slope"].isHidden())

    def test_panel_field_reaches_the_inspector_and_reopen_keeps_one_set_of_connections(self):
        layer = self._raster("dem")
        window, iface, dock = self._dock(DEM_ON)
        dock.tabs.setCurrentWidget(dock.agrocad)
        dock.agrocad.select_section(dem_section := "TERRAIN")
        window.show()
        counts = []
        with mock.patch.object(feature_flags, "is_enabled", DEM_ON):
            for _ in range(5):
                dock.show()
                dock.refresh()
                iface.setActiveLayer(self.boundary)
                QgsApplication.processEvents()
                time.sleep(0.12)
                QgsApplication.processEvents()
                inspector = dock.agrocad.dem_inspector
                self.assertEqual(inspector.field_id, "TL-1")
                inspector.select_raster(layer.id())
                counts.append(inspector.connection_count)
                dock.close()
                QgsApplication.processEvents()
                self.assertEqual(inspector.connection_count, 0)
        self.assertEqual(dock.agrocad.current_section, dem_section)
        self.assertEqual(len(set(counts)), 1)
        self.assertGreater(counts[0], 0)


if __name__ == "__main__":
    unittest.main()
