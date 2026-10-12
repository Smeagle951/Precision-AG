# -*- coding: utf-8 -*-
"""Catalogo das ferramentas do painel AgroCAD (sem Qt).

Cada ferramenta so aciona o que ja existe: uma acao nativa do QGIS, uma acao do
menu do plugin (mesma QAction, mesmo codigo) ou a pilha de desfazer da camada.
O que ainda nao tem integracao confiavel fica listado como indisponivel.
"""

from __future__ import annotations

from dataclasses import dataclass

SECTION_EDITOR = "EDITOR"
SECTION_OBSTACLES = "OBSTACLES"
SECTION_TERRAIN = "TERRAIN"
SECTION_PLANNING = "PLANNING"
SECTIONS = (
    (SECTION_EDITOR, "Editor"),
    (SECTION_OBSTACLES, "Obstáculos"),
    (SECTION_TERRAIN, "Terreno"),
    (SECTION_PLANNING, "Planejamento"),
)

SOURCE_NATIVE = "native"
SOURCE_PLUGIN = "plugin"
SOURCE_PANEL = "panel"
SOURCE_UNAVAILABLE = "unavailable"

REQUIRES_VECTOR = "vector"
REQUIRES_EDITABLE = "editable"
REQUIRES_UNDO = "undo"
REQUIRES_REDO = "redo"

PANEL_UNDO = "undo"
PANEL_REDO = "redo"

# Chaves das acoes do plugin (plugin.py -> FortSmartDock.set_tool_actions).
PLUGIN_WORKSPACE = "workspace"
PLUGIN_HEADLAND_TURNS = "headland_turns"
PLUGIN_STRATEGY_ANALYZER = "strategy_analyzer"
PLUGIN_OBSTACLE_DETOUR = "obstacle_detour"
PLUGIN_LINE_CUT = "line_cut"
PLUGIN_OPERATION_SIMULATOR = "operation_simulator"
PLUGIN_COVERAGE_XRAY = "coverage_xray"
PLUGIN_EXPORT_READINESS = "export_readiness"
PLUGIN_CRS_CONVERTER = "crs_converter"


@dataclass(frozen=True)
class AgroCadTool:
    key: str
    section: str
    label: str
    source: str
    target: str
    description: str
    requires: tuple = ()
    map_tool: bool = False


@dataclass(frozen=True)
class LayerFacts:
    present: bool = False
    is_vector: bool = False
    is_editable: bool = False
    can_undo: bool = False
    can_redo: bool = False


@dataclass(frozen=True)
class ToolState:
    enabled: bool
    reason: str = ""


_DIALOG = "Abre a tela existente do FortSmart; os parâmetros ficam nela."

