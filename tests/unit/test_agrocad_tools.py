# -*- coding: utf-8 -*-
"""Etapa 0D: catalogo de ferramentas do painel AgroCAD (sem QGIS)."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core import agrocad_tools as tools
from plugin.fortsmart_precision.core.agrocad_tools import LayerFacts, tool_by_key, tool_state

NO_LAYER = LayerFacts()
VECTOR = LayerFacts(present=True, is_vector=True)
EDITING = LayerFacts(present=True, is_vector=True, is_editable=True)
RASTER = LayerFacts(present=True, is_vector=False)
PLUGIN_KEYS = {
    tools.PLUGIN_WORKSPACE,
    tools.PLUGIN_HEADLAND_TURNS,
    tools.PLUGIN_STRATEGY_ANALYZER,
    tools.PLUGIN_OBSTACLE_DETOUR,
    tools.PLUGIN_LINE_CUT,
    tools.PLUGIN_OPERATION_SIMULATOR,
    tools.PLUGIN_COVERAGE_XRAY,
    tools.PLUGIN_EXPORT_READINESS,
    tools.PLUGIN_CRS_CONVERTER,
}


class CatalogTest(unittest.TestCase):
    def test_keys_are_unique_and_every_section_has_tools(self):
        keys = [tool.key for tool in tools.TOOLS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual([code for code, _ in tools.SECTIONS], ["EDITOR", "OBSTACLES", "TERRAIN", "PLANNING"])
        for section, _label in tools.SECTIONS:
            self.assertTrue(tools.tools_for(section), section)

    def test_plugin_tools_point_only_to_existing_menu_actions(self):
        targets = {tool.target for tool in tools.TOOLS if tool.source == tools.SOURCE_PLUGIN}
        self.assertEqual(targets, PLUGIN_KEYS)
        self.assertFalse({"organize_layers", "persist_layers"} & targets)

    def test_native_tools_use_qgis_interface_actions(self):
        for tool in tools.TOOLS:
            if tool.source == tools.SOURCE_NATIVE:
                self.assertTrue(tool.target.startswith("action"), tool.key)

    def test_terrain_stays_unavailable_until_0f(self):
        for tool in tools.tools_for(tools.SECTION_TERRAIN):
            self.assertEqual(tool.source, tools.SOURCE_UNAVAILABLE)
            state = tool_state(tool, available=True, facts=EDITING)
            self.assertFalse(state.enabled)
            self.assertTrue(state.reason)

    def test_merge_is_not_exposed_without_a_stable_native_method(self):
        self.assertEqual(tool_by_key("merge_features").source, tools.SOURCE_UNAVAILABLE)
        self.assertIsNone(tool_by_key("simplify"))


class ToolStateTest(unittest.TestCase):
    def test_plugin_tools_do_not_depend_on_the_active_layer(self):
        tool = tool_by_key("obstacle_detour")
        self.assertTrue(tool_state(tool, available=True, facts=NO_LAYER).enabled)
        missing = tool_state(tool, available=False, facts=EDITING)
        self.assertFalse(missing.enabled)
        self.assertIn("plugin", missing.reason)

    def test_missing_native_action_is_reported(self):
        state = tool_state(tool_by_key("select"), available=False, facts=VECTOR)
        self.assertFalse(state.enabled)
        self.assertIn("nativa", state.reason)

    def test_vector_requirement(self):
        tool = tool_by_key("select")
        self.assertFalse(tool_state(tool, available=True, facts=NO_LAYER).enabled)
        self.assertFalse(tool_state(tool, available=True, facts=RASTER).enabled)
        self.assertTrue(tool_state(tool, available=True, facts=VECTOR).enabled)

    def test_editing_requirement(self):
        tool = tool_by_key("vertex_tool")
        blocked = tool_state(tool, available=True, facts=VECTOR)
        self.assertFalse(blocked.enabled)
        self.assertIn("edição", blocked.reason)
        self.assertTrue(tool_state(tool, available=True, facts=EDITING).enabled)

    def test_undo_and_redo_follow_the_layer_stack(self):
        undo, redo = tool_by_key("undo"), tool_by_key("redo")
        self.assertFalse(tool_state(undo, available=True, facts=EDITING).enabled)
        can_undo = LayerFacts(present=True, is_vector=True, is_editable=True, can_undo=True)
        self.assertTrue(tool_state(undo, available=True, facts=can_undo).enabled)
        self.assertFalse(tool_state(redo, available=True, facts=can_undo).enabled)
        can_redo = LayerFacts(present=True, is_vector=True, is_editable=True, can_redo=True)
        self.assertTrue(tool_state(redo, available=True, facts=can_redo).enabled)


if __name__ == "__main__":
    unittest.main()
