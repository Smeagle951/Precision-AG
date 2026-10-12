# -*- coding: utf-8 -*-
"""Importa AdaptiveCurve: corta U-turns de cabeceira, mantem desvios no miolo, estende pontas."""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, degrees
from uuid import uuid4

from .guidance_engine import TrafficPass
from .line_geometry import (
    MultiPolygon,
    Point,
    Segment,
    add,
    build_processing_boundary,
    clip_polyline_to_multipolygon,
    decimate_polyline,
    distance,
    dot,
    extend_polyline_ends,
    mul,
    normalize,
    point_in_multipolygon,
    polyline_length,
    segment_samples,
    sub,
)
from .parallel_pass_engine import line_label_for_pass


class AdaptiveCurveImportError(ValueError):
    """Erro ao importar / limpar curva adaptativa."""


@dataclass(frozen=True)
class AdaptiveCurveImportResult:
    passes: list[TrafficPass]
    stripped_uturn_count: int
    source_polyline_count: int
    labels: tuple[str, ...]


def import_adaptive_curve_passes(
    polylines: list[list[Point] | tuple[Point, ...]],
    field: MultiPolygon,
    *,
    extension_m: float = 10.0,
    pass_spacing_m: float = 36.0,
    width_m: float = 36.0,
    operation_id: str = "spraying",
    headland_band_m: float | None = None,
    min_turn_deg: float = 100.0,
) -> AdaptiveCurveImportResult:
    """Parte serpentinas, remove U na cabeceira, estende pontas alem do limite."""
    if not field:
        raise AdaptiveCurveImportError("Talhao vazio para importar AdaptiveCurve.")
    band = headland_band_m if headland_band_m is not None else max(width_m * 1.25, 30.0)
    cleaned: list[list[Point]] = []
    stripped = 0
    source_count = 0
    for raw in polylines:
        pts = _clean_points(raw)
        if len(pts) < 2:
            continue
        source_count += 1
        parts, n_cut = split_serpentine_strip_uturns(
            pts,
            field,
            headland_band_m=band,
            min_turn_deg=min_turn_deg,
        )
        stripped += n_cut
        for part in parts:
            if len(part) >= 2:
                cleaned.append(part)

    if not cleaned:
        raise AdaptiveCurveImportError(
            "Nenhuma passada util apos cortar retornos. "
            "Verifique se a camada tem linhas no talhao."
        )

    processing = build_processing_boundary(field, extension_m)
    extended_parts: list[list[Point]] = []
    for part in cleaned:
        ext = extend_polyline_ends(part, extension_m)
        chunks = clip_polyline_to_multipolygon(ext, processing) if processing else [ext]
        if not chunks:
            # Se clip falhar, mantem extensao bruta.
            if len(ext) >= 2:
                extended_parts.append(ext)
            continue
        longest = max(chunks, key=lambda c: polyline_length(c))
        if len(longest) >= 2:
            extended_parts.append(longest)

    if not extended_parts:
        raise AdaptiveCurveImportError("Passadas ficaram vazias apos extensao/clip.")

    numbered = _number_passes_by_lateral_offset(extended_parts)
    passes: list[TrafficPass] = []
    labels: list[str] = []
    for pass_no, pts in numbered:
        path = tuple(decimate_polyline(pts, min_step_m=2.5, max_points=200))
        if len(path) < 2:
            continue
        seg = Segment(path[0], path[-1])
        az = degrees(atan2(path[-1][1] - path[0][1], path[-1][0] - path[0][0])) % 360.0
        # offset aproximado: distancia assinada do ponto medio ao eixo medio das passadas
        mid = path[len(path) // 2]
        passes.append(
            TrafficPass(
                pass_no=pass_no,
                fs_id=str(uuid4()),
                operation_id=operation_id,
                spacing_m=pass_spacing_m,
                width_m=width_m,
                offset_m=float(pass_no) * pass_spacing_m,
                azimuth_deg=az,
                direction="forward",
                clipped_segment=seg,
                guidance_segment=seg,
                path_points=path if len(path) > 2 else (),
            )
        )
        labels.append(line_label_for_pass(pass_no, machine_prefix="A"))
        _ = mid

    return AdaptiveCurveImportResult(
        passes=passes,
        stripped_uturn_count=stripped,
        source_polyline_count=source_count,
        labels=tuple(labels),
    )


def split_serpentine_strip_uturns(
    points: list[Point] | tuple[Point, ...],
    field: MultiPolygon,
    *,
    headland_band_m: float = 40.0,
    min_turn_deg: float = 100.0,
) -> tuple[list[list[Point]], int]:
    """Remove trechos de retorno (U) perto do limite; mantem desvios no miolo.

    Retorna (lista de passadas, quantidade de trechos U removidos).
    """
    pts = _clean_points(points)
    if len(pts) < 3:
        return ([pts] if len(pts) >= 2 else []), 0

    # Amostra regular para estabilidade do angulo.
    sampled = segment_samples(pts, densify_m=max(3.0, polyline_length(pts) / 400.0))
    sampled = decimate_polyline(sampled, min_step_m=2.0, max_points=800)
    if len(sampled) < 3:
        return [pts], 0

    turn_deg = _vertex_turn_degrees(sampled)
    near_headland = [
        _distance_to_field_exterior(p, field) <= headland_band_m
        or (not point_in_multipolygon(p, field, check_boundary=True))
        for p in sampled
    ]

    is_uturn = [False] * len(sampled)
    for i in range(1, len(sampled) - 1):
        if near_headland[i] and abs(turn_deg[i]) >= min_turn_deg:
            is_uturn[i] = True

    # Expande marcas para cobrir o arco U completo (vizinhos tambem na cabeceira).
    expanded = list(is_uturn)
    for i in range(1, len(sampled) - 1):
        if not is_uturn[i]:
            continue
        for j in range(max(1, i - 8), min(len(sampled) - 1, i + 9)):
            if near_headland[j] and abs(turn_deg[j]) >= min_turn_deg * 0.45:
                expanded[j] = True

    # Suaviza: buracos pequenos dentro de U viram U.
    for i in range(1, len(expanded) - 1):
        if expanded[i - 1] and expanded[i + 1]:
            expanded[i] = True

    parts: list[list[Point]] = []
    current: list[Point] = []
    stripped_runs = 0
    in_uturn = False
    for i, point in enumerate(sampled):
        if expanded[i]:
            if current and len(current) >= 2:
                parts.append(current)
            elif current and len(current) == 1 and parts:
                # Junta ponta solta a passada anterior se colada.
                pass
            current = []
            if not in_uturn:
                stripped_runs += 1
                in_uturn = True
            continue
        in_uturn = False
        if not current or distance(current[-1], point) > 1e-9:
            current.append(point)
    if len(current) >= 2:
        parts.append(current)

    # Descarta passadas muito curtas (resto de giro).
    min_len = max(headland_band_m * 0.5, pass_spacing_guess(parts) * 0.4)
    usable = [p for p in parts if polyline_length(p) >= min_len]
    if not usable and parts:
        usable = [max(parts, key=polyline_length)]
    return usable, stripped_runs


def pass_spacing_guess(parts: list[list[Point]]) -> float:
    if len(parts) < 2:
        return 36.0
    mids = [p[len(p) // 2] for p in parts if p]
    if len(mids) < 2:
        return 36.0
    dists = sorted(distance(mids[i], mids[i + 1]) for i in range(len(mids) - 1))
    return max(5.0, dists[len(dists) // 2])


def polyline_min_distance_to_point(points: list[Point] | tuple[Point, ...], center: Point) -> float:
    """Menor distancia ponto→polilinha (arestas)."""
    pts = list(points)
    if not pts:
        return float("inf")
    if len(pts) == 1:
        return distance(pts[0], center)
    best = float("inf")
    for a, b in zip(pts, pts[1:]):
        edge = sub(b, a)
        length2 = edge[0] * edge[0] + edge[1] * edge[1]
        if length2 <= 1e-18:
            d = distance(center, a)
        else:
            t = max(0.0, min(1.0, dot(sub(center, a), edge) / length2))
            proj = add(a, mul(edge, t))
            d = distance(center, proj)
        if d < best:
            best = d
    return best


def polyline_intersects_circle(
    points: list[Point] | tuple[Point, ...],
    center: Point,
    radius_m: float,
) -> bool:
    return polyline_min_distance_to_point(points, center) < radius_m - 1e-6


def _clean_points(points: list[Point] | tuple[Point, ...]) -> list[Point]:
    out: list[Point] = []
    for p in points:
        if not out or distance(out[-1], p) > 1e-9:
            out.append((float(p[0]), float(p[1])))
    return out


def _vertex_turn_degrees(points: list[Point]) -> list[float]:
    """Angulo de viragem em cada vertice (graus). Extremos = 0."""
    n = len(points)
    turns = [0.0] * n
    for i in range(1, n - 1):
        v1 = sub(points[i], points[i - 1])
        v2 = sub(points[i + 1], points[i])
        try:
            a = normalize(v1)
            b = normalize(v2)
        except ValueError:
            continue
        cross = a[0] * b[1] - a[1] * b[0]
        d = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1]))
        ang = atan2(cross, d)
        turns[i] = degrees(ang)
    return turns


def _distance_to_field_exterior(point: Point, field: MultiPolygon) -> float:
    """Distancia ao anel externo mais proximo (0 se fora / na borda)."""
    if not point_in_multipolygon(point, field, check_boundary=True):
        return 0.0
    best = float("inf")
    for outer, _holes in field:
        ring = list(outer)
        if len(ring) < 2:
            continue
        d = polyline_min_distance_to_point(ring, point)
        if d < best:
            best = d
    return best if best < float("inf") else 0.0


def _number_passes_by_lateral_offset(
    parts: list[list[Point]],
) -> list[tuple[int, list[Point]]]:
    """Numera relativo ao eixo medio (passada central ~ 0)."""
    if not parts:
        return []
    # Direcao dominante: media das direcoes das passadas.
    dirs: list[Point] = []
    for pts in parts:
        if len(pts) < 2:
            continue
        try:
            dirs.append(normalize(sub(pts[-1], pts[0])))
        except ValueError:
            continue
    if not dirs:
        return [(i, p) for i, p in enumerate(parts)]
    mean_dir = normalize(
        (sum(d[0] for d in dirs) / len(dirs), sum(d[1] for d in dirs) / len(dirs))
    )
    # Normal esquerda para offset lateral.
    left = (-mean_dir[1], mean_dir[0])
    scored: list[tuple[float, list[Point]]] = []
    for pts in parts:
        mid = pts[len(pts) // 2]
        # Origem arbitraria: primeiro mid
        scored.append((mid[0] * left[0] + mid[1] * left[1], pts))
    scored.sort(key=lambda item: item[0])
    # Zero = mais proximo da mediana dos offsets (eixo do campo / A-B tipica).
    offsets = [s[0] for s in scored]
    median = offsets[len(offsets) // 2]
    zero_idx = min(range(len(scored)), key=lambda i: abs(scored[i][0] - median))
    return [(i - zero_idx, scored[i][1]) for i in range(len(scored))]
