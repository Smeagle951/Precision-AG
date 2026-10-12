# -*- coding: utf-8 -*-
"""Importa AdaptiveCurve: corta U de cabeceira, preserva desvios do miolo, mantem path_points.

Fluxo (modelo operacional):
  AdaptiveCurve completa
    -> todas as partes
    -> U-turn perto do Boundary + liga faixas = cortar
    -> curva no miolo = preservar
    -> estender pontas + clip no processing boundary
    -> last_result.spraying_passes (polilinhas completas)
  Aplicar desvio (etapa separada):
    -> so onde a polilinha ainda intersecta envelope
    -> idempotente se ja contorna
"""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, degrees
from uuid import uuid4

from ..domain.headland_layout import HeadlandLayout
from ..domain.machine_model import PlanterMachine, SprayerMachine
from ..domain.planting_kinematics import PlantingKinematics
from ..domain.precision_project import ABLine, PrecisionOperation
from .boundary_engine import BoundaryPlan, build_boundary_plan
from .guidance_engine import TrafficPass, generate_traffic_passes
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
from .planting_kinematics_engine import generate_rows_from_tractor_paths, kinematics_from_planter
from .row_engine import PlantingRow


class AdaptiveCurveImportError(ValueError):
    """Erro ao importar / limpar AdaptiveCurve."""


@dataclass(frozen=True)
class AdaptiveCurveImportResult:
    passes: list[TrafficPass]
    stripped_uturn_count: int
    source_polyline_count: int
    labels: tuple[str, ...]
    removed_contour_count: int = 0
    master_path: tuple[Point, ...] = ()


@dataclass(frozen=True)
class AdaptiveCurvePlanResult:
    """Plano completo: passadas limpas + plantio/bordadura pela mestra (motores existentes)."""

    spraying_passes: list[TrafficPass]
    planting_passes: list[TrafficPass]
    planting_rows: list[PlantingRow]
    spraying_boundary: BoundaryPlan | None
    planting_boundary: BoundaryPlan | None
    ab_line: ABLine
    stripped_uturn_count: int
    removed_contour_count: int
    source_polyline_count: int
    master_path: tuple[Point, ...]
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
    min_turn_deg: float = 90.0,
) -> AdaptiveCurveImportResult:
    """Importa TODAS as partes; corta so U de cabeceira; preserva path_points do miolo.

    Nunca descarta a AdaptiveCurve para regenerar por A-B: o resultado sao as
    proprias passadas limpas (polilinhas completas).
    """
    if not field:
        raise AdaptiveCurveImportError("Talhao vazio para importar AdaptiveCurve.")
    band = (
        headland_band_m
        if headland_band_m is not None
        else _default_headland_band_m(field, width_m)
    )

    cleaned: list[list[Point]] = []
    stripped = 0
    removed_contour = 0
    source_count = 0

    for raw in polylines:
        pts = _clean_points(raw)
        if len(pts) < 2:
            continue
        source_count += 1
        # Conector U isolado (feicao curta so de cabeceira) — descarta.
        if _is_uturn_connector_feature(pts, field, headland_band_m=band, spacing_m=pass_spacing_m):
            stripped += 1
            continue
        # Contorno fechado / anel de cabeceira — so anel curto (nao serpentina de miolo).
        if _is_closed_headland_contour(
            pts, field, headland_band_m=band, spacing_m=pass_spacing_m
        ):
            removed_contour += 1
            continue
        parts, n_cut = split_serpentine_strip_uturns(
            pts,
            field,
            headland_band_m=band,
            min_turn_deg=min_turn_deg,
        )
        stripped += n_cut
        # Fallback: se ainda restou 1 serpentina longa, corta por reversoes de rumo na cabeceira.
        if len(parts) == 1 and _looks_like_unsplit_serpentine(parts[0], spacing_m=pass_spacing_m):
            parts2, n2 = split_by_headland_heading_reversals(
                parts[0],
                field,
                headland_band_m=band,
                spacing_m=pass_spacing_m,
            )
            if len(parts2) > 1:
                parts = parts2
                stripped += n2
        for part in parts:
            if len(part) < 2:
                continue
            if _is_uturn_connector_feature(part, field, headland_band_m=band, spacing_m=pass_spacing_m):
                stripped += 1
                continue
            if _is_closed_headland_contour(
                part, field, headland_band_m=band, spacing_m=pass_spacing_m
            ):
                removed_contour += 1
                continue
            cleaned.append(part)

    if not cleaned:
        raise AdaptiveCurveImportError(
            "Nenhuma passada util apos cortar retornos. "
            "Verifique se a camada AdaptiveCurve tem linhas de miolo no talhao."
        )

    processing = build_processing_boundary(field, extension_m)
    extended_parts: list[list[Point]] = []
    for part in cleaned:
        ext = extend_polyline_ends(part, extension_m)
        chunks = clip_polyline_to_multipolygon(ext, processing) if processing else [ext]
        if not chunks:
            if len(ext) >= 2:
                extended_parts.append(ext)
            continue
        longest = max(chunks, key=lambda c: polyline_length(c))
        if len(longest) >= 2:
            extended_parts.append(longest)

    if not extended_parts:
        raise AdaptiveCurveImportError("Passadas vazias apos extensao/clip.")

    numbered = _number_passes_by_lateral_offset(extended_parts)
    passes: list[TrafficPass] = []
    labels: list[str] = []
    master_path: tuple[Point, ...] = ()

    for pass_no, pts in numbered:
        # Densidade suficiente para manter arcos de desvio do miolo.
        path = tuple(decimate_polyline(pts, min_step_m=1.5, max_points=400))
        if len(path) < 2:
            continue
        if pass_no == 0 or not master_path:
            master_path = path
        seg = Segment(path[0], path[-1])
        az = degrees(atan2(path[-1][1] - path[0][1], path[-1][0] - path[0][0])) % 360.0
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
                # Sempre guarda polilinha completa (mesmo com 2 pts) para o desvio operar nela.
                path_points=path,
            )
        )
        labels.append(line_label_for_pass(pass_no, machine_prefix="A"))

    if not passes:
        raise AdaptiveCurveImportError("Nenhuma passada materializada.")

    for traffic in passes:
        if traffic.pass_no == 0:
            master_path = traffic.line_points()
            break

    return AdaptiveCurveImportResult(
        passes=passes,
        stripped_uturn_count=stripped,
        source_polyline_count=source_count,
        labels=tuple(labels),
        removed_contour_count=removed_contour,
        master_path=master_path,
    )


