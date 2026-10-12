# -*- coding: utf-8 -*-
"""Geometria 2D simples para linhas agricolas paralelas.

Este modulo nao depende do QGIS para permitir testes unitarios rapidos. As
coordenadas devem estar em um CRS projetado metrico, validado antes da chamada.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import acos, atan2, ceil, cos, degrees, floor, hypot, pi, radians, sin


EPSILON = 1e-9
# Flecha maxima da corda nos arcos de offset/buffer (bordadura, miolo).
ARC_CHORD_TOLERANCE_M = 0.005
Point = tuple[float, float]
Ring = list[Point]
Polygon = tuple[Ring, list[Ring]]
MultiPolygon = list[Polygon]


@dataclass(frozen=True)
class Segment:
    start: Point
    end: Point

    @property
    def length(self) -> float:
        return distance(self.start, self.end)


def add(a: Point, b: Point) -> Point:
    return (a[0] + b[0], a[1] + b[1])


def sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1])


def mul(a: Point, scale: float) -> Point:
    return (a[0] * scale, a[1] * scale)


def dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def distance(a: Point, b: Point) -> float:
    return hypot(b[0] - a[0], b[1] - a[1])


def normalize(vector: Point) -> Point:
    length = hypot(vector[0], vector[1])
    if length <= EPSILON:
        raise ValueError("Linha A-B curta demais para definir direcao.")
    return (vector[0] / length, vector[1] / length)


def perpendicular_left(vector: Point) -> Point:
    return (-vector[1], vector[0])


def azimuth_degrees(start: Point, end: Point) -> float:
    """Retorna azimute em graus: 0=N, 90=E."""
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    angle = degrees(atan2(dx, dy))
    return (angle + 360.0) % 360.0


def point_from_azimuth(start: Point, azimuth_deg: float, length: float) -> Point:
    angle = radians(azimuth_deg)
    return (
        start[0] + sin(angle) * length,
        start[1] + cos(angle) * length,
    )


def extend_segment(start: Point, end: Point, extension: float) -> Segment:
    direction = normalize(sub(end, start))
    return Segment(
        add(start, mul(direction, -extension)),
        add(end, mul(direction, extension)),
    )


def signed_projection(point: Point, origin: Point, axis: Point) -> float:
    return dot(sub(point, origin), axis)


def ring_without_duplicate_close(ring: Ring) -> Ring:
    if len(ring) > 1 and distance(ring[0], ring[-1]) <= EPSILON:
        return ring[:-1]
    return ring


def ring_bbox(ring: Ring) -> tuple[float, float, float, float]:
    pts = ring_without_duplicate_close(ring)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def multipolygon_bbox(polygons: MultiPolygon) -> tuple[float, float, float, float]:
    boxes = [ring_bbox(outer) for outer, _holes in polygons]
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def bbox_corners(bbox: tuple[float, float, float, float]) -> list[Point]:
    xmin, ymin, xmax, ymax = bbox
    return [(xmin, ymin), (xmin, ymax), (xmax, ymin), (xmax, ymax)]


def decimate_polyline(
    points: list[Point] | tuple[Point, ...],
    *,
    min_step_m: float = 5.0,
    max_points: int | None = 120,
) -> list[Point]:
    """Remove vertices densos mantendo extremos (evita freeze no QGIS)."""
    pts = list(points)
    if len(pts) < 2:
        return pts
    if min_step_m > 0:
        out: list[Point] = [pts[0]]
        for point in pts[1:-1]:
            if distance(out[-1], point) >= min_step_m - 1e-9:
                out.append(point)
        if distance(out[-1], pts[-1]) > 1e-9:
            out.append(pts[-1])
        elif len(out) == 1:
            out.append(pts[-1])
    else:
        out = pts
    if max_points is not None and len(out) > max_points:
        last = len(out) - 1
        idxs = [0]
        for i in range(1, max_points - 1):
            idxs.append(int(round(i * last / (max_points - 1))))
        idxs.append(last)
        uniq: list[int] = []
        for idx in idxs:
            if not uniq or idx > uniq[-1]:
                uniq.append(idx)
        out = [out[i] for i in uniq]
    return out


def sanitize_master_polyline(
    points: list[Point] | tuple[Point, ...],
    *,
    min_edge_m: float = 0.05,
) -> list[Point]:
    """Remove vertices repetidos e abre anel fechado para offset de passadas."""
    pts = list(points)
    if len(pts) < 2:
        return pts
    out: list[Point] = [pts[0]]
    for point in pts[1:]:
        if distance(out[-1], point) >= min_edge_m:
            out.append(point)
    if len(out) >= 3 and distance(out[0], out[-1]) < min_edge_m:
        out = out[:-1]
    if len(out) < 2:
        return pts
    return out


def polyline_tangent_at_end(
    points: list[Point] | tuple[Point, ...],
    *,
    at_start: bool,
) -> Point:
    """Direcao unitaria na ponta da polilinha; ignora arestas degeneradas."""
    pts = sanitize_master_polyline(points)
    if len(pts) < 2:
        raise ValueError("Linha A-B curta demais para definir direcao.")
    if at_start:
        pairs = zip(pts, pts[1:])
    else:
        pairs = zip(reversed(pts[:-1]), reversed(pts[1:]))
    for a, b in pairs:
        vec = sub(b, a)
        if hypot(vec[0], vec[1]) > EPSILON:
            return normalize(vec)
    raise ValueError("Linha A-B curta demais para definir direcao.")


def tangent_at_polyline_index(
    points: list[Point] | tuple[Point, ...],
    index: int,
) -> Point:
    """Direcao unitaria no indice da polilinha (ignora arestas degeneradas)."""
    pts = sanitize_master_polyline(points)
    if len(pts) < 2:
        raise ValueError("Linha A-B curta demais para definir direcao.")
    idx = max(0, min(int(index), len(pts) - 1))
    probes = (
        (idx, idx + 1),
        (idx - 1, idx),
        (idx + 1, idx + 2),
        (0, 1),
        (len(pts) - 2, len(pts) - 1),
    )
    for a, b in probes:
        if 0 <= a < len(pts) and 0 <= b < len(pts) and a != b:
            vec = sub(pts[b], pts[a])
            if hypot(vec[0], vec[1]) > EPSILON:
                return normalize(vec)
    return polyline_tangent_at_end(pts, at_start=idx < len(pts) // 2)


def segment_travel_direction(
    segment: Segment,
    path_points: tuple[Point, ...] | list[Point] | None = None,
    *,
    at_index: int | None = None,
    min_span_m: float = 0.05,
) -> Point:
    """Direcao de deslocamento: corda do segmento ou tangente da polilinha."""
    vec = sub(segment.end, segment.start)
    if hypot(vec[0], vec[1]) >= min_span_m:
        return normalize(vec)
    if path_points and len(path_points) >= 2:
        idx = at_index if at_index is not None else len(path_points) // 2
        return tangent_at_polyline_index(path_points, idx)
    raise ValueError("Linha A-B curta demais para definir direcao.")


def ensure_segment_span(
    segment: Segment,
    path_points: tuple[Point, ...] | list[Point] | None = None,
    *,
    at_index: int | None = None,
    half_span_m: float = 12.0,
    min_span_m: float = 1.0,
) -> Segment:
    """Garante segmento com comprimento util para desvio de obstaculo."""
    if distance(segment.start, segment.end) >= min_span_m:
        return segment
    pts = sanitize_master_polyline(path_points) if path_points else []
    idx = at_index if at_index is not None else (len(pts) // 2 if pts else 0)
    if distance(segment.start, segment.end) > EPSILON:
        anchor = point_at_segment_t(segment, 0.5)
    elif pts:
        idx = max(0, min(idx, len(pts) - 1))
        anchor = pts[idx]
    else:
        anchor = segment.start
    direction = segment_travel_direction(segment, pts, at_index=idx)
    return Segment(
        add(anchor, mul(direction, -half_span_m)),
        add(anchor, mul(direction, half_span_m)),
    )


def densify_closed_ring(
    ring: Ring,
    *,
    max_edge_m: float = 2.5,
    max_vertices: int = 720,
    preserve_vertices: bool = False,
) -> Ring:
    """Insere vertices em arestas longas para o offset seguir curvas suaves.

    Limites importados do QGIS costumam ter poucos pontos nas curvas; sem
    densificar, a linha de bordadura vira cordas retas entre vertices esparsos.

    `preserve_vertices`: o limite de vertices nunca reamostra o anel (a
    reamostragem uniforme corta cantos reais); a densificacao fica mais
    espacada e, se o original ja passa do limite, ele e devolvido intacto.
    """
    pts = ring_without_duplicate_close(ring)
    if len(pts) < 2 or max_edge_m <= EPSILON:
        return close_ring(list(pts))
    if preserve_vertices and max_vertices > 0:
        if len(pts) >= max_vertices:
            return close_ring(list(pts))
        perimeter = sum(distance(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts)))
        budget = max_vertices - len(pts)
        max_edge_m = max(max_edge_m, perimeter / float(max(1, budget)))

    out: list[Point] = []
    for index, start in enumerate(pts):
        end = pts[(index + 1) % len(pts)]
        out.append(start)
        edge_len = distance(start, end)
        if edge_len <= max_edge_m:
            continue
        steps = int(ceil(edge_len / max_edge_m))
        for step in range(1, steps):
            t = step / steps
            out.append(add(start, mul(sub(end, start), t)))

    closed = close_ring(out)
    if preserve_vertices:
        return closed
    if max_vertices > 0 and len(ring_without_duplicate_close(closed)) > max_vertices:
        return resample_closed_ring(closed, max_vertices=max_vertices, min_edge_m=0.0)
    return closed


def densify_polygon(
    polygon: Polygon,
    *,
    max_edge_m: float = 2.5,
    max_vertices: int = 720,
    preserve_vertices: bool = False,
) -> Polygon:
    outer, holes = polygon
    options = dict(max_edge_m=max_edge_m, max_vertices=max_vertices, preserve_vertices=preserve_vertices)
    return (
        densify_closed_ring(outer, **options),
        [densify_closed_ring(hole, **options) for hole in holes],
    )


def densify_multipolygon(
    polygons: MultiPolygon,
    *,
    max_edge_m: float = 2.5,
    max_vertices: int = 720,
    preserve_vertices: bool = False,
) -> MultiPolygon:
    return [
        densify_polygon(
            poly,
            max_edge_m=max_edge_m,
            max_vertices=max_vertices,
            preserve_vertices=preserve_vertices,
        )
        for poly in polygons
    ]


def resample_closed_ring(
    ring: Ring,
    *,
    max_vertices: int = 180,
    min_edge_m: float = 0.0,
) -> Ring:
    """Reduz vertices de anel fechado preservando forma (PIP / shutoff).

    Pivos densificados a 2 m (~1500 verts) tornam point-in-polygon inviavel
    no cruzamento linha × bordadura. Limitar a ~180 verts mantem a forma
    e reduz o custo de O(N×V) em ordens de magnitude.
    """
    pts = ring_without_duplicate_close(ring)
    if len(pts) < 3:
        return close_ring(list(pts)) if pts else []

    # Remove arestas muito curtas antes do limite de vertices.
    if min_edge_m > 0:
        cleaned: list[Point] = [pts[0]]
        for pt in pts[1:]:
            if distance(cleaned[-1], pt) >= min_edge_m:
                cleaned.append(pt)
        if len(cleaned) >= 3 and distance(cleaned[-1], cleaned[0]) < min_edge_m:
            cleaned.pop()
        pts = cleaned if len(cleaned) >= 3 else ring_without_duplicate_close(ring)

    if max_vertices <= 0 or len(pts) <= max_vertices:
        return close_ring(list(pts))

    # Amostragem uniforme pelo comprimento acumulado.
    edges = [distance(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]
    perimeter = sum(edges)
    if perimeter <= EPSILON:
        return close_ring(list(pts[:max_vertices]))

    step = perimeter / float(max_vertices)
    out: list[Point] = [pts[0]]
    walked = 0.0
    target = step
    for idx, edge_len in enumerate(edges):
        a = pts[idx]
        b = pts[(idx + 1) % len(pts)]
        if edge_len <= EPSILON:
            continue
        while walked + edge_len >= target - 1e-9 and len(out) < max_vertices:
            t = (target - walked) / edge_len
            t = max(0.0, min(1.0, t))
            out.append(add(a, mul(sub(b, a), t)))
            target += step
        walked += edge_len
    if len(out) < 3:
        stride = max(1, len(pts) // max_vertices)
        out = pts[::stride][:max_vertices]
    return close_ring(out)


def simplify_multipolygon_for_pip(
    polygons: MultiPolygon,
    *,
    max_vertices: int = 180,
    min_edge_m: float = 2.0,
) -> MultiPolygon:
    """Simplifica aneis para testes point-in-polygon / shutoff."""
    if not polygons:
        return []
    result: MultiPolygon = []
    for outer, holes in polygons:
        new_outer = resample_closed_ring(
            outer, max_vertices=max_vertices, min_edge_m=min_edge_m
        )
        new_holes = [
            resample_closed_ring(hole, max_vertices=max_vertices, min_edge_m=min_edge_m)
            for hole in holes
        ]
        if len(ring_without_duplicate_close(new_outer)) >= 3:
            result.append((new_outer, new_holes))
    return result


def point_in_ring(point: Point, ring: Ring, *, check_boundary: bool = True) -> bool:
    """Teste ray-casting. Pontos na borda sao considerados dentro."""
    pts = ring_without_duplicate_close(ring)
    if len(pts) < 3:
        return False
    inside = False
    x, y = point
    count = len(pts)
    for idx in range(count):
        a = pts[idx]
        b = pts[(idx + 1) % count]
        if check_boundary and point_on_segment(point, a, b):
            return True
        intersects = ((a[1] > y) != (b[1] > y)) and (
            x < (b[0] - a[0]) * (y - a[1]) / ((b[1] - a[1]) or EPSILON) + a[0]
        )
        if intersects:
            inside = not inside
    return inside


def point_on_segment(point: Point, start: Point, end: Point) -> bool:
    if abs(cross(sub(point, start), sub(end, start))) > 1e-7:
        return False
    return (
        min(start[0], end[0]) - 1e-7 <= point[0] <= max(start[0], end[0]) + 1e-7
        and min(start[1], end[1]) - 1e-7 <= point[1] <= max(start[1], end[1]) + 1e-7
    )


def point_in_polygon(point: Point, polygon: Polygon, *, check_boundary: bool = True) -> bool:
    outer, holes = polygon
    if not point_in_ring(point, outer, check_boundary=check_boundary):
        return False
    return not any(
        point_in_ring(point, hole, check_boundary=check_boundary) for hole in holes
    )


def point_in_multipolygon(
    point: Point,
    polygons: MultiPolygon,
    *,
    check_boundary: bool = True,
) -> bool:
    return any(
        point_in_polygon(point, polygon, check_boundary=check_boundary)
        for polygon in polygons
    )


_PREPARED_POLYGON_CACHE: dict[int, tuple[object, list]] = {}


def _prepared_polygons(polygons: MultiPolygon) -> list | None:
    cached = _PREPARED_POLYGON_CACHE.get(id(polygons))
    if cached is not None and cached[0] is polygons:
        return cached[1]
    try:
        from shapely import prepare
        from shapely.geometry import Polygon as _ShapelyPolygon
    except ImportError:
        return None
    prepared = []
    for outer, holes in polygons:
        if len(ring_without_duplicate_close(outer)) < 3:
            continue
        geometry = _ShapelyPolygon(outer, [hole for hole in holes if len(hole) >= 4])
        prepare(geometry)
        prepared.append(geometry)
    if len(_PREPARED_POLYGON_CACHE) > 16:
        _PREPARED_POLYGON_CACHE.clear()
    _PREPARED_POLYGON_CACHE[id(polygons)] = (polygons, prepared)
    return prepared


def points_in_multipolygon(points: list[Point], polygons: MultiPolygon) -> list[bool]:
    """Mesmo criterio de point_in_multipolygon (borda = dentro), vetorizado no GEOS.

    O teste ponto a ponto em Python e O(pontos x vertices) e travava a geracao de
    passadas curvas em talhoes com milhares de vertices.
    """
    if not points:
        return []
    prepared = _prepared_polygons(polygons) if len(points) >= 32 else None
    if prepared is not None:
        try:
            import numpy as np
            from shapely import intersects_xy

            coords = np.asarray(points, dtype=float)
            inside = np.zeros(len(points), dtype=bool)
            for geometry in prepared:
                inside |= intersects_xy(geometry, coords[:, 0], coords[:, 1])
            return inside.tolist()
        except Exception:
            pass
    return [point_in_multipolygon(point, polygons) for point in points]


def line_ring_intersections(base: Point, direction: Point, ring: Ring) -> list[float]:
    """Retorna parametros t onde base + direction*t cruza o anel."""
    pts = ring_without_duplicate_close(ring)
    intersections: list[float] = []
    for idx in range(len(pts)):
        a = pts[idx]
        b = pts[(idx + 1) % len(pts)]
        edge = sub(b, a)
        denom = cross(direction, edge)
        if abs(denom) <= EPSILON:
            if abs(cross(sub(a, base), direction)) <= EPSILON:
                intersections.append(dot(sub(a, base), direction))
                intersections.append(dot(sub(b, base), direction))
            continue
        delta = sub(a, base)
        t = cross(delta, edge) / denom
        u = cross(delta, direction) / denom
        if -EPSILON <= u <= 1.0 + EPSILON:
            intersections.append(t)
    return intersections


def _unique_sorted(values: list[float]) -> list[float]:
    values = sorted(values)
    unique: list[float] = []
    for value in values:
        if not unique or abs(value - unique[-1]) > 1e-7:
            unique.append(value)
    return unique


def clip_infinite_line_to_polygon(base: Point, direction: Point, polygon: Polygon) -> list[Segment]:
    """Recorta uma reta infinita por um poligono com buracos."""
    outer, holes = polygon
    t_values = line_ring_intersections(base, direction, outer)
    for hole in holes:
        t_values.extend(line_ring_intersections(base, direction, hole))
    values = _unique_sorted(t_values)
    if len(values) < 2:
        return []

    segments: list[Segment] = []
    for start_t, end_t in zip(values, values[1:]):
        if end_t - start_t <= EPSILON:
            continue
        mid_t = (start_t + end_t) / 2.0
        midpoint = add(base, mul(direction, mid_t))
        if point_in_polygon(midpoint, polygon):
            segments.append(
                Segment(
                    add(base, mul(direction, start_t)),
                    add(base, mul(direction, end_t)),
                )
            )
    return segments


def clip_infinite_line_to_multipolygon(
    base: Point,
    direction: Point,
    polygons: MultiPolygon,
) -> list[Segment]:
    segments: list[Segment] = []
    for polygon in polygons:
        segments.extend(clip_infinite_line_to_polygon(base, direction, polygon))
    return segments


def shrink_axis_aligned_polygon(polygon: Polygon, distance_m: float) -> Polygon | None:
    """Encolhe retangulo alinhado aos eixos (legado de fixtures).

    Preferir `shrink_polygon` — o limite real do talhao nao pode virar bbox.
    """
    if distance_m <= 0:
        return polygon
    outer, holes = polygon
    xmin, ymin, xmax, ymax = ring_bbox(outer)
    if xmax - xmin <= distance_m * 2 or ymax - ymin <= distance_m * 2:
        return None
    inner = [
        (xmin + distance_m, ymin + distance_m),
        (xmax - distance_m, ymin + distance_m),
        (xmax - distance_m, ymax - distance_m),
        (xmin + distance_m, ymax - distance_m),
        (xmin + distance_m, ymin + distance_m),
    ]
    return inner, holes


def ring_signed_area(ring: Ring) -> float:
    pts = ring_without_duplicate_close(ring)
    total = 0.0
    for idx in range(len(pts)):
        a = pts[idx]
        b = pts[(idx + 1) % len(pts)]
        total += a[0] * b[1] - b[0] * a[1]
    return 0.5 * total


def ensure_ccw_ring(ring: Ring) -> Ring:
    pts = ring_without_duplicate_close(ring)
    if ring_signed_area(pts) < 0:
        return list(reversed(pts))
    return list(pts)


def polygon_area(polygon: Polygon) -> float:
    """Area real do poligono (anel externo menos buracos), em m2 no CRS metrico."""
    outer, holes = polygon
    total = abs(ring_signed_area(outer))
    for hole in holes:
        total -= abs(ring_signed_area(hole))
    return max(0.0, total)


def multipolygon_area(polygons: MultiPolygon) -> float:
    """Soma das areas dos poligonos (nunca usa bounding box)."""
    return sum(polygon_area(poly) for poly in polygons)


def line_line_intersection(a1: Point, a2: Point, b1: Point, b2: Point) -> Point | None:
    """Intersecao de retas infinitas a1-a2 e b1-b2."""
    da = sub(a2, a1)
    db = sub(b2, b1)
    denom = cross(da, db)
    if abs(denom) <= EPSILON:
        return None
    t = cross(sub(b1, a1), db) / denom
    return add(a1, mul(da, t))


def offset_closed_ring(ring: Ring, offset_m: float) -> Ring | None:
    """Offset de anel fechado: positivo = esquerda dos segmentos.

    Em anel exterior CCW, a esquerda aponta para DENTRO: offset positivo encolhe.
    Offset negativo expande.
    Nunca usa bounding box como geometria de saida.

    Usa buffer real (GEOS) quando disponivel: mantem a distancia CONSTANTE em
    curvas e elimina lacos de auto-intersecao do offset por mitre. Sem GEOS,
    cai no offset por intersecao de paralelas (abaixo).
    """
    pts = ring_without_duplicate_close(ring)
    if len(pts) < 3 or abs(offset_m) <= EPSILON:
        return close_ring(list(pts)) if pts else None

    buffered = _offset_closed_ring_geos(pts, offset_m)
    if buffered is not None:
        return buffered

    n = len(pts)
    parallels: list[tuple[Point, Point]] = []
    for idx in range(n):
        a = pts[idx]
        b = pts[(idx + 1) % n]
        edge = sub(b, a)
        length = hypot(edge[0], edge[1])
        if length <= EPSILON:
            if parallels:
                prev_a, prev_b = parallels[-1]
                direction = normalize(sub(prev_b, prev_a))
            else:
                continue
        else:
            direction = (edge[0] / length, edge[1] / length)
        normal = perpendicular_left(direction)
        shift = mul(normal, offset_m)
        parallels.append((add(a, shift), add(b, shift)))

    if len(parallels) < 3:
        return None

    out: list[Point] = []
    count = len(parallels)
    for idx in range(count):
        prev_a, prev_b = parallels[idx - 1]
        cur_a, cur_b = parallels[idx]
        hit = line_line_intersection(prev_a, prev_b, cur_a, cur_b)
        if hit is None:
            hit = cur_a
        out.append(hit)

    if len(out) < 3:
        return None
    if abs(ring_signed_area(out)) < 1e-3:
        return None
    return close_ring(out)


def _offset_closed_ring_geos(pts: Ring, offset_m: float) -> Ring | None:
    """Offset por buffer real (GEOS/Shapely). None se indisponivel ou degenerado."""
    try:
        from shapely.geometry import Polygon as _ShapelyPolygon
    except Exception:
        return None

    try:
        source = _ShapelyPolygon([(float(p[0]), float(p[1])) for p in pts])
        if not source.is_valid:
            source = source.buffer(0)
        if source.is_empty:
            return None
        # Anel CCW: offset positivo aponta para dentro (encolhe) => buffer negativo.
        signed = -offset_m if ring_signed_area(pts) >= 0 else offset_m
        if signed < 0:
            # Encolher (bordadura/miolo): round mantem os cantos vivos do talhao
            # e transforma reentrancias em arco — e o arco que trava a distancia.
            result = source.buffer(signed, quad_segs=24, join_style=1)
        else:
            # Expandir (area de processamento/envelope): mitre mantem os cantos
            # vivos e evita inflar vertices em contornos usados ponto a ponto.
            result = source.buffer(signed, quad_segs=16, join_style=2, mitre_limit=5.0)
        if result.is_empty:
            return None
        if result.geom_type == "MultiPolygon":
            result = max(result.geoms, key=lambda g: g.area)
        if result.geom_type != "Polygon" or result.is_empty:
            return None
        coords = [(float(x), float(y)) for x, y in result.exterior.coords]
    except Exception:
        return None

    out = ring_without_duplicate_close(coords)
    if len(out) < 3 or abs(ring_signed_area(out)) < 1e-3:
        return None
    # Preserva a orientacao do anel de entrada (chamadores assumem CCW).
    if (ring_signed_area(out) >= 0) != (ring_signed_area(pts) >= 0):
        out = list(reversed(out))
    return close_ring(out)


def shrink_polygon(polygon: Polygon, distance_m: float) -> Polygon | None:
    """Encolhe poligono real (anel externo + buracos), sem bbox.

    Outer CCW: offset positivo (esquerda = para dentro).
    Buracos CCW: offset negativo (direita = para dentro do material / buraco maior).
    """
    if distance_m <= 0:
        return polygon
    outer, holes = polygon
    outer_ccw = ensure_ccw_ring(outer)
    new_outer = offset_closed_ring(outer_ccw, distance_m)
    if new_outer is None:
        return None
    new_holes: list[Ring] = []
    for hole in holes:
        hole_ccw = ensure_ccw_ring(hole)
        expanded = offset_closed_ring(hole_ccw, -distance_m)
        if expanded is not None:
            new_holes.append(expanded)
    return new_outer, new_holes


def expand_polygon(polygon: Polygon, distance_m: float) -> Polygon:
    """Expande poligono real para fora (area de processamento / +extensao)."""
    if distance_m <= 0:
        return polygon
    outer, holes = polygon
    outer_ccw = ensure_ccw_ring(outer)
    new_outer = offset_closed_ring(outer_ccw, -distance_m)
    if new_outer is None:
        return polygon
    new_holes: list[Ring] = []
    for hole in holes:
        hole_ccw = ensure_ccw_ring(hole)
        shrunk_hole = offset_closed_ring(hole_ccw, distance_m)
        if shrunk_hole is not None and abs(ring_signed_area(shrunk_hole)) >= 1e-3:
            new_holes.append(shrunk_hole)
    return new_outer, new_holes


def shrink_polygon_components(polygon: Polygon, distance_m: float) -> MultiPolygon:
    """Encolhe o poligono devolvendo TODOS os componentes do buffer interno.

    Um estreitamento mais fino que 2x a distancia separa o talhao em partes;
    cada parte continua sendo area de trabalho (nunca so a maior). Com um unico
    componente o resultado e identico a `shrink_polygon`.
    """
    if distance_m <= 0:
        return [polygon]
    eroded = eroded_polygon_geos(polygon, distance_m)
    if eroded is None:
        shrunk = shrink_polygon(polygon, distance_m)
        return [shrunk] if shrunk is not None else []
    from .polygon_components import extract_polygon_components, validate_component_area_conservation

    parts = extract_polygon_components(eroded)
    validate_component_area_conservation(eroded.area, [part.area for part in parts])
    components: MultiPolygon = []
    for part in parts:
        outer = _ccw_closed_ring(part.exterior.coords)
        if outer is None:
            continue
        holes = [ring for ring in (_ccw_closed_ring(item.coords) for item in part.interiors) if ring]
        components.append((outer, holes))
    return components


def erosion_quad_segs(
    distance_m: float,
    tolerance_m: float = ARC_CHORD_TOLERANCE_M,
    *,
    minimum: int = 24,
    maximum: int = 720,
) -> int:
    """Segmentos por quarto de circulo para a corda do arco ficar a <= tolerancia.

    Nos arcos do buffer os vertices ficam exatamente a `distance_m`; o meio de
    cada corda fica mais perto (flecha = d * (1 - cos(corda / 2))). O GEOS
    arredonda o numero de segmentos de cada arco, entao uma corda pode cobrir
    ate 1,5 passo angular: o passo e dimensionado para esse pior caso.
    """
    d = abs(float(distance_m))
    if d <= tolerance_m:
        return minimum
    half_chord = acos(max(-1.0, 1.0 - tolerance_m / d))
    if half_chord <= 0:
        return maximum
    step = 2.0 * half_chord / 1.5
    return int(min(maximum, max(minimum, ceil((pi / 2.0) / step))))


def eroded_polygon_geos(polygon: Polygon, distance_m: float):
    """polygon.buffer(-d) com juncao redonda (distancia exata a limite e ilhas).

    Sempre a partir do poligono original (offset absoluto). None sem GEOS.
    """
    outer, holes = polygon
    pts = ring_without_duplicate_close(outer)
    if len(pts) < 3:
        return None
    try:
        from shapely.geometry import Polygon as _ShapelyPolygon
    except Exception:
        return None
    try:
        hole_rings = [
            ring_without_duplicate_close(hole) for hole in holes if len(ring_without_duplicate_close(hole)) >= 3
        ]
        source = _ShapelyPolygon(
            [(float(p[0]), float(p[1])) for p in ensure_ccw_ring(pts)],
            [[(float(p[0]), float(p[1])) for p in ring] for ring in hole_rings],
        )
        if not source.is_valid:
            source = source.buffer(0)
        if source.is_empty:
            return None
        return source.buffer(-distance_m, quad_segs=erosion_quad_segs(distance_m), join_style=1)
    except Exception:
        return None


def _ccw_closed_ring(coords) -> Ring | None:
    ring = ring_without_duplicate_close([(float(x), float(y)) for x, y in coords])
    if len(ring) < 3 or abs(ring_signed_area(ring)) < 1e-3:
        return None
    if ring_signed_area(ring) < 0:
        ring = list(reversed(ring))
    return close_ring(ring)


def shrink_multipolygon(polygons: MultiPolygon, distance_m: float) -> MultiPolygon:
    result: MultiPolygon = []
    for polygon in polygons:
        result.extend(shrink_polygon_components(polygon, distance_m))
    return result


def expand_multipolygon(polygons: MultiPolygon, distance_m: float) -> MultiPolygon:
    return [expand_polygon(polygon, distance_m) for polygon in polygons]


def build_processing_boundary(
    original_boundary: MultiPolygon,
    extension_m: float,
) -> MultiPolygon:
    """Limite operacional temporario = original expandido (+extensao).

    O talhao visual permanece o original; so o clip das passadas usa este buffer.
    Nunca usa bounding box — preserva curvas do limite real.
    """
    if not original_boundary:
        return []
    if extension_m <= 0:
        return list(original_boundary)
    return expand_multipolygon(original_boundary, extension_m)


def offset_open_polyline(points: list[Point] | tuple[Point, ...], offset_m: float) -> list[Point]:
    """Offset perpendicular a esquerda ao longo de polilinha aberta."""
    pts = sanitize_master_polyline(points)
    if len(pts) < 2 or abs(offset_m) <= EPSILON:
        return pts
    out: list[Point] = []
    last = len(pts) - 1
    for index, point in enumerate(pts):
        direction = None
        if index == 0:
            try:
                direction = polyline_tangent_at_end(pts, at_start=True)
            except ValueError:
                direction = None
        elif index == last:
            try:
                direction = polyline_tangent_at_end(pts, at_start=False)
            except ValueError:
                direction = None
        else:
            d1 = sub(pts[index], pts[index - 1])
            d2 = sub(pts[index + 1], pts[index])
            combined = add(d1, d2)
            if hypot(combined[0], combined[1]) > EPSILON:
                direction = normalize(combined)
            elif hypot(d2[0], d2[1]) > EPSILON:
                direction = normalize(d2)
            elif hypot(d1[0], d1[1]) > EPSILON:
                direction = normalize(d1)
        if direction is None:
            continue
        out.append(add(point, mul(perpendicular_left(direction), offset_m)))
    return out if len(out) >= 2 else pts


def offset_open_polyline_exact(
    points: list[Point] | tuple[Point, ...], offset_m: float
) -> list[list[Point]]:
    """Offset a esquerda com distancia exata a polilinha em todo ponto (GEOS, juncao redonda).

    O offset por bissetriz encurta a distancia nos vertices; aqui cada ponto fica
    a |offset_m| da mestre (arcos com flecha <= ARC_CHORD_TOLERANCE_M). Partes
    sao devolvidas no sentido da mestre. Sem GEOS cai no offset por bissetriz.
    """
    pts = sanitize_master_polyline(points)
    if len(pts) < 2 or abs(offset_m) <= EPSILON:
        return [pts] if len(pts) >= 2 else []
    try:
        from shapely.geometry import LineString as _ShapelyLine

        master = _ShapelyLine(pts)
        result = master.offset_curve(
            offset_m, quad_segs=erosion_quad_segs(offset_m), join_style="round"
        )
        lines = list(getattr(result, "geoms", [result]))
    except Exception:
        fallback = offset_open_polyline(pts, offset_m)
        return [fallback] if len(fallback) >= 2 else []
    parts: list[tuple[float, list[Point]]] = []
    for line in lines:
        if line.is_empty or line.geom_type != "LineString":
            continue
        coords = [(float(x), float(y)) for x, y in line.coords]
        if len(coords) < 2:
            continue
        start_station = master.project(line.interpolate(0.0))
        end_station = master.project(line.interpolate(line.length))
        if end_station < start_station:
            coords.reverse()
            start_station = end_station
        parts.append((start_station, coords))
    parts.sort(key=lambda item: item[0])
    return [coords for _, coords in parts]


def extend_polyline_ends(points: list[Point] | tuple[Point, ...], extension_m: float) -> list[Point]:
    """Estende apenas as pontas da polilinha (unica extensao operacional permitida)."""
    pts = sanitize_master_polyline(points)
    if extension_m <= 0 or len(pts) < 2:
        return list(points) if points else pts
    start_dir = polyline_tangent_at_end(pts, at_start=True)
    end_dir = polyline_tangent_at_end(pts, at_start=False)
    return [add(pts[0], mul(start_dir, -extension_m))] + pts + [add(pts[-1], mul(end_dir, extension_m))]


def clip_polyline_to_multipolygon(
    points: list[Point] | tuple[Point, ...],
    polygons: MultiPolygon,
) -> list[list[Point]]:
    """Recorta polilinha ao multipoligono; devolve trechos contiguos dentro."""
    pts = list(points)
    if len(pts) < 2 or not polygons:
        return []
    # Densifica levemente para capturar cruzamentos com o limite.
    densified = segment_samples(pts, densify_m=max(1.0, polyline_length(pts) / 200.0))
    chunks: list[list[Point]] = []
    current: list[Point] = []
    for point, inside in zip(densified, points_in_multipolygon(densified, polygons)):
        if inside:
            current.append(point)
        else:
            if len(current) >= 2:
                chunks.append(current)
            current = []
    if len(current) >= 2:
        chunks.append(current)
    return chunks


def clip_polyline_exact(
    points: list[Point] | tuple[Point, ...],
    polygons: MultiPolygon,
) -> list[list[Point]]:
    """Recorte no cruzamento real com o limite (GEOS), sem cortar a curva por amostra.

    Os trechos seguem o sentido da polilinha e mantem os vertices originais.
    Sem GEOS cai no recorte amostral.
    """
    pts = list(points)
    if len(pts) < 2 or not polygons:
        return []
    try:
        from shapely.geometry import LineString as _ShapelyLine
        from shapely.geometry import Polygon as _ShapelyPolygon
        from shapely.ops import unary_union

        shapes = []
        for outer, holes in polygons:
            ring = ring_without_duplicate_close(outer)
            if len(ring) < 3:
                continue
            shape = _ShapelyPolygon(
                ring,
                [ring_without_duplicate_close(h) for h in holes if len(ring_without_duplicate_close(h)) >= 3],
            )
            shapes.append(shape if shape.is_valid else shape.buffer(0))
        if not shapes:
            return []
        line = _ShapelyLine(pts)
        result = line.intersection(unary_union(shapes))
    except Exception:
        return clip_polyline_to_multipolygon(pts, polygons)
    pieces = [
        geom
        for geom in getattr(result, "geoms", [result])
        if not geom.is_empty and geom.geom_type == "LineString" and geom.length > EPSILON
    ]
    chunks: list[tuple[float, list[Point]]] = []
    for piece in pieces:
        coords = [(float(x), float(y)) for x, y in piece.coords]
        start = line.project(piece.interpolate(0.0))
        end = line.project(piece.interpolate(piece.length))
        if end < start:
            coords.reverse()
            start = end
        chunks.append((start, coords))
    chunks.sort(key=lambda item: item[0])
    merged: list[list[Point]] = []
    for _, coords in chunks:
        if merged and distance(merged[-1][-1], coords[0]) <= 1e-9:
            merged[-1].extend(coords[1:])
        else:
            merged.append(coords)
    return merged


def signed_distance_point_to_polyline(point: Point, polyline: list[Point] | tuple[Point, ...]) -> float:
    """Distancia com sinal: positiva a esquerda da polilinha."""
    pts = list(polyline)
    if len(pts) < 2:
        return 0.0
    best = None
    best_dist = float("inf")
    for start, end in zip(pts, pts[1:]):
        edge = sub(end, start)
        length2 = edge[0] * edge[0] + edge[1] * edge[1]
        if length2 <= EPSILON:
            continue
        t = max(0.0, min(1.0, dot(sub(point, start), edge) / length2))
        proj = add(start, mul(edge, t))
        d = distance(point, proj)
        if d < best_dist:
            best_dist = d
            direction = normalize(edge)
            side = cross(direction, sub(point, proj))
            best = best_dist if side >= 0 else -best_dist
    return 0.0 if best is None else best


def signed_distances_to_polyline(
    points: list[Point], polyline: list[Point] | tuple[Point, ...]
) -> list[float]:
    """signed_distance_point_to_polyline para muitos pontos, vetorizado no GEOS."""
    pts = sanitize_master_polyline(polyline)
    if len(points) >= 32 and len(pts) >= 2:
        try:
            import numpy as np
            import shapely
            from shapely.geometry import LineString as _ShapelyLine

            line = _ShapelyLine(pts)
            coords = np.asarray(points, dtype=float)
            geoms = shapely.points(coords)
            stations = shapely.line_locate_point(line, geoms)
            projected = shapely.get_coordinates(shapely.line_interpolate_point(line, stations))
            vertices = np.asarray(pts, dtype=float)
            cumulative = np.concatenate(
                ([0.0], np.cumsum(np.hypot(*np.diff(vertices, axis=0).T)))
            )
            index = np.clip(np.searchsorted(cumulative, stations, side="right") - 1, 0, len(pts) - 2)
            edge = vertices[index + 1] - vertices[index]
            delta = coords - projected
            side = edge[:, 0] * delta[:, 1] - edge[:, 1] * delta[:, 0]
            distances = np.hypot(delta[:, 0], delta[:, 1])
            return np.where(side >= 0, distances, -distances).tolist()
        except Exception:
            pass
    return [signed_distance_point_to_polyline(point, pts) for point in points]


def polygon_bbox_fill_ratio(polygon: Polygon) -> float:
    """area(poligono) / area(bbox). Círculo ~0.785; retângulo eixo-alinhado ~1.0."""
    outer, _holes = polygon
    xmin, ymin, xmax, ymax = ring_bbox(outer)
    width = xmax - xmin
    height = ymax - ymin
    if width <= EPSILON or height <= EPSILON:
        return 1.0
    bbox_area = width * height
    poly_area = abs(ring_signed_area(outer))
    if bbox_area <= EPSILON:
        return 1.0
    return poly_area / bbox_area


def circularity_score(polygon: Polygon) -> float:
    """4*pi*A/P^2 — ~1.0 para círculo, ~0.785 para quadrado."""
    outer, _holes = polygon
    pts = ring_without_duplicate_close(outer)
    if len(pts) < 3:
        return 0.0
    area = abs(ring_signed_area(outer))
    peri = polyline_length(close_ring(list(pts)))
    if peri <= EPSILON:
        return 0.0
    return (4.0 * pi * area) / (peri * peri)


def looks_like_axis_aligned_bbox(
    polygon: Polygon,
    *,
    min_fill_ratio: float = 0.92,
    edge_fraction: float = 0.95,
) -> bool:
    """Detecta envelope retangular mesmo densificado (muitos vértices colineares)."""
    outer, _holes = polygon
    pts = ring_without_duplicate_close(outer)
    if len(pts) < 4:
        return True
    xmin, ymin, xmax, ymax = ring_bbox(outer)
    width = xmax - xmin
    height = ymax - ymin
    if width <= EPSILON or height <= EPSILON:
        return True
    fill = polygon_bbox_fill_ratio(polygon)
    if fill < min_fill_ratio:
        return False
    # 4 vértices distintos eixo-alinhados
    xs = {round(p[0], 3) for p in pts}
    ys = {round(p[1], 3) for p in pts}
    if len(pts) <= 4 and len(xs) <= 2 and len(ys) <= 2:
        return True
    # Densificado: quase todos os pontos colados nas 4 bordas do bbox
    tol = max(0.5, 0.02 * min(width, height))
    on_edge = 0
    for x, y in pts:
        if (
            abs(x - xmin) <= tol
            or abs(x - xmax) <= tol
            or abs(y - ymin) <= tol
            or abs(y - ymax) <= tol
        ):
            on_edge += 1
    return (on_edge / len(pts)) >= edge_fraction


def assert_not_degenerate_field(multipolygon: MultiPolygon) -> None:
    """Bloqueia saida se o limite virou um retangulo/bbox (mesmo densificado)."""
    if not multipolygon:
        raise ValueError("Limite operacional vazio.")
    polygon = multipolygon[0]
    outer = polygon[0]
    xmin, ymin, xmax, ymax = ring_bbox(outer)
    if looks_like_axis_aligned_bbox(polygon):
        raise ValueError(
            "O limite ficou um retangulo/quadrado (provavel Bounding Box / extent), "
            "nao a circunferencia do talhao. "
            "Selecione SO a feicao circular do pivo na camada LIMITE "
            f"(EPSG metrico), marque 'usar feicao selecionada' e limpe o preview. "
            f"Envelope: {xmax - xmin:.1f} m x {ymax - ymin:.1f} m "
            f"(preenchimento bbox={polygon_bbox_fill_ratio(polygon):.2f})."
        )


def close_ring(points: Ring) -> Ring:
    if not points:
        return points
    if distance(points[0], points[-1]) <= EPSILON:
        return points
    return points + [points[0]]


def polyline_length(points: list[Point]) -> float:
    total = 0.0
    for start, end in zip(points, points[1:]):
        total += distance(start, end)
    return total


def arc_polyline(
    start: Point,
    end: Point,
    *,
    bulge_left: bool = True,
    segments: int = 16,
) -> list[Point]:
    """Aproxima um semicirculo (volta em U) com diametro start-end.

    O arco fica a esquerda ou direita do vetor start->end conforme
    `bulge_left`. O raio geometrico e metade da distancia entre extremos
    (nao inventa o raio minimo da maquina).
    """
    from math import pi

    chord = sub(end, start)
    chord_len = hypot(chord[0], chord[1])
    if chord_len <= EPSILON:
        return [start, end]
    if segments < 2:
        segments = 2

    direction = normalize(chord)
    normal = perpendicular_left(direction)
    if not bulge_left:
        normal = mul(normal, -1.0)
    radius = chord_len / 2.0
    center = mul(add(start, end), 0.5)

    points: list[Point] = []
    for step in range(segments + 1):
        t = step / segments
        ang = pi * t
        points.append(
            add(
                center,
                add(mul(direction, -radius * cos(ang)), mul(normal, radius * sin(ang))),
            )
        )
    points[0] = start
    points[-1] = end
    return points


def drop_polyline(
    start: Point,
    end: Point,
    *,
    forward: Point,
    radius_m: float,
    segments: int = 24,
) -> list[Point]:
    """Aproxima uma volta em gota (bulb) avancando no sentido `forward`.

    O centro fica alem da corda start-end, no interior da bordadura, e o arco
    percorre o caminho longo (>= 180°) de start ate end.
    """
    from math import atan2, pi

    chord = sub(end, start)
    chord_len = hypot(chord[0], chord[1])
    if chord_len <= EPSILON:
        return [start, end]
    if segments < 4:
        segments = 4

    fwd = normalize(forward)
    mid = mul(add(start, end), 0.5)
    depth = max(radius_m, chord_len / 2.0)
    center = add(mid, mul(fwd, depth))

    start_vec = sub(start, center)
    end_vec = sub(end, center)
    start_r = hypot(start_vec[0], start_vec[1])
    end_r = hypot(end_vec[0], end_vec[1])
    if start_r <= EPSILON or end_r <= EPSILON:
        return [start, end]

    start_ang = atan2(start_vec[1], start_vec[0])
    end_ang = atan2(end_vec[1], end_vec[0])
    delta = end_ang - start_ang
    while delta <= -pi:
        delta += 2.0 * pi
    while delta > pi:
        delta -= 2.0 * pi
    apex = add(mid, mul(fwd, depth * 2.0))
    apex_ang = atan2(apex[1] - center[1], apex[0] - center[0])

    def _ang_dist(a: float, b: float) -> float:
        d = b - a
        while d <= -pi:
            d += 2.0 * pi
        while d > pi:
            d -= 2.0 * pi
        return d

    short = delta
    long = delta - 2.0 * pi if delta > 0 else delta + 2.0 * pi
    if abs(long) < pi:
        long = delta + (2.0 * pi if delta <= 0 else -2.0 * pi)

    def score(sweep: float) -> float:
        mid_ang = start_ang + sweep / 2.0
        return abs(_ang_dist(mid_ang, apex_ang))

    sweep = long if score(long) <= score(short) else (
        short if abs(short) >= pi else long
    )
    if abs(sweep) < pi:
        sweep = pi if sweep >= 0 else -pi

    points: list[Point] = []
    for step in range(segments + 1):
        t = step / segments
        ang = start_ang + sweep * t
        radius = start_r + (end_r - start_r) * t
        points.append((center[0] + cos(ang) * radius, center[1] + sin(ang) * radius))
    points[0] = start
    points[-1] = end
    return points


def omega_polyline(
    start: Point,
    end: Point,
    *,
    forward: Point,
    radius_m: float,
    segments: int = 32,
) -> list[Point]:
    """Aproxima uma volta em omega (dois lobos laterais + abertura frontal).

    Forma tipica para implementos longos/rebocados: a maquina abre para os
    lados e avanca, reduzindo o angulo de articulacao.
    """
    chord = sub(end, start)
    chord_len = hypot(chord[0], chord[1])
    if chord_len <= EPSILON:
        return [start, end]
    if segments < 8:
        segments = 8

    fwd = normalize(forward)
    direction = normalize(chord)
    left = perpendicular_left(direction)
    mid = mul(add(start, end), 0.5)
    lobe = max(radius_m, chord_len * 0.35)
    depth = max(radius_m * 1.25, chord_len * 0.4)

    # Controles da forma Ω: laterais + apex frontal.
    p_left = add(start, add(mul(fwd, depth * 0.45), mul(left, lobe)))
    p_apex = add(mid, mul(fwd, depth))
    p_right = add(end, add(mul(fwd, depth * 0.45), mul(left, -lobe)))
    controls = [start, p_left, p_apex, p_right, end]

    # Densifica cada segmento de controle para polilinha suave.
    per_seg = max(2, segments // (len(controls) - 1))
    points: list[Point] = [start]
    for a, b in zip(controls, controls[1:]):
        for step in range(1, per_seg + 1):
            t = step / per_seg
            points.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    points[0] = start
    points[-1] = end
    return points


def three_point_polyline(
    start: Point,
    end: Point,
    *,
    forward: Point,
    radius_m: float,
) -> list[Point]:
    """Aproxima manobra de tres pontos (avanco / re / avanco).

    Marcada como manobra especial: nao e giro continuo.
    """
    chord = sub(end, start)
    chord_len = hypot(chord[0], chord[1])
    if chord_len <= EPSILON:
        return [start, end]

    fwd = normalize(forward)
    direction = normalize(chord)
    left = perpendicular_left(direction)
    mid = mul(add(start, end), 0.5)
    stem = max(radius_m, chord_len * 0.4)
    lateral = max(radius_m * 0.6, chord_len * 0.25)

    a = add(start, mul(fwd, stem))
    b = add(mid, add(mul(fwd, stem * 0.25), mul(left, lateral)))
    c = add(end, mul(fwd, stem))
    return [start, a, b, c, end]


def segment_samples(points: list[Point], densify_m: float = 2.0) -> list[Point]:
    """Amostra pontos ao longo de uma polilinha para validacao espacial."""
    if densify_m <= 0 or len(points) < 2:
        return list(points)
    samples: list[Point] = [points[0]]
    for start, end in zip(points, points[1:]):
        length = distance(start, end)
        if length <= densify_m:
            samples.append(end)
            continue
        steps = max(1, int(floor(length / densify_m)))
        direction = normalize(sub(end, start))
        for idx in range(1, steps + 1):
            samples.append(add(start, mul(direction, densify_m * idx)))
        if distance(samples[-1], end) > EPSILON:
            samples.append(end)
    return samples


def segment_inside_intervals(
    segment: Segment,
    polygons: MultiPolygon,
    *,
    sample_count: int = 64,
) -> list[tuple[float, float]]:
    """Retorna intervalos normalizados [t0, t1] onde o segmento esta dentro do multipoligono."""
    length = segment.length
    if length <= EPSILON or not polygons:
        return []

    intervals: list[tuple[float, float]] = []
    open_start: float | None = None
    steps = max(4, sample_count)
    for step in range(steps + 1):
        t = step / steps
        point = add(segment.start, mul(sub(segment.end, segment.start), t))
        inside = point_in_multipolygon(point, polygons)
        if inside and open_start is None:
            open_start = t
        elif not inside and open_start is not None:
            intervals.append((open_start, t))
            open_start = None
    if open_start is not None:
        intervals.append((open_start, 1.0))
    return intervals


def segment_subtract_multipolygon(
    segment: Segment,
    polygons: MultiPolygon,
    *,
    sample_count: int = 64,
) -> list[Segment]:
    """Retorna sub-segmentos que ficam fora do multipoligono."""
    if not polygons:
        return [segment]
    inside = segment_inside_intervals(segment, polygons, sample_count=sample_count)
    if not inside:
        return [segment]

    outside: list[Segment] = []
    cursor = 0.0
    vec = sub(segment.end, segment.start)
    for start_t, end_t in inside:
        if start_t - cursor > EPSILON:
            outside.append(
                Segment(
                    add(segment.start, mul(vec, cursor)),
                    add(segment.start, mul(vec, start_t)),
                )
            )
        cursor = max(cursor, end_t)
    if 1.0 - cursor > EPSILON:
        outside.append(
            Segment(
                add(segment.start, mul(vec, cursor)),
                segment.end,
            )
        )
    return [item for item in outside if item.length > EPSILON]


def build_track_strip_polygon(
    segment: Segment,
    *,
    normal_left: Point,
    lateral_offset_m: float,
    tire_width_m: float,
) -> Polygon:
    """Constroi faixa retangular de tramline paralela ao segmento."""
    half = tire_width_m / 2.0
    offset = mul(normal_left, lateral_offset_m)
    lateral = normal_left
    p1 = add(segment.start, add(offset, mul(lateral, half)))
    p2 = add(segment.end, add(offset, mul(lateral, half)))
    p3 = add(segment.end, add(offset, mul(lateral, -half)))
    p4 = add(segment.start, add(offset, mul(lateral, -half)))
    ring = close_ring([p1, p2, p3, p4])
    return (ring, [])


def build_polyline_strip_polygon(
    points: list[Point] | tuple[Point, ...],
    *,
    half_width_m: float,
    resample_m: float = 2.0,
) -> Polygon | None:
    """Faixa poligonal ao longo de polilinha (retas e arcos densificados).

    Nao usa bounding box nem corda start→end. Offset ±half_width na perpendicular.
    Reamostra a polilinha para limitar vertices (performance no shutoff).
    """
    pts = list(points)
    if len(pts) < 2 or half_width_m <= EPSILON:
        return None
    if resample_m > 0 and len(pts) > 2:
        pts = segment_samples(pts, densify_m=max(resample_m, half_width_m))
    # Remove duplicatas consecutivas.
    cleaned: list[Point] = [pts[0]]
    for point in pts[1:]:
        if distance(cleaned[-1], point) > EPSILON:
            cleaned.append(point)
    pts = cleaned
    if len(pts) < 2:
        return None
    left = offset_open_polyline(pts, half_width_m)
    right = offset_open_polyline(pts, -half_width_m)
    if len(left) < 2 or len(right) < 2:
        return None
    ring = close_ring(list(left) + list(reversed(right)))
    if abs(ring_signed_area(ring)) < 1e-6:
        return None
    return (ring, [])


def split_polyline_by_multipolygon(
    points: list[Point] | tuple[Point, ...],
    polygons: MultiPolygon,
    *,
    densify_m: float = 0.5,
) -> tuple[list[list[Point]], list[list[Point]]]:
    """Parte polilinha em trechos dentro e fora do multipoligono.

    Amostra grosso e so refina perto das transicoes (evita freeze em pivos densos).
    """
    pts = list(points)
    if len(pts) < 2:
        return [], []
    if not polygons:
        return [], [pts]

    coarse_step = max(5.0, densify_m)
    fine_step = max(0.5, densify_m)
    coarse = segment_samples(pts, densify_m=coarse_step)
    if not coarse:
        return [], []

    flags = [
        point_in_multipolygon(point, polygons, check_boundary=False) for point in coarse
    ]

    # Refina apenas intervalos que mudam dentro/fora.
    densified: list[Point] = []
    inside_flags: list[bool] = []
    for index, point in enumerate(coarse):
        flag = flags[index]
        if index == 0:
            densified.append(point)
            inside_flags.append(flag)
            continue
        prev = coarse[index - 1]
        prev_flag = flags[index - 1]
        if prev_flag != flag and fine_step < coarse_step - 1e-9:
            refined = segment_samples([prev, point], densify_m=fine_step)
            for mid in refined[1:-1]:
                densified.append(mid)
                inside_flags.append(
                    point_in_multipolygon(mid, polygons, check_boundary=False)
                )
        densified.append(point)
        inside_flags.append(flag)

    inside_chunks: list[list[Point]] = []
    outside_chunks: list[list[Point]] = []
    current: list[Point] = []
    current_inside: bool | None = None

    for point, inside in zip(densified, inside_flags):
        if current_inside is None:
            current_inside = inside
            current = [point]
            continue
        if inside == current_inside:
            current.append(point)
            continue
        if len(current) >= 2:
            if current_inside:
                inside_chunks.append(current)
            else:
                outside_chunks.append(current)
        current = [current[-1], point]
        current_inside = inside

    if current_inside is not None and len(current) >= 2:
        if current_inside:
            inside_chunks.append(current)
        else:
            outside_chunks.append(current)
    return inside_chunks, outside_chunks


def circle_arc_polyline(
    center: Point,
    radius_m: float,
    start_angle_rad: float,
    sweep_rad: float,
    *,
    segments: int = 32,
) -> list[Point]:
    """Gera arco circular concéntrico (sentido anti-horario matematico)."""
    from math import cos, sin

    if radius_m <= EPSILON:
        return [center]
    if segments < 4:
        segments = 4
    points: list[Point] = []
    for step in range(segments + 1):
        t = step / segments
        ang = start_angle_rad + sweep_rad * t
        points.append((center[0] + cos(ang) * radius_m, center[1] + sin(ang) * radius_m))
    return points


def circle_ring_polygon(center: Point, radius_m: float, *, segments: int = 32) -> Polygon:
    """Anel circular completo como poligono."""
    ring = circle_arc_polyline(center, radius_m, 0.0, 2.0 * 3.141592653589793, segments=segments)
    return (close_ring(ring), [])


def offset_axis_aligned_polygon(polygon: Polygon, distance_m: float) -> Polygon:
    """Offset simples eixo-alinhado (expande bbox externa)."""
    outer, holes = polygon
    xs = [p[0] for p in outer]
    ys = [p[1] for p in outer]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    expanded = [
        (min_x - distance_m, min_y - distance_m),
        (max_x + distance_m, min_y - distance_m),
        (max_x + distance_m, max_y + distance_m),
        (min_x - distance_m, max_y + distance_m),
        (min_x - distance_m, min_y - distance_m),
    ]
    return (expanded, holes)


def line_circle_intersections(segment: Segment, center: Point, radius_m: float) -> list[float]:
    """Parametros t em [0,1] onde o segmento cruza a circunferencia."""
    from math import sqrt

    if radius_m <= EPSILON:
        return []
    d = sub(segment.end, segment.start)
    f = sub(segment.start, center)
    a = dot(d, d)
    b = 2.0 * dot(f, d)
    c = dot(f, f) - radius_m * radius_m
    disc = b * b - 4.0 * a * c
    if disc < 0 or a <= EPSILON:
        return []
    sqrt_disc = sqrt(disc)
    values: list[float] = []
    for sign in (-1.0, 1.0):
        t = (-b + sign * sqrt_disc) / (2.0 * a)
        if -EPSILON <= t <= 1.0 + EPSILON:
            values.append(max(0.0, min(1.0, t)))
    return sorted(set(round(v, 9) for v in values))


def point_at_segment_t(segment: Segment, t: float) -> Point:
    return add(segment.start, mul(sub(segment.end, segment.start), t))
