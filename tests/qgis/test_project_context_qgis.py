# -*- coding: utf-8 -*-
"""Etapa 0B: contexto do projeto num QgsProject real e compatibilidade com o Precision Ag."""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from qgis.core import (
    QgsApplication,
    QgsFeature,
    QgsGeometry,
    QgsProject,
    QgsSettings,
    QgsVectorLayer,
)

from plugin.fortsmart_precision import feature_flags
from plugin.fortsmart_precision.core import project_context as pc
from plugin.fortsmart_precision.core.layer_roles import (
    LAYER_ROLES,
    SIMULATION_ROLES,
    definition_for_role,
    set_layer_role_properties,
)
from plugin.fortsmart_precision.core.persistence_manager import FortSmartPersistenceManager
from plugin.fortsmart_precision.gui import layer_tree_organizer as organizer

_APP = None
CRS = "EPSG:31981"
SQUARE = "Polygon((0 0, 100 0, 100 100, 0 100, 0 0))"
TWO_SQUARES = "MultiPolygon(((0 0, 10 0, 10 10, 0 10, 0 0)),((50 50, 60 50, 60 60, 50 60, 50 50)))"
AG_DIR_ENV = "FORTSMART_AG_PLUGIN_DIR"
EXPECTED_ALGORITHMS = {
    "health_check",
    "inspect_input",
    "import_field_boundary",
    "create_parallel_agricultural_lines",
    "create_operation_passes",
    "create_turn_paths",
    "generate_precision_lines",
    "validate_precision_project",
    "create_obstacles",
    "generate_obstacle_avoidance",
    "simulate_obstacle_avoidance",
    "simulate_real_operation",
    "simulate_obstacle_border_cut",
}


def _setup_qgis():
    global _APP
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if QgsApplication.instance() is None:
        _APP = QgsApplication([], True)
        _APP.initQgis()


def _layer(geometry_type, name, wkts, *, crs=CRS, fields=""):
    layer = QgsVectorLayer(f"{geometry_type}?crs={crs}{fields}", name, "memory")
    features = []
    for wkt in wkts:
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt(wkt))
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    return layer


def _role_layer(key, wkts=(SQUARE,), *, catalog=LAYER_ROLES, geometry_type="Polygon", field_name=None, crs=CRS):
    definition = catalog[key]
    layer = _layer(geometry_type, definition.display_name, wkts, crs=crs)
    set_layer_role_properties(layer, definition, field_name=field_name)
    return layer


def _tree_signature(node):
    items = []
    for child in node.children():
        if hasattr(child, "layer") and callable(child.layer):
            items.append(("L", child.layer().id(), child.itemVisibilityChecked()))
        else:
            items.append(("G", child.name(), _tree_signature(child)))
    return items


def _properties(layer):
    return {key: layer.customProperty(key) for key in layer.customPropertyKeys()}


def _ag_plugin_dir():
    candidates = []
    if os.environ.get(AG_DIR_ENV):
        candidates.append(Path(os.environ[AG_DIR_ENV]))
    if os.environ.get("APPDATA"):
        candidates.append(
            Path(os.environ["APPDATA"]) / "QGIS" / "QGIS3" / "profiles" / "default" / "python" / "plugins"
            / "fortsmart_gs3_import"
        )
    return next((path for path in candidates if (path / "field_group_export.py").is_file()), None)


def _import_ag(module):
    """Importa um modulo do Precision Ag so para leitura (sem gravar bytecode no plugin)."""
    plugin_dir = _ag_plugin_dir()
    if plugin_dir is None:
        raise unittest.SkipTest(
            f"Precision Ag nao encontrado: defina {AG_DIR_ENV} com a pasta fortsmart_gs3_import."
        )
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(plugin_dir.parent))
    try:
        return importlib.import_module(f"{plugin_dir.name}.{module}")
    finally:
        sys.path.remove(str(plugin_dir.parent))
        sys.dont_write_bytecode = previous


class _ProjectCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.project = QgsProject.instance()
        self.project.clear()
        self.project.setFileName(str(self.tmp / "fazenda.qgz"))
        self.root = self.project.layerTreeRoot()

    def tearDown(self):
        self.project.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _place(self, layer, field_name, section):
        self.project.addMapLayer(layer, False)
        group = organizer.project_group(self.root, field_name)
        target = organizer.section_group(group, section) if section else group
        organizer.insert_layer_ordered(target, layer)
        return layer


