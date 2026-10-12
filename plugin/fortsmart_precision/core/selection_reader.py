# -*- coding: utf-8 -*-
"""Leitura da selecao nativa do QGIS (Subfase 0E).

A selecao do QGIS e a unica fonte: nada aqui guarda uma selecao propria. Cada
leitura consulta `selectedFeatureIds()` da camada naquele momento.
"""

from __future__ import annotations

from dataclasses import dataclass

from .logical_layer_tree import flat_wkb_type, geometry_label
from .project_context import (
    SEVERITY_INFO,
    SEVERITY_WARNING,
    Diagnostic,
    _call,
)

DEFAULT_LIMIT = 500

IDENTITY_ATTRIBUTES = ("fs_id", "line_id")

ID_ATTRIBUTE = "ATTRIBUTE"
ID_PROVIDER_KEY = "PROVIDER_KEY"
ID_SESSION = "SESSION"
ID_UNSTABLE = "UNSTABLE"
ID_NEW = "NEW"
STABLE_SOURCES = (ID_ATTRIBUTE, ID_PROVIDER_KEY)
IDENTITY_LABELS = {
    ID_ATTRIBUTE: "atributo FortSmart",
    ID_PROVIDER_KEY: "chave do arquivo",
    ID_SESSION: "só nesta sessão",
    ID_UNSTABLE: "pode mudar após edição",
    ID_NEW: "feição nova não salva",
}

LINE_CODES = frozenset({2, 5, 8, 9, 11})
POLYGON_CODES = frozenset({3, 6, 10, 12, 15, 16, 17})
POINT_CODES = frozenset({1, 4})

DUPLICATE_IDENTITY = "DUPLICATE_IDENTITY"
UNSTABLE_IDENTITY = "UNSTABLE_IDENTITY"
SESSION_IDENTITY = "SESSION_IDENTITY"
UNSAVED_FEATURES = "UNSAVED_FEATURES"
SELECTION_TRUNCATED = "SELECTION_TRUNCATED"


@dataclass(frozen=True)
class FeatureIdentity:
    fid: int
    source: str
    value: str

    @property
    def key(self) -> str:
        return f"{self.source}:{self.value}"

    @property
    def stable(self) -> bool:
        return self.source in STABLE_SOURCES


@dataclass(frozen=True)
class SelectionInfo:
    layer_id: str
    layer_name: str
    role: str
    role_trusted: bool
    field: object
    crs: object
    geometry_code: int | None
    count: int
    features: tuple = ()
    truncated: bool = False
    diagnostics: tuple = ()

    @property
    def geometry(self) -> str:
        return geometry_label(self.geometry_code)

    @property
    def is_line(self) -> bool:
        return self.geometry_code in LINE_CODES

    @property
    def is_polygon(self) -> bool:
        return self.geometry_code in POLYGON_CODES

    @property
    def single_line(self) -> bool:
        return self.is_line and self.count == 1

    @property
    def multiple_lines(self) -> bool:
        return self.is_line and self.count > 1

    @property
    def fids(self) -> tuple:
        return tuple(item.fid for item in self.features)

    def text(self) -> str:
        if not self.count:
            return "nenhuma feição selecionada"
        noun = ("linha selecionada", "linhas selecionadas") if self.is_line else (
            "feição selecionada", "feições selecionadas")
        parts = [f"{self.count} {noun[0] if self.count == 1 else noun[1]}"]
        if self.features:
            sources = sorted({item.source for item in self.features})
            parts.append("ID: " + ", ".join(IDENTITY_LABELS[source] for source in sources))
            shown = ", ".join(item.value for item in self.features[:5])
            parts.append(shown + (" …" if self.count > 5 else ""))
        return " · ".join(parts)


def _clean(value) -> str:
    if value is None:
        return ""
    if callable(getattr(value, "isNull", None)):
        try:
            if value.isNull():
                return ""
        except Exception:
            pass
    text = str(value).strip()
    return "" if text.upper() in ("NULL", "NONE") else text


def provider_key_indexes(layer) -> tuple:
    provider = _call(layer, "dataProvider")
    indexes = _call(provider, "pkAttributeIndexes", []) if provider is not None else []
    return tuple(int(index) for index in (indexes or ()))


def identity_attribute(layer) -> str | None:
    fields = _call(layer, "fields")
    names = {str(field.name()).casefold(): str(field.name()) for field in (fields or [])}
    return next((names[name] for name in IDENTITY_ATTRIBUTES if name in names), None)


