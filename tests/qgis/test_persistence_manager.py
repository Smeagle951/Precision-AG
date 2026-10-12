# -*- coding: utf-8 -*-
"""Persistencia canonica em GeoPackage: um GPKG por talhao, uma tabela por role."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsApplication,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsProject,
    QgsProviderRegistry,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant

from plugin.fortsmart_precision.core.layer_roles import (
    definition_for_role,
    mark_temporary_preview,
    set_layer_role_properties,
)
from plugin.fortsmart_precision.core.persistence_manager import (
    FIELD_ID_MISSING,
    PROJECT_NOT_SAVED,
    STATUS_KEPT_PREVIOUS,
    STATUS_PERSISTED,
    FortSmartPersistenceManager,
    PersistenceError,
)
from plugin.fortsmart_precision.gui import layer_tree_organizer as organizer

_APP = None
CRS = "EPSG:31981"


def _setup_qgis():
    global _APP
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if QgsApplication.instance() is None:
        _APP = QgsApplication([], True)
        _APP.initQgis()


def _work_layer(count=3, field_name="talhao_12", role="WORK_PATH", name=None):
    definition = definition_for_role(role)
    layer = QgsVectorLayer(f"LineString?crs={CRS}", name or definition.display_name, "memory")
    layer.dataProvider().addAttributes([QgsField("line_number", QVariant.Int)])
    layer.updateFields()
    features = []
    for number in range(1, count + 1):
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt(f"LINESTRING(0 {number * 10}, 1000 {number * 10})"))
        feature["line_number"] = number
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    set_layer_role_properties(layer, definition, field_name=field_name)
    return layer


def _source_path(layer):
    return QgsProviderRegistry.instance().decodeUri("ogr", layer.source()).get("path", "")


def _role_layers(project, role, field_id=None):
    return [
        layer for layer in project.mapLayers().values()
        if layer.customProperty("fortsmart_role", "") == role
        and (field_id is None or layer.customProperty("fortsmart_field_id", "") == field_id)
    ]


class PersistenceManagerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.project = QgsProject.instance()
        self.project.clear()
        self.project.setFileName(str(self.tmp / "fazenda.qgz"))
        self.manager = FortSmartPersistenceManager(self.project)

    def tearDown(self):
        self.project.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _persist(self, layer, field_name="talhao_12", **kwargs):
        self.project.addMapLayer(layer)
        definition = definition_for_role(layer.customProperty("fortsmart_role"))
        result = self.manager.persist_layer(layer, definition, field_name, **kwargs)
        organizer.publish_persisted(
            self.project, layer, result.layer, reused=result.reused_layer, field_name=field_name, definition=definition
        )
        return result

    def test_storage_path_is_one_gpkg_per_field_next_to_project(self):
        self.assertEqual(
            self.manager.get_field_storage_path("Boundary — talhao_12 (EPSG:31981)"),
            self.tmp / "fortsmart_data" / "talhao_12" / "fortsmart_talhao_12.gpkg",
        )

    def test_unsaved_project_is_refused_without_fallback(self):
        self.project.setFileName("")
        with self.assertRaises(PersistenceError) as raised:
            self.manager.persist_layer(_work_layer(), definition_for_role("WORK_PATH"), "talhao_12")
        self.assertEqual(raised.exception.code, PROJECT_NOT_SAVED)
        self.assertIn("Salve o projeto QGIS", str(raised.exception))
        self.assertFalse((self.tmp / "fortsmart_data").exists())

    def test_missing_field_id_is_reported(self):
        with self.assertRaises(PersistenceError) as raised:
            self.manager.persist_layer(_work_layer(), definition_for_role("WORK_PATH"), "")
        self.assertEqual(raised.exception.code, FIELD_ID_MISSING)

    def test_persist_and_reopen_project_keeps_features(self):
        result = self._persist(_work_layer(3))
        self.assertEqual(result.status, STATUS_PERSISTED)
        layer = _role_layers(self.project, "WORK_PATH")[0]
        self.assertEqual(layer.providerType(), "ogr")
        self.assertEqual(layer.customProperty("fortsmart_storage"), "geopackage")
        self.assertTrue(layer.customProperty("fortsmart_persisted"))
        project_file = self.project.fileName()
        self.assertTrue(self.project.write())
        self.project.clear()
        self.assertEqual(self.project.mapLayers(), {})
        self.assertTrue(self.project.read(project_file))

        reopened = _role_layers(self.project, "WORK_PATH", "talhao_12")
        self.assertEqual(len(reopened), 1)
        self.assertTrue(reopened[0].isValid())
        self.assertEqual(reopened[0].featureCount(), 3)
        self.assertEqual(reopened[0].name(), "12_Passadas_Plantio")
        self.assertEqual(reopened[0].crs().authid(), CRS)
        self.assertEqual(
            Path(_source_path(reopened[0])).resolve(),
            (self.tmp / "fortsmart_data" / "talhao_12" / "fortsmart_talhao_12.gpkg").resolve(),
        )
        node = self.project.layerTreeRoot().findLayer(reopened[0].id())
        self.assertEqual(node.parent().name(), "10_PLANEJAMENTO")
        self.assertEqual(node.parent().parent().name(), "FORTSMART - talhao_12")

    def test_fields_are_isolated_in_their_own_geopackage(self):
        self._persist(_work_layer(3, "talhao_12"), "talhao_12")
        self._persist(_work_layer(5, "talhao_13"), "talhao_13")
        first = self.manager.get_field_storage_path("talhao_12")
        second = self.manager.get_field_storage_path("talhao_13")
        self.assertNotEqual(first, second)
        self.assertEqual(self.manager.table_feature_count(first, "12_Passadas_Plantio"), 3)
        self.assertEqual(self.manager.table_feature_count(second, "12_Passadas_Plantio"), 5)
        self.assertEqual(len(_role_layers(self.project, "WORK_PATH")), 2)

    def test_regeneration_replaces_the_same_table_and_layer(self):
        self._persist(_work_layer(3))
        persisted = _role_layers(self.project, "WORK_PATH")[0]
        persisted_id = persisted.id()
        result = self._persist(_work_layer(5))
        self.assertTrue(result.reused_layer)
        path = self.manager.get_field_storage_path("talhao_12")
        self.assertEqual(self.manager.table_names(path), ["12_Passadas_Plantio"])
        layers = _role_layers(self.project, "WORK_PATH")
        self.assertEqual([layer.id() for layer in layers], [persisted_id])
        self.assertEqual(layers[0].featureCount(), 5)
        self.assertTrue(all(not layer.name().endswith("_2") for layer in self.project.mapLayers().values()))
        self.assertEqual(len(self.project.layerTreeRoot().findLayers()), 1)

    def test_empty_result_keeps_persisted_table_unless_confirmed(self):
        self._persist(_work_layer(3))
        result = self._persist(_work_layer(0))
        self.assertEqual(result.status, STATUS_KEPT_PREVIOUS)
        self.assertEqual(result.message, "Resultado vazio. A camada persistida anterior foi mantida.")
        self.assertEqual(_role_layers(self.project, "WORK_PATH")[0].featureCount(), 3)
        confirmed = self._persist(_work_layer(0), allow_empty=True)
        self.assertEqual(confirmed.status, STATUS_PERSISTED)
        self.assertEqual(_role_layers(self.project, "WORK_PATH")[0].featureCount(), 0)

    def test_minimum_schema_fields_and_existing_ids_are_kept(self):
        layer = _work_layer(2, role="FINAL_WORK_PATH")
        layer.dataProvider().addAttributes([QgsField("line_id", QVariant.String)])
        layer.updateFields()
        first = next(layer.getFeatures())
        layer.dataProvider().changeAttributeValues({first.id(): {layer.fields().indexFromName("line_id"): "X7"}})
        self._persist(layer)
        persisted = _role_layers(self.project, "FINAL_WORK_PATH")[0]
        names = persisted.fields().names()
        for field_name in ("fortsmart_role", "field_id", "source_id", "line_id", "pass_number",
                           "parent_line_id", "segment_index"):
            self.assertIn(field_name, names)
        rows = sorted(
            (feature["line_number"], feature["line_id"], feature["source_id"], feature["field_id"])
            for feature in persisted.getFeatures()
        )
        self.assertEqual(rows[0], (1, "X7", "X7:1", "talhao_12"))
        self.assertEqual(rows[1], (2, "L0002", "L0002:1", "talhao_12"))
        self.assertEqual({feature["fortsmart_role"] for feature in persisted.getFeatures()}, {"FINAL_WORK_PATH"})

    def test_user_fields_survive_regeneration(self):
        self._persist(_work_layer(2))
        persisted = _role_layers(self.project, "WORK_PATH")[0]
        persisted.dataProvider().addAttributes([QgsField("observacao", QVariant.String)])
        persisted.updateFields()
        self._persist(_work_layer(4))
        self.assertIn("observacao", persisted.fields().names())
        self.assertEqual(persisted.featureCount(), 4)

    def test_spatial_index_and_working_crs(self):
        from osgeo import ogr

        self._persist(_work_layer(2))
        path = self.manager.get_field_storage_path("talhao_12")
        source = ogr.Open(str(path))
        result = source.ExecuteSQL("SELECT HasSpatialIndex('12_Passadas_Plantio', 'geom')")
        self.assertEqual(result.GetNextFeature().GetField(0), 1)
        source.ReleaseResultSet(result)
        self.assertEqual(source.GetLayerByName("12_Passadas_Plantio").GetSpatialRef().GetAuthorityCode(None), "31981")
        source = None

    def test_renamed_layer_keeps_role_and_canonical_table(self):
        self._persist(_work_layer(2))
        persisted = _role_layers(self.project, "WORK_PATH")[0]
        persisted.setName("Minhas passadas")
        self._persist(_work_layer(3))
        layers = _role_layers(self.project, "WORK_PATH")
        self.assertEqual([layer.name() for layer in layers], ["Minhas passadas"])
        self.assertEqual(layers[0].featureCount(), 3)
        self.assertEqual(
            self.manager.table_names(self.manager.get_field_storage_path("talhao_12")), ["12_Passadas_Plantio"]
        )

    def test_style_is_copied_on_first_persist_and_user_style_survives(self):
        memory = _work_layer(2)
        memory.renderer().symbol().setColor(QColor(10, 200, 30))
        memory.setOpacity(0.4)
        self._persist(memory)
        persisted = _role_layers(self.project, "WORK_PATH")[0]
        self.assertEqual(persisted.renderer().symbol().color().name(), "#0ac81e")
        self.assertAlmostEqual(persisted.opacity(), 0.4)
        persisted.renderer().symbol().setColor(QColor(255, 0, 0))
        self._persist(_work_layer(3))
        self.assertEqual(persisted.renderer().symbol().color().name(), "#ff0000")

    def test_remove_role_layer_drops_table_and_project_layer(self):
        self._persist(_work_layer(2))
        self._persist(_work_layer(1, role="FINAL_WORK_PATH"))
        removed = self.manager.remove_role_layer("talhao_12", definition_for_role("WORK_PATH"))
        self.assertTrue(removed)
        path = self.manager.get_field_storage_path("talhao_12")
        self.assertEqual(self.manager.table_names(path), ["31_Linhas_Finais"])
        self.assertEqual(_role_layers(self.project, "WORK_PATH"), [])
        self.assertEqual(len(_role_layers(self.project, "FINAL_WORK_PATH")), 1)
        layer, reused = self.manager.load_persisted_layer("talhao_12", definition_for_role("WORK_PATH"))
        self.assertIsNone(layer)
        self.assertFalse(reused)

    def test_previews_never_create_tables(self):
        for _index in range(10):
            preview = _work_layer(2)
            mark_temporary_preview(preview)
            self.project.addMapLayer(preview)
        report = organizer.persist_generated_memory_layers(self.project, self.manager)
        self.assertEqual(report["entries"], [])
        self.assertEqual(report["ignored_previews"], 10)
        self.assertFalse((self.tmp / "fortsmart_data" / "talhao_12").exists())

    def test_migration_persists_memory_layers_by_field_and_swaps_nodes(self):
        root = self.project.layerTreeRoot()
        for field_name, count in (("talhao_12", 3), ("talhao_13", 2)):
            layer = _work_layer(count, field_name)
            self.project.addMapLayer(layer, False)
            organizer.insert_layer_ordered(
                organizer.section_group(organizer.project_group(root, field_name), "10_PLANEJAMENTO"), layer
            )
        user = QgsVectorLayer(f"LineString?crs={CRS}", "minha camada", "memory")
        self.project.addMapLayer(user)
        preview = _work_layer(1)
        self.project.addMapLayer(preview, False)
        organizer.preview_group(organizer.project_group(root, "talhao_12")).addLayer(preview)

        report = organizer.persist_generated_memory_layers(self.project, self.manager)

        self.assertIn("FORTSMART STORAGE REPORT", report["text"])
        self.assertIn("Talhão: talhao_12", report["text"])
        self.assertIn("12_Passadas_Plantio: 3 feições — MEMORY → GPKG — OK", report["text"])
        self.assertIn("Preview: 1 ignorado(s)", report["text"])
        persisted = _role_layers(self.project, "WORK_PATH")
        by_field = {layer.customProperty("fortsmart_field_id"): layer for layer in persisted if layer.providerType() == "ogr"}
        self.assertEqual(set(by_field), {"talhao_12", "talhao_13"})
        self.assertEqual(by_field["talhao_12"].featureCount(), 3)
        self.assertIsNotNone(self.project.mapLayer(user.id()))
        self.assertIsNotNone(self.project.mapLayer(preview.id()))
        memory_nodes = [
            node for node in root.findLayers()
            if node.layer().providerType() == "memory" and node.layer().customProperty("fortsmart_role") == "WORK_PATH"
            and node.parent().name() != "SIM_PREVIEW"
        ]
        self.assertEqual(memory_nodes, [])
        second = organizer.persist_generated_memory_layers(self.project, self.manager)
        self.assertEqual(second["entries"], [])


if __name__ == "__main__":
    unittest.main()
