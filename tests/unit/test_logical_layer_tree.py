# -*- coding: utf-8 -*-
"""Etapa 0C: arvore logica 01-05, visibilidade reversivel e diagnosticos, sem QGIS."""

from __future__ import annotations

import os
import tempfile
import unittest

from plugin.fortsmart_precision.core import logical_layer_tree as llt
from plugin.fortsmart_precision.core import project_context as pc
from plugin.fortsmart_precision.core.layer_roles import (
    AUXILIARY_SECTION,
    LAYER_ROLES,
    PREVIEW_SECTION,
    SECTION_ORDER,
    SIMULATION_ROLES,
    TEMPORARY_PREVIEW_PROPERTY,
)
from tests.unit.test_project_context import (
    FakeIface,
    FakeLayer,
    FakeProject,
    _codes,
    _field_tree,
    _freeze,
    _role_layer,
)


class GeoLayer(FakeLayer):
    def __init__(self, name, *, wkb=3, **kwargs):
        super().__init__(name, **kwargs)
        self._wkb = wkb

    def wkbType(self):
        return self._wkb


def _model(project):
    return llt.LayerOrganizerModel(pc.ProjectContextService(project, FakeIface()))


def _category(field, code):
    return next(item for item in field.categories if item.definition.code == code)


def _names(category):
    return [layer.name for layer in category.layers]


class CategoryCatalogTest(unittest.TestCase):
    def test_every_real_section_has_one_display_category(self):
        mapped = [section for category in llt.LOGICAL_CATEGORIES for section in category.sections]
        self.assertEqual(sorted(mapped), sorted(item for item in SECTION_ORDER if item != AUXILIARY_SECTION))
        self.assertEqual(llt.AUXILIARY_CATEGORY.sections, (AUXILIARY_SECTION,))
        self.assertEqual(llt.PREVIEW_CATEGORY.sections, (PREVIEW_SECTION,))

    def test_titles_are_display_labels_only(self):
        self.assertEqual(
            [item.title for item in llt.LOGICAL_CATEGORIES],
            ["01 — Referências", "02 — Planejamento", "03 — Obstáculos", "04 — Operação", "05 — Análises"],
        )
        self.assertEqual(SECTION_ORDER[:5], ("00_REFERENCIAS", "10_PLANEJAMENTO", "20_OBSTACULOS", "30_OPERACAO", "40_SIMULACAO"))

    def test_flat_wkb_type_ignores_z_m_and_25d(self):
        self.assertEqual(llt.flat_wkb_type(1006), 6)
        self.assertEqual(llt.flat_wkb_type(3003), 3)
        self.assertEqual(llt.flat_wkb_type(0x80000002), 2)
        self.assertEqual(llt.flat_wkb_type(100), 100)
        self.assertIsNone(llt.flat_wkb_type(None))


