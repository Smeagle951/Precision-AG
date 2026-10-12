# -*- coding: utf-8 -*-
"""Integracao QGIS: publica o resultado do motor na arvore canonica."""

from __future__ import annotations

import os
import unittest

from qgis.core import QgsApplication, QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry, QgsProject, QgsVectorLayer
from qgis.PyQt.QtWidgets import QDialog

from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
from plugin.fortsmart_precision.domain.headland_layout import (
    HEADLAND_CORNER_AUTO,
    HEADLAND_CORNER_FOLLOW_BOUNDARY,
    HEADLAND_CORNER_STRAIGHT_THROUGH,
    HeadlandLayout,
)
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, PlanterMachine
from plugin.fortsmart_precision.domain.precision_project import ABLine, FieldGeometry, PrecisionOperation, PrecisionProject
from plugin.fortsmart_precision.gui.fortsmart_workspace_dialog import FortSmartWorkspaceDialog
from plugin.fortsmart_precision.gui.machine_work_geometry_widget import MachineWorkGeometryBox
from plugin.fortsmart_precision.gui.machine_config_widgets import (
    PlanterConfigWidget,
    SprayerConfigWidget,
)


_APP = None


def _setup_qgis():
    global _APP
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if QgsApplication.instance() is None:
        _APP = QgsApplication([], True)
        _APP.initQgis()


class _MapSettings:
    @staticmethod
    def destinationCrs():
        return QgsCoordinateReferenceSystem("EPSG:31981")


class _Canvas:
    def setRenderFlag(self, *_args):
        pass

    def refresh(self):
        pass

    def setExtent(self, *_args):
        pass

    def zoomOut(self):
        pass

    @staticmethod
    def mapSettings():
        return _MapSettings()


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


class _Combo:
    def __init__(self, layer):
        self.layer = layer

    def currentLayer(self):
        return self.layer

    def setLayer(self, layer):
        self.layer = layer


class _Label:
    def __init__(self):
        self.text = ""

    def setText(self, text):
        self.text = text


def _planting_result():
    field = [(
        [(0.0, 0.0), (1000.0, 0.0), (1000.0, 300.0), (0.0, 300.0), (0.0, 0.0)],
        [],
    )]
    planter = PlanterMachine(
        machine_id="p10",
        name="Plantadeira 10 m",
        row_count=20,
        row_spacing_m=0.5,
        track=MachineTrack(track_width_m=2.0, tire_width_m=0.4),
    )
    operation = PrecisionOperation(
        operation_id="planting",
        machine=planter,
        headland=HeadlandLayout(pass_count=2, width_m=10.0, effective_spacing_m=10.0, mode="follow_boundary"),
        extension_m=20.0,
    )
    project = PrecisionProject(
        field=FieldGeometry(field_boundary=field, operational_boundary=field, crs_authid="EPSG:31981"),
        ab_line=ABLine(start=(0.0, 150.0), end=(1000.0, 150.0)),
        planting=operation,
    )
    return run_precision_lines(project)


def _field_layer(name):
    layer = QgsVectorLayer("Polygon?crs=EPSG:31981", name, "memory")
    feature = QgsFeature()
    feature.setGeometry(QgsGeometry.fromWkt("POLYGON((0 0,1000 0,1000 300,0 300,0 0))"))
    layer.dataProvider().addFeature(feature)
    QgsProject.instance().addMapLayer(layer)
    return layer


def _generator(field_layer):
    dialog = FortSmartWorkspaceDialog.__new__(FortSmartWorkspaceDialog)
    QDialog.__init__(dialog)
    dialog.iface = _Iface()
    dialog.border_entry_preview = None
    dialog.work_crs_authid = "EPSG:31981"
    dialog.field_combo = _Combo(field_layer)
    dialog.ab_layer_combo = _Combo(None)
    dialog.obstacle_combo = _Combo(None)
    return dialog