def classify_identity(fid: int, *, attribute_value: str = "", provider: str = "", has_provider_key: bool = False):
    """Origem do identificador de uma feicao, da mais para a menos estavel."""
    fid = int(fid)
    if attribute_value:
        return FeatureIdentity(fid, ID_ATTRIBUTE, attribute_value)
    if fid < 0:
        return FeatureIdentity(fid, ID_NEW, str(fid))
    if has_provider_key:
        return FeatureIdentity(fid, ID_PROVIDER_KEY, str(fid))
    if provider == "memory":
        return FeatureIdentity(fid, ID_SESSION, str(fid))
    return FeatureIdentity(fid, ID_UNSTABLE, str(fid))


def identity_diagnostics(identities, *, layer_id: str = "", truncated: bool = False, count: int = 0) -> tuple:
    found = []
    seen = {}
    duplicates = set()
    for item in identities:
        if item.source != ID_ATTRIBUTE:
            continue
        if item.value in seen:
            duplicates.add(item.value)
        seen[item.value] = item.fid
    if duplicates:
        found.append(Diagnostic(
            DUPLICATE_IDENTITY, SEVERITY_WARNING,
            f"Identificador repetido na seleção: {', '.join(sorted(duplicates))}.", layer_id))
    sources = {item.source for item in identities}
    if ID_UNSTABLE in sources:
        found.append(Diagnostic(
            UNSTABLE_IDENTITY, SEVERITY_WARNING,
            "Formato sem chave própria: o identificador pode mudar após edição ou compactação.", layer_id))
    if ID_SESSION in sources:
        found.append(Diagnostic(
            SESSION_IDENTITY, SEVERITY_INFO,
            "Camada temporária: o identificador vale só enquanto a camada existir.", layer_id))
    if ID_NEW in sources:
        found.append(Diagnostic(
            UNSAVED_FEATURES, SEVERITY_INFO,
            "Há feições novas ainda não salvas; o identificador muda ao salvar.", layer_id))
    if truncated:
        found.append(Diagnostic(
            SELECTION_TRUNCATED, SEVERITY_INFO,
            f"Seleção com {count} feições; só as primeiras foram identificadas.", layer_id))
    return tuple(found)


def is_vector(layer) -> bool:
    return layer is not None and callable(getattr(layer, "selectedFeatureIds", None))


def _request(fids, attribute_indexes, with_geometry: bool):
    from qgis.core import QgsFeatureRequest

    request = QgsFeatureRequest().setFilterFids(list(fids))
    request.setSubsetOfAttributes(list(attribute_indexes))
    if not with_geometry:
        request.setFlags(QgsFeatureRequest.NoGeometry)
    return request


def read_selection(layer, service, *, limit: int = DEFAULT_LIMIT) -> SelectionInfo | None:
    """Selecao atual da camada; None se nao houver camada vetorial."""
    if not is_vector(layer):
        return None
    context = service.describe_layer(layer)
    fids = sorted(int(fid) for fid in (layer.selectedFeatureIds() or ()))
    count = len(fids)
    wanted = fids[:limit]
    attribute = identity_attribute(layer)
    attribute_index = layer.fields().indexOf(attribute) if attribute else -1
    provider = str(_call(layer, "providerType", "") or "")
    has_key = bool(provider_key_indexes(layer))
    values = {}
    if wanted and attribute_index >= 0:
        for feature in layer.getFeatures(_request(wanted, [attribute_index], False)):
            values[int(feature.id())] = _clean(feature.attribute(attribute_index))
    identities = tuple(
        classify_identity(fid, attribute_value=values.get(fid, ""), provider=provider, has_provider_key=has_key)
        for fid in wanted
    )
    truncated = count > len(wanted)
    return SelectionInfo(
        layer_id=context.layer_id,
        layer_name=context.name,
        role=context.role,
        role_trusted=context.role_trusted,
        field=context.field,
        crs=context.crs,
        geometry_code=flat_wkb_type(_call(layer, "wkbType")),
        count=count,
        features=identities,
        truncated=truncated,
        diagnostics=identity_diagnostics(identities, layer_id=context.layer_id, truncated=truncated, count=count),
    )


def selected_geometries(layer, *, limit: int = DEFAULT_LIMIT) -> list:
    """(fid, geometria) das feicoes selecionadas, no CRS da camada; so leitura."""
    if not is_vector(layer):
        return []
    fids = sorted(int(fid) for fid in (layer.selectedFeatureIds() or ()))[:limit]
    if not fids:
        return []
    found = []
    for feature in layer.getFeatures(_request(fids, [], True)):
        geometry = feature.geometry()
        if geometry is not None and not geometry.isNull() and not geometry.isEmpty():
            found.append((int(feature.id()), geometry))
    return found