def build_plan_from_adaptive_curve(
    polylines: list[list[Point] | tuple[Point, ...]],
    field: MultiPolygon,
    *,
    sprayer: SprayerMachine,
    planter: PlanterMachine | None,
    spray_headland: HeadlandLayout,
    plant_headland: HeadlandLayout | None = None,
    spray_extension_m: float = 10.0,
    plant_extension_m: float = 10.0,
    plant_kinematics: PlantingKinematics | None = None,
) -> AdaptiveCurvePlanResult:
    """Passadas limpas da AdaptiveCurve + plantio/bordadura pelos motores ja existentes.

    IMPORTANTE: pulverizacao = geometria importada (apos corte de U). Nunca regenera
    spray por A-B — isso descartava a AdaptiveCurve e gerava paralelas novas.
    """
    spray_width = sprayer.operational_width_m
    imported = import_adaptive_curve_passes(
        polylines,
        field,
        extension_m=spray_extension_m,
        pass_spacing_m=spray_width,
        width_m=spray_width,
        operation_id="spraying",
        headland_band_m=_default_headland_band_m(field, spray_width),
    )
    master = list(imported.master_path) or list(imported.passes[0].line_points())
    ab_line = ABLine(start=master[0], end=master[-1], path_points=tuple(master))

    # AdaptiveCurve exige bordadura visivel: se UI veio com 0, forca 1 passada.
    spray_h = spray_headland
    if spray_h.pass_count <= 0:
        spray_h = HeadlandLayout(
            pass_count=1,
            width_m=spray_width,
            effective_spacing_m=spray_width,
            mode="follow_boundary",
        )

    spray_op = PrecisionOperation(
        operation_id="spraying",
        machine=sprayer,
        headland=spray_h,
        extension_m=spray_extension_m,
    )
    spraying_boundary = build_boundary_plan(
        field,
        spray_op,
        ab_line.start,
        ab_line.end,
        field_boundary=field,
        ab_path=ab_line.line_points(),
    )

    # Sempre as passadas da AdaptiveCurve limpa (path_points intactos).
    spraying_passes = list(imported.passes)
    if not spraying_passes:
        raise AdaptiveCurveImportError("Importacao AdaptiveCurve nao produziu passadas.")

    planting_passes: list[TrafficPass] = []
    planting_rows: list[PlantingRow] = []
    planting_boundary: BoundaryPlan | None = None
    if planter is not None:
        plant_h = plant_headland or HeadlandLayout()
        if plant_h.pass_count <= 0:
            plant_w = planter.operational_width_m
            plant_h = HeadlandLayout(
                pass_count=1,
                width_m=plant_w,
                effective_spacing_m=plant_w,
                mode="follow_boundary",
            )
        plant_op = PrecisionOperation(
            operation_id="planting",
            machine=planter,
            headland=plant_h,
            extension_m=plant_extension_m,
        )
        planting_boundary = build_boundary_plan(
            field,
            plant_op,
            ab_line.start,
            ab_line.end,
            field_boundary=field,
            ab_path=ab_line.line_points(),
        )
        plant_inner = planting_boundary.inner_boundary or field
        # Plantio: novas linhas seguindo a curva mestra (espacamento da plantadeira).
        planting_passes = generate_traffic_passes(
            plant_inner,
            ab_line,
            plant_op,
            clip_boundary=field,
        )
        kin = plant_kinematics or kinematics_from_planter(planter)
        planting_rows = generate_rows_from_tractor_paths(
            planting_passes,
            planter,
            kin,
            work_area=plant_inner,
        )

    return AdaptiveCurvePlanResult(
        spraying_passes=spraying_passes,
        planting_passes=planting_passes,
        planting_rows=planting_rows,
        spraying_boundary=spraying_boundary,
        planting_boundary=planting_boundary,
        ab_line=ab_line,
        stripped_uturn_count=imported.stripped_uturn_count,
        removed_contour_count=imported.removed_contour_count,
        source_polyline_count=imported.source_polyline_count,
        master_path=tuple(master),
        labels=imported.labels,
    )


