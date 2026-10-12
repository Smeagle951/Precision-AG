# -*- coding: utf-8 -*-

import re
import unittest

from plugin.fortsmart_precision.core.layer_roles import (
    CANONICAL_ROLE_ORDER,
    EMPTY_ROLE_LAYER,
    HEADLAND_TURN_ROLE,
    LAYER_ROLES,
    ROLE_LAYER_MISSING,
    ROLE_LAYER_OK,
    SCHEMA_VERSION,
    SECTION_ORDER,
    SIMULATION_ROLES,
    SOURCE_DISPLAY_NAME,
    SOURCE_HEURISTIC,
    SOURCE_INTERNAL_KEY,
    SOURCE_LEGACY_ALIAS,
    SOURCE_ROLE,
    all_role_definitions,
    canonical_field_name,
    canonical_project_group_name,
    classify_layer,
    definition_for_key,
    definition_for_role,
    find_layer_by_role,
    format_normalization_report,
    is_generated_layer,
    is_temporary_preview,
    layer_field_id,
    layer_inventory,
    layer_role,
    layer_role_definition,
    mark_temporary_preview,
    normalization_summary,
    role_layer_status,
    role_order_index,
    section_order_index,
    feature_identity,
    format_storage_report,
    is_persisted_layer,
    role_field_schema,
    set_layer_role_properties,
    simulation_role_definition,
    storage_kind,
)


class Layer:
    def __init__(self, name, role="", features=1, **properties):
        self._name = name
        self._features = features
        self.properties = dict(properties)
        if role:
            self.properties["fortsmart_role"] = role

    def name(self):
        return self._name

    def featureCount(self):
        return self._features

    def customProperty(self, key, default=""):
        return self.properties.get(key, default)

    def setCustomProperty(self, key, value):
        self.properties[key] = value


class CatalogTest(unittest.TestCase):
    def test_generator_roles_are_canonical(self):
        self.assertEqual(layer_role_definition("01_Limite_Externo").role, "EXTERNAL_BOUNDARY")
        self.assertEqual(layer_role_definition("06_Passadas_Plantio").display_name, "12_Passadas_Plantio")
        self.assertEqual(layer_role_definition("13_Shutoff").section, "30_OPERACAO")
        self.assertEqual(layer_role_definition("11_Desvios_Obstaculos").display_name, "23_Desvios_Obstaculos")

    def test_internal_keys_are_kept_and_recorded(self):
        for key, definition in {**LAYER_ROLES, **SIMULATION_ROLES}.items():
            self.assertEqual(definition.key, key)
            self.assertIs(definition_for_key(key), definition)
        self.assertEqual(HEADLAND_TURN_ROLE.key, "HEADLAND_TURN")
        self.assertIs(definition_for_key("HEADLAND_TURN"), HEADLAND_TURN_ROLE)
        self.assertIsNone(definition_for_key("nao_existe"))

    def test_simulation_uses_operation_and_simulation_ranges(self):
        expected = {
            "SIM_WORK_LINES": ("31_Linhas_Finais", "30_OPERACAO", "FINAL_WORK_PATH"),
            "SIM_WORK_OFF": ("32_Work_Off", "30_OPERACAO", "WORK_OFF"),
            "SIM_WORK_ON": ("33_Work_On", "30_OPERACAO", "WORK_ON"),
            "SIM_COVERAGE": ("41_Cobertura", "40_SIMULACAO", "COVERAGE"),
            "SIM_BORDER_OVERLAPS": ("42_Remonte", "40_SIMULACAO", "OVERLAP"),
            "SIM_BORDER_GAPS": ("43_Falha", "40_SIMULACAO", "GAP"),
            "SIM_MACHINE_PATH": ("44_Trajetoria_Maquina", "40_SIMULACAO", "MACHINE_PATH"),
            "SIM_MAIN_WORK_AREA": ("45_Faixa_Implemento", "40_SIMULACAO", "IMPLEMENT_SWATH"),
            "SIM_BORDER_COVERAGE": ("46_Faixa_Bordadura", "40_SIMULACAO", "HEADLAND_SWATH"),
        }
        for key, (display, section, role) in expected.items():
            definition = simulation_role_definition(key)
            self.assertEqual((definition.display_name, definition.section, definition.role), (display, section, role))

    def test_display_name_and_role_are_one_to_one(self):
        by_display, by_role = {}, {}
        for definition in all_role_definitions():
            by_display.setdefault(definition.display_name, set()).add(definition.role)
            by_role.setdefault(definition.role, set()).add(definition.display_name)
        self.assertEqual({name: roles for name, roles in by_display.items() if len(roles) > 1}, {})
        self.assertEqual({role: names for role, names in by_role.items() if len(names) > 1}, {})

    def test_numeric_prefix_is_not_shared_between_roles(self):
        prefixes = {}
        for definition in all_role_definitions():
            prefix = re.match(r"(\d+)_", definition.display_name).group(1)
            prefixes.setdefault(prefix, set()).add(definition.role)
        self.assertEqual({prefix: roles for prefix, roles in prefixes.items() if len(roles) > 1}, {})

    def test_display_names_have_no_derived_suffix(self):
        for definition in all_role_definitions():
            self.assertNotIn(" - ", definition.display_name)
            self.assertNotRegex(definition.display_name, r"_\d+$")

    def test_every_section_and_role_has_a_fixed_position(self):
        for definition in all_role_definitions():
            self.assertIn(definition.section, SECTION_ORDER)
            self.assertIn(definition.role, CANONICAL_ROLE_ORDER)
        self.assertEqual(len(CANONICAL_ROLE_ORDER), len(set(CANONICAL_ROLE_ORDER)))
        self.assertLess(role_order_index("EXTERNAL_BOUNDARY"), role_order_index("AB_LINE"))
        self.assertLess(role_order_index("WORK_PATH"), role_order_index("HEADLAND_TURN"))
        self.assertEqual(role_order_index("DESCONHECIDO"), len(CANONICAL_ROLE_ORDER))
        self.assertLess(section_order_index("00_REFERENCIAS"), section_order_index("90_AUXILIARES"))
        self.assertEqual(section_order_index("MEU_GRUPO"), len(SECTION_ORDER))

    def test_definition_for_role_prefers_generator_catalog(self):
        self.assertEqual(definition_for_role("FINAL_WORK_PATH").key, "12_Linhas_Finais")
        self.assertIs(definition_for_role("HEADLAND_TURN"), HEADLAND_TURN_ROLE)
        self.assertIsNone(definition_for_role("NADA"))


