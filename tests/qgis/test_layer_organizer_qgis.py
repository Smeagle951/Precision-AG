# -*- coding: utf-8 -*-
"""Etapa 0C: aba 'Camadas' (arvore logica 01-05) num QGIS real, so apresentacao."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from qgis.core import QgsApplication, QgsFeature, QgsGeometry, QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import QObject, Qt, pyqtSignal
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QMainWindow

from plugin.fortsmart_precision import feature_flags
from plugin.fortsmart_precision.core import logical_layer_tree as llt
from plugin.fortsmart_precision.core.layer_roles import (
    LAYER_ROLES,
    PREVIEW_SECTION,
    TEMPORARY_PREVIEW_PROPERTY,
    definition_for_role,
    set_layer_role_properties,
)
from plugin.fortsmart_precision.core.persistence_manager import FortSmartPersistenceManager
from plugin.fortsmart_precision.gui import layer_tree_organizer as organizer
from plugin.fortsmart_precision.gui.layer_organizer_panel import (
    DEBOUNCE_MS,
    ITEM_CATEGORY,
    ITEM_FIELD,
    ITEM_LAYER,
    LayerOrganizerPanel,
)

_APP = None
CRS = "EPSG:31981"
SQUARE = "Polygon((0 0, 100 0, 100 100, 0 100, 0 0))"
TWO_SQUARES = "MultiPolygon(((0 0, 10 0, 10 10, 0 10, 0 0)),((50 50, 60 50, 60 60, 50 60, 50 50)))"
ORGANIZER_ON = (lambda name, settings=None: name == feature_flags.ENABLE_LAYER_ORGANIZER_V1)
ALL_OFF = (lambda name, settings=None: False)


def _setup_qgis():
    global _APP
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if QgsApplication.instance() is None:
        _APP = QgsApplication([], True)
        _APP.initQgis()


def _layer(geometry_type, name, wkts=(SQUARE,)):
    layer = QgsVectorLayer(f"{geometry_type}?crs={CRS}", name, "memory")
    features = []
    for wkt in wkts:
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt(wkt))
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    return layer


def _role_layer(key, field_name, *, geometry_type="Polygon", wkts=(SQUARE,)):
    definition = LAYER_ROLES[key]
    layer = _layer(geometry_type, definition.display_name, wkts)
    set_layer_role_properties(layer, definition, field_name=field_name)
    return layer


def _write_gpkg(path, tables):
    from osgeo import ogr, osr

    source = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(31981)
    for table, (geometry_type, wkts) in tables.items():
        target = source.CreateLayer(table, srs, geometry_type)
        for wkt in wkts:
            feature = ogr.Feature(target.GetLayerDefn())
            feature.SetGeometry(ogr.CreateGeometryFromWkt(wkt))
            target.CreateFeature(feature)
            feature = None
    source = None


def _tree_signature(node):
    items = []
    for child in node.children():
        if hasattr(child, "layer") and callable(child.layer):
            items.append(("L", child.layerId(), child.name(), child.itemVisibilityChecked()))
        else:
            items.append(("G", child.name(), child.itemVisibilityChecked(), _tree_signature(child)))
    return items


def _properties(project):
    return {
        layer.id(): {key: layer.customProperty(key) for key in layer.customPropertyKeys()}
        for layer in project.mapLayers().values()
    }


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class _Iface(QObject):
    currentLayerChanged = pyqtSignal(object)

    def __init__(self, window=None):
        super().__init__()
        self._window = window
        self.layer = None

    def mainWindow(self):
        return self._window

    def activeLayer(self):
        return self.layer

    def setActiveLayer(self, layer):
        self.layer = layer
        self.currentLayerChanged.emit(layer)
        return True


def _items(panel):
    stack = [panel.tree.topLevelItem(index) for index in range(panel.tree.topLevelItemCount())]
    while stack:
        item = stack.pop(0)
        yield item
        stack.extend(item.child(index) for index in range(item.childCount()))


def _item(panel, key):
    return next((item for item in _items(panel) if LayerOrganizerPanel._key(item) == key), None)


class _ProjectCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.project = QgsProject.instance()
        self.project.clear()
        self.project.setFileName(str(self.tmp / "fazenda.qgz"))
        self.root = self.project.layerTreeRoot()
        self.panels = []

    def tearDown(self):
        for panel in self.panels:
            panel.shutdown()
            panel.deleteLater()
        QgsApplication.processEvents()
        self.project.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _panel(self, *, show=False, iface=None):
        panel = LayerOrganizerPanel(iface, project=self.project)
        self.panels.append(panel)
        if show:
            panel.show()
            QgsApplication.processEvents()
        else:
            panel.refresh_full()
        return panel

    def _place(self, layer, field_name, section):
        self.project.addMapLayer(layer, False)
        group = organizer.project_group(self.root, field_name)
        target = organizer.section_group(group, section) if section else group
        organizer.insert_layer_ordered(target, layer)
        return layer

    def _wait(self):
        QTest.qWait(DEBOUNCE_MS * 3)


class OldProjectQgisTest(_ProjectCase):
    def _old_project(self):
        from osgeo import ogr

        gpkg = self.tmp / "legado.gpkg"
        _write_gpkg(gpkg, {
            "limite": (ogr.wkbPolygon, [SQUARE]),
            "passadas": (ogr.wkbLineString, ["LineString(0 0, 100 100)"]),
            "todos": (ogr.wkbPolygon, [SQUARE]),
            "rota": (ogr.wkbLineString, ["LineString(0 0, 1 1)"]),
        })
        group = self.root.addGroup("FORTSMART - TL-9")
        for table, name, section in (("limite", "Limite_Externo", "00_REFERENCIAS"),
                                     ("passadas", "05_Passadas", "10_PLANEJAMENTO")):
            layer = QgsVectorLayer(f"{gpkg}|layername={table}", name, "ogr")
            self.project.addMapLayer(layer, False)
            (group.findGroup(section) or group.addGroup(section)).addLayer(layer)
        self.project.addMapLayer(QgsVectorLayer(f"{gpkg}|layername=todos", "Todos — Limites", "ogr"))
        preview = QgsVectorLayer(f"{gpkg}|layername=rota", "Rota_Preview", "ogr")
        preview.setCustomProperty(TEMPORARY_PREVIEW_PROPERTY, True)
        self.project.addMapLayer(preview, False)
        self.root.addGroup(PREVIEW_SECTION).addLayer(preview)
        path = self.tmp / "antigo.qgz"
        self.assertTrue(self.project.write(str(path)))
        return path, gpkg

    def test_old_project_opens_in_logical_view_without_changes(self):
        path, gpkg = self._old_project()
        ids = set(self.project.mapLayers())
        self.project.clear()
        panel = self._panel(show=True)
        self.assertTrue(self.project.read(str(path)))
        self._wait()
        project_hash, gpkg_hash = _digest(path), _digest(gpkg)
        signature, properties = _tree_signature(self.root), _properties(self.project)

        self.assertEqual(set(self.project.mapLayers()), ids)
        tree = panel.model.tree
        self.assertEqual([field.field_id for field in tree.fields], ["TL-9"])
        field = tree.fields[0]
        self.assertEqual([item.title for item in field.categories][:5],
                         [item.title for item in llt.LOGICAL_CATEGORIES])
        self.assertEqual([layer.name for layer in field.categories[0].layers], ["Limite_Externo"])
        self.assertEqual([layer.name for layer in field.categories[1].layers], ["05_Passadas"])
        outside = {layer.name: layer for layer in tree.unassociated.layers}
        self.assertEqual(set(outside), {"Todos — Limites", "Rota_Preview"})
        self.assertEqual(outside["Rota_Preview"].kind, llt.KIND_PREVIEW)
        self.assertEqual(outside["Todos — Limites"].geometry, "Polígono")
        for category in llt.LOGICAL_CATEGORIES:
            self.assertIsNotNone(_item(panel, (ITEM_CATEGORY, "tl-9", category.code)), category.title)

        panel.refresh_full()
        self.assertEqual(_tree_signature(self.root), signature)
        self.assertEqual(_properties(self.project), properties)
        self.assertEqual(_digest(path), project_hash)
        self.assertEqual(_digest(gpkg), gpkg_hash)
        self.assertFalse(self.project.isDirty())
        self.assertFalse((self.tmp / "fortsmart_data").exists())


class VisibilityQgisTest(_ProjectCase):
    def _two_fields(self):
        self.a1 = self._place(_role_layer("01_Limite_Externo", "TL-1"), "TL-1", "00_REFERENCIAS")
        self.a2 = self._place(_role_layer("14_Limite_Operacional", "TL-1"), "TL-1", "00_REFERENCIAS")
        self.b1 = self._place(_role_layer("01_Limite_Externo", "TL-2"), "TL-2", "00_REFERENCIAS")
        self.b2 = self._place(
            _role_layer("05_Passadas", "TL-2", geometry_type="LineString", wkts=("LineString(0 0, 1 1)",)),
            "TL-2",
            "10_PLANEJAMENTO",
        )

    def test_toggle_and_restore_act_on_original_nodes(self):
        self._two_fields()
        self.b2.selectByIds([next(self.b2.getFeatures()).id()])
        selection = {layer.id(): sorted(layer.selectedFeatureIds()) for layer in self.project.mapLayers().values()}
        signature = _tree_signature(self.root)
        ids = set(self.project.mapLayers())
        panel = self._panel(show=True)
        self.assertEqual({field.field_id for field in panel.model.tree.fields}, {"TL-1", "TL-2"})
        node_count = len(self.root.findLayers())

        item = _item(panel, (ITEM_LAYER, self.a2.id()))
        item.setCheckState(0, Qt.Unchecked)
        self.assertFalse(self.root.findLayer(self.a2.id()).itemVisibilityChecked())
        panel.tree.setCurrentItem(_item(panel, (ITEM_FIELD, "tl-2")))
        report = panel.set_selected_visibility(False)
        self.assertEqual(len(report.changed), 2)
        self.assertFalse(self.root.findLayer(self.b1.id()).itemVisibilityChecked())
        self.assertEqual(len(self.root.findLayers()), node_count)
        self._wait()
        self.assertEqual(_item(panel, (ITEM_LAYER, self.b2.id())).checkState(0), Qt.Unchecked)

        report = panel.restore_visibility()
        self.assertEqual(len(report.changed), 3)
        self.assertEqual(_tree_signature(self.root), signature)
        self.assertEqual(set(self.project.mapLayers()), ids)
        self.assertEqual(
            {layer.id(): sorted(layer.selectedFeatureIds()) for layer in self.project.mapLayers().values()},
            selection,
        )
        self._wait()
        self.assertEqual(_item(panel, (ITEM_LAYER, self.a2.id())).checkState(0), Qt.Checked)

    def test_boundaries_visible_together_warn_and_stay_visible(self):
        self._two_fields()
        panel = self._panel()
        field = panel.model.tree.field("tl-1")
        self.assertIn("MULTIPLE_APPLICABLE_BOUNDARIES", {item.code for item in field.diagnostics})
        self.assertNotIn("MULTIPLE_APPLICABLE_BOUNDARIES",
                         {item.code for item in panel.model.tree.field("tl-2").diagnostics})
        self.assertTrue(self.root.findLayer(self.a1.id()).itemVisibilityChecked())
        self.assertTrue(self.root.findLayer(self.a2.id()).itemVisibilityChecked())
        self.assertEqual(_item(panel, (ITEM_FIELD, "tl-1")).text(3), llt.STATUS_WARNING)

    def test_qgis_changes_refresh_the_view(self):
        self._two_fields()
        panel = self._panel(show=True)
        self.root.findLayer(self.b2.id()).setItemVisibilityChecked(False)
        self._wait()
        self.assertEqual(_item(panel, (ITEM_LAYER, self.b2.id())).checkState(0), Qt.Unchecked)
        loose = _layer("Polygon", "Todos — Limites")
        self.project.addMapLayer(loose)
        self._wait()
        self.assertIsNotNone(_item(panel, (ITEM_LAYER, loose.id())))
        self.assertIsNone(panel.model.tree.layer(loose.id()).field_id)
        loose_id = loose.id()
        self.project.removeMapLayer(loose_id)
        self._wait()
        self.assertIsNone(_item(panel, (ITEM_LAYER, loose_id)))
        self.assertNotIn(loose_id, panel._layer_connections)

    def test_ambiguous_layer_blocks_field_action(self):
        conflict = self._place(_role_layer("01_Limite_Externo", "TL-2"), "TL-1", "00_REFERENCIAS")
        self._place(_role_layer("01_Limite_Externo", "TL-2"), "TL-2", "00_REFERENCIAS")
        panel = self._panel()
        panel.tree.setCurrentItem(_item(panel, (ITEM_LAYER, conflict.id())))
        self.assertEqual(panel.model.tree.layer(conflict.id()).status, llt.STATUS_AMBIGUOUS)
        self.assertFalse(panel.btn_work_field.isEnabled())
        panel.tree.setCurrentItem(_item(panel, (ITEM_FIELD, "tl-2")))
        self.assertTrue(panel.btn_work_field.isEnabled())
        panel.use_selected_field()
        self.assertEqual(panel.service.explicit_field, "TL-2")


class GeoPackageQgisTest(_ProjectCase):
    def test_geometry_risk_is_read_only(self):
        definition = definition_for_role("SAFETY_ZONE")
        manager = FortSmartPersistenceManager(self.project)
        result = manager.persist_layer(_layer("Polygon", definition.display_name), definition, "TL-5")
        persisted = self._place(result.layer, "TL-5", "20_OBSTACULOS")
        memory = _layer("MultiPolygon", definition.display_name, [TWO_SQUARES])
        set_layer_role_properties(memory, definition, field_name="TL-5")
        self._place(memory, "TL-5", "20_OBSTACULOS")
        QgsApplication.processEvents()
        path = manager.get_field_storage_path("TL-5")
        files = sorted(path.parent.glob("*.gpkg"))
        before = {item.name: (_digest(item), item.stat().st_mtime_ns) for item in files}
        ids = set(self.project.mapLayers())

        panel = self._panel()
        panel.refresh_full()
        layer = panel.model.tree.layer(memory.id())
        self.assertIn(llt.GEOMETRY_WRITE_RISK, {item.code for item in layer.diagnostics})
        self.assertNotIn(llt.GEOMETRY_WRITE_RISK,
                         {item.code for item in panel.model.tree.layer(persisted.id()).diagnostics})
        self.assertEqual(layer.geometry, "Multipolígono")
        after = {item.name: (_digest(item), item.stat().st_mtime_ns) for item in sorted(path.parent.glob("*.gpkg"))}
        self.assertEqual(after, before)
        self.assertEqual(set(self.project.mapLayers()), ids)
        self.assertEqual(memory.featureCount(), 1)


class DockQgisTest(_ProjectCase):
    def _dock(self, enabled):
        from plugin.fortsmart_precision.gui.main_dock import FortSmartDock

        window = QMainWindow()
        iface = _Iface(window)
        with mock.patch.object(feature_flags, "is_enabled", enabled):
            dock = FortSmartDock(iface)
        window.addDockWidget(Qt.RightDockWidgetArea, dock)
        self.addCleanup(window.deleteLater)
        return window, iface, dock

    def test_flag_off_keeps_the_panel_as_before(self):
        _window, _iface, dock = self._dock(ALL_OFF)
        self.assertIsNone(dock.tabs)
        self.assertIsNone(dock.organizer)
        self.assertIs(dock.widget().layout().itemAt(0).widget(), dock.stack)
        self.assertEqual(dock.widget().layout().count(), 1)

    def test_flag_toggles_the_tab_without_rebuilding_the_dock(self):
        _window, _iface, dock = self._dock(ALL_OFF)
        with mock.patch.object(feature_flags, "is_enabled", ORGANIZER_ON):
            dock.refresh()
        self.assertIsNotNone(dock.organizer)
        self.assertEqual(dock.tabs.tabText(1), "Camadas")
        self.assertIs(dock.tabs.widget(0), dock.stack)
        with mock.patch.object(feature_flags, "is_enabled", ALL_OFF):
            dock.refresh()
        self.assertIsNone(dock.tabs)
        self.assertIs(dock.widget().layout().itemAt(0).widget(), dock.stack)
        self.assertEqual(dock.widget().layout().count(), 1)

    def test_open_and_close_repeatedly_keeps_one_set_of_connections(self):
        self._place(_role_layer("01_Limite_Externo", "TL-1"), "TL-1", "00_REFERENCIAS")
        window, _iface, dock = self._dock(ORGANIZER_ON)
        dock.tabs.setCurrentWidget(dock.organizer)
        window.show()
        counts = []
        with mock.patch.object(feature_flags, "is_enabled", ORGANIZER_ON):
            for _ in range(5):
                dock.show()
                dock.refresh()
                QgsApplication.processEvents()
                counts.append(dock.organizer.connection_count)
                self.assertEqual(dock.organizer.model.tree.fields[0].field_id, "TL-1")
                dock.close()
                QgsApplication.processEvents()
                self.assertEqual(dock.organizer.connection_count, 0)
            dock.show()
            QgsApplication.processEvents()
            self.assertGreater(dock.organizer.connection_count, 0)
            window.removeDockWidget(dock)
            QgsApplication.processEvents()
        self.assertEqual(len(set(counts)), 1)
        self.assertGreater(counts[0], 0)
        self.assertEqual(dock.organizer.connection_count, 0)


if __name__ == "__main__":
    unittest.main()
