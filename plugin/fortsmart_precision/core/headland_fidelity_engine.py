# -*- coding: utf-8 -*-
"""Bordadura FIDELITY: offsets internos progressivos fieis ao limite real.

Modulo geometrico puro. O limite original e usado sem reamostragem (apenas a
invalidez e corrigida); cada passada deriva da anterior por buffer negativo com
uniao arredondada, que mantem a distancia constante em curvas, recuos e desvios
ja desenhados no limite. Identidade das passadas e tratamento das pontas V/U
ficam no `boundary_engine`, que reaproveita a logica LEGACY aprovada.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import shapely
from shapely.geometry import LineString, MultiPolygon as ShapelyMultiPolygon, Polygon
from shapely.geometry.polygon import orient
from shapely.prepared import prep

from .line_geometry import MultiPolygon, Point, erosion_quad_segs

CLEANUP_TOLERANCE_M = 0.001
MIN_SEGMENT_M = 0.05
MIN_PART_AREA_M2 = 1.0
SPIKE_ANGLE_DEG = 5.0
DISTANCE_TOLERANCE_M = 0.05
DISTANCE_TOLERANCE_RATIO = 0.002
OUTSIDE_TOLERANCE_M = 0.01


class HeadlandFidelityError(ValueError):
    """Falha da geracao FIDELITY; o chamador decide o fallback."""


@dataclass(frozen=True)
class FidelityPass:
    pass_index: int
    offset_m: float
    geometry: Any
    rings: tuple[tuple[Point, ...], ...]


@dataclass(frozen=True)
class FinalHeadlandPath:
    pass_id: str
    segment_id: int
    points: tuple[Point, ...]


@dataclass(frozen=True)
class HeadlandValidationReport:
    pass_count: int
    segment_count: int
    outside_length_m: float
    spacing_deviation_m: float
    fidelity_deviation_m: float
    invalid_geometry_count: int
    loop_count: int
    spike_count: int
    short_segment_count: int
    duplicate_id_count: int
    empty_pass_count: int
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "pass_count": self.pass_count,
            "segment_count": self.segment_count,
            "outside_length_m": round(self.outside_length_m, 4),
            "spacing_deviation_m": round(self.spacing_deviation_m, 4),
            "fidelity_deviation_m": round(self.fidelity_deviation_m, 4),
            "invalid_geometry_count": self.invalid_geometry_count,
            "loop_count": self.loop_count,
            "spike_count": self.spike_count,
            "short_segment_count": self.short_segment_count,
            "duplicate_id_count": self.duplicate_id_count,
            "empty_pass_count": self.empty_pass_count,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def distance_tolerance_m(offset_m: float) -> float:
    """Erro de corda dos arcos do buffer cresce com o raio (offset)."""
    return DISTANCE_TOLERANCE_M + DISTANCE_TOLERANCE_RATIO * abs(offset_m)


def _polygon_parts(geometry: Any) -> list[Polygon]:
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    if hasattr(geometry, "geoms"):
        parts: list[Polygon] = []
        for item in geometry.geoms:
            parts.extend(_polygon_parts(item))
        return parts
    return []


def _as_polygonal(parts: list[Polygon]) -> Any:
    if not parts:
        return Polygon()
    return parts[0] if len(parts) == 1 else ShapelyMultiPolygon(parts)


def prepare_boundary(operational_boundary: MultiPolygon) -> Any:
    """Limite original sem simplificar nem reamostrar; corrige apenas invalidez."""
    polygons = [
        Polygon(outer, [hole for hole in holes if len(hole) >= 3])
        for outer, holes in operational_boundary
        if len(outer) >= 3
    ]
    if not polygons:
        raise HeadlandFidelityError("Limite do talhao vazio.")
    geometry = _as_polygonal(polygons)
    if not geometry.is_valid:
        geometry = shapely.make_valid(geometry)
    parts = [part for part in _polygon_parts(geometry) if part.area > 0]
    if not parts:
        raise HeadlandFidelityError("Limite do talhao sem area apos correcao geometrica.")
    return _as_polygonal(parts)


def _clean_offset(geometry: Any) -> list[Polygon]:
    """Remove ruido de centimetros sem simplificacao global agressiva."""
    if geometry.is_empty:
        return []
    cleaned = geometry.simplify(CLEANUP_TOLERANCE_M, preserve_topology=True)
    cleaned = shapely.remove_repeated_points(cleaned, MIN_SEGMENT_M)
    if not cleaned.is_valid:
        cleaned = shapely.make_valid(cleaned)
    parts = [orient(part, 1.0) for part in _polygon_parts(cleaned) if part.area >= MIN_PART_AREA_M2]
    parts.sort(key=lambda part: (-round(part.area, 6), part.centroid.x, part.centroid.y))
    return parts


def progressive_offsets(boundary: Any, center_offsets_m: list[float]) -> list[FidelityPass]:
    """B(k) = offset_interno(BASE, offset_k); BASE = limite util.

    Offset absoluto: cada passada sai sempre do limite original, nunca da
    passada anterior, entao arredondamentos de corda nao se acumulam.
    """
    result: list[FidelityPass] = []
    previous = 0.0
    for index, offset in enumerate(center_offsets_m):
        if offset < previous:
            raise HeadlandFidelityError("Offsets de bordadura devem ser crescentes.")
        raw = (
            boundary.buffer(-offset, quad_segs=erosion_quad_segs(offset), join_style="round")
            if offset > 0
            else boundary
        )
        parts = _clean_offset(raw)
        rings = tuple(
            tuple((float(x), float(y)) for x, y in part.exterior.coords) for part in parts
        )
        result.append(FidelityPass(index, offset, _as_polygonal(parts), rings))
        previous = offset
    return result


def _oriented_pieces(start: Point, end: Point, clipped: Any) -> list[list[Point]]:
    if clipped.is_empty:
        return []
    lines = clipped.geoms if hasattr(clipped, "geoms") else [clipped]
    dx, dy = end[0] - start[0], end[1] - start[1]
    pieces: list[list[Point]] = []
    for line in lines:
        if line.geom_type != "LineString" or line.is_empty:
            continue
        coords = [(float(x), float(y)) for x, y in line.coords]
        if (coords[-1][0] - coords[0][0]) * dx + (coords[-1][1] - coords[0][1]) * dy < 0:
            coords.reverse()
        pieces.append(coords)
    pieces.sort(key=lambda c: (c[0][0] - start[0]) * dx + (c[0][1] - start[1]) * dy)
    return pieces


def clip_path_to_field(path: tuple[Point, ...], field: Any) -> list[tuple[Point, ...]]:
    """Recorta a passada no talhao segmento a segmento.

    Cada aresta e recortada isoladamente: o overlay nunca ve a polilinha
    inteira, entao cruzamentos X da propria passada nao viram nos nem quebras,
    e passadas diferentes jamais sao unidas.
    """
    allowed = prep(field.buffer(OUTSIDE_TOLERANCE_M))
    if len(path) < 2:
        return []
    if allowed.covers(LineString(path)):
        return [tuple(path)]
    pieces: list[list[Point]] = []
    for start, end in zip(path, path[1:]):
        if start == end:
            continue
        segment = LineString([start, end])
        if allowed.covers(segment):
            kept = [[start, end]]
        else:
            kept = _oriented_pieces(start, end, segment.intersection(field))
        for coords in kept:
            if pieces and math.dist(pieces[-1][-1], coords[0]) <= 1e-9:
                pieces[-1].extend(coords[1:])
            else:
                pieces.append(list(coords))
    return [tuple(piece) for piece in pieces if LineString(piece).length > MIN_SEGMENT_M]


def _samples(ring: tuple[Point, ...], max_samples: int = 4000) -> list[Point]:
    points = list(ring)
    samples = list(points)
    samples.extend(
        ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0) for a, b in zip(points, points[1:])
    )
    stride = max(1, len(samples) // max_samples)
    return samples[::stride]


def _max_distance_deviation(points: list[Point], reference: Any, expected_m: float) -> float:
    if not points or reference.is_empty:
        return 0.0
    distances = shapely.distance(shapely.points(points), reference)
    return float(max(abs(float(d) - expected_m) for d in distances))


def _vertex_angles_deg(ring: tuple[Point, ...]) -> list[float]:
    points = list(ring[:-1]) if len(ring) > 1 and ring[0] == ring[-1] else list(ring)
    angles = []
    count = len(points)
    for index in range(count):
        before, current, after = points[index - 1], points[index], points[(index + 1) % count]
        ax, ay = before[0] - current[0], before[1] - current[1]
        bx, by = after[0] - current[0], after[1] - current[1]
        la, lb = math.hypot(ax, ay), math.hypot(bx, by)
        if la <= 1e-12 or lb <= 1e-12:
            continue
        cosine = max(-1.0, min(1.0, (ax * bx + ay * by) / (la * lb)))
        angles.append(math.degrees(math.acos(cosine)))
    return angles


def validate_fidelity_headland(
    boundary: Any,
    passes: list[FidelityPass],
    finals: list[FinalHeadlandPath],
) -> HeadlandValidationReport:
    """Validacoes 1-5: dentro do talhao, espacamento, geometria, fidelidade, identidade."""
    errors: list[str] = []
    warnings: list[str] = []

    outside = sum(
        LineString(item.points).difference(boundary).length for item in finals if len(item.points) >= 2
    )
    if outside > OUTSIDE_TOLERANCE_M:
        errors.append(f"OUTSIDE_FIELD: {outside:.3f} m de bordadura fora do talhao.")

    boundary_lines = boundary.boundary
    spacing_dev = 0.0
    fidelity_dev = 0.0
    invalid = loops = spikes = short = empty = 0
    for index, item in enumerate(passes):
        if not item.rings:
            empty += 1
            continue
        samples = [point for ring in item.rings for point in _samples(ring)]
        deviation = _max_distance_deviation(samples, boundary_lines, item.offset_m)
        fidelity_dev = max(fidelity_dev, deviation)
        if deviation > distance_tolerance_m(item.offset_m):
            errors.append(
                f"FIDELITY: passada {index + 1} desvia {deviation:.3f} m do offset {item.offset_m:.3f} m."
            )
        if index > 0 and passes[index - 1].rings:
            step = item.offset_m - passes[index - 1].offset_m
            dev = _max_distance_deviation(samples, passes[index - 1].geometry.boundary, step)
            spacing_dev = max(spacing_dev, dev)
            if dev > distance_tolerance_m(item.offset_m):
                errors.append(
                    f"SPACING: passada {index + 1} desvia {dev:.3f} m do passo {step:.3f} m."
                )
        for part in _polygon_parts(item.geometry):
            if not part.is_valid:
                invalid += 1
            if not part.exterior.is_simple:
                loops += 1
        for ring in item.rings:
            spikes += sum(1 for angle in _vertex_angles_deg(ring) if angle < SPIKE_ANGLE_DEG)
            short += sum(
                1 for a, b in zip(ring, ring[1:]) if math.dist(a, b) < MIN_SEGMENT_M * 0.99
            )
    if invalid:
        errors.append(f"INVALID_GEOMETRY: {invalid} geometria(s) invalida(s).")
    if loops:
        errors.append(f"LOOP: {loops} anel(is) com auto-intersecao.")
    if spikes:
        errors.append(f"SPIKE: {spikes} vertice(s) com angulo menor que {SPIKE_ANGLE_DEG:.0f} graus.")
    if short:
        warnings.append(f"SHORT_SEGMENT: {short} segmento(s) menores que {MIN_SEGMENT_M:.2f} m.")
    if empty:
        warnings.append(f"EMPTY_PASS: {empty} passada(s) sem area restante no talhao.")
    if passes and empty == len(passes):
        errors.append("NO_PASS: nenhuma passada de bordadura cabe no talhao.")

    keys = [(item.pass_id, item.segment_id) for item in finals]
    duplicates = len(keys) - len(set(keys))
    if duplicates:
        errors.append(f"DUPLICATE_ID: {duplicates} identificador(es) repetido(s).")

    return HeadlandValidationReport(
        pass_count=len(passes),
        segment_count=len(finals),
        outside_length_m=outside,
        spacing_deviation_m=spacing_dev,
        fidelity_deviation_m=fidelity_dev,
        invalid_geometry_count=invalid,
        loop_count=loops,
        spike_count=spikes,
        short_segment_count=short,
        duplicate_id_count=duplicates,
        empty_pass_count=empty,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def point_distances_to_boundary(points: list[Point], boundary: Any) -> list[float]:
    if not points:
        return []
    return [float(d) for d in shapely.distance(shapely.points(points), boundary.boundary)]
