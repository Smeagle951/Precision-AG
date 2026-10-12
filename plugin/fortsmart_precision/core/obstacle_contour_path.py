# -*- coding: utf-8 -*-
"""Contorno de obstaculos pelo anel do buffer (geometria real).

Pipeline (CRS metrico):
    buffer(obstaculo_real, dist_seguranca) -> entrada/saida na borda
    -> substring do anel (arco mais curto / lado preferido)
    -> reta + arco + reta
    -> validar Rcurv >= Rmin (aumenta buffer se preciso)
    -> validar envelope do IMPLEMENTO (hitch)

Nunca usa bounding box nem deslocamento perpendicular fixo.
A linha gerada e a trajetoria do TRATOR (guiagem).
"""

from __future__ import annotations

from math import acos, atan2, cos, pi, sin, tan

from .line_geometry import (
    Point,
    Segment,
    add,
    circle_arc_polyline,
    decimate_polyline,
    distance,
    expand_polygon,
    line_circle_intersections,
    mul,
    normalize,
    perpendicular_left,
    point_at_segment_t,
    point_in_multipolygon,
    ring_without_duplicate_close,
    segment_samples,
    sub,
)
from .obstacle_buffer_engine import ObstacleSafetyEnvelope, envelope_hits_segment

_AVOID_DENSIFY_M = 1.25
_AVOID_MAX_POINTS = 220
_CIRCLE_SEGMENTS = 96
_POLY_RING_STEP_M = 0.85
_MIN_TURN_M = 1.5
_BEZIER_SAMPLES = 48
# Folga nominal ja inclui W/2: extras modestos so para pontas na curva/hitch.
_IMPLEMENT_CLEARANCE_EXTRAS = (0.0, 0.5, 1.0, 2.0, 3.0, 5.0)


def polyline_envelope_hit_range(
    points: tuple[Point, ...] | list[Point],
    envelope: ObstacleSafetyEnvelope,
    *,
    half_width_m: float = 0.0,
) -> tuple[int, int, Segment] | None:
    """Primeiro/ultimo indice onde a trajetoria do CENTRO entra no envelope.

    O envelope ja embute a meia largura do implemento
    (`application_radius_m = raio_obstaculo + meia_largura + margem`), logo
    testar o eixo contra o envelope JA protege as pontas da barra. Deslocar a
    linha mais meia largura contaria a protecao duas vezes e geraria desvio
    onde a ponta ja passava com folga.

    `half_width_m` fica disponivel para envelopes crus (sem meia largura),
    como as regioes proibidas do plantio.
    """
    pts = list(points)
    if len(pts) < 2:
        return None
    use_swath = half_width_m > 0.0
    if use_swath:
        from .obstacle_buffer_engine import envelope_swath_hits_segment

    first_in: int | None = None
    last_in: int | None = None
    for index in range(len(pts) - 1):
        seg = Segment(pts[index], pts[index + 1])
        if use_swath:
            hit = envelope_swath_hits_segment(envelope, seg, half_width_m)
        else:
            hit = envelope_hits_segment(envelope, seg.start, seg.end)
        if not hit:
            continue
        if first_in is None:
            first_in = index
        last_in = index + 1
    if first_in is None or last_in is None:
        return None
    return first_in, last_in, Segment(pts[first_in], pts[last_in])


def polyline_forbidden_hit_range(
    points: tuple[Point, ...] | list[Point],
    region,
    *,
    half_width_m: float = 0.0,
) -> tuple[int, int, Segment] | None:
    from .obstacle_buffer_engine import forbidden_swath_hits_segment

    pts = list(points)
    if len(pts) < 2:
        return None
    first_in: int | None = None
    last_in: int | None = None
    for index in range(len(pts) - 1):
        seg = Segment(pts[index], pts[index + 1])
        if not forbidden_swath_hits_segment(region, seg, half_width_m):
            continue
        if first_in is None:
            first_in = index
        last_in = index + 1
    if first_in is None or last_in is None:
        return None
    return first_in, last_in, Segment(pts[first_in], pts[last_in])


