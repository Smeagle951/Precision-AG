# -*- coding: utf-8 -*-
"""Limite superamostrado (ex.: GS3 com vertice a cada 4 mm) reduzido sem mudar a forma.

Douglas-Peucker com preservacao de topologia: nenhum ponto do limite sai mais
que `tolerance_m` da posicao original (2 mm, a mesma tolerancia das passadas).
So atua em anel com mais vertices que `min_vertices`; limites normais passam
intactos. Coordenadas sempre em CRS metrico (chamado dentro dos motores).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .line_geometry import MultiPolygon

LOGGER = logging.getLogger("fortsmart_precision.boundary")

BOUNDARY_SIMPLIFY_TOLERANCE_M = 0.002
BOUNDARY_DENSE_VERTEX_LIMIT = 720


@dataclass(frozen=True)
class BoundarySimplification:
    original_vertices: int
    simplified_vertices: int
    tolerance_m: float

    @property
    def applied(self) -> bool:
        return self.simplified_vertices < self.original_vertices


def _vertex_count(polygon) -> int:
    outer, holes = polygon
    return len(outer) + sum(len(hole) for hole in holes)


def _ring(coords) -> list:
    return [(float(x), float(y)) for x, y, *_ in coords]


def simplify_dense_boundary(
    polygons: MultiPolygon,
    *,
    tolerance_m: float = BOUNDARY_SIMPLIFY_TOLERANCE_M,
    min_vertices: int = BOUNDARY_DENSE_VERTEX_LIMIT,
) -> tuple[MultiPolygon, BoundarySimplification]:
    """Devolve o limite reduzido (ou o mesmo objeto, se nada mudou) e o resumo."""
    original = sum(_vertex_count(polygon) for polygon in polygons or [])
    unchanged = (polygons, BoundarySimplification(original, original, tolerance_m))
    if not polygons or not any(_vertex_count(p) > min_vertices for p in polygons):
        return unchanged
    try:
        from shapely.geometry import Polygon as ShapelyPolygon
    except ImportError:  # sem GEOS o limite segue como veio
        return unchanged
    result: MultiPolygon = []
    for polygon in polygons:
        outer, holes = polygon
        if _vertex_count(polygon) <= min_vertices or len(outer) < 4:
            result.append(polygon)
            continue
        simple = ShapelyPolygon(outer, holes).simplify(tolerance_m, preserve_topology=True)
        if simple.is_empty or simple.geom_type != "Polygon" or not simple.is_valid:
            result.append(polygon)
            continue
        result.append((_ring(simple.exterior.coords), [_ring(ring.coords) for ring in simple.interiors]))
    reduced = sum(_vertex_count(polygon) for polygon in result)
    if reduced >= original:
        return unchanged
    LOGGER.info(
        "BOUNDARY SIMPLIFIED vertices=%d -> %d max_deviation_m=%.3f", original, reduced, tolerance_m
    )
    return result, BoundarySimplification(original, reduced, tolerance_m)
