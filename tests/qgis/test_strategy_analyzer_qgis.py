# -*- coding: utf-8 -*-
"""Analisador de estrategias no QGIS: preview temporario, escolha manual e WORK_PATH unico."""

from __future__ import annotations

import math
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
)

from plugin.fortsmart_precision.core.export_readiness_validator import validate_field_for_export
from plugin.fortsmart_precision.core.layer_roles import (
    canonical_field_name,
    is_temporary_preview,
    layer_role,
)
from plugin.fortsmart_precision.core.persistence_manager import FortSmartPersistenceManager
from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
from plugin.fortsmart_precision.domain.machine_model import PlanterMachine, load_machine_presets
from plugin.fortsmart_precision.domain.precision_project import (
    ABLine,
    FieldGeometry,
    PrecisionOperation,
    PrecisionProject,
)
from plugin.fortsmart_precision.gui import layer_tree_organizer as organizer
from plugin.fortsmart_precision.strategy_analyzer.field_context import FieldContext
from plugin.fortsmart_precision.strategy_analyzer.models import (
    CURVE_REFERENCE_REQUIRED,
    STRATEGY_SAVE_FAILED,
    StrategyAnalysisConfig,
    StrategyAnalysisError,
    StrategyType,
)
from plugin.fortsmart_precision.strategy_analyzer.strategy_analyzer import LineStrategyAnalyzer
from plugin.fortsmart_precision.strategy_analyzer.strategy_preview import (
    PREVIEW_CURVE_NAME,
    PREVIEW_STRAIGHT_NAME,
    StrategyPreviewManager,
    preview_layers,
)
from plugin.fortsmart_precision.strategy_analyzer.strategy_save import (
    SAVE_NEW_VERSION,
    SAVE_REPLACE,
    has_existing_work_path,
    materialize_as_work_path,
)

_APP = None
CRS = "EPSG:31982"
FIELD = "TL-13"
WORK_PATH_NAME = "12_Passadas_Plantio"


def _setup_qgis():
    global _APP
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if QgsApplication.instance() is None:
        _APP = QgsApplication([], True)
        _APP.initQgis()


def _field_polygons():
    south = [(float(x), -60.0 * math.sin(math.pi * x / 600.0)) for x in range(0, 601, 25)]
    outer = south + [(600.0, 260.0), (0.0, 260.0), south[0]]
    return [(outer, [])]


def _reference():
    return tuple((float(x), 130.0 - 60.0 * math.sin(math.pi * x / 600.0)) for x in range(0, 601, 20))


def _analysis(field_id=FIELD, offset=0.0):
    polygons = [([(x + offset, y + offset) for x, y in outer], []) for outer, _holes in _field_polygons()]
    context = FieldContext(
        field_id=field_id,
        work_area=polygons,
        allowed_area=polygons,
        operational_boundary=polygons,
        pass_spacing_m=18.0,
        operation_width_m=18.0,
        extension_m=0.0,
        reference_curve=tuple((x + offset, y + offset) for x, y in _reference()),
        reference_id="ref",
    )
    return LineStrategyAnalyzer().analyze(context, StrategyAnalysisConfig(straight_angle_step=15.0))


def _work_paths(project, field_name=FIELD):
    field_id = canonical_field_name(field_name)
    return [
        layer for layer in project.mapLayers().values()
        if layer_role(layer) == "WORK_PATH" and layer.customProperty("fortsmart_field_id", "") == field_id
    ]


def _planter() -> PlanterMachine:
    machine = load_machine_presets()["db27_36x050"]
    assert isinstance(machine, PlanterMachine)
    return machine