class TreeStructureTest(unittest.TestCase):
    def test_existing_groups_show_five_categories_per_field(self):
        project = FakeProject()
        _field_tree(project, "TL-1", {"00_REFERENCIAS": [_role_layer("01_Limite_Externo", field_name="TL-1")]})
        _field_tree(project, "TL-2", {})
        tree = _model(project).build()
        self.assertEqual([field.field_id for field in tree.fields], ["TL-1", "TL-2"])
        for field in tree.fields:
            self.assertEqual(
                [item.definition.code for item in field.categories][:5], ["01", "02", "03", "04", "05"]
            )
        self.assertEqual(_names(_category(tree.fields[0], "01")), ["01_Limite_Externo"])
        self.assertEqual(tree.fields[1].layers, ())

    def test_several_fields_keep_their_own_layers(self):
        project = FakeProject()
        _field_tree(project, "TL-1", {
            "00_REFERENCIAS": [_role_layer("01_Limite_Externo", field_name="TL-1")],
            "10_PLANEJAMENTO": [_role_layer("05_Passadas", field_name="TL-1")],
        })
        _field_tree(project, "TL-2", {
            "00_REFERENCIAS": [_role_layer("01_Limite_Externo", field_name="TL-2")],
            "30_OPERACAO": [_role_layer("12_Linhas_Finais", field_name="TL-2")],
            "40_SIMULACAO": [_role_layer("SIM_COVERAGE", catalog=SIMULATION_ROLES, field_name="TL-2")],
        })
        tree = _model(project).build()
        first, second = tree.fields
        self.assertEqual(_names(_category(first, "02")), ["11_Passadas"])
        self.assertEqual(_names(_category(second, "04")), ["31_Linhas_Finais"])
        self.assertEqual(_names(_category(second, "05")), ["41_Cobertura"])
        self.assertTrue(all(layer.field_id == "TL-1" for layer in first.layers))
        self.assertTrue(all(layer.field_id == "TL-2" for layer in second.layers))

    def test_layers_without_group_are_not_associated(self):
        project = FakeProject()
        _field_tree(project, "TL-1", {})
        loose = _role_layer("01_Limite_Externo")
        everything = FakeLayer("Todos — Limites")
        project.root.addLayer(loose)
        project.root.addLayer(everything)
        _freeze(project)
        tree = _model(project).build()
        self.assertEqual([field.field_id for field in tree.fields], ["TL-1"])
        self.assertEqual(tree.fields[0].layers, ())
        outside = {layer.name: layer for layer in tree.unassociated.layers}
        self.assertEqual(set(outside), {"01_Limite_Externo", "Todos — Limites"})
        self.assertIsNone(outside["Todos — Limites"].field_id)
        self.assertEqual(outside["Todos — Limites"].kind, llt.KIND_AUXILIARY)
        self.assertIn(pc.LAYER_OUTSIDE_FIELD_GROUP, _codes(outside["01_Limite_Externo"].diagnostics))
        self.assertIn(llt.UNASSOCIATED_LAYERS, _codes(tree.unassociated.diagnostics))
        self.assertFalse(any(field.field_id == "01_Limite_Externo" for field in tree.fields))

    def test_sim_preview_is_never_a_field(self):
        project = FakeProject()
        preview_inside = _role_layer("05_Passadas", field_name="TL-1", props={TEMPORARY_PREVIEW_PROPERTY: True})
        _field_tree(project, "TL-1", {PREVIEW_SECTION: [preview_inside]})
        root_preview = project.root.addGroup(PREVIEW_SECTION)
        root_preview.addLayer(FakeLayer("Cobertura_Preview", props={TEMPORARY_PREVIEW_PROPERTY: True}))
        bogus = project.root.addGroup("FORTSMART - SIM_PREVIEW")
        bogus.addLayer(FakeLayer("Rota_Preview"))
        tree = _model(project).build()
        self.assertEqual([field.field_id for field in tree.fields], ["TL-1"])
        self.assertEqual(_names(_category(tree.fields[0], "PREVIEW")), ["11_Passadas"])
        self.assertEqual(_category(tree.fields[0], "PREVIEW").layers[0].kind, llt.KIND_PREVIEW)
        outside = {layer.name: layer for layer in tree.unassociated.layers}
        self.assertEqual(outside["Cobertura_Preview"].kind, llt.KIND_PREVIEW)
        self.assertIsNone(outside["Rota_Preview"].field_id)
        self.assertIn(llt.INVALID_FIELD_GROUP, _codes(outside["Rota_Preview"].diagnostics))
        self.assertIn(llt.INVALID_FIELD_GROUP, _codes(tree.diagnostics))

    def test_ambiguous_layer_is_not_placed_under_a_field(self):
        project = FakeProject()
        conflict = _role_layer("01_Limite_Externo", field_name="TL-2")
        _field_tree(project, "TL-1", {"00_REFERENCIAS": [conflict]})
        _field_tree(project, "TL-2", {})
        tree = _model(project).build()
        self.assertEqual(tree.fields[0].layers, ())
        layer = tree.unassociated.layers[0]
        self.assertIsNone(layer.field_id)
        self.assertEqual(layer.status, llt.STATUS_AMBIGUOUS)
        self.assertEqual({candidate for candidate, _source in layer.field_candidates}, {"TL-1", "TL-2"})

    def test_kinds_separate_official_operational_auxiliary_and_preview(self):
        project = FakeProject()
        user = FakeLayer("Talhao_vizinho")
        _field_tree(project, "TL-1", {
            "00_REFERENCIAS": [_role_layer("01_Limite_Externo", field_name="TL-1")],
            "10_PLANEJAMENTO": [_role_layer("05_Passadas", field_name="TL-1")],
            AUXILIARY_SECTION: [user],
        })
        tree = _model(project).build()
        kinds = {layer.name: layer.kind for layer in tree.fields[0].layers}
        self.assertEqual(kinds, {
            "01_Limite_Externo": llt.KIND_OFFICIAL,
            "11_Passadas": llt.KIND_OPERATIONAL,
            "Talhao_vizinho": llt.KIND_AUXILIARY,
        })
        self.assertEqual(_names(_category(tree.fields[0], "AUX")), ["Talhao_vizinho"])

    def test_build_is_read_only(self):
        project = FakeProject()
        _field_tree(project, "TL-1", {
            "00_REFERENCIAS": [_role_layer("01_Limite_Externo", field_name="TL-1")],
            PREVIEW_SECTION: [FakeLayer("x", props={TEMPORARY_PREVIEW_PROPERTY: True})],
        })
        project.root.addLayer(FakeLayer("Todos — Limites"))
        before = project.root.structure()
        _freeze(project)
        _model(project).build()
        self.assertEqual(project.root.structure(), before)

    def test_describe_failure_is_reported_not_skipped(self):
        project = FakeProject()
        _field_tree(project, "TL-1", {"00_REFERENCIAS": [_role_layer("01_Limite_Externo", field_name="TL-1")]})

        def broken(_layer):
            raise RuntimeError("falha simulada")

        tree = llt.build_logical_tree(
            project.root, project.mapLayers().values(), pc.field_groups(project.root), describe=broken
        )
        layer = tree.unassociated.layers[0]
        self.assertIn(llt.DESCRIBE_FAILED, _codes(layer.diagnostics))
        self.assertEqual(layer.status, llt.STATUS_WARNING)


