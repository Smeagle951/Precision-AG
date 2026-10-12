# -*- coding: utf-8 -*-
"""GUI da cabeceira da pulverizacao: combo, independencia e bloqueio sem raio."""

from __future__ import annotations

import unittest

from qgis.core import QgsProject

from plugin.fortsmart_precision.domain.headland_layout import HEADLAND_MODE_FIDELITY
from plugin.fortsmart_precision.domain.precision_project import (
    SPRAY_HEADLAND_TURN_AUTOMATIC,
    SPRAY_HEADLAND_TURN_MANUAL,
)
from plugin.fortsmart_precision.gui.machine_config_widgets import SprayerConfigWidget
from tests.qgis.test_spray_preview_layers_baseline import _setup_qgis, make_dialog, set_spray_turn_mode


class SprayerTurnModeWidgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()

    def test_default_is_straight_extension_with_two_options(self):
        widget = SprayerConfigWidget()
        combo = widget.spray_turn_mode_combo
        self.assertEqual(
            [(combo.itemText(i), combo.itemData(i)) for i in range(combo.count())],
            [("Extensão reta / operador manobra", SPRAY_HEADLAND_TURN_MANUAL),
             ("Manobra automática", SPRAY_HEADLAND_TURN_AUTOMATIC)],
        )
        self.assertEqual(widget.spray_headland_turn_mode(), SPRAY_HEADLAND_TURN_MANUAL)
        self.assertIn("operador manobra", widget.spray_turn_mode_hint.text())

    def test_turn_mode_independent_from_border_mode(self):
        widget = SprayerConfigWidget()
        legacy_mode = widget.headland_mode()
        combo = widget.spray_turn_mode_combo
        combo.setCurrentIndex(combo.findData(SPRAY_HEADLAND_TURN_AUTOMATIC))
        self.assertEqual(widget.headland_mode(), legacy_mode)
        self.assertIn("raio >= minimo do PULVERIZADOR", widget.spray_turn_mode_hint.text())
        border = widget.headland_mode_combo
        border.setCurrentIndex(border.findData(HEADLAND_MODE_FIDELITY))
        self.assertEqual(widget.headland_mode(), HEADLAND_MODE_FIDELITY)
        self.assertEqual(widget.spray_headland_turn_mode(), SPRAY_HEADLAND_TURN_AUTOMATIC)


class DialogTurnModeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()

    def setUp(self):
        self.dialog = make_dialog()

    def tearDown(self):
        self.dialog.reject()
        QgsProject.instance().clear()

    def test_automatic_without_sprayer_radius_blocks_with_clear_message(self):
        set_spray_turn_mode(self.dialog, SPRAY_HEADLAND_TURN_AUTOMATIC, radius=0.0)
        self.dialog.planter_widget.turn_radius_spin.setValue(6.0)  # nunca usado na pulverizacao
        self.dialog._sync_spray_avoid_controls()
        self.assertIn("Manobra automatica sem raio", self.dialog.sprayer_widget.spray_turn_mode_hint.text())
        with self.assertRaises(ValueError) as ctx:
            self.dialog._build_project(include_planting=False, include_spraying=True)
        self.assertIn("raio minimo de giro do pulverizador", str(ctx.exception))
        self.assertIn("raio da plantadeira nao e usado", str(ctx.exception))

    def test_manual_without_radius_still_generates(self):
        self.dialog.spray_turn_radius_spin.setValue(0.0)
        project = self.dialog._build_project(include_planting=False, include_spraying=True)
        self.assertEqual(project.spray_headland_turn_mode, SPRAY_HEADLAND_TURN_MANUAL)
        self.assertEqual(project.obstacles, ())

    def test_automatic_keeps_planting_turn_mode_separate(self):
        set_spray_turn_mode(self.dialog, SPRAY_HEADLAND_TURN_AUTOMATIC, radius=8.0)
        self.assertTrue(self.dialog.spray_turn_radius_spin.isEnabled())
        spray = self.dialog._build_project(include_planting=False, include_spraying=True)
        self.assertEqual(spray.spray_headland_turn_mode, SPRAY_HEADLAND_TURN_AUTOMATIC)
        self.assertEqual(spray.spraying.machine.sprayer_minimum_turn_radius_m, 8.0)
        self.assertEqual(spray.headland_turn_mode, "extend")
        self.assertFalse(spray.avoidance.enabled())  # desvio continua desligado
        self.assertEqual(len(spray.obstacles), 1)  # so para a curva respeitar a zona de seguranca
        planting = self.dialog._build_project(include_planting=True, include_spraying=False)
        self.assertEqual(planting.spray_headland_turn_mode, SPRAY_HEADLAND_TURN_MANUAL)
        self.assertEqual(planting.headland_turn_mode, self.dialog.planter_widget.headland_turn_mode())


if __name__ == "__main__":
    unittest.main()
