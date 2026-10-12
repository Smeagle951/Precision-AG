# -*- coding: utf-8 -*-
"""Contexto somente leitura do projeto FortSmart: talhao, papel, selecao e CRS.

Reutiliza o catalogo de layer_roles (nenhum catalogo novo). Nao cria grupos,
camadas nem arquivos e nao grava metadados. O talhao vem do grupo
'FORTSMART - <talhao>' que contem a camada ou de escolha explicita; o nome da
camada nunca define o talhao. Os diagnosticos de exportacao reproduzem as
regras do FortSmart Precision Ag sem importar o Ag.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from .crs import SIRGAS_UTM_SOUTH_GUIDE, inspect_authid
from .layer_roles import (
    INTERNAL_KEY_PROPERTY,
    PROJECT_GROUP_PREFIX,
    SECTION_ORDER,
    PREVIEW_SECTION,
    SOURCE_INTERNAL_KEY,
    SOURCE_ROLE,
    canonical_field_name,
    classify_layer,
    definition_for_role,
    is_generated_layer,
    is_temporary_preview,
    layer_field_id,
    layer_role,
    storage_kind,
)

FIELD_RESOLVED = "RESOLVED"
FIELD_AMBIGUOUS = "AMBIGUOUS"
FIELD_UNRESOLVED = "UNRESOLVED"

SOURCE_PROJECT_GROUP = "project_group"
SOURCE_EXPLICIT = "explicit"
SOURCE_LAYER_METADATA = "layer_metadata"
SOURCE_OTHER_GROUP = "group"
SOURCE_ATTRIBUTE = "attribute"

SEVERITY_INFO = "INFO"
SEVERITY_WARNING = "WARNING"
SEVERITY_ERROR = "ERROR"

LAYER_NOT_IN_TREE = "LAYER_NOT_IN_TREE"
LAYER_OUTSIDE_FIELD_GROUP = "LAYER_OUTSIDE_FIELD_GROUP"
FIELD_METADATA_CONFLICT = "FIELD_METADATA_CONFLICT"
DUPLICATE_FIELD_GROUP = "DUPLICATE_FIELD_GROUP"
EXPLICIT_FIELD_DIFFERS_FROM_LAYER = "EXPLICIT_FIELD_DIFFERS_FROM_LAYER"
FIELD_NOT_SELECTED = "FIELD_NOT_SELECTED"
REPROJECTED_COPY = "REPROJECTED_COPY"
REPROJECTED_COPY_WITHOUT_METADATA = "REPROJECTED_COPY_WITHOUT_METADATA"
ROLE_BY_NAME_ONLY = "ROLE_BY_NAME_ONLY"
ROLE_ONLY_IN_ATTRIBUTE = "ROLE_ONLY_IN_ATTRIBUTE"
ROLE_ATTRIBUTE_CONFLICT = "ROLE_ATTRIBUTE_CONFLICT"
ROLE_UNKNOWN_TO_AG = "ROLE_UNKNOWN_TO_AG"
AG_GROUP_DIFFERS = "AG_GROUP_DIFFERS"
MULTIPLE_APPLICABLE_BOUNDARIES = "MULTIPLE_APPLICABLE_BOUNDARIES"
NO_APPLICABLE_BOUNDARY = "NO_APPLICABLE_BOUNDARY"
FIELD_ERID_INCONSISTENT = "FIELD_ERID_INCONSISTENT"
FIELD_ERID_INVALID = "FIELD_ERID_INVALID"
CRS_INVALID = "CRS_INVALID"
CRS_GEOGRAPHIC = "CRS_GEOGRAPHIC"
CRS_NOT_METRIC = "CRS_NOT_METRIC"
FARM_NOT_RECORDED = "FARM_NOT_RECORDED"
FARM_AMBIGUOUS = "FARM_AMBIGUOUS"

# Espelho do FortSmart Precision Ag 2.9.20 (somente leitura; conferido nos testes).
AG_SECTIONS = frozenset({"00_REFERENCIAS", "10_PLANEJAMENTO", "20_OBSTACULOS", "30_OPERACAO"})
AG_FIELD_NAME_RE = re.compile(r"^(?:TL|TALH[AÃ]O|FIELD)[ _-]*[A-Z0-9.-]+$", re.IGNORECASE)
AG_KNOWN_ROLES = frozenset({
    "EXTERNAL_BOUNDARY",
    "OPERATIONAL_BOUNDARY",
    "INTERNAL_BOUNDARY",
    "HEADLAND",
    "AB_LINE",
    "AB_CURVE",
    "GUIDANCE_TRACK",
    "OBSTACLE",
    "SAFETY_ZONE",
    "WORK_PATH",
    "FINAL_WORK_PATH",
    "TRACTOR_PATH",
    "TIRE_TRACK",
    "FIELD_HEADLAND_PATH",
    "HEADLAND_TURN",
    "OBSTACLE_DETOUR",
    "WORK_OFF",
    "WORK_ON",
    "SHUTOFF",
    "MARKER",
})
# Os dois viram LIMITE no Ag; o John Deere aceita uma unica feicao LIMITE por talhao.
AG_BOUNDARY_ROLES = frozenset({"EXTERNAL_BOUNDARY", "OPERATIONAL_BOUNDARY"})
AG_ROLE_ATTRIBUTES = ("fortsmart_role", "role")
FIELD_ERID_ATTRIBUTE = "field_erid"
FARM_ATTRIBUTES = ("fazenda", "farm")

REPROJECTED_NAME_RE = re.compile(r"^(?P<base>.*?)\s*\((?P<authid>EPSG:\d+)\)\s*$", re.IGNORECASE)
TRUSTED_ROLE_SOURCES = (SOURCE_ROLE, SOURCE_INTERNAL_KEY)
_FORTSMART_STANDARD_CRS = frozenset(authid for authid, _hint in SIRGAS_UTM_SOUTH_GUIDE.values())


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: str
    message: str
    layer_id: str = ""


@dataclass(frozen=True)
class FieldGroup:
    field_id: str
    group_name: str
    path: str


@dataclass(frozen=True)
class FieldResolution:
    status: str
    field_id: str | None = None
    source: str = ""
    group_name: str = ""
    candidates: tuple = ()

    @property
    def resolved(self) -> bool:
        return self.status == FIELD_RESOLVED


@dataclass(frozen=True)
class FarmResolution:
    status: str
    name: str | None = None
    source: str = ""
    candidates: tuple = ()


@dataclass(frozen=True)
class CrsSummary:
    authid: str
    is_valid: bool
    is_geographic: bool
    is_metric: bool
    is_fortsmart_standard: bool


@dataclass(frozen=True)
class ReprojectionInfo:
    base_name: str
    declared_authid: str
    source_layer_ids: tuple
    has_fortsmart_metadata: bool
    attribute_roles: tuple


@dataclass(frozen=True)
class LayerContext:
    layer_id: str
    name: str
    role: str
    role_source: str
    role_trusted: bool
    section: str
    display_name: str
    is_generated: bool
    is_temporary: bool
    storage: str
    field: FieldResolution
    ag_group_name: str | None
    crs: CrsSummary | None
    selected_count: int
    is_editing: bool
    reprojection: ReprojectionInfo | None
    diagnostics: tuple = ()


@dataclass(frozen=True)
class ProjectContext:
    project_file: str
    project_title: str
    project_saved: bool
    project_crs: CrsSummary | None
    fields: tuple
    field: FieldResolution
    explicit_field: str | None
    farm: FarmResolution
    active_layer: LayerContext | None
    field_layer_ids: tuple
    diagnostics: tuple = ()


# ------------------------------------------------------------ arvore ------
def _call(obj, name, default=None):
    getter = getattr(obj, name, None)
    if not callable(getter):
        return default
    try:
        return getter()
    except Exception:
        return default


def _custom_property(layer, key: str):
    getter = getattr(layer, "customProperty", None)
    if not callable(getter):
        return None
    try:
        return getter(key, None)
    except Exception:
        return None


def _is_layer_node(node) -> bool:
    return callable(getattr(node, "layer", None))


def _node_name(node) -> str:
    return str(_call(node, "name", "") or "")


def _ancestors(node, root) -> list:
    found = []
    parent = _call(node, "parent")
    while parent is not None and parent is not root:
        found.append(parent)
        parent = _call(parent, "parent")
    return found


def _group_path(group, root) -> str:
    names = [_node_name(group)] + [_node_name(item) for item in _ancestors(group, root)]
    return "/" + "/".join(reversed(names))


def _is_field_group(node) -> bool:
    return not _is_layer_node(node) and _node_name(node).startswith(PROJECT_GROUP_PREFIX)


def _walk_groups(node):
    for child in _call(node, "children", []) or []:
        if _is_layer_node(child):
            continue
        yield child
        yield from _walk_groups(child)


def field_groups(root) -> tuple[FieldGroup, ...]:
    """Grupos 'FORTSMART - <talhao>' do projeto, na ordem da arvore."""
    return tuple(
        FieldGroup(canonical_field_name(_node_name(group)), _node_name(group), _group_path(group, root))
        for group in _walk_groups(root)
        if _is_field_group(group)
    )


def _same_field(left: str | None, right: str | None) -> bool:
    return bool(left) and bool(right) and str(left).casefold() == str(right).casefold()


def _layer_id(layer) -> str:
    return str(_call(layer, "id", "") or "")


def _layer_name(layer) -> str:
    return str(_call(layer, "name", "") or "")


def _find_layer_node(root, layer):
    finder = getattr(root, "findLayer", None)
    if layer is None or not callable(finder):
        return None
    try:
        return finder(_layer_id(layer))
    except Exception:
        return None


def resolve_layer_field(root, layer, *, groups=None) -> tuple[FieldResolution, tuple[Diagnostic, ...]]:
    """Talhao da camada pela arvore; metadado divergente vira ambiguidade, nunca escolha.

    'groups' (field_groups(root) ja calculado) evita refazer a varredura por camada.
    """
    layer_id = _layer_id(layer)
    node = _find_layer_node(root, layer)
    if node is None:
        return FieldResolution(FIELD_UNRESOLVED), (
            Diagnostic(LAYER_NOT_IN_TREE, SEVERITY_WARNING, "A camada não está na árvore de camadas do projeto.", layer_id),
        )
    ancestors = _ancestors(node, root)
    owner = next((group for group in ancestors if _is_field_group(group)), None)
    metadata = layer_field_id(layer)
    if owner is not None:
        group_field = canonical_field_name(_node_name(owner))
        if metadata and not _same_field(metadata, group_field):
            return (
                FieldResolution(
                    FIELD_AMBIGUOUS,
                    candidates=((group_field, SOURCE_PROJECT_GROUP), (metadata, SOURCE_LAYER_METADATA)),
                ),
                (
                    Diagnostic(
                        FIELD_METADATA_CONFLICT,
                        SEVERITY_WARNING,
                        f"A camada está no grupo do talhão '{group_field}', mas o metadado indica "
                        f"'{metadata}'. Escolha o talhão explicitamente.",
                        layer_id,
                    ),
                ),
            )
        diagnostics = ()
        known = field_groups(root) if groups is None else groups
        same = [item for item in known if _same_field(item.field_id, group_field)]
        if len(same) > 1:
            diagnostics = (
                Diagnostic(
                    DUPLICATE_FIELD_GROUP,
                    SEVERITY_WARNING,
                    f"Há {len(same)} grupos para o talhão '{group_field}' "
                    f"({', '.join(item.path for item in same)}); eles compartilham o mesmo GeoPackage.",
                    layer_id,
                ),
            )
        resolution = FieldResolution(FIELD_RESOLVED, group_field, SOURCE_PROJECT_GROUP, _node_name(owner))
        return resolution, diagnostics
    candidates = []
    if metadata:
        candidates.append((metadata, SOURCE_LAYER_METADATA))
    other = next(
        (group for group in ancestors if _node_name(group) not in SECTION_ORDER and _node_name(group) != PREVIEW_SECTION),
        None,
    )
    if other is not None:
        candidates.append((_node_name(other), SOURCE_OTHER_GROUP))
    severity = SEVERITY_WARNING if is_generated_layer(layer) else SEVERITY_INFO
    where = "na raiz do projeto" if not ancestors else f"no grupo '{_node_name(ancestors[0])}'"
    return FieldResolution(FIELD_UNRESOLVED, candidates=tuple(candidates)), (
        Diagnostic(
            LAYER_OUTSIDE_FIELD_GROUP,
            severity,
            f"A camada está {where}, fora de um grupo '{PROJECT_GROUP_PREFIX}<talhão>'; "
            "o talhão não foi associado automaticamente.",
            layer_id,
        ),
    )


def ag_field_group(root, layer):
    """Grupo que o Precision Ag usa como talhao (field_group_export._field_node)."""
    node = _find_layer_node(root, layer)
    if node is None:
        return None
    ancestors = _ancestors(node, root)
    for candidate in ancestors:
        names = {
            _node_name(child).strip().upper()
            for child in _call(candidate, "children", []) or []
        }
        if names & AG_SECTIONS:
            return candidate
    for candidate in ancestors:
        if AG_FIELD_NAME_RE.fullmatch(_node_name(candidate).strip()):
            return candidate
    for candidate in ancestors:
        name = _node_name(candidate).strip()
        if name.upper() not in AG_SECTIONS and not name.startswith("FortSmart"):
            return candidate
    return None


# --------------------------------------------------------- atributos ------
def _is_null(value) -> bool:
    if value is None:
        return True
    checker = getattr(value, "isNull", None)
    try:
        return bool(checker()) if callable(checker) else False
    except Exception:
        return False


def _field_index(layer, name: str) -> int:
    fields = _call(layer, "fields")
    names = _call(fields, "names", []) if fields is not None else []
    for index, current in enumerate(names or []):
        if str(current).casefold() == name.casefold():
            return index
    return -1


def attribute_values(layer, name: str) -> tuple[str, ...]:
    """Valores distintos e nao vazios do atributo (sem ler geometria)."""
    index = _field_index(layer, name)
    reader = getattr(layer, "uniqueValues", None)
    if index < 0 or not callable(reader):
        return ()
    try:
        values = reader(index)
    except Exception:
        return ()
    cleaned = {str(value).strip() for value in values if not _is_null(value) and str(value).strip()}
    return tuple(sorted(cleaned))


def _feature_count(layer) -> int:
    value = _call(layer, "featureCount", 0)
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------- CRS ------
def crs_summary(crs) -> CrsSummary | None:
    if crs is None:
        return None
    authid = str(_call(crs, "authid", "") or "")
    is_valid = bool(_call(crs, "isValid", bool(authid)))
    is_geographic = _call(crs, "isGeographic")
    info = inspect_authid(authid)
    if is_geographic is None:
        is_geographic = info.is_geographic
    is_metric = None
    units = _call(crs, "mapUnits")
    if units is not None:
        try:
            from qgis.core import Qgis

            is_metric = units == Qgis.DistanceUnit.Meters
        except (ImportError, AttributeError):
            is_metric = None
    if is_metric is None:
        is_metric = info.is_projected_metric
    return CrsSummary(
        authid=info.authid or authid,
        is_valid=is_valid,
        is_geographic=bool(is_geographic),
        is_metric=bool(is_metric) and not bool(is_geographic),
        is_fortsmart_standard=(info.authid or authid) in _FORTSMART_STANDARD_CRS,
    )


def crs_diagnostics(summary: CrsSummary | None, layer_id: str = "") -> tuple[Diagnostic, ...]:
    if summary is None or not summary.is_valid:
        return (Diagnostic(CRS_INVALID, SEVERITY_WARNING, "CRS ausente ou inválido.", layer_id),)
    if summary.is_geographic:
        return (
            Diagnostic(
                CRS_GEOGRAPHIC,
                SEVERITY_WARNING,
                f"CRS geográfico ({summary.authid}): área, distância e buffer exigem SIRGAS 2000 / UTM.",
                layer_id,
            ),
        )
    if not summary.is_metric:
        return (
            Diagnostic(CRS_NOT_METRIC, SEVERITY_WARNING, f"CRS {summary.authid} não usa metros.", layer_id),
        )
    return ()


# ------------------------------------------------------- reprojecao ------
def reprojection_info(layer, project_layers) -> ReprojectionInfo | None:
    """Copia 'Nome (EPSG:n)' do conversor de CRS: origem provavel e metadados presentes."""
    match = REPROJECTED_NAME_RE.match(_layer_name(layer))
    if match is None:
        return None
    base = match.group("base").strip()
    own_id = _layer_id(layer)
    sources = tuple(
        _layer_id(other)
        for other in project_layers
        if _layer_id(other) != own_id and _layer_name(other).strip() == base
    )
    has_metadata = bool(layer_role(layer) or _custom_property(layer, INTERNAL_KEY_PROPERTY))
    roles = tuple(
        sorted({value.upper() for name in AG_ROLE_ATTRIBUTES for value in attribute_values(layer, name)})
    )
    return ReprojectionInfo(base, match.group("authid").upper(), sources, has_metadata, roles)


def reprojection_diagnostics(info: ReprojectionInfo | None, layer_id: str = "") -> tuple[Diagnostic, ...]:
    if info is None:
        return ()
    origin = "origem encontrada no projeto" if info.source_layer_ids else "origem não encontrada no projeto"
    found = [
        Diagnostic(
            REPROJECTED_COPY,
            SEVERITY_INFO,
            f"Cópia reprojetada de '{info.base_name}' para {info.declared_authid} ({origin}).",
            layer_id,
        )
    ]
    if not info.has_fortsmart_metadata:
        detail = (
            f" O atributo das feições ainda indica {', '.join(info.attribute_roles)}, "
            "que o Precision Ag lê."
            if info.attribute_roles
            else ""
        )
        found.append(
            Diagnostic(
                REPROJECTED_COPY_WITHOUT_METADATA,
                SEVERITY_WARNING,
                "A cópia reprojetada não tem os metadados FortSmart (papel, talhão, chave interna); "
                f"o Planner a trata como camada do usuário.{detail} Nada foi corrigido automaticamente.",
                layer_id,
            )
        )
    return tuple(found)


# -------------------------------------------------------------- papel ------
def role_diagnostics(layer, role: str, source: str) -> tuple[Diagnostic, ...]:
    layer_id = _layer_id(layer)
    found = []
    attribute_roles = {
        value.upper() for name in AG_ROLE_ATTRIBUTES for value in attribute_values(layer, name)
    }
    declared = layer_role(layer)
    if role and source not in TRUSTED_ROLE_SOURCES:
        found.append(
            Diagnostic(
                ROLE_BY_NAME_ONLY,
                SEVERITY_INFO,
                f"Papel {role} reconhecido só pelo nome da camada ({source}); não há metadado FortSmart.",
                layer_id,
            )
        )
    if not declared and attribute_roles & AG_KNOWN_ROLES:
        found.append(
            Diagnostic(
                ROLE_ONLY_IN_ATTRIBUTE,
                SEVERITY_INFO,
                "O papel está só no atributo das feições "
                f"({', '.join(sorted(attribute_roles & AG_KNOWN_ROLES))}); o Precision Ag o usa, o Planner não.",
                layer_id,
            )
        )
    conflicting = sorted((attribute_roles & AG_KNOWN_ROLES) - {declared}) if declared else []
    if conflicting:
        found.append(
            Diagnostic(
                ROLE_ATTRIBUTE_CONFLICT,
                SEVERITY_WARNING,
                f"A camada é {declared}, mas há feições com papel {', '.join(conflicting)} no atributo; "
                "o Precision Ag usa o papel da feição.",
                layer_id,
            )
        )
    if role and role not in AG_KNOWN_ROLES:
        found.append(
            Diagnostic(
                ROLE_UNKNOWN_TO_AG,
                SEVERITY_INFO,
                f"O papel {role} não é exportado pelo Precision Ag.",
                layer_id,
            )
        )
    return tuple(found)


# --------------------------------------------------------- exportacao ------
def export_contract_diagnostics(layers, *, visible_ids=None) -> tuple[Diagnostic, ...]:
    """Contratos do Precision Ag para um talhao: limite unico, field_erid e papel."""
    layers = list(layers)
    visible = [layer for layer in layers if visible_ids is None or _layer_id(layer) in visible_ids]
    found = []
    boundaries = []
    for layer in visible:
        role, _source = classify_layer(layer)
        if role in AG_BOUNDARY_ROLES and _feature_count(layer):
            boundaries.append((layer, role, _feature_count(layer)))
    total = sum(count for _layer, _role, count in boundaries)
    if total > 1:
        detail = "; ".join(f"{_layer_name(layer)} ({role}, {count})" for layer, role, count in boundaries)
        found.append(
            Diagnostic(
                MULTIPLE_APPLICABLE_BOUNDARIES,
                SEVERITY_WARNING,
                f"{total} feições de limite visíveis no talhão ({detail}). O Precision Ag trata limite "
                "externo e operacional como LIMITE e a exportação John Deere aceita um só.",
            )
        )
    elif total == 0:
        found.append(
            Diagnostic(NO_APPLICABLE_BOUNDARY, SEVERITY_INFO, "Nenhum limite externo ou operacional visível no talhão.")
        )
    erids = {}
    for layer in layers:
        for value in attribute_values(layer, FIELD_ERID_ATTRIBUTE):
            erids.setdefault(value, []).append(_layer_name(layer))
    valid = []
    for value, names in sorted(erids.items()):
        try:
            uuid.UUID(value)
        except ValueError:
            found.append(
                Diagnostic(
                    FIELD_ERID_INVALID,
                    SEVERITY_WARNING,
                    f"field_erid '{value}' não é UUID ({', '.join(sorted(set(names)))}); o Precision Ag o ignora.",
                )
            )
            continue
        valid.append(value)
    if len(valid) > 1:
        found.append(
            Diagnostic(
                FIELD_ERID_INCONSISTENT,
                SEVERITY_WARNING,
                f"{len(valid)} valores de field_erid no mesmo talhão; o Precision Ag dividiria o talhão em "
                "mais de um pacote.",
            )
        )
    return tuple(found)


# ------------------------------------------------------------ fazenda ------
def farm_from_layers(layers) -> FarmResolution:
    values = sorted({value for layer in layers for name in FARM_ATTRIBUTES for value in attribute_values(layer, name)})
    if len(values) == 1:
        return FarmResolution(FIELD_RESOLVED, values[0], SOURCE_ATTRIBUTE)
    if values:
        return FarmResolution(FIELD_AMBIGUOUS, candidates=tuple(values), source=SOURCE_ATTRIBUTE)
    return FarmResolution(FIELD_UNRESOLVED)


# -------------------------------------------------------------- camada ------
def describe_layer(root, layer, project_layers=(), *, groups=None) -> LayerContext:
    """Contexto de uma camada; so le propriedades, arvore e atributos."""
    layer_id = _layer_id(layer)
    role, source = classify_layer(layer)
    definition = definition_for_role(role) if role else None
    resolution, field_diagnostics = resolve_layer_field(root, layer, groups=groups)
    ag_group = ag_field_group(root, layer)
    ag_name = _node_name(ag_group) if ag_group is not None else None
    diagnostics = list(field_diagnostics)
    if resolution.resolved and ag_name != resolution.group_name:
        diagnostics.append(
            Diagnostic(
                AG_GROUP_DIFFERS,
                SEVERITY_WARNING,
                f"O Precision Ag agruparia esta camada em '{ag_name or 'Sem grupo'}', "
                f"não em '{resolution.group_name}'.",
                layer_id,
            )
        )
    crs = crs_summary(_call(layer, "crs"))
    diagnostics.extend(crs_diagnostics(crs, layer_id))
    reprojection = reprojection_info(layer, project_layers)
    diagnostics.extend(reprojection_diagnostics(reprojection, layer_id))
    diagnostics.extend(role_diagnostics(layer, role, source))
    selected = _call(layer, "selectedFeatureCount", 0)
    return LayerContext(
        layer_id=layer_id,
        name=_layer_name(layer),
        role=role,
        role_source=source,
        role_trusted=source in TRUSTED_ROLE_SOURCES,
        section=definition.section if definition else "",
        display_name=definition.display_name if definition else "",
        is_generated=is_generated_layer(layer),
        is_temporary=is_temporary_preview(layer),
        storage=storage_kind(layer),
        field=resolution,
        ag_group_name=ag_name,
        crs=crs,
        selected_count=int(selected or 0),
        is_editing=bool(_call(layer, "isEditable", False)),
        reprojection=reprojection,
        diagnostics=tuple(diagnostics),
    )


# ------------------------------------------------------------ servico ------
class ProjectContextService:
    """Fonte unica de contexto para o painel; somente leitura.

    A escolha explicita do talhao fica so em memoria (nao vai para o projeto).
    """

    def __init__(self, project=None, iface=None):
        self._project = project
        self._iface = iface
        self._explicit_field: str | None = None

    @property
    def project(self):
        if self._project is None:
            from qgis.core import QgsProject

            self._project = QgsProject.instance()
        return self._project

    @property
    def explicit_field(self) -> str | None:
        return self._explicit_field

    def _root(self):
        return self.project.layerTreeRoot()

    def _layers(self) -> list:
        layers = _call(self.project, "mapLayers", {}) or {}
        return list(layers.values())

    def available_fields(self) -> tuple[FieldGroup, ...]:
        return field_groups(self._root())

    def set_explicit_field(self, field_id: str) -> str:
        wanted = canonical_field_name(field_id)
        match = next((item for item in self.available_fields() if _same_field(item.field_id, wanted)), None)
        if match is None:
            raise ValueError(f"Talhão '{field_id}' não existe como grupo '{PROJECT_GROUP_PREFIX}<talhão>' no projeto.")
        self._explicit_field = match.field_id
        return match.field_id

    def clear_explicit_field(self) -> None:
        self._explicit_field = None

    def active_layer(self):
        return _call(self._iface, "activeLayer") if self._iface is not None else None

    def describe_layer(self, layer, *, groups=None, project_layers=None) -> LayerContext:
        layers = self._layers() if project_layers is None else project_layers
        return describe_layer(self._root(), layer, layers, groups=groups)

    def field_layers(self, field_id: str) -> list:
        """Camadas dentro dos grupos do talhao (inclusive subgrupos e SIM_PREVIEW)."""
        root = self._root()
        found = {}
        for group in _walk_groups(root):
            if not _is_field_group(group) or not _same_field(canonical_field_name(_node_name(group)), field_id):
                continue
            for node in _call(group, "findLayers", []) or []:
                layer = _call(node, "layer")
                if layer is not None:
                    found.setdefault(_layer_id(layer), layer)
        return list(found.values())

    def visible_layer_ids(self, layers) -> set:
        root = self._root()
        visible = set()
        for layer in layers:
            node = _find_layer_node(root, layer)
            if node is not None and _call(node, "isVisible", True):
                visible.add(_layer_id(layer))
        return visible

    def export_diagnostics(self, field_id: str) -> tuple[Diagnostic, ...]:
        layers = [
            layer for layer in self.field_layers(field_id)
            if not is_temporary_preview(layer)
        ]
        return export_contract_diagnostics(layers, visible_ids=self.visible_layer_ids(layers))

    def snapshot(self, layer=None) -> ProjectContext:
        project = self.project
        layer = layer if layer is not None else self.active_layer()
        layer_context = self.describe_layer(layer) if layer is not None else None
        fields = self.available_fields()
        diagnostics = []
        if self._explicit_field:
            effective = FieldResolution(FIELD_RESOLVED, self._explicit_field, SOURCE_EXPLICIT)
            if (
                layer_context is not None
                and layer_context.field.resolved
                and not _same_field(layer_context.field.field_id, self._explicit_field)
            ):
                diagnostics.append(
                    Diagnostic(
                        EXPLICIT_FIELD_DIFFERS_FROM_LAYER,
                        SEVERITY_INFO,
                        f"Talhão escolhido: '{self._explicit_field}'; a camada ativa é do talhão "
                        f"'{layer_context.field.field_id}'.",
                        layer_context.layer_id,
                    )
                )
        elif layer_context is not None and layer_context.field.status != FIELD_UNRESOLVED:
            effective = layer_context.field
        else:
            candidates = tuple((item.field_id, SOURCE_PROJECT_GROUP) for item in fields)
            if layer_context is not None:
                candidates = layer_context.field.candidates + candidates
            effective = FieldResolution(FIELD_UNRESOLVED, candidates=candidates)
        if not effective.resolved:
            diagnostics.append(
                Diagnostic(
                    FIELD_NOT_SELECTED,
                    SEVERITY_INFO,
                    "Talhão não resolvido: escolha o talhão explicitamente.",
                )
            )
        field_layers = self.field_layers(effective.field_id) if effective.resolved else []
        farm = farm_from_layers(field_layers) if field_layers else FarmResolution(FIELD_UNRESOLVED)
        if effective.resolved and farm.status == FIELD_UNRESOLVED:
            diagnostics.append(
                Diagnostic(FARM_NOT_RECORDED, SEVERITY_INFO, "Fazenda não registrada nas camadas do talhão.")
            )
        elif farm.status == FIELD_AMBIGUOUS:
            diagnostics.append(
                Diagnostic(
                    FARM_AMBIGUOUS,
                    SEVERITY_WARNING,
                    f"Mais de uma fazenda nas camadas do talhão: {', '.join(farm.candidates)}.",
                )
            )
        return ProjectContext(
            project_file=str(_call(project, "fileName", "") or ""),
            project_title=str(_call(project, "title", "") or ""),
            project_saved=bool(_call(project, "fileName", "")),
            project_crs=crs_summary(_call(project, "crs")),
            fields=fields,
            field=effective,
            explicit_field=self._explicit_field,
            farm=farm,
            active_layer=layer_context,
            field_layer_ids=tuple(_layer_id(item) for item in field_layers),
            diagnostics=tuple(diagnostics),
        )