def _role_layers(role, field_id=None):
    return [
        layer for layer in QgsProject.instance().mapLayers().values()
        if layer.customProperty("fortsmart_role", "") == role
        and (field_id is None or layer.customProperty("fortsmart_field_id", "") == field_id)
    ]


class WorkspaceRegenerationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()
        cls.result = _planting_result()

    def setUp(self):
        QgsProject.instance().clear()

    def tearDown(self):
        QgsProject.instance().clear()

    def test_regenerating_keeps_one_layer_per_role(self):
        field = _field_layer("Boundary — talhao_12 (EPSG:31981)")
        dialog = _generator(field)
        dialog._render_preview(self.result)
        first_count = len(QgsProject.instance().mapLayers())
        dialog._render_preview(self.result)
        self.assertEqual(len(QgsProject.instance().mapLayers()), first_count)
        work = _role_layers("WORK_PATH")
        self.assertEqual([layer.name() for layer in work], ["12_Passadas_Plantio"])
        self.assertEqual(work[0].customProperty("fortsmart_field_id"), "talhao_12")
        self.assertEqual(work[0].customProperty("fortsmart_internal_key"), "06_Passadas_Plantio")
        self.assertEqual(work[0].customProperty("fortsmart_schema_version"), 1)
        root = QgsProject.instance().layerTreeRoot()
        self.assertEqual(len([g for g in root.children() if g.name() == "FORTSMART - talhao_12"]), 1)
        group = root.findGroup("FORTSMART - talhao_12")
        self.assertEqual(
            [child.name() for child in group.children()],
            ["00_REFERENCIAS", "10_PLANEJAMENTO", "20_OBSTACULOS", "30_OPERACAO", "90_AUXILIARES"],
        )
        references = [child.name() for child in group.findGroup("00_REFERENCIAS").children()]
        self.assertEqual(references[:4], ["01_Limite_Externo", "02_Limite_Interno", "03_Bordadura", "04_Linha_AB"])
        self.assertEqual(root.findLayer(field.id()).parent().name(), "90_AUXILIARES")
        self.assertTrue(all(not layer.name().endswith("_2") for layer in QgsProject.instance().mapLayers().values()))

    def test_user_layer_with_canonical_name_is_not_overwritten(self):
        user = QgsVectorLayer("LineString?crs=EPSG:31981", "12_Passadas_Plantio", "memory")
        feature = QgsFeature()
        feature.setGeometry(QgsGeometry.fromWkt("LINESTRING(0 0, 5 5)"))
        user.dataProvider().addFeature(feature)
        QgsProject.instance().addMapLayer(user)
        dialog = _generator(_field_layer("talhao_12"))
        dialog._render_preview(self.result)
        dialog._render_preview(self.result)
        self.assertIsNotNone(QgsProject.instance().mapLayer(user.id()))
        self.assertEqual(user.featureCount(), 1)
        self.assertEqual(user.customProperty("fortsmart_role", ""), "")
        self.assertEqual([layer.name() for layer in _role_layers("WORK_PATH")], ["12_Passadas_Plantio_2"])

    def test_other_field_layers_survive_regeneration(self):
        _generator(_field_layer("talhao_13"))._render_preview(self.result)
        other_ids = {layer.id() for layer in _role_layers("WORK_PATH", "talhao_13")}
        dialog = _generator(_field_layer("talhao_12"))
        dialog._render_preview(self.result)
        dialog._render_preview(self.result)
        self.assertEqual({layer.id() for layer in _role_layers("WORK_PATH", "talhao_13")}, other_ids)
        self.assertEqual(len(_role_layers("WORK_PATH", "talhao_12")), 1)
        self.assertEqual(
            [layer.name() for layer in _role_layers("WORK_PATH")], ["12_Passadas_Plantio", "12_Passadas_Plantio"]
        )

    def test_saved_results_are_kept_and_empty_preview_does_not_replace_them(self):
        from plugin.fortsmart_precision.core.layer_roles import (
            HEADLAND_TURN_ROLE,
            set_layer_role_properties,
            simulation_role_definition,
        )

        field = _field_layer("talhao_12")
        dialog = _generator(field)
        dialog._render_preview(self.result)
        self.assertEqual(_role_layers("FINAL_WORK_PATH")[0].featureCount(), 0)
        group = QgsProject.instance().layerTreeRoot().findGroup("FORTSMART - talhao_12")
        saved = {}
        for definition in (simulation_role_definition("SIM_WORK_LINES"), HEADLAND_TURN_ROLE):
            layer = QgsVectorLayer("LineString?crs=EPSG:31981", definition.display_name, "memory")
            feature = QgsFeature()
            feature.setGeometry(QgsGeometry.fromWkt("LINESTRING(0 0, 5 5)"))
            layer.dataProvider().addFeature(feature)
            set_layer_role_properties(layer, definition, field_name="talhao_12")
            QgsProject.instance().addMapLayer(layer, False)
            group.findGroup(definition.section).addLayer(layer)
            saved[definition.role] = layer.id()
        for layer in _role_layers("FINAL_WORK_PATH"):
            if layer.featureCount() == 0:
                QgsProject.instance().removeMapLayer(layer.id())

        dialog._render_preview(self.result)

        self.assertEqual([layer.id() for layer in _role_layers("FINAL_WORK_PATH")], [saved["FINAL_WORK_PATH"]])
        self.assertEqual([layer.id() for layer in _role_layers("HEADLAND_TURN")], [saved["HEADLAND_TURN"]])
        self.assertIsNotNone(QgsProject.instance().mapLayer(field.id()))


class WorkspacePersistenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()
        cls.result = _planting_result()

    def setUp(self):
        import tempfile
        from pathlib import Path

        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        QgsProject.instance().clear()
        QgsProject.instance().setFileName(str(Path(self.tmp.name) / "fazenda.qgz"))
        self.storage = Path(self.tmp.name) / "fortsmart_data" / "talhao_12" / "fortsmart_talhao_12.gpkg"

    def tearDown(self):
        QgsProject.instance().clear()
        self.tmp.cleanup()

    def test_generation_persists_roles_and_survives_reopen(self):
        from plugin.fortsmart_precision.core.persistence_manager import FortSmartPersistenceManager

        dialog = _generator(_field_layer("Boundary — talhao_12 (EPSG:31981)"))
        dialog._render_preview(self.result)
        work = _role_layers("WORK_PATH")
        self.assertEqual(len(work), 1)
        self.assertEqual(work[0].providerType(), "ogr")
        expected = work[0].featureCount()
        self.assertGreater(expected, 0)
        tables = FortSmartPersistenceManager.table_names(self.storage)
        for name in ("01_Limite_Externo", "12_Passadas_Plantio", "13_Linha_Trator", "15_Passadas_Bordadura"):
            self.assertIn(name, tables)
        self.assertIn(str(self.storage), dialog._storage_note)
        memory_generated = [
            layer for layer in QgsProject.instance().mapLayers().values()
            if layer.customProperty("fortsmart_generated", False) and layer.providerType() == "memory"
        ]
        self.assertEqual(memory_generated, [])

        project_file = QgsProject.instance().fileName()
        self.assertTrue(QgsProject.instance().write())
        QgsProject.instance().clear()
        self.assertTrue(QgsProject.instance().read(project_file))
        reopened = _role_layers("WORK_PATH", "talhao_12")
        self.assertEqual(len(reopened), 1)
        self.assertEqual(reopened[0].featureCount(), expected)
        self.assertEqual(reopened[0].name(), "12_Passadas_Plantio")
        self.assertIsNotNone(find_role(QgsProject.instance().mapLayers().values(), "TRACTOR_PATH"))
        node = QgsProject.instance().layerTreeRoot().findLayer(reopened[0].id())
        self.assertEqual(node.parent().name(), "10_PLANEJAMENTO")

    def test_regeneration_reuses_persisted_layer_and_user_style(self):
        from qgis.PyQt.QtGui import QColor

        dialog = _generator(_field_layer("talhao_12"))
        dialog._render_preview(self.result)
        (work,) = _role_layers("WORK_PATH")
        work_id = work.id()
        work.renderer().symbol().setColor(QColor(255, 0, 0))
        work.setName("Minhas passadas")
        dialog._render_preview(self.result)
        self.assertEqual([layer.id() for layer in _role_layers("WORK_PATH")], [work_id])
        self.assertEqual(work.name(), "Minhas passadas")
        self.assertEqual(work.renderer().symbol().color().name(), "#ff0000")
        self.assertTrue(all(not layer.name().endswith("_2") for layer in QgsProject.instance().mapLayers().values()))

    def test_unsaved_project_keeps_memory_and_warns(self):
        QgsProject.instance().setFileName("")
        dialog = _generator(_field_layer("talhao_12"))
        dialog._render_preview(self.result)
        self.assertEqual(_role_layers("WORK_PATH")[0].providerType(), "memory")
        self.assertIn("Salve o projeto QGIS antes de persistir os resultados FortSmart.", dialog._storage_note)
        self.assertFalse(self.storage.exists())