class DiagnosticsTest(unittest.TestCase):
    def test_both_boundaries_visible_warn_without_hiding(self):
        project = FakeProject()
        external = _role_layer("01_Limite_Externo", field_name="TL-1")
        operational = _role_layer("14_Limite_Operacional", field_name="TL-1")
        _field_tree(project, "TL-1", {"00_REFERENCIAS": [external, operational]})
        model = _model(project)
        field = model.build().fields[0]
        self.assertIn(pc.MULTIPLE_APPLICABLE_BOUNDARIES, _codes(field.diagnostics))
        self.assertEqual(field.status, llt.STATUS_WARNING)
        for layer in field.layers:
            self.assertIn(llt.BOUNDARY_VISIBLE_WITH_OTHER, _codes(layer.diagnostics))
        nodes = project.root.findLayers()
        self.assertTrue(all(node.visible for node in nodes))
        project.root.findLayer(operational.id()).visible = False
        field = model.build().fields[0]
        self.assertNotIn(pc.MULTIPLE_APPLICABLE_BOUNDARIES, _codes(field.diagnostics))
        self.assertTrue(all(llt.BOUNDARY_VISIBLE_WITH_OTHER not in _codes(item.diagnostics) for item in field.layers))

    def test_conflicting_roles_are_reported(self):
        project = FakeProject()
        first = _role_layer("05_Passadas", field_name="TL-1")
        second = _role_layer("05_Passadas", name="11_Passadas_copia", field_name="TL-1")
        attribute = _role_layer("01_Limite_Externo", field_name="TL-1", attrs={"fortsmart_role": {"OBSTACLE"}})
        _field_tree(project, "TL-1", {"00_REFERENCIAS": [attribute], "10_PLANEJAMENTO": [first, second]})
        tree = _model(project).build()
        self.assertIn(llt.DUPLICATE_ROLE_IN_FIELD, _codes(tree.fields[0].diagnostics))
        boundary = tree.layer(attribute.id())
        self.assertIn(pc.ROLE_ATTRIBUTE_CONFLICT, _codes(boundary.diagnostics))
        self.assertEqual(boundary.status, llt.STATUS_WARNING)

    def test_reprojected_copy_without_metadata_is_flagged(self):
        project = FakeProject()
        source = _role_layer("01_Limite_Externo", field_name="TL-1")
        copy = FakeLayer("01_Limite_Externo (EPSG:31982)", crs="EPSG:31982")
        _field_tree(project, "TL-1", {"00_REFERENCIAS": [source]})
        project.root.addLayer(copy)
        _freeze(project)
        layer = _model(project).build().layer(copy.id())
        self.assertIn(pc.REPROJECTED_COPY_WITHOUT_METADATA, _codes(layer.diagnostics))
        self.assertIsNone(layer.field_id)

    def test_field_named_after_a_layer_is_flagged_not_renamed(self):
        project = FakeProject()
        _field_tree(project, "01_Limite_Externo", {})
        tree = _model(project).build()
        self.assertEqual(tree.fields[0].field_id, "01_Limite_Externo")
        self.assertIn(llt.FIELD_GROUP_NAMED_AFTER_LAYER, _codes(tree.fields[0].diagnostics))
        self.assertEqual(project.root.children()[0].name(), "FORTSMART - 01_Limite_Externo")


