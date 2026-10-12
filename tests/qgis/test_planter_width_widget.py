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
        self.assertAlmostEqual(widget.effective_width_m(), 19.0)
        self.assertEqual(widget.width_status_label.text(), "Distancia entre passadas: 19.00 m")
        self.assertIsNone(widget.build_machine().informed_operational_width_m)


if __name__ == "__main__":
    unittest.main()