def split_serpentine_strip_uturns(
    points: list[Point] | tuple[Point, ...],
    field: MultiPolygon,
    *,
    headland_band_m: float = 40.0,
    min_turn_deg: float = 90.0,
) -> tuple[list[list[Point]], int]:
    """Corta U-turns espaciais: curva + perto do Boundary + liga faixas.

    Miolo (desvio antigo): curvatura longe da cabeceira → preservada.
    U suave (arco denso): viragem acumulada na janela ≥ ~135°.
    """
    pts = _clean_points(points)
    if len(pts) < 3:
        return ([pts] if len(pts) >= 2 else []), 0

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
    accum = _cumulative_turn_degrees(sampled, window_m=max(headland_band_m * 0.8, 20.0))

    is_uturn = [False] * len(sampled)
    for i in range(1, len(sampled) - 1):
        if not near_headland[i]:
            continue
        sharp = abs(turn_deg[i]) >= min_turn_deg
        smooth_u = abs(accum[i]) >= max(135.0, min_turn_deg)
        if sharp or smooth_u:
            is_uturn[i] = True

    expanded = list(is_uturn)
    for i in range(1, len(sampled) - 1):
        if not is_uturn[i]:
            continue
        for j in range(max(1, i - 12), min(len(sampled) - 1, i + 13)):
            if not near_headland[j]:
                continue
            if abs(turn_deg[j]) >= min_turn_deg * 0.35 or abs(accum[j]) >= 90.0:
                expanded[j] = True

    for i in range(1, len(expanded) - 1):
        if expanded[i - 1] and expanded[i + 1]:
            expanded[i] = True

    parts: list[list[Point]] = []
    current: list[Point] = []
    stripped_runs = 0
    in_uturn = False
    for i, point in enumerate(sampled):
        if expanded[i]:
            if len(current) >= 2:
                parts.append(current)
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
    """Menor distancia ponto→polilinha (arestas). Usado pelo application_obstacle_engine."""
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