def detour_side_toward_pass(
    segment: Segment,
    obstacle_point: Point,
    path_points: tuple[Point, ...] | list[Point] | None = None,
    *,
    at_index: int | None = None,
) -> Point:
    """Lado do desvio: cada passada contorna pelo seu lado do obstaculo."""
    from .line_geometry import point_at_segment_t, segment_travel_direction

    travel = segment_travel_direction(segment, path_points, at_index=at_index)
    left = perpendicular_left(travel)
    if distance(segment.start, segment.end) > 1e-6:
        mid = point_at_segment_t(segment, 0.5)
    elif path_points and len(path_points) >= 2:
        idx = at_index if at_index is not None else len(path_points) // 2
        idx = max(0, min(idx, len(path_points) - 1))
        mid = path_points[idx]
    else:
        mid = segment.start
    to_pass = sub(mid, obstacle_point)
    lateral = to_pass[0] * left[0] + to_pass[1] * left[1]
    if abs(lateral) < 1e-9:
        return left
    return left if lateral > 0 else mul(left, -1.0)


def polyline_max_lateral_offset_m(
    points: tuple[Point, ...] | list[Point],
    segment: Segment,
) -> float:
    """Maior afastamento perpendicular do caminho em relacao a linha-guia.

    Usado para garantir que o desvio nao invada a passada vizinha: o limite
    operacional e meio espacamento entre passadas.
    """
    pts = list(points)
    if len(pts) < 2:
        return 0.0
    direction = sub(segment.end, segment.start)
    length = (direction[0] ** 2 + direction[1] ** 2) ** 0.5
    if length <= 1e-9:
        return 0.0
    ux, uy = direction[0] / length, direction[1] / length
    worst = 0.0
    for px, py in pts:
        dx, dy = px - segment.start[0], py - segment.start[1]
        lateral = abs(dx * (-uy) + dy * ux)
        if lateral > worst:
            worst = lateral
    return worst


def stitch_avoidance_into_polyline(
    points: tuple[Point, ...] | list[Point],
    index_in: int,
    index_out: int,
    avoidance_points: list[Point],
) -> tuple[Point, ...]:
    pts = list(points)
    if not avoidance_points:
        return tuple(pts)
    prefix = pts[: index_in + 1]
    suffix = pts[index_out:] if index_out < len(pts) else []
    return tuple(_dedupe_points(prefix + list(avoidance_points) + suffix))


def smooth_avoidance_trajectory(
    points: list[Point] | tuple[Point, ...],
    *,
    densify_m: float = _AVOID_DENSIFY_M,
    chaikin_iterations: int = 0,
    max_points: int = _AVOID_MAX_POINTS,
    preserve_circular: bool = False,
) -> list[Point]:
    """Densifica/decima. Chaikin so se chaikin_iterations > 0."""
    pts = _dedupe_points(list(points))
    if len(pts) < 2:
        return pts
    start, end = pts[0], pts[-1]
    step = max(0.55, densify_m * (0.75 if preserve_circular else 1.0))
    work = segment_samples(pts, densify_m=step)
    if chaikin_iterations > 0 and len(work) >= 3:
        for _ in range(min(4, int(chaikin_iterations))):
            if len(work) < 3:
                break
            work = _chaikin_once(work)
    work = list(decimate_polyline(work, min_step_m=step * 0.85, max_points=max_points))
    if not work:
        return pts
    work[0], work[-1] = start, end
    return _dedupe_points(work)