class ResolverTest(unittest.TestCase):
    def test_find_layer_by_role_prefers_role_over_name(self):
        by_name = Layer("12_Passadas_Plantio")
        by_role = Layer("minhas passadas", "WORK_PATH")
        copy = Layer("12_Passadas_Plantio_2")
        self.assertIs(find_layer_by_role([by_name, by_role], "WORK_PATH", names=("12_Passadas_Plantio",)), by_role)
        self.assertIs(find_layer_by_role([by_name], "WORK_PATH", names=("12_Passadas_Plantio",)), by_name)
        self.assertIs(find_layer_by_role([copy], names=("12_Passadas_Plantio",)), copy)
        self.assertIsNone(find_layer_by_role([Layer("outra")], "WORK_PATH", names=("12_Passadas_Plantio",)))
        self.assertEqual(layer_role(by_role), "WORK_PATH")
        self.assertEqual(layer_role(object()), "")

    def test_renamed_layer_keeps_role(self):
        passes = Layer("Passadas de Plantio", "WORK_PATH")
        boundary = Layer("Limite do talhao 12", "EXTERNAL_BOUNDARY")
        others = [Layer("12_Passadas_Plantio_antiga", "FINAL_WORK_PATH"), Layer("Boundary")]
        self.assertIs(find_layer_by_role([*others, passes], "WORK_PATH"), passes)
        self.assertIs(find_layer_by_role([*others, boundary], "EXTERNAL_BOUNDARY"), boundary)

    def test_fallback_order_role_internal_alias_display_heuristic(self):
        self.assertEqual(classify_layer(Layer("x", "WORK_PATH")), ("WORK_PATH", SOURCE_ROLE))
        internal = Layer("qualquer", **{"fortsmart_internal_key": "06_Passadas_Plantio"})
        self.assertEqual(classify_layer(internal), ("WORK_PATH", SOURCE_INTERNAL_KEY))
        legacy_mark = Layer("qualquer", **{"fortsmart_precision/preview_layer": "12_Linhas_Finais"})
        self.assertEqual(classify_layer(legacy_mark), ("FINAL_WORK_PATH", SOURCE_INTERNAL_KEY))
        self.assertEqual(classify_layer(Layer("06_Passadas_Plantio")), ("WORK_PATH", SOURCE_LEGACY_ALIAS))
        self.assertEqual(classify_layer(Layer("Passadas Plantio")), ("WORK_PATH", SOURCE_LEGACY_ALIAS))
        self.assertEqual(classify_layer(Layer("Boundary — talhao_12")), ("EXTERNAL_BOUNDARY", SOURCE_LEGACY_ALIAS))
        self.assertEqual(classify_layer(Layer("Limite Externo")), ("EXTERNAL_BOUNDARY", SOURCE_LEGACY_ALIAS))
        self.assertEqual(classify_layer(Layer("43_Falha")), ("GAP", SOURCE_DISPLAY_NAME))
        self.assertEqual(classify_layer(Layer("12_Passadas_Plantio (84)")), ("WORK_PATH", SOURCE_DISPLAY_NAME))
        self.assertEqual(
            classify_layer(Layer("_fortsmart_workspace_05_Passadas (12)")), ("GUIDANCE_TRACK", SOURCE_LEGACY_ALIAS)
        )
        self.assertEqual(classify_layer(Layer("minhas_linhas_finais_v2")), ("FINAL_WORK_PATH", SOURCE_HEURISTIC))
        self.assertEqual(classify_layer(Layer("marcacao_35")), ("", ""))
        self.assertEqual(classify_layer(Layer("Reta A")), ("", ""))

    def test_legacy_layer_without_role_is_found_by_fallback(self):
        legacy = Layer("06_Passadas_Plantio")
        self.assertIs(find_layer_by_role([Layer("marcacao_35"), legacy], "WORK_PATH"), legacy)
        boundary = Layer("Boundary — talhao_12 (EPSG:31981)")
        self.assertIs(find_layer_by_role([boundary], "EXTERNAL_BOUNDARY"), boundary)

    def test_heuristic_never_overrides_a_more_specific_classification(self):
        detour = Layer("23_Desvios_Obstaculos")
        self.assertEqual(classify_layer(detour)[0], "OBSTACLE_DETOUR")
        self.assertIsNone(find_layer_by_role([detour], "OBSTACLE"))
        self.assertEqual(find_layer_by_role([detour, Layer("obstaculos_campo")], "OBSTACLE").name(), "obstaculos_campo")

    def test_layer_with_other_role_is_not_taken_by_name(self):
        final = Layer("12_Passadas_Plantio", "FINAL_WORK_PATH")
        self.assertIsNone(find_layer_by_role([final], "WORK_PATH", names=("12_Passadas_Plantio",)))

    def test_non_empty_skips_empty_role_layer(self):
        empty_final = Layer("31_Linhas_Finais", "FINAL_WORK_PATH", features=0)
        plan = Layer("12_Passadas_Plantio", "WORK_PATH", features=84)
        self.assertIsNone(find_layer_by_role([empty_final, plan], "FINAL_WORK_PATH", non_empty=True))
        self.assertIs(find_layer_by_role([empty_final, plan], "FINAL_WORK_PATH"), empty_final)
        self.assertIs(find_layer_by_role([empty_final, plan], "FINAL_WORK_PATH", "WORK_PATH", non_empty=True), plan)

    def test_role_layer_status(self):
        self.assertEqual(role_layer_status(None), ROLE_LAYER_MISSING)
        self.assertEqual(role_layer_status(Layer("a", "WORK_PATH", features=0)), EMPTY_ROLE_LAYER)
        self.assertEqual(role_layer_status(Layer("a", "WORK_PATH", features=3)), ROLE_LAYER_OK)