def _default_headland_band_m(field: MultiPolygon, width_m: float) -> float:
    """Faixa de cabeceira ~1.25–2.5 larguras (U reais ficam perto do Boundary).

    Nao pode crescer demais: banda larga demais classifica miolo como cabeceira
    e a serpentina AdaptiveCurve e descartada como 'contorno'.
    """
    xs: list[float] = []
    ys: list[float] = []
    for outer, _holes in field:
        for x, y in outer:
            xs.append(float(x))
            ys.append(float(y))
    if not xs:
        return max(width_m * 1.25, 30.0)
    short = min(max(xs) - min(xs), max(ys) - min(ys))
    # No maximo ~15% do lado curto do talhao, e nunca acima de 2.5*barra.
    return max(width_m * 1.25, 30.0, min(short * 0.15, width_m * 2.5))


def _is_uturn_connector_feature(
    points: list[Point],
    field: MultiPolygon,
    *,
    headland_band_m: float,
    spacing_m: float,
) -> bool:
    """Feicao curta so de cabeceira (conector U entre passadas ja separadas)."""
    if len(points) < 2:
        return False
    length = polyline_length(points)
    if length <= 1e-6:
        return True
    if length > max(spacing_m * 3.5, headland_band_m * 2.5):
        return False
    step = max(1, len(points) // 20)
    sample = points[::step]
    near = sum(
        1 for p in sample if _distance_to_field_exterior(p, field) <= headland_band_m
    )
    ratio = near / max(1, len(sample))
    if ratio < 0.65:
        return False
    turns = _vertex_turn_degrees(points)
    total_abs = sum(abs(t) for t in turns)
    return total_abs >= 60.0 or ratio >= 0.85


def _looks_like_unsplit_serpentine(points: list[Point], *, spacing_m: float) -> bool:
    """Heuristica: polilinha longa demais / com varrimento lateral de varias faixas."""
    length = polyline_length(points)
    if length < spacing_m * 8.0 or len(points) < 12:
        return False
    try:
        direction = normalize(sub(points[-1], points[0]))
    except ValueError:
        return True
    left = (-direction[1], direction[0])
    step = max(1, len(points) // 40)
    offsets = [p[0] * left[0] + p[1] * left[1] for p in points[::step]]
    if not offsets:
        return False
    return (max(offsets) - min(offsets)) > spacing_m * 1.2


def split_by_headland_heading_reversals(
    points: list[Point] | tuple[Point, ...],
    field: MultiPolygon,
    *,
    headland_band_m: float,
    spacing_m: float,
) -> tuple[list[list[Point]], int]:
    """Fallback: corta onde o rumo inverte ~180° perto da cabeceira."""
    pts = _clean_points(points)
    if len(pts) < 8:
        return [pts], 0

    sampled = segment_samples(pts, densify_m=max(3.0, polyline_length(pts) / 500.0))
    sampled = decimate_polyline(sampled, min_step_m=2.0, max_points=1000)
    if len(sampled) < 8:
        return [pts], 0

    headings = [0.0] * len(sampled)
    for i in range(1, len(sampled)):
        dx = sampled[i][0] - sampled[i - 1][0]
        dy = sampled[i][1] - sampled[i - 1][1]
        headings[i] = degrees(atan2(dy, dx)) % 360.0
    headings[0] = headings[1]

    near = [
        _distance_to_field_exterior(p, field) <= headland_band_m
        or (not point_in_multipolygon(p, field, check_boundary=True))
        for p in sampled
    ]

    cut = [False] * len(sampled)
    window = max(4, int(max(8.0, spacing_m * 0.35) / 2.0))
    for i in range(window, len(sampled) - window):
        if not near[i]:
            continue
        h0 = headings[i - window]
        h1 = headings[i + window]
        delta = abs((h1 - h0 + 180.0) % 360.0 - 180.0)
        if delta >= 120.0:
            for j in range(i - window, i + window + 1):
                if 0 <= j < len(cut) and near[j]:
                    cut[j] = True

    for i in range(1, len(cut) - 1):
        if cut[i - 1] and cut[i + 1]:
            cut[i] = True

    parts: list[list[Point]] = []
    current: list[Point] = []
    runs = 0
    in_cut = False
    for i, point in enumerate(sampled):
        if cut[i]:
            if len(current) >= 2:
                parts.append(current)
            current = []
            if not in_cut:
                runs += 1
                in_cut = True
            continue
        in_cut = False
        if not current or distance(current[-1], point) > 1e-9:
            current.append(point)
    if len(current) >= 2:
        parts.append(current)

    min_len = max(headland_band_m * 0.4, spacing_m * 0.5)
    usable = [p for p in parts if polyline_length(p) >= min_len]
    if len(usable) <= 1:
        return [pts], 0
    return usable, runs


def _is_closed_headland_contour(
    points: list[Point],
    field: MultiPolygon,
    *,
    headland_band_m: float,
    spacing_m: float | None = None,
) -> bool:
    """Contorno de cabeceira da AdaptiveCurve: anel quase fechado perto do Boundary.

    Passadas / serpentinas (mesmo com pontas na mesma cabeceira) NAO sao contorno.
    Anel real: corda inicio-fim pequena (< ~15 m), quase toda a linha na faixa.
    """
    if len(points) < 4:
        return False
    length = polyline_length(points)
    if length < headland_band_m * 4.0:
        return False
    spacing = float(spacing_m) if spacing_m and spacing_m > 0 else headland_band_m
    # Serpentina de miolo (varredura lateral de varias faixas) nunca e anel.
    if _looks_like_unsplit_serpentine(points, spacing_m=spacing):
        return False
    chord = distance(points[0], points[-1])
    # Corda frouxa (0.75*banda) classificava serpentina A→…→A' como anel.
    nearly_closed = chord <= max(12.0, min(headland_band_m * 0.2, 20.0))
    if not nearly_closed:
        return False

    step = max(1, len(points) // 50)
    sample = points[::step]
    near = sum(
        1 for p in sample if _distance_to_field_exterior(p, field) <= headland_band_m
    )
    ratio = near / max(1, len(sample))
    if ratio < 0.75:
        return False

    turns = _vertex_turn_degrees(points)
    total_abs = sum(abs(t) for t in turns)
    return nearly_closed and (total_abs >= 200.0 or length >= headland_band_m * 8.0)


def _clean_points(points: list[Point] | tuple[Point, ...]) -> list[Point]:
    out: list[Point] = []
    for p in points:
        if not out or distance(out[-1], p) > 1e-9:
            out.append((float(p[0]), float(p[1])))
    return out


def _vertex_turn_degrees(points: list[Point]) -> list[float]:
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
        turns[i] = degrees(atan2(cross, d))
    return turns


def _cumulative_turn_degrees(points: list[Point], *, window_m: float) -> list[float]:
    n = len(points)
    local = _vertex_turn_degrees(points)
    cum = [0.0] * n
    for i in range(1, n):
        cum[i] = cum[i - 1] + distance(points[i - 1], points[i])
    out = [0.0] * n
    half = max(window_m * 0.5, 8.0)
    left = 0
    right = 0
    for i in range(n):
        while left < i and cum[i] - cum[left] > half:
            left += 1
        while right < n - 1 and cum[right] - cum[i] < half:
            right += 1
        total = 0.0
        for j in range(left + 1, right):
            total += local[j]
        out[i] = total
    return out


def _distance_to_field_exterior(point: Point, field: MultiPolygon) -> float:
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
    if not parts:
        return []
    dirs: list[Point] = []
    for pts in parts:
        if len(pts) < 2:
            continue
        try:
            d = normalize(sub(pts[-1], pts[0]))
        except ValueError:
            continue
        # Serpentina: passadas de volta invertidas — alinha todas ao 1º sentido.
        if dirs and (d[0] * dirs[0][0] + d[1] * dirs[0][1]) < 0.0:
            d = (-d[0], -d[1])
        dirs.append(d)
    if not dirs:
        return [(i, p) for i, p in enumerate(parts)]
    mean_vec = (
        sum(d[0] for d in dirs) / len(dirs),
        sum(d[1] for d in dirs) / len(dirs),
    )
    try:
        mean_dir = normalize(mean_vec)
    except ValueError:
        mean_dir = dirs[0]
    left = (-mean_dir[1], mean_dir[0])
    scored: list[tuple[float, list[Point]]] = []
    for pts in parts:
        mid = pts[len(pts) // 2]
        scored.append((mid[0] * left[0] + mid[1] * left[1], pts))
    scored.sort(key=lambda item: item[0])
    offsets = [s[0] for s in scored]
    median = offsets[len(offsets) // 2]
    zero_idx = min(range(len(scored)), key=lambda i: abs(scored[i][0] - median))
    return [(i - zero_idx, scored[i][1]) for i in range(len(scored))]
