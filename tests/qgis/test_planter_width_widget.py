# -*- coding: utf-8 -*-
"""Tela da plantadeira: largura de trabalho informada posiciona as passadas."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from qgis.core import QgsApplication

    HAS_QGIS = True
except ImportError:
    HAS_QGIS = False


@unittest.skipUnless(HAS_QGIS, "QGIS nao disponivel")
class PlanterWidthWidgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QgsApplication.instance() is None:
            cls.app = QgsApplication([], True)
            cls.app.initQgis()

    def widget(self, width=20.0):
        from plugin.fortsmart_precision.gui.machine_config_widgets import PlanterConfigWidget

        widget = PlanterConfigWidget()
        widget.row_count_spin.setValue(38)
        widget.row_spacing_spin.setValue(0.5)
        widget.informed_width_spin.setValue(width)
        return widget

    def test_empty_widget_requires_real_measurements(self):
        from plugin.fortsmart_precision.gui.machine_config_widgets import PlanterConfigWidget

        widget = PlanterConfigWidget()
        self.assertEqual(widget.row_count_spin.value(), 0)
        self.assertEqual(widget.row_spacing_spin.value(), 0.0)
        self.assertEqual(widget.informed_width_spin.value(), 0.0)
        self.assertIn("Informe", widget.width_status_label.text())
        with self.assertRaises(ValueError):
            widget.build_machine()

    def test_manual_width_does_not_invent_planter_track(self):
        from plugin.fortsmart_precision.core.planting_kinematics_engine import kinematics_from_planter

        widget = self.widget(width=19.0)
        machine = widget.build_machine()
        self.assertAlmostEqual(machine.operational_width_m, 19.0)
        self.assertIsNone(machine.track)
        self.assertIsNone(machine.to_dict()["track_width_m"])
        self.assertEqual(kinematics_from_planter(machine).track_width_m, 0.0)

    def test_physical_width_is_separate_from_pass_spacing(self):
        widget = self.widget(width=0.0)
        widget.use_calculated_width_check.setChecked(True)
        widget.physical_width_spin.setValue(20.0)
        machine = widget.build_machine()
        self.assertAlmostEqual(machine.operational_width_m, 19.0)
        self.assertAlmostEqual(machine.physical_width_m, 20.0)
        self.assertAlmostEqual(machine.meeting_spacing_m(), 0.5)
        self.assertIn("Largura fisica total: 20.00 m", widget.planter_summary_label.text())

    def test_working_width_drives_passes_and_rows_only_warn(self):
        widget = self.widget()
        self.assertAlmostEqual(widget.effective_width_m(), 20.0)
        self.assertIn("19.000 m (apenas conferencia)", widget.calc_width_label.text())
        status = widget.width_status_label.text()
        self.assertIn("GEOMETRY_WIDTH_MISMATCH", status)
        self.assertIn("Largura de trabalho configurada: 20.00 m", status)
        self.assertIn("Largura equivalente pelas linhas: 19.00 m", status)
        self.assertIn("Distancia entre passadas mantida: 20.00 m", status)
        self.assertEqual(
            widget.planter_summary_label.text(),
            "Plantadeira: 38 linhas × 0.50 m\nLargura de trabalho: 20.00 m\n"
            "Largura pelas linhas: 19.00 m\nEncontro entre passadas: 1.50 m",
        )
        self.assertIn("FALHA", widget.meeting_label.text())
        machine = widget.build_machine()
        self.assertAlmostEqual(machine.operational_width_m, 20.0)
        self.assertAlmostEqual(widget.headland_total_width_m(), 20.0)
        self.assertFalse(hasattr(widget, "override_check"))

    def test_without_width_uses_rows(self):
        widget = self.widget(width=0.0)
        with self.assertRaisesRegex(ValueError, "confirme"):
            widget.build_machine()
        widget.use_calculated_width_check.setChecked(True)
        self.assertAlmostEqual(widget.effective_width_m(), 19.0)
        self.assertEqual(widget.width_status_label.text(), "Distancia entre passadas: 19.00 m")
        self.assertIsNone(widget.build_machine().informed_operational_width_m)


if __name__ == "__main__":
    unittest.main()