class ProjectGroupTest(unittest.TestCase):
    def test_project_group_is_derived_from_field(self):
        self.assertEqual(canonical_project_group_name("Boundary — talhao_11 (EPSG:31981)"), "FORTSMART - talhao_11")
        self.assertEqual(canonical_project_group_name("Boundary - talhao_12"), "FORTSMART - talhao_12")
        self.assertEqual(canonical_project_group_name("Boundary – talhao_12"), "FORTSMART - talhao_12")
        self.assertEqual(canonical_project_group_name("  talhao   12  "), "FORTSMART - talhao 12")
        self.assertEqual(canonical_project_group_name(None), "FORTSMART - PROJETO")

    def test_group_name_is_idempotent(self):
        name = canonical_project_group_name("Boundary — talhao_12 (EPSG:31981)")
        self.assertEqual(canonical_project_group_name(name), name)
        self.assertEqual(canonical_field_name(name), "talhao_12")


class MetadataTest(unittest.TestCase):
    def test_role_properties_record_origin(self):
        layer = Layer("12_Passadas_Plantio")
        set_layer_role_properties(
            layer, layer_role_definition("06_Passadas_Plantio"), field_name="Boundary — talhao_12 (EPSG:31981)"
        )
        props = layer.properties
        self.assertEqual(props["fortsmart_role"], "WORK_PATH")
        self.assertEqual(props["fortsmart_precision/role"], "WORK_PATH")
        self.assertEqual(props["fortsmart_section"], "10_PLANEJAMENTO")
        self.assertEqual(props["fortsmart_internal_key"], "06_Passadas_Plantio")
        self.assertEqual(props["fortsmart_project"], "FORTSMART - talhao_12")
        self.assertEqual(props["fortsmart_field_id"], "talhao_12")
        self.assertEqual(props["fortsmart_schema_version"], SCHEMA_VERSION)
        self.assertIs(props["fortsmart_generated"], True)
        self.assertTrue(is_generated_layer(layer))
        self.assertEqual(layer_field_id(layer), "talhao_12")

    def test_not_generated_layer_and_temporary_preview(self):
        user = Layer("12_Passadas_Plantio")
        set_layer_role_properties(user, layer_role_definition("06_Passadas_Plantio"), generated=False)
        self.assertFalse(is_generated_layer(user))
        self.assertNotIn("fortsmart_field_id", user.properties)
        self.assertTrue(is_generated_layer(Layer("x", **{"fortsmart_generated": "true"})))
        self.assertTrue(is_generated_layer(Layer("_fortsmart_workspace_05_Passadas")))
        self.assertTrue(is_generated_layer(Layer("x", **{"fortsmart_precision/preview_layer": "05_Passadas"})))
        preview = Layer("31_Linhas_Finais")
        self.assertFalse(is_temporary_preview(preview))
        mark_temporary_preview(preview)
        self.assertTrue(is_temporary_preview(preview))
        self.assertTrue(is_temporary_preview(Layer("x", fortsmart_temporary=True)))
        self.assertTrue(is_temporary_preview(Layer("PREVIEW_RETA 37°", fortsmart_preview="true")))
        self.assertFalse(is_temporary_preview(Layer("x", fortsmart_preview="false")))

    def test_legacy_role_alias_is_resolved(self):
        old = Layer("43_Falha", role="HEADLAND_GAP")
        self.assertEqual(layer_role(old), "GAP")
        self.assertIs(find_layer_by_role([old], "GAP"), old)

    def test_storage_flags(self):
        class MemoryLayer(Layer):
            @staticmethod
            def providerType():
                return "memory"

        memory = MemoryLayer("12_Passadas_Plantio")
        set_layer_role_properties(memory, layer_role_definition("06_Passadas_Plantio"), field_name="talhao_12")
        self.assertEqual(storage_kind(memory), "memory")
        self.assertIs(memory.properties["fortsmart_persisted"], False)
        self.assertFalse(is_persisted_layer(memory))
        persisted = Layer("x", fortsmart_storage="geopackage", fortsmart_persisted="true")
        self.assertEqual(storage_kind(persisted), "geopackage")
        self.assertTrue(is_persisted_layer(persisted))
        self.assertEqual(storage_kind(Layer("externa")), "external")