def circular_bypass_path(
    segment: Segment,
    center: Point,
    radius_m: float,
    *,
    turn_radius_m: float | None = None,
    hitch_distance_m: float = 0.0,
    implement_offset_m: float = 0.0,
    segments: int = _CIRCLE_SEGMENTS,
    obstacle_reference: Point | None = None,
    path_points: tuple[Point, ...] | list[Point] | None = None,
    at_index: int | None = None,
    quick: bool = False,
) -> list[Point] | None:
    """
    Desvio circular pelo anel do buffer (geometria real).

    Miolo = substring do anel; entrada/saida com fillet tangencial (Rmin)
    para nao nascer quina de 90° na corda. Com hitch > 0 amplia o raio
    (off-tracking) e valida a trajetoria do IMPLEMENTO.
    """
    from .obstacle_ring_bypass import desviar_circulo_validado

    if radius_m <= 0.05:
        return None

    rmin = max(float(turn_radius_m or 0.0), _MIN_TURN_M)
    hitch = max(0.0, float(hitch_distance_m or 0.0))
    lat_off = float(implement_offset_m or 0.0)
    from .line_geometry import ensure_segment_span

    try:
        segment = ensure_segment_span(
            segment,
            path_points,
            at_index=at_index,
            half_span_m=max(12.0, radius_m * 2.0),
            min_span_m=1.0,
        )
    except ValueError:
        if distance(segment.start, segment.end) < 1.0:
            return None
    ref = obstacle_reference if obstacle_reference is not None else center
    lado = detour_side_toward_pass(segment, ref, path_points, at_index=at_index)

    path = desviar_circulo_validado(
        segment,
        center,
        radius_m,
        raio_giro_minimo_m=rmin,
        distancia_pino_eixo_m=hitch,
        segmentos_por_quadrante=max(16, int(segments) // 4),
        lado_preferido=lado,
    )
    if path is None or len(path) < 4:
        return None

    path = _fillet_line_to_ring_joins(
        segment,
        path,
        blend_m=max(rmin * 2.0, radius_m * 0.45, 5.0),
        path_points=path_points,
        at_index=at_index,
    )
    if path is None or len(path) < 4:
        return None
    # Curvatura local do fillet (amostragem discreta) pode subestimar o raio;
    # o anel ja foi validado em desviar_circulo_validado.
    return smooth_avoidance_trajectory(
        path,
        densify_m=0.75,
        chaikin_iterations=0,
        preserve_circular=True,
    )


def circular_orbit_360_path(
    segment: Segment,
    center: Point,
    radius_m: float,
    *,
    turn_radius_m: float | None = None,
    hitch_distance_m: float = 0.0,
    implement_offset_m: float = 0.0,
    segments: int = _CIRCLE_SEGMENTS,
    obstacle_reference: Point | None = None,
    path_points: tuple[Point, ...] | list[Point] | None = None,
    at_index: int | None = None,
    quick: bool = False,
) -> list[Point] | None:
    """Pulverizacao: entra, da volta 360° no anel e sai na passada sem quebra.

    `radius_m` ja e a folga do CENTRO (raio_obstaculo + W/2 + margem) — nao
    soma hitch/W de novo.
    """
    from .obstacle_ring_bypass import desviar_circulo_orbita_360

    del hitch_distance_m, implement_offset_m  # folga ja embute W/2; hitch validado fora
    if radius_m <= 0.05:
        return None

    from .line_geometry import ensure_segment_span

    try:
        segment = ensure_segment_span(
            segment,
            path_points,
            at_index=at_index,
            half_span_m=max(12.0, radius_m * 2.0),
            min_span_m=1.0,
        )
    except ValueError:
        if distance(segment.start, segment.end) < 1.0:
            return None
    ref = obstacle_reference if obstacle_reference is not None else center
    lado = detour_side_toward_pass(segment, ref, path_points, at_index=at_index)

    # Rmin nao amplia o anel: radius_m ja e a folga do centro (W/2 + margem).
    del turn_radius_m
    path = desviar_circulo_orbita_360(
        segment,
        center,
        radius_m,
        segmentos_por_quadrante=max(16, int(segments) // 4),
        lado_preferido=lado,
    )
    if path is None or len(path) < 5:
        return None
    # Sem fillet agressivo: a orbita ja e continua na polilinha do anel;
    # blend grande puxava pontos para dentro do raio (W/2).
    return smooth_avoidance_trajectory(
        path,
        densify_m=0.75 if not quick else 1.0,
        chaikin_iterations=0,
        preserve_circular=True,
    )


def contour_path_around_polygon(
    segment: Segment,
    polygon_geometry,
    *,
    clearance_m: float,
    densify_m: float = _AVOID_DENSIFY_M,
    turn_radius_m: float | None = None,
    hitch_distance_m: float = 0.0,
    implement_offset_m: float = 0.0,
    obstacle_reference: Point | None = None,
    path_points: tuple[Point, ...] | list[Point] | None = None,
    at_index: int | None = None,
) -> list[Point] | None:
    """Poligono: buffer na geometria real + substring do anel; valida Rmin/hitch."""
    from .obstacle_ring_bypass import desviar_anel_validado, desviar_pelo_anel

    outer = list(polygon_geometry[0]) if polygon_geometry else []
    if len(outer) < 4:
        return None

    ref = obstacle_reference
    if ref is None:
        ref = (
            sum(p[0] for p in outer) / len(outer),
            sum(p[1] for p in outer) / len(outer),
        )
    rmin = max(float(turn_radius_m or 0.0), _MIN_TURN_M)
    hitch = max(0.0, float(hitch_distance_m or 0.0))
    lat_off = float(implement_offset_m or 0.0)
    from .line_geometry import ensure_segment_span

    try:
        segment = ensure_segment_span(
            segment,
            path_points,
            at_index=at_index,
            half_span_m=max(12.0, clearance_m * 4.0),
            min_span_m=1.0,
        )
    except ValueError:
        pass
    lado = detour_side_toward_pass(segment, ref, path_points, at_index=at_index)
    clearance = max(0.05, float(clearance_m))

    path = desviar_anel_validado(
        segment,
        polygon_geometry,
        largura_implemento_m=0.0,
        raio_giro_minimo_m=rmin,
        distancia_pino_eixo_m=hitch,
        margem_extra_m=0.0,
        distancia_base_m=clearance,
        segmentos_por_quadrante=24,
        cantos="round",
        lado_preferido=lado,
    )
    if path is None:
        path = desviar_pelo_anel(
            segment,
            polygon_geometry,
            clearance,
            segmentos_por_quadrante=24,
            cantos="round",
            lado_preferido=lado,
        )
    if path is None or len(path) < 4:
        return None

    path = _fillet_line_to_ring_joins(
        segment,
        path,
        blend_m=max(rmin * 1.1, 3.0),
        path_points=path_points,
        at_index=at_index,
    )
    if path is None or len(path) < 4:
        return None
    step = max(0.65, min(densify_m, _AVOID_DENSIFY_M))
    return smooth_avoidance_trajectory(path, densify_m=step, chaikin_iterations=0)


def plan_circular_avoidance_for_implement(
    segment: Segment,
    center: Point,
    clearance_radius_m: float,
    kinematics: "PlantingKinematics",
    *,
    segments: int = 96,
    quick: bool = False,
    path_points: tuple[Point, ...] | list[Point] | None = None,
    at_index: int | None = None,
) -> list[Point] | None:
    """
    Planeja desvio do TRATOR garantindo que a PLANTADEIRA nao colida.

    Fluxo:
        anel do buffer (+ hitch off-tracking) -> trajetoria trator
            -> pose hitch/implemento
            -> se colide: amplia raio e repete

    `quick=True` pula validacao densa do implemento (desvios intermediarios).
    """
    from .planting_kinematics_engine import implement_clears_circle

    rmin = kinematics.minimum_turn_radius_m
    hitch = kinematics.hitch_distance_m
    lat = kinematics.implement_center_offset_m
    from .line_geometry import ensure_segment_span

    try:
        segment = ensure_segment_span(
            segment,
            path_points,
            at_index=at_index,
            half_span_m=max(12.0, clearance_radius_m * 2.0),
            min_span_m=1.0,
        )
    except ValueError:
        if distance(segment.start, segment.end) < 1.0:
            return None

    arc_segments = min(segments, 48) if quick else segments
    extras = (0.0, 2.0) if quick else _IMPLEMENT_CLEARANCE_EXTRAS
    for extra in extras:
        path = circular_bypass_path(
            segment,
            center,
            clearance_radius_m + extra,
            turn_radius_m=rmin,
            hitch_distance_m=hitch,
            implement_offset_m=lat,
            segments=arc_segments,
            obstacle_reference=center,
            path_points=path_points,
            at_index=at_index,
        )
        if path is None or len(path) < 4:
            continue
        if quick:
            return path
        if not implement_clears_circle(
            path,
            kinematics,
            center,
            clearance_radius_m=clearance_radius_m,
        ):
            continue
        return path
    return None


def plan_polygon_avoidance_for_implement(
    segment: Segment,
    polygon_geometry,
    *,
    clearance_m: float,
    kinematics: "PlantingKinematics",
    densify_m: float = _AVOID_DENSIFY_M,
    obstacle_reference: Point | None = None,
    path_points: tuple[Point, ...] | list[Point] | None = None,
    at_index: int | None = None,
) -> list[Point] | None:
    """Desvio poligonal: trator a `clearance_m` da feicao (inclui W/2).

    `clearance_m` e a distancia do CENTRO do trator a geometria do obstaculo
    (raio/margem + meia largura da plantadeira). As pontas sao validadas contra
    o nucleo fisico (clearance - W/2). Antes, com hitch=0, a validacao era
    pulada e o motor aceitava contorno so com a margem (~1 m).
    """
    from .planting_kinematics_engine import implement_clears_polygon

    rmin = kinematics.minimum_turn_radius_m
    hitch = kinematics.hitch_distance_m
    lat = kinematics.implement_center_offset_m
    half_w = max(0.0, float(kinematics.half_operational_width_m))
    tractor_clearance = max(float(clearance_m), 0.05)
    # Nucleo sem meia-barra: tolerancia pequena evita re-empilhar W/2 nos extras.
    core_clearance = max(0.05, tractor_clearance - half_w - 0.25) if half_w > 1e-6 else tractor_clearance
    core_envelope = expand_polygon(polygon_geometry, core_clearance)

    # clearance_m ja embute W/2 — nunca somar meia barra de novo (evita ~20 m em 20 m).
    for extra in _IMPLEMENT_CLEARANCE_EXTRAS:
        path = contour_path_around_polygon(
            segment,
            polygon_geometry,
            clearance_m=tractor_clearance + extra,
            densify_m=densify_m,
            turn_radius_m=rmin,
            hitch_distance_m=hitch,
            implement_offset_m=lat,
            obstacle_reference=obstacle_reference,
            path_points=path_points,
            at_index=at_index,
        )
        if path is None or len(path) < 4:
            continue
        # Sempre valida pontas (hitch=0 tambem: a barra ainda tem largura).
        if not implement_clears_polygon(path, kinematics, core_envelope):
            continue
        return path
    return contour_path_around_polygon(
        segment,
        polygon_geometry,
        clearance_m=tractor_clearance,
        densify_m=densify_m,
        turn_radius_m=rmin,
        hitch_distance_m=hitch,
        implement_offset_m=lat,
        obstacle_reference=obstacle_reference,
        path_points=path_points,
        at_index=at_index,
    )


def hitch_anticipation_m(hitch_distance_m: float, turn_radius_m: float) -> float:
    """Metros ao longo da linha para iniciar o desvio antes (atraso do implemento)."""
    return _hitch_anticipation_m(hitch_distance_m, turn_radius_m)


def _fillet_line_to_ring_joins(
    segment: Segment,
    path: list[Point],
    *,
    blend_m: float,
    path_points: tuple[Point, ...] | list[Point] | None = None,
    at_index: int | None = None,
) -> list[Point] | None:
    """
    Suaviza a quina reta->anel e anel->reta com Bezier cubica tangente.

    O miolo do path (contorno real do buffer) e preservado; so as juncoes
    na corda sao substituidas para ficar dirigivel (sem ~90°).
    """
    pts = _dedupe_points(list(path))
    if len(pts) < 5:
        return pts

    from .line_geometry import segment_travel_direction

    travel = segment_travel_direction(segment, path_points, at_index=at_index)
    # Indices onde a polilinha sai / volta a faixa da reta guia.
    i_leave = None
    i_rejoin = None
    for i, p in enumerate(pts):
        if _point_line_distance(p, segment) > 0.35:
            i_leave = i
            break
    for i in range(len(pts) - 1, -1, -1):
        if _point_line_distance(pts[i], segment) > 0.35:
            i_rejoin = i
            break
    if i_leave is None or i_rejoin is None or i_rejoin - i_leave < 3:
        return pts

    blend = max(2.0, float(blend_m))
    # Ponto na reta antes da entrada.
    t_leave = max(0.0, _project_t(pts[i_leave], segment))
    lead_t = blend / max(distance(segment.start, segment.end), 1e-6)
    t_a = max(0.0, t_leave - lead_t)
    p_a = point_at_segment_t(segment, t_a)

    # Avanca ao longo do arco ~blend metros apos a saida da reta.
    j_in = i_leave
    acc = 0.0
    while j_in < i_rejoin - 1 and acc < blend:
        acc += distance(pts[j_in], pts[j_in + 1])
        j_in += 1
    p_b = pts[j_in]
    try:
        tan_b = normalize(sub(pts[min(j_in + 1, len(pts) - 1)], pts[max(j_in - 1, 0)]))
    except ValueError:
        tan_b = travel

    entry = _cubic_bezier_polyline(
        p_a,
        add(p_a, mul(travel, blend * 0.85)),
        add(p_b, mul(tan_b, -blend * 0.85)),
        p_b,
        samples=20,
    )

    # Saida simetrica.
    t_rejoin = min(1.0, _project_t(pts[i_rejoin], segment))
    t_d = min(1.0, t_rejoin + lead_t)
    p_d = point_at_segment_t(segment, t_d)
    j_out = i_rejoin
    acc = 0.0
    while j_out > j_in + 1 and acc < blend:
        acc += distance(pts[j_out], pts[j_out - 1])
        j_out -= 1
    p_c = pts[j_out]
    try:
        tan_c = normalize(sub(pts[min(j_out + 1, len(pts) - 1)], pts[max(j_out - 1, 0)]))
    except ValueError:
        tan_c = travel

    exit_bz = _cubic_bezier_polyline(
        p_c,
        add(p_c, mul(tan_c, blend * 0.85)),
        add(p_d, mul(travel, -blend * 0.85)),
        p_d,
        samples=20,
    )

    middle = pts[j_in : j_out + 1]
    out = _dedupe_points(
        [segment.start]
        + ([p_a] if distance(segment.start, p_a) > 1e-6 else [])
        + entry
        + middle
        + exit_bz
        + ([p_d] if distance(p_d, segment.end) > 1e-6 else [])
        + [segment.end]
    )
    return out if len(out) >= 4 else pts


def implement_path_from_tractor_path(
    tractor_path: list[Point] | tuple[Point, ...],
    hitch_distance_m: float,
    implement_offset_m: float = 0.0,
) -> list[Point]:
    """
    Trajetoria do centro do implemento a partir da guiagem do trator.

    implemento ≈ trator - hitch * heading + offset_lateral * esquerda
    (mesmo modelo do planting_kinematics_engine).
    """
    pts = list(tractor_path)
    hitch = max(0.0, float(hitch_distance_m or 0.0))
    lat = float(implement_offset_m or 0.0)
    if len(pts) < 2 or (hitch <= 1e-6 and abs(lat) <= 1e-6):
        return pts

    out: list[Point] = []
    for i, tractor in enumerate(pts):
        if i < len(pts) - 1:
            try:
                forward = normalize(sub(pts[i + 1], tractor))
            except ValueError:
                forward = normalize(sub(tractor, pts[i - 1])) if i > 0 else (1.0, 0.0)
        else:
            try:
                forward = normalize(sub(tractor, pts[i - 1]))
            except ValueError:
                forward = (1.0, 0.0)
        left = perpendicular_left(forward)
        impl = add(tractor, mul(forward, -hitch))
        if abs(lat) > 1e-9:
            impl = add(impl, mul(left, lat))
        out.append(impl)
    return _dedupe_points(out)


def _hitch_anticipation_m(hitch_m: float, turn_radius_m: float) -> float:
    """
    Antecipacao longitudinal do desvio.

    - hitch: implemento ainda esta hitch metros atras quando o trator inicia a curva
    - hitch^2/(2R): atraso lateral tipico em curva (corda vs arco)
    """
    hitch = max(0.0, float(hitch_m or 0.0))
    if hitch <= 1e-6:
        return 0.0
    rmin = max(float(turn_radius_m or 0.0), _MIN_TURN_M)
    lateral_lag = (hitch * hitch) / (2.0 * rmin)
    return hitch + lateral_lag


def _circle_key_points(
    segment: Segment,
    center: Point,
    radius_m: float,
    *,
    side: Point,
) -> tuple[Point, Point, Point, float, float] | None:
    ts = line_circle_intersections(segment, center, radius_m)
    if len(ts) < 2:
        if _point_line_distance(center, segment) > radius_m + 0.05:
            return None
        t_mid = _project_t(center, segment)
        t_s = max(0.0, t_mid - 0.12)
        t_e = min(1.0, t_mid + 0.12)
    else:
        t_s, t_e = ts[0], ts[1]

    p_s = point_at_segment_t(segment, t_s)
    p_e = point_at_segment_t(segment, t_e)
    p_v = add(center, mul(side, radius_m))
    mid = point_at_segment_t(segment, 0.5 * (t_s + t_e))
    to_v = sub(p_v, mid)
    if side[0] * to_v[0] + side[1] * to_v[1] < 0:
        p_v = add(center, mul(side, -radius_m))
    return p_s, p_e, p_v, t_s, t_e


def _dual_bezier_bypass(
    segment: Segment,
    travel: Point,
    p_v: Point,
    t_s: float,
    t_e: float,
    *,
    lead_m: float,
    handle_m: float,
    samples: int,
) -> list[Point] | None:
    """Duas Bezier cubicas com tangencia a linha global (Eq. 16 Chen 2023)."""
    length = distance(segment.start, segment.end)
    if length < 1e-6:
        return None
    lead_t = min(0.4, lead_m / length)
    t10 = max(0.0, t_s - lead_t)
    t11 = max(t10, t_s - lead_t * 0.35)
    t23 = min(1.0, t_e + lead_t)
    t22 = min(t23, t_e + lead_t * 0.35)

    p10 = point_at_segment_t(segment, t10)
    p11 = point_at_segment_t(segment, t11)
    p12 = sub(p_v, mul(travel, handle_m))
    p13 = p_v
    p20 = p_v
    p21 = add(p_v, mul(travel, handle_m))
    p22 = point_at_segment_t(segment, t22)
    p23 = point_at_segment_t(segment, t23)

    curve1 = _cubic_bezier_polyline(p10, p11, p12, p13, samples=samples)
    curve2 = _cubic_bezier_polyline(p20, p21, p22, p23, samples=samples)

    before = [segment.start]
    if t10 > 1e-6 and distance(segment.start, p10) > 0.05:
        before.append(p10)
    after: list[Point] = []
    if t23 < 1.0 - 1e-6 and distance(p23, segment.end) > 0.05:
        after.append(p23)
    after.append(segment.end)

    return _dedupe_points(before + curve1 + curve2[1:] + after)


def _cubic_bezier_polyline(
    p0: Point, p1: Point, p2: Point, p3: Point, *, samples: int = 48,
) -> list[Point]:
    n = max(8, samples)
    return [_cubic_bezier_point(p0, p1, p2, p3, i / n) for i in range(n + 1)]


def _cubic_bezier_point(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    u = 1.0 - t
    u2, t2 = u * u, t * t
    u3, t3 = u2 * u, t2 * t
    return (
        u3 * p0[0] + 3.0 * u2 * t * p1[0] + 3.0 * u * t2 * p2[0] + t3 * p3[0],
        u3 * p0[1] + 3.0 * u2 * t * p1[1] + 3.0 * u * t2 * p2[1] + t3 * p3[1],
    )


def _max_curvature(path: list[Point]) -> float:
    if len(path) < 3:
        return 0.0
    k_max = 0.0
    for i in range(1, len(path) - 1):
        a, b, c = path[i - 1], path[i], path[i + 1]
        ab, bc, ca = distance(a, b), distance(b, c), distance(c, a)
        if ab < 1e-6 or bc < 1e-6 or ab * bc * ca < 1e-9:
            continue
        area2 = abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
        k_max = max(k_max, area2 / (ab * bc * ca))
    return k_max


def _blend_perimeter_into_bezier(
    bezier_path: list[Point], perimeter: list[Point], p_v: Point,
) -> list[Point]:
    if len(bezier_path) < 6 or len(perimeter) < 3:
        return bezier_path
    i0, i1 = len(bezier_path) // 3, (2 * len(bezier_path)) // 3
    out = list(bezier_path)
    for i in range(i0, i1 + 1):
        pt = out[i]
        nearest = min(perimeter, key=lambda q: distance(q, pt))
        w = 0.55 if distance(pt, p_v) < distance(nearest, p_v) * 1.5 else 0.35
        out[i] = (pt[0] * (1.0 - w) + nearest[0] * w, pt[1] * (1.0 - w) + nearest[1] * w)
    return _dedupe_points(out)


def _enforce_circle_clearance(path: list[Point], center: Point, radius_m: float) -> list[Point]:
    safe = radius_m * 0.998
    out: list[Point] = []
    for pt in path:
        dx, dy = pt[0] - center[0], pt[1] - center[1]
        dist = (dx * dx + dy * dy) ** 0.5
        if 1e-9 < dist < safe:
            scale = safe / dist
            out.append((center[0] + dx * scale, center[1] + dy * scale))
        else:
            out.append(pt)
    return out


def _path_outside_circle(path: list[Point], center: Point, radius_m: float) -> bool:
    return all(distance(pt, center) >= radius_m - 0.05 for pt in path)


def _strip_points_inside_polygon(path: list[Point], polygon_geometry) -> list[Point]:
    out = [
        pt for pt in path
        if not point_in_multipolygon(pt, [polygon_geometry], check_boundary=False)
    ]
    return out if len(out) >= 2 else path


def _fillet_polygon_ring(ring: list[Point], fillet_r: float) -> list[Point]:
    if len(ring) < 3 or fillet_r <= 0.05:
        return ring
    n = len(ring)
    out: list[Point] = []
    for i in range(n):
        prev_pt, curr, next_pt = ring[(i - 1) % n], ring[i], ring[(i + 1) % n]
        try:
            v1 = normalize(sub(curr, prev_pt))
            v2 = normalize(sub(next_pt, curr))
        except ValueError:
            out.append(curr)
            continue
        dot = max(-1.0, min(1.0, v1[0] * v2[0] + v1[1] * v2[1]))
        turn = acos(dot)
        if turn < 0.25 or turn > pi - 0.25:
            out.append(curr)
            continue
        edge1, edge2 = distance(prev_pt, curr), distance(curr, next_pt)
        half = turn / 2.0
        trim = min(fillet_r / max(tan(half), 0.15), edge1 * 0.45, edge2 * 0.45)
        if trim < 0.15:
            out.append(curr)
            continue
        p1 = (curr[0] - v1[0] * trim, curr[1] - v1[1] * trim)
        p2 = (curr[0] + v2[0] * trim, curr[1] + v2[1] * trim)
        bis = normalize(add((-v1[1], v1[0]), (v2[1], -v2[0])))
        dist_center = fillet_r / max(sin(half), 0.15)
        arc_center = (curr[0] + bis[0] * dist_center, curr[1] + bis[1] * dist_center)
        ang1 = atan2(p1[1] - arc_center[1], p1[0] - arc_center[0])
        ang2 = atan2(p2[1] - arc_center[1], p2[0] - arc_center[0])
        sweep = ang2 - ang1
        while sweep <= -pi:
            sweep += 2.0 * pi
        while sweep > pi:
            sweep -= 2.0 * pi
        if abs(sweep) < 0.05:
            out.extend([p1, p2])
            continue
        n_seg = max(4, int(abs(sweep) * fillet_r * 1.5))
        corner = circle_arc_polyline(arc_center, fillet_r, ang1, sweep, segments=n_seg)
        if out and distance(out[-1], corner[0]) < 1e-6:
            out.extend(corner[1:])
        else:
            out.extend(corner)
    return _dedupe_points(out) if out else ring


def _walk_ring(ring: list[Point], start_i: int, end_i: int, step: int) -> list[Point]:
    path = [ring[start_i]]
    i, guard = start_i, 0
    while i != end_i and guard < len(ring) + 2:
        i = (i + step) % len(ring)
        path.append(ring[i])
        guard += 1
    return path


def _path_length(points: list[Point]) -> float:
    return sum(distance(a, b) for a, b in zip(points, points[1:]))


def _segment_polygon_crossings(segment: Segment, polygon_geometry) -> tuple[float, float]:
    samples = segment_samples([segment.start, segment.end], densify_m=0.75)
    if len(samples) < 2:
        return 0.25, 0.75
    n = len(samples) - 1
    flags = [point_in_multipolygon(pt, [polygon_geometry], check_boundary=True) for pt in samples]
    first_in = last_in = None
    for i, flag in enumerate(flags):
        if not flag:
            continue
        t = i / n if n else 0.0
        if first_in is None:
            first_in = t
        last_in = t
    if first_in is not None and last_in is not None and last_in - first_in > 1e-6:
        margin = min(0.04, 0.12 * (last_in - first_in))
        return max(0.0, first_in - margin), min(1.0, last_in + margin)
    return 0.2, 0.8


def _point_line_distance(point: Point, segment: Segment) -> float:
    from .line_geometry import cross

    dx = segment.end[0] - segment.start[0]
    dy = segment.end[1] - segment.start[1]
    length = (dx * dx + dy * dy) ** 0.5
    if length <= 1e-9:
        return distance(point, segment.start)
    return abs(cross(sub(point, segment.start), (dx, dy))) / length


def _project_t(point: Point, segment: Segment) -> float:
    dx = segment.end[0] - segment.start[0]
    dy = segment.end[1] - segment.start[1]
    length2 = dx * dx + dy * dy
    if length2 <= 1e-12:
        return 0.0
    t = ((point[0] - segment.start[0]) * dx + (point[1] - segment.start[1]) * dy) / length2
    return max(0.0, min(1.0, t))


def _chaikin_once(points: list[Point]) -> list[Point]:
    if len(points) < 3:
        return points
    result = [points[0]]
    for a, b in zip(points, points[1:]):
        q = (0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1])
        r = (0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1])
        result.extend([q, r])
    result.append(points[-1])
    return result


def _dedupe_points(points: list[Point]) -> list[Point]:
    if not points:
        return points
    out = [points[0]]
    for pt in points[1:]:
        if distance(out[-1], pt) > 1e-6:
            out.append(pt)
    return out
