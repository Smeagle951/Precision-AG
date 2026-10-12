# -*- coding: utf-8 -*-
"""Desvio pelo contorno REAL do buffer (buffer + anel + substring).

Metodo: nunca bounding box / deslocamento perpendicular fixo.
1. Buffer na geometria real do obstaculo (quad_segs alto, cantos round).
2. Entrada/saida = intersecoes linha x anel exterior.
3. Trecho do anel entre entrada e saida (arco mais curto).
4. Une reta + arco + reta.
5. Distancia de seguranca = meia-largura + off-tracking hitch^2/(2R) + margem.
6. Se curvatura < Rmin, aumenta o buffer ate ficar dirigivel.

Depende de shapely (ja disponivel no ambiente FortSmart).
"""

from __future__ import annotations

from math import inf

from shapely.geometry import LineString, Point as ShapelyPoint, Polygon as ShapelyPolygon
from shapely.ops import substring

from .line_geometry import Point, Polygon, Segment


def distancia_seguranca_ideal(
    largura_implemento_m: float,
    raio_giro_minimo_m: float,
    distancia_pino_eixo_m: float = 0.0,
    margem_extra_m: float = 0.5,
) -> float:
    """
    Folga do buffer a partir da maquina real:

    meia_largura + (hitch^2)/(2*Rmin) + margem
    """
    meia = max(0.0, float(largura_implemento_m)) * 0.5
    rmin = max(0.0, float(raio_giro_minimo_m))
    hitch = max(0.0, float(distancia_pino_eixo_m))
    corte = (hitch * hitch) / (2.0 * rmin) if rmin > 1e-6 else 0.0
    return meia + corte + max(0.0, float(margem_extra_m))


def raio_curvatura_minimo_m(points: list[Point] | tuple[Point, ...]) -> float:
    """Menor raio de curvatura estimado por trincas de 3 pontos consecutivos."""
    coords = list(points)
    if len(coords) < 3:
        return inf
    r_min = inf
    for i in range(len(coords) - 2):
        r = _raio_circulo_3_pontos(coords[i], coords[i + 1], coords[i + 2])
        if r is not None and r < r_min:
            r_min = r
    return r_min


def desviar_pelo_anel(
    segment: Segment,
    obstaculo_polygon: Polygon,
    distancia_seguranca_m: float,
    *,
    segmentos_por_quadrante: int = 24,
    cantos: str = "round",
    lado_preferido: Point | None = None,
) -> list[Point] | None:
    """
    Contorno pelo anel do buffer (geometria real).

    Retorna None se nao houver cruzamento util.
    """
    linha = LineString([segment.start, segment.end])
    obst = _to_shapely_polygon(obstaculo_polygon)
    if obst is None or obst.is_empty or linha.length < 1e-6:
        return None

    join_style = {"round": 1, "sharp": 2, "flat": 3}.get(cantos, 1)
    dist = float(distancia_seguranca_m)
    if dist > 1e-9:
        zona = obst.buffer(
            dist,
            quad_segs=max(8, int(segmentos_por_quadrante)),
            join_style=join_style,
        )
    else:
        zona = obst
    if zona.is_empty or not linha.intersects(zona):
        return None

    return _linha_mais_anel(
        linha,
        zona.exterior,
        lado_preferido=lado_preferido,
    )


def desviar_circulo_anel(
    segment: Segment,
    center: Point,
    raio_m: float,
    *,
    segmentos_por_quadrante: int = 32,
    lado_preferido: Point | None = None,
) -> list[Point] | None:
    """Desvio pelo anel de um circulo de clearance (ja inclui folga)."""
    r = max(0.05, float(raio_m))
    linha = LineString([segment.start, segment.end])
    if linha.length < 1e-6:
        return None
    zona = ShapelyPoint(float(center[0]), float(center[1])).buffer(
        r,
        quad_segs=max(8, int(segmentos_por_quadrante)),
    )
    if zona.is_empty or not linha.intersects(zona):
        return None
    return _linha_mais_anel(linha, zona.exterior, lado_preferido=lado_preferido)


