# -*- coding: utf-8 -*-
"""Validacao numerica de espacamento: passadas, bordaduras e limites internos.

Tolerancia agronomica (espacamento) e separada da tolerancia geometrica
(topologia/clip): um erro de espacamento nunca e escondido pela segunda.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from .line_geometry import MultiPolygon, Point, dot, ring_without_duplicate_close, sub

LOGGER = logging.getLogger("fortsmart_precision.spacing")

AGRONOMIC_SPACING_TOLERANCE_M = 0.01
PASS_SPACING_OUT_OF_TOLERANCE = "PASS_SPACING_OUT_OF_TOLERANCE"
HEADLAND_OFFSET_OUT_OF_TOLERANCE = "HEADLAND_OFFSET_OUT_OF_TOLERANCE"


@dataclass(frozen=True)
class PassSpacingSample:
    """Uma passada medida na normal da familia (atributos de depuracao)."""

    pass_index: int
    expected_spacing_m: float
    expected_offset_m: float
    actual_offset_m: float
    spacing_error_m: float

    def as_dict(self) -> dict[str, object]:
        return {
            "pass_index": self.pass_index,
            "expected_spacing_m": self.expected_spacing_m,
            "expected_offset_m": self.expected_offset_m,
            "actual_offset_m": self.actual_offset_m,
            "spacing_error_m": self.spacing_error_m,
        }


@dataclass(frozen=True)
class SpacingReport:
    label: str
    expected_spacing_m: float
    tolerance_m: float
    samples: tuple[PassSpacingSample, ...] = ()
    min_spacing_m: float = 0.0
    mean_spacing_m: float = 0.0
    max_spacing_m: float = 0.0
    code: str = ""
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def max_abs_error_m(self) -> float:
        return max((abs(item.spacing_error_m) for item in self.samples), default=0.0)

    def summary_lines(self) -> list[str]:
        lines = [
            f"SPACING {self.label}: esperado={self.expected_spacing_m:.6f} m "
            f"tolerancia={self.tolerance_m:.3f} m",
            f"Espacamento: min={self.min_spacing_m:.6f} medio={self.mean_spacing_m:.6f} "
            f"max={self.max_spacing_m:.6f}",
            f"Erro maximo: {self.max_abs_error_m:.6f} m em {len(self.samples)} passada(s)",
        ]
        lines.extend(self.errors[:10])
        return lines

    def as_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "ok": self.ok,
            "code": self.code,
            "expected_spacing_m": self.expected_spacing_m,
            "tolerance_m": self.tolerance_m,
            "min_spacing_m": self.min_spacing_m,
            "mean_spacing_m": self.mean_spacing_m,
            "max_spacing_m": self.max_spacing_m,
            "max_abs_error_m": self.max_abs_error_m,
            "errors": list(self.errors),
        }


def validate_pass_spacing(
    passes: Iterable[tuple[int, Sequence[Point]]],
    origin: Point,
    normal: Point,
    spacing_m: float,
    *,
    tolerance_m: float = AGRONOMIC_SPACING_TOLERANCE_M,
    label: str = "plantio",
) -> SpacingReport:
    """Projeta cada vertice na normal: real = (p - origem) . normal; esperado = indice * W.

    Varias partes do mesmo indice (talhao concavo) entram no mesmo grupo; o
    erro de cada indice e o pior vertice. O espacamento entre indices vizinhos
    vem das posicoes reais medidas, nunca do atributo `offset_m`.
    """
    worst: dict[int, tuple[float, float]] = {}
    for pass_index, points in passes:
        expected = pass_index * spacing_m
        for point in points:
            actual = dot(sub(point, origin), normal)
            error = actual - expected
            current = worst.get(pass_index)
            if current is None or abs(error) > abs(current[1]):
                worst[pass_index] = (actual, error)
    samples = tuple(
        PassSpacingSample(index, spacing_m, index * spacing_m, actual, error)
        for index, (actual, error) in sorted(worst.items())
    )
    spacings = [
        (b.actual_offset_m - a.actual_offset_m) / (b.pass_index - a.pass_index)
        for a, b in zip(samples, samples[1:])
    ]
    errors = tuple(
        f"{PASS_SPACING_OUT_OF_TOLERANCE}: {label} passada {item.pass_index} "
        f"real={item.actual_offset_m:.4f} esperado={item.expected_offset_m:.4f} "
        f"erro={item.spacing_error_m:+.4f} m"
        for item in samples
        if abs(item.spacing_error_m) > tolerance_m
    )
    return SpacingReport(
        label=label,
        expected_spacing_m=spacing_m,
        tolerance_m=tolerance_m,
        samples=samples,
        min_spacing_m=min(spacings, default=spacing_m),
        mean_spacing_m=sum(spacings) / len(spacings) if spacings else spacing_m,
        max_spacing_m=max(spacings, default=spacing_m),
        code=PASS_SPACING_OUT_OF_TOLERANCE if errors else "",
        errors=errors,
    )


@dataclass(frozen=True)
class OffsetLevelSample:
    pass_index: int
    expected_offset_m: float
    min_distance_m: float
    max_distance_m: float

    @property
    def error_m(self) -> float:
        return max(
            abs(self.min_distance_m - self.expected_offset_m),
            abs(self.max_distance_m - self.expected_offset_m),
        )


@dataclass(frozen=True)
class OffsetReport:
    label: str
    tolerance_m: float
    levels: tuple[OffsetLevelSample, ...] = ()
    code: str = ""
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def max_abs_error_m(self) -> float:
        return max((level.error_m for level in self.levels), default=0.0)

    def summary_lines(self) -> list[str]:
        lines = [f"OFFSET {self.label}: tolerancia={self.tolerance_m:.3f} m"]
        lines.extend(
            f"B{level.pass_index + 1}: esperado={level.expected_offset_m:.4f} "
            f"dist_min={level.min_distance_m:.4f} dist_max={level.max_distance_m:.4f} "
            f"erro={level.error_m:.4f}"
            for level in self.levels
        )
        lines.extend(self.errors[:10])
        return lines

    def as_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "ok": self.ok,
            "code": self.code,
            "tolerance_m": self.tolerance_m,
            "max_abs_error_m": self.max_abs_error_m,
            "levels": [
                {
                    "pass_index": level.pass_index,
                    "expected_offset_m": level.expected_offset_m,
                    "min_distance_m": level.min_distance_m,
                    "max_distance_m": level.max_distance_m,
                    "error_m": level.error_m,
                }
                for level in self.levels
            ],
            "errors": list(self.errors),
        }


def ring_samples(ring: Sequence[Point]) -> list[Point]:
    """Vertices + pontos medios das arestas (a flecha da corda aparece no meio)."""
    pts = ring_without_duplicate_close(ring)
    if len(pts) < 2:
        return list(pts)
    closed = list(pts) + [pts[0]]
    mids = [((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0) for a, b in zip(closed, closed[1:])]
    return list(pts) + mids


def distances_to_boundary(points: Sequence[Point], boundary: MultiPolygon) -> list[float]:
    """Distancia euclidiana de cada ponto as arestas (externas e ilhas) do limite."""
    if not points:
        return []
    from shapely import distance as shapely_distance, points as shapely_points
    from shapely.geometry import MultiLineString

    lines = [
        list(ring_without_duplicate_close(ring)) + [ring_without_duplicate_close(ring)[0]]
        for outer, holes in boundary
        for ring in (outer, *holes)
        if len(ring_without_duplicate_close(ring)) >= 2
    ]
    edges = MultiLineString(lines)
    return [float(value) for value in shapely_distance(shapely_points(list(points)), edges)]


def validate_offset_levels(
    boundary: MultiPolygon,
    levels: Iterable[tuple[int, float, Sequence[Sequence[Point]]]],
    *,
    tolerance_m: float = AGRONOMIC_SPACING_TOLERANCE_M,
    label: str = "bordadura",
) -> OffsetReport:
    """Cada nivel B(k) deve ficar a `offset_k` do limite REAL em todos os pontos."""
    samples: list[OffsetLevelSample] = []
    for pass_index, expected, rings in levels:
        points = [point for ring in rings for point in ring_samples(ring)]
        distances = distances_to_boundary(points, boundary)
        if not distances:
            continue
        samples.append(OffsetLevelSample(pass_index, expected, min(distances), max(distances)))
    errors = tuple(
        f"{HEADLAND_OFFSET_OUT_OF_TOLERANCE}: {label} B{level.pass_index + 1} "
        f"esperado={level.expected_offset_m:.4f} min={level.min_distance_m:.4f} "
        f"max={level.max_distance_m:.4f} erro={level.error_m:.4f} m"
        for level in samples
        if level.error_m > tolerance_m
    )
    return OffsetReport(
        label=label,
        tolerance_m=tolerance_m,
        levels=tuple(samples),
        code=HEADLAND_OFFSET_OUT_OF_TOLERANCE if errors else "",
        errors=errors,
    )


@dataclass(frozen=True)
class AdjacentPairSample:
    """Par Pn / Pn+1 medido da passada externa (maior |n|) ate a interna."""

    first_index: int
    second_index: int
    outer_index: int
    expected_m: float
    min_m: float
    max_m: float
    worst_m: float
    worst_segment: int
    worst_point: Point
    sample_count: int

    @property
    def error_m(self) -> float:
        return self.worst_m - self.expected_m

    def label(self) -> str:
        return f"P{self.first_index} / P{self.second_index}"


@dataclass(frozen=True)
class AdjacentSpacingReport:
    label: str
    expected_spacing_m: float
    tolerance_m: float
    pairs: tuple[AdjacentPairSample, ...] = ()
    code: str = ""
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def max_abs_error_m(self) -> float:
        return max((abs(pair.error_m) for pair in self.pairs), default=0.0)

    @property
    def min_spacing_m(self) -> float:
        return min((pair.min_m for pair in self.pairs), default=self.expected_spacing_m)

    @property
    def max_spacing_m(self) -> float:
        return max((pair.max_m for pair in self.pairs), default=self.expected_spacing_m)

    def summary_lines(self) -> list[str]:
        lines = [
            f"ADJACENT {self.label}: esperado={self.expected_spacing_m:.4f} m "
            f"tolerancia={self.tolerance_m:.3f} m pares={len(self.pairs)}",
            f"Distancia normal local: min={self.min_spacing_m:.4f} max={self.max_spacing_m:.4f} "
            f"erro maximo={self.max_abs_error_m:.4f} m",
        ]
        lines.extend(self.errors[:10])
        return lines

    def as_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "ok": self.ok,
            "code": self.code,
            "expected_spacing_m": self.expected_spacing_m,
            "tolerance_m": self.tolerance_m,
            "min_spacing_m": self.min_spacing_m,
            "max_spacing_m": self.max_spacing_m,
            "max_abs_error_m": self.max_abs_error_m,
            "errors": list(self.errors),
        }


def _segment_samples_with_ids(
    points: Sequence[Point], sample_step_m: float, max_samples: int
) -> tuple[list[Point], list[int]]:
    """Pontos ao longo da passada (com o ponto medio de toda aresta) e o indice da aresta."""
    import numpy as np

    coords = np.asarray(points, dtype=float)
    if len(coords) < 2:
        return [], []
    lengths = np.hypot(*np.diff(coords, axis=0).T)
    step = max(sample_step_m, float(lengths.sum()) / max(1, max_samples))
    counts = np.maximum(2, np.ceil(lengths / step).astype(int))
    starts = np.repeat(coords[:-1], counts, axis=0)
    deltas = np.repeat(coords[1:] - coords[:-1], counts, axis=0)
    fractions = np.concatenate([np.arange(count) / count for count in counts])
    samples = starts + deltas * fractions[:, None]
    segment_ids = np.repeat(np.arange(len(lengths)), counts)
    samples = np.vstack([samples, coords[-1:]])
    segment_ids = np.append(segment_ids, len(lengths) - 1)
    return [tuple(map(float, p)) for p in samples], segment_ids.tolist()


def validate_adjacent_pass_spacing(
    passes: Iterable[tuple[int, Sequence[Point]]],
    spacing_m: float,
    *,
    tolerance_m: float = AGRONOMIC_SPACING_TOLERANCE_M,
    label: str = "plantio",
    sample_step_m: float = 2.0,
    max_samples_per_part: int = 2000,
) -> AdjacentSpacingReport:
    """Distancia normal local entre passadas vizinhas (retas e curvas).

    Cada ponto da passada externa (maior |indice|) mede a distancia ate a
    interna; numa familia de offsets exatos ela vale a largura em todo ponto.
    Pontos cujo pe mais proximo cai na ponta de um trecho da interna (fim de
    passada, recorte do limite) nao tem vizinha na normal e ficam de fora.
    """
    import numpy as np
    import shapely
    from shapely.geometry import MultiLineString, MultiPoint

    groups: dict[int, list[list[Point]]] = {}
    for pass_index, points in passes:
        pts = [tuple(map(float, p)) for p in points]
        if len(pts) >= 2:
            groups.setdefault(int(pass_index), []).append(pts)

    pairs: list[AdjacentPairSample] = []
    for first in sorted(groups):
        second = first + 1
        if second not in groups:
            continue
        outer, inner = (second, first) if abs(second) > abs(first) else (first, second)
        inner_lines = MultiLineString(groups[inner])
        inner_ends = MultiPoint([p for part in groups[inner] for p in (part[0], part[-1])])
        measured_parts: list[tuple[np.ndarray, list[int], list[Point]]] = []
        for part in groups[outer]:
            samples, segment_ids = _segment_samples_with_ids(part, sample_step_m, max_samples_per_part)
            if not samples:
                continue
            geoms = shapely.points(np.asarray(samples))
            to_line = shapely.distance(geoms, inner_lines)
            valid = shapely.distance(geoms, inner_ends) - to_line > 1e-6
            if valid.any():
                keep = np.flatnonzero(valid)
                measured_parts.append(
                    (to_line[keep], [segment_ids[i] for i in keep], [samples[i] for i in keep])
                )
        if not measured_parts:
            continue
        measured = np.concatenate([item[0] for item in measured_parts])
        segment_ids = [sid for item in measured_parts for sid in item[1]]
        sample_points = [p for item in measured_parts for p in item[2]]
        worst = int(np.argmax(np.abs(measured - spacing_m)))
        pairs.append(
            AdjacentPairSample(
                first_index=first,
                second_index=second,
                outer_index=outer,
                expected_m=spacing_m,
                min_m=float(measured.min()),
                max_m=float(measured.max()),
                worst_m=float(measured[worst]),
                worst_segment=segment_ids[worst],
                worst_point=sample_points[worst],
                sample_count=len(measured),
            )
        )

    errors = tuple(
        f"{PASS_SPACING_OUT_OF_TOLERANCE}: {label}\n"
        f"Esperado: {pair.expected_m:.2f} m\n"
        f"Encontrado: {pair.worst_m:.2f} m\n"
        f"Passadas: {pair.label()}\n"
        f"Trecho: segmento {pair.worst_segment + 1} da P{pair.outer_index} "
        f"(x={pair.worst_point[0]:.2f}, y={pair.worst_point[1]:.2f})"
        for pair in pairs
        if abs(pair.error_m) > tolerance_m
    )
    return AdjacentSpacingReport(
        label=label,
        expected_spacing_m=spacing_m,
        tolerance_m=tolerance_m,
        pairs=tuple(pairs),
        code=PASS_SPACING_OUT_OF_TOLERANCE if errors else "",
        errors=errors,
    )


def log_spacing_report(
    report: SpacingReport | OffsetReport | AdjacentSpacingReport, *, crs_authid: str = ""
) -> None:
    if crs_authid:
        LOGGER.info("CRS=%s", crs_authid)
    log = LOGGER.info if report.ok else LOGGER.warning
    for line in report.summary_lines():
        log(line)
