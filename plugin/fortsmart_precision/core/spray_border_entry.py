# -*- coding: utf-8 -*-
"""Entra e sai automatico da pulverizacao pela linha real da bordadura.

Etapa posterior a geracao: nao altera passadas, bordadura, A-B nem o U da
manobra automatica. Distancias em metros, CRS projetado.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

from shapely.geometry import LineString, MultiPoint, Point as ShapelyPoint
from shapely.geometry import Polygon
from shapely.ops import substring

from .headland_turn_engine import HEADLAND_TURN_FIELDS
from .line_geometry import Point, add, distance, mul, sub
from .planting_line_cut_engine import line_id_for

TURN_TYPE = "BORDER_TRANSIT"
SPRAY_BORDER_ENTRY_PROPERTY = "fortsmart_precision/spray_border_entry"
SPRAY_BORDER_ENTRY_SOURCE = "11_Passadas"

EXIT_LEAD_M = 7.0
ENTRY_ANTICIPATION_M = 7.0
ENTRY_ALIGNMENT_STEP_M = 0.50
MIN_ENTRY_ALIGNMENT_M = 0.50

STATUS_OK = "OK"
STATUS_NOT_VALIDATED = "NOT_VALIDATED"
STATUS_INFEASIBLE = "INFEASIBLE"
STATUS_BLOCKED_U_TURN = "BLOCKED_U_TURN"
STATUS_NO_HEADLAND = "NO_HEADLAND"
STATUS_NO_PASSES = "NO_PASSES"

INFEASIBLE_MESSAGE = "Manobra inviavel com os criterios atuais"
BLOCKED_U_TURN_MESSAGE = (
    "Entra e sai automatico nao roda junto da manobra automatica (U). "
    "Volte o modo de cabeceira para extensao reta."
)
NOT_VALIDATED_MESSAGE = (
    "Previa geometrica ok; raio de giro do pulverizador nao informado "
    "(nao validado para operacao)."
)

GEOMETRY_TOLERANCE_M = 0.05
ANGLE_TOLERANCE_DEG = 2.0
HIT_TOLERANCE_M = 0.15
BEZIER_SAMPLES = 48
BEZIER_ALPHAS = (0.25, 0.35, 0.45, 0.55, 0.20, 0.65)
MAX_HEADING_JUMP_DEG = 25.0
_MIN_PART_M = 0.05
_HEADING_DELTA_M = 0.08


def _unit(vector: Point) -> Point | None:
    length = math.hypot(vector[0], vector[1])
    if length < 1e-12:
        return None
    return (vector[0] / length, vector[1] / length)


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _heading_error_deg(a: Point, b: Point) -> float:
    ua, ub = _unit(a), _unit(b)
    if ua is None or ub is None:
        return 180.0
    return abs(math.degrees(math.atan2(_cross(ua, ub), _dot(ua, ub))))


def _pt(geom) -> Point:
    return (float(geom.x), float(geom.y))


def _closed(points: Iterable[Point]) -> list[Point]:
    coords = [(float(x), float(y)) for x, y in points]
    if len(coords) < 2:
        return coords
    if distance(coords[0], coords[-1]) > 1e-9:
        coords.append(coords[0])
    return coords


def _as_line(points: Iterable[Point]) -> LineString | None:
    coords = [(float(x), float(y)) for x, y in points]
    if len(coords) < 2:
        return None
    line = LineString(coords)
    return None if line.length < _MIN_PART_M else line


def _cubic_bezier(p0: Point, p1: Point, p2: Point, p3: Point, samples: int = BEZIER_SAMPLES) -> list[Point]:
    out: list[Point] = []
    n = max(8, int(samples))
    for i in range(n + 1):
        t = i / n
        u = 1.0 - t
        x = (u ** 3) * p0[0] + 3 * (u ** 2) * t * p1[0] + 3 * u * (t ** 2) * p2[0] + (t ** 3) * p3[0]
        y = (u ** 3) * p0[1] + 3 * (u ** 2) * t * p1[1] + 3 * u * (t ** 2) * p2[1] + (t ** 3) * p3[1]
        out.append((x, y))
    return out


def _hermite_bezier(
    start: Point,
    start_dir: Point,
    end: Point,
    end_dir: Point,
    alpha: float,
    inward: Point | None = None,
) -> list[Point]:
    chord = distance(start, end)
    reach = max(chord * float(alpha), 0.05)
    # Controles sobre as tangentes (G1). O vetor inward so escolhe alpha, nao puxa fora da tangente.
    _ = inward
    c1 = add(start, mul(start_dir, reach))
    c2 = add(end, mul(end_dir, -reach))
    return _cubic_bezier(start, c1, c2, end)


def _path_headings(points: list[Point]) -> list[Point]:
    heads: list[Point] = []
    for a, b in zip(points, points[1:]):
        unit = _unit(sub(b, a))
        if unit is not None:
            heads.append(unit)
    return heads


def _max_heading_jump_deg(points: list[Point]) -> float:
    heads = _path_headings(points)
    if len(heads) < 2:
        return 0.0
    return max(_heading_error_deg(a, b) for a, b in zip(heads, heads[1:]))


def _min_radius_m(points: list[Point]) -> float:
    if len(points) < 3:
        return math.inf
    best = math.inf
    for p0, p1, p2 in zip(points, points[1:], points[2:]):
        a = distance(p0, p1)
        b = distance(p1, p2)
        c = distance(p0, p2)
        cross = abs(_cross(sub(p1, p0), sub(p2, p0)))
        if cross < 1e-12:
            continue
        radius = (a * b * c) / (2.0 * cross)
        if radius < best:
            best = radius
    return best


def _polyline_length(points: list[Point]) -> float:
    return sum(distance(a, b) for a, b in zip(points, points[1:]))


def _max_distance_to_line(points: list[Point], reference: LineString, step_m: float = 0.25) -> float:
    """Maior afastamento amostrado; cobre o interior dos segmentos, nao so vertices."""
    line = _as_line(points)
    if line is None or reference.is_empty:
        return math.inf
    samples = max(2, int(math.ceil(line.length / max(step_m, 0.01))) + 1)
    return max(
        float(reference.distance(line.interpolate(line.length * index / (samples - 1))))
        for index in range(samples)
    )


def _dedupe(points: list[Point], tol: float = 1e-9) -> list[Point]:
    if not points:
        return []
    out = [points[0]]
    for point in points[1:]:
        if distance(out[-1], point) > tol:
            out.append(point)
    return out


def _coords(geom) -> list[Point]:
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "LineString":
        return [(float(x), float(y)) for x, y in geom.coords]
    parts = []
    for item in getattr(geom, "geoms", []):
        parts.extend(_coords(item))
    return parts


def _interpolate(line: LineString, station: float) -> Point:
    length = line.length
    if length <= 0:
        return _pt(line.interpolate(0.0))
    wrapped = station % length
    if wrapped < 0:
        wrapped += length
    return _pt(line.interpolate(wrapped))


def _heading_at(line: LineString, station: float, sign: int, *, closed: bool = False) -> Point:
    length = line.length
    delta = _HEADING_DELTA_M
    signed = 1 if sign >= 0 else -1
    if closed:
        a = _interpolate(line, station - signed * delta)
        b = _interpolate(line, station + signed * delta)
        return _unit(sub(b, a)) or (1.0, 0.0)
    s0 = min(max(station, 0.0), length)
    s1 = min(max(station + signed * delta, 0.0), length)
    if abs(s1 - s0) < 1e-9:
        s1 = min(max(station - signed * delta, 0.0), length)
        unit = _unit(sub(_pt(line.interpolate(s1)), _pt(line.interpolate(s0))))
        return mul(unit, -1.0) if unit else (1.0, 0.0)
    return _unit(sub(_pt(line.interpolate(s1)), _pt(line.interpolate(s0)))) or (1.0, 0.0)


def _forward_span(length: float, start: float, end: float) -> float:
    if length <= 0:
        return 0.0
    span = (end - start) % length
    return span if span > 0 or abs(end - start) < 1e-12 else 0.0


def _ring_substring(ring: LineString, start: float, end: float, forward: bool) -> list[Point]:
    length = ring.length
    if length <= 0:
        return []
    if forward:
        span = _forward_span(length, start, end)
        if span < _MIN_PART_M:
            return []
        if start <= end + 1e-12:
            return _coords(substring(ring, start, min(end, length)))
        first = _coords(substring(ring, start, length))
        second = _coords(substring(ring, 0.0, end))
        return _dedupe(first + second)
    span = _forward_span(length, end, start)
    if span < _MIN_PART_M:
        return []
    if end <= start + 1e-12:
        return list(reversed(_coords(substring(ring, end, min(start, length)))))
    first = list(reversed(_coords(substring(ring, 0.0, start))))
    second = list(reversed(_coords(substring(ring, end, length))))
    return _dedupe(first + second)


def _hits(pass_line: LineString, ring: LineString, tol: float = HIT_TOLERANCE_M) -> list[tuple[float, float, Point]]:
    found: list[tuple[float, float, Point]] = []
    inter = pass_line.intersection(ring)
    geoms = []
    if inter.is_empty:
        if pass_line.distance(ring) <= tol:
            p_on_pass = pass_line.interpolate(pass_line.project(ring.interpolate(ring.project(pass_line.centroid))))
            station_p = pass_line.project(p_on_pass)
            p_on_ring = ring.interpolate(ring.project(p_on_pass))
            geoms = [p_on_ring]
        else:
            return []
    elif inter.geom_type == "Point":
        geoms = [inter]
    elif inter.geom_type == "MultiPoint":
        geoms = list(inter.geoms)
    else:
        geoms = [item for item in getattr(inter, "geoms", [inter]) if item.geom_type == "Point"]
        if not geoms and hasattr(inter, "coords"):
            geoms = [ShapelyPoint(coord) for coord in inter.coords]
    seen = set()
    for geom in geoms:
        point = _pt(geom)
        key = (round(point[0], 3), round(point[1], 3))
        if key in seen:
            continue
        seen.add(key)
        found.append((float(pass_line.project(ShapelyPoint(*point))), float(ring.project(ShapelyPoint(*point))), point))
    return found


def _is_forward(direction: str | int | None) -> bool:
    text = str(direction or "forward").strip().casefold()
    return text not in {"reverse", "rev", "ba", "b->a", "b-a", "volta", "-1", "reversed", "invertido"}


@dataclass(frozen=True)
class SprayPassInput:
    pass_id: int
    points: tuple[Point, ...]
    direction: str = "forward"
    line_id: str = ""

    @property
    def key(self) -> str:
        return self.line_id or line_id_for(int(self.pass_id))


@dataclass(frozen=True)
class HeadlandRingInput:
    pass_no: int
    offset_m: float
    points: tuple[Point, ...]
    line_id: str = ""


@dataclass(frozen=True)
class BorderEntrySettings:
    exit_lead_m: float = EXIT_LEAD_M
    entry_lead_m: float = ENTRY_ANTICIPATION_M
    alignment_step_m: float = ENTRY_ALIGNMENT_STEP_M
    min_alignment_m: float = MIN_ENTRY_ALIGNMENT_M
    min_turn_radius_m: float | None = None
    geometry_tolerance_m: float = GEOMETRY_TOLERANCE_M
    angle_tolerance_deg: float = ANGLE_TOLERANCE_DEG

    def validate_limits(self) -> str | None:
        if self.exit_lead_m <= 0:
            return "lead de saida deve ser > 0"
        if self.entry_lead_m <= 0:
            return "antecipacao da entrada sobre a bordadura deve ser > 0"
        if self.alignment_step_m <= 0:
            return "passo de busca do alinhamento deve ser > 0"
        if self.min_alignment_m <= 0:
            return "alinhamento minimo deve ser > 0"
        if self.min_turn_radius_m is not None and self.min_turn_radius_m <= 0:
            return "raio minimo, se informado, deve ser > 0"
        return None


@dataclass(frozen=True)
class BorderEntryConnection:
    turn_id: str
    from_pass: int
    to_pass: int
    from_line_id: str
    to_line_id: str
    headland_line_id: str
    status: str
    points: tuple[Point, ...]
    exit_points: tuple[Point, ...] = ()
    transit_points: tuple[Point, ...] = ()
    entry_points: tuple[Point, ...] = ()
    a: Point | None = None
    b: Point | None = None
    d: Point | None = None
    e: Point | None = None
    exit_lead_m: float = 0.0
    entry_lead_m: float = 0.0
    align_m: float = 0.0
    min_radius_m: float | None = None
    length_m: float = 0.0
    transit_length_m: float = 0.0
    a_station_m: float | None = None
    b_station_m: float | None = None
    d_station_m: float | None = None
    e_station_m: float | None = None
    tangent_error_a_deg: float | None = None
    tangent_error_b_deg: float | None = None
    tangent_error_d_deg: float | None = None
    tangent_error_e_deg: float | None = None
    max_transit_distance_m: float | None = None
    message: str = ""
    kinematics: str = "not_validated"

    def attributes(self, source_layer: str = SPRAY_BORDER_ENTRY_SOURCE) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "from_pass": self.from_pass,
            "to_pass": self.to_pass,
            "turn_type": TURN_TYPE,
            "radius_m": None if self.min_radius_m is None else round(self.min_radius_m, 3),
            "length_m": round(self.length_m, 3),
            "status": self.status,
            "sequence": 0,
            "source_layer": source_layer,
            "simulation_only": True,
            "pass_spacing_m": 0.0,
            "from_line_id": self.from_line_id,
            "to_line_id": self.to_line_id,
            "headland_line_id": self.headland_line_id,
            "message": self.message,
        }

    def diagnostic(self) -> dict[str, Any]:
        """Valores auditaveis da previa, sem persistir nem alterar fontes."""
        return {
            "turn_id": self.turn_id,
            "turn_type": TURN_TYPE,
            "status": self.status,
            "from_pass": self.from_pass,
            "to_pass": self.to_pass,
            "from_line_id": self.from_line_id,
            "to_line_id": self.to_line_id,
            "headland_line_id": self.headland_line_id,
            "points": {"A": self.a, "B": self.b, "D": self.d, "E": self.e},
            "a_station_m": self.a_station_m,
            "b_station_m": self.b_station_m,
            "d_station_m": self.d_station_m,
            "e_station_m": self.e_station_m,
            "exit_lead_m": self.exit_lead_m,
            "transit_length_m": self.transit_length_m,
            "entry_lead_m": self.entry_lead_m,
            "align_m": self.align_m,
            "tangent_error_deg": {
                "A": self.tangent_error_a_deg,
                "B": self.tangent_error_b_deg,
                "D": self.tangent_error_d_deg,
                "E": self.tangent_error_e_deg,
            },
            "max_transit_distance_m": self.max_transit_distance_m,
            "component_vertices": {
                "exit": len(self.exit_points),
                "border_transit": len(self.transit_points),
                "entry": len(self.entry_points),
            },
            "uses_real_headland_substring": len(self.transit_points) >= 2,
        }


@dataclass(frozen=True)
class BorderEntryPlan:
    connections: tuple[BorderEntryConnection, ...] = ()
    rejected: tuple[BorderEntryConnection, ...] = ()
    warnings: tuple[str, ...] = ()
    report: dict[str, Any] = field(default_factory=dict)

    @property
    def accepted(self) -> tuple[BorderEntryConnection, ...]:
        return tuple(
            item for item in self.connections
            if item.status in (STATUS_OK, STATUS_NOT_VALIDATED) and len(item.points) >= 2
        )


def outermost_headland_ring(rings: Iterable[HeadlandRingInput]) -> HeadlandRingInput | None:
    valid = [ring for ring in rings if len(ring.points) >= 2]
    if not valid:
        return None
    return min(valid, key=lambda ring: (float(ring.offset_m), int(ring.pass_no)))


def _interior_polygon(ring: LineString) -> Polygon | None:
    coords = _closed(ring.coords)
    if len(coords) < 4:
        return None
    polygon = Polygon(coords)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if polygon.is_empty or polygon.area <= 0:
        return None
    return polygon


def _inward_at(ring: LineString, station: float, interior: Polygon | None, forward: bool) -> Point | None:
    tangent = _heading_at(ring, station, 1 if forward else -1, closed=True)
    left = (-tangent[1], tangent[0])
    point = _interpolate(ring, station)
    probe = add(point, mul(left, 0.4))
    if interior is None:
        return left
    if interior.covers(ShapelyPoint(*probe)) or interior.contains(ShapelyPoint(*probe)):
        return left
    return mul(left, -1.0)


def _entry_alignment_candidates(available_m: float, settings: BorderEntrySettings) -> list[float]:
    """Distancias crescentes na passada destino; nao altera os 7 m medidos em B1."""
    if available_m + 1e-9 < settings.min_alignment_m:
        return []
    dense_limit = min(float(available_m), 20.0)
    values: list[float] = []
    value = float(settings.min_alignment_m)
    while value <= dense_limit + 1e-9:
        values.append(min(value, float(available_m)))
        value += float(settings.alignment_step_m)
    if available_m > dense_limit + 1e-9:
        coarse_step = max(settings.alignment_step_m, (available_m - dense_limit) / 128.0)
        value = dense_limit + coarse_step
        while value < available_m - 1e-9:
            values.append(value)
            value += coarse_step
        values.append(float(available_m))
    return sorted(set(round(item, 9) for item in values))


def _connection(
    from_pass: SprayPassInput,
    to_pass: SprayPassInput,
    ring: LineString,
    ring_id: str,
    settings: BorderEntrySettings,
    interior: Polygon | None,
) -> BorderEntryConnection:
    turn_id = f"BE{int(from_pass.pass_id):03d}_{int(to_pass.pass_id):03d}"

    def fail(message: str, **extra) -> BorderEntryConnection:
        return BorderEntryConnection(
            turn_id=turn_id,
            from_pass=int(from_pass.pass_id),
            to_pass=int(to_pass.pass_id),
            from_line_id=from_pass.key,
            to_line_id=to_pass.key,
            headland_line_id=ring_id,
            status=STATUS_INFEASIBLE,
            points=(),
            message=f"{INFEASIBLE_MESSAGE}: {message}",
            **extra,
        )

    limit_error = settings.validate_limits()
    if limit_error:
        return fail(limit_error)

    from_line = _as_line(from_pass.points)
    to_line = _as_line(to_pass.points)
    if from_line is None or to_line is None:
        return fail("passada sem geometria")

    from_hits = _hits(from_line, ring)
    to_hits = _hits(to_line, ring)
    if not from_hits or not to_hits:
        return fail("passada nao cruza a bordadura")

    from_target = from_line.length if _is_forward(from_pass.direction) else 0.0
    to_target = 0.0 if _is_forward(to_pass.direction) else to_line.length
    s_from, r_from, c1 = min(from_hits, key=lambda hit: abs(hit[0] - from_target))
    s_to, r_to, c2 = min(to_hits, key=lambda hit: abs(hit[0] - to_target))
    if distance(c1, c2) < settings.geometry_tolerance_m:
        return fail("cruzamentos coincidentes")

    length = ring.length
    span_fwd = _forward_span(length, r_from, r_to)
    span_rev = _forward_span(length, r_to, r_from)
    if min(span_fwd, span_rev) < settings.entry_lead_m + _MIN_PART_M:
        return fail("arco de bordadura curto demais para os criterios")
    # Mesma cabeceira: o arco curto. O longo e o outro lado do talhao.
    forward = span_fwd <= span_rev
    arc_m = span_fwd if forward else span_rev
    if arc_m > 0.55 * length:
        return fail("pares nao adjacentes na mesma cabeceira")

    from_sign = 1 if s_from >= from_line.length * 0.5 else -1
    a_station = s_from - from_sign * settings.exit_lead_m
    if a_station < -1e-9 or a_station > from_line.length + 1e-9:
        return fail(f"nao ha {settings.exit_lead_m:.2f} m de passada para dentro ate a bordadura")
    a_station = min(max(a_station, 0.0), from_line.length)
    measured_exit = abs(s_from - a_station)
    if abs(measured_exit - settings.exit_lead_m) > 0.02:
        return fail(f"saida nao mede {settings.exit_lead_m:.2f} m ao longo da passada")

    to_sign = 1 if s_to < to_line.length * 0.5 else -1
    available_alignment = to_line.length - s_to if to_sign > 0 else s_to

    if forward:
        d_station = (r_to - settings.entry_lead_m) % length
        measured_entry = _forward_span(length, d_station, r_to)
    else:
        d_station = (r_to + settings.entry_lead_m) % length
        measured_entry = _forward_span(length, r_to, d_station)
    if abs(measured_entry - settings.entry_lead_m) > 0.02:
        return fail(
            f"antecipacao da entrada nao mede {settings.entry_lead_m:.2f} m sobre a bordadura"
        )
    if _forward_span(length, r_from, d_station) if forward else _forward_span(length, d_station, r_from) >= arc_m:
        return fail("D nao fica no trecho B→cruzamento")

    a = _pt(from_line.interpolate(a_station))
    b = c1
    d = _interpolate(ring, d_station)
    a_dir = _heading_at(from_line, a_station, from_sign, closed=False)
    b_dir = _heading_at(ring, r_from, 1 if forward else -1, closed=True)
    d_dir = _heading_at(ring, d_station, 1 if forward else -1, closed=True)
    inward_b = _inward_at(ring, r_from, interior, forward)
    inward_d = _inward_at(ring, d_station, interior, forward)

    transit = _ring_substring(ring, r_from, d_station, forward)
    if len(transit) < 2:
        return fail("trecho B→D da bordadura vazio")
    max_transit_distance = _max_distance_to_line(transit, ring)
    if max_transit_distance > settings.geometry_tolerance_m:
        return fail("B→D nao coincide com a bordadura")

    ab_curve = None
    for alpha in BEZIER_ALPHAS:
        cand_ab = _hermite_bezier(a, a_dir, b, b_dir, alpha, inward_b)
        if _transition_ok(cand_ab, a_dir, b_dir, interior, ring, settings):
            ab_curve = cand_ab
            break
    if ab_curve is None:
        return fail(
            f"saida de {settings.exit_lead_m:.2f} m nao comporta curva tangente sem ultrapassar B1",
            a=a, b=b, d=d,
            exit_lead_m=measured_exit, entry_lead_m=measured_entry,
        )

    de_curve = None
    e = None
    e_dir = None
    e_station = None
    measured_align = 0.0
    for align_distance in _entry_alignment_candidates(available_alignment, settings):
        candidate_station = s_to + to_sign * align_distance
        candidate_e = _pt(to_line.interpolate(candidate_station))
        candidate_dir = _heading_at(to_line, candidate_station, to_sign, closed=False)
        for alpha in BEZIER_ALPHAS:
            cand_de = _hermite_bezier(d, d_dir, candidate_e, candidate_dir, alpha, inward_d)
            if _transition_ok(cand_de, d_dir, candidate_dir, interior, ring, settings):
                de_curve = cand_de
                e = candidate_e
                e_dir = candidate_dir
                e_station = candidate_station
                measured_align = align_distance
                break
        if de_curve is not None:
            break
    if de_curve is None or e is None or e_dir is None or e_station is None:
        return fail(
            f"entrada iniciada {settings.entry_lead_m:.2f} m antes em B1 nao encontra alinhamento tangente em A8",
            a=a, b=b, d=d,
            exit_lead_m=measured_exit, entry_lead_m=measured_entry,
        )

    points = _dedupe(ab_curve[:-1] + transit + de_curve[1:])
    if len(points) < 4:
        return fail("geometria costurada vazia", a=a, b=b, d=d, e=e)
    path = LineString(points)
    if not path.is_simple:
        return fail("trajeto com auto-intersecao", a=a, b=b, d=d, e=e)
    if _max_heading_jump_deg(points) > MAX_HEADING_JUMP_DEG:
        return fail("quina ou inversao abrupta", a=a, b=b, d=d, e=e)

    radius = _min_radius_m(points)
    transit_length = LineString(transit).length
    exit_heads = _path_headings(ab_curve)
    entry_heads = _path_headings(de_curve)
    tangent_errors = (
        _heading_error_deg(exit_heads[0], a_dir),
        _heading_error_deg(exit_heads[-1], b_dir),
        _heading_error_deg(entry_heads[0], d_dir),
        _heading_error_deg(entry_heads[-1], e_dir),
    )
    kinematics = "not_validated"
    status = STATUS_NOT_VALIDATED
    message = NOT_VALIDATED_MESSAGE
    if settings.min_turn_radius_m is not None:
        if radius + 1e-6 < float(settings.min_turn_radius_m):
            return fail(
                f"raio minimo medido {radius:.2f} m < {settings.min_turn_radius_m:.2f} m cadastrado",
                a=a, b=b, d=d, e=e,
                exit_lead_m=measured_exit, entry_lead_m=measured_entry, align_m=measured_align,
                min_radius_m=radius,
            )
        kinematics = "radius_checked"
        status = STATUS_OK
        message = ""

    return BorderEntryConnection(
        turn_id=turn_id,
        from_pass=int(from_pass.pass_id),
        to_pass=int(to_pass.pass_id),
        from_line_id=from_pass.key,
        to_line_id=to_pass.key,
        headland_line_id=ring_id,
        status=status,
        points=tuple(points),
        exit_points=tuple(ab_curve),
        transit_points=tuple(transit),
        entry_points=tuple(de_curve),
        a=a,
        b=b,
        d=d,
        e=e,
        exit_lead_m=round(measured_exit, 4),
        entry_lead_m=round(measured_entry, 4),
        align_m=round(measured_align, 4),
        min_radius_m=None if math.isinf(radius) else round(radius, 3),
        length_m=round(_polyline_length(points), 3),
        transit_length_m=round(float(transit_length), 3),
        a_station_m=round(float(a_station), 4),
        b_station_m=round(float(r_from), 4),
        d_station_m=round(float(d_station), 4),
        e_station_m=round(float(e_station), 4),
        tangent_error_a_deg=round(float(tangent_errors[0]), 4),
        tangent_error_b_deg=round(float(tangent_errors[1]), 4),
        tangent_error_d_deg=round(float(tangent_errors[2]), 4),
        tangent_error_e_deg=round(float(tangent_errors[3]), 4),
        max_transit_distance_m=round(float(max_transit_distance), 6),
        message=message,
        kinematics=kinematics,
    )


def _transition_ok(
    curve: list[Point],
    start_dir: Point,
    end_dir: Point,
    interior: Polygon | None,
    ring: LineString,
    settings: BorderEntrySettings,
) -> bool:
    if len(curve) < 3:
        return False
    heads = _path_headings(curve)
    if not heads:
        return False
    if _heading_error_deg(heads[0], start_dir) > settings.angle_tolerance_deg:
        return False
    if _heading_error_deg(heads[-1], end_dir) > settings.angle_tolerance_deg:
        return False
    if _max_heading_jump_deg(curve) > MAX_HEADING_JUMP_DEG:
        return False
    line = LineString(curve)
    if not line.is_simple:
        return False
    if interior is None:
        return not line.crosses(ring)
    allowed = interior.buffer(settings.geometry_tolerance_m)
    return bool(allowed.covers(line))


def plan_spray_border_entries(
    passes: Iterable[SprayPassInput],
    rings: Iterable[HeadlandRingInput],
    *,
    settings: BorderEntrySettings | None = None,
    u_turns_active: bool = False,
) -> BorderEntryPlan:
    """Pares consecutivos (por pass_id) usando o anel mais externo. Nao grava nada."""
    settings = settings or BorderEntrySettings()
    report: dict[str, Any] = {
        "turn_type": TURN_TYPE,
        "exit_lead_m": settings.exit_lead_m,
        "entry_lead_m": settings.entry_lead_m,
        "alignment_rule": "GEOMETRIC_SEARCH_ON_DESTINATION_PASS",
        "passes_modified": False,
        "persisted": False,
        "generator_called": False,
    }
    if u_turns_active:
        report["status"] = STATUS_BLOCKED_U_TURN
        return BorderEntryPlan(warnings=(BLOCKED_U_TURN_MESSAGE,), report=report)

    ordered = sorted(
        [item for item in passes if len(item.points) >= 2],
        key=lambda item: int(item.pass_id),
    )
    ring_input = outermost_headland_ring(rings)
    report["pass_count"] = len(ordered)
    report["headland_found"] = ring_input is not None
    if ring_input is not None:
        report["headland_offset_m"] = round(float(ring_input.offset_m), 3)
        report["headland_pass_no"] = int(ring_input.pass_no)
    if len(ordered) < 2:
        report["status"] = STATUS_NO_PASSES
        return BorderEntryPlan(warnings=("Entra e sai: menos de duas passadas.",), report=report)
    if ring_input is None:
        report["status"] = STATUS_NO_HEADLAND
        return BorderEntryPlan(warnings=("Entra e sai: passada de bordadura nao encontrada.",), report=report)

    ring = _as_line(_closed(ring_input.points))
    if ring is None:
        report["status"] = STATUS_NO_HEADLAND
        return BorderEntryPlan(warnings=("Entra e sai: geometria da bordadura invalida.",), report=report)
    interior = _interior_polygon(ring)

    connections: list[BorderEntryConnection] = []
    for first, second in zip(ordered, ordered[1:]):
        if int(second.pass_id) - int(first.pass_id) != 1:
            connections.append(
                BorderEntryConnection(
                    turn_id=f"BE{int(first.pass_id):03d}_{int(second.pass_id):03d}",
                    from_pass=int(first.pass_id),
                    to_pass=int(second.pass_id),
                    from_line_id=first.key,
                    to_line_id=second.key,
                    headland_line_id=ring_input.line_id,
                    status=STATUS_INFEASIBLE,
                    points=(),
                    message=f"{INFEASIBLE_MESSAGE}: passadas nao adjacentes",
                )
            )
            continue
        connections.append(
            _connection(first, second, ring, ring_input.line_id, settings, interior)
        )

    accepted = tuple(
        item for item in connections if item.status in (STATUS_OK, STATUS_NOT_VALIDATED)
    )
    rejected = tuple(item for item in connections if item.status == STATUS_INFEASIBLE)
    report.update({
        "status": STATUS_OK if accepted and not rejected else (
            STATUS_INFEASIBLE if not accepted else "PARTIAL"
        ),
        "pair_count": len(connections),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "possible_count": len(ordered) - 1,
        "connections": [item.diagnostic() for item in connections],
    })
    warnings = tuple(item.message for item in connections if item.message)
    return BorderEntryPlan(
        connections=tuple(connections),
        rejected=rejected,
        warnings=warnings,
        report=report,
    )


def border_entry_summary(plan: BorderEntryPlan | None) -> str:
    if plan is None:
        return ""
    status = plan.report.get("status")
    if status == STATUS_BLOCKED_U_TURN:
        return BLOCKED_U_TURN_MESSAGE
    passes = plan.report.get("pass_count", 0)
    found = "encontrada" if plan.report.get("headland_found") else "ausente"
    possible = plan.report.get("possible_count", 0)
    accepted = plan.report.get("accepted_count", 0)
    rejected = plan.report.get("rejected_count", 0)
    text = f"Passadas: {passes} | Bordadura: {found} | Conexoes possiveis: {possible}"
    if accepted or rejected:
        text += f" | Ok: {accepted} | Inviaveis: {rejected}"
    if plan.accepted:
        item = plan.accepted[0]
        text += (
            f"\n{item.turn_id} [{TURN_TYPE}] "
            f"A={item.a_station_m:.2f} m | B={item.b_station_m:.2f} m | "
            f"D={item.d_station_m:.2f} m | E={item.e_station_m:.2f} m | "
            f"B-D real={item.transit_length_m:.2f} m"
        )
    return text


def border_entry_connection_summary(item: BorderEntryConnection | None) -> str:
    if item is None:
        return "Selecione uma conexao para inspecionar."

    def point_text(name: str, point: Point | None, station: float | None) -> str:
        if point is None or station is None:
            return f"{name}=indisponivel"
        return f"{name}=({point[0]:.3f}, {point[1]:.3f}) @ {station:.2f} m"

    errors = (
        item.tangent_error_a_deg,
        item.tangent_error_b_deg,
        item.tangent_error_d_deg,
        item.tangent_error_e_deg,
    )
    tangent = max(value for value in errors if value is not None) if any(
        value is not None for value in errors
    ) else None
    tangent_text = "n/d" if tangent is None else f"{tangent:.3f} graus"
    distance_text = (
        "n/d" if item.max_transit_distance_m is None
        else f"{item.max_transit_distance_m:.4f} m"
    )
    return (
        f"{item.turn_id}: {item.from_line_id} -> {item.to_line_id} | "
        f"bordadura={item.headland_line_id or 'sem ID'} | status={item.status}\n"
        f"{point_text('A', item.a, item.a_station_m)} | "
        f"{point_text('B', item.b, item.b_station_m)}\n"
        f"{point_text('D', item.d, item.d_station_m)} | "
        f"{point_text('E', item.e, item.e_station_m)}\n"
        f"saida={item.exit_lead_m:.2f} m em {item.from_line_id} | "
        f"antecipacao={item.entry_lead_m:.2f} m em B1 | "
        f"alinhamento efetivo={item.align_m:.2f} m em {item.to_line_id}\n"
        f"B-D={item.transit_length_m:.3f} m | erro tangente max={tangent_text} | "
        f"afastamento max da bordadura={distance_text}"
    )


HEADLAND_TURN_FIELD_NAMES = tuple(name for name, _kind in HEADLAND_TURN_FIELDS)