class ProjectContextQgisTest(_ProjectCase):
    def test_snapshot_is_read_only(self):
        boundary = self._place(_role_layer("01_Limite_Externo", field_name="TL-12"), "TL-12", "00_REFERENCIAS")
        passes = self._place(
            _role_layer("06_Passadas_Plantio", ("LineString(0 0, 100 100)",), geometry_type="LineString",
                        field_name="TL-12"),
            "TL-12",
            "10_PLANEJAMENTO",
        )
        passes.selectByIds([next(passes.getFeatures()).id()])
        loose = _layer("Polygon", "01_Limite_Externo", [SQUARE])
        self.project.addMapLayer(loose)
        tree_before = _tree_signature(self.root)
        properties_before = {layer.id(): _properties(layer) for layer in self.project.mapLayers().values()}
        layers_before = set(self.project.mapLayers())

        service = pc.ProjectContextService(self.project)
        context = service.snapshot(passes)
        self.assertEqual(context.field.field_id, "TL-12")
        self.assertEqual(context.active_layer.role, "WORK_PATH")
        self.assertEqual(context.active_layer.selected_count, 1)
        self.assertEqual(context.active_layer.crs.authid, CRS)
        self.assertTrue(context.active_layer.crs.is_metric)
        self.assertEqual(context.active_layer.ag_group_name, "FORTSMART - TL-12")
        self.assertEqual(set(context.field_layer_ids), {boundary.id(), passes.id()})

        unresolved = service.snapshot(loose)
        self.assertEqual(unresolved.field.status, pc.FIELD_UNRESOLVED)
        with self.assertRaises(ValueError):
            service.set_explicit_field(loose.name())
        service.describe_layer(loose)
        service.export_diagnostics("TL-12")

        self.assertEqual(_tree_signature(self.root), tree_before)
        self.assertEqual({layer.id(): _properties(layer) for layer in self.project.mapLayers().values()},
                         properties_before)
        self.assertEqual(set(self.project.mapLayers()), layers_before)
        self.assertIsNone(self.root.findGroup("FORTSMART - 01_Limite_Externo"))
        self.assertFalse((self.tmp / "fortsmart_data").exists())

    def test_geographic_layer_is_diagnosed(self):
        layer = self._place(
            _role_layer("01_Limite_Externo", ("Polygon((-54 -12, -53.99 -12, -53.99 -11.99, -54 -12))",),
                        crs="EPSG:4674"),
            "TL-1",
            "00_REFERENCIAS",
        )
        context = pc.ProjectContextService(self.project).describe_layer(layer)
        self.assertTrue(context.crs.is_geographic)
        self.assertFalse(context.crs.is_metric)
        self.assertIn(pc.CRS_GEOGRAPHIC, {item.code for item in context.diagnostics})

    def test_real_reprojected_copy_loses_metadata_and_is_diagnosed(self):
        from plugin.fortsmart_precision.gui.crs_reproject_service import reproject_vector_layer

        source = _layer(
            "Polygon",
            "01_Limite_Externo",
            ["Polygon((-54 -12, -53.99 -12, -53.99 -11.99, -54 -12))"],
            crs="EPSG:4674",
            fields="&field=fortsmart_role:string",
        )
        source.dataProvider().changeAttributeValues({next(source.getFeatures()).id(): {0: "EXTERNAL_BOUNDARY"}})
        set_layer_role_properties(source, LAYER_ROLES["01_Limite_Externo"], field_name="TL-3")
        self._place(source, "TL-3", "00_REFERENCIAS")
        source_properties = _properties(source)
        copy = reproject_vector_layer(source, CRS)
        self.project.addMapLayer(copy, False)
        organizer.section_group(organizer.project_group(self.root, "TL-3"), "00_REFERENCIAS").addLayer(copy)

        context = pc.ProjectContextService(self.project).describe_layer(copy)
        self.assertEqual(copy.name(), f"01_Limite_Externo ({CRS})")
        self.assertEqual(context.reprojection.source_layer_ids, (source.id(),))
        self.assertFalse(context.reprojection.has_fortsmart_metadata)
        self.assertEqual(context.reprojection.attribute_roles, ("EXTERNAL_BOUNDARY",))
        codes = {item.code for item in context.diagnostics}
        self.assertIn(pc.REPROJECTED_COPY_WITHOUT_METADATA, codes)
        self.assertFalse(context.is_generated)
        self.assertEqual(_properties(source), source_properties)
        self.assertEqual(copy.customPropertyKeys(), [])
        self.assertIn(
            pc.MULTIPLE_APPLICABLE_BOUNDARIES,
            {item.code for item in pc.ProjectContextService(self.project).export_diagnostics("TL-3")},
        )