def find_role(layers, role):
    from plugin.fortsmart_precision.core.layer_roles import find_layer_by_role

    return find_layer_by_role(layers, role)


class WorkspaceCanonicalPreviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()

    def setUp(self):
        QgsProject.instance().clear()

    def tearDown(self):
        QgsProject.instance().clear()

    def test_machine_widgets_expose_all_headland_corner_modes(self):
        for widget in (PlanterConfigWidget(), SprayerConfigWidget()):
            self.assertEqual(widget.headland_corner_mode(), HEADLAND_CORNER_AUTO)
            for mode in (
                HEADLAND_CORNER_FOLLOW_BOUNDARY,
                HEADLAND_CORNER_STRAIGHT_THROUGH,
            ):
                widget.headland_corner_combo.setCurrentIndex(
                    widget.headland_corner_combo.findData(mode)
                )
                self.assertEqual(widget.headland_corner_mode(), mode)

    def test_planting_preview_has_sections_roles_and_no_tuple_error(self):
        result = _planting_result()
        field_layer = _field_layer("Boundary — talhao_12 (EPSG:31981)")
        dialog = _generator(field_layer)
        dialog._render_preview_layers(result)

        root = QgsProject.instance().layerTreeRoot()
        parent = root.findGroup("FORTSMART - talhao_12")
        self.assertIsNotNone(parent)
        self.assertIsNotNone(parent.findGroup("00_REFERENCIAS"))
        self.assertIsNotNone(parent.findGroup("10_PLANEJAMENTO"))
        roles = {layer.customProperty("fortsmart_role", "") for layer in QgsProject.instance().mapLayers().values()}
        self.assertIn("WORK_PATH", roles)
        self.assertIn("TRACTOR_PATH", roles)
        tractor_layer = next(
            layer
            for layer in QgsProject.instance().mapLayers().values()
            if layer.customProperty("fortsmart_role", "") == "TRACTOR_PATH"
        )
        self.assertEqual(tractor_layer.name(), "13_Linha_Trator")
        self.assertEqual(tractor_layer.featureCount(), len(result.tractor_axes))
        self.assertTrue(
            all(len(feature.geometry().asPolyline()) == 2 for feature in tractor_layer.getFeatures())
        )
        headland_layer = next(
            layer
            for layer in QgsProject.instance().mapLayers().values()
            if layer.customProperty("fortsmart_role", "") == "FIELD_HEADLAND_PATH"
        )
        self.assertEqual(headland_layer.name(), "15_Passadas_Bordadura")
        self.assertEqual(headland_layer.featureCount(), 2)
        self.assertEqual(
            {feature["pass_no"] for feature in headland_layer.getFeatures()},
            {1, 2},
        )
        self.assertTrue(
            all(
                feature.geometry().asPolyline()[0] == feature.geometry().asPolyline()[-1]
                for feature in headland_layer.getFeatures()
            )
        )

    def test_planning_copies_complete_cut_geometry_to_engine_dialog(self):
        dialog = FortSmartWorkspaceDialog.__new__(FortSmartWorkspaceDialog)
        dialog.fast_cut_geometry_box = MachineWorkGeometryBox()
        source = dialog.fast_cut_geometry_box
        source.strategy_combo.setCurrentIndex(source.strategy_combo.findData("CUT_FOR_BORDER"))
        source.reference_combo.setCurrentIndex(source.reference_combo.findData("HITCH_PIN"))
        source.border_combo.setCurrentIndex(source.border_combo.findData("CUSTOM"))
        source.offset_spin.setValue(-7.5)
        source.border_spin.setValue(12.0)
        source.lateral_margin_spin.setValue(0.75)

        destination = MachineWorkGeometryBox()
        dialog._copy_fast_cut_geometry(destination)

        self.assertEqual(destination.strategy_combo.currentData(), "CUT_FOR_BORDER")
        self.assertEqual(destination.reference_combo.currentData(), "HITCH_PIN")
        self.assertEqual(destination.border_combo.currentData(), "CUSTOM")
        self.assertAlmostEqual(destination.working_offset_m(), -7.5)
        self.assertAlmostEqual(destination.border_spin.value(), 12.0)
        self.assertAlmostEqual(destination.lateral_margin_spin.value(), 0.75)

    def test_planning_exposes_cut_geometry_and_uses_planter_width(self):
        dialog = FortSmartWorkspaceDialog(_Iface())
        try:
            self.assertEqual(dialog.fast_cut_width_spin.value(), 0.0)
            dialog.planter_widget.row_count_spin.setValue(18)
            dialog.planter_widget.row_spacing_spin.setValue(0.50)
            dialog.planter_widget.informed_width_spin.setValue(9.0)
            self.assertIsInstance(dialog.fast_cut_geometry_box, MachineWorkGeometryBox)
            self.assertAlmostEqual(
                dialog.fast_cut_width_spin.value(),
                dialog.planter_widget.effective_width_m(),
            )
        finally:
            dialog.reject()

    def test_planning_dialog_opens_and_closes_with_qgis_initialized(self):
        dialog = FortSmartWorkspaceDialog(_Iface())
        try:
            dialog.show()
            QgsApplication.processEvents()
            self.assertTrue(dialog.isVisible())
            self.assertIsNone(dialog.border_entry_preview)
        finally:
            dialog.reject()
            QgsApplication.processEvents()
        self.assertFalse(dialog.isVisible())

    def test_saved_cut_becomes_current_planting_layer_in_planning(self):
        final = QgsVectorLayer("LineString?crs=EPSG:31981", "31_Linhas_Finais", "memory")
        final.setCustomProperty("fortsmart_role", "FINAL_WORK_PATH")
        QgsProject.instance().addMapLayer(final)

        dialog = FortSmartWorkspaceDialog.__new__(FortSmartWorkspaceDialog)
        dialog.field_combo = _Combo(None)
        dialog.plant_line_combo = _Combo(None)
        dialog.summary = _Label()
        dialog._refresh_operation_layer_combos = lambda: None
        dialog._on_fast_cut_saved(["31_Linhas_Finais", "35_Linhas_Bordadura"])

        self.assertIs(dialog.plant_line_combo.currentLayer(), final)
        self.assertIn("35_Linhas_Bordadura", dialog.summary.text)


if __name__ == "__main__":
    unittest.main()