class ModelCacheTest(unittest.TestCase):
    def test_precomputed_groups_give_the_same_context(self):
        project = FakeProject()
        _field_tree(project, "TL-1", {"00_REFERENCIAS": [_role_layer("01_Limite_Externo", field_name="TL-1")]})
        _field_tree(project, "TL-1", {"10_PLANEJAMENTO": [_role_layer("05_Passadas", field_name="TL-1")]})
        _field_tree(project, "TL-2", {"00_REFERENCIAS": [_role_layer("01_Limite_Externo", field_name="TL-1")]})
        project.root.addLayer(FakeLayer("01_Limite_Externo (EPSG:31982)"))
        groups = pc.field_groups(project.root)
        layers = list(project.mapLayers().values())
        for layer in layers:
            self.assertEqual(
                pc.describe_layer(project.root, layer, layers, groups=groups),
                pc.describe_layer(project.root, layer, layers),
                layer.name(),
            )

    def _project(self):
        project = FakeProject()
        _field_tree(project, "TL-1", {"00_REFERENCIAS": [_role_layer("01_Limite_Externo", field_name="TL-1")]})
        _field_tree(project, "TL-2", {"00_REFERENCIAS": [_role_layer("01_Limite_Externo", field_name="TL-2")]})
        return project

    def test_visibility_change_reuses_layer_context(self):
        project = self._project()
        model = _model(project)
        model.build()
        self.assertEqual(model.stats["describe_calls"], 2)
        self.assertEqual(model.stats["field_diagnostic_calls"], 2)
        model.build()
        self.assertEqual(model.stats["describe_calls"], 2)
        self.assertEqual(model.stats["field_diagnostic_calls"], 2)
        project.root.findLayers()[0].visible = False
        model.build()
        self.assertEqual(model.stats["describe_calls"], 2)
        self.assertEqual(model.stats["field_diagnostic_calls"], 3)

    def test_invalidating_one_layer_redescribes_only_it(self):
        project = self._project()
        model = _model(project)
        model.build()
        layer_id = project.root.findLayers()[0].layer().id()
        model.invalidate([layer_id])
        model.build()
        self.assertEqual(model.stats["describe_calls"], 3)
        model.invalidate()
        model.build()
        self.assertEqual(model.stats["describe_calls"], 5)


