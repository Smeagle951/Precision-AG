# -*- coding: utf-8 -*-
"""Indice espacial em grade uniforme para obstaculos (envelopes e zonas proibidas).

Sem este indice, detectar conflito custa O(passadas x obstaculos): 200 passadas
com 50 obstaculos = 10.000 testes geometricos, quase todos entre geometrias
distantes centenas de metros.

A grade responde "quais obstaculos estao perto DESTA passada?" em tempo
proporcional a area varrida pela passada, nao ao total de obstaculos:

    indice = build_envelope_index(envelopes)      # uma vez por geracao
    proximos = indice.query_polyline(pts, reach)  # por passada

Nunca substitui o teste geometrico preciso — apenas descarta cedo o que nao
tem chance de colidir. O resultado e sempre um SUPERCONJUNTO dos candidatos
reais, entao a precisao agronomica fica intacta.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import floor

from .line_geometry import Point

_DEFAULT_MIN_CELL_M = 25.0


@dataclass(frozen=True)
class _Item:
    """Elemento indexado: objeto + bbox + raio de alcance proprio."""

    payload: object
    xmin: float
    ymin: float
    xmax: float
    ymax: float


class UniformGridIndex:
    """Grade uniforme de bboxes. Consultas por bbox, ponto ou polilinha."""

    def __init__(self, items: list[_Item], cell_size_m: float) -> None:
        self._items = items
        self._cell = max(float(cell_size_m), 1.0)
        self._buckets: dict[tuple[int, int], list[int]] = {}
        for index, item in enumerate(items):
            for key in self._cells_for_bbox(item.xmin, item.ymin, item.xmax, item.ymax):
                self._buckets.setdefault(key, []).append(index)

    def __len__(self) -> int:
        return len(self._items)

    @property
    def cell_size_m(self) -> float:
        return self._cell

    def _cell_key(self, x: float, y: float) -> tuple[int, int]:
        return (int(floor(x / self._cell)), int(floor(y / self._cell)))

    def _cells_for_bbox(
        self, xmin: float, ymin: float, xmax: float, ymax: float
    ) -> list[tuple[int, int]]:
        cx0, cy0 = self._cell_key(xmin, ymin)
        cx1, cy1 = self._cell_key(xmax, ymax)
        # Talhoes enormes com celula pequena poderiam explodir; a celula e
        # dimensionada pelo maior alcance, entao o intervalo fica curto.
        return [(cx, cy) for cx in range(cx0, cx1 + 1) for cy in range(cy0, cy1 + 1)]

    def query_bbox(
        self, xmin: float, ymin: float, xmax: float, ymax: float
    ) -> list[object]:
        """Objetos cujo bbox intersecta o retangulo consultado."""
        seen: set[int] = set()
        out: list[object] = []
        for key in self._cells_for_bbox(xmin, ymin, xmax, ymax):
            for index in self._buckets.get(key, ()):
                if index in seen:
                    continue
                seen.add(index)
                item = self._items[index]
                if item.xmax < xmin or item.xmin > xmax:
                    continue
                if item.ymax < ymin or item.ymin > ymax:
                    continue
                out.append(item.payload)
        return out

    def query_point(self, point: Point, reach_m: float = 0.0) -> list[object]:
        return self.query_bbox(
            point[0] - reach_m,
            point[1] - reach_m,
            point[0] + reach_m,
            point[1] + reach_m,
        )

    def query_polyline(
        self,
        points: list[Point] | tuple[Point, ...],
        reach_m: float,
        *,
        segment_chunk: int = 24,
    ) -> list[object]:
        """Objetos proximos da polilinha, varrendo por blocos de segmentos.

        Usar o bbox da polilinha inteira devolveria obstaculos de todo o talhao
        em passadas longas; varrer em blocos mantem a consulta apertada sem
        pagar um bbox por vertice.
        """
        pts = list(points)
        if not pts:
            return []
        if len(pts) == 1:
            return self.query_point(pts[0], reach_m)

        seen: set[int] = set()
        out: list[object] = []
        step = max(1, int(segment_chunk))
        for start in range(0, len(pts) - 1, step):
            chunk = pts[start : start + step + 1]
            xs = [pt[0] for pt in chunk]
            ys = [pt[1] for pt in chunk]
            for payload in self.query_bbox(
                min(xs) - reach_m,
                min(ys) - reach_m,
                max(xs) + reach_m,
                max(ys) + reach_m,
            ):
                key = id(payload)
                if key in seen:
                    continue
                seen.add(key)
                out.append(payload)
        return out


def _bbox_from_center_radius(center: Point, radius_m: float) -> tuple[float, float, float, float]:
    return (
        center[0] - radius_m,
        center[1] - radius_m,
        center[0] + radius_m,
        center[1] + radius_m,
    )


def _geometry_bbox(geometry) -> tuple[float, float, float, float] | None:
    """bbox de um Polygon (anel externo + buracos), se houver geometria real."""
    try:
        outer = geometry[0]
    except Exception:
        return None
    if not outer:
        return None
    xs = [pt[0] for pt in outer]
    ys = [pt[1] for pt in outer]
    return (min(xs), min(ys), max(xs), max(ys))


def build_envelope_index(envelopes: list) -> UniformGridIndex:
    """Indexa `ObstacleSafetyEnvelope` pelo bbox do raio de aplicacao."""
    items: list[_Item] = []
    max_reach = 0.0
    for envelope in envelopes:
        radius = float(getattr(envelope, "application_radius_m", 0.0) or 0.0)
        bbox = None
        geometry = getattr(envelope, "geometry", None)
        if geometry is not None:
            bbox = _geometry_bbox(geometry)
        if bbox is None:
            center = getattr(envelope, "center", None)
            if center is None:
                continue
            bbox = _bbox_from_center_radius(center, radius)
        items.append(_Item(envelope, *bbox))
        max_reach = max(max_reach, radius, bbox[2] - bbox[0], bbox[3] - bbox[1])
    return UniformGridIndex(items, max(_DEFAULT_MIN_CELL_M, max_reach))


def build_region_index(regions: list) -> UniformGridIndex:
    """Indexa `ForbiddenRegion` (zonas proibidas do plantio) pelo bbox."""
    items: list[_Item] = []
    max_reach = 0.0
    for region in regions:
        radius = float(getattr(region, "implement_clearance_radius_m", 0.0) or 0.0)
        bbox = None
        geometry = getattr(region, "geometry", None)
        if geometry is not None:
            bbox = _geometry_bbox(geometry)
        if bbox is None:
            center = getattr(region, "center", None)
            if center is None:
                continue
            bbox = _bbox_from_center_radius(center, radius)
        items.append(_Item(region, *bbox))
        max_reach = max(max_reach, radius, bbox[2] - bbox[0], bbox[3] - bbox[1])
    return UniformGridIndex(items, max(_DEFAULT_MIN_CELL_M, max_reach))
