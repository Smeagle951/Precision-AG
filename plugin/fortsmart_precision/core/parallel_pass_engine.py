# -*- coding: utf-8 -*-
"""Motor comum para passadas paralelas baseadas em linha mestre (reta ou curva)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from math import ceil, floor
from uuid import uuid4

from .ab_direction import resolve_ab_direction_end
from .line_geometry import (
    MultiPolygon,
    Point,
    Segment,
    add,
    azimuth_degrees,
    bbox_corners,
    build_processing_boundary,
    clip_infinite_line_to_multipolygon,
    clip_polyline_exact,
    distance,
    dot,
    extend_polyline_ends,
    mul,
    multipolygon_bbox,
    normalize,
    offset_open_polyline_exact,
    perpendicular_left,
    signed_distances_to_polyline,
    signed_projection,
    sub,
)

LOGGER = logging.getLogger("fortsmart_precision.generator")

GEOMETRY_TOLERANCE_M = 0.01
GENERATOR_INCOMPLETE_FIELD_COVERAGE = "GENERATOR_INCOMPLETE_FIELD_COVERAGE"
PASS_SEGMENT_FIELDS = ("pass_number", "segment_index", "segment_count", "source_candidate_index")


class ParallelPassError(ValueError):
    """Erro de configuracao do motor de passadas."""


@dataclass(frozen=True)
class ParallelPassParams:
    polygons: MultiPolygon
    ab_start: Point
    ab_end: Point
    pass_spacing_m: float
    operation_width_m: float
    extension_m: float = 10.0
    ab_offset_right_m: float = 0.0
    lateral_offset_m: float = 0.0
    min_length_m: float = 0.0
    operation_id: str = ""
    is_headland: bool = False
    first_pass_no: int = 0
    master_path: tuple[Point, ...] = ()
    # Limite original (operacional) para expandir com extensao; se None, usa polygons.
    clip_boundary: MultiPolygon | None = None

    def validate(self) -> None:
        if not self.polygons:
            raise ParallelPassError("Limite vazio.")
        try:
            resolve_ab_direction_end(
                self.ab_start,
                self.ab_end,
                self.resolved_master_path(),
            )
        except ValueError as exc:
            raise ParallelPassError(str(exc)) from exc
        if self.pass_spacing_m <= 0:
            raise ParallelPassError("Espacamento entre passadas deve ser maior que zero.")
        if self.operation_width_m <= 0:
            raise ParallelPassError("Largura operacional deve ser maior que zero.")
        if self.extension_m < 0:
            raise ParallelPassError("Extensao externa nao pode ser negativa.")

    def resolved_master_path(self) -> tuple[Point, ...]:
        from .line_geometry import sanitize_master_polyline

        if len(self.master_path) >= 2:
            return tuple(sanitize_master_polyline(self.master_path))
        return (self.ab_start, self.ab_end)

    def coverage_polygons(self) -> MultiPolygon:
        """Area que define quais offsets gerar (miolo / operacional — sem buffer)."""
        return self.polygons

    def processing_polygons(self) -> MultiPolygon:
        """Limite de clip: original.buffer(extensao). Nao altera o talhao visual."""
        base = self.clip_boundary if self.clip_boundary else self.polygons
        return build_processing_boundary(base, self.extension_m)


@dataclass(frozen=True)
class ParallelPass:
    fs_id: str
    operation_id: str
    pass_no: int
    spacing_m: float
    width_m: float
    half_width_m: float
    offset_m: float
    azimuth_deg: float
    length_m: float
    is_headland: bool
    clipped_segment: Segment
    guidance_segment: Segment
    path_points: tuple[Point, ...] = ()
    # Partes de uma mesma reta candidata compartilham pass_no (P35/0, P35/1).
    source_candidate_index: int | None = None
    segment_index: int = 0
    segment_count: int = 1

    def line_points(self) -> tuple[Point, ...]:
        if len(self.path_points) >= 2:
            return self.path_points
        return (self.guidance_segment.start, self.guidance_segment.end)

    def attributes(self) -> dict[str, object]:
        return {
            "fs_id": self.fs_id,
            "operation_id": self.operation_id,
            "pass_no": self.pass_no,
            "line_no": self.pass_no,
            "spacing_m": self.spacing_m,
            "width_m": self.width_m,
            "half_width_m": self.half_width_m,
            "offset_m": self.offset_m,
            "azimuth_deg": self.azimuth_deg,
            "length_m": self.length_m,
            "is_headland": self.is_headland,
        }


def generate_parallel_passes(params: ParallelPassParams) -> list[ParallelPass]:
    """Gera linhas centrais de operacao a partir da geometria mestra.

    Ordem correta da extensao:
      1) cobertura = limite de trabalho (miolo / operacional) — define offsets
      2) processing = cobertura_ou_operacional.buffer(+extensao)
      3) offsets da linha mestra
      4) intersection(processing) — sem segundo clip no limite original

    Bbox so dimensiona indices; nunca vira geometria de saida.
    """
    return generate_parallel_passes_with_stats(params)[0]


@dataclass
class StraightFamilyStats:
    """Diagnostico da familia reta: faixa projetada do talhao e candidatas."""

    origin: Point = (0.0, 0.0)
    direction: Point = (1.0, 0.0)
    normal_left: Point = (0.0, 1.0)
    projection_min: float = 0.0
    projection_max: float = 0.0
    generation_margin: float = 0.0
    candidates_tested: int = 0
    candidates_empty: int = 0
    candidates_valid: int = 0
    candidate_parts: dict[int, int] = field(default_factory=dict)

    @property
    def is_straight(self) -> bool:
        return self.candidates_tested > 0


def generate_parallel_passes_with_stats(
    params: ParallelPassParams,
) -> tuple[list[ParallelPass], StraightFamilyStats | None]:
    """Igual a `generate_parallel_passes`, devolvendo o diagnostico da familia reta."""
    params.validate()
    master = params.resolved_master_path()
    if len(master) >= 3:
        return _generate_curved_passes(params, master), None
    stats = StraightFamilyStats()
    return _generate_straight_passes(params, stats), stats


def compute_polygon_projection_range(
    polygons: MultiPolygon,
    origin: Point,
    axis: Point,
) -> tuple[float, float]:
    """Min/max da projecao de todos os vertices (externos e furos) no eixo."""
    values = [
        signed_projection(point, origin, axis)
        for outer, holes in polygons
        for ring in (outer, *holes)
        for point in ring
    ]
    if not values:
        raise ParallelPassError("Limite sem vertices para projetar.")
    return min(values), max(values)


def generation_margin(
    implement_width_m: float,
    pass_spacing_m: float,
    geometry_tolerance_m: float = GEOMETRY_TOLERANCE_M,
) -> float:
    return max(float(implement_width_m), float(pass_spacing_m) * 2.0, geometry_tolerance_m * 10.0)


def merge_continuous_segments(
    parts: list[Segment],
    tolerance_m: float = GEOMETRY_TOLERANCE_M,
) -> list[Segment]:
    """Une partes colineares ordenadas que se tocam; lacunas reais continuam separadas."""
    merged: list[Segment] = []
    for segment in parts:
        if merged and distance(merged[-1].end, segment.start) <= tolerance_m:
            merged[-1] = Segment(merged[-1].start, segment.end)
        else:
            merged.append(segment)
    return merged


def build_full_candidate_line(
    base: Point,
    direction: Point,
    bbox: tuple[float, float, float, float],
) -> Segment:
    """Segmento finito da candidata atravessando todo o bbox (meia-extensao = 2x diagonal)."""
    xmin, ymin, xmax, ymax = bbox
    diagonal = ((xmax - xmin) ** 2 + (ymax - ymin) ** 2) ** 0.5
    half_length = max(diagonal * 2.0, GEOMETRY_TOLERANCE_M * 10.0)
    center = ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0)
    mid = add(base, mul(direction, dot(sub(center, base), direction)))
    return Segment(
        add(mid, mul(direction, -half_length)),
        add(mid, mul(direction, half_length)),
    )


def straight_family_frame(
    ab_start: Point,
    ab_end: Point,
    master_path: tuple[Point, ...] = (),
    ab_offset_right_m: float = 0.0,
) -> tuple[Point, Point, Point] | None:
    """Referencial canonico (origem, direcao, normal_esquerda) da familia reta.

    Passada i = origem + normal * (i * espacamento): posicao absoluta, nunca a
    partir da passada anterior. None quando a linha mestra e curva.
    """
    params = ParallelPassParams(
        polygons=[],
        ab_start=ab_start,
        ab_end=ab_end,
        pass_spacing_m=1.0,
        operation_width_m=1.0,
        ab_offset_right_m=ab_offset_right_m,
        master_path=tuple(master_path),
    )
    master = params.resolved_master_path()
    if len(master) >= 3:
        return None
    ab_end_dir = resolve_ab_direction_end(ab_start, ab_end, master)
    direction = normalize(sub(ab_end_dir, ab_start))
    normal_left = perpendicular_left(direction)
    origin = add(ab_start, mul(normal_left, -ab_offset_right_m))
    return origin, direction, normal_left


def _generate_straight_passes(
    params: ParallelPassParams,
    stats: StraightFamilyStats | None = None,
) -> list[ParallelPass]:
    ab_end_dir = resolve_ab_direction_end(
        params.ab_start,
        params.ab_end,
        params.resolved_master_path(),
    )
    shifted_ab_start, direction, normal_left = straight_family_frame(
        params.ab_start, params.ab_end, params.master_path, params.ab_offset_right_m
    )
    coverage = params.coverage_polygons()
    processing = params.processing_polygons()
    # A-B define direcao e fase; a cobertura inteira (sem buffer) define ate onde gerar.
    projection_min, projection_max = compute_polygon_projection_range(
        coverage, shifted_ab_start, normal_left
    )
    margin = generation_margin(params.operation_width_m, params.pass_spacing_m)
    start_index = floor((projection_min - margin) / params.pass_spacing_m)
    end_index = ceil((projection_max + margin) / params.pass_spacing_m)
    azimuth = azimuth_degrees(params.ab_start, ab_end_dir)
    if stats is not None:
        stats.origin = shifted_ab_start
        stats.direction = direction
        stats.normal_left = normal_left
        stats.projection_min = projection_min
        stats.projection_max = projection_max
        stats.generation_margin = margin

    raw: list[tuple[float, Segment, Segment, tuple[Point, ...]]] = []
    candidates: list[int] = []
    for index in range(start_index, end_index + 1):
        offset_left = index * params.pass_spacing_m
        base = add(shifted_ab_start, mul(normal_left, offset_left))
        parts: list[Segment] = []
        # So gera passada se cruza a cobertura real (evita fantasma so no anel +extensao).
        # Candidata vazia nao encerra a familia: concavidades deixam buracos no meio.
        if clip_infinite_line_to_multipolygon(base, direction, coverage):
            # Clip final no limite operacional expandido — a extensao vive aqui.
            parts = clip_infinite_line_to_multipolygon(base, direction, processing)
        # Todas as partes no sentido A->B, ordenadas pela projecao longitudinal.
        parts.sort(key=lambda seg: dot(sub(seg.start, shifted_ab_start), direction))
        parts = [
            segment
            for segment in merge_continuous_segments(parts)
            if segment.length >= params.min_length_m
        ]
        if stats is not None:
            stats.candidates_tested += 1
            if parts:
                stats.candidates_valid += 1
                stats.candidate_parts[index] = len(parts)
            else:
                stats.candidates_empty += 1
        if parts:
            LOGGER.debug("candidate=%d offset=%.1f parts=%d", index, offset_left, len(parts))
        for segment in parts:
            raw.append((offset_left, segment, segment, (segment.start, segment.end)))
            candidates.append(index)

    return _materialize_passes(params, raw, azimuth, candidate_indices=candidates)


def _generate_curved_passes(
    params: ParallelPassParams,
    master: tuple[Point, ...],
) -> list[ParallelPass]:
    coverage = params.coverage_polygons()
    processing = params.processing_polygons()
    sample_points: list[Point] = []
    for outer, holes in coverage:
        sample_points.extend(outer)
        for hole in holes:
            sample_points.extend(hole)
    if not sample_points:
        bbox = multipolygon_bbox(coverage)
        sample_points = bbox_corners(bbox)

    offsets = signed_distances_to_polyline(sample_points, master)
    start_index = floor((min(offsets) - params.pass_spacing_m * 2) / params.pass_spacing_m)
    end_index = ceil((max(offsets) + params.pass_spacing_m * 2) / params.pass_spacing_m)
    azimuth = azimuth_degrees(master[0], master[-1])

    # A-B curva CURTA precisa atravessar o talhao inteiro: lead = diagonal do
    # processing (talhao + extensao), nao so extension_m + spacing. Caso contrario
    # a passada para longe da borda (lacunas de dezenas/centenas de metros).
    proc_bbox = multipolygon_bbox(processing)
    diag = (
        (proc_bbox[2] - proc_bbox[0]) ** 2 + (proc_bbox[3] - proc_bbox[1]) ** 2
    ) ** 0.5
    lead = max(
        float(params.extension_m),
        diag,
        max(params.pass_spacing_m, params.operation_width_m) * 2.0,
    )
    master_for_offset = extend_polyline_ends(master, lead)

    raw: list[tuple[float, Segment, Segment, tuple[Point, ...]]] = []
    for index in range(start_index, end_index + 1):
        # Sempre da mestre original: P_n fica a n x largura em toda a curva.
        offset_left = index * params.pass_spacing_m - params.ab_offset_right_m
        work_chunks: list[list[Point]] = []
        for offset_path in offset_open_polyline_exact(master_for_offset, offset_left):
            if len(offset_path) < 2:
                continue
            if not clip_polyline_exact(offset_path, coverage):
                continue
            # Estende o offset inteiro ate cobrir o processing, depois um unico clip.
            # Clip exato: a ponta cai no limite sem prolongar por tangente (que
            # sairia da curva e mudaria a distancia para a vizinha).
            offset_path = extend_polyline_ends(offset_path, lead)
            work_chunks.extend(clip_polyline_exact(offset_path, processing))
        for chunk in work_chunks:
            if len(chunk) < 2:
                continue
            clipped = Segment(chunk[0], chunk[-1])
            length = sum(distance(a, b) for a, b in zip(chunk, chunk[1:]))
            if length < params.min_length_m:
                continue
            from .line_geometry import ensure_segment_span

            try:
                guidance = ensure_segment_span(
                    clipped,
                    tuple(chunk),
                    at_index=0,
                    half_span_m=max(8.0, params.pass_spacing_m),
                    min_span_m=0.5,
                )
            except ValueError:
                guidance = clipped
            raw.append((offset_left, clipped, guidance, tuple(chunk)))

    raw.sort(key=lambda item: (item[0], item[1].start[0], item[1].start[1]))
    return _materialize_passes(params, raw, azimuth)


def _materialize_passes(
    params: ParallelPassParams,
    raw: list[tuple[float, Segment, Segment, tuple[Point, ...]]],
    azimuth: float,
    *,
    candidate_indices: list[int] | None = None,
) -> list[ParallelPass]:
    """Materializa passadas com numeracao relativa a A-B (linha 0 = referencia).

    Com `candidate_indices`, a numeracao segue a reta candidata: todas as partes
    da mesma candidata recebem o mesmo pass_no e um segment_index proprio.
    """
    if not raw:
        return []
    # offset_left ~ 0 e a passada sobre a linha A-B / camada selecionada.
    zero_idx = min(range(len(raw)), key=lambda i: (abs(raw[i][0]), i))
    segment_counts: dict[int, int] = {}
    if candidate_indices is not None:
        for candidate in candidate_indices:
            segment_counts[candidate] = segment_counts.get(candidate, 0) + 1
    segment_seen: dict[int, int] = {}
    passes: list[ParallelPass] = []
    for index, (offset_left, clipped, guidance, path) in enumerate(raw):
        candidate: int | None = None
        segment_index = 0
        segment_count = 1
        if candidate_indices is not None:
            candidate = candidate_indices[index]
            pass_no = params.first_pass_no + (candidate - candidate_indices[zero_idx])
            segment_index = segment_seen.get(candidate, 0)
            segment_seen[candidate] = segment_index + 1
            segment_count = segment_counts[candidate]
        else:
            pass_no = params.first_pass_no + (index - zero_idx)
        passes.append(
            ParallelPass(
                fs_id=str(uuid4()),
                operation_id=params.operation_id,
                pass_no=pass_no,
                spacing_m=params.pass_spacing_m,
                width_m=params.operation_width_m,
                half_width_m=params.operation_width_m / 2.0,
                offset_m=-offset_left,
                azimuth_deg=azimuth,
                length_m=(
                    sum(distance(a, b) for a, b in zip(path, path[1:]))
                    if len(path) >= 2
                    else guidance.length
                ),
                is_headland=params.is_headland,
                clipped_segment=clipped,
                guidance_segment=guidance,
                path_points=path if len(path) >= 2 else (),
                source_candidate_index=candidate,
                segment_index=segment_index,
                segment_count=segment_count,
            )
        )
    return passes


def pass_segment_layout(passes) -> list[tuple[int, int]]:
    """(segment_index, segment_count) por feicao, agrupando pelo pass_no final.

    Recalculado sobre a lista final porque recortes posteriores (suavizacao,
    extensao, desvio) podem dividir uma passada em mais partes.
    """
    groups: dict[int, list[int]] = {}
    for position, item in enumerate(passes):
        groups.setdefault(int(item.pass_no), []).append(position)
    layout: list[tuple[int, int]] = [(0, 1)] * len(passes)
    for positions in groups.values():
        if len(positions) == 1:
            continue
        first = passes[positions[0]].line_points()
        origin = first[0]
        axis = normalize(sub(first[-1], first[0])) if distance(first[0], first[-1]) > 0 else (1.0, 0.0)

        def longitudinal(position: int) -> tuple[float, int]:
            return (dot(sub(passes[position].line_points()[0], origin), axis), position)

        ordered = sorted(positions, key=longitudinal)
        for segment_index, position in enumerate(ordered):
            layout[position] = (segment_index, len(ordered))
    return layout


def source_candidate_index_for(item) -> int | None:
    """Indice da reta candidata (offset/espacamento a partir da A-B)."""
    explicit = getattr(item, "source_candidate_index", None)
    if explicit is not None:
        return int(explicit)
    spacing = float(getattr(item, "spacing_m", 0.0) or 0.0)
    if spacing <= 0:
        return None
    return int(round(-float(item.offset_m) / spacing))


def line_label_for_pass(pass_no: int, *, machine_prefix: str = "") -> str:
    """Rotulo visivel: '0', 'P0', 'A-1', etc."""
    prefix = (machine_prefix or "").strip()
    return f"{prefix}{pass_no}"