class VisibilityJournalTest(unittest.TestCase):
    def setUp(self):
        self.project = FakeProject()
        self.a = _role_layer("01_Limite_Externo", field_name="TL-1")
        self.b = _role_layer("14_Limite_Operacional", field_name="TL-1")
        _field_tree(self.project, "TL-1", {"00_REFERENCIAS": [self.a, self.b]})
        self.root = self.project.root
        self.structure = self.root.structure()

    def node(self, layer):
        return self.root.findLayer(layer.id())

    def test_hide_and_restore_on_original_node(self):
        journal = llt.VisibilityJournal()
        report = journal.apply(self.root, [self.a.id(), self.b.id()], False)
        self.assertEqual(len(report.changed), 2)
        self.assertFalse(self.node(self.a).visible)
        self.assertEqual(journal.pending, 2)
        report = journal.restore(self.root)
        self.assertEqual(len(report.changed), 2)
        self.assertTrue(self.node(self.a).visible and self.node(self.b).visible)
        self.assertEqual(journal.pending, 0)
        self.assertEqual(self.root.structure(), self.structure)

    def test_restore_keeps_later_manual_change(self):
        journal = llt.VisibilityJournal()
        journal.apply(self.root, [self.a.id(), self.b.id()], False)
        self.node(self.b).visible = True
        report = journal.restore(self.root)
        self.assertEqual(report.kept, ("05_Limite_Operacional",))
        self.assertIn("mantidas", report.text(restoring=True))
        self.assertTrue(self.node(self.a).visible)

    def test_toggle_back_and_unchanged_are_not_recorded(self):
        journal = llt.VisibilityJournal()
        report = journal.apply(self.root, [self.a.id()], True)
        self.assertEqual(report.unchanged, ("01_Limite_Externo",))
        self.assertEqual(journal.pending, 0)
        journal.apply(self.root, [self.a.id()], False)
        journal.apply(self.root, [self.a.id()], True)
        self.assertEqual(journal.pending, 0)

    def test_missing_layer_is_reported(self):
        journal = llt.VisibilityJournal()
        journal.apply(self.root, [self.a.id()], False)
        self.root._children[0]._children[0]._children.remove(self.node(self.a))
        report = journal.restore(self.root)
        self.assertEqual(report.missing, ("01_Limite_Externo",))


class GeometryRiskTest(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".gpkg")
        os.close(handle)
        self.reads = []

    def tearDown(self):
        os.remove(self.path)

    def _checker(self, table_type):
        def read(path, table):
            self.reads.append(table)
            return table_type

        return llt.GeometryRiskChecker(lambda _field: self.path, read)

    def _context(self, layer):
        project = FakeProject()
        _field_tree(project, "TL-1", {"20_OBSTACULOS": [layer]})
        return pc.describe_layer(project.root, layer)

    def test_multipolygon_into_polygon_table_is_potential_risk(self):
        layer = GeoLayer("22_Zonas_Seguranca", wkb=1006)
        from plugin.fortsmart_precision.core.layer_roles import set_layer_role_properties

        set_layer_role_properties(layer, LAYER_ROLES["10_Zonas_Seguranca"], field_name="TL-1")
        checker = self._checker(3)
        found = checker(layer, self._context(layer))
        self.assertEqual(_codes(found), {llt.GEOMETRY_WRITE_RISK})
        self.assertIn("MULTIPART_INTO_SINGLE", found[0].message)
        checker(layer, self._context(layer))
        self.assertEqual(self.reads, ["22_Zonas_Seguranca"])

    def test_same_type_temporary_or_missing_table_are_quiet(self):
        from plugin.fortsmart_precision.core.layer_roles import set_layer_role_properties

        layer = GeoLayer("22_Zonas_Seguranca", wkb=3)
        set_layer_role_properties(layer, LAYER_ROLES["10_Zonas_Seguranca"], field_name="TL-1")
        self.assertEqual(self._checker(3)(layer, self._context(layer)), ())
        self.assertEqual(self._checker(None)(layer, self._context(layer)), ())
        preview = GeoLayer("22_Zonas_Seguranca", wkb=6, props={TEMPORARY_PREVIEW_PROPERTY: True})
        set_layer_role_properties(preview, LAYER_ROLES["10_Zonas_Seguranca"], field_name="TL-1")
        self.assertEqual(self._checker(3)(preview, self._context(preview)), ())


if __name__ == "__main__":
    unittest.main()
