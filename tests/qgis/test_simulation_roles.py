# -*- coding: utf-8 -*-
"""Simulador visual: saidas 41/42/43 por role, na secao 40_SIMULACAO, persistidas sob demanda."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from qgis.core import (
    QgsApplication,
    QgsFeature,
    QgsGeometry,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProcessingOutputLayerDefinition,
    QgsProject,
    QgsVectorLayer,
)

from plugin.fortsmart_precision.algorithms.simulate_real_operation import SimulateRealOperationAlgorithm
from plugin.fortsmart_precision.core.layer_roles import definition_for_role, set_layer_role_properties
from plugin.fortsmart_precision.core.persistence_manager import FortSmartPersistenceManager
from plugin.fortsmart_precision.gui import layer_tree_organizer as organizer

_APP = None
CRS = "EPSG:31981"


def _setup_qgis():
    global _APP
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if QgsApplication.instance() is None:
        _APP = QgsApplication([], True)
        _APP.initQgis()


def _layer(uri, name, wkts):
    layer = QgsVectorLayer(uri, name, "memory")
    features = []
    for wkt in wkts:
        feature = QgsFeature()
        feature.setGeometry(QgsGeometry.fromWkt(wkt))
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    return layer


class SimulationRolesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.project = QgsProject.instance()
        self.project.clear()
        self.project.setFileName(str(self.tmp / "fazenda.qgz"))
        root = self.project.layerTreeRoot()
        self.passes = _layer(f"LineString?crs={CRS}", "12_Passadas_Plantio", [
            "LINESTRING(0 5, 100 5)", "LINESTRING(0 13, 100 13)", "LINESTRING(0 21, 100 21)",
        ])
        set_layer_role_properties(self.passes, definition_for_role("WORK_PATH"), field_name="talhao_12")
        self.boundary = _layer(f"Polygon?crs={CRS}", "talhao_12", ["POLYGON((0 0,100 0,100 30,0 30,0 0))"])
        self.project.addMapLayer(self.passes, False)
        organizer.insert_layer_ordered(
            organizer.section_group(organizer.project_group(root, "talhao_12"), "10_PLANEJAMENTO"), self.passes
        )
        self.project.addMapLayer(self.boundary)

    def tearDown(self):
        self.project.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_and_load(self):
        """Executa como o dialogo do Processing: saidas temporarias carregadas no projeto."""
        algorithm = SimulateRealOperationAlgorithm().create()
        context = QgsProcessingContext()
        context.setProject(self.project)
        feedback = QgsProcessingFeedback()
        parameters = {
            "LINES": self.passes,
            "WORK_WIDTH": 10.0,
            "BOUNDARY": self.boundary,
            "COVERAGE": QgsProcessingOutputLayerDefinition("TEMPORARY_OUTPUT", self.project),
            "OVERLAP": QgsProcessingOutputLayerDefinition("TEMPORARY_OUTPUT", self.project),
            "GAP": QgsProcessingOutputLayerDefinition("TEMPORARY_OUTPUT", self.project),
        }
        results, ok = algorithm.run(parameters, context, feedback)
        self.assertTrue(ok)
        loaded = {}
        for dest_id in list(context.layersToLoadOnCompletion()):
            details = context.layerToLoadOnCompletionDetails(dest_id)
            layer = context.temporaryLayerStore().takeMapLayer(context.getMapLayer(dest_id))
            layer.setName(details.name)
            self.project.addMapLayer(layer)
            details.postProcessor().postProcessLayer(layer, context, feedback)
            loaded[layer.customProperty("fortsmart_role")] = layer
        return results, loaded

    def _role_layers(self, role):
        return [layer for layer in self.project.mapLayers().values()
                if layer.customProperty("fortsmart_role", "") == role]

    def test_outputs_use_canonical_roles_and_simulation_section(self):
        _results, loaded = self._run_and_load()
        self.assertEqual(set(loaded), {"COVERAGE", "OVERLAP", "GAP"})
        self.assertEqual(
            {role: layer.name() for role, layer in loaded.items()},
            {"COVERAGE": "41_Cobertura", "OVERLAP": "42_Remonte", "GAP": "43_Falha"},
        )
        root = self.project.layerTreeRoot()
        for layer in loaded.values():
            node = root.findLayer(layer.id())
            self.assertEqual(node.parent().name(), "40_SIMULACAO")
            self.assertEqual(node.parent().parent().name(), "FORTSMART - talhao_12")
            self.assertEqual(layer.customProperty("fortsmart_field_id"), "talhao_12")
            self.assertEqual(layer.customProperty("fortsmart_storage"), "memory")
        self.assertFalse(any(layer.name().startswith("SIM_") for layer in self.project.mapLayers().values()))
        self.assertGreater(loaded["OVERLAP"].featureCount(), 0)

    def test_rerun_keeps_one_layer_per_role(self):
        self._run_and_load()
        self._run_and_load()
        for role in ("COVERAGE", "OVERLAP", "GAP"):
            self.assertEqual(len(self._role_layers(role)), 1)

    def test_save_simulation_writes_41_42_43_and_reopens(self):
        self._run_and_load()
        report = organizer.persist_generated_memory_layers(self.project)
        self.assertIn("41_Cobertura", report["text"])
        path = FortSmartPersistenceManager(self.project).get_field_storage_path("talhao_12")
        tables = set(FortSmartPersistenceManager.table_names(path))
        self.assertTrue({"41_Cobertura", "42_Remonte", "43_Falha"} <= tables)
        coverage = self._role_layers("COVERAGE")[0].featureCount()
        project_file = self.project.fileName()
        self.assertTrue(self.project.write())
        self.project.clear()
        self.assertTrue(self.project.read(project_file))
        reopened = self._role_layers("COVERAGE")
        self.assertEqual(len(reopened), 1)
        self.assertEqual(reopened[0].providerType(), "ogr")
        self.assertEqual(reopened[0].featureCount(), coverage)
        node = self.project.layerTreeRoot().findLayer(reopened[0].id())
        self.assertEqual(node.parent().name(), "40_SIMULACAO")

    def test_new_run_does_not_drop_saved_simulation(self):
        self._run_and_load()
        organizer.persist_generated_memory_layers(self.project)
        saved_id = self._role_layers("COVERAGE")[0].id()
        (self.passes,) = self._role_layers("WORK_PATH")
        self.assertEqual(self.passes.providerType(), "ogr")
        self._run_and_load()
        ids = {layer.id() for layer in self._role_layers("COVERAGE")}
        self.assertIn(saved_id, ids)
        organizer.persist_generated_memory_layers(self.project)
        self.assertEqual([layer.id() for layer in self._role_layers("COVERAGE")], [saved_id])


if __name__ == "__main__":
    unittest.main()
