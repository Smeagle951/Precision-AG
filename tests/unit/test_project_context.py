# -*- coding: utf-8 -*-
"""Etapa 0B: contexto do projeto (talhao, papel, reprojecao, contratos do Ag) sem QGIS."""

from __future__ import annotations

import unittest
import uuid

from plugin.fortsmart_precision import feature_flags
from plugin.fortsmart_precision.core import geometry_write_check as gwc
from plugin.fortsmart_precision.core import project_context as pc
from plugin.fortsmart_precision.core.layer_roles import (
    LAYER_ROLES,
    SIMULATION_ROLES,
    classify_layer,
    definition_for_role,
    set_layer_role_properties,
)


class FakeFields:
    def __init__(self, names):
        self._names = list(names)

    def names(self):
        return list(self._names)


class FakeCrs:
    def __init__(self, authid, *, geographic=None, valid=True):
        self._authid = authid
        self._geographic = geographic
        self._valid = valid

    def authid(self):
        return self._authid

    def isValid(self):
        return self._valid

    def isGeographic(self):
        return self._geographic if self._geographic is not None else self._authid in ("EPSG:4326", "EPSG:4674")


class FakeLayer:
    _counter = 0

    def __init__(self, name, *, props=None, attrs=None, crs="EPSG:31981", features=1, provider="memory",
                 selected=0, editing=False):
        FakeLayer._counter += 1
        self._id = f"layer_{FakeLayer._counter}"
        self._name = name
        self._props = dict(props or {})
        self._attrs = {key: set(values) for key, values in (attrs or {}).items()}
        self._crs = FakeCrs(crs) if isinstance(crs, str) else crs
        self._features = features
        self._provider = provider
        self._selected = selected
        self._editing = editing
        self.frozen = False

    def id(self):
        return self._id

    def name(self):
        return self._name

    def customProperty(self, key, default=None):
        return self._props.get(key, default)

    def setCustomProperty(self, key, value):
        if self.frozen:
            raise AssertionError(f"contexto gravou metadado: {key}")
        self._props[key] = value

    def fields(self):
        return FakeFields(self._attrs)

    def uniqueValues(self, index, limit=-1):
        return set(self._attrs[list(self._attrs)[index]])

    def featureCount(self):
        return self._features

    def crs(self):
        return self._crs

    def selectedFeatureCount(self):
        return self._selected

    def isEditable(self):
        return self._editing

    def providerType(self):
        return self._provider


class FakeLayerNode:
    def __init__(self, layer, parent):
        self._layer = layer
        self._parent = parent
        self.visible = True

    def layer(self):
        return self._layer

    def name(self):
        return self._layer.name()

    def parent(self):
        return self._parent

    def children(self):
        return []

    def isVisible(self):
        return self.visible and self._parent.isVisible()

    def itemVisibilityChecked(self):
        return self.visible

    def setItemVisibilityChecked(self, value):
        self.visible = bool(value)


class FakeGroup:
    def __init__(self, name="", parent=None):
        self._name = name
        self._parent = parent
        self._children = []
        self.visible = True
        self.frozen = False

    def name(self):
        return self._name

    def parent(self):
        return self._parent

    def children(self):
        return list(self._children)

    def isVisible(self):
        return self.visible and (self._parent.isVisible() if self._parent is not None else True)

    def addGroup(self, name):
        group = FakeGroup(name, self)
        self._children.append(group)
        return group

    def addLayer(self, layer):
        node = FakeLayerNode(layer, self)
        self._children.append(node)
        return node

    def findLayers(self):
        found = []
        for child in self._children:
            if isinstance(child, FakeLayerNode):
                found.append(child)
            else:
                found.extend(child.findLayers())
        return found

    def findLayer(self, layer_id):
        return next((node for node in self.findLayers() if node.layer().id() == layer_id), None)

    def structure(self):
        return [
            (child.name(), child.structure() if isinstance(child, FakeGroup) else child.layer().id())
            for child in self._children
        ]


class FakeProject:
    def __init__(self, file_name="C:/dados/fazenda.qgz"):
        self.root = FakeGroup()
        self._file = file_name

    def layerTreeRoot(self):
        return self.root

    def mapLayers(self):
        return {node.layer().id(): node.layer() for node in self.root.findLayers()}

    def fileName(self):
        return self._file

    def title(self):
        return ""

    def crs(self):
        return FakeCrs("EPSG:31981")