class AgCompatibilityQgisTest(_ProjectCase):
    def test_field_grouping_matches_precision_ag(self):
        field_group_export = _import_ag("field_group_export")
        boundary = self._place(_role_layer("01_Limite_Externo"), "TL-12", "00_REFERENCIAS")
        preview = _role_layer("SIM_WORK_LINES", ("LineString(0 0, 1 1)",), catalog=SIMULATION_ROLES,
                              geometry_type="LineString")
        self.project.addMapLayer(preview, False)
        organizer.preview_group(organizer.project_group(self.root, "TL-12")).addLayer(preview)
        lone_preview = _role_layer("SIM_WORK_LINES", ("LineString(0 0, 1 1)",), catalog=SIMULATION_ROLES,
                                   geometry_type="LineString")
        self.project.addMapLayer(lone_preview, False)
        organizer.preview_group(organizer.project_group(self.root, "TL-9")).addLayer(lone_preview)
        loose = _layer("Polygon", "01_Limite_Externo", [SQUARE])
        self.project.addMapLayer(loose)
        imported = self.root.addGroup("FortSmart GS3")
        todos = _layer("Polygon", "Todos — Limites", [SQUARE])
        self.project.addMapLayer(todos, False)
        imported.addLayer(todos)
        tl = _layer("Polygon", "Limite", [SQUARE])
        self.project.addMapLayer(tl, False)
        imported.addGroup("Fazenda Exemplo").addGroup("TL-12").addLayer(tl)
        user = _layer("Polygon", "Mapa solo", [SQUARE])
        self.project.addMapLayer(user, False)
        self.root.addGroup("Mapas").addLayer(user)

        for layer in (boundary, preview, lone_preview, loose, todos, tl, user):
            expected = field_group_export._field_node(layer, self.root)
            found = pc.ag_field_group(self.root, layer)
            self.assertEqual(
                expected.name() if expected is not None else None,
                found.name() if found is not None else None,
                layer.name(),
            )
        groups = {group.label for group in field_group_export.group_export_layers(
            [boundary, todos, loose], self.root)}
        self.assertIn("FORTSMART - TL-12", groups)
        self.assertIn("Sem grupo: Todos — Limites", groups)
        self.assertIn("Sem grupo: 01_Limite_Externo", groups)

    def test_known_roles_match_precision_ag(self):
        canonical_project = _import_ag("canonical_project")
        self.assertEqual(set(canonical_project.ROLE_KIND_MAP), set(pc.AG_KNOWN_ROLES))
        for key, definition in LAYER_ROLES.items():
            self.assertEqual(canonical_project.INTERNAL_KEY_ROLES.get(key.upper()), definition.role, key)


class PersistenceGeometryCheckQgisTest(_ProjectCase):
    def _persist_twice(self, field_name, *, flag_on):
        definition = definition_for_role("SAFETY_ZONE")
        manager = FortSmartPersistenceManager(self.project)
        first = _layer("Polygon", definition.display_name, [SQUARE])
        manager.persist_layer(first, definition, field_name)
        second = _layer("MultiPolygon", definition.display_name, [TWO_SQUARES])
        precheck = manager.diagnose_geometry_write(second, definition, field_name)
        path = manager.get_field_storage_path(field_name)
        self.assertEqual(manager.table_feature_count(path, definition.display_name), 1)
        enabled = (lambda name, settings=None: name == feature_flags.ENABLE_GPKG_GEOMETRY_CHECK_V1) if flag_on \
            else (lambda name, settings=None: False)
        with mock.patch.object(feature_flags, "is_enabled", enabled):
            result = manager.persist_layer(second, definition, field_name)
        stored = sorted(feature.geometry().asWkt(3) for feature in result.layer.getFeatures())
        return precheck, result.warnings, stored

    def test_check_only_adds_warnings(self):
        precheck_off, warnings_off, stored_off = self._persist_twice("TL-7", flag_on=False)
        precheck_on, warnings_on, stored_on = self._persist_twice("TL-70", flag_on=True)
        self.assertEqual(warnings_off, [])
        self.assertEqual(stored_on, stored_off)
        self.assertEqual(len(warnings_on), 1)
        self.assertTrue(warnings_on[0].startswith("MULTIPART_INTO_SINGLE: 1 feicao(oes) em '22_Zonas_Seguranca'"))
        self.assertEqual(precheck_off, precheck_on)
        self.assertTrue(precheck_on[0].startswith("MULTIPART_INTO_SINGLE: 1 feicao(oes) em '22_Zonas_Seguranca'"))

    def test_precheck_without_table_is_empty(self):
        definition = definition_for_role("SAFETY_ZONE")
        manager = FortSmartPersistenceManager(self.project)
        layer = _layer("MultiPolygon", definition.display_name, [TWO_SQUARES])
        self.assertEqual(manager.diagnose_geometry_write(layer, definition, "TL-8"), [])
        self.assertFalse((self.tmp / "fortsmart_data").exists())


class FlagSettingsQgisTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()

    def test_flags_persist_in_qgs_settings(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            from qgis.PyQt.QtCore import QSettings

            settings = QgsSettings(str(tmp / "flags.ini"), QSettings.IniFormat)
            self.assertEqual(set(feature_flags.persisted_flags(settings).values()), {False})
            feature_flags.set_enabled(feature_flags.ENABLE_LAYER_ORGANIZER_V1, True, settings)
            settings.sync()
            reread = QgsSettings(str(tmp / "flags.ini"), QSettings.IniFormat)
            self.assertTrue(feature_flags.is_enabled(feature_flags.ENABLE_LAYER_ORGANIZER_V1, reread))
            self.assertFalse(feature_flags.is_enabled(feature_flags.ENABLE_AGROCAD_PANEL_V1, reread))
            del settings, reread
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ProcessingProviderQgisTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()

    def test_provider_keeps_the_13_algorithms(self):
        from plugin.fortsmart_precision.provider import FortSmartProvider

        provider = FortSmartProvider()
        provider.refreshAlgorithms()
        self.assertEqual({algorithm.name() for algorithm in provider.algorithms()}, EXPECTED_ALGORITHMS)
        self.assertEqual(len(provider.algorithms()), 13)


if __name__ == "__main__":
    unittest.main()
