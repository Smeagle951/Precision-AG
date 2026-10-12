# -*- coding: utf-8 -*-
"""Nomes fixos das camadas de preview do Workspace (auditaveis no QGIS).

As camadas aparecem no painel com o nome fiel ao conteudo (ex.:
``06_Passadas_Plantio``), sem prefixo tecnico nem contagem no nome. O plugin
reconhece as proprias camadas por propriedade customizada, nao pelo nome.
"""

from __future__ import annotations

import re

# Prefixo antigo: so para reconhecer/limpar camadas de projetos anteriores.
PREVIEW_PREFIX = "_fortsmart_workspace_"
LEGACY_PREVIEW_GROUP_NAME = "_fortsmart_workspace_"
PREVIEW_GROUP_NAME = "FORTSMART"
PREVIEW_LAYER_PROPERTY = "fortsmart_precision/preview_layer"
PREVIEW_GROUP_PROPERTY = "fortsmart_precision/preview_group"

NAMED_PREVIEW_LAYERS = (
    "01_Limite_Externo",
    "02_Bordadura",
    "03_Limite_Interno",
    "04_Linha_AB",
    "05_Passadas",
    "06_Passadas_Plantio",
    "07_Linha_Trator",
    "08_Rastros_Pneus",
    "09_Obstaculos_RTK",
    "10_Zonas_Seguranca",
    "11_Desvios_Obstaculos",
    "12_Linhas_Finais",
    "13_Shutoff",
    "14_Limite_Operacional",
    "15_Passadas_Bordadura",
)

PLANTING_LINE_ROLES = ("WORK_PATH", "FINAL_WORK_PATH")
SPRAYING_LINE_ROLES = ("GUIDANCE_TRACK",)

# Alias legado (camadas antigas ainda podem existir no projeto).
PREVIEW_LAYER_ALIASES = {
    "06_Linhas_Plantio": "06_Passadas_Plantio",
}

PREVIEW_LAYER_GEOM = {
    "01_Limite_Externo": "Polygon",
    "02_Bordadura": "Polygon",
    "03_Limite_Interno": "Polygon",
    "04_Linha_AB": "LineString",
    "05_Passadas": "LineString",
    "06_Passadas_Plantio": "LineString",
    "07_Linha_Trator": "LineString",
    "08_Rastros_Pneus": "LineString",
    "09_Obstaculos_RTK": "Point",
    "10_Zonas_Seguranca": "Polygon",
    "11_Desvios_Obstaculos": "Polygon",
    "12_Linhas_Finais": "LineString",
    "13_Shutoff": "LineString",
    "14_Limite_Operacional": "Polygon",
    "15_Passadas_Bordadura": "LineString",
}


def preview_layer_base_name(short_name: str) -> str:
    """Nome canonico exibido; a chave interna permanece retrocompativel."""
    from .layer_roles import layer_role_definition

    return layer_role_definition(short_name).display_name


def unique_layer_name(desired: str, taken_names) -> str:
    """desired, ou desired_2, desired_3... se ja existir camada de outra origem."""
    taken = set(taken_names)
    if desired not in taken:
        return desired
    index = 2
    while f"{desired}_{index}" in taken:
        index += 1
    return f"{desired}_{index}"


def preview_group_name(field_name: str | None = None) -> str:
    from .layer_roles import canonical_project_group_name

    return canonical_project_group_name(field_name)


def is_legacy_preview_name(layer_name: str) -> bool:
    return str(layer_name or "").startswith(PREVIEW_PREFIX)


def match_preview_layer_name(layer_name: str, short_name: str) -> bool:
    """
    True se layer_name for o preview short_name.

    Aceita o nome limpo (05_Passadas), a copia unica (05_Passadas_2) e os
    formatos antigos '_fortsmart_workspace_05_Passadas (12)'.
    """
    name = str(layer_name or "")
    if name.startswith(PREVIEW_PREFIX):
        name = name[len(PREVIEW_PREFIX):]
    if re.fullmatch(re.escape(short_name) + r"(_\d+)?( \(\d+\))?", name):
        return True
    try:
        canonical = preview_layer_base_name(short_name)
    except KeyError:
        canonical = short_name
    if re.fullmatch(re.escape(canonical) + r"(_\d+)?( \(\d+\))?", name):
        return True
    # Alias legado.
    alias = PREVIEW_LAYER_ALIASES.get(short_name)
    if alias:
        return match_preview_layer_name(layer_name, alias)
    # short_name pode ser o alias legado (06_Linhas_Plantio).
    for legacy, canonical in PREVIEW_LAYER_ALIASES.items():
        if short_name == legacy:
            return match_preview_layer_name(layer_name, canonical)
    return False


def preview_layer_role(layer) -> str | None:
    """short_name gravado pelo plugin na camada, ou None se nao for preview atual."""
    getter = getattr(layer, "customProperty", None)
    if getter is None:
        return None
    try:
        value = getter(PREVIEW_LAYER_PROPERTY, "")
    except Exception:
        return None
    return str(value) if value else None


def is_plugin_preview_layer(layer) -> bool:
    name = getattr(layer, "name", lambda: "")()
    return preview_layer_role(layer) is not None or is_legacy_preview_name(name)


def find_preview_layer(layers, *short_names: str):
    """Primeira camada de preview de algum short_name; as marcadas pelo plugin vencem."""
    layer_list = list(layers)
    for short in short_names:
        for layer in layer_list:
            role = preview_layer_role(layer)
            if role is not None and (
                role == short or PREVIEW_LAYER_ALIASES.get(short) == role
            ):
                return layer
        for layer in layer_list:
            name = getattr(layer, "name", lambda: "")()
            if match_preview_layer_name(name, short):
                return layer
    return None


def is_planting_preview_line_layer(layer) -> bool:
    """True se a camada e preview de plantio (nao deve ir no combo de pulverizacao)."""
    if layer is None:
        return False
    from .layer_roles import layer_role

    role = layer_role(layer)
    if role:
        return role in PLANTING_LINE_ROLES
    name = layer.name() if hasattr(layer, "name") else ""
    return any(
        match_preview_layer_name(name, short)
        for short in (
            "06_Passadas_Plantio",
            "12_Passadas_Plantio",
            "06_Linhas_Plantio",
            "linhas_plantio",
            "rows",
            "passadas_plantio",
        )
    )


def is_spraying_preview_line_layer(layer) -> bool:
    """True se a camada e preview de pulverizacao."""
    if layer is None:
        return False
    from .layer_roles import layer_role

    role = layer_role(layer)
    if role:
        return role in SPRAYING_LINE_ROLES
    name = layer.name() if hasattr(layer, "name") else ""
    return any(
        match_preview_layer_name(name, short)
        for short in ("05_Passadas", "passadas_aplicacao", "spray")
    )
