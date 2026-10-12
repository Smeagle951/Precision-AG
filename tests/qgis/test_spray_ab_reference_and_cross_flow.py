# -*- coding: utf-8 -*-
"""SKILL 3 — fluxo real do Workspace: A-B original preservada e cruzamento intacto.

Passo 15: selecionar A-B -> gerar aplicacao -> alterar parametros -> gerar de
novo: a A-B continua sendo a linha original (nunca 11_Passadas).
Passo 16: gerar aplicacao -> plantio -> cruzamento (rastros, tramlines,
shutoff), inclusive com desvio da pulverizacao e cabeceira automatica ligados.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from qgis.core import QgsFeature, QgsGeometry, QgsProject, QgsVectorLayer
from qgis.PyQt.QtWidgets import QDialog

from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
from plugin.fortsmart_precision.core.preview_layer_names import find_preview_layer
from plugin.fortsmart_precision.domain.precision_project import (
    SPRAY_HEADLAND_TURN_AUTOMATIC,
    SPRAY_HEADLAND_TURN_MANUAL,
)
from tests.qgis.test_spray_preview_layers_baseline import (
    _setup_qgis,
    enable_spray_avoidance,
    make_dialog,
    set_spray_turn_mode,
)

DIALOG_MODULE = "plugin.fortsmart_precision.gui.fortsmart_workspace_dialog"
AB_WKT = "LINESTRING(0 190, 600 196)"


class _AcceptCross:
    def __init__(self, *_args, **_kwargs):
        pass

    @staticmethod
    def exec_():
        return QDialog.Accepted


class _Errors(Exception):
    pass


def _raise(exc):
    raise _Errors(str(exc)) from exc


def _patched_dialog_env():
    """Sem janelas modais: geracao sincrona, confirmacao do cruzamento aceita."""
    return (
        patch(f"{DIALOG_MODULE}.run_precision_lines_with_progress",
              side_effect=lambda _parent, project, **_kw: run_precision_lines(project)),
        patch(f"{DIALOG_MODULE}.QMessageBox", MagicMock()),
        patch(f"{DIALOG_MODULE}.CrossConfirmDialog", _AcceptCross),
    )


class _FlowCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()

    def setUp(self):
        self.dialog = make_dialog()
        self._patches = list(_patched_dialog_env())
        self.message_box = None
        for p in self._patches:
            started = p.start()
            if isinstance(started, MagicMock) and p.attribute == "QMessageBox":
                self.message_box = started
        self.dialog._warn_crs_error = _raise

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        self.dialog.reject()
        QgsProject.instance().clear()

    def _layer(self, short_name):
        return find_preview_layer(self.dialog._field_scoped_layers(), short_name)


class AbReferenceFlowTest(_FlowCase):
    def setUp(self):
        super().setUp()
        self.ab_layer = QgsVectorLayer("LineString?crs=EPSG:31982", "AB_original", "memory")
        feature = QgsFeature()
        feature.setGeometry(QgsGeometry.fromWkt(AB_WKT))
        self.ab_layer.dataProvider().addFeature(feature)
        QgsProject.instance().addMapLayer(self.ab_layer)
        self.dialog.ab_layer_combo.setLayer(self.ab_layer)
        self.dialog._load_ab_from_layer()
        self.dialog.spray_ab_combo.setLayer(self.ab_layer)
        self.original = (self.dialog.ab_start, self.dialog.ab_end, tuple(self.dialog.ab_path_points))

    def _assert_ab_original(self):
        self.assertIs(self.dialog.spray_ab_combo.currentLayer(), self.ab_layer)
        current = (self.dialog.ab_start, self.dialog.ab_end, tuple(self.dialog.ab_path_points))
        for got, expected in zip(current[:2], self.original[:2]):
            self.assertAlmostEqual(got[0], expected[0], places=6)
            self.assertAlmostEqual(got[1], expected[1], places=6)
        self.assertEqual(len(current[2]), len(self.original[2]))

    def test_ab_stays_original_after_regenerating_with_new_parameters(self):
        self.assertAlmostEqual(self.original[0][1], 190.0, places=6)
        self.dialog._generate_application()
        passes = self._layer("05_Passadas")
        self.assertIsNotNone(passes)
        first = [tuple(p.line_points()) for p in self.dialog.last_result.spraying_passes]
        self._assert_ab_original()
        self.assertIsNot(self.dialog.spray_ab_combo.currentLayer(), passes)

        self.dialog.sprayer_widget.nozzle_count_spin.setValue(60)  # barra 30 m
        self.dialog._generate_application()
        second = [tuple(p.line_points()) for p in self.dialog.last_result.spraying_passes]
        self.assertNotEqual(first, second)
        self._assert_ab_original()
        self.assertIsNot(self.dialog.spray_ab_combo.currentLayer(), self._layer("05_Passadas"))

    def test_generated_passes_refused_as_ab_with_clear_message(self):
        self.dialog._generate_application()
        passes = self._layer("05_Passadas")
        self.dialog._refresh_operation_layer_combos()
        self.dialog.spray_ab_combo.setLayer(passes)
        self.assertIsNot(self.dialog.spray_ab_combo.currentLayer(), passes)  # combo nao oferece
        messages = []
        self.dialog._warn_crs_error = lambda exc: messages.append(str(exc))
        self.dialog.spray_ab_combo.setExceptedLayerList([])
        self.dialog.spray_ab_combo.setLayer(passes)
        self.assertIs(self.dialog.spray_ab_combo.currentLayer(), passes)
        self.dialog._generate_application()
        self.assertEqual(len(messages), 1)
        self.assertIn("nao pode ser usada como A-B", messages[0])
        self.dialog.spray_ab_combo.setLayer(self.ab_layer)
        self._assert_ab_original()

        self.message_box.warning.reset_mock()
        self.dialog.ab_layer_combo.setLayer(passes)
        self.dialog._load_ab_from_layer()
        self.message_box.warning.assert_called_once()
        self.assertIn("nao pode ser usada como A-B", self.message_box.warning.call_args[0][2])
        self._assert_ab_original()

    def test_multiple_base_lines_require_one_selected_feature(self):
        layer = QgsVectorLayer("LineString?crs=EPSG:31982", "bases_spray", "memory")
        features = []
        for wkt in (
            "LINESTRING (500000 8200000, 500200 8200000)",
            "LINESTRING (500000 8200010, 500200 8200010)",
        ):
            feature = QgsFeature()
            feature.setGeometry(QgsGeometry.fromWkt(wkt))
            features.append(feature)
        layer.dataProvider().addFeatures(features)
        QgsProject.instance().addMapLayer(layer)
        self.dialog.spray_ab_combo.setLayer(layer)

        with self.assertRaisesRegex(ValueError, "possui varias feicoes"):
            self.dialog._activate_ab_for_operation("spraying")

        feature_id = next(layer.getFeatures()).id()
        layer.selectByIds([feature_id])
        self.dialog.spray_ab_selected_only.setChecked(True)
        self.dialog._activate_ab_for_operation("spraying")
        self.assertIn(f"ID {feature_id}", self.dialog.spray_ab_summary.text())


class AbReferenceComboTest(_FlowCase):
    def test_optional_ab_combos_start_empty_and_never_jump_to_other_line(self):
        self.assertIsNone(self.dialog.spray_ab_combo.currentLayer())
        self.assertIsNone(self.dialog.plant_ab_combo.currentLayer())
        posts = QgsProject.instance().mapLayersByName("Postes")[0]
        self.dialog.spray_ab_combo.setLayer(posts)
        self.dialog._refresh_ab_reference_combo(self.dialog.spray_ab_combo)
        self.assertIsNone(self.dialog.spray_ab_combo.currentLayer())  # ponto nao e A-B: vazio

        self.dialog._generate_application()
        passes = self._layer("05_Passadas")
        self.dialog._refresh_ab_reference_combo(self.dialog.spray_ab_combo)
        self.assertIsNone(self.dialog.spray_ab_combo.currentLayer())
        self.dialog.spray_ab_combo.setLayer(passes)
        self.assertIsNone(self.dialog.spray_ab_combo.currentLayer())  # passada gerada fora da lista
        self.dialog.spray_ab_combo.setExceptedLayerList([])
        self.dialog.spray_ab_combo.setLayer(passes)
        self.dialog._refresh_ab_reference_combo(self.dialog.spray_ab_combo)
        self.assertIs(self.dialog.spray_ab_combo.currentLayer(), passes)  # mantida para o aviso


def _signature(result):
    return {
        "spray": [tuple(round(c, 3) for pt in p.line_points() for c in pt) for p in result.spraying_passes],
        "tracks": sorted(
            (str(t.pass_id), str(t.side), tuple(round(c, 3) for pt in t.points for c in pt))
            for t in result.tire_tracks
        ),
        "tramlines": len(result.tramline_zones),
        "shutoff": len(result.shutoff_segments),
        "rows": len(result.planting_rows),
    }


class CrossFlowTest(_FlowCase):
    """Talhao 180 x 120 m com entalhe: o shutoff por linha de semente e caro no talhao grande."""

    def setUp(self):
        super().setUp()
        self.dialog.reject()
        self.dialog = make_dialog(
            ring="0 0,180 0,180 120,100 120,90 105,80 120,0 120,0 0",
            post_xy=(90.0, 60.0),
            ab=((0.0, 56.0), (180.0, 56.0)),
        )
        self.dialog.sprayer_widget.nozzle_count_spin.setValue(40)  # barra 20 m: 3 passadas no miolo
        self.dialog._warn_crs_error = _raise

    def _flow(self, turn_mode):
        enable_spray_avoidance(self.dialog, 8.0)
        set_spray_turn_mode(self.dialog, turn_mode, radius=8.0)
        self.dialog.shutoff_tramline_check.setChecked(True)
        self.dialog._generate_application()
        spray = self.dialog.last_result
        self.assertTrue(spray.spray_avoidance_records)
        self.dialog._generate_planting()
        planted = self.dialog.last_result
        self.assertIs(planted.spraying_passes, spray.spraying_passes)
        self.assertTrue(planted.planting_rows or planted.planting_passes)
        self.dialog._cross_layers()
        crossed = self.dialog.last_result
        self.assertTrue(crossed.planting_rows)
        self.assertTrue(crossed.tire_tracks)
        self.assertGreater(len(crossed.tramline_zones), 0)
        self.assertGreater(len(crossed.shutoff_segments), 0)
        self.assertIsNotNone(self.dialog.operational_draft)
        self.assertTrue(self.dialog.save_operational_btn.isEnabled())
        self.assertIn("Calculado", self.dialog.operational_state_label.text())
        self.assertEqual(
            [p.line_points() for p in crossed.spraying_passes],
            [p.line_points() for p in spray.spraying_passes],
        )
        return spray, crossed

    def test_cross_manual_then_detour_and_automatic_headland(self):
        _spray, manual = self._flow(SPRAY_HEADLAND_TURN_MANUAL)
        self.assertIsNone(manual.spray_headland_turns)
        self.assertIsNone(self._layer("16_Manobras_Cabeceira"))
        manual_signature = _signature(manual)
        self.tearDown()
        self.setUp()
        spray, auto = self._flow(SPRAY_HEADLAND_TURN_AUTOMATIC)
        self.assertEqual(spray.project.spray_headland_turn_mode, SPRAY_HEADLAND_TURN_AUTOMATIC)
        self.assertIs(auto.spray_headland_turns, spray.spray_headland_turns)
        self.assertGreater(len(auto.spray_headland_turns.turns), 0, auto.spray_headland_turns.report)
        # Curvas sao feicoes separadas: rastros, tramlines e shutoff iguais ao modo manual.
        self.assertEqual(_signature(auto), manual_signature)
        turn_layer = [
            layer for layer in QgsProject.instance().mapLayers().values()
            if layer.customProperty("fortsmart_role", "") == "HEADLAND_TURN"
        ]
        self.assertEqual(len(turn_layer), 1)
        self.assertEqual(turn_layer[0].featureCount(), len(auto.spray_headland_turns.turns))

    def test_existing_spray_passes_use_only_selected_features(self):
        self.dialog._generate_planting()
        layer = QgsVectorLayer("LineString?crs=EPSG:31982", "spray_real", "memory")
        features = []
        for wkt in (
            "LINESTRING (70 0, 70 120)",
            "LINESTRING (110 0, 110 120)",
        ):
            feature = QgsFeature()
            feature.setGeometry(QgsGeometry.fromWkt(wkt))
            features.append(feature)
        layer.dataProvider().addFeatures(features)
        QgsProject.instance().addMapLayer(layer)
        self.dialog._refresh_operation_layer_combos()
        mode_index = self.dialog.spray_source_mode_combo.findData("existing_passes")
        self.dialog.spray_source_mode_combo.setCurrentIndex(mode_index)
        self.dialog.spray_line_combo.setLayer(layer)

        with self.assertRaisesRegex(_Errors, "Nenhuma feicao"):
            self.dialog._cross_layers()

        selected_id = next(layer.getFeatures()).id()
        layer.selectByIds([selected_id])
        self.dialog._refresh_cross_spray_selection()
        self.dialog._cross_layers()

        self.assertEqual(len(self.dialog.last_result.spraying_passes), 1)
        self.assertTrue(
            self.dialog.last_result.spraying_passes[0].fs_id.endswith(f":{selected_id}")
        )
        self.assertIn("Passadas analisadas: 1", self.dialog.cross_result_summary.text())

        layer.selectByIds([])
        self.assertIsNone(self.dialog.operational_draft)
        self.assertFalse(self.dialog.save_operational_btn.isEnabled())
        self.assertIn("Desatualizado", self.dialog.operational_state_label.text())


if __name__ == "__main__":
    unittest.main()