class FeatureSchemaTest(unittest.TestCase):
    def test_role_field_schema(self):
        names = lambda role: [name for name, _kind in role_field_schema(role)]
        self.assertEqual(names("WORK_PATH"), ["fortsmart_role", "field_id", "source_id", "line_id", "pass_number"])
        self.assertEqual(
            names("FINAL_WORK_PATH")[-2:], ["parent_line_id", "segment_index"]
        )
        self.assertEqual(names("WORK_OFF")[-3:], ["line_id", "station", "obstacle_id"])
        self.assertEqual(names("HEADLAND_TURN")[-4:], ["turn_id", "from_pass", "to_pass", "turn_type"])
        self.assertEqual(names("COVERAGE"), ["fortsmart_role", "field_id", "source_id"])

    def test_identity_derives_only_missing_values(self):
        derived = feature_identity("WORK_PATH", {"line_number": 7}, field_id="talhao_12", feature_id=3)
        self.assertEqual(derived, {
            "fortsmart_role": "WORK_PATH", "field_id": "talhao_12", "source_id": "L0007",
            "line_id": "L0007", "pass_number": 7,
        })
        kept = feature_identity(
            "WORK_PATH", {"line_id": "X9", "pass_number": 2, "source_id": "orig"}, field_id="t", feature_id=1
        )
        self.assertEqual(kept, {"fortsmart_role": "WORK_PATH", "field_id": "t"})

    def test_segment_identity_uses_parent_and_index(self):
        derived = feature_identity(
            "FINAL_WORK_PATH",
            {"line_number": 3, "parent_line_id": "L0003", "segment_index": 2},
            field_id="t", feature_id=10,
        )
        self.assertEqual(derived["line_id"], "L0003")
        self.assertEqual(derived["source_id"], "L0003:2")
        self.assertNotIn("segment_index", derived)

    def test_events_turns_and_fallback_ids(self):
        event = feature_identity("WORK_OFF", {"pass_id": "L0004", "station_m": 12.5}, field_id="t", feature_id=1)
        self.assertEqual((event["line_id"], event["station"]), ("L0004", 12.5))
        turn = feature_identity("HEADLAND_TURN", {"turn_id": "T1", "from_pass": 1, "to_pass": 2},
                                field_id="t", feature_id=5)
        self.assertEqual(turn["source_id"], "T1")
        self.assertNotIn("turn_type", turn)
        area = feature_identity("COVERAGE", {"classe": "COBERTURA"}, field_id="t", feature_id=4)
        self.assertEqual(area, {"fortsmart_role": "COVERAGE", "field_id": "t", "source_id": "COVERAGE:4"})

    def test_null_values_count_as_missing(self):
        class Null:
            @staticmethod
            def isNull():
                return True

        derived = feature_identity("WORK_PATH", {"line_id": Null(), "line_number": 1}, field_id="t", feature_id=1)
        self.assertEqual(derived["line_id"], "L0001")


