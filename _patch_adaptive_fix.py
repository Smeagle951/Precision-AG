# -*- coding: utf-8 -*-
"""Patch adaptive_curve_import_engine: never regenerate spray from A-B; stronger U-cut."""
from pathlib import Path

path = Path(r"C:\Users\fortu\Desktop\PYTHON\plugin\fortsmart_precision\core\adaptive_curve_import_engine.py")
text = path.read_text(encoding="utf-8")

# 1) Replace headland band default inside import_adaptive_curve_passes
old_band = "    band = headland_band_m if headland_band_m is not None else max(width_m * 1.25, 30.0)"
new_band = "    band = headland_band_m if headland_band_m is not None else _default_headland_band_m(field, width_m)"
if old_band not in text:
    raise SystemExit("band default not found")
text = text.replace(old_band, new_band, 1)

# 2) Insert connector + serpentine fallback after contour skip, before split call block
old_loop = '''        if _is_closed_headland_contour(pts, field, headland_band_m=band):
            removed_contour += 1
            continue
        parts, n_cut = split_serpentine_strip_uturns(
            pts,
            field,
            headland_band_m=band,
            min_turn_deg=min_turn_deg,
        )
        stripped += n_cut
        for part in parts:
            if len(part) < 2:
                continue
            if _is_closed_headland_contour(part, field, headland_band_m=band):
                removed_contour += 1
                continue
            cleaned.append(part)
'''

new_loop = '''        if _is_uturn_connector_feature(
            pts, field, headland_band_m=band, spacing_m=pass_spacing_m
        ):
            stripped += 1
            continue
        if _is_closed_headland_contour(pts, field, headland_band_m=band):
            removed_contour += 1
            continue
        parts, n_cut = split_serpentine_strip_uturns(
            pts,
            field,
            headland_band_m=band,
            min_turn_deg=min_turn_deg,
        )
        stripped += n_cut
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
            if _is_uturn_connector_feature(
                part, field, headland_band_m=band, spacing_m=pass_spacing_m
            ):
                stripped += 1
                continue
            if _is_closed_headland_contour(part, field, headland_band_m=band):
                removed_contour += 1
                continue
            cleaned.append(part)
'''
if old_loop not in text:
    raise SystemExit("import loop block not found")
text = text.replace(old_loop, new_loop, 1)

# 3) Replace entire build_plan_from_adaptive_curve
start = text.find("def build_plan_from_adaptive_curve(")
end = text.find("def split_serpentine_strip_uturns(")
if start < 0 or end < 0:
    raise SystemExit("build_plan markers not found")

new_build = '''def build_plan_from_adaptive_curve(
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
    """Passadas limpas da AdaptiveCurve + plantio/bordadura.

    Pulverizacao = geometria importada (apos corte de U). NUNCA regenera spray por A-B.
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


'''

helpers = '''
def _default_headland_band_m(field: MultiPolygon, width_m: float) -> float:
    """Faixa de cabeceira proporcional ao talhao (U reais costumam ficar ate ~2 larguras)."""
    xs: list[float] = []
    ys: list[float] = []
    for outer, _holes in field:
        for x, y in outer:
            xs.append(float(x))
            ys.append(float(y))
    if not xs:
        return max(width_m * 1.5, 40.0)
    diag = ((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2) ** 0.5
    return max(width_m * 1.5, 40.0, min(diag * 0.12, width_m * 4.0))


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
    # Conector tipico: curto frente ao espacamento / campo.
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
    """Heuristica: polilinha longa demais para uma unica passada."""
    length = polyline_length(points)
    if length < spacing_m * 8.0:
        return False
    if len(points) < 12:
        return False
    # Deslocamento lateral grande entre segmentos = varias faixas.
    mid = points[len(points) // 2]
    try:
        direction = normalize(sub(points[-1], points[0]))
    except ValueError:
        return True
    left = (-direction[1], direction[0])
    offsets = [p[0] * left[0] + p[1] * left[1] for p in points[:: max(1, len(points) // 40)]]
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

    headings: list[float] = [0.0] * len(sampled)
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
                if near[j]:
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


'''

# Insert helpers before _default or before _is_closed if helpers not present
if "_default_headland_band_m" not in text:
    # place before _is_closed_headland_contour
    idx = text.find("def _is_closed_headland_contour(")
    if idx < 0:
        idx = text.find("def _clean_points(")
    if idx < 0:
        raise SystemExit("helper insert point not found")
    text = text[:idx] + helpers + text[idx:]

text = text[:start] + new_build + text[end:]
path.write_text(text, encoding="utf-8")
print("patched ok", path.stat().st_size)