def _precision_project(polygons=None):
    polygons = polygons or [([(0.0, 0.0), (400.0, 0.0), (400.0, 240.0), (0.0, 240.0), (0.0, 0.0)], [])]
    return PrecisionProject(
        field=FieldGeometry(
            field_id=FIELD, field_boundary=polygons, operational_boundary=polygons, crs_authid=CRS
        ),
        ab_line=ABLine(start=(0.0, 120.0), end=(400.0, 120.0)),
        planting=PrecisionOperation(
            operation_id="planting",
            machine=_planter(),
            headland=HeadlandLayout(pass_count=1, width_m=18.0, effective_spacing_m=18.0, mode="parallel_ab"),
        ),
    )


class _StrategyTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()
        cls.result = _analysis()
        cls.straight = next(c for c in cls.result.preview_candidates if c.strategy_type is StrategyType.STRAIGHT)
        cls.curve = cls.result.curve_candidate()
        assert cls.curve is not None and cls.curve.valid
        assert cls.straight.line_count != cls.curve.line_count or cls.straight.total_length_m != cls.curve.total_length_m

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.project = QgsProject.instance()
        self.project.clear()

    def tearDown(self):
        self.project.clear()
        self.project.setFileName("")
        shutil.rmtree(self.tmp, ignore_errors=True)

    def save_project(self):
        self.project.setFileName(str(self.tmp / "fazenda.qgz"))


class StrategyPreviewTest(_StrategyTestBase):
    def test_preview_is_temporary_without_role_and_skipped_by_export(self):
        previews = StrategyPreviewManager(CRS, FIELD)
        straight_layer = previews.show_candidate(self.straight)
        curve_layer = previews.show_candidate(self.curve)
        self.assertTrue(straight_layer.name().startswith(PREVIEW_STRAIGHT_NAME))
        self.assertEqual(curve_layer.name(), PREVIEW_CURVE_NAME)
        for layer in (straight_layer, curve_layer):
            self.assertTrue(layer.customProperty("fortsmart_preview"))
            self.assertTrue(is_temporary_preview(layer))
            self.assertEqual(layer_role(layer), "")
            self.assertEqual(layer.providerType(), "memory")
            self.assertTrue(organizer.in_preview_group(self.project.layerTreeRoot(), layer))
        self.assertEqual(straight_layer.featureCount(), self.straight.line_count)
        self.assertEqual(_work_paths(self.project), [])
        report = validate_field_for_export(FIELD)
        work = [item for item in report.role_report if item.role == "WORK_PATH"]
        self.assertTrue(not work or work[0].layer_count == 0)
        names = [layer.name() for layer in self.project.mapLayers().values()]
        self.assertFalse(any(name.startswith(WORK_PATH_NAME) for name in names))

    def test_preview_never_persisted_by_migration(self):
        self.save_project()
        previews = StrategyPreviewManager(CRS, FIELD)
        previews.show_candidate(self.straight)
        report = organizer.persist_generated_memory_layers(self.project)
        self.assertEqual(report["entries"], [])
        manager = FortSmartPersistenceManager(self.project)
        self.assertFalse(manager.get_field_storage_path(FIELD).exists())

    def test_show_again_replaces_and_clear_removes_all(self):
        previews = StrategyPreviewManager(CRS, FIELD)
        first = previews.show_candidate(self.straight)
        first_id = first.id()
        second_id = previews.show_candidate(self.straight).id()
        self.assertIsNone(self.project.mapLayer(first_id))
        self.assertEqual(len(preview_layers(self.project, FIELD)), 1)
        previews.hide_candidate(self.straight.candidate_id)
        self.assertIsNone(self.project.mapLayer(second_id))
        previews.show_candidate(self.straight)
        previews.show_candidate(self.curve)
        previews.clear_previews()
        self.assertEqual(preview_layers(self.project, FIELD), [])
        group = organizer.project_group(self.project.layerTreeRoot(), FIELD, create=False)
        self.assertIsNone(organizer.preview_group(group, create=False) if group is not None else None)

    def test_show_only_toggles_visibility_without_recreating(self):
        previews = StrategyPreviewManager(CRS, FIELD)
        straight_id = previews.show_candidate(self.straight).id()
        previews.show_candidate(self.curve)
        previews.show_only([self.curve.candidate_id])
        self.assertFalse(previews.is_visible(self.straight.candidate_id))
        self.assertTrue(previews.is_visible(self.curve.candidate_id))
        self.assertIsNotNone(self.project.mapLayer(straight_id))
        previews.show_only([self.straight.candidate_id, self.curve.candidate_id])
        self.assertTrue(previews.is_visible(self.straight.candidate_id))
        extent = previews.combined_extent()
        self.assertGreater(extent.width(), 500.0)
        previews.clear_previews()
        self.assertIsNone(previews.combined_extent())

    def test_clear_removes_leftovers_from_previous_session_of_same_field_only(self):
        StrategyPreviewManager(CRS, FIELD).show_candidate(self.straight)
        other = StrategyPreviewManager(CRS, "TL-12")
        other.show_candidate(self.straight)
        StrategyPreviewManager(CRS, FIELD).clear_previews()
        self.assertEqual(preview_layers(self.project, FIELD), [])
        self.assertEqual(len(preview_layers(self.project, "TL-12")), 1)


