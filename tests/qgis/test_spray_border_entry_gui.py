# -*- coding: utf-8 -*-
"""Fase 2 GUI: entra e sai so no Workspace, chave desligada, sem gravacao."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from qgis.PyQt.QtCore import QVariant
from qgis.core import QgsFeature, QgsField, QgsProject, QgsVectorLayer

from plugin.fortsmart_precision import feature_flags
from plugin.fortsmart_precision.core.layer_roles import HEADLAND_TURN_ROLE
from plugin.fortsmart_precision.domain.precision_project import SPRAY_HEADLAND_TURN_AUTOMATIC
from tests.qgis.test_spray_preview_layers_baseline import _setup_qgis, make_dialog, set_spray_turn_mode


class SprayBorderEntryGuiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()

    def tearDown(self):
        if getattr(self, "dialog", None) is not None:
            self.dialog.reject()
        QgsProject.instance().clear()

    def test_flag_off_hides_box(self):
        self.dialog = make_dialog()
        self.assertFalse(self.dialog.border_entry_box.isVisible())
        self.assertFalse(self.dialog.border_entry_confirm_btn.isEnabled())

    def test_flag_on_shows_preview_without_confirm_or_persist(self):
        with patch.object(feature_flags, "is_enabled", return_value=True):
            self.dialog = make_dialog()
        self.dialog.border_entry_box.setVisible(True)
        self.assertTrue(self.dialog.border_entry_preview_btn.isEnabled())
        self.assertFalse(self.dialog.border_entry_confirm_btn.isEnabled())
        self.assertEqual(self.dialog.border_entry_component_combo.count(), 4)
        before = {
            layer.id()
            for layer in QgsProject.instance().mapLayers().values()
            if layer.customProperty("fortsmart_role", "") == HEADLAND_TURN_ROLE.role
        }
        self.dialog._cancel_spray_border_entry()
        after = {
            layer.id()
            for layer in QgsProject.instance().mapLayers().values()
            if layer.customProperty("fortsmart_role", "") == HEADLAND_TURN_ROLE.role
        }
        self.assertEqual(before, after)

    def test_preview_refuses_automatic_u_turns(self):
        self.dialog = make_dialog()
        self.dialog.border_entry_box.setVisible(True)
        self.dialog._spray_border_entry_flag_on = lambda: True
        set_spray_turn_mode(self.dialog, SPRAY_HEADLAND_TURN_AUTOMATIC, radius=8.0)
        self.dialog.last_result = type("R", (), {"spraying_passes": [object()], "spraying_boundary": None})()
        from qgis.PyQt.QtWidgets import QMessageBox

        with patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok) as warn:
            self.dialog._preview_spray_border_entry()
        warn.assert_called()
        self.assertIn("manobra automática", warn.call_args[0][2].lower())

    def test_existing_eight_u_turns_are_reported_without_changes(self):
        self.dialog = make_dialog()
        layer = QgsVectorLayer("LineString?crs=EPSG:31981", "16_Manobras_Cabeceira", "memory")
        layer.dataProvider().addAttributes([QgsField("turn_type", QVariant.String)])
        layer.updateFields()
        features = []
        for _index in range(8):
            feature = QgsFeature(layer.fields())
            feature.setAttribute("turn_type", "U_TURN")
            features.append(feature)
        layer.dataProvider().addFeatures(features)
        layer.setCustomProperty("fortsmart_role", "HEADLAND_TURN")
        QgsProject.instance().addMapLayer(layer)
        before = layer.featureCount()
        text = self.dialog._existing_spray_turn_diagnostic()
        self.assertIn("motor antigo=8", text)
        self.assertIn("BORDER_TRANSIT persistido=0", text)
        self.assertEqual(layer.featureCount(), before)
