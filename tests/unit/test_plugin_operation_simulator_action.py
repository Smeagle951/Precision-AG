# -*- coding: utf-8 -*-
"""Testes do atalho de menu/barra para o Simulador de Operacao."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from qgis.core import QgsApplication

    HAS_QGIS = True
except ImportError:
    HAS_QGIS = False


def _qgis_app():
    app = QgsApplication.instance()
    if app is None:
        app = QgsApplication([], True)
        app.initQgis()
    return app


@unittest.skipUnless(HAS_QGIS, "QGIS nao disponivel")
class OperationSimulatorActionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _qgis_app()
        from plugin.fortsmart_precision import plugin as plugin_module

        cls.plugin_module = plugin_module

    def _plugin(self):
        iface = MagicMock()
        iface.mainWindow.return_value = None
        return self.plugin_module.FortSmartPrecisionPlugin(iface), iface

    def test_algorithm_id_matches_registered_algorithm(self):
        from plugin.fortsmart_precision.algorithms.simulate_real_operation import (
            SimulateRealOperationAlgorithm,
        )
        from plugin.fortsmart_precision.provider import FortSmartProvider

        expected = f"{FortSmartProvider().id()}:{SimulateRealOperationAlgorithm().name()}"
        self.assertEqual(self.plugin_module.OPERATION_SIMULATOR_ALGORITHM_ID, expected)

    def test_init_gui_adds_simulator_to_menu_and_toolbar(self):
        plugin, iface = self._plugin()
        with patch.object(QgsApplication, "processingRegistry"):
            plugin.initGui()

        action = plugin.action_operation_simulator
        self.assertIsNotNone(action)
        self.assertEqual(action.text(), "Simulador de Operacao")
        iface.addPluginToMenu.assert_any_call("FortSmart Precision", action)
        iface.addToolBarIcon.assert_any_call(action)

        with patch.object(QgsApplication, "processingRegistry"):
            plugin.unload()
        iface.removePluginMenu.assert_any_call("FortSmart Precision", action)
        iface.removeToolBarIcon.assert_any_call(action)

    def test_simulator_action_opens_route_simulator_and_xray_stays_in_menu(self):
        plugin, iface = self._plugin()
        with patch.object(QgsApplication, "processingRegistry"):
            plugin.initGui()
        self.assertEqual(plugin.action_coverage_xray.text(), "Raio-X de cobertura (analise)")
        iface.addPluginToMenu.assert_any_call("FortSmart Precision", plugin.action_coverage_xray)
        with patch("plugin.fortsmart_precision.gui.route_simulation_dialog.RouteSimulationDialog") as dialog:
            plugin.action_operation_simulator.trigger()
            plugin.action_operation_simulator.trigger()
        dialog.assert_called_once_with(iface)
        self.assertEqual(dialog.return_value.show.call_count, 2)
        with patch.object(QgsApplication, "processingRegistry"):
            plugin.unload()
        dialog.return_value.close.assert_called_once()
        iface.removePluginMenu.assert_any_call("FortSmart Precision", plugin.action_coverage_xray)

    def test_open_operation_simulator_opens_processing_dialog(self):
        plugin, _iface = self._plugin()
        fake_processing = MagicMock()
        with patch.dict(sys.modules, {"processing": fake_processing}):
            plugin.open_operation_simulator()
        fake_processing.execAlgorithmDialog.assert_called_once_with(
            "fortsmart_precision:simulate_real_operation", {}
        )

    def test_open_operation_simulator_warns_without_processing(self):
        plugin, _iface = self._plugin()
        with patch.dict(sys.modules, {"processing": None}), patch.object(
            self.plugin_module.QMessageBox, "warning"
        ) as warning:
            plugin.open_operation_simulator()
        warning.assert_called_once()

    def test_persist_action_is_in_menu(self):
        plugin, iface = self._plugin()
        with patch.object(QgsApplication, "processingRegistry"):
            plugin.initGui()
        action = plugin.action_persist_layers
        self.assertEqual(action.text(), "Persistir camadas FortSmart")
        iface.addPluginToMenu.assert_any_call("FortSmart Precision", action)
        with patch.object(QgsApplication, "processingRegistry"):
            plugin.unload()
        iface.removePluginMenu.assert_any_call("FortSmart Precision", action)

    def test_persist_layers_warns_when_project_is_not_saved(self):
        from qgis.core import QgsProject

        plugin, _iface = self._plugin()
        QgsProject.instance().clear()
        with patch.object(self.plugin_module.QMessageBox, "warning") as warning, \
                patch.object(self.plugin_module.QMessageBox, "information") as information:
            plugin.persist_layers()
        warning.assert_called_once()
        self.assertIn("Salve o projeto QGIS", warning.call_args[0][2])
        information.assert_not_called()

    def test_persist_layers_shows_storage_report(self):
        report = {"text": "FORTSMART STORAGE REPORT\n..."}
        plugin, _iface = self._plugin()
        with patch.object(self.plugin_module, "persist_generated_memory_layers", return_value=report), \
                patch.object(self.plugin_module.QMessageBox, "information") as information:
            plugin.persist_layers()
        self.assertIn("FORTSMART STORAGE REPORT", information.call_args[0][2])


if __name__ == "__main__":
    unittest.main()