class MaterializeWorkPathTest(_StrategyTestBase):
    def test_choose_straight_creates_single_work_path_with_metadata(self):
        previews = StrategyPreviewManager(CRS, FIELD)
        previews.show_candidate(self.straight)
        previews.show_candidate(self.curve)
        saved = materialize_as_work_path(self.straight, crs_authid=CRS, field_name=FIELD)
        layers = _work_paths(self.project)
        self.assertEqual(layers, [saved.layer])
        layer = saved.layer
        self.assertEqual(layer.name(), WORK_PATH_NAME)
        self.assertEqual(layer.featureCount(), self.straight.line_count)
        self.assertFalse(saved.persisted)
        self.assertEqual(layer.customProperty("strategy_type"), "STRAIGHT")
        self.assertAlmostEqual(float(layer.customProperty("strategy_angle")), self.straight.angle_deg)
        self.assertTrue(layer.customProperty("strategy_analyzed"))
        self.assertEqual(int(layer.customProperty("analysis_version")), 1)
        self.assertEqual(int(layer.customProperty("strategy_version")), 1)
        feature = next(layer.getFeatures())
        self.assertEqual(feature["strategy_type"], "STRAIGHT")
        self.assertEqual(feature["source_candidate_id"], self.straight.candidate_id)
        self.assertEqual(feature["label"], f"P{feature['line_number']}")
        self.assertFalse(is_temporary_preview(layer))
        self.assertEqual(len(preview_layers(self.project, FIELD)), 2)
        report = validate_field_for_export(FIELD)
        work = next(item for item in report.role_report if item.role == "WORK_PATH")
        self.assertEqual(work.layer_count, 1)
        self.assertEqual(work.feature_count, self.straight.line_count)

    def test_choose_curve_creates_only_curve_lines(self):
        saved = materialize_as_work_path(self.curve, crs_authid=CRS, field_name=FIELD)
        self.assertEqual(_work_paths(self.project), [saved.layer])
        self.assertEqual(saved.layer.featureCount(), self.curve.line_count)
        self.assertEqual(saved.layer.customProperty("strategy_type"), "CURVE")
        values = {feature["strategy_type"] for feature in saved.layer.getFeatures()}
        self.assertEqual(values, {"CURVE"})

    def test_replace_keeps_single_work_path(self):
        materialize_as_work_path(self.curve, crs_authid=CRS, field_name=FIELD)
        saved = materialize_as_work_path(self.straight, crs_authid=CRS, field_name=FIELD, mode=SAVE_REPLACE)
        layers = _work_paths(self.project)
        self.assertEqual(layers, [saved.layer])
        self.assertEqual(saved.layer.featureCount(), self.straight.line_count)
        self.assertEqual(int(saved.layer.customProperty("strategy_version")), 2)

    def test_persisted_new_version_archives_previous_table(self):
        self.save_project()
        first = materialize_as_work_path(self.straight, crs_authid=CRS, field_name=FIELD)
        self.assertTrue(first.persisted)
        self.assertEqual(first.layer.providerType(), "ogr")
        saved = materialize_as_work_path(self.curve, crs_authid=CRS, field_name=FIELD, mode=SAVE_NEW_VERSION)
        manager = FortSmartPersistenceManager(self.project)
        path = manager.get_field_storage_path(FIELD)
        self.assertEqual(saved.archived_table, f"{WORK_PATH_NAME}_v1")
        self.assertEqual(manager.table_feature_count(path, WORK_PATH_NAME), self.curve.line_count)
        self.assertEqual(manager.table_feature_count(path, f"{WORK_PATH_NAME}_v1"), self.straight.line_count)
        self.assertEqual(saved.version, 2)
        layers = _work_paths(self.project)
        self.assertEqual(len(layers), 1)
        self.assertEqual(layers[0].featureCount(), self.curve.line_count)
        self.assertEqual(layers[0].customProperty("strategy_type"), "CURVE")
        loaded_tables = {
            layer.source().split("layername=")[-1] for layer in self.project.mapLayers().values()
            if layer.providerType() == "ogr"
        }
        self.assertNotIn(f"{WORK_PATH_NAME}_v1", loaded_tables)

    def test_new_version_requires_saved_project(self):
        with self.assertRaises(StrategyAnalysisError) as raised:
            materialize_as_work_path(self.straight, crs_authid=CRS, field_name=FIELD, mode=SAVE_NEW_VERSION)
        self.assertEqual(raised.exception.code, STRATEGY_SAVE_FAILED)
        self.assertEqual(_work_paths(self.project), [])

    def test_invalid_candidate_is_rejected(self):
        broken = _analysis().curve_candidate()
        broken.valid = False
        with self.assertRaises(StrategyAnalysisError) as raised:
            materialize_as_work_path(broken, crs_authid=CRS, field_name=FIELD)
        self.assertEqual(raised.exception.code, STRATEGY_SAVE_FAILED)
        self.assertEqual(_work_paths(self.project), [])

    def test_multi_field_save_does_not_touch_other_field(self):
        other = _analysis(field_id="TL-12", offset=5000.0)
        other_straight = other.preview_candidates[0]
        tl12 = materialize_as_work_path(other_straight, crs_authid=CRS, field_name="TL-12")
        self.assertFalse(has_existing_work_path(self.project, FIELD))
        self.assertTrue(has_existing_work_path(self.project, "TL-12"))
        saved = materialize_as_work_path(self.straight, crs_authid=CRS, field_name=FIELD)
        self.assertEqual(_work_paths(self.project, "TL-12"), [tl12.layer])
        self.assertEqual(_work_paths(self.project, FIELD), [saved.layer])
        tl13_extent = saved.layer.extent()
        self.assertLess(tl13_extent.xMaximum(), 4000.0)