class FakeIface:
    def __init__(self, layer=None):
        self.layer = layer

    def activeLayer(self):
        return self.layer


class FakeSettings:
    def __init__(self):
        self.values = {}

    def value(self, key, default=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value


def _role_layer(key, *, name=None, field_name=None, catalog=LAYER_ROLES, **kwargs):
    definition = catalog[key]
    layer = FakeLayer(name or definition.display_name, **kwargs)
    set_layer_role_properties(layer, definition, field_name=field_name)
    return layer


def _field_tree(project, field_name, layers_by_section):
    group = project.root.addGroup(f"FORTSMART - {field_name}")
    for section, layers in layers_by_section.items():
        target = group.addGroup(section) if section else group
        for layer in layers:
            target.addLayer(layer)
    return group


def _freeze(project):
    for layer in project.mapLayers().values():
        layer.frozen = True


def _codes(diagnostics):
    return {item.code for item in diagnostics}


class FieldIdentityTest(unittest.TestCase):
    def test_layer_inside_fortsmart_group_resolves_by_group(self):
        project = FakeProject()
        boundary = _role_layer("01_Limite_Externo", field_name="TH 6 B")
        _field_tree(project, "TH 6 B", {"00_REFERENCIAS": [boundary]})
        _freeze(project)
        resolution, diagnostics = pc.resolve_layer_field(project.root, boundary)
        self.assertEqual(resolution.status, pc.FIELD_RESOLVED)
        self.assertEqual(resolution.field_id, "TH 6 B")
        self.assertEqual(resolution.source, pc.SOURCE_PROJECT_GROUP)
        self.assertEqual(diagnostics, ())

    def test_layer_named_like_boundary_at_root_never_becomes_a_field(self):
        project = FakeProject()
        loose = FakeLayer("01_Limite_Externo")
        project.root.addLayer(loose)
        _freeze(project)
        before = project.root.structure()
        service = pc.ProjectContextService(project, FakeIface(loose))
        context = service.snapshot()
        self.assertEqual(context.field.status, pc.FIELD_UNRESOLVED)
        self.assertIsNone(context.field.field_id)
        self.assertNotIn("01_Limite_Externo", [value for value, _source in context.field.candidates])
        self.assertIn(pc.FIELD_NOT_SELECTED, _codes(context.diagnostics))
        self.assertIn(pc.LAYER_OUTSIDE_FIELD_GROUP, _codes(context.active_layer.diagnostics))
        self.assertEqual(project.root.structure(), before)

    def test_group_and_metadata_conflict_is_ambiguous(self):
        project = FakeProject()
        layer = _role_layer("06_Passadas_Plantio", field_name="TL-13")
        _field_tree(project, "TL-12", {"10_PLANEJAMENTO": [layer]})
        _freeze(project)
        resolution, diagnostics = pc.resolve_layer_field(project.root, layer)
        self.assertEqual(resolution.status, pc.FIELD_AMBIGUOUS)
        self.assertIsNone(resolution.field_id)
        self.assertEqual(
            set(resolution.candidates), {("TL-12", pc.SOURCE_PROJECT_GROUP), ("TL-13", pc.SOURCE_LAYER_METADATA)}
        )
        self.assertIn(pc.FIELD_METADATA_CONFLICT, _codes(diagnostics))

    def test_metadata_outside_group_is_only_a_candidate(self):
        project = FakeProject()
        layer = _role_layer("06_Passadas_Plantio", field_name="TL-13")
        project.root.addLayer(layer)
        _freeze(project)
        resolution, diagnostics = pc.resolve_layer_field(project.root, layer)
        self.assertEqual(resolution.status, pc.FIELD_UNRESOLVED)
        self.assertEqual(resolution.candidates, (("TL-13", pc.SOURCE_LAYER_METADATA),))
        self.assertEqual(diagnostics[0].severity, pc.SEVERITY_WARNING)

    def test_ag_import_tree_and_todos_limites_are_not_associated(self):
        project = FakeProject()
        imported_root = project.root.addGroup("FortSmart GS3")
        todos = FakeLayer("Todos — Limites", props={"fortsmart_role": "EXTERNAL_BOUNDARY"})
        imported_root.addLayer(todos)
        field_group = imported_root.addGroup("Fazenda Exemplo").addGroup("TL-12")
        boundary = FakeLayer("Limite", props={"fortsmart_role": "EXTERNAL_BOUNDARY"})
        field_group.addLayer(boundary)
        _freeze(project)
        todos_context = pc.describe_layer(project.root, todos, project.mapLayers().values())
        self.assertEqual(todos_context.field.status, pc.FIELD_UNRESOLVED)
        self.assertIsNone(todos_context.ag_group_name)
        self.assertEqual(todos_context.field.candidates, (("FortSmart GS3", pc.SOURCE_OTHER_GROUP),))
        boundary_context = pc.describe_layer(project.root, boundary, project.mapLayers().values())
        self.assertEqual(boundary_context.field.status, pc.FIELD_UNRESOLVED)
        self.assertEqual(boundary_context.ag_group_name, "TL-12")
        self.assertIn(("TL-12", pc.SOURCE_OTHER_GROUP), boundary_context.field.candidates)

    def test_duplicate_field_groups_are_reported(self):
        project = FakeProject()
        first = _role_layer("01_Limite_Externo")
        second = _role_layer("01_Limite_Externo")
        _field_tree(project, "TL-12", {"00_REFERENCIAS": [first]})
        project.root.addGroup("Arquivo").addGroup("FORTSMART - TL-12").addLayer(second)
        _freeze(project)
        resolution, diagnostics = pc.resolve_layer_field(project.root, first)
        self.assertTrue(resolution.resolved)
        self.assertIn(pc.DUPLICATE_FIELD_GROUP, _codes(diagnostics))

    def test_preview_group_without_sections_differs_from_ag_grouping(self):
        project = FakeProject()
        preview = _role_layer("SIM_WORK_LINES", catalog=SIMULATION_ROLES)
        group = project.root.addGroup("FORTSMART - TL-9")
        group.addGroup("SIM_PREVIEW").addLayer(preview)
        _freeze(project)
        context = pc.describe_layer(project.root, preview, project.mapLayers().values())
        self.assertTrue(context.field.resolved)
        self.assertEqual(context.ag_group_name, "SIM_PREVIEW")
        self.assertIn(pc.AG_GROUP_DIFFERS, _codes(context.diagnostics))

    def test_sections_keep_ag_grouping_on_field_group(self):
        project = FakeProject()
        boundary = _role_layer("01_Limite_Externo")
        preview = _role_layer("SIM_WORK_LINES", catalog=SIMULATION_ROLES)
        group = _field_tree(project, "TL-9", {"00_REFERENCIAS": [boundary]})
        group.addGroup("SIM_PREVIEW").addLayer(preview)
        _freeze(project)
        for layer in (boundary, preview):
            context = pc.describe_layer(project.root, layer, project.mapLayers().values())
            self.assertEqual(context.ag_group_name, "FORTSMART - TL-9")
            self.assertNotIn(pc.AG_GROUP_DIFFERS, _codes(context.diagnostics))


class RoleCatalogReuseTest(unittest.TestCase):
    def test_role_section_and_name_come_from_layer_roles(self):
        project = FakeProject()
        layers = [_role_layer(key) for key in LAYER_ROLES] + [
            _role_layer(key, catalog=SIMULATION_ROLES) for key in SIMULATION_ROLES
        ]
        _field_tree(project, "TL-1", {"": layers})
        _freeze(project)
        for layer in layers:
            context = pc.describe_layer(project.root, layer, project.mapLayers().values())
            role, source = classify_layer(layer)
            definition = definition_for_role(role)
            self.assertEqual((context.role, context.role_source), (role, source))
            self.assertEqual(context.section, definition.section)
            self.assertEqual(context.display_name, definition.display_name)
            self.assertTrue(context.role_trusted)

    def test_role_known_only_by_name_is_flagged(self):
        project = FakeProject()
        layer = FakeLayer("12_Passadas_Plantio")
        _field_tree(project, "TL-1", {"10_PLANEJAMENTO": [layer]})
        _freeze(project)
        context = pc.describe_layer(project.root, layer, project.mapLayers().values())
        self.assertEqual(context.role, "WORK_PATH")
        self.assertFalse(context.role_trusted)
        self.assertIn(pc.ROLE_BY_NAME_ONLY, _codes(context.diagnostics))

    def test_planner_only_roles_are_reported_as_not_exported_by_ag(self):
        for key in ("FINAL_BORDER_PASS", "SIM_COVERAGE", "SIM_BORDER_GAPS"):
            layer = _role_layer(key, catalog=SIMULATION_ROLES)
            role, source = classify_layer(layer)
            self.assertIn(pc.ROLE_UNKNOWN_TO_AG, _codes(pc.role_diagnostics(layer, role, source)))
        for key in ("01_Limite_Externo", "15_Passadas_Bordadura", "05_Passadas", "09_Obstaculos_RTK"):
            layer = _role_layer(key)
            role, source = classify_layer(layer)
            self.assertNotIn(pc.ROLE_UNKNOWN_TO_AG, _codes(pc.role_diagnostics(layer, role, source)))


class ReprojectedCopyTest(unittest.TestCase):
    def test_copy_without_metadata_is_diagnosed_and_untouched(self):
        project = FakeProject()
        source = _role_layer("01_Limite_Externo")
        copy = FakeLayer(
            "01_Limite_Externo (EPSG:31981)", attrs={"fortsmart_role": {"EXTERNAL_BOUNDARY"}}
        )
        _field_tree(project, "TL-5", {"00_REFERENCIAS": [source, copy]})
        _freeze(project)
        context = pc.describe_layer(project.root, copy, project.mapLayers().values())
        self.assertEqual(context.reprojection.base_name, "01_Limite_Externo")
        self.assertEqual(context.reprojection.declared_authid, "EPSG:31981")
        self.assertEqual(context.reprojection.source_layer_ids, (source.id(),))
        self.assertFalse(context.reprojection.has_fortsmart_metadata)
        self.assertEqual(context.reprojection.attribute_roles, ("EXTERNAL_BOUNDARY",))
        codes = _codes(context.diagnostics)
        self.assertTrue({pc.REPROJECTED_COPY, pc.REPROJECTED_COPY_WITHOUT_METADATA, pc.ROLE_ONLY_IN_ATTRIBUTE} <= codes)
        self.assertFalse(context.is_generated)
        self.assertEqual(copy.customProperty("fortsmart_role"), None)

    def test_copy_with_metadata_is_only_informed(self):
        copy = _role_layer("01_Limite_Externo", name="01_Limite_Externo (EPSG:31982)")
        info = pc.reprojection_info(copy, [copy])
        self.assertTrue(info.has_fortsmart_metadata)
        self.assertEqual(info.source_layer_ids, ())
        self.assertEqual(_codes(pc.reprojection_diagnostics(info)), {pc.REPROJECTED_COPY})

    def test_regular_names_are_not_copies(self):
        for name in ("01_Limite_Externo", "Talhao (2)", "EPSG 31981"):
            self.assertIsNone(pc.reprojection_info(FakeLayer(name), []))


class AgExportContractTest(unittest.TestCase):
    def test_external_and_operational_boundaries_count_as_one_limit(self):
        external = _role_layer("01_Limite_Externo")
        operational = _role_layer("14_Limite_Operacional")
        both = pc.export_contract_diagnostics([external, operational])
        self.assertIn(pc.MULTIPLE_APPLICABLE_BOUNDARIES, _codes(both))
        only_visible = pc.export_contract_diagnostics([external, operational], visible_ids={external.id()})
        self.assertNotIn(pc.MULTIPLE_APPLICABLE_BOUNDARIES, _codes(only_visible))
        self.assertIn(pc.NO_APPLICABLE_BOUNDARY, _codes(pc.export_contract_diagnostics([_role_layer("04_Linha_AB")])))

    def test_multipart_boundary_layer_counts_each_feature(self):
        external = _role_layer("01_Limite_Externo", features=2)
        self.assertIn(pc.MULTIPLE_APPLICABLE_BOUNDARIES, _codes(pc.export_contract_diagnostics([external])))

    def test_field_erid_must_be_consistent_and_valid(self):
        same = str(uuid.uuid4())
        consistent = [
            _role_layer("01_Limite_Externo", attrs={"field_erid": {same}}),
            _role_layer("04_Linha_AB", attrs={"field_erid": {same}}),
        ]
        self.assertFalse(
            _codes(pc.export_contract_diagnostics(consistent)) & {pc.FIELD_ERID_INCONSISTENT, pc.FIELD_ERID_INVALID}
        )
        split = consistent + [_role_layer("05_Passadas", attrs={"field_erid": {str(uuid.uuid4())}})]
        self.assertIn(pc.FIELD_ERID_INCONSISTENT, _codes(pc.export_contract_diagnostics(split)))
        invalid = [_role_layer("01_Limite_Externo", attrs={"field_erid": {"talhao-12"}})]
        self.assertIn(pc.FIELD_ERID_INVALID, _codes(pc.export_contract_diagnostics(invalid)))

    def test_role_attribute_conflict_follows_ag_feature_precedence(self):
        layer = _role_layer("06_Passadas_Plantio", attrs={"role": {"WORK_PATH", "FIELD_HEADLAND_PATH"}})
        role, source = classify_layer(layer)
        self.assertIn(pc.ROLE_ATTRIBUTE_CONFLICT, _codes(pc.role_diagnostics(layer, role, source)))
        other_use = _role_layer("06_Passadas_Plantio", attrs={"role": {"traffic"}})
        role, source = classify_layer(other_use)
        self.assertNotIn(pc.ROLE_ATTRIBUTE_CONFLICT, _codes(pc.role_diagnostics(other_use, role, source)))


class CrsAndFarmTest(unittest.TestCase):
    def test_crs_summary(self):
        utm = pc.crs_summary(FakeCrs("EPSG:31981"))
        self.assertTrue(utm.is_metric and utm.is_fortsmart_standard and not utm.is_geographic)
        self.assertEqual(pc.crs_diagnostics(utm), ())
        geographic = pc.crs_summary(FakeCrs("EPSG:4674"))
        self.assertEqual(_codes(pc.crs_diagnostics(geographic)), {pc.CRS_GEOGRAPHIC})
        self.assertEqual(_codes(pc.crs_diagnostics(pc.crs_summary(FakeCrs("", valid=False)))), {pc.CRS_INVALID})
        self.assertEqual(_codes(pc.crs_diagnostics(None)), {pc.CRS_INVALID})

    def test_farm_comes_only_from_attributes(self):
        one = pc.farm_from_layers([FakeLayer("a", attrs={"fazenda": {"Santa Rita"}}), FakeLayer("b")])
        self.assertEqual((one.status, one.name), (pc.FIELD_RESOLVED, "Santa Rita"))
        two = pc.farm_from_layers([FakeLayer("a", attrs={"fazenda": {"A"}}), FakeLayer("b", attrs={"farm": {"B"}})])
        self.assertEqual(two.status, pc.FIELD_AMBIGUOUS)
        self.assertEqual(pc.farm_from_layers([FakeLayer("Fazenda Boa Vista")]).status, pc.FIELD_UNRESOLVED)


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.project = FakeProject()
        self.boundary = _role_layer("01_Limite_Externo", attrs={"fazenda": {"Santa Rita"}})
        self.passes = _role_layer("06_Passadas_Plantio", selected=3, editing=True)
        _field_tree(self.project, "TL-12", {"00_REFERENCIAS": [self.boundary], "10_PLANEJAMENTO": [self.passes]})
        self.other = _role_layer("01_Limite_Externo")
        _field_tree(self.project, "TL-13", {"00_REFERENCIAS": [self.other]})
        self.loose = FakeLayer("pontos_rtk")
        self.project.root.addLayer(self.loose)
        _freeze(self.project)
        self.before = self.project.root.structure()

    def tearDown(self):
        self.assertEqual(self.project.root.structure(), self.before)

    def test_snapshot_from_active_layer(self):
        context = pc.ProjectContextService(self.project, FakeIface(self.passes)).snapshot()
        self.assertTrue(context.project_saved)
        self.assertEqual([item.field_id for item in context.fields], ["TL-12", "TL-13"])
        self.assertEqual((context.field.field_id, context.field.source), ("TL-12", pc.SOURCE_PROJECT_GROUP))
        self.assertEqual(context.active_layer.role, "WORK_PATH")
        self.assertEqual(context.active_layer.selected_count, 3)
        self.assertTrue(context.active_layer.is_editing)
        self.assertEqual(context.farm.name, "Santa Rita")
        self.assertEqual(set(context.field_layer_ids), {self.boundary.id(), self.passes.id()})

    def test_unresolved_layer_requires_explicit_choice(self):
        service = pc.ProjectContextService(self.project, FakeIface(self.loose))
        context = service.snapshot()
        self.assertEqual(context.field.status, pc.FIELD_UNRESOLVED)
        self.assertEqual(
            [value for value, source in context.field.candidates if source == pc.SOURCE_PROJECT_GROUP],
            ["TL-12", "TL-13"],
        )
        with self.assertRaises(ValueError):
            service.set_explicit_field("pontos_rtk")
        self.assertEqual(service.set_explicit_field("FORTSMART - tl-13"), "TL-13")
        chosen = service.snapshot()
        self.assertEqual((chosen.field.field_id, chosen.field.source), ("TL-13", pc.SOURCE_EXPLICIT))
        self.assertEqual(chosen.field_layer_ids, (self.other.id(),))
        service.clear_explicit_field()
        self.assertEqual(service.snapshot().field.status, pc.FIELD_UNRESOLVED)

    def test_explicit_choice_differing_from_active_layer_is_reported(self):
        service = pc.ProjectContextService(self.project, FakeIface(self.passes))
        service.set_explicit_field("TL-13")
        context = service.snapshot()
        self.assertEqual(context.field.field_id, "TL-13")
        self.assertIn(pc.EXPLICIT_FIELD_DIFFERS_FROM_LAYER, _codes(context.diagnostics))

    def test_no_active_layer(self):
        context = pc.ProjectContextService(self.project, FakeIface(None)).snapshot()
        self.assertIsNone(context.active_layer)
        self.assertEqual(context.field.status, pc.FIELD_UNRESOLVED)

    def test_export_diagnostics_use_visibility(self):
        service = pc.ProjectContextService(self.project)
        self.assertNotIn(pc.MULTIPLE_APPLICABLE_BOUNDARIES, _codes(service.export_diagnostics("TL-12")))


class FeatureFlagTest(unittest.TestCase):
    def test_existing_constants_unchanged(self):
        self.assertIs(feature_flags.ENABLE_STRATEGY_ANALYZER, True)
        self.assertIs(feature_flags.SHOW_ROW_PREVIEW, False)

    def test_new_flags_default_off_and_persist(self):
        settings = FakeSettings()
        self.assertEqual(set(feature_flags.persisted_flags(settings).values()), {False})
        feature_flags.set_enabled(feature_flags.ENABLE_AGROCAD_PANEL_V1, True, settings)
        self.assertEqual(settings.values["fortsmart_precision/flags/ENABLE_AGROCAD_PANEL_V1"], True)
        self.assertTrue(feature_flags.is_enabled(feature_flags.ENABLE_AGROCAD_PANEL_V1, settings))
        settings.values["fortsmart_precision/flags/ENABLE_DEM_INSPECTOR_V1"] = "true"
        self.assertTrue(feature_flags.is_enabled(feature_flags.ENABLE_DEM_INSPECTOR_V1, settings))
        settings.values["fortsmart_precision/flags/ENABLE_DEM_INSPECTOR_V1"] = "false"
        self.assertFalse(feature_flags.is_enabled(feature_flags.ENABLE_DEM_INSPECTOR_V1, settings))
        with self.assertRaises(KeyError):
            feature_flags.is_enabled("ENABLE_QUALQUER_COISA", settings)


class GeometryWriteCheckTest(unittest.TestCase):
    def test_classification(self):
        classify = gwc.classify_geometry_write
        self.assertEqual(classify(3, 3), "")
        self.assertEqual(classify(6, 3), "")
        self.assertEqual(classify(3, 6, part_count=1, valid_before=True, valid_after=True), "")
        self.assertEqual(classify(3, 6, part_count=2), gwc.MULTIPART_INTO_SINGLE)
        self.assertEqual(classify(3, 2), gwc.GEOMETRY_FAMILY_MISMATCH)
        self.assertEqual(classify(3, 7), gwc.COLLECTION_INTO_TYPED_TABLE)
        self.assertEqual(classify(6, 3, valid_before=True, valid_after=False), gwc.FORCED_GEOMETRY_INVALID)
        self.assertEqual(classify(0, 2), "")
        self.assertEqual(classify(100, 2), "")

    def test_audit_aggregates_by_code(self):
        audit = gwc.GeometryWriteAudit("22_Zonas_Seguranca", 3)
        audit.observe(3, feature_id=1)
        audit.observe(6, feature_id=2, part_count=2)
        audit.observe(6, feature_id=3, part_count=3)
        self.assertFalse(audit.ok)
        self.assertEqual(audit.counts, {gwc.MULTIPART_INTO_SINGLE: 2})
        (warning,) = audit.warnings()
        self.assertTrue(warning.startswith("MULTIPART_INTO_SINGLE: 2 feicao(oes) em '22_Zonas_Seguranca'"))
        self.assertIn("MultiPolygon em tabela Polygon", warning)


if __name__ == "__main__":
    unittest.main()
