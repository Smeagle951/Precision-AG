# -*- coding: utf-8 -*-
"""Etapa 0D: painel AgroCAD no dock FortSmart, num QGIS real."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from qgis.core import QgsApplication, QgsFeature, QgsGeometry, QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import QObject, Qt, pyqtSignal
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QAction, QMainWindow

from plugin.fortsmart_precision import feature_flags
from plugin.fortsmart_precision.core import agrocad_tools as tools
from plugin.fortsmart_precision.core.layer_roles import LAYER_ROLES, set_layer_role_properties
from plugin.fortsmart_precision.gui import layer_tree_organizer as organizer
from plugin.fortsmart_precision.gui.agrocad_panel import DEBOUNCE_MS, AgroCadPanel

_APP = None
CRS = "EPSG:31981"
SQUARE = "Polygon((0 0, 100 0, 100 100, 0 100, 0 0))"
LINES = ("LineString(0 0, 0 100)", "LineString(10 0, 10 100)", "LineString(20 0, 20 100)")
AGROCAD_ON = (lambda name, settings=None: name == feature_flags.ENABLE_AGROCAD_PANEL_V1)
BOTH_ON = (lambda name, settings=None: name in (
    feature_flags.ENABLE_AGROCAD_PANEL_V1, feature_flags.ENABLE_LAYER_ORGANIZER_V1))
ALL_OFF = (lambda name, settings=None: False)
NATIVE = (
    "actionToggleEditing", "actionSaveActiveLayerEdits", "actionSelect", "actionSelectRectangle",
    "actionSelectPolygon", "actionVertexToolActiveLayer", "actionSplitFeatures", "actionPan",
)


def _setup_qgis():
    global _APP
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if QgsApplication.instance() is None:
        _APP = QgsApplication([], True)
        _APP.initQgis()


def _layer(geometry_type, name, wkts):
    layer = QgsVectorLayer(f"{geometry_type}?crs={CRS}", name, "memory")
    features = []
    for wkt in wkts:
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt(wkt))
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    return layer


def _role_layer(key, field_name, geometry_type="Polygon", wkts=(SQUARE,)):
    definition = LAYER_ROLES[key]
    layer = _layer(geometry_type, definition.display_name, wkts)
    set_layer_role_properties(layer, definition, field_name=field_name)
    return layer


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


class _Iface(QObject):
    """Interface minima do QGIS: camada ativa, acoes nativas e dock."""

    currentLayerChanged = pyqtSignal(object)

    def __init__(self, window=None, native=NATIVE):
        super().__init__()
        self._window = window
        self.layer = None
        self.triggered: list = []
        self._actions = {}
        for name in native:
            action = QAction(name, self)
            action.triggered.connect(lambda _checked=False, value=name: self.triggered.append(value))
            self._actions[name] = action

    def __getattr__(self, name):
        actions = self.__dict__.get("_actions", {})
        if name in actions:
            return lambda: actions[name]
        raise AttributeError(name)

    def mainWindow(self):
        return self._window

    def activeLayer(self):
        return self.layer

    def setActiveLayer(self, layer):
        self.layer = layer
        self.currentLayerChanged.emit(layer)
        return True

    def addPluginToMenu(self, *args):
        pass

    def removePluginMenu(self, *args):
        pass

    def addToolBarIcon(self, *args):
        pass

    def removeToolBarIcon(self, *args):
        pass

    def addDockWidget(self, area, dock):
        self._window.addDockWidget(area, dock)

    def removeDockWidget(self, dock):
        self._window.removeDockWidget(dock)


def _wait():
    QTest.qWait(DEBOUNCE_MS + 40)
    QgsApplication.processEvents()


class _Base(unittest.TestCase):
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

    def _place(self, layer, field_name, section):
        self.project.addMapLayer(layer, False)
        group = organizer.project_group(self.root, field_name)
        organizer.insert_layer_ordered(organizer.section_group(group, section), layer)
        return layer

    def _panel(self, iface, actions=None):
        panel = AgroCadPanel(iface, tool_actions=actions)
        self.panels.append(panel)
        panel.show()
        QgsApplication.processEvents()
        return panel


class ContextQgisTest(_Base):
    def test_old_project_without_fortsmart_data_is_only_read(self):
        legacy = _layer("Polygon", "contorno antigo", (SQUARE,))
        self.project.addMapLayer(legacy)
        tree, props = _tree_signature(self.root), _properties(self.project)
        iface = _Iface()
        iface.layer = legacy
        panel = self._panel(iface)
        self.assertIn("Fazenda não registrada / Talhão não definido", panel.project_label.text())
        self.assertEqual(panel.field_combo.count(), 1)
        self.assertIn("contorno antigo", panel.layer_label.text())
        self.assertIn("sem papel FortSmart", panel.layer_label.text())
        panel.select_tool("select")
        self.assertTrue(panel.apply())
        panel.cancel()
        self.assertEqual(_tree_signature(self.root), tree)
        self.assertEqual(_properties(self.project), props)

    def test_header_follows_active_layer_and_explicit_choice(self):
        tl1 = self._place(_role_layer("01_Limite_Externo", "TL-1"), "TL-1", "00_REFERENCIAS")
        self._place(_role_layer("01_Limite_Externo", "TL-2"), "TL-2", "00_REFERENCIAS")
        iface = _Iface()
        panel = self._panel(iface)
        self.assertIn("Talhão não definido", panel.project_label.text())
        iface.setActiveLayer(tl1)
        _wait()
        self.assertIn("TL-1 (pela camada ativa)", panel.project_label.text())
        self.assertIn("talhão TL-1", panel.layer_label.text())
        self.assertEqual(sorted(panel.field_combo.itemText(i) for i in range(1, panel.field_combo.count())),
                         ["TL-1", "TL-2"])
        panel.field_combo.setCurrentIndex(panel.field_combo.findData("TL-2"))
        _wait()
        self.assertEqual(panel.service.explicit_field, "TL-2")
        self.assertIn("TL-2 (escolhido)", panel.project_label.text())
        panel.field_combo.setCurrentIndex(0)
        _wait()
        self.assertIsNone(panel.service.explicit_field)
        self.assertIn("TL-1 (pela camada ativa)", panel.project_label.text())

    def test_selection_change_updates_without_rebuilding_the_context(self):
        lines = self._place(_role_layer("05_Passadas", "TL-1", "LineString", LINES), "TL-1", "10_PLANEJAMENTO")
        iface = _Iface()
        iface.layer = lines
        panel = self._panel(iface)
        self.assertEqual(panel.selection_label.text(), "nenhuma feição selecionada")
        with mock.patch.object(panel.service, "snapshot", wraps=panel.service.snapshot) as snapshot:
            lines.selectByIds([feature.id() for feature in lines.getFeatures()][:2])
            _wait()
            self.assertEqual(panel.selection_label.text(), "2 feições selecionadas")
            lines.removeSelection()
            _wait()
            self.assertEqual(snapshot.call_count, 0)
        self.assertEqual(panel.selection_label.text(), "nenhuma feição selecionada")

    def test_removed_active_layer_and_project_switch(self):
        layer = self._place(_role_layer("01_Limite_Externo", "TL-1"), "TL-1", "00_REFERENCIAS")
        iface = _Iface()
        iface.layer = layer
        panel = self._panel(iface)
        panel.field_combo.setCurrentIndex(panel.field_combo.findData("TL-1"))
        panel.select_tool("obstacle_detour")
        bound = panel.connection_count
        layer_id = layer.id()
        self.project.removeMapLayer(layer_id)
        _wait()
        self.assertLess(panel.connection_count, bound)
        self.assertEqual(panel.layer_label.text(), "Nenhuma camada ativa no QGIS.")
        self.project.clear()
        _wait()
        self.assertIsNone(panel.service.explicit_field)
        self.assertIsNone(panel.current_tool)
        self.assertIn("projeto trocado", panel.status_label.text())


class ToolsQgisTest(_Base):
    def test_unavailable_actions_are_disabled(self):
        panel = self._panel(_Iface())
        for tool in tools.TOOLS:
            if tool.source == tools.SOURCE_UNAVAILABLE:
                self.assertFalse(panel.tool_buttons[tool.key].isEnabled(), tool.key)
        self.assertFalse(panel.btn_preview.isEnabled())
        self.assertFalse(panel.btn_apply.isEnabled())
        panel.select_tool("dem_inspector")
        self.assertIsNone(panel.current_tool)

    def test_plugin_tools_trigger_the_same_menu_action(self):
        action = QAction("Desvio")
        fired = []
        action.triggered.connect(lambda *_: fired.append(1))
        panel = self._panel(_Iface(), {tools.PLUGIN_OBSTACLE_DETOUR: action})
        panel.select_tool("obstacle_detour")
        self.assertEqual(panel.current_section, tools.SECTION_OBSTACLES)
        self.assertTrue(panel.btn_apply.isEnabled())
        self.assertTrue(panel.apply())
        self.assertEqual(fired, [1])
        self.assertIn("tela aberta", panel.status_label.text())
        panel.select_tool("headland_turns")
        self.assertFalse(panel.btn_apply.isEnabled())
        self.assertFalse(panel.apply())
        self.assertIn("plugin indisponível", panel.status_label.text())

    def test_native_map_tool_and_cancel_back_to_pan(self):
        layer = _layer("LineString", "linhas", LINES)
        self.project.addMapLayer(layer)
        iface = _Iface()
        iface.layer = layer
        panel = self._panel(iface)
        panel.select_tool("vertex_tool")
        self.assertFalse(panel.apply())
        self.assertIn("edição", panel.status_label.text())
        panel.select_tool("select_rectangle")
        self.assertTrue(panel.apply())
        panel.cancel()
        self.assertEqual(iface.triggered, ["actionSelectRectangle", "actionPan"])
        self.assertIsNone(panel.current_tool)
        self.assertFalse(any(button.isChecked() for button in panel.tool_buttons.values()))

    def test_missing_native_action_is_disabled_not_skipped(self):
        layer = _layer("LineString", "linhas", LINES)
        self.project.addMapLayer(layer)
        iface = _Iface(native=("actionPan",))
        iface.layer = layer
        panel = self._panel(iface)
        panel.select_tool("select")
        self.assertFalse(panel.apply())
        self.assertIn("nativa indisponível", panel.status_label.text())

    def test_undo_and_redo_use_the_layer_stack(self):
        layer = _layer("LineString", "linhas", LINES)
        self.project.addMapLayer(layer)
        iface = _Iface()
        iface.layer = layer
        panel = self._panel(iface)
        self.assertFalse(panel.state_of("undo").enabled)
        layer.startEditing()
        layer.beginEditCommand("nova linha")
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt("LineString(30 0, 30 100)"))
        layer.addFeature(feature)
        layer.endEditCommand()
        _wait()
        self.assertIn("em edição", panel.layer_label.text())
        self.assertEqual(layer.featureCount(), 4)
        panel.select_tool("undo")
        self.assertTrue(panel.apply())
        self.assertEqual(layer.featureCount(), 3)
        _wait()
        self.assertFalse(panel.state_of("undo").enabled)
        panel.select_tool("redo")
        self.assertTrue(panel.apply())
        self.assertEqual(layer.featureCount(), 4)
        layer.rollBack()


class DockQgisTest(_Base):
    def _dock(self, enabled):
        from plugin.fortsmart_precision.gui.main_dock import FortSmartDock

        window = QMainWindow()
        iface = _Iface(window)
        with mock.patch.object(feature_flags, "is_enabled", enabled):
            dock = FortSmartDock(iface)
        window.addDockWidget(Qt.RightDockWidgetArea, dock)
        self.addCleanup(window.deleteLater)
        return window, iface, dock

    def test_flags_off_keep_the_panel_as_before(self):
        _window, _iface, dock = self._dock(ALL_OFF)
        self.assertIsNone(dock.tabs)
        self.assertIsNone(dock.agrocad)
        self.assertIsNone(dock.context_service)
        self.assertIs(dock.widget().layout().itemAt(0).widget(), dock.stack)
        self.assertEqual(dock.widget().layout().count(), 1)

    def test_tabs_follow_flags_and_share_one_context(self):
        _window, _iface, dock = self._dock(AGROCAD_ON)
        self.assertEqual([dock.tabs.tabText(i) for i in range(dock.tabs.count())], ["Projeto", "AgroCAD"])
        self.assertIsNone(dock.organizer)
        with mock.patch.object(feature_flags, "is_enabled", BOTH_ON):
            dock.refresh()
        self.assertEqual(
            [dock.tabs.tabText(i) for i in range(dock.tabs.count())], ["Projeto", "AgroCAD", "Camadas"]
        )
        self.assertIs(dock.agrocad.service, dock.organizer.service)
        with mock.patch.object(feature_flags, "is_enabled", AGROCAD_ON):
            dock.refresh()
        self.assertIsNone(dock.organizer)
        self.assertEqual(dock.tabs.count(), 2)
        with mock.patch.object(feature_flags, "is_enabled", ALL_OFF):
            dock.refresh()
        self.assertIsNone(dock.tabs)
        self.assertIsNone(dock.agrocad)
        self.assertIs(dock.widget().layout().itemAt(0).widget(), dock.stack)
        self.assertEqual(dock.widget().layout().count(), 1)

    def test_tool_actions_reach_a_panel_created_later(self):
        _window, _iface, dock = self._dock(ALL_OFF)
        action = QAction("Planejamento")
        dock.set_tool_actions({tools.PLUGIN_WORKSPACE: action})
        with mock.patch.object(feature_flags, "is_enabled", AGROCAD_ON):
            dock.refresh()
        self.assertTrue(dock.agrocad.state_of("workspace").enabled)

    def test_open_close_reopen_keeps_one_set_of_connections(self):
        layer = self._place(_role_layer("01_Limite_Externo", "TL-1"), "TL-1", "00_REFERENCIAS")
        window, iface, dock = self._dock(AGROCAD_ON)
        dock.tabs.setCurrentWidget(dock.agrocad)
        window.show()
        counts = []
        with mock.patch.object(feature_flags, "is_enabled", AGROCAD_ON):
            for _ in range(5):
                dock.show()
                dock.refresh()
                QgsApplication.processEvents()
                iface.setActiveLayer(layer)
                _wait()
                counts.append(dock.agrocad.connection_count)
                self.assertIn("TL-1", dock.agrocad.project_label.text())
                dock.close()
                QgsApplication.processEvents()
                self.assertEqual(dock.agrocad.connection_count, 0)
                iface.setActiveLayer(None)
        self.assertEqual(len(set(counts)), 1)
        self.assertGreater(counts[0], 0)
        self.assertEqual(iface.receivers(iface.currentLayerChanged), 0)

    def test_reopened_dock_follows_the_active_layer_again(self):
        window, iface, dock = self._dock(ALL_OFF)
        window.show()
        dock.show()
        dock.close()
        QgsApplication.processEvents()
        dock.show()
        QgsApplication.processEvents()
        with mock.patch.object(dock, "refresh_layer") as refresh_layer:
            iface.setActiveLayer(None)
        refresh_layer.assert_called_once()
        self.assertEqual(iface.receivers(iface.currentLayerChanged), 1)


class PluginUnloadQgisTest(_Base):
    def test_unload_leaves_no_signal_pointing_to_the_dock(self):
        from plugin.fortsmart_precision.plugin import FortSmartPrecisionPlugin

        window = QMainWindow()
        self.addCleanup(window.deleteLater)
        iface = _Iface(window)
        plugin = FortSmartPrecisionPlugin(iface)
        with mock.patch.object(feature_flags, "is_enabled", BOTH_ON):
            plugin.initGui()
            plugin.open_panel()
            QgsApplication.processEvents()
            dock = plugin.dock
            self.assertIs(dock.agrocad._tool_actions[tools.PLUGIN_OBSTACLE_DETOUR], plugin.action_obstacle_detour)
            self.assertIs(dock.agrocad._tool_actions[tools.PLUGIN_WORKSPACE], plugin.action_workspace)
            plugin.open_panel()
            self.assertIs(plugin.dock, dock)
            plugin.unload()
            QgsApplication.processEvents()
        self.assertIsNone(plugin.dock)
        self.assertEqual(iface.receivers(iface.currentLayerChanged), 0)


if __name__ == "__main__":
    unittest.main()
