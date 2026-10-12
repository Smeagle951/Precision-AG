# -*- coding: utf-8 -*-
"""Arvore logica 01-05 do painel FortSmart: so apresentacao, sobre o contexto da 0B.

As categorias sao rotulos de exibicao das secoes reais (00_REFERENCIAS ...);
nenhum grupo, camada, tabela ou nome e criado, renomeado ou movido. A unica
escrita e a visibilidade do no original da camada, feita pelo VisibilityJournal,
que guarda o estado anterior para restaurar.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace

from .geometry_write_check import MESSAGES as GEOMETRY_MESSAGES
from .geometry_write_check import classify_declared_types
from .layer_roles import (
    AUXILIARY_SECTION,
    PREVIEW_SECTION,
    PROJECT_GROUP_PREFIX,
    SECTION_ORDER,
    SOURCE_DISPLAY_NAME,
    SOURCE_HEURISTIC,
    SOURCE_LEGACY_ALIAS,
    STORAGE_MEMORY,
    canonical_field_name,
    classify_layer_at,
    definition_for_role,
    role_order_index,
)
from .project_context import (
    AG_BOUNDARY_ROLES,
    FIELD_AMBIGUOUS,
    FIELD_UNRESOLVED,
    MULTIPLE_APPLICABLE_BOUNDARIES,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    Diagnostic,
    _call,
    _is_layer_node,
    _layer_id,
    _layer_name,
    _node_name,
)

INVALID_FIELD_GROUP = "INVALID_FIELD_GROUP"
FIELD_GROUP_NAMED_AFTER_LAYER = "FIELD_GROUP_NAMED_AFTER_LAYER"
DUPLICATE_FIELD_GROUPS = "DUPLICATE_FIELD_GROUPS"
DUPLICATE_ROLE_IN_FIELD = "DUPLICATE_ROLE_IN_FIELD"
BOUNDARY_VISIBLE_WITH_OTHER = "BOUNDARY_VISIBLE_WITH_OTHER"
GEOMETRY_WRITE_RISK = "GEOMETRY_WRITE_RISK"
UNASSOCIATED_LAYERS = "UNASSOCIATED_LAYERS"
NO_FIELD_GROUPS = "NO_FIELD_GROUPS"
DESCRIBE_FAILED = "DESCRIBE_FAILED"

KIND_OFFICIAL = "OFICIAL"
KIND_OPERATIONAL = "OPERACIONAL"
KIND_AUXILIARY = "AUXILIAR"
KIND_PREVIEW = "PREVIA"
KIND_LABELS = {
    KIND_OFFICIAL: "Oficial",
    KIND_OPERATIONAL: "Operacional",
    KIND_AUXILIARY: "Auxiliar",
    KIND_PREVIEW: "Prévia",
}
# Dados de base do talhao; os demais papeis do catalogo sao gerados para a operacao.
OFFICIAL_ROLES = frozenset({
    "EXTERNAL_BOUNDARY",
    "INTERNAL_BOUNDARY",
    "OPERATIONAL_BOUNDARY",
    "HEADLAND",
    "AB_LINE",
    "OBSTACLE",
    "SAFETY_ZONE",
})

STATUS_OK = "OK"
STATUS_NOTE = "Nota"
STATUS_WARNING = "Aviso"
STATUS_AMBIGUOUS = "Ambíguo"
STATUS_NOT_IN_TREE = "Fora da árvore"

GEOMETRY_RASTER = "Raster"
_GEOMETRY_LABELS = {
    0: "Desconhecida",
    1: "Ponto",
    2: "Linha",
    3: "Polígono",
    4: "Multiponto",
    5: "Multilinha",
    6: "Multipolígono",
    7: "Coleção",
    8: "Linha curva",
    9: "Linha composta",
    10: "Polígono curvo",
    11: "Multicurva",
    12: "Multissuperfície",
    100: "Sem geometria",
}


@dataclass(frozen=True)
class CategoryDefinition:
    code: str
    label: str
    sections: tuple

    @property
    def title(self) -> str:
        return f"{self.code} — {self.label}" if self.code.isdigit() else self.label


LOGICAL_CATEGORIES = (
    CategoryDefinition("01", "Referências", ("00_REFERENCIAS",)),
    CategoryDefinition("02", "Planejamento", ("10_PLANEJAMENTO",)),
    CategoryDefinition("03", "Obstáculos", ("20_OBSTACULOS",)),
    CategoryDefinition("04", "Operação", ("30_OPERACAO",)),
    CategoryDefinition("05", "Análises", ("40_SIMULACAO",)),
)
AUXILIARY_CATEGORY = CategoryDefinition("AUX", "Auxiliares", (AUXILIARY_SECTION,))
PREVIEW_CATEGORY = CategoryDefinition("PREVIEW", "Prévias", (PREVIEW_SECTION,))
ALL_CATEGORIES = LOGICAL_CATEGORIES + (AUXILIARY_CATEGORY, PREVIEW_CATEGORY)
_SECTION_CATEGORY = {section: item for item in LOGICAL_CATEGORIES for section in item.sections}
# Nomes que nunca sao talhao, mesmo dentro de 'FORTSMART - ...'.
_NOT_A_FIELD = frozenset(name.casefold() for name in (*SECTION_ORDER, PREVIEW_SECTION))


@dataclass(frozen=True)
class LogicalLayer:
    layer_id: str
    name: str
    geometry: str
    geometry_code: int | None
    in_tree: bool
    visible_checked: bool
    visible_effective: bool
    group_path: str
    field_id: str | None
    field_status: str
    field_candidates: tuple
    role: str
    role_source: str
    section: str
    category: str
    kind: str
    status: str
    diagnostics: tuple = ()

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)


@dataclass(frozen=True)
class LogicalCategory:
    definition: CategoryDefinition
    layers: tuple

    @property
    def title(self) -> str:
        return self.definition.title


@dataclass(frozen=True)
class LogicalField:
    key: str
    field_id: str | None
    group_paths: tuple
    categories: tuple
    diagnostics: tuple = ()

    @property
    def associated(self) -> bool:
        return self.field_id is not None

    @property
    def title(self) -> str:
        return self.field_id if self.field_id is not None else "Sem talhão definido"

    @property
    def layers(self) -> tuple:
        return tuple(layer for category in self.categories for layer in category.layers)

    @property
    def status(self) -> str:
        return _status_from(self.diagnostics)


@dataclass(frozen=True)
class LogicalTree:
    fields: tuple
    unassociated: LogicalField
    diagnostics: tuple = ()

    def all_fields(self) -> tuple:
        return self.fields + (self.unassociated,)

    def layers(self) -> tuple:
        return tuple(layer for item in self.all_fields() for layer in item.layers)

    def layer(self, layer_id: str) -> LogicalLayer | None:
        return next((layer for layer in self.layers() if layer.layer_id == layer_id), None)

    def field(self, key: str) -> LogicalField | None:
        return next((item for item in self.all_fields() if item.key == key), None)


# ------------------------------------------------------------ geometria ----
def flat_wkb_type(value) -> int | None:
    """Codigo plano (sem Z/M/25D) a partir de QgsWkbTypes/Qgis.WkbType ou inteiro."""
    if value is None:
        return None
    value = getattr(value, "value", value)
    try:
        code = int(value)
    except (TypeError, ValueError):
        return None
    if code & 0x80000000:
        code &= 0x7FFFFFFF
    return code % 1000


def geometry_label(code: int | None) -> str:
    if code is None:
        return GEOMETRY_RASTER
    return _GEOMETRY_LABELS.get(code, f"Tipo {code}")


def layer_geometry(layer) -> tuple[str, int | None]:
    code = flat_wkb_type(_call(layer, "wkbType"))
    if code is None and not callable(getattr(layer, "bandCount", None)):
        return "—", None
    return geometry_label(code), code


def is_valid_field_id(field_id: str | None) -> bool:
    return bool(field_id) and str(field_id).casefold() not in _NOT_A_FIELD


class _Named:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


def field_named_after_layer(field_id: str) -> str:
    """Papel cujo nome de camada coincide com o nome do talhao ('' se nao coincide)."""
    named = _Named(field_id)
    return classify_layer_at(named, SOURCE_DISPLAY_NAME) or classify_layer_at(named, SOURCE_LEGACY_ALIAS)


# ---------------------------------------------------------------- arvore ----
@dataclass(frozen=True)
class NodeInfo:
    layer_id: str
    checked: bool
    visible: bool
    group_path: str
    ancestors: tuple
    physical_field: str | None
    tree_index: int


def layer_nodes(root) -> dict:
    """Uma passada pela arvore: no de cada camada, caminho real e talhao fisico."""
    found: dict[str, NodeInfo] = {}

    def walk(node, names, field):
        for child in _call(node, "children", []) or []:
            if _is_layer_node(child):
                layer_id = str(_call(child, "layerId", "") or _layer_id(_call(child, "layer")))
                if layer_id and layer_id not in found:
                    found[layer_id] = NodeInfo(
                        layer_id=layer_id,
                        checked=bool(_call(child, "itemVisibilityChecked", True)),
                        visible=bool(_call(child, "isVisible", True)),
                        group_path="/" + "/".join(names),
                        ancestors=tuple(names),
                        physical_field=field,
                        tree_index=len(found),
                    )
                continue
            name = _node_name(child)
            nearest = canonical_field_name(name) if name.startswith(PROJECT_GROUP_PREFIX) else field
            walk(child, names + [name], nearest)

    walk(root, [], None)
    return found


def _status_from(diagnostics, *, in_tree: bool = True, field_status: str = "") -> str:
    if not in_tree:
        return STATUS_NOT_IN_TREE
    if field_status == FIELD_AMBIGUOUS:
        return STATUS_AMBIGUOUS
    severities = {item.severity for item in diagnostics}
    if severities & {SEVERITY_ERROR, SEVERITY_WARNING}:
        return STATUS_WARNING
    if SEVERITY_INFO in severities:
        return STATUS_NOTE
    return STATUS_OK


def _placement(context, info: NodeInfo | None) -> tuple[CategoryDefinition, str]:
    ancestors = info.ancestors if info is not None else ()
    if context.is_temporary or PREVIEW_SECTION in ancestors:
        return PREVIEW_CATEGORY, KIND_PREVIEW
    definition = definition_for_role(context.role) if context.role else None
    if definition is None or context.role_source == SOURCE_HEURISTIC:
        return AUXILIARY_CATEGORY, KIND_AUXILIARY
    if AUXILIARY_SECTION in ancestors and not context.is_generated and not context.role_trusted:
        return AUXILIARY_CATEGORY, KIND_AUXILIARY
    category = _SECTION_CATEGORY.get(definition.section)
    if category is None:
        return AUXILIARY_CATEGORY, KIND_AUXILIARY
    return category, KIND_OFFICIAL if context.role in OFFICIAL_ROLES else KIND_OPERATIONAL


def _failed_layer(layer, info: NodeInfo | None, exc) -> LogicalLayer:
    layer_id = _layer_id(layer)
    diagnostics = (
        Diagnostic(DESCRIBE_FAILED, SEVERITY_WARNING, f"Não foi possível ler o contexto da camada ({exc}).", layer_id),
    )
    geometry, code = layer_geometry(layer)
    return LogicalLayer(
        layer_id=layer_id,
        name=_layer_name(layer),
        geometry=geometry,
        geometry_code=code,
        in_tree=info is not None,
        visible_checked=info.checked if info else False,
        visible_effective=info.visible if info else False,
        group_path=info.group_path if info else "",
        field_id=None,
        field_status=FIELD_UNRESOLVED,
        field_candidates=(),
        role="",
        role_source="",
        section="",
        category=AUXILIARY_CATEGORY.code,
        kind=KIND_AUXILIARY,
        status=_status_from(diagnostics, in_tree=info is not None),
        diagnostics=diagnostics,
    )


def logical_layer(layer, context, info: NodeInfo | None, *, extra_diagnostics=()) -> LogicalLayer:
    category, kind = _placement(context, info)
    diagnostics = list(context.diagnostics) + list(extra_diagnostics)
    field_status = context.field.status
    field_id = context.field.field_id if context.field.resolved else None
    if field_id is not None and not is_valid_field_id(field_id):
        diagnostics.append(
            Diagnostic(
                INVALID_FIELD_GROUP,
                SEVERITY_WARNING,
                f"O grupo '{context.field.group_name}' não é um talhão válido; a camada não foi associada.",
                context.layer_id,
            )
        )
        field_id = None
        field_status = FIELD_UNRESOLVED
    geometry, code = layer_geometry(layer)
    in_tree = info is not None
    return LogicalLayer(
        layer_id=context.layer_id,
        name=context.name,
        geometry=geometry,
        geometry_code=code,
        in_tree=in_tree,
        visible_checked=info.checked if info else False,
        visible_effective=info.visible if info else False,
        group_path=info.group_path if info else "",
        field_id=field_id,
        field_status=field_status,
        field_candidates=context.field.candidates,
        role=context.role,
        role_source=context.role_source,
        section=context.section,
        category=category.code,
        kind=kind,
        status=_status_from(diagnostics, in_tree=in_tree, field_status=field_status),
        diagnostics=tuple(diagnostics),
    )


def _with_diagnostic(entry: LogicalLayer, diagnostic: Diagnostic) -> LogicalLayer:
    diagnostics = entry.diagnostics + (diagnostic,)
    return replace(
        entry,
        diagnostics=diagnostics,
        status=_status_from(diagnostics, in_tree=entry.in_tree, field_status=entry.field_status),
    )


def _sorted(entries) -> tuple:
    return tuple(sorted(entries, key=lambda item: (role_order_index(item[0].role), item[1])))


def _categories(entries, *, keep_empty: bool) -> tuple:
    found = []
    for definition in ALL_CATEGORIES:
        members = [item for item in entries if item[0].category == definition.code]
        if members or (keep_empty and definition in LOGICAL_CATEGORIES):
            found.append(LogicalCategory(definition, tuple(entry for entry, _index in _sorted(members))))
    return tuple(found)


def _field_level_diagnostics(field_id: str, paths: tuple, entries) -> list:
    found = []
    if len(paths) > 1:
        found.append(
            Diagnostic(
                DUPLICATE_FIELD_GROUPS,
                SEVERITY_WARNING,
                f"{len(paths)} grupos para o talhão '{field_id}' ({', '.join(paths)}); "
                "eles compartilham o mesmo GeoPackage. Nada foi unificado.",
            )
        )
    role = field_named_after_layer(field_id)
    if role:
        found.append(
            Diagnostic(
                FIELD_GROUP_NAMED_AFTER_LAYER,
                SEVERITY_WARNING,
                f"O talhão '{field_id}' tem nome de camada ({role}); provavelmente foi criado ao escolher "
                "a camada como talhão. Nada foi renomeado.",
            )
        )
    by_role: dict[str, list] = {}
    for entry, _index in entries:
        if entry.role and entry.kind in (KIND_OFFICIAL, KIND_OPERATIONAL):
            by_role.setdefault(entry.role, []).append(entry.name)
    for role_name, names in sorted(by_role.items()):
        if len(names) > 1:
            found.append(
                Diagnostic(
                    DUPLICATE_ROLE_IN_FIELD,
                    SEVERITY_WARNING,
                    f"Papel {role_name} em {len(names)} camadas do talhão ({', '.join(names)}); "
                    "os exportadores podem usar qualquer uma delas.",
                )
            )
    return found


def build_logical_tree(root, layers, fields, *, describe, field_diagnostics=None, geometry_risk=None) -> LogicalTree:
    """Monta a arvore logica; so le. 'describe' e 'field_diagnostics' vem do contexto da 0B.

    field_diagnostics(field_id, signature) recebe a visibilidade das camadas do grupo
    para permitir cache; geometry_risk(layer, context) devolve diagnosticos extras.
    """
    nodes = layer_nodes(root)
    valid: dict[str, tuple[str, list]] = {}
    tree_diagnostics = []
    for item in fields:
        if not is_valid_field_id(item.field_id):
            tree_diagnostics.append(
                Diagnostic(
                    INVALID_FIELD_GROUP,
                    SEVERITY_WARNING,
                    f"O grupo '{item.path}' não é um talhão válido; suas camadas ficam em 'Sem talhão definido'.",
                )
            )
            continue
        valid.setdefault(item.field_id.casefold(), (item.field_id, []))[1].append(item.path)

    grouped: dict[str, list] = {key: [] for key in valid}
    unassociated = []
    for layer in layers:
        layer_id = _layer_id(layer)
        info = nodes.get(layer_id)
        index = info.tree_index if info is not None else len(nodes)
        try:
            context = describe(layer)
            extra = geometry_risk(layer, context) if geometry_risk is not None else ()
            entry = logical_layer(layer, context, info, extra_diagnostics=extra)
        except Exception as exc:
            entry = _failed_layer(layer, info, exc)
        key = entry.field_id.casefold() if entry.field_id else ""
        (grouped[key] if key in grouped else unassociated).append((entry, index))

    built = []
    for key, (field_id, paths) in valid.items():
        entries = grouped[key]
        diagnostics = _field_level_diagnostics(field_id, tuple(paths), entries)
        if field_diagnostics is not None:
            signature = tuple(
                sorted((info.layer_id, info.visible) for info in nodes.values()
                       if info.physical_field and info.physical_field.casefold() == key)
            )
            diagnostics.extend(field_diagnostics(field_id, signature))
        if any(item.code == MULTIPLE_APPLICABLE_BOUNDARIES for item in diagnostics):
            entries = [
                (
                    _with_diagnostic(
                        entry,
                        Diagnostic(
                            BOUNDARY_VISIBLE_WITH_OTHER,
                            SEVERITY_WARNING,
                            "Limite visível junto com outro limite do talhão; a exportação do Precision Ag "
                            "aceita um só. Nenhum limite foi ocultado automaticamente.",
                            entry.layer_id,
                        ),
                    )
                    if entry.role in AG_BOUNDARY_ROLES and entry.visible_effective and entry.kind != KIND_PREVIEW
                    else entry,
                    index,
                )
                for entry, index in entries
            ]
        built.append(
            LogicalField(key, field_id, tuple(paths), _categories(entries, keep_empty=True), tuple(diagnostics))
        )

    outside = []
    if unassociated:
        ambiguous = sum(1 for entry, _index in unassociated if entry.field_status == FIELD_AMBIGUOUS)
        detail = f" ({ambiguous} com talhão ambíguo)" if ambiguous else ""
        outside.append(
            Diagnostic(
                UNASSOCIATED_LAYERS,
                SEVERITY_INFO,
                f"{len(unassociated)} camada(s) fora de um grupo '{PROJECT_GROUP_PREFIX}<talhão>'{detail}; "
                "nenhuma foi associada automaticamente.",
            )
        )
    if not valid:
        tree_diagnostics.append(
            Diagnostic(NO_FIELD_GROUPS, SEVERITY_INFO, f"Nenhum grupo '{PROJECT_GROUP_PREFIX}<talhão>' no projeto.")
        )
    return LogicalTree(
        fields=tuple(built),
        unassociated=LogicalField("", None, (), _categories(unassociated, keep_empty=False), tuple(outside)),
        diagnostics=tuple(tree_diagnostics),
    )


# ------------------------------------------------------- modelo com cache ----
class LayerOrganizerModel:
    """Cache do contexto por camada; visibilidade nao invalida o cache.

    So os diagnosticos de exportacao do talhao cuja visibilidade mudou sao refeitos.
    """

    def __init__(self, service, *, geometry_risk=None):
        self.service = service
        self.geometry_risk = geometry_risk
        self._contexts: dict = {}
        self._risks: dict = {}
        self._field_cache: dict = {}
        self._groups = None
        self._layers = None
        self.tree: LogicalTree | None = None
        self.stats = {"builds": 0, "describe_calls": 0, "field_diagnostic_calls": 0}

    def invalidate(self, layer_ids=None) -> None:
        if layer_ids is None:
            self._contexts.clear()
            self._risks.clear()
        else:
            for layer_id in layer_ids:
                self._contexts.pop(layer_id, None)
                self._risks.pop(layer_id, None)
        self._field_cache.clear()

    def _describe(self, layer):
        layer_id = _layer_id(layer)
        context = self._contexts.get(layer_id)
        if context is None:
            context = self.service.describe_layer(layer, groups=self._groups, project_layers=self._layers)
            self.stats["describe_calls"] += 1
            self._contexts[layer_id] = context
        return context

    def _geometry_risk(self, layer, context):
        if self.geometry_risk is None:
            return ()
        layer_id = _layer_id(layer)
        if layer_id not in self._risks:
            self._risks[layer_id] = tuple(self.geometry_risk(layer, context))
        return self._risks[layer_id]

    def _field_diagnostics(self, field_id, signature):
        key = field_id.casefold()
        cached = self._field_cache.get(key)
        if cached is not None and cached[0] == signature:
            return cached[1]
        diagnostics = tuple(self.service.export_diagnostics(field_id))
        self.stats["field_diagnostic_calls"] += 1
        self._field_cache[key] = (signature, diagnostics)
        return diagnostics

    def build(self) -> LogicalTree:
        layers = list((_call(self.service.project, "mapLayers", {}) or {}).values())
        current = {_layer_id(layer) for layer in layers}
        for stale in set(self._contexts) - current:
            self._contexts.pop(stale, None)
            self._risks.pop(stale, None)
        self._groups = self.service.available_fields()
        self._layers = layers
        try:
            self.tree = build_logical_tree(
                self.service.project.layerTreeRoot(),
                layers,
                self._groups,
                describe=self._describe,
                field_diagnostics=self._field_diagnostics,
                geometry_risk=self._geometry_risk,
            )
        finally:
            self._groups = None
            self._layers = None
        self.stats["builds"] += 1
        return self.tree


class GeometryRiskChecker:
    """Tipo declarado da camada em memoria x tabela do GPKG do talhao (so cabecalho, sem feicoes)."""

    def __init__(self, storage_path, read_table_type):
        self._storage_path = storage_path
        self._read = read_table_type
        self._cache: dict = {}

    def table_type(self, path, table: str) -> int | None:
        try:
            stamp = os.stat(path).st_mtime_ns
        except OSError:
            return None
        key = (str(path), table)
        cached = self._cache.get(key)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        value = self._read(path, table)
        self._cache[key] = (stamp, value)
        return value

    def __call__(self, layer, context) -> tuple:
        if not (
            context.is_generated
            and context.storage == STORAGE_MEMORY
            and not context.is_temporary
            and context.field.resolved
        ):
            return ()
        definition = definition_for_role(context.role) if context.role else None
        layer_type = flat_wkb_type(_call(layer, "wkbType"))
        if definition is None or layer_type is None:
            return ()
        path = self._storage_path(context.field.field_id)
        if path is None:
            return ()
        table_type = self.table_type(path, definition.display_name)
        if table_type is None:
            return ()
        code = classify_declared_types(table_type, layer_type)
        if not code:
            return ()
        text = GEOMETRY_MESSAGES[code].format(geometry=geometry_label(layer_type), table=geometry_label(table_type))
        return (
            Diagnostic(
                GEOMETRY_WRITE_RISK,
                SEVERITY_WARNING,
                f"Ao persistir, a camada iria para a tabela '{definition.display_name}' do GeoPackage do talhão: "
                f"{text} [{code}]. Verificado só pelo tipo declarado, sem ler feições; nada foi gravado.",
                context.layer_id,
            ),
        )


# ---------------------------------------------------------- visibilidade ----
@dataclass(frozen=True)
class VisibilityReport:
    changed: tuple = ()
    unchanged: tuple = ()
    missing: tuple = ()
    kept: tuple = ()

    def text(self, *, restoring: bool = False) -> str:
        if restoring:
            parts = [f"Visibilidade anterior restaurada em {len(self.changed)} camada(s)."]
        else:
            parts = [f"Visibilidade alterada em {len(self.changed)} camada(s)."]
        if self.kept:
            parts.append(
                f"{len(self.kept)} alterada(s) depois no QGIS foram mantidas: {', '.join(self.kept)}."
            )
        if self.missing:
            parts.append(f"{len(self.missing)} não estão mais na árvore: {', '.join(self.missing)}.")
        return " ".join(parts)


class VisibilityJournal:
    """Visibilidade so no no original da camada; guarda o estado anterior para restaurar.

    Ao restaurar, camadas mudadas depois no QGIS mantem a escolha do usuario e aparecem
    no relatorio; nada e restaurado em silencio por cima dela.
    """

    def __init__(self):
        self._entries: dict[str, list] = {}

    @property
    def pending(self) -> int:
        return len(self._entries)

    def forget(self) -> None:
        self._entries.clear()

    @staticmethod
    def _node(root, layer_id):
        finder = getattr(root, "findLayer", None)
        return finder(layer_id) if callable(finder) else None

    def apply(self, root, layer_ids, visible: bool) -> VisibilityReport:
        changed, unchanged, missing = [], [], []
        for layer_id in layer_ids:
            node = self._node(root, layer_id)
            if node is None:
                missing.append(layer_id)
                continue
            name = _node_name(node)
            current = bool(node.itemVisibilityChecked())
            if current == bool(visible):
                unchanged.append(name)
                continue
            entry = self._entries.get(layer_id)
            if entry is None:
                self._entries[layer_id] = [current, bool(visible), name]
            elif entry[0] == bool(visible):
                del self._entries[layer_id]
            else:
                entry[1] = bool(visible)
            node.setItemVisibilityChecked(bool(visible))
            changed.append(name)
        return VisibilityReport(tuple(changed), tuple(unchanged), tuple(missing))

    def restore(self, root) -> VisibilityReport:
        changed, missing, kept = [], [], []
        for layer_id, (original, applied, name) in list(self._entries.items()):
            node = self._node(root, layer_id)
            if node is None:
                missing.append(name)
            elif bool(node.itemVisibilityChecked()) != applied:
                kept.append(name)
            else:
                node.setItemVisibilityChecked(original)
                changed.append(name)
        self._entries.clear()
        return VisibilityReport(tuple(changed), (), tuple(missing), tuple(kept))
