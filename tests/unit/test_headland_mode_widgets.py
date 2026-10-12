# -*- coding: utf-8 -*-
"""Seletor LEGACY/FIDELITY da bordadura nas telas de maquina."""

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
class HeadlandModeWidgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QgsApplication.instance() is None:
            cls.app = QgsApplication([], True)
            cls.app.initQgis()

    def test_combo_defaults_to_legacy(self):
        from plugin.fortsmart_precision.domain.headland_layout import (
            HEADLAND_MODE_FIDELITY,
            HEADLAND_MODE_LEGACY,
        )
        from plugin.fortsmart_precision.gui.machine_config_widgets import build_headland_mode_combo

        combo = build_headland_mode_combo()
        self.assertEqual(combo.currentData(), HEADLAND_MODE_LEGACY)
        self.assertEqual([combo.itemData(i) for i in range(combo.count())], [HEADLAND_MODE_LEGACY, HEADLAND_MODE_FIDELITY])

    def test_planter_and_sprayer_expose_selected_mode(self):
        from plugin.fortsmart_precision.domain.headland_layout import (
            HEADLAND_MODE_FIDELITY,
            HEADLAND_MODE_LEGACY,
        )
        from plugin.fortsmart_precision.gui.machine_config_widgets import (
            PlanterConfigWidget,
            SprayerConfigWidget,
        )

        for widget in (PlanterConfigWidget(), SprayerConfigWidget()):
            with self.subTest(widget=type(widget).__name__):
                self.assertEqual(widget.headland_mode(), HEADLAND_MODE_LEGACY)
                widget.headland_mode_combo.setCurrentIndex(1)
                self.assertEqual(widget.headland_mode(), HEADLAND_MODE_FIDELITY)


if __name__ == "__main__":
    unittest.main()
