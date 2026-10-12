# -*- coding: utf-8 -*-
"""Passada preparada para validacao: geometria shapely e medidas ao longo da linha."""

from __future__ import annotations

from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import substring


def line_parts(geometry) -> list[LineString]:
    """Partes lineares de qualquer resultado de overlay (pontos e vazios ficam fora)."""
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [geometry]
    if geometry.geom_type == "MultiLineString":
        return list(geometry.geoms)
    if geometry.geom_type == "GeometryCollection":
        return [part for geom in geometry.geoms for part in line_parts(geom)]
    return []


def point_parts(geometry) -> list[Point]:
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "Point":
        return [geometry]
    if geometry.geom_type in ("MultiPoint", "GeometryCollection"):
        return [part for geom in geometry.geoms for part in point_parts(geom)]
    return []


class PreparedRoute:
    """Passada valida na ordem da sequencia; estacoes medidas no sentido desenhado."""

    def __init__(self, pass_id: str, index: int, sequence, route_type, segments):
        self.id = pass_id
        self.index = index
        self.sequence = sequence
        self.route_type = (route_type or "MAIN").upper()
        self.parts = tuple(LineString(points) for points in segments)
        self.geometry = self.parts[0] if len(self.parts) == 1 else MultiLineString(self.parts)
        self._offsets = []
        total = 0.0
        for part in self.parts:
            self._offsets.append(total)
            total += part.length
        self.length = total

    @property
    def endpoints(self) -> list[Point]:
        return [Point(self.parts[0].coords[0]), Point(self.parts[-1].coords[-1])]

    def part_endpoints(self) -> list[Point]:
        return [Point(c) for part in self.parts for c in (part.coords[0], part.coords[-1])]

    def station(self, point) -> float:
        """Distancia ao longo da passada ate o ponto (parte mais proxima)."""
        best = min(range(len(self.parts)), key=lambda i: self.parts[i].distance(point))
        return self._offsets[best] + self.parts[best].project(point)

    def stations_of(self, geometry) -> tuple[float, float]:
        coords = [Point(c) for part in line_parts(geometry) for c in (part.coords[0], part.coords[-1])]
        coords += point_parts(geometry)
        values = [self.station(p) for p in coords] or [0.0]
        return min(values), max(values)

    def between(self, start_m: float, end_m: float):
        """Trecho da passada entre duas estacoes (pode atravessar partes)."""
        pieces = []
        for offset, part in zip(self._offsets, self.parts):
            a = max(start_m, offset) - offset
            b = min(end_m, offset + part.length) - offset
            if b - a > 1e-9:
                pieces.append(substring(part, a, b))
        if not pieces:
            return None
        return pieces[0] if len(pieces) == 1 else MultiLineString(pieces)