class StorageReportTest(unittest.TestCase):
    def test_report_groups_by_field(self):
        text = format_storage_report([
            {"field_id": "talhao_12", "name": "12_Passadas_Plantio", "features": 84, "status": "OK"},
            {"field_id": "talhao_12", "name": "31_Linhas_Finais", "features": 5, "status": "KEPT_PREVIOUS",
             "message": "Resultado vazio. A camada persistida anterior foi mantida."},
            {"field_id": "talhao_13", "name": "16_Manobras_Cabeceira", "features": 0,
             "status": "GPKG_WRITE_FAILED", "message": "Não foi possível salvar 16_Manobras_Cabeceira."},
        ], ignored_previews=3)
        self.assertTrue(text.startswith("FORTSMART STORAGE REPORT"))
        self.assertIn("Talhão: talhao_12", text)
        self.assertIn("12_Passadas_Plantio: 84 feições — MEMORY → GPKG — OK", text)
        self.assertIn("Talhão: talhao_13", text)
        self.assertIn("Preview: 3 ignorado(s)", text)
        self.assertIn("Status: 2 camada(s) persistida(s), 1 erro(s)", text)


class ReportTest(unittest.TestCase):
    def test_inventory_and_summary(self):
        generated = {"fortsmart_generated": True, "fortsmart_field_id": "talhao_12"}
        layers = [
            Layer("12_Passadas_Plantio", "WORK_PATH", features=84, **generated),
            Layer("12_Passadas_Plantio_2", "WORK_PATH", features=84, **generated),
            Layer("01_Limite_Externo", "EXTERNAL_BOUNDARY", features=0, **generated),
            Layer("Boundary — talhao_12"),
            Layer("marcacao_35"),
            Layer("31_Linhas_Finais", "FINAL_WORK_PATH", features=5, fortsmart_temporary_preview=True, **generated),
        ]
        entries = layer_inventory(layers)
        self.assertEqual(entries[2]["status"], EMPTY_ROLE_LAYER)
        self.assertEqual(entries[3]["source"], SOURCE_LEGACY_ALIAS)
        summary = normalization_summary(entries)
        self.assertEqual(summary["fortsmart_layers"], 4)
        self.assertEqual(summary["legacy_aliases"], 1)
        self.assertEqual(summary["empty_layers"], ["01_Limite_Externo"])
        self.assertEqual(summary["duplicated_roles"], ["WORK_PATH (talhao_12)"])
        self.assertEqual(summary["external_layers"], ["Boundary — talhao_12", "marcacao_35"])
        text = format_normalization_report(summary, moved=("Boundary — talhao_12",))
        self.assertIn("Camadas FortSmart normalizadas: 4", text)
        self.assertIn("EMPTY_ROLE_LAYER", text)
        self.assertIn("Camadas movidas: 1", text)
        self.assertIn("WORK_PATH (talhao_12)", text)


if __name__ == "__main__":
    unittest.main()
