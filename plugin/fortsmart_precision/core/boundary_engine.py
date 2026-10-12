# -*- coding: utf-8 -*-
"""Motor de bordadura: limite externo, centros de passada e limite interno."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from math import acos, degrees
from uuid import uuid4

from ..domain.boundary_areas import BoundaryAreas, BoundaryAreasError, build_inner_and_headland
from ..domain.headland_layout import (
    HEADLAND_CORNER_AUTO,
    HEADLAND_CORNER_FOLLOW_BOUNDARY,
    HEADLAND_CORNER_STRAIGHT_THROUGH,
    HEADLAND_MODE_FIDELITY,
    HEADLAND_MODE_LEGACY,
    HeadlandLayout,
)
from ..domain.precision_project import PrecisionOperation
from .ab_direction import resolve_ab_direction_end
from .line_geometry import (
    MultiPolygon,
    Point,
    Segment,
    add,
    azimuth_degrees,
    clip_infinite_line_to_multipolygon,
    close_ring,
    distance,
    line_line_intersection,
    mul,
    multipolygon_area,
    normalize,
    perpendicular_left,
    ring_without_duplicate_close,
    ring_signed_area,
    shrink_multipolygon,
    sub,
)


LOGGER = logging.getLogger("fortsmart_precision.boundary")


class BoundaryEngineError(ValueError):
    """Erro no motor de bordadura."""


@dataclass(frozen=True)
class HeadlandCenterline:
    fs_id: str
    pass_no: int
    offset_from_outer_m: float
    segment: Segment
    azimuth_deg: float
    path_points: tuple[Point, ...] = ()
    role: str = "traffic"  # traffic = caminho do trator/implemento
    # Identidade FIDELITY (vazia no LEGACY, que mantem o esquema exportado).
    pass_id: str = ""
    parent_pass_id: str = ""
    segment_id: int = 0

    def line_points(self) -> tuple[Point, ...]:
        if self.path_points:
            return self.path_points
        return (self.segment.start, self.segment.end)

    def length_m(self) -> float:
        """Comprimento real percorrido (contorno fechado nao e start->end)."""
        points = self.line_points()
        if len(points) < 2:
            return 0.0
        return sum(distance(a, b) for a, b in zip(points, points[1:]))

    def attributes(self) -> dict[str, object]:
        attrs: dict[str, object] = {
            "fs_id": self.fs_id,
            "pass_no": self.pass_no,
            "offset_from_outer_m": self.offset_from_outer_m,
            "azimuth_deg": self.azimuth_deg,
            "length_m": self.length_m(),
            "role": self.role,
        }
        if self.pass_id:
            attrs["pass_id"] = self.pass_id
            attrs["parent_pass_id"] = self.parent_pass_id
            attrs["segment_id"] = self.segment_id
        return attrs


@dataclass(frozen=True)
class HeadlandInnerLimit:
    """Contorno do limite interno da bordadura (desligamento / miolo)."""

    fs_id: str
    ring_index: int
    points: tuple[Point, ...]

    def attributes(self) -> dict[str, object]:
        return {
            "fs_id": self.fs_id,
            "ring_index": self.ring_index,
            "role": "inner_limit",
            "vertex_count": len(self.points),
        }


@dataclass(frozen=True)
class BoundaryPlan:
    areas: BoundaryAreas
    outer_boundary: MultiPolygon
    inner_boundary: MultiPolygon | None
    headland_centerlines: tuple[HeadlandCenterline, ...]
    reserved_width_m: float
    headland_inner_limits: tuple[HeadlandInnerLimit, ...] = ()
    headland_mode: str = HEADLAND_MODE_LEGACY
    headland_fallback: bool = False
    headland_validation: dict[str, object] | None = None
    # Distancia medida de B(k) e do limite interno ao limite real.
    offset_validation: dict[str, object] | None = None

    def report(self) -> dict[str, object]:
        report: dict[str, object] = {
            **self.areas.report(),
            "headland_pass_count": len(self.headland_centerlines),
            "reserved_width_m": self.reserved_width_m,
            "headland_inner_limit_count": len(self.headland_inner_limits),
            "headland_mode": self.headland_mode,
            "HEADLAND_FALLBACK": self.headland_fallback,
        }
        if self.headland_validation is not None:
            report["headland_validation"] = self.headland_validation
        if self.offset_validation is not None:
            report["offset_validation"] = self.offset_validation
        return report

    def with_centerlines(self, centerlines: tuple[HeadlandCenterline, ...]) -> BoundaryPlan:
        return replace(self, headland_centerlines=centerlines)


def master_boundary_geometry(
    operational_boundary: MultiPolygon,
    *,
    width_m: float,
) -> MultiPolygon:
    """Geometria mestre do talhao: limite REAL densificado uma unica vez.

    Todo o resto da bordadura (limite interno, area de bordadura e linha de
    trafego) deriva desta mesma geometria — assim o limite interno e a linha do
    trator nunca discordam em curvas. Densificar apenas subdivide as arestas
    existentes: a forma do talhao permanece identica (curva continua curva,
    concavidade continua concavidade, ilha continua ilha).

    Nunca usa bounding box.
    """
    from .line_geometry import densify_multipolygon

    if not operational_boundary:
        return []
    max_edge_m = max(0.75, min(3.0, width_m / 6.0 if width_m > 0 else 2.5))
    # Vertices reais nunca saem: reamostrar cortava cantos e deslocava a bordadura.
    return densify_multipolygon(
        operational_boundary,
        max_edge_m=max_edge_m,
        max_vertices=720,
        preserve_vertices=True,
    )


def headland_traffic_offset_m(width_m: float) -> float:
    """Distancia do limite ate a linha de trafego: meia largura operacional.

    Barra de 24 m -> 12 m; 30 m -> 15 m; 36 m -> 18 m; 36,05 m -> 18,025 m.
    Deriva sempre da maquina informada na GUI; nada fixo no motor.
    """
    if width_m <= 0:
        raise BoundaryEngineError("Largura operacional deve ser maior que zero.")
    return width_m / 2.0


def build_boundary_plan(
    operational_boundary: MultiPolygon,
    operation: PrecisionOperation,
    ab_start: Point,
    ab_end: Point,
    *,
    field_boundary: MultiPolygon | None = None,
    ab_path: tuple[Point, ...] = (),
) -> BoundaryPlan:
    """Gera limite externo, linhas centrais de bordadura e limite interno.

    Aceita plantadeira ou pulverizador: a faixa reservada usa a largura operacional.
    Para 1 passada de largura W: centro (trafego) em W/2; limite interno em W.

        limite real -> W/2 -> linha de trafego -> W/2 -> area interna

    Limite interno, area de bordadura e linha de trafego saem todos da MESMA
    geometria mestre (`master_boundary_geometry`), preservando a forma do talhao.
    O `outer_boundary` devolvido continua sendo a geometria original selecionada
    pelo usuario — a camada 01_Limite_Externo nunca e recriada.

    Modos:
    - follow_boundary / perimeter: linha de trafego = contorno encolhido (forma do talhao)
    - parallel_ab: retas paralelas a A-B (legado / testes)
    """
    from .boundary_simplify import simplify_dense_boundary

    operational_boundary, _ = simplify_dense_boundary(operational_boundary)
    if field_boundary is not None:
        field_boundary, _ = simplify_dense_boundary(field_boundary)
    machine = operation.machine
    width = machine.operational_width_m
    layout = operation.headland
    if layout.pass_count <= 0:
        layout = HeadlandLayout(
            pass_count=0,
            width_m=width,
            effective_spacing_m=width,
            mode="follow_boundary",
            corner_mode=layout.corner_mode,
            sharp_angle_threshold_deg=layout.sharp_angle_threshold_deg,
            heading_sample_m=layout.heading_sample_m,
            extension_length_m=layout.extension_length_m,
            headland_mode=layout.headland_mode,
            outside_overlap_m=layout.outside_overlap_m,
        )
    else:
        layout = HeadlandLayout(
            pass_count=layout.pass_count,
            width_m=width if layout.width_m <= 0 else layout.width_m,
            effective_spacing_m=layout.spacing_m if layout.effective_spacing_m is not None else width,
            mode=layout.mode if layout.mode != "none" else "follow_boundary",
            corner_mode=layout.corner_mode,
            sharp_angle_threshold_deg=layout.sharp_angle_threshold_deg,
            heading_sample_m=layout.heading_sample_m,
            extension_length_m=layout.extension_length_m,
            headland_mode=layout.headland_mode,
            outside_overlap_m=layout.outside_overlap_m,
        )
    layout.validate()

    master = master_boundary_geometry(operational_boundary, width_m=layout.width_m) or list(
        operational_boundary
    )

    try:
        areas = build_inner_and_headland(
            master,
            layout.reserved_width_m,
            field_boundary=field_boundary,
        )
    except BoundaryAreasError as exc:
        raise BoundaryEngineError(
            f"A bordadura de {layout.reserved_width_m:.2f} m consumiu todo o talhao. "
            "Reduza o numero de passadas de bordadura ou a largura da maquina."
        ) from exc
    _validate_headland_areas(areas, layout, operational_boundary)
    fallback = False
    validation: dict[str, object] | None = None
    levels: list[tuple[int, float, list[list[Point]]]] = []
    if layout.mode in {"follow_boundary", "perimeter"}:
        centerlines = _build_perimeter_headland_centerlines(master, layout, levels)
        if layout.headland_mode == HEADLAND_MODE_FIDELITY and centerlines:
            centerlines, fallback, validation = _fidelity_or_legacy(
                operational_boundary, layout, centerlines
            )
    else:
        centerlines = _build_parallel_ab_headland_centerlines(
            operational_boundary,
            layout,
            ab_start,
            ab_end,
            operation.extension_m,
        )
    inner_limits = _build_headland_inner_limits(areas.inner_work_area)
    return BoundaryPlan(
        areas=areas,
        outer_boundary=operational_boundary,
        inner_boundary=areas.inner_work_area,
        headland_centerlines=tuple(centerlines),
        reserved_width_m=layout.reserved_width_m,
        headland_inner_limits=tuple(inner_limits),
        headland_mode=layout.headland_mode,
        headland_fallback=fallback,
        headland_validation=validation,
        offset_validation=_offset_validation(
            operational_boundary, areas.inner_work_area, layout.reserved_width_m, levels
        ),
    )


def _offset_validation(
    operational_boundary: MultiPolygon,
    inner: MultiPolygon | None,
    reserved_width_m: float,
    levels: list[tuple[int, float, list[list[Point]]]],
) -> dict[str, object] | None:
    """Mede limite interno e niveis B(k) contra o limite REAL (nao a mestre)."""
    from .spacing_validation import log_spacing_report, validate_offset_levels

    try:
        reports = {}
        if levels:
            reports["headland"] = validate_offset_levels(operational_boundary, levels, label="bordadura")
        if inner and reserved_width_m > 0:
            rings = [ring for outer, holes in inner for ring in (outer, *holes)]
            reports["inner_limit"] = validate_offset_levels(
                operational_boundary, [(0, reserved_width_m, rings)], label="limite_interno"
            )
    except Exception as exc:  # sem GEOS a medicao fica indisponivel, nao a geracao
        LOGGER.debug("Validacao de offset indisponivel: %s", exc)
        return None
    for report in reports.values():
        log_spacing_report(report)
    return {key: report.as_dict() for key, report in reports.items()} or None


def headland_pass_id(pass_no: int) -> str:
    return f"HEADLAND_{pass_no + 1:02d}"


def headland_status_note(**plans: BoundaryPlan | None) -> str:
    """Resumo para o operador; vazio quando tudo roda no LEGACY."""
    notes = []
    for label, plan in plans.items():
        if plan is None or plan.headland_mode == HEADLAND_MODE_LEGACY:
            continue
        if plan.headland_fallback:
            errors = (plan.headland_validation or {}).get("errors") or ["motivo nao informado"]
            notes.append(f"Bordadura {label}: FIDELITY falhou, usado LEGACY ({errors[0]})")
        else:
            notes.append(f"Bordadura {label}: FIDELITY")
    return " | ".join(notes)


def build_fidelity_headland_centerlines(
    operational_boundary: MultiPolygon,
    layout: HeadlandLayout,
):
    """Bordadura FIDELITY: offsets progressivos do limite REAL (sem reamostragem).

    Cada anel recebe o mesmo tratamento de ponta V/U do LEGACY
    (`_straight_through_sharp_tip`), entao cruzamentos X sao preservados e
    nenhuma passada e unida a outra. Partes separadas de um mesmo offset viram
    segmentos da mesma passada (`pass_id` + `segment_id`).
    """
    from .headland_fidelity_engine import (
        FinalHeadlandPath,
        clip_path_to_field,
        prepare_boundary,
        progressive_offsets,
        validate_fidelity_headland,
    )

    boundary = prepare_boundary(operational_boundary)
    passes = progressive_offsets(boundary, layout.center_offsets_m())
    centerlines: list[HeadlandCenterline] = []
    finals: list[FinalHeadlandPath] = []
    for item in passes:
        pass_id = headland_pass_id(item.pass_index)
        parent = "BOUNDARY" if item.pass_index == 0 else headland_pass_id(item.pass_index - 1)
        segment_id = 0
        for ring in item.rings:
            path = _straight_through_sharp_tip(ring, layout)
            for piece in clip_path_to_field(path, boundary):
                segment_id += 1
                finals.append(FinalHeadlandPath(pass_id, segment_id, piece))
                centerlines.append(
                    HeadlandCenterline(
                        fs_id=str(uuid4()),
                        pass_no=item.pass_index,
                        offset_from_outer_m=item.offset_m,
                        segment=Segment(piece[0], piece[1]),
                        azimuth_deg=azimuth_degrees(piece[0], piece[1]),
                        path_points=piece,
                        role="traffic",
                        pass_id=pass_id,
                        parent_pass_id=parent,
                        segment_id=segment_id,
                    )
                )
    return centerlines, validate_fidelity_headland(boundary, passes, finals)


def _fidelity_or_legacy(
    operational_boundary: MultiPolygon,
    layout: HeadlandLayout,
    legacy: list[HeadlandCenterline],
) -> tuple[list[HeadlandCenterline], bool, dict[str, object]]:
    """FIDELITY validado ou, se falhar, o LEGACY com HEADLAND_FALLBACK = true."""
    try:
        candidate, report = build_fidelity_headland_centerlines(operational_boundary, layout)
    except Exception as exc:  # qualquer falha nova nao pode apagar a bordadura
        return legacy, True, {"valid": False, "errors": [f"EXCEPTION: {exc}"], "warnings": []}
    validation = report.to_dict()
    errors = list(report.errors)
    missing = sorted({line.pass_no for line in legacy} - {line.pass_no for line in candidate})
    if missing:
        errors.append(
            "MISSING_PASS: passada(s) "
            + ", ".join(headland_pass_id(no) for no in missing)
            + " existem no LEGACY e nao no FIDELITY."
        )
    validation["errors"] = errors
    validation["valid"] = not errors
    if errors:
        return legacy, True, validation
    return candidate, False, validation


def _headland_summary(plan: BoundaryPlan, operational_boundary: MultiPolygon) -> dict[str, object]:
    from shapely.geometry import LineString

    from .headland_fidelity_engine import point_distances_to_boundary, prepare_boundary

    boundary = prepare_boundary(operational_boundary)
    by_pass: dict[str, list[HeadlandCenterline]] = {}
    for line in plan.headland_centerlines:
        by_pass.setdefault(line.pass_id or headland_pass_id(line.pass_no), []).append(line)
    deviations: dict[str, float] = {}
    for pass_id, lines in sorted(by_pass.items()):
        points = [p for line in lines for p in line.line_points()]
        distances = point_distances_to_boundary(points, boundary)
        offset = lines[0].offset_from_outer_m
        deviations[pass_id] = round(max(abs(d - offset) for d in distances), 3) if distances else 0.0
    lines = plan.headland_centerlines
    return {
        "headland_mode": plan.headland_mode,
        "headland_fallback": plan.headland_fallback,
        "line_count": len(lines),
        "pass_ids": sorted(by_pass),
        "segments_per_pass": {key: len(value) for key, value in sorted(by_pass.items())},
        "total_length_m": round(sum(line.length_m() for line in lines), 3),
        "crossing_lines": sum(
            1 for line in lines if len(line.line_points()) >= 4 and not LineString(line.line_points()).is_simple
        ),
        "open_lines": sum(1 for line in lines if line.line_points()[0] != line.line_points()[-1]),
        "endpoints": [
            (tuple(round(c, 2) for c in line.line_points()[0]), tuple(round(c, 2) for c in line.line_points()[-1]))
            for line in lines
            if line.line_points()[0] != line.line_points()[-1]
        ],
        "inner_area_ha": round(multipolygon_area(plan.inner_boundary or []) / 10_000.0, 6),
        "max_offset_deviation_m": deviations,
    }


def compare_headland_modes(
    operational_boundary: MultiPolygon,
    operation: PrecisionOperation,
    ab_start: Point,
    ab_end: Point,
    *,
    field_boundary: MultiPolygon | None = None,
) -> dict[str, object]:
    """Executa o mesmo projeto em LEGACY e FIDELITY e lista as diferencas."""
    summaries: dict[str, dict[str, object]] = {}
    for mode in (HEADLAND_MODE_LEGACY, HEADLAND_MODE_FIDELITY):
        op = replace(operation, headland=replace(operation.headland, headland_mode=mode))
        plan = build_boundary_plan(
            operational_boundary, op, ab_start, ab_end, field_boundary=field_boundary
        )
        summaries[mode] = _headland_summary(plan, operational_boundary)
    legacy, fidelity = summaries[HEADLAND_MODE_LEGACY], summaries[HEADLAND_MODE_FIDELITY]
    differences = {
        key: {"LEGACY": legacy[key], "FIDELITY": fidelity[key]}
        for key in legacy
        if key not in {"headland_mode"} and legacy[key] != fidelity[key]
    }
    return {
        HEADLAND_MODE_LEGACY: legacy,
        HEADLAND_MODE_FIDELITY: fidelity,
        "differences": differences,
    }


def _ring_min_distance_to_rings(
    ring: tuple[Point, ...] | list[Point],
    reference: MultiPolygon,
    *,
    max_samples: int = 96,
) -> float:
    """Menor distancia entre os vertices do anel e as arestas do limite original."""
    from .line_geometry import point_at_segment_t

    pts = ring_without_duplicate_close(ring)
    if not pts:
        return float("inf")
    step = max(1, len(pts) // max_samples)
    samples = pts[::step]

    edges: list[tuple[Point, Point]] = []
    for outer, holes in reference:
        for candidate in [outer, *holes]:
            closed = ring_without_duplicate_close(candidate)
            if len(closed) < 2:
                continue
            edges.extend(zip(closed, closed[1:] + closed[:1]))
    if not edges:
        return float("inf")

    best = float("inf")
    for point in samples:
        for start, end in edges:
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            length2 = dx * dx + dy * dy
            if length2 <= 1e-12:
                best = min(best, distance(point, start))
                continue
            t = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length2
            t = max(0.0, min(1.0, t))
            closest = point_at_segment_t(Segment(start, end), t)
            best = min(best, distance(point, closest))
    return best


def _validate_headland_areas(
    areas: BoundaryAreas,
    layout: HeadlandLayout,
    original: MultiPolygon,
) -> None:
    """Valida que o offset interno continua sendo geometria operacional util.

    Talhoes reais tem cantos fechados, concavidades, estreitamentos e ilhas.
    Um `buffer(-W)` cego pode devolver anel vazio, invertido ou raso demais
    (o offset por mitre colapsa quando a faixa e maior que o raio interno).
    Nesses casos a mensagem precisa dizer o que fazer, nao deixar o preview mudo.
    """
    if layout.pass_count <= 0:
        return
    from .line_geometry import multipolygon_area

    reserved = layout.reserved_width_m
    inner = areas.inner_work_area or []
    usable = [poly for poly in inner if len(ring_without_duplicate_close(poly[0])) >= 3]
    if not usable:
        raise BoundaryEngineError(
            f"A bordadura de {reserved:.2f} m consumiu todo o talhao. "
            "Reduza o numero de passadas de bordadura ou a largura da maquina."
        )

    original_area = multipolygon_area(original)
    inner_area = multipolygon_area(usable)
    if original_area > 0 and inner_area / original_area < 0.02:
        raise BoundaryEngineError(
            f"A bordadura de {reserved:.2f} m deixou menos de 2% do talhao "
            "para o miolo. Reduza a faixa de bordadura."
        )

    # O miolo precisa estar realmente a `reserved` metros do limite. Se o offset
    # colapsou, a distancia medida fica muito abaixo do pedido.
    if reserved > 0:
        measured = min(
            _ring_min_distance_to_rings(poly[0], original) for poly in usable
        )
        if measured < reserved * 0.75:
            raise BoundaryEngineError(
                f"A bordadura de {reserved:.2f} m nao cabe neste talhao: o miolo "
                f"ficaria a apenas {measured:.2f} m do limite. Reduza a faixa de "
                "bordadura ou a largura da maquina."
            )


def _build_headland_inner_limits(
    inner_boundary: MultiPolygon | None,
) -> list[HeadlandInnerLimit]:
    if not inner_boundary:
        return []
    limits: list[HeadlandInnerLimit] = []
    for index, polygon in enumerate(inner_boundary):
        outer, _holes = polygon
        points = tuple(close_ring(ring_without_duplicate_close(outer)))
        if len(points) < 4:
            continue
        limits.append(
            HeadlandInnerLimit(
                fs_id=str(uuid4()),
                ring_index=index,
                points=points,
            )
        )
    return limits


def _build_perimeter_headland_centerlines(
    master: MultiPolygon,
    layout: HeadlandLayout,
    levels: list[tuple[int, float, list[list[Point]]]] | None = None,
) -> list[HeadlandCenterline]:
    """Linha de trafego = contorno do buffer(-W/2) da geometria mestre.

    Recebe a geometria mestre ja densificada (`master_boundary_geometry`) para
    compartilhar exatamente a mesma referencia do limite interno. Cada nivel
    B(k) sai da MESMA geometria mestre (offset absoluto), nunca do anterior.
    `levels` recebe os aneis teoricos (antes do tratamento de pontas).
    """
    if layout.pass_count <= 0:
        return []
    work = master
    centerlines: list[HeadlandCenterline] = []
    for index, offset_from_outer in enumerate(layout.center_offsets_m()):
        shrunk = shrink_multipolygon(work, offset_from_outer)
        if levels is not None:
            levels.append((index, offset_from_outer, [list(poly[0]) for poly in shrunk]))
        for poly in shrunk:
            ring = ring_without_duplicate_close(poly[0])
            if len(ring) < 3:
                continue
            closed = tuple(close_ring(ring))
            path = _straight_through_sharp_tip(closed, layout)
            centerlines.append(
                HeadlandCenterline(
                    fs_id=str(uuid4()),
                    pass_no=index,
                    offset_from_outer_m=offset_from_outer,
                    segment=Segment(path[0], path[1]),
                    azimuth_deg=azimuth_degrees(path[0], path[1]),
                    path_points=path,
                    role="traffic",
                )
            )
    return centerlines


def _walk_ring_index(
    points: list[Point], start: int, direction: int, target_distance_m: float
) -> int:
    """Indice a uma distancia acumulada no anel, sem interpolar a geometria."""
    index = start
    travelled = 0.0
    for _ in range(len(points) - 1):
        nxt = (index + direction) % len(points)
        travelled += distance(points[index], points[nxt])
        index = nxt
        if travelled >= target_distance_m:
            break
    return index


def _walk_ring_location(
    points: list[Point], start: int, direction: int, target_distance_m: float
) -> tuple[Point, int]:
    """Ponto interpolado a uma distancia real e o vertice seguinte no percurso."""
    index = start
    remaining = target_distance_m
    for _ in range(len(points) - 1):
        nxt = (index + direction) % len(points)
        edge_length = distance(points[index], points[nxt])
        if edge_length > 1e-9 and remaining <= edge_length:
            ratio = max(0.0, min(1.0, remaining / edge_length))
            return (
                add(points[index], mul(sub(points[nxt], points[index]), ratio)),
                nxt,
            )
        remaining -= edge_length
        index = nxt
    return points[index], index


def _circular_candidate_groups(indices: list[int], size: int) -> list[list[int]]:
    """Agrupa indices vizinhos, inclusive quando o grupo cruza o inicio do anel."""
    if not indices:
        return []
    ordered = sorted(set(indices))
    groups = [[ordered[0]]]
    for index in ordered[1:]:
        if index == groups[-1][-1] + 1:
            groups[-1].append(index)
        else:
            groups.append([index])
    if len(groups) > 1 and groups[0][0] == 0 and groups[-1][-1] == size - 1:
        groups[0] = groups[-1] + groups[0]
        groups.pop()
    return groups


def _corner_angle_deg(before: Point, current: Point, after: Point) -> float:
    left = sub(before, current)
    right = sub(after, current)
    left_len = distance(before, current)
    right_len = distance(after, current)
    if left_len <= 1e-9 or right_len <= 1e-9:
        return 180.0
    cosine = (left[0] * right[0] + left[1] * right[1]) / (left_len * right_len)
    return degrees(acos(max(-1.0, min(1.0, cosine))))


def _straight_through_sharp_tip(
    closed_ring: tuple[Point, ...], layout: HeadlandLayout
) -> tuple[Point, ...]:
    """Abre uma ponta aguda e prolonga suas pernas ate formar um X.

    A feicao continua unica: remove apenas o retorno curto da ponta. Os dois
    segmentos terminais preservam seus headings e podem se cruzar sem split.
    """
    if layout.corner_mode == HEADLAND_CORNER_FOLLOW_BOUNDARY:
        return closed_ring
    points = ring_without_duplicate_close(closed_ring)
    if len(points) < 6:
        return closed_ring

    detection_sample_m = max(5.0, min(20.0, layout.width_m))
    orientation = 1.0 if ring_signed_area(points) >= 0 else -1.0
    candidates: list[tuple[float, int]] = []
    for index, current in enumerate(points):
        before, _ = _walk_ring_location(points, index, -1, detection_sample_m)
        after, _ = _walk_ring_location(points, index, 1, detection_sample_m)
        incoming = sub(current, before)
        outgoing = sub(after, current)
        cross = incoming[0] * outgoing[1] - incoming[1] * outgoing[0]
        if cross * orientation <= 0:
            continue
        angle = _corner_angle_deg(before, current, after)
        candidates.append((angle, index))
    if not candidates:
        return closed_ring

    candidate_angle = {index: angle for angle, index in candidates}
    if layout.corner_mode == HEADLAND_CORNER_AUTO:
        groups = _circular_candidate_groups(
            [
                index
                for angle, index in candidates
                if angle < max(layout.sharp_angle_threshold_deg, 100.0)
            ],
            len(points),
        )
        # Um V possui pelo menos um angulo abaixo do limite configurado. Um U
        # curto aparece como uma sequencia de curvas fortes: nao deve ser
        # confundido com um canto isolado de 90 graus do talhao.
        groups = [
            group
            for group in groups
            if any(
                candidate_angle[index] < layout.sharp_angle_threshold_deg
                for index in group
            )
            or (
                len(group) >= 3
                and min(candidate_angle[index] for index in group) < 90.0
            )
        ]
    else:
        groups = _circular_candidate_groups(
            [index for angle, index in candidates if angle < 170.0], len(points)
        )
    if not groups:
        return closed_ring

    group = min(
        groups, key=lambda item: min(candidate_angle[index] for index in item)
    )
    _tip_index = group[len(group) // 2]

    # A janela de heading precisa alcancar as pernas estaveis, alem da curva
    # curta da ponta. A configuracao explicita sempre prevalece.
    heading_sample_m = layout.heading_sample_m or max(
        10.0, min(30.0, layout.width_m * 1.5)
    )
    before, before_anchor = _walk_ring_location(
        points, _tip_index, -1, heading_sample_m
    )
    far_before, _ = _walk_ring_location(
        points, _tip_index, -1, heading_sample_m * 2.0
    )
    after, after_anchor = _walk_ring_location(
        points, _tip_index, 1, heading_sample_m
    )
    far_after, _ = _walk_ring_location(
        points, _tip_index, 1, heading_sample_m * 2.0
    )
    if distance(far_before, before) <= 1e-9 or distance(after, far_after) <= 1e-9:
        return closed_ring
    incoming_dir = normalize(sub(before, far_before))
    outgoing_dir = normalize(sub(far_after, after))
    hit = line_line_intersection(
        before, add(before, incoming_dir),
        after, add(after, outgoing_dir),
    )
    beyond = layout.extension_length_m or max(
        layout.half_width_m, heading_sample_m / 2.0
    )
    if hit is not None and distance(hit, points[_tip_index]) <= max(
        4.0 * heading_sample_m, 4.0 * layout.width_m
    ):
        incoming_extension = add(hit, mul(incoming_dir, beyond))
        outgoing_extension = add(hit, mul(outgoing_dir, -beyond))
    else:
        # U estreito: pernas paralelas nao possuem interseccao finita. Cada
        # heading atravessa a ponta pela distancia local, sem criar retorno.
        span = max(
            distance(before, points[_tip_index]),
            distance(after, points[_tip_index]),
        ) + beyond
        incoming_extension = add(before, mul(incoming_dir, span))
        outgoing_extension = add(after, mul(outgoing_dir, -span))

    kept: list[Point] = [after]
    index = after_anchor
    for _ in range(len(points)):
        if points[index] != kept[-1]:
            kept.append(points[index])
        if index == before_anchor:
            break
        index = (index + 1) % len(points)
    else:
        return closed_ring
    if kept[-1] != before:
        kept.append(before)
    return tuple([outgoing_extension, *kept, incoming_extension])


def _build_parallel_ab_headland_centerlines(
    operational: MultiPolygon,
    layout: HeadlandLayout,
    ab_start: Point,
    ab_end: Point,
    extension_m: float,
) -> list[HeadlandCenterline]:
    if layout.pass_count <= 0:
        return []

    ab_end_dir = resolve_ab_direction_end(ab_start, ab_end)
    direction = normalize(sub(ab_end_dir, ab_start))
    normal_left = perpendicular_left(direction)
    azimuth = azimuth_degrees(ab_start, ab_end_dir)
    centerlines: list[HeadlandCenterline] = []

    for index, offset_from_outer in enumerate(layout.center_offsets_m()):
        # Offset medido a partir do limite externo para dentro do talhao.
        base = add(ab_start, mul(normal_left, -offset_from_outer))
        clipped = clip_infinite_line_to_multipolygon(base, direction, operational)
        if not clipped:
            continue
        longest = max(clipped, key=lambda seg: seg.length)
        if extension_m > 0:
            from .line_geometry import extend_segment

            guidance = extend_segment(longest.start, longest.end, extension_m)
            segment = guidance
        else:
            segment = longest
        centerlines.append(
            HeadlandCenterline(
                fs_id=str(uuid4()),
                pass_no=index,
                offset_from_outer_m=offset_from_outer,
                segment=segment,
                azimuth_deg=azimuth,
                role="traffic",
            )
        )
    return centerlines
