# -*- coding: utf-8 -*-
"""Catalogo canonico de camadas entre gerador, corte e exportadores.

Cada camada tem tres identidades: chave interna (codigo), display_name (painel)
e fortsmart_role (semantica). Busca e substituicao usam o role; o nome visual
pode mudar sem quebrar nada.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace


SCHEMA_VERSION = 1

ROLE_PROPERTY = "fortsmart_role"
ROLE_PROPERTY_NAMESPACED = "fortsmart_precision/role"
SECTION_PROPERTY = "fortsmart_precision/section"
GENERATED_PROPERTY = "fortsmart_generated"
SECTION_KEY_PROPERTY = "fortsmart_section"
INTERNAL_KEY_PROPERTY = "fortsmart_internal_key"
PROJECT_PROPERTY = "fortsmart_project"
FIELD_ID_PROPERTY = "fortsmart_field_id"
SCHEMA_PROPERTY = "fortsmart_schema_version"
TEMPORARY_PREVIEW_PROPERTY = "fortsmart_temporary_preview"
TEMPORARY_PROPERTY = "fortsmart_temporary"
# Preview do analisador de estrategias: nunca exportado nem persistido.
STRATEGY_PREVIEW_PROPERTY = "fortsmart_preview"
ORIGINAL_NAME_PROPERTY = "fortsmart_original_name"
ORIGINAL_GROUP_PATH_PROPERTY = "fortsmart_original_group_path"
CLASSIFIED_BY_PROPERTY = "fortsmart_classified_by"
STORAGE_PROPERTY = "fortsmart_storage"
PERSISTED_PROPERTY = "fortsmart_persisted"
UPDATED_AT_PROPERTY = "fortsmart_updated_at"
SOURCE_LAYER_ID_PROPERTY = "fortsmart_source_layer_id"
STORAGE_MEMORY = "memory"
STORAGE_GEOPACKAGE = "geopackage"
STORAGE_EXTERNAL = "external"
# Marca gravada pelo Workspace antes do schema de metadados.
LEGACY_INTERNAL_KEY_PROPERTY = "fortsmart_precision/preview_layer"
LEGACY_NAME_PREFIX = "_fortsmart_workspace_"

PROJECT_GROUP_PREFIX = "FORTSMART - "
PREVIEW_SECTION = "SIM_PREVIEW"
AUXILIARY_SECTION = "90_AUXILIARES"
SECTION_ORDER = (
    "00_REFERENCIAS",
    "10_PLANEJAMENTO",
    "20_OBSTACULOS",
    "30_OPERACAO",
    "40_SIMULACAO",
    AUXILIARY_SECTION,
)

ROLE_LAYER_OK = "OK"
EMPTY_ROLE_LAYER = "EMPTY_ROLE_LAYER"
ROLE_LAYER_MISSING = "MISSING"

SOURCE_ROLE = "role"
SOURCE_INTERNAL_KEY = "internal_key"
SOURCE_LEGACY_ALIAS = "legacy_alias"
SOURCE_DISPLAY_NAME = "display_name"
SOURCE_HEURISTIC = "heuristic"


@dataclass(frozen=True)
class LayerRoleDefinition:
    display_name: str
    section: str
    role: str
    key: str = ""


def _catalog(items: dict) -> dict:
    return {key: replace(definition, key=key) for key, definition in items.items()}


LAYER_ROLES = _catalog({
    "01_Limite_Externo": LayerRoleDefinition("01_Limite_Externo", "00_REFERENCIAS", "EXTERNAL_BOUNDARY"),
    "02_Bordadura": LayerRoleDefinition("03_Bordadura", "00_REFERENCIAS", "HEADLAND"),
    "03_Limite_Interno": LayerRoleDefinition("02_Limite_Interno", "00_REFERENCIAS", "INTERNAL_BOUNDARY"),
    "04_Linha_AB": LayerRoleDefinition("04_Linha_AB", "00_REFERENCIAS", "AB_LINE"),
    "14_Limite_Operacional": LayerRoleDefinition("05_Limite_Operacional", "00_REFERENCIAS", "OPERATIONAL_BOUNDARY"),
    "15_Passadas_Bordadura": LayerRoleDefinition(
        "15_Passadas_Bordadura", "10_PLANEJAMENTO", "FIELD_HEADLAND_PATH"
    ),
    "05_Passadas": LayerRoleDefinition("11_Passadas", "10_PLANEJAMENTO", "GUIDANCE_TRACK"),
    "06_Passadas_Plantio": LayerRoleDefinition("12_Passadas_Plantio", "10_PLANEJAMENTO", "WORK_PATH"),
    "07_Linha_Trator": LayerRoleDefinition("13_Linha_Trator", "10_PLANEJAMENTO", "TRACTOR_PATH"),
    "08_Rastros_Pneus": LayerRoleDefinition("14_Rastros_Pneus", "10_PLANEJAMENTO", "TIRE_TRACK"),
    "09_Obstaculos_RTK": LayerRoleDefinition("21_Obstaculos_RTK", "20_OBSTACULOS", "OBSTACLE"),
    "10_Zonas_Seguranca": LayerRoleDefinition("22_Zonas_Seguranca", "20_OBSTACULOS", "SAFETY_ZONE"),
    "11_Desvios_Obstaculos": LayerRoleDefinition("23_Desvios_Obstaculos", "20_OBSTACULOS", "OBSTACLE_DETOUR"),
    "12_Linhas_Finais": LayerRoleDefinition("31_Linhas_Finais", "30_OPERACAO", "FINAL_WORK_PATH"),
    "13_Shutoff": LayerRoleDefinition("34_Shutoff", "30_OPERACAO", "SHUTOFF"),
})


SIMULATION_ROLES = _catalog({
    "SIM_WORK_LINES": LayerRoleDefinition("31_Linhas_Finais", "30_OPERACAO", "FINAL_WORK_PATH"),
    "SIM_WORK_OFF": LayerRoleDefinition("32_Work_Off", "30_OPERACAO", "WORK_OFF"),
    "SIM_WORK_ON": LayerRoleDefinition("33_Work_On", "30_OPERACAO", "WORK_ON"),
    "FINAL_BORDER_PASS": LayerRoleDefinition(
        "35_Linhas_Bordadura", "30_OPERACAO", "HEADLAND_WORK_PATH"
    ),
    "SIM_COVERAGE": LayerRoleDefinition("41_Cobertura", "40_SIMULACAO", "COVERAGE"),
    "SIM_BORDER_OVERLAPS": LayerRoleDefinition("42_Remonte", "40_SIMULACAO", "OVERLAP"),
    "SIM_BORDER_GAPS": LayerRoleDefinition("43_Falha", "40_SIMULACAO", "GAP"),
    "SIM_MACHINE_PATH": LayerRoleDefinition("44_Trajetoria_Maquina", "40_SIMULACAO", "MACHINE_PATH"),
    "SIM_MAIN_WORK_AREA": LayerRoleDefinition("45_Faixa_Implemento", "40_SIMULACAO", "IMPLEMENT_SWATH"),
    "SIM_BORDER_COVERAGE": LayerRoleDefinition("46_Faixa_Bordadura", "40_SIMULACAO", "HEADLAND_SWATH"),
    "SIM_WORKING_PATH": LayerRoleDefinition("47_Trajetoria_Linha_Ativa", "40_SIMULACAO", "ACTIVE_ROW_PATH"),
    "SIM_BORDER_PASS": LayerRoleDefinition("48_Trajetoria_Bordadura", "40_SIMULACAO", "HEADLAND_PATH"),
    "SIM_UNWORKED_BORDER": LayerRoleDefinition("49_Trecho_Sem_Operacao", "40_SIMULACAO", "UNWORKED_AREA"),
    "SIM_SAFETY_ZONE": LayerRoleDefinition("22_Zonas_Seguranca", "20_OBSTACULOS", "SAFETY_ZONE"),
})

# Camada derivada das manobras; nao faz parte do preview do gerador.
HEADLAND_TURN_ROLE = LayerRoleDefinition(
    "16_Manobras_Cabeceira", "10_PLANEJAMENTO", "HEADLAND_TURN", "HEADLAND_TURN"
)

# Ordem visual dentro das secoes (topo -> base); independe do display_name.
CANONICAL_ROLE_ORDER = (
    "EXTERNAL_BOUNDARY",
    "INTERNAL_BOUNDARY",
    "HEADLAND",
    "AB_LINE",
    "OPERATIONAL_BOUNDARY",
    "GUIDANCE_TRACK",
    "WORK_PATH",
    "TRACTOR_PATH",
    "TIRE_TRACK",
    "FIELD_HEADLAND_PATH",
    "HEADLAND_TURN",
    "OBSTACLE",
    "SAFETY_ZONE",
    "OBSTACLE_DETOUR",
    "FINAL_WORK_PATH",
    "WORK_OFF",
    "WORK_ON",
    "SHUTOFF",
    "HEADLAND_WORK_PATH",
    "COVERAGE",
    "OVERLAP",
    "GAP",
    "MACHINE_PATH",
    "IMPLEMENT_SWATH",
    "HEADLAND_SWATH",
    "ACTIVE_ROW_PATH",
    "HEADLAND_PATH",
    "UNWORKED_AREA",
)

# Nomes antigos/externos; so classificam em memoria, nunca renomeiam.
LEGACY_LAYER_ALIASES = {
    "EXTERNAL_BOUNDARY": ("Limite_Externo", "Boundary"),
    "HEADLAND": ("02_Bordadura", "Bordadura"),
    "INTERNAL_BOUNDARY": ("03_Limite_Interno", "Limite_Interno"),
    "AB_LINE": ("Linha_AB",),
    "OPERATIONAL_BOUNDARY": ("14_Limite_Operacional", "Limite_Operacional"),
    "GUIDANCE_TRACK": ("05_Passadas", "Passadas"),
    "WORK_PATH": (
        "06_Passadas_Plantio",
        "Passadas_Plantio",
        "06_Linhas_Plantio",
        "Linhas_Plantio",
    ),
    "TRACTOR_PATH": ("07_Linha_Trator", "Linha_Trator"),
    "TIRE_TRACK": ("08_Rastros_Pneus", "Rastros_Pneus"),
    "FIELD_HEADLAND_PATH": ("Passadas_Bordadura",),
    "OBSTACLE": ("09_Obstaculos_RTK", "21_Obstaculos", "Obstaculos_RTK"),
    "SAFETY_ZONE": ("10_Zonas_Seguranca", "Zonas_Seguranca"),
    "OBSTACLE_DETOUR": ("11_Desvios_Obstaculos", "23_Desvios", "Desvios_Obstaculos"),
    "FINAL_WORK_PATH": ("12_Linhas_Finais", "Linhas_Finais"),
    "SHUTOFF": ("13_Shutoff", "Shutoff"),
    "WORK_OFF": ("Work_Off",),
    "WORK_ON": ("Work_On",),
    "HEADLAND_TURN": ("Manobras_Cabeceira",),
}

# Roles renomeados: valor antigo gravado em projetos -> role atual.
LEGACY_ROLE_ALIASES = {"HEADLAND_GAP": "GAP"}

# Campos minimos por feicao gravados na persistencia (nome, tipo).
_BASE_FIELDS = (("fortsmart_role", "string"), ("field_id", "string"), ("source_id", "string"))
_LINE_FIELDS = (("line_id", "string"), ("pass_number", "int"))
_SEGMENT_FIELDS = (("parent_line_id", "string"), ("segment_index", "int"))
_EVENT_FIELDS = (("line_id", "string"), ("station", "double"), ("obstacle_id", "string"))
_TURN_FIELDS = (("turn_id", "string"), ("from_pass", "int"), ("to_pass", "int"), ("turn_type", "string"))
ROLE_FIELD_SCHEMA = {
    "GUIDANCE_TRACK": _BASE_FIELDS + _LINE_FIELDS,
    "WORK_PATH": _BASE_FIELDS + _LINE_FIELDS,
    "TRACTOR_PATH": _BASE_FIELDS + _LINE_FIELDS,
    "FIELD_HEADLAND_PATH": _BASE_FIELDS + _LINE_FIELDS,
    "FINAL_WORK_PATH": _BASE_FIELDS + _LINE_FIELDS + _SEGMENT_FIELDS,
    "HEADLAND_WORK_PATH": _BASE_FIELDS + _LINE_FIELDS + _SEGMENT_FIELDS,
    "WORK_OFF": _BASE_FIELDS + _EVENT_FIELDS,
    "WORK_ON": _BASE_FIELDS + _EVENT_FIELDS,
    "HEADLAND_TURN": _BASE_FIELDS + _TURN_FIELDS,
}
_SEGMENTED_ROLES = ("FINAL_WORK_PATH", "HEADLAND_WORK_PATH")

# Ultimo recurso: fragmentos no nome normalizado, na ordem de prioridade.
_HEURISTIC_TOKENS = (
    ("linhas_finais", "FINAL_WORK_PATH"),
    ("passadas_plantio", "WORK_PATH"),
    ("manobras_cabeceira", "HEADLAND_TURN"),
    ("limite_externo", "EXTERNAL_BOUNDARY"),
    ("limite_interno", "INTERNAL_BOUNDARY"),
    ("seguranca", "SAFETY_ZONE"),
    ("obstacul", "OBSTACLE"),
)


def layer_role_definition(key: str) -> LayerRoleDefinition:
    return LAYER_ROLES[key]


def simulation_role_definition(key: str) -> LayerRoleDefinition:
    return SIMULATION_ROLES[key]


def all_role_definitions() -> tuple[LayerRoleDefinition, ...]:
    return (*LAYER_ROLES.values(), *SIMULATION_ROLES.values(), HEADLAND_TURN_ROLE)


def definition_for_role(role: str) -> LayerRoleDefinition | None:
    return next((item for item in all_role_definitions() if item.role == role), None)


def definition_for_key(key: str) -> LayerRoleDefinition | None:
    if key in LAYER_ROLES:
        return LAYER_ROLES[key]
    if key in SIMULATION_ROLES:
        return SIMULATION_ROLES[key]
    return HEADLAND_TURN_ROLE if key == HEADLAND_TURN_ROLE.key else None


def role_order_index(role: str) -> int:
    try:
        return CANONICAL_ROLE_ORDER.index(role)
    except ValueError:
        return len(CANONICAL_ROLE_ORDER)


def section_order_index(section: str) -> int:
    try:
        return SECTION_ORDER.index(section)
    except ValueError:
        return len(SECTION_ORDER)


def _property(layer, key: str, default=""):
    getter = getattr(layer, "customProperty", None)
    if getter is None:
        return default
    try:
        value = getter(key, default)
    except Exception:
        return default
    return default if value is None else value


def _truthy(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def _layer_name(layer) -> str:
    getter = getattr(layer, "name", None)
    try:
        return str(getter() if callable(getter) else "")
    except Exception:
        return ""


def layer_role(layer) -> str:
    role = str(_property(layer, ROLE_PROPERTY) or _property(layer, ROLE_PROPERTY_NAMESPACED) or "")
    return LEGACY_ROLE_ALIASES.get(role, role)


def layer_field_id(layer) -> str:
    return str(_property(layer, FIELD_ID_PROPERTY) or "")


def is_generated_layer(layer) -> bool:
    """Camada criada pelo plugin (schema atual ou marca legada do Workspace)."""
    if _truthy(_property(layer, GENERATED_PROPERTY, False)):
        return True
    return bool(_property(layer, LEGACY_INTERNAL_KEY_PROPERTY)) or _layer_name(layer).startswith(
        LEGACY_NAME_PREFIX
    )


# Camadas derivadas das passadas: nunca podem virar a referencia A-B.
GENERATED_PASS_ROLES = frozenset({
    "GUIDANCE_TRACK",
    "WORK_PATH",
    "TRACTOR_PATH",
    "TIRE_TRACK",
    "FIELD_HEADLAND_PATH",
    "FINAL_WORK_PATH",
    "HEADLAND_WORK_PATH",
    "HEADLAND_TURN",
    "SHUTOFF",
    "WORK_OFF",
    "WORK_ON",
    "MACHINE_PATH",
    "ACTIVE_ROW_PATH",
    "HEADLAND_PATH",
})


def ab_source_rejection_reason(layer) -> str | None:
    """Motivo para recusar a camada como A-B (marca do plugin), ou None se aceitavel."""
    if layer is None:
        return None
    role = layer_role(layer) or _role_from_internal_key(layer)
    if role not in GENERATED_PASS_ROLES:
        return None
    definition = definition_for_role(role)
    label = definition.display_name if definition is not None else role
    return (
        f"A camada '{_layer_name(layer)}' foi gerada pelo FortSmart ({label}) e nao pode "
        "ser usada como A-B. A A-B continua sendo a linha original escolhida."
    )


def is_temporary_preview(layer) -> bool:
    return any(
        _truthy(_property(layer, key, False))
        for key in (TEMPORARY_PREVIEW_PROPERTY, TEMPORARY_PROPERTY, STRATEGY_PREVIEW_PROPERTY)
    )


def storage_kind(layer) -> str:
    """memory / geopackage / external: metadado gravado, senao o provider."""
    stored = str(_property(layer, STORAGE_PROPERTY) or "")
    if stored:
        return stored
    getter = getattr(layer, "providerType", None)
    try:
        provider = getter() if callable(getter) else ""
    except Exception:
        provider = ""
    return STORAGE_MEMORY if provider == "memory" else STORAGE_EXTERNAL


def is_persisted_layer(layer) -> bool:
    return _truthy(_property(layer, PERSISTED_PROPERTY, False))


def _normalized_name(name: str) -> str:
    text = str(name or "").strip()
    if text.startswith(LEGACY_NAME_PREFIX):
        text = text[len(LEGACY_NAME_PREFIX):]
    text = re.sub(r"\s*\(EPSG:\d+\)\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*\(\d+\)\s*$", "", text)
    text = re.sub(r"_\d+$", "", text)
    return re.sub(r"[\s_]+", "_", text).strip("_").casefold()


def _name_index(pairs) -> dict[str, str]:
    index: dict[str, str] = {}
    for name, role in pairs:
        index.setdefault(_normalized_name(name), role)
    return index


_ALIAS_INDEX = _name_index(
    (name, role) for role, names in LEGACY_LAYER_ALIASES.items() for name in names
)
_DISPLAY_INDEX = _name_index((item.display_name, item.role) for item in all_role_definitions())


def _role_from_internal_key(layer) -> str:
    for key in (_property(layer, INTERNAL_KEY_PROPERTY), _property(layer, LEGACY_INTERNAL_KEY_PROPERTY)):
        definition = definition_for_key(str(key or ""))
        if definition is not None:
            return definition.role
    legacy = str(_property(layer, LEGACY_INTERNAL_KEY_PROPERTY) or "")
    return _ALIAS_INDEX.get(_normalized_name(legacy), "") if legacy else ""


def _role_from_alias(name: str) -> str:
    normalized = _normalized_name(name)
    if re.fullmatch(r"boundary(_?[—–-].*)?", normalized):
        return "EXTERNAL_BOUNDARY"
    return _ALIAS_INDEX.get(normalized, "")


def _role_from_heuristic(name: str) -> str:
    normalized = _normalized_name(name)
    return next((role for token, role in _HEURISTIC_TOKENS if token in normalized), "")


def classify_layer_at(layer, source: str) -> str:
    """Role que uma unica fonte de identificacao atribui a camada ('' se nenhum)."""
    if source == SOURCE_ROLE:
        return layer_role(layer)
    if source == SOURCE_INTERNAL_KEY:
        return _role_from_internal_key(layer)
    name = _layer_name(layer)
    if source == SOURCE_LEGACY_ALIAS:
        return _role_from_alias(name)
    if source == SOURCE_DISPLAY_NAME:
        return _DISPLAY_INDEX.get(_normalized_name(name), "")
    if source == SOURCE_HEURISTIC:
        return _role_from_heuristic(name)
    return ""


CLASSIFICATION_ORDER = (
    SOURCE_ROLE,
    SOURCE_INTERNAL_KEY,
    SOURCE_LEGACY_ALIAS,
    SOURCE_DISPLAY_NAME,
    SOURCE_HEURISTIC,
)


def classify_layer(layer) -> tuple[str, str]:
    """(role, fonte) na ordem: role > metadado interno > alias > nome > heuristica."""
    for source in CLASSIFICATION_ORDER:
        role = classify_layer_at(layer, source)
        if role:
            return role, source
    return "", ""


def _feature_count(layer) -> int:
    counter = getattr(layer, "featureCount", None)
    if counter is None:
        return -1
    try:
        return int(counter())
    except Exception:
        return -1


def find_layer_by_role(layers, *roles: str, names: tuple[str, ...] = (), non_empty: bool = False):
    """Primeira camada pelo role canonico; nomes so entram como fallback."""
    items = [layer for layer in layers if not non_empty or _feature_count(layer) != 0]
    for role in roles:
        for layer in items:
            if layer_role(layer) == role:
                return layer
    unassigned = [(layer, classify_layer(layer)) for layer in items if not layer_role(layer)]
    for source in (SOURCE_INTERNAL_KEY, SOURCE_LEGACY_ALIAS, SOURCE_DISPLAY_NAME):
        for role in roles:
            for layer, (found, found_source) in unassigned:
                if found_source == source and found == role:
                    return layer
    for name in names:
        pattern = re.compile(re.escape(name) + r"(_\d+)?", re.IGNORECASE)
        for layer, _classification in unassigned:
            if pattern.fullmatch(_layer_name(layer)):
                return layer
    for role in roles:
        for layer, (found, found_source) in unassigned:
            if found_source == SOURCE_HEURISTIC and found == role:
                return layer
    return None


def role_layer_status(layer) -> str:
    if layer is None:
        return ROLE_LAYER_MISSING
    return EMPTY_ROLE_LAYER if _feature_count(layer) == 0 else ROLE_LAYER_OK


def canonical_field_name(field_name: str | None) -> str:
    """Nome do talhao sem prefixo do grupo, sufixo de CRS ou 'Boundary —'."""
    name = re.sub(r"\s+", " ", str(field_name or "")).strip()
    if name.upper().startswith(PROJECT_GROUP_PREFIX.upper()):
        name = name[len(PROJECT_GROUP_PREFIX):].strip()
    name = re.sub(r"\s*\(EPSG:\d+\)\s*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"^Boundary\s*[—–-]\s*", "", name, flags=re.IGNORECASE)
    return name.strip() or "PROJETO"


def canonical_project_group_name(field_name: str | None) -> str:
    return f"{PROJECT_GROUP_PREFIX}{canonical_field_name(field_name)}"


def set_layer_role_properties(
    layer,
    definition: LayerRoleDefinition,
    *,
    field_name: str | None = None,
    generated: bool = True,
) -> None:
    """Metadados da camada no projeto; nao toca geometria nem atributos."""
    layer.setCustomProperty(ROLE_PROPERTY, definition.role)
    layer.setCustomProperty(ROLE_PROPERTY_NAMESPACED, definition.role)
    layer.setCustomProperty(SECTION_PROPERTY, definition.section)
    layer.setCustomProperty(SECTION_KEY_PROPERTY, definition.section)
    layer.setCustomProperty(INTERNAL_KEY_PROPERTY, definition.key)
    layer.setCustomProperty(SCHEMA_PROPERTY, SCHEMA_VERSION)
    if generated:
        layer.setCustomProperty(GENERATED_PROPERTY, True)
    if storage_kind(layer) == STORAGE_MEMORY:
        layer.setCustomProperty(STORAGE_PROPERTY, STORAGE_MEMORY)
        layer.setCustomProperty(PERSISTED_PROPERTY, False)
    if field_name is not None:
        layer.setCustomProperty(PROJECT_PROPERTY, canonical_project_group_name(field_name))
        layer.setCustomProperty(FIELD_ID_PROPERTY, canonical_field_name(field_name))


def mark_temporary_preview(layer) -> None:
    layer.setCustomProperty(TEMPORARY_PREVIEW_PROPERTY, True)


def apply_qgis_layer_role(
    layer,
    definition: LayerRoleDefinition,
    *,
    field_name: str | None = None,
) -> None:
    """Grava identidade no projeto e nas feicoes, sem depender do nome visual."""
    from qgis.PyQt.QtCore import QVariant
    from qgis.core import QgsField

    set_layer_role_properties(layer, definition, field_name=field_name)
    names = layer.fields().names()
    if ROLE_PROPERTY not in names:
        if not layer.dataProvider().addAttributes([QgsField(ROLE_PROPERTY, QVariant.String)]):
            return
        layer.updateFields()
    field_index = layer.fields().indexFromName(ROLE_PROPERTY)
    if field_index < 0:
        return
    changes = {feature.id(): {field_index: definition.role} for feature in layer.getFeatures()}
    if changes:
        layer.dataProvider().changeAttributeValues(changes)


def role_field_schema(role: str) -> tuple[tuple[str, str], ...]:
    return ROLE_FIELD_SCHEMA.get(role, _BASE_FIELDS)


def _is_null(value) -> bool:
    if value is None:
        return True
    checker = getattr(value, "isNull", None)
    try:
        return bool(checker()) if callable(checker) else False
    except Exception:
        return False


def _first(attributes: dict, *names: str):
    folded = {str(key).casefold(): value for key, value in attributes.items()}
    for name in names:
        value = folded.get(name)
        if not _is_null(value) and value != "":
            return value
    return None


def _as_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def feature_identity(role: str, attributes: dict, *, field_id: str, feature_id) -> dict:
    """Valores dos campos minimos do role que ainda estao vazios na feicao.

    IDs existentes nunca sao refeitos: line_id/pass_number/source_id herdados
    vencem; so o que falta e derivado (numero -> L0042, segmento 1).
    """
    from .planting_line_cut_engine import line_id_for

    number = _as_int(_first(attributes, "pass_number", "line_number", "line_no", "pass_no", "pass_id"))
    line_id = _first(attributes, "line_id", "parent_line_id")
    if line_id is None and number is not None:
        line_id = line_id_for(number)
    if line_id is None:
        line_id = _first(attributes, "pass_id")
    segment = _as_int(_first(attributes, "segment_index")) or 1
    turn_id = _first(attributes, "turn_id")
    source_id = _first(attributes, "source_id")
    if source_id is None:
        if line_id is not None and role in _SEGMENTED_ROLES:
            source_id = f"{line_id}:{segment}"
        else:
            source_id = line_id or turn_id or f"{role}:{feature_id}"
    derived = {
        "fortsmart_role": role,
        "field_id": field_id,
        "source_id": str(source_id),
        "line_id": None if line_id is None else str(line_id),
        "pass_number": number,
        "parent_line_id": _first(attributes, "parent_line_id") or line_id,
        "segment_index": segment,
        "station": _as_float(_first(attributes, "station", "station_m")),
        "obstacle_id": _first(attributes, "obstacle_id", "obstacle_ids"),
        "turn_id": turn_id,
        "from_pass": _as_int(_first(attributes, "from_pass")),
        "to_pass": _as_int(_first(attributes, "to_pass")),
        "turn_type": _first(attributes, "turn_type"),
    }
    missing = {}
    for name, _kind in role_field_schema(role):
        current = _first(attributes, name)
        if current is None and derived.get(name) is not None:
            missing[name] = derived[name]
    return missing


def format_storage_report(entries, *, ignored_previews: int = 0) -> str:
    """Relatorio legivel de persistencia (uma linha por camada, agrupado por talhao)."""
    lines = ["FORTSMART STORAGE REPORT"]
    by_field: dict[str, list] = {}
    for entry in entries:
        by_field.setdefault(entry.get("field_id") or "sem talhao", []).append(entry)
    for field_id, items in by_field.items():
        lines.append("")
        lines.append(f"Talhão: {field_id}")
        for item in items:
            status = item.get("status", "")
            detail = f" — {item['message']}" if item.get("message") else ""
            lines.append(
                f"{item.get('name', '')}: {item.get('features', 0)} feições — "
                f"{item.get('transition', 'MEMORY → GPKG')} — {status}{detail}"
            )
    ok = sum(1 for entry in entries if entry.get("status") in ("OK", "KEPT_PREVIOUS"))
    errors = len(entries) - ok
    lines.append("")
    lines.append(f"Preview: {ignored_previews} ignorado(s)")
    lines.append(f"Status: {ok} camada(s) persistida(s), {errors} erro(s)")
    return "\n".join(lines)


def layer_inventory(layers) -> list[dict]:
    """Classificacao de cada camada para o relatorio; nao altera nada."""
    entries = []
    for layer in layers:
        role, source = classify_layer(layer)
        definition = definition_for_role(role) if role else None
        entries.append({
            "name": _layer_name(layer),
            "role": role,
            "source": source,
            "section": definition.section if definition else "",
            "generated": is_generated_layer(layer),
            "temporary": is_temporary_preview(layer),
            "field_id": layer_field_id(layer),
            "feature_count": _feature_count(layer),
            "status": role_layer_status(layer) if role else "",
        })
    return entries


def normalization_summary(entries) -> dict:
    fortsmart = [item for item in entries if item["role"] and (item["generated"] or item["source"] == SOURCE_ROLE)]
    keys = [
        (item["role"], item["field_id"])
        for item in fortsmart
        if item["generated"] and not item["temporary"]
    ]
    duplicated = sorted({key for key in keys if keys.count(key) > 1})
    return {
        "fortsmart_layers": len(fortsmart),
        "legacy_aliases": sum(
            1 for item in entries
            if item["source"] in (SOURCE_INTERNAL_KEY, SOURCE_LEGACY_ALIAS, SOURCE_DISPLAY_NAME)
        ),
        "empty_layers": sorted(item["name"] for item in entries if item["status"] == EMPTY_ROLE_LAYER),
        "duplicated_roles": [f"{role} ({field or 'sem talhao'})" for role, field in duplicated],
        "external_layers": sorted(
            item["name"] for item in entries if not item["generated"] and item["source"] != SOURCE_ROLE
        ),
    }


def format_normalization_report(summary: dict, *, moved: tuple[str, ...] = ()) -> str:
    lines = [
        f"Camadas FortSmart normalizadas: {summary['fortsmart_layers']}",
        f"Aliases legados reconhecidos: {summary['legacy_aliases']}",
        f"Camadas vazias ({EMPTY_ROLE_LAYER}): {len(summary['empty_layers'])}",
        f"Roles duplicados no mesmo talhao: {len(summary['duplicated_roles'])}",
        f"Camadas externas preservadas: {len(summary['external_layers'])}",
    ]
    if moved:
        lines.append(f"Camadas movidas: {len(moved)}")
    if summary["empty_layers"]:
        lines.append("Vazias: " + ", ".join(summary["empty_layers"]))
    if summary["duplicated_roles"]:
        lines.append("Duplicadas: " + ", ".join(summary["duplicated_roles"]))
    return "\n".join(lines)
