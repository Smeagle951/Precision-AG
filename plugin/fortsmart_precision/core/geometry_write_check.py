# -*- coding: utf-8 -*-
"""Diagnostico do tipo geometrico antes de gravar numa tabela GPKG existente.

So classifica; nunca converte nem descarta geometria. Os codigos seguem o tipo
OGR "achatado" (sem Z/M): 1 Point, 2 LineString, 3 Polygon, 4 MultiPoint,
5 MultiLineString, 6 MultiPolygon, 7 GeometryCollection, 0 Unknown, 100 None.
"""

from __future__ import annotations

from dataclasses import dataclass, field

GEOMETRY_FAMILY_MISMATCH = "GEOMETRY_FAMILY_MISMATCH"
MULTIPART_INTO_SINGLE = "MULTIPART_INTO_SINGLE"
FORCED_GEOMETRY_INVALID = "FORCED_GEOMETRY_INVALID"
COLLECTION_INTO_TYPED_TABLE = "COLLECTION_INTO_TYPED_TABLE"

_FAMILY = {1: "point", 4: "point", 2: "line", 5: "line", 3: "polygon", 6: "polygon"}
_MULTI = {4, 5, 6}
_NAMES = {
    0: "Unknown",
    1: "Point",
    2: "LineString",
    3: "Polygon",
    4: "MultiPoint",
    5: "MultiLineString",
    6: "MultiPolygon",
    7: "GeometryCollection",
    100: "None",
}

MESSAGES = {
    GEOMETRY_FAMILY_MISMATCH: "tipo diferente da tabela ({geometry} em tabela {table})",
    MULTIPART_INTO_SINGLE: "geometria com varias partes em tabela de parte simples ({geometry} em tabela {table})",
    FORCED_GEOMETRY_INVALID: "geometria valida ficaria invalida ao converter para {table}",
    COLLECTION_INTO_TYPED_TABLE: "colecao de geometrias em tabela {table}",
}


def geometry_type_name(code: int) -> str:
    return _NAMES.get(int(code), f"OGR:{code}")


def classify_geometry_write(
    table_type: int,
    geometry_type: int,
    *,
    part_count: int = 1,
    valid_before: bool | None = None,
    valid_after: bool | None = None,
) -> str:
    """Codigo do problema ('' quando a gravacao preserva a geometria)."""
    table_type = int(table_type)
    geometry_type = int(geometry_type)
    if table_type in (0, 100) or table_type == geometry_type and valid_after is not False:
        return ""
    if geometry_type == 7 and table_type != 7:
        return COLLECTION_INTO_TYPED_TABLE
    table_family = _FAMILY.get(table_type)
    geometry_family = _FAMILY.get(geometry_type)
    if table_family and geometry_family and table_family != geometry_family:
        return GEOMETRY_FAMILY_MISMATCH
    if geometry_type in _MULTI and table_type not in _MULTI and int(part_count) > 1:
        return MULTIPART_INTO_SINGLE
    if valid_before is True and valid_after is False:
        return FORCED_GEOMETRY_INVALID
    return ""


def classify_declared_types(table_type: int, layer_type: int) -> str:
    """Risco so pelos tipos declarados (sem ler feicoes): camada multi em tabela simples e potencial."""
    return classify_geometry_write(table_type, layer_type, part_count=2)


@dataclass
class GeometryWriteAudit:
    """Acumula os problemas por codigo durante uma gravacao (uma tabela)."""

    table: str
    table_type: int
    counts: dict = field(default_factory=dict)
    examples: dict = field(default_factory=dict)

    def observe(self, geometry_type: int, *, feature_id=None, **kwargs) -> str:
        code = classify_geometry_write(self.table_type, geometry_type, **kwargs)
        if code:
            self.counts[code] = self.counts.get(code, 0) + 1
            self.examples.setdefault(code, (int(geometry_type), feature_id))
        return code

    @property
    def ok(self) -> bool:
        return not self.counts

    def warnings(self) -> list[str]:
        lines = []
        for code in sorted(self.counts):
            geometry_type, feature_id = self.examples[code]
            text = MESSAGES[code].format(
                geometry=geometry_type_name(geometry_type), table=geometry_type_name(self.table_type)
            )
            example = f" (ex.: feicao {feature_id})" if feature_id is not None else ""
            lines.append(f"{code}: {self.counts[code]} feicao(oes) em '{self.table}': {text}{example}.")
        return lines