def desviar_circulo_orbita_360(
    segment: Segment,
    center: Point,
    raio_m: float,
    *,
    segmentos_por_quadrante: int = 32,
    lado_preferido: Point | None = None,
) -> list[Point] | None:
    """Entra no anel, da uma volta completa (360°) e sai na linha sem quebra.

    Usa circulo matematico (nao cordas do buffer Shapely) para manter a folga
    exata do CENTRO = raio informado (obstaculo + W/2 + margem).
    """
    from math import atan2, cos, pi, sin

    from .line_geometry import circle_arc_polyline, line_circle_intersections, point_at_segment_t

    r = max(0.05, float(raio_m))
    ts = line_circle_intersections(segment, center, r)
    if len(ts) < 2:
        return None
    t_in, t_out = ts[0], ts[-1]
    p_in = point_at_segment_t(segment, t_in)
    p_out = point_at_segment_t(segment, t_out)

    ang_in = atan2(p_in[1] - center[1], p_in[0] - center[0])
    ang_out = atan2(p_out[1] - center[1], p_out[0] - center[0])

    # Direcao da orbita: lado preferido da passada (mesmo criterio do arco curto).
    sweep_short = ang_out - ang_in
    while sweep_short <= -pi:
        sweep_short += 2.0 * pi
    while sweep_short > pi:
        sweep_short -= 2.0 * pi
    if lado_preferido is not None:
        mid_ang = ang_in + sweep_short * 0.5
        mid = (center[0] + cos(mid_ang) * r, center[1] + sin(mid_ang) * r)
        mid_line = point_at_segment_t(segment, 0.5 * (t_in + t_out))
        score = (mid[0] - mid_line[0]) * lado_preferido[0] + (mid[1] - mid_line[1]) * lado_preferido[1]
        if score < 0:
            # Outro sentido: arco longo no sentido oposto.
            if sweep_short >= 0:
                sweep_short -= 2.0 * pi
            else:
                sweep_short += 2.0 * pi

    sense = 1.0 if sweep_short >= 0 else -1.0
    segs = max(48, int(segmentos_por_quadrante) * 4)
    # Volta completa a partir da entrada.
    orbita = circle_arc_polyline(center, r, ang_in, sense * 2.0 * pi, segments=segs)
    # Continua no mesmo sentido ate a saida (arco curto ou o escolhido).
    exit_sweep = ang_out - ang_in
    while sense > 0 and exit_sweep <= 0:
        exit_sweep += 2.0 * pi
    while sense < 0 and exit_sweep >= 0:
        exit_sweep -= 2.0 * pi
    # Prefere o menor arco no sentido da orbita (0 < |sweep| <= pi).
    if abs(exit_sweep) > pi + 1e-9:
        exit_sweep -= sense * 2.0 * pi
    if abs(exit_sweep) < 1e-9:
        exit_arc = [p_in, p_out]
    else:
        exit_arc = circle_arc_polyline(
            center, r, ang_in, exit_sweep, segments=max(8, segs // 4)
        )

    coords: list[Point] = []
    if t_in > 1e-9:
        coords.append(segment.start)
    coords.append(p_in)
    for pt in orbita[1:]:
        if abs(coords[-1][0] - pt[0]) > 1e-9 or abs(coords[-1][1] - pt[1]) > 1e-9:
            coords.append(pt)
    for pt in exit_arc[1:]:
        if abs(coords[-1][0] - pt[0]) > 1e-9 or abs(coords[-1][1] - pt[1]) > 1e-9:
            coords.append(pt)
    if t_out < 1.0 - 1e-9:
        if abs(coords[-1][0] - segment.end[0]) > 1e-9 or abs(coords[-1][1] - segment.end[1]) > 1e-9:
            coords.append(segment.end)
    return coords if len(coords) >= 5 else None


def _distancia_ponto_segmento(point: Point, segment: Segment) -> float:
    """Menor distancia do ponto ao segmento (inclui o interior, nao so as pontas)."""
    ax, ay = segment.start
    bx, by = segment.end
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 <= 1e-12:
        return ((point[0] - ax) ** 2 + (point[1] - ay) ** 2) ** 0.5
    t = ((point[0] - ax) * dx + (point[1] - ay) * dy) / length2
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return ((point[0] - cx) ** 2 + (point[1] - cy) ** 2) ** 0.5


def desviar_circulo_validado(
    segment: Segment,
    center: Point,
    raio_base_m: float,
    *,
    raio_giro_minimo_m: float,
    distancia_pino_eixo_m: float = 0.0,
    incremento_m: float = 0.5,
    max_tentativas: int = 20,
    segmentos_por_quadrante: int = 32,
    lado_preferido: Point | None = None,
) -> list[Point] | None:
    """
    Circulo de clearance + off-tracking hitch; aumenta raio ate Rcurv >= Rmin.

    O raio necessario e resolvido antes de gerar geometria. Para um contorno por
    anel a curvatura minima do caminho E o raio do anel, e o anel so produz
    contorno se alcancar a linha. Logo o raio de partida ja pode ser:

        max(raio_clearance, Rmin, distancia_ate_a_linha)

    Alem de gastar ate 20 buffers do Shapely por obstaculo, crescer o raio as
    cegas era contraproducente: a curvatura pior do caminho fica na juncao reta
    x arco, e um anel maior encurta a reta de entrada e FECHA mais essa juncao.
    Por isso o laco guarda a melhor tentativa (maior curvatura) e para assim que
    aumentar o raio deixa de ajudar, em vez de devolver a ultima — que era
    justamente o desvio mais largo e menos dirigivel.
    """
    rmin = max(0.05, float(raio_giro_minimo_m))
    # raio_base_m = distancia do CENTRO do trator (ja inclui W/2 + margem).
    raio = max(0.05, float(raio_base_m))
    incremento = max(1e-6, float(incremento_m))
    tentativas = max(1, int(max_tentativas))

    # Teto que o laco original alcancaria; alem disso nunca houve contorno.
    raio_teto = raio + incremento * (tentativas - 1)
    alcance = _distancia_ponto_segmento(center, segment)
    if alcance > raio_teto:
        return None

    # Curvatura do anel ~ raio; Rmin pode exigir anel um pouco maior que a folga nominal.
    alvo = max(raio, rmin * 0.98)
    if alcance > alvo:
        # Primeiro multiplo do incremento que realmente cruza a linha.
        passos = int((alcance - raio) / incremento) + 1
        alvo = max(alvo, raio + passos * incremento)
    if alvo > raio_teto:
        alvo = raio_teto
    raio = alvo

    melhor: list[Point] | None = None
    melhor_curvatura = -inf
    sem_ganho = 0
    while raio <= raio_teto + 1e-9:
        path = desviar_circulo_anel(
            segment,
            center,
            raio,
            segmentos_por_quadrante=segmentos_por_quadrante,
            lado_preferido=lado_preferido,
        )
        if path is not None:
            curvatura = raio_curvatura_minimo_m(path)
            if curvatura >= rmin * 0.98:
                return path
            if curvatura > melhor_curvatura + 1e-9:
                melhor_curvatura = curvatura
                melhor = path
                sem_ganho = 0
            else:
                sem_ganho += 1
                if sem_ganho >= 2:
                    break
        raio += incremento
    return melhor


def _intersecoes_linha_anel(
    linha: LineString,
    anel,
) -> tuple[ShapelyPoint, ShapelyPoint] | None:
    if anel is None or anel.is_empty:
        return None
    inter = linha.intersection(anel)
    if inter.is_empty:
        return None
    pontos = list(inter.geoms) if hasattr(inter, "geoms") else [inter]
    pontos = [p for p in pontos if isinstance(p, ShapelyPoint) and not p.is_empty]
    if len(pontos) < 2:
        return None
    pontos.sort(key=lambda p: linha.project(p))
    return pontos[0], pontos[-1]


def _escolher_arco_anel(
    linha: LineString,
    anel,
    p_in: ShapelyPoint,
    p_out: ShapelyPoint,
    *,
    lado_preferido: Point | None = None,
) -> LineString | None:
    d_in = anel.project(p_in)
    d_out = anel.project(p_out)
    arco_a = substring(anel, d_in, d_out)
    arco_b = substring(anel, d_out, d_in)
    candidatos: list[LineString] = []
    if not arco_a.is_empty:
        candidatos.append(arco_a)
    if not arco_b.is_empty:
        candidatos.append(LineString(list(arco_b.coords)[::-1]))
    if not candidatos:
        return None

    if lado_preferido is not None and len(candidatos) == 2:
        mid_a = candidatos[0].interpolate(0.5, normalized=True)
        mid_b = candidatos[1].interpolate(0.5, normalized=True)
        mid_linha = linha.interpolate(0.5, normalized=True)
        score_a = (mid_a.x - mid_linha.x) * lado_preferido[0] + (mid_a.y - mid_linha.y) * lado_preferido[1]
        score_b = (mid_b.x - mid_linha.x) * lado_preferido[0] + (mid_b.y - mid_linha.y) * lado_preferido[1]
        if abs(score_a - score_b) > 1e-6 and (score_a > 0) != (score_b > 0):
            return candidatos[0] if score_a >= score_b else candidatos[1]
        arco = min(candidatos, key=lambda g: g.length)
        if abs(candidatos[0].length - candidatos[1].length) < 1e-3:
            return candidatos[0] if score_a >= score_b else candidatos[1]
        return arco
    return min(candidatos, key=lambda g: g.length)


def _append_coords(coords: list[Point], part) -> None:
    if part is None:
        return
    if hasattr(part, "coords"):
        sequence = part.coords
    else:
        sequence = part
    for xy in sequence:
        pt = (float(xy[0]), float(xy[1]))
        if not coords or abs(coords[-1][0] - pt[0]) > 1e-9 or abs(coords[-1][1] - pt[1]) > 1e-9:
            coords.append(pt)


def _linha_mais_anel(
    linha: LineString,
    anel,
    *,
    lado_preferido: Point | None = None,
) -> list[Point] | None:
    ends = _intersecoes_linha_anel(linha, anel)
    if ends is None:
        return None
    p_in, p_out = ends
    arco = _escolher_arco_anel(linha, anel, p_in, p_out, lado_preferido=lado_preferido)
    if arco is None:
        return None

    antes = substring(linha, 0.0, linha.project(p_in))
    depois = substring(linha, linha.project(p_out), linha.length)
    coords: list[Point] = []
    _append_coords(coords, antes)
    _append_coords(coords, arco)
    _append_coords(coords, depois)
    return coords if len(coords) >= 3 else None


def desviar_anel_validado(
    segment: Segment,
    obstaculo_polygon: Polygon,
    *,
    largura_implemento_m: float,
    raio_giro_minimo_m: float,
    distancia_pino_eixo_m: float = 0.0,
    margem_extra_m: float = 0.5,
    incremento_m: float = 0.5,
    max_tentativas: int = 20,
    segmentos_por_quadrante: int = 24,
    cantos: str = "round",
    lado_preferido: Point | None = None,
    distancia_base_m: float | None = None,
) -> list[Point] | None:
    """Buffer + anel, aumentando a distancia ate a curva respeitar Rmin."""
    if distancia_base_m is not None:
        # Folga ja inclui W/2 + margem: hitch e validado nas pontas, nao somado de novo.
        distancia = max(0.05, float(distancia_base_m))
    else:
        distancia = distancia_seguranca_ideal(
            largura_implemento_m,
            raio_giro_minimo_m,
            distancia_pino_eixo_m,
            margem_extra_m,
        )
    rmin = max(0.05, float(raio_giro_minimo_m))
    incremento = max(1e-6, float(incremento_m))
    tentativas = max(1, int(max_tentativas))
    distancia_teto = distancia + incremento * (tentativas - 1)

    # Uma unica medida de distancia evita ate 20 buffers descartados quando o
    # obstaculo esta longe demais da linha para gerar contorno.
    obst = _to_shapely_polygon(obstaculo_polygon)
    if obst is not None and not obst.is_empty:
        try:
            alcance = LineString([segment.start, segment.end]).distance(obst)
        except Exception:
            alcance = 0.0
        if alcance > distancia_teto:
            return None
        if alcance > distancia:
            passos = int((alcance - distancia) / incremento) + 1
            distancia = min(distancia + passos * incremento, distancia_teto)

    melhor: list[Point] | None = None
    melhor_curvatura = -inf
    sem_ganho = 0
    while distancia <= distancia_teto + 1e-9:
        path = desviar_pelo_anel(
            segment,
            obstaculo_polygon,
            distancia,
            segmentos_por_quadrante=segmentos_por_quadrante,
            cantos=cantos,
            lado_preferido=lado_preferido,
        )
        if path is not None:
            curvatura = raio_curvatura_minimo_m(path)
            if curvatura >= rmin * 0.98:
                return path
            # Afastar mais fecha a juncao reta x anel: guarda a melhor tentativa.
            if curvatura > melhor_curvatura + 1e-9:
                melhor_curvatura = curvatura
                melhor = path
                sem_ganho = 0
            else:
                sem_ganho += 1
                if sem_ganho >= 2:
                    break
        distancia += incremento
    return melhor


def circle_as_polygon(center: Point, radius_m: float, *, segments: int = 64) -> Polygon:
    """Circulo como poligono (anel fechado) para o buffer Shapely."""
    from .line_geometry import circle_ring_polygon

    return circle_ring_polygon(center, radius_m, segments=max(16, segments))


def _to_shapely_polygon(polygon: Polygon) -> ShapelyPolygon | None:
    outer, holes = polygon
    if len(outer) < 4:
        return None
    shell = [(float(p[0]), float(p[1])) for p in outer]
    hole_rings = []
    for hole in holes:
        if len(hole) >= 4:
            hole_rings.append([(float(p[0]), float(p[1])) for p in hole])
    try:
        poly = ShapelyPolygon(shell, hole_rings)
        if not poly.is_valid:
            poly = poly.buffer(0)
        return poly if not poly.is_empty else None
    except Exception:
        return None


def _raio_circulo_3_pontos(p1: Point, p2: Point, p3: Point) -> float | None:
    ax, ay = p1
    bx, by = p2
    cx, cy = p3
    a = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
    b = ((cx - bx) ** 2 + (cy - by) ** 2) ** 0.5
    c = ((cx - ax) ** 2 + (cy - ay) ** 2) ** 0.5
    s = (a + b + c) * 0.5
    area2 = max(s * (s - a) * (s - b) * (s - c), 0.0)
    area = area2 ** 0.5
    if area <= 1e-12:
        return None
    return (a * b * c) / (4.0 * area)
