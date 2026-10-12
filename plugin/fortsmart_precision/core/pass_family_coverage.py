# -*- coding: utf-8 -*-
"""Diagnostico de cobertura da familia de passadas paralelas (somente leitura).

Nao altera passadas: mede, com GEOS, se a familia gerada cobre a area permitida
(miolo/limite) e se toda reta candidata que cruza o talhao virou passada.
Coordenadas sempre em CRS metrico (o projeto e validado antes da geracao).
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor

from .line_geometry import MultiPolygon, add, mul, multipolygon_bbox
from .parallel_pass_engine import (
    GENERATOR_INCOMPLETE_FIELD_COVERAGE,
    GEOMETRY_TOLERANCE_M,
    LOGGER,
    StraightFamilyStats,
    build_full_candidate_line,
)


@dataclass(frozen=True)
class FamilyCoverageReport:
    label: str
    expected_projection_min: float
    expected_projection_max: float
    generated_projection_min: float | None
    generated_projection_max: float | None
    candidates_tested: int
    candidates_empty: int
    candidates_valid: int
    expected_valid_candidates: int | None
    logical_passes: int
    features: int
    multipart_passes: int
    allowed_area_m2: float
    missing_area_m2: float
    coverage_gap_tolerance_m: float
    significant_area_m2: float

    @property
    def missing_candidates(self) -> int:
        if self.expected_valid_candidates is None:
            return 0
        return max(0, self.expected_valid_candidates - self.candidates_valid)

    @property
    def ok(self) -> bool:
        return self.missing_area_m2 <= self.significant_area_m2 and self.missing_candidates == 0

    @property
    def code(self) -> str:
        return "" if self.ok else GENERATOR_INCOMPLETE_FIELD_COVERAGE

    def summary_lines(self) -> list[str]:
        return [
            f"TALHAO: {self.label}",
            f"Projecao: min={self.expected_projection_min:.1f} max={self.expected_projection_max:.1f}",
            (
                f"Candidatas: testadas={self.candidates_tested} vazias={self.candidates_empty} "
                f"validas={self.candidates_valid}"
            ),
            (
                f"Passadas: logicas={self.logical_passes} feicoes={self.features} "
                f"multipartes={self.multipart_passes}"
            ),
            f"Cobertura: faltante_ha={self.missing_area_m2 / 10000.0:.4f}",
        ]

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "label": self.label,
            "expected_projection_min": round(self.expected_projection_min, 3),
            "expected_projection_max": round(self.expected_projection_max, 3),
            "generated_projection_min": (
                None if self.generated_projection_min is None else round(self.generated_projection_min, 3)
            ),
            "generated_projection_max": (
                None if self.generated_projection_max is None else round(self.generated_projection_max, 3)
            ),
            "candidates_tested": self.candidates_tested,
            "candidates_empty": self.candidates_empty,
            "candidates_valid": self.candidates_valid,
            "expected_valid_candidates": self.expected_valid_candidates,
            "logical_passes": self.logical_passes,
            "features": self.features,
            "multipart_passes": self.multipart_passes,
            "missing_area_m2": round(self.missing_area_m2, 3),
            "missing_area_ha": round(self.missing_area_m2 / 10000.0, 5),
        }


def extract_valid_line_parts(geometry, min_length_m: float = GEOMETRY_TOLERANCE_M) -> list:
    """Todas as partes lineares de um resultado GEOS (Line/MultiLine/Collection recursiva).

    Pontos e poligonos sao ignorados; partes vazias ou menores que a tolerancia saem.
    """
    if geometry is None or geometry.is_empty:
        return []
    kind = geometry.geom_type
    if kind in ("LineString", "LinearRing"):
        return [geometry] if geometry.length >= min_length_m else []
    if kind in ("MultiLineString", "GeometryCollection"):
        parts: list = []
        for item in geometry.geoms:
            parts.extend(extract_valid_line_parts(item, min_length_m))
        return parts
    return []


def _shapely_area(polygons: MultiPolygon):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    from shapely.validation import make_valid

    shapes = []
    for outer, holes in polygons:
        if len(outer) < 4:
            continue
        shape = Polygon(outer, [hole for hole in holes if len(hole) >= 4])
        if not shape.is_valid:
            shape = make_valid(shape)
        shapes.append(shape)
    if not shapes:
        return None
    return unary_union(shapes)


def default_coverage_gap_tolerance(implement_width_m: float, pass_spacing_m: float) -> float:
    """Meia-largura da maior faixa inerente ao paralelismo (borda concava paralela).

    Entre a ultima passada dentro de um braco e a borda dele sobram ate
    `espacamento - largura/2`; faixas assim nao sao falha do gerador.
    """
    inherent = max(float(pass_spacing_m) - float(implement_width_m) / 2.0, 0.0)
    return inherent / 2.0 + GEOMETRY_TOLERANCE_M * 5.0


def validate_family_coverage(
    passes,
    allowed_area: MultiPolygon,
    *,
    implement_width_m: float,
    pass_spacing_m: float,
    stats: StraightFamilyStats | None = None,
    coverage_gap_tolerance_m: float | None = None,
    label: str = "",
) -> FamilyCoverageReport | None:
    """Mede a cobertura da familia; devolve None se GEOS indisponivel ou area vazia."""
    try:
        import shapely
        from shapely.geometry import LineString
        from shapely.ops import unary_union
    except ImportError:
        return None
    allowed = _shapely_area(allowed_area)
    if allowed is None or allowed.is_empty:
        return None

    tolerance = (
        default_coverage_gap_tolerance(implement_width_m, pass_spacing_m)
        if coverage_gap_tolerance_m is None
        else float(coverage_gap_tolerance_m)
    )
    significant = max(1.0, 0.25 * float(implement_width_m) ** 2)

    lines = [LineString(item.line_points()) for item in passes if len(item.line_points()) >= 2]
    if lines:
        strips = shapely.buffer(lines, float(implement_width_m) / 2.0, cap_style="flat")
        coverage = unary_union(list(strips))
        missing = allowed.difference(coverage)
    else:
        missing = allowed
    if missing.is_empty:
        missing_m2 = 0.0
    elif tolerance > 0:
        opened = missing.buffer(-tolerance).buffer(tolerance)
        missing_m2 = 0.0 if opened.is_empty else opened.intersection(missing).area
    else:
        missing_m2 = missing.area

    pass_numbers: dict[int, int] = {}
    for item in passes:
        pass_numbers[int(item.pass_no)] = pass_numbers.get(int(item.pass_no), 0) + 1

    expected_min = expected_max = 0.0
    generated_min = generated_max = None
    expected_valid: int | None = None
    if stats is not None and stats.is_straight:
        expected_min = stats.projection_min
        expected_max = stats.projection_max
        offsets = [-float(item.offset_m) for item in passes]
        if offsets:
            generated_min, generated_max = min(offsets), max(offsets)
        expected_valid = _expected_valid_candidates(allowed, allowed_area, stats, pass_spacing_m)

    return FamilyCoverageReport(
        label=label,
        expected_projection_min=expected_min,
        expected_projection_max=expected_max,
        generated_projection_min=generated_min,
        generated_projection_max=generated_max,
        candidates_tested=stats.candidates_tested if stats else 0,
        candidates_empty=stats.candidates_empty if stats else 0,
        candidates_valid=stats.candidates_valid if stats else len(pass_numbers),
        expected_valid_candidates=expected_valid,
        logical_passes=len(pass_numbers),
        features=len(passes),
        multipart_passes=sum(1 for count in pass_numbers.values() if count > 1),
        allowed_area_m2=float(allowed.area),
        missing_area_m2=float(missing_m2),
        coverage_gap_tolerance_m=tolerance,
        significant_area_m2=significant,
    )


def _expected_valid_candidates(allowed, allowed_area: MultiPolygon, stats: StraightFamilyStats, spacing: float) -> int:
    """Conta, com GEOS, as candidatas cujo interior cruza a area permitida."""
    from shapely.geometry import LineString
    from shapely.prepared import prep

    bbox = multipolygon_bbox(allowed_area)
    prepared = prep(allowed)
    first = floor(stats.projection_min / spacing)
    last = ceil(stats.projection_max / spacing)
    count = 0
    for index in range(first, last + 1):
        base = add(stats.origin, mul(stats.normal_left, index * spacing))
        candidate = build_full_candidate_line(base, stats.direction, bbox)
        line = LineString([candidate.start, candidate.end])
        if not prepared.intersects(line):
            continue
        parts = extract_valid_line_parts(allowed.intersection(line))
        # Reta sobre a borda nao e passada (mesma regra do recorte do gerador).
        if any(prepared.contains(part.interpolate(0.5, normalized=True)) for part in parts):
            count += 1
    return count


def log_family_coverage(report: FamilyCoverageReport | None) -> None:
    if report is None:
        return
    for line in report.summary_lines():
        LOGGER.info(line)
    if not report.ok:
        LOGGER.warning("%s %s", GENERATOR_INCOMPLETE_FIELD_COVERAGE, report.as_dict())


__all__ = [
    "FamilyCoverageReport",
    "default_coverage_gap_tolerance",
    "extract_valid_line_parts",
    "log_family_coverage",
    "validate_family_coverage",
]
