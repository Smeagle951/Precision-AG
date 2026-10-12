# -*- coding: utf-8 -*-
"""Arvore canonica FORTSMART: secoes, ordem, substituicao por role e normalizacao."""

from __future__ import annotations

import os
import unittest

try:
    from qgis.core import QgsApplication

    HAS_QGIS = True
except ImportError:
    HAS_QGIS = False

CRS = "EPSG:31981"
_APP = None


def _qgis_setup():
    global _APP
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if QgsApplication.instance() is None:
        _APP = QgsApplication([], True)
        _APP.initQgis()


def _layer(name, wkt="LINESTRING(0 0, 10 0)", geometry="LineString"):
    from qgis.core import QgsFeature, QgsGeometry, QgsVectorLayer

    layer = QgsVectorLayer(f"{geometry}?crs={CRS}", name, "memory")
    feature = QgsFeature()
    feature.setGeometry(QgsGeometry.fromWkt(wkt))
    layer.dataProvider().addFeatures([feature])
    return layer


def _generated(name, key, field_name="talhao_12"):
    from plugin.fortsmart_precision.core.layer_roles import definition_for_key, set_layer_role_properties

    layer = _layer(name)
    set_layer_role_properties(layer, definition_for_key(key), field_name=field_name)
    return layer


@unittest.skipUnless(HAS_QGIS, "QGIS nao disponivel")
class LayerTreeOrganizerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _qgis_setup()

    def setUp(self):
        from qgis.core import QgsProject

        from plugin.fortsmart_precision.gui import layer_tree_organizer as organizer

        self.organizer = organizer
        self.project = QgsProject.instance()
        self.project.clear()
        self.root = self.project.layerTreeRoot()

    def tearDown(self):
        self.project.clear()

    def test_project_group_is_unique_per_field(self):
        first = self.organizer.project_group(self.root, "Boundary — talhao_12 (EPSG:31981)")
        second = self.organizer.project_group(self.root, "talhao_12")
        self.assertIs(first, second)
        self.assertEqual(first.name(), "FORTSMART - talhao_12")
        self.assertIsNone(self.organizer.project_group(self.root, "talhao_99", create=False))

    def test_sections_follow_canonical_order(self):
        parent = self.organizer.project_group(self.root, "talhao_12")
        for section in ("40_SIMULACAO", "10_PLANEJAMENTO", "90_AUXILIARES", "00_REFERENCIAS", "30_OPERACAO"):
            self.organizer.section_group(parent, section)
        self.organizer.preview_group(parent)
        self.organizer.section_group(parent, "20_OBSTACULOS")
        self.assertEqual(
            [child.name() for child in parent.children()],
            ["SIM_PREVIEW", "00_REFERENCIAS", "10_PLANEJAMENTO", "20_OBSTACULOS", "30_OPERACAO",
             "40_SIMULACAO", "90_AUXILIARES"],
        )
        self.assertIs(self.organizer.section_group(parent, "10_PLANEJAMENTO"), parent.findGroup("10_PLANEJAMENTO"))

    def test_layers_are_inserted_in_role_order(self):
        parent = self.organizer.project_group(self.root, "talhao_12")
        section = self.organizer.section_group(parent, "10_PLANEJAMENTO")
        user = _layer("minha camada")
        layers = [
            _generated("13_Linha_Trator", "07_Linha_Trator"),
            user,
            _generated("16_Manobras_Cabeceira", "HEADLAND_TURN"),
            _generated("11_Passadas", "05_Passadas"),
            _generated("Passadas de Plantio", "06_Passadas_Plantio"),
        ]
        for layer in layers:
            self.project.addMapLayer(layer, False)
            self.organizer.insert_layer_ordered(section, layer)
        self.assertEqual(
            [child.name() for child in section.children()],
            ["11_Passadas", "Passadas de Plantio", "13_Linha_Trator", "16_Manobras_Cabeceira", "minha camada"],
        )

    def test_generated_layers_for_role_is_scoped_to_field(self):
        from plugin.fortsmart_precision.core.layer_roles import mark_temporary_preview

        mine = _generated("12_Passadas_Plantio", "06_Passadas_Plantio")
        other = _generated("12_Passadas_Plantio", "06_Passadas_Plantio", field_name="talhao_13")
        preview = _generated("12_Passadas_Plantio", "06_Passadas_Plantio")
        mark_temporary_preview(preview)
        user = _layer("12_Passadas_Plantio")
        user.setCustomProperty("fortsmart_role", "WORK_PATH")
        for layer in (mine, other, preview, user):
            self.project.addMapLayer(layer)
        found = self.organizer.generated_layers_for_role(self.project, "WORK_PATH", "Boundary — talhao_12")
        self.assertEqual(found, [mine])
        with_preview = self.organizer.generated_layers_for_role(
            self.project, "WORK_PATH", "talhao_12", include_temporary=True
        )
        self.assertEqual({layer.id() for layer in with_preview}, {mine.id(), preview.id()})

    def test_originals_move_to_auxiliaries_without_data_change(self):
        parent = self.organizer.project_group(self.root, "talhao_12")
        boundary = _layer("Boundary — talhao_12", "POLYGON((0 0,10 0,10 10,0 10,0 0))", "Polygon")
        grouped = _layer("Reta A")
        self.project.addMapLayer(boundary)
        self.project.addMapLayer(grouped, False)
        self.root.addGroup("meus dados").addLayer(grouped)
        before = [feature.geometry().asWkt() for feature in boundary.getFeatures()]
        moved = self.organizer.move_layers_to_auxiliaries(self.root, parent, [boundary, grouped, None])
        self.assertEqual(moved, ["Boundary — talhao_12"])
        node = self.root.findLayer(boundary.id())
        self.assertEqual(node.parent().name(), "90_AUXILIARES")
        self.assertEqual(boundary.name(), "Boundary — talhao_12")
        self.assertEqual([feature.geometry().asWkt() for feature in boundary.getFeatures()], before)
        self.assertEqual(self.root.findLayer(grouped.id()).parent().name(), "meus dados")
        self.assertEqual(len(self.root.findLayers()), 2)

    def test_empty_groups_are_pruned(self):
        parent = self.organizer.project_group(self.root, "talhao_12")
        self.organizer.preview_group(parent)
        section = self.organizer.section_group(parent, "10_PLANEJAMENTO")
        layer = _generated("11_Passadas", "05_Passadas")
        self.project.addMapLayer(layer, False)
        section.addLayer(layer)
        self.organizer.section_group(parent, "30_OPERACAO")
        self.organizer.prune_empty_sections(parent)
        self.assertEqual([child.name() for child in parent.children()], ["10_PLANEJAMENTO"])
        self.organizer.remove_group_if_empty(parent)
        self.assertIsNotNone(self.root.findGroup("FORTSMART - talhao_12"))

    def test_normalize_legacy_project_layers(self):
        parent = self.organizer.project_group(self.root, "talhao_12")
        legacy = _layer("_fortsmart_workspace_06_Passadas_Plantio (12)")
        legacy.setCustomProperty("fortsmart_precision/preview_layer", "06_Passadas_Plantio")
        user_inside = _layer("12_Passadas_Plantio")
        boundary = _layer("Boundary — talhao_12", "POLYGON((0 0,10 0,10 10,0 10,0 0))", "Polygon")
        loose = _layer("marcacao_35", "POINT(1 1)", "Point")
        for layer in (legacy, user_inside):
            self.project.addMapLayer(layer, False)
            parent.addLayer(layer)
        self.project.addMapLayer(boundary)
        self.project.addMapLayer(loose)
        before = [feature.geometry().asWkt() for feature in legacy.getFeatures()]

        report = self.organizer.normalize_legacy_project_layers(self.project)

        self.assertEqual(legacy.customProperty("fortsmart_role"), "WORK_PATH")
        self.assertEqual(legacy.customProperty("fortsmart_field_id"), "talhao_12")
        self.assertEqual(legacy.customProperty("fortsmart_original_name"), "_fortsmart_workspace_06_Passadas_Plantio (12)")
        self.assertEqual(legacy.customProperty("fortsmart_classified_by"), "internal_key")
        self.assertEqual(legacy.name(), "_fortsmart_workspace_06_Passadas_Plantio (12)")
        self.assertEqual([feature.geometry().asWkt() for feature in legacy.getFeatures()], before)
        self.assertEqual(self.root.findLayer(legacy.id()).parent().name(), "10_PLANEJAMENTO")
        self.assertEqual(user_inside.customProperty("fortsmart_role", ""), "")
        self.assertEqual(self.root.findLayer(user_inside.id()).parent().name(), "90_AUXILIARES")
        self.assertEqual(boundary.customProperty("fortsmart_role", ""), "")
        self.assertEqual(self.root.findLayer(boundary.id()).parent().name(), "90_AUXILIARES")
        self.assertIs(self.root.findLayer(loose.id()).parent(), self.root)
        self.assertEqual(len(self.project.mapLayers()), 4)
        self.assertEqual(len(report["moved"]), 3)
        self.assertIn("Camadas movidas: 3", report["text"])
        self.assertIn("marcacao_35", report["summary"]["external_layers"])

        second = self.organizer.normalize_legacy_project_layers(self.project)
        self.assertEqual(second["moved"], [])


if __name__ == "__main__":
    unittest.main()