TOOLS = (
    AgroCadTool("toggle_editing", SECTION_EDITOR, "Alternar edição", SOURCE_NATIVE, "actionToggleEditing",
                "Liga ou desliga a edição da camada ativa (ação nativa do QGIS).", (REQUIRES_VECTOR,)),
    AgroCadTool("save_edits", SECTION_EDITOR, "Salvar edições", SOURCE_NATIVE, "actionSaveActiveLayerEdits",
                "Grava as edições da camada ativa (ação nativa do QGIS).", (REQUIRES_EDITABLE,)),
    AgroCadTool("select", SECTION_EDITOR, "Selecionar", SOURCE_NATIVE, "actionSelect",
                "Seleção nativa do QGIS por clique.", (REQUIRES_VECTOR,), True),
    AgroCadTool("select_rectangle", SECTION_EDITOR, "Selecionar por retângulo", SOURCE_NATIVE,
                "actionSelectRectangle", "Seleção nativa do QGIS por retângulo.", (REQUIRES_VECTOR,), True),
    AgroCadTool("select_polygon", SECTION_EDITOR, "Selecionar por polígono", SOURCE_NATIVE, "actionSelectPolygon",
                "Seleção nativa do QGIS por polígono.", (REQUIRES_VECTOR,), True),
    AgroCadTool("vertex_tool", SECTION_EDITOR, "Editar vértices", SOURCE_NATIVE, "actionVertexToolActiveLayer",
                "Ferramenta de vértices do QGIS na camada ativa.", (REQUIRES_EDITABLE,), True),
    AgroCadTool("split_features", SECTION_EDITOR, "Dividir feições", SOURCE_NATIVE, "actionSplitFeatures",
                "Divisão nativa do QGIS; altera a camada em edição.", (REQUIRES_EDITABLE,), True),
    AgroCadTool("undo", SECTION_EDITOR, "Desfazer", SOURCE_PANEL, PANEL_UNDO,
                "Desfaz a última edição da camada ativa (pilha de desfazer do QGIS).", (REQUIRES_UNDO,)),
    AgroCadTool("redo", SECTION_EDITOR, "Refazer", SOURCE_PANEL, PANEL_REDO,
                "Refaz a edição desfeita da camada ativa (pilha de desfazer do QGIS).", (REQUIRES_REDO,)),
    AgroCadTool("merge_features", SECTION_EDITOR, "Unir feições", SOURCE_UNAVAILABLE, "",
                "Sem método estável na interface do QGIS; use o menu Editar do QGIS."),
    AgroCadTool("obstacle_detour", SECTION_OBSTACLES, "Desvio de obstáculo", SOURCE_PLUGIN,
                PLUGIN_OBSTACLE_DETOUR, _DIALOG),
    AgroCadTool("line_cut", SECTION_OBSTACLES, "Cortar linhas por obstáculos", SOURCE_PLUGIN, PLUGIN_LINE_CUT,
                _DIALOG),
    AgroCadTool("dem_inspector", SECTION_TERRAIN, "Inspetor DEM", SOURCE_UNAVAILABLE, "",
                "Disponível com a chave ENABLE_DEM_INSPECTOR_V1 (Subfase 0F)."),
    AgroCadTool("slope", SECTION_TERRAIN, "Declividade", SOURCE_UNAVAILABLE, "",
                "Fora da Etapa 0 (análise de terreno)."),
    AgroCadTool("contours", SECTION_TERRAIN, "Curvas de nível", SOURCE_UNAVAILABLE, "",
                "Fora da Etapa 0 (análise de terreno)."),
    AgroCadTool("workspace", SECTION_PLANNING, "Planejamento Precision Lines", SOURCE_PLUGIN, PLUGIN_WORKSPACE,
                _DIALOG),
    AgroCadTool("headland_turns", SECTION_PLANNING, "Manobras de cabeceira", SOURCE_PLUGIN,
                PLUGIN_HEADLAND_TURNS, _DIALOG),
    AgroCadTool("strategy_analyzer", SECTION_PLANNING, "Comparar projeção de plantio", SOURCE_PLUGIN,
                PLUGIN_STRATEGY_ANALYZER, _DIALOG),
    AgroCadTool("operation_simulator", SECTION_PLANNING, "Simulador de operação", SOURCE_PLUGIN,
                PLUGIN_OPERATION_SIMULATOR, _DIALOG),
    AgroCadTool("coverage_xray", SECTION_PLANNING, "Raio-X de cobertura", SOURCE_PLUGIN, PLUGIN_COVERAGE_XRAY,
                _DIALOG),
    AgroCadTool("export_readiness", SECTION_PLANNING, "Validar para exportação", SOURCE_PLUGIN,
                PLUGIN_EXPORT_READINESS, _DIALOG),
    AgroCadTool("crs_converter", SECTION_PLANNING, "Conversor de zona / CRS", SOURCE_PLUGIN, PLUGIN_CRS_CONVERTER,
                _DIALOG),
)


def tools_for(section: str) -> tuple:
    return tuple(tool for tool in TOOLS if tool.section == section)


def tool_by_key(key: str) -> AgroCadTool | None:
    return next((tool for tool in TOOLS if tool.key == key), None)


def tool_state(tool: AgroCadTool, *, available: bool, facts: LayerFacts) -> ToolState:
    """Habilitado so com a origem disponivel e a camada no estado exigido."""
    if tool.source == SOURCE_UNAVAILABLE:
        return ToolState(False, tool.description)
    if not available:
        origin = "Ação nativa indisponível nesta versão do QGIS." if tool.source == SOURCE_NATIVE \
            else "Ação do plugin indisponível."
        return ToolState(False, origin)
    needs_layer = set(tool.requires) & {REQUIRES_VECTOR, REQUIRES_EDITABLE, REQUIRES_UNDO, REQUIRES_REDO}
    if needs_layer and not (facts.present and facts.is_vector):
        return ToolState(False, "Selecione uma camada vetorial no QGIS.")
    if REQUIRES_EDITABLE in tool.requires and not facts.is_editable:
        return ToolState(False, "Ative a edição da camada (Editor → Alternar edição).")
    if REQUIRES_UNDO in tool.requires and not facts.can_undo:
        return ToolState(False, "Nada para desfazer na camada ativa.")
    if REQUIRES_REDO in tool.requires and not facts.can_redo:
        return ToolState(False, "Nada para refazer na camada ativa.")
    return ToolState(True)