class ArchiveRoleTableTest(_StrategyTestBase):
    def test_archive_increments_and_skips_missing_table(self):
        self.save_project()
        manager = FortSmartPersistenceManager(self.project)
        definition = organizer.definition_for_role("WORK_PATH")
        self.assertIsNone(manager.archive_role_table(FIELD, definition))
        materialize_as_work_path(self.straight, crs_authid=CRS, field_name=FIELD)
        self.assertEqual(manager.archive_role_table(FIELD, definition), f"{WORK_PATH_NAME}_v1")
        self.assertEqual(manager.archive_role_table(FIELD, definition), f"{WORK_PATH_NAME}_v2")
        path = manager.get_field_storage_path(FIELD)
        self.assertEqual(manager.archived_versions(path, WORK_PATH_NAME), [1, 2])


class StrategyDialogTest(_StrategyTestBase):
    def _dialog(self, reference_layer=None, polygons=None):
        from plugin.fortsmart_precision.gui.strategy_dialog import StrategyAnalyzerDialog

        dialog = StrategyAnalyzerDialog(
            _precision_project(polygons), field_name=FIELD, crs_authid=CRS, reference_layer=reference_layer
        )
        dialog._show_warning = lambda message: setattr(dialog, "last_warning", message)
        dialog.angle_step.setValue(15.0)
        return dialog

    def _curved_dialog(self):
        """Talhao com borda curva e A-B reta: 'Automatica' usa a borda."""
        return self._dialog(polygons=_field_polygons())

    def test_setup_page_is_simple_with_advanced_hidden(self):
        from plugin.fortsmart_precision.gui import strategy_dialog as module

        dialog = self._dialog()
        self.assertEqual(dialog.windowTitle(), "Comparar projeção de plantio")
        self.assertEqual(dialog.pages.currentIndex(), 0)
        self.assertEqual(dialog.compare_mode(), module.COMPARE_BOTH)
        self.assertEqual(dialog.straight_mode(), module.STRAIGHT_AUTO)
        self.assertEqual(dialog.curve_source(), module.CURVE_SOURCE_AUTO)
        self.assertFalse(dialog.advanced_frame.isVisibleTo(dialog))
        self.assertFalse(dialog.curve_options.isVisibleTo(dialog))
        self.assertEqual(dialog.analyze_btn.text(), "ANALISAR TALHÃO")
        self.assertEqual(dialog.angle_end.value(), 175.0)
        self.assertIn("borda do talhão", dialog.curve_source_label.text())
        self.assertFalse(dialog.curve_source_buttons[module.CURVE_SOURCE_AB].isEnabled())
        dialog.advanced_toggle.setChecked(True)
        self.assertTrue(dialog.advanced_frame.isVisibleTo(dialog))
        dialog.mode_buttons[module.COMPARE_STRAIGHT].setChecked(True)
        self.assertFalse(dialog.curve_section.isEnabled())
        dialog.mode_buttons[module.COMPARE_CURVE].setChecked(True)
        self.assertFalse(dialog.straight_section.isEnabled())
        self.assertFalse(dialog.reference_combo.isEnabled())
        dialog.curve_source_buttons[module.CURVE_SOURCE_LAYER].setChecked(True)
        self.assertTrue(dialog.reference_combo.isEnabled())
        dialog.close()

    def test_cancel_changes_nothing(self):
        before = set(self.project.mapLayers())
        dialog = self._dialog()
        original = dialog._on_progress

        def cancel_on_progress(message):
            original(message)
            dialog.request_cancel()

        dialog._on_progress = cancel_on_progress
        dialog.run_analysis()
        self.assertIsNone(dialog.result)
        self.assertIn("cancelada", dialog.progress_label.text())
        self.assertEqual(set(self.project.mapLayers()), before)
        self.assertEqual(dialog.pages.currentIndex(), 0)
        dialog.close()

    def test_reta_x_curva_shows_cards_summary_and_map_toggle(self):
        dialog = self._curved_dialog()
        dialog.run_analysis()
        self.assertEqual(dialog.pages.currentIndex(), 1)
        straight, curve = dialog.straight_candidate(), dialog.curve_candidate()
        self.assertIsNotNone(straight)
        self.assertIsNotNone(curve)
        self.assertEqual(list(dialog.cards), [straight.candidate_id, curve.candidate_id])
        self.assertEqual(dialog.curve_reference.source, "boundary")
        self.assertEqual(len(dialog.summary_label.text().splitlines()), 3)
        self.assertNotIn("MELHOR", dialog.summary_label.text().upper())
        self.assertEqual([b.text() for b in dialog.map_buttons.values()], ["RETA", "CURVA"])
        self.assertIsNone(dialog.selected_candidate())
        self.assertFalse(dialog.use_btn.isEnabled())
        self.assertIsNone(dialog.use_selected())
        self.assertTrue(dialog.previews.is_visible(straight.candidate_id))
        self.assertTrue(dialog.previews.is_visible(curve.candidate_id))
        dialog.map_buttons[curve.candidate_id].click()
        self.assertFalse(dialog.previews.is_visible(straight.candidate_id))
        self.assertTrue(dialog.previews.is_visible(curve.candidate_id))
        self.assertIs(dialog.selected_candidate(), curve)
        self.assertTrue(dialog.cards[curve.candidate_id].is_selected())
        self.assertIn("CURVA", dialog.use_btn.text())
        dialog.compare_btn.click()
        self.assertTrue(dialog.previews.is_visible(straight.candidate_id))
        self.assertIs(dialog.selected_candidate(), curve)
        self.assertEqual(_work_paths(self.project), [])
        dialog.close()
        self.assertEqual(preview_layers(self.project, FIELD), [])

    def test_use_selected_curve_saves_only_curve_and_clears_previews(self):
        dialog = self._curved_dialog()
        dialog.run_analysis()
        dialog._confirm = lambda candidate: True
        dialog._ask_save_mode = lambda allow_version: self.fail("sem camada existente nao pergunta")
        curve = dialog.curve_candidate()
        dialog.cards[curve.candidate_id].clicked.emit(curve.candidate_id)
        saved = dialog.use_selected()
        self.assertIsNotNone(saved)
        self.assertEqual(_work_paths(self.project), [saved.layer])
        self.assertEqual(saved.layer.featureCount(), curve.line_count)
        self.assertEqual(saved.layer.customProperty("strategy_type"), "CURVE")
        self.assertEqual(preview_layers(self.project, FIELD), [])
        self.assertFalse(dialog.use_btn.isEnabled())
        self.assertIn("gravada", dialog.notice_label.text())
        dialog.close()

    def test_rectangle_curve_from_border_is_discarded_with_notice(self):
        dialog = self._dialog()
        dialog.run_analysis()
        self.assertEqual(dialog.pages.currentIndex(), 1)
        self.assertIn("Curva descartada", dialog.notice_label.text())
        self.assertIsNone(dialog.curve_candidate())
        candidates = dialog.result.preview_candidates
        self.assertTrue(all(item.strategy_type is StrategyType.STRAIGHT for item in candidates))
        labels = [button.text() for button in dialog.map_buttons.values()]
        self.assertEqual(labels, [item.label for item in candidates])
        self.assertFalse(dialog.use_btn.isEnabled())
        dialog.set_map_mode(candidates[0].candidate_id)
        self.assertTrue(dialog.use_btn.isEnabled())
        dialog.close()

    def test_straight_from_ab_tests_only_ab_direction(self):
        from plugin.fortsmart_precision.gui import strategy_dialog as module

        dialog = self._dialog()
        dialog.mode_buttons[module.COMPARE_STRAIGHT].setChecked(True)
        dialog.straight_ab_btn.setChecked(True)
        dialog.run_analysis()
        self.assertEqual(dialog.result.straight_tested, 1)
        candidate = dialog.selected_candidate()
        self.assertAlmostEqual(candidate.angle_deg, 90.0)
        self.assertIsNone(dialog.result.curve_candidate())
        dialog.close()

    def test_curve_reference_layer_is_read_without_modification(self):
        from plugin.fortsmart_precision.gui import strategy_dialog as module

        layer = QgsVectorLayer(f"LineString?crs={CRS}", "curva_mestre", "memory")
        feature = QgsFeature()
        feature.setGeometry(QgsGeometry.fromPolylineXY(
            [QgsPointXY(x, 120.0 + 25.0 * math.sin(math.pi * x / 400.0)) for x in range(0, 401, 20)]
        ))
        layer.dataProvider().addFeatures([feature])
        self.project.addMapLayer(layer)
        before = layer.getFeature(1).geometry().asWkt()
        dialog = self._dialog(reference_layer=layer)
        dialog.curve_source_buttons[module.CURVE_SOURCE_LAYER].setChecked(True)
        self.assertIn("curva_mestre", dialog.curve_source_label.text())
        dialog.run_analysis()
        curve = dialog.curve_candidate()
        self.assertIsNotNone(curve)
        self.assertEqual(curve.reference_id, layer.id())
        self.assertEqual(layer.getFeature(1).geometry().asWkt(), before)
        self.assertEqual(layer.featureCount(), 1)
        dialog.close()

    def test_existing_lines_are_never_replaced_silently(self):
        existing = materialize_as_work_path(self.curve, crs_authid=CRS, field_name=FIELD)
        count = existing.layer.featureCount()
        dialog = self._dialog()
        dialog.run_analysis()
        dialog.set_map_mode(dialog.straight_candidate().candidate_id)
        dialog._confirm = lambda candidate: True
        asked = []
        dialog._ask_save_mode = lambda allow_version: asked.append(allow_version)
        self.assertIsNone(dialog.use_selected())
        self.assertEqual(asked, [False])
        self.assertEqual(_work_paths(self.project), [existing.layer])
        self.assertEqual(existing.layer.featureCount(), count)
        dialog._ask_save_mode = lambda allow_version: SAVE_REPLACE
        saved = dialog.use_selected()
        self.assertEqual(_work_paths(self.project), [saved.layer])
        dialog.close()

    def test_declined_confirmation_changes_nothing(self):
        dialog = self._dialog()
        dialog.run_analysis()
        dialog.set_map_mode(dialog.straight_candidate().candidate_id)
        dialog._confirm = lambda candidate: False
        self.assertIsNone(dialog.use_selected())
        self.assertEqual(_work_paths(self.project), [])
        dialog.close()

    def test_new_analysis_returns_to_setup_and_removes_previews(self):
        dialog = self._curved_dialog()
        dialog.run_analysis()
        self.assertGreater(len(preview_layers(self.project, FIELD)), 0)
        dialog.new_analysis()
        self.assertEqual(dialog.pages.currentIndex(), 0)
        self.assertEqual(preview_layers(self.project, FIELD), [])
        self.assertEqual(dialog.cards, {})
        dialog.run_analysis()
        self.assertEqual(len(dialog.cards), 2)
        dialog.close()


class FeatureFlagTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()

    def test_workspace_button_follows_flag(self):
        from plugin.fortsmart_precision.gui import fortsmart_workspace_dialog as workspace

        class _Canvas:
            def mapSettings(self):
                class _Settings:
                    @staticmethod
                    def destinationCrs():
                        return QgsCoordinateReferenceSystem(CRS)

                return _Settings()

        class _Iface:
            @staticmethod
            def mainWindow():
                return None

            @staticmethod
            def mapCanvas():
                return _Canvas()

            @staticmethod
            def activeLayer():
                return None

        original = workspace.ENABLE_STRATEGY_ANALYZER
        try:
            for enabled in (False, True):
                workspace.ENABLE_STRATEGY_ANALYZER = enabled
                dialog = workspace.FortSmartWorkspaceDialog(_Iface())
                try:
                    self.assertEqual(dialog.strategy_btn is not None, enabled)
                    if enabled:
                        self.assertEqual(dialog.strategy_btn.text(), "COMPARAR PROJEÇÃO")
                        dialog._set_generation_busy(True)
                        self.assertFalse(dialog.strategy_btn.isEnabled())
                        dialog._set_generation_busy(False)
                    self.assertEqual(dialog.gen_plant_btn.text(), "2. Gerar plantio")
                finally:
                    dialog.close()
        finally:
            workspace.ENABLE_STRATEGY_ANALYZER = original


if __name__ == "__main__":
    unittest.main()
