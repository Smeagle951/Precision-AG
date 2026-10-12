# -*- coding: utf-8 -*-
"""Manobras de cabeceira entre passadas EXISTENTES (motor de conexao).

Nao gera, corta, estende nem renumera passadas: le a identidade e a geometria
ja produzidas pelo FortSmart e devolve somente as curvas de ligacao
(arco - reta - arco tangentes, raio >= minimo). O que nao couber com seguranca
geometrica sai marcado como inviavel, sem curva "so para fechar o desenho".
Todas as distancias sao em metros num CRS projetado.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Iterable, NamedTuple

from shapely.geometry import LineString
from shapely.prepared import prep

from .planting_line_cut_engine import spatial_line_numbers

Point = tuple[float, float]


class HeadlandTurnError(ValueError):
    """Entrada invalida para o motor de manobras."""


class TurnMode(str, Enum):
    AUTO = "AUTO"
    U_TURN = "U_TURN"
    TEARDROP = "TEARDROP"
    SKIP_PASS = "SKIP_PASS"


IMPLEMENTED_TURN_MODES = (TurnMode.AUTO, TurnMode.U_TURN)
AUTO_CANDIDATES = (TurnMode.U_TURN,)


class PassClass(str, Enum):
    MAIN = "MAIN"
    BORDER = "BORDER"


STATUS_OK = "OK"
STATUS_WARNING_CROSSING = "WARNING_CROSSING"
STATUS_INFEASIBLE_RADIUS = "INFEASIBLE_RADIUS"
STATUS_OBSTACLE_CONFLICT = "OBSTACLE_CONFLICT"
STATUS_DIRECTION_CONFLICT = "DIRECTION_CONFLICT"

HEADLAND_TURN_FIELDS = (
    ("turn_id", "string"),
    ("from_pass", "int"),
    ("to_pass", "int"),
    ("turn_type", "string"),
    ("radius_m", "double"),
    ("length_m", "double"),
    ("status", "string"),
    ("sequence", "int"),
    ("source_layer", "string"),
    ("simulation_only", "bool"),
    ("pass_spacing_m", "double"),
    ("from_line_id", "string"),
    ("to_line_id", "string"),
    ("message", "string"),
)

BORDER_ROLES = {"FIELD_HEADLAND_PATH", "HEADLAND_WORK_PATH", "HEADLAND_PATH"}
_BORDER_LABEL = re.compile(r"^B\d+$", re.IGNORECASE)
DIRECTION_FIELDS = ("direction", "sentido", "travel_direction", "dir")
_FORWARD = {"forward", "fwd", "ab", "a->b", "a-b", "ida", "1", "+1", "normal"}
_REVERSE = {"reverse", "rev", "ba", "b->a", "b-a", "volta", "-1", "reversed", "invertido"}
_TRUE = {"true", "t", "1", "sim", "yes", "y"}
_FALSE = {"false", "f", "0", "nao", "não", "no", "n"}
# Par de extremos compativel: sentidos de saida/entrada devem estar a mais de 120 graus.
OPPOSITE_HEADING_DOT = -0.5


# --------------------------------------------------------------- vetores ----
def _sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1])


def _add(a: Point, b: Point) -> Point:
    return (a[0] + b[0], a[1] + b[1])


def _mul(a: Point, k: float) -> Point:
    return (a[0] * k, a[1] * k)


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _norm(a: Point) -> float:
    return math.hypot(a[0], a[1])


def _unit(a: Point) -> Point | None:
    length = _norm(a)
    return None if length < 1e-12 else (a[0] / length, a[1] / length)


def _left(a: Point) -> Point:
    return (-a[1], a[0])


def _rotate(v: Point, angle: float) -> Point:
    c, s = math.cos(angle), math.sin(angle)
    return (v[0] * c - v[1] * s, v[0] * s + v[1] * c)


def _heading_error_deg(a: Point, b: Point) -> float:
    return abs(math.degrees(math.atan2(_cross(a, b), _dot(a, b))))


# ------------------------------------------------------------ atributos ----
def _clean(value: Any) -> Any:
    if value is None:
        return None
    text = str(value).strip()
    return None if text == "" or text.upper() in {"NULL", "NONE"} else value


def _lowered(attributes: dict[str, Any] | None) -> dict[str, Any]:
    return {str(key).casefold(): value for key, value in (attributes or {}).items()}


def classify_pass(attributes: dict[str, Any] | None) -> PassClass:
    """MAIN ou BORDER; bordadura nunca entra no zig-zag das passadas principais."""
    values = _lowered(attributes)
    explicit = _clean(values.get("pass_class"))
    if explicit is not None and str(explicit).strip().upper() in PassClass.__members__:
        return PassClass(str(explicit).strip().upper())
    role = str(_clean(values.get("fortsmart_role")) or "").strip().upper()
    if role in BORDER_ROLES:
        return PassClass.BORDER
    for key in ("label", "name", "nome", "role"):
        value = _clean(values.get(key))
        if value is None:
            continue
        text = str(value).strip()
        if _BORDER_LABEL.match(text) or text.upper() in {"BORDER", "BORDADURA", "HEADLAND"}:
            return PassClass.BORDER
    return PassClass.MAIN


def direction_from_attributes(attributes: dict[str, Any] | None) -> int | None:
    """+1 = percorre no sentido digitalizado, -1 = inverso, None = sem atributo."""
    values = _lowered(attributes)
    for key in DIRECTION_FIELDS:
        value = _clean(values.get(key))
        if value is None:
            continue
        text = str(value).strip().casefold()
        if text in _FORWARD:
            return 1
        if text in _REVERSE:
            return -1
    flag = _clean(values.get("reversed"))
    if flag is not None:
        text = str(flag).strip().casefold()
        if text in _TRUE:
            return -1
        if text in _FALSE:
            return 1
    return None


# ------------------------------------------------------ identidade ----
@dataclass(frozen=True)
class PassRecord:
    """Uma feicao (ou parte) lida da camada de passadas, sem alteracao."""

    points: tuple[Point, ...]
    line_id: str | None = None
    number: int | None = None
    segment_index: int | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LogicalPass:
    """PASS_IDENTITY separada de GEOMETRY_SEGMENTS: 1 inicio e 1 fim logicos."""

    key: str
    number: int
    segments: tuple[tuple[Point, ...], ...]
    pass_class: PassClass = PassClass.MAIN
    direction: int | None = None

    @property
    def start(self) -> Point:
        return self.segments[0][0]

    @property
    def end(self) -> Point:
        return self.segments[-1][-1]

    @property
    def heading(self) -> Point:
        return _unit(_sub(self.end, self.start)) or (1.0, 0.0)


def _start_heading(points: tuple[Point, ...], min_length_m: float = 0.05) -> Point:
    for point in points[1:]:
        unit = _unit(_sub(point, points[0]))
        if unit is not None and _norm(_sub(point, points[0])) >= min_length_m:
            return unit
    return _unit(_sub(points[-1], points[0])) or (1.0, 0.0)


def _end_heading(points: tuple[Point, ...], min_length_m: float = 0.05) -> Point:
    for point in reversed(points[:-1]):
        unit = _unit(_sub(points[-1], point))
        if unit is not None and _norm(_sub(points[-1], point)) >= min_length_m:
            return unit
    return _unit(_sub(points[-1], points[0])) or (1.0, 0.0)


def build_logical_passes(records: Iterable[PassRecord]) -> tuple[list[LogicalPass], str]:
    """Agrupa trechos pela identidade (line_id > line_number); nunca renumera.

    Trechos de uma linha cortada por obstaculo continuam sendo a mesma linha.
    Sem numeracao na camada, cria uma unica vez pela ordem transversal.
    """
    groups: dict[str, list[PassRecord]] = {}
    for index, record in enumerate(records):
        points = tuple((float(x), float(y)) for x, y in record.points)
        if len(points) < 2:
            continue
        record = PassRecord(points, record.line_id, record.number, record.segment_index, record.attributes)
        if record.line_id not in (None, ""):
            key = str(record.line_id)
        elif record.number is not None:
            key = f"N{record.number}"
        else:
            key = f"F{index}"
        groups.setdefault(key, []).append(record)
    if not groups:
        return [], "none"

    numbers: dict[str, int | None] = {
        key: next((r.number for r in items if r.number is not None), None) for key, items in groups.items()
    }
    missing = [key for key, number in numbers.items() if number is None]
    source = "attribute"
    if missing:
        spatial = spatial_line_numbers(
            {key: tuple(p for r in groups[key] for p in r.points) for key in missing}
        )
        base = max((n for n in numbers.values() if n is not None), default=0)
        for key in missing:
            numbers[key] = base + spatial[key]
        source = "spatial_order" if len(missing) == len(groups) else "attribute+spatial_order"

    passes = []
    for key, items in groups.items():
        if all(r.segment_index is not None for r in items):
            ordered = sorted(items, key=lambda r: r.segment_index)
        else:
            longest = max(items, key=lambda r: _norm(_sub(r.points[-1], r.points[0])))
            axis = _unit(_sub(longest.points[-1], longest.points[0])) or (1.0, 0.0)
            ordered = sorted(items, key=lambda r: _dot(r.points[0], axis))
        pass_class = (
            PassClass.BORDER
            if any(classify_pass(r.attributes) is PassClass.BORDER for r in items)
            else PassClass.MAIN
        )
        direction = next(
            (d for d in (direction_from_attributes(r.attributes) for r in items) if d is not None), None
        )
        passes.append(
            LogicalPass(key, int(numbers[key]), tuple(r.points for r in ordered), pass_class, direction)
        )
    return passes, source


# ------------------------------------------------------------ sentido ----
@dataclass(frozen=True)
class OperationalPass:
    """Passada com sentido operacional; a geometria original nao e invertida."""

    logical: LogicalPass
    reversed: bool = False

    @property
    def number(self) -> int:
        return self.logical.number

    @property
    def key(self) -> str:
        return self.logical.key


class Endpoint(NamedTuple):
    point: Point
    heading: Point


def get_operational_start(operational: OperationalPass) -> Endpoint:
    """Onde a maquina ENTRA na passada e o sentido de deslocamento nesse ponto."""
    logical = operational.logical
    if operational.reversed:
        return Endpoint(logical.end, _mul(_end_heading(logical.segments[-1]), -1.0))
    return Endpoint(logical.start, _start_heading(logical.segments[0]))


def get_operational_end(operational: OperationalPass) -> Endpoint:
    """Onde a maquina SAI da passada e o sentido de deslocamento nesse ponto."""
    logical = operational.logical
    if operational.reversed:
        return Endpoint(logical.start, _mul(_start_heading(logical.segments[0]), -1.0))
    return Endpoint(logical.end, _end_heading(logical.segments[-1]))


def resolve_operational_directions(
    passes: list[LogicalPass],
    *,
    respect_direction: bool = True,
    ab_heading: Point | None = None,
) -> tuple[list[OperationalPass], str]:
    """Prioridade: atributo > orientacao do gerador > linha AB > zig-zag."""
    if not passes:
        return [], "none"
    if respect_direction and all(p.direction is not None for p in passes):
        return [OperationalPass(p, p.direction < 0) for p in passes], "attribute"
    headings = [p.heading for p in passes]
    if respect_direction and len(passes) > 1 and all(
        _dot(a, b) < 0 for a, b in zip(headings, headings[1:])
    ):
        return [OperationalPass(p, False) for p in passes], "geometry"
    reference, source = headings[0], "zigzag"
    ab_unit = _unit(ab_heading) if ab_heading is not None else None
    if ab_unit is not None:
        reference, source = ab_unit, "ab_line"
    operational = []
    for index, (logical, heading) in enumerate(zip(passes, headings)):
        desired = reference if index % 2 == 0 else _mul(reference, -1.0)
        operational.append(OperationalPass(logical, _dot(heading, desired) < 0))
    return operational, source


def endpoint_pairs(from_pass: OperationalPass, to_pass: OperationalPass) -> list[dict[str, Any]]:
    """Os quatro pares de extremos possiveis, medidos no eixo da passada de origem."""
    axis = from_pass.logical.heading
    ends_from = {"start": from_pass.logical.start, "end": from_pass.logical.end}
    ends_to = {"start": to_pass.logical.start, "end": to_pass.logical.end}
    pairs = []
    for from_end, from_point in ends_from.items():
        for to_end, to_point in ends_to.items():
            delta = _sub(to_point, from_point)
            pairs.append({
                "from_end": from_end,
                "to_end": to_end,
                "along_m": abs(_dot(delta, axis)),
                "lateral_m": abs(_cross(axis, delta)),
                "distance_m": _norm(delta),
            })
    return pairs


def check_connection(
    from_pass: OperationalPass, to_pass: OperationalPass, *, endpoint_tolerance_m: float = 0.05
) -> str | None:
    """None se saida/entrada operacionais formam um par valido de cabeceira."""
    exit_point = get_operational_end(from_pass)
    entry_point = get_operational_start(to_pass)
    if _dot(exit_point.heading, entry_point.heading) > OPPOSITE_HEADING_DOT:
        return "sentidos de saída e entrada não são opostos"
    from_end = "start" if from_pass.reversed else "end"
    to_end = "end" if to_pass.reversed else "start"
    by_pair = {(p["from_end"], p["to_end"]): p for p in endpoint_pairs(from_pass, to_pass)}
    chosen = by_pair[(from_end, to_end)]
    other = by_pair[(from_end, "start" if to_end == "end" else "end")]
    if chosen["along_m"] > other["along_m"] + endpoint_tolerance_m:
        return "saída e entrada ficam em cabeceiras opostas"
    return None


# ------------------------------------------------------------ geometria ----
def _arc(center: Point, start: Point, angle: float, sign: int, step: float) -> list[Point]:
    if angle <= 1e-12:
        return [start]
    count = max(1, math.ceil(angle / step))
    radial = _sub(start, center)
    return [_add(center, _rotate(radial, sign * angle * k / count)) for k in range(count + 1)]


def _turn_angle(a: Point, b: Point, sign: int) -> float:
    angle = math.atan2(_cross(a, b), _dot(a, b)) * sign
    angle %= 2.0 * math.pi
    return 0.0 if angle > 2.0 * math.pi - 1e-9 else angle


def u_turn_path(
    start: Point,
    start_heading: Point,
    end: Point,
    end_heading: Point,
    radius_m: float,
    *,
    turn_left: bool,
    arc_step_deg: float = 2.0,
) -> tuple[tuple[Point, ...], float, float] | None:
    """Arco - reta - arco no mesmo sentido de giro (C1), ou None se virar laco.

    Chega em ``end`` com ``end_heading``; os dois arcos tem exatamente ``radius_m``.
    """
    sign = 1 if turn_left else -1
    h1 = _unit(start_heading)
    h2 = _unit(end_heading)
    if h1 is None or h2 is None or radius_m <= 0:
        return None
    c1 = _add(start, _mul(_left(h1), sign * radius_m))
    c2 = _add(end, _mul(_left(h2), sign * radius_m))
    step = math.radians(arc_step_deg)
    link = _sub(c2, c1)
    if _norm(link) < 1e-9:
        theta1, theta2 = _turn_angle(h1, h2, sign), 0.0
        points = _arc(c1, start, theta1, sign, step)
    else:
        u = _unit(link)
        theta1 = _turn_angle(h1, u, sign)
        theta2 = _turn_angle(u, h2, sign)
        tangent_2 = _sub(c2, _mul(_left(u), sign * radius_m))
        first = _arc(c1, start, theta1, sign, step)
        second = _arc(c2, tangent_2, theta2, sign, step)
        points = first + second if _norm(_sub(first[-1], second[0])) > 1e-9 else first + second[1:]
    if theta1 + theta2 > 1.5 * math.pi:
        return None
    return tuple(points), theta1, theta2


def polyline_length(points: Iterable[Point]) -> float:
    items = list(points)
    return sum(_norm(_sub(b, a)) for a, b in zip(items, items[1:]))


def tangent_errors_deg(points: tuple[Point, ...], start_heading: Point, end_heading: Point) -> tuple[float, float]:
    first = _start_heading(points, 1e-9)
    last = _end_heading(points, 1e-9)
    return _heading_error_deg(first, start_heading), _heading_error_deg(last, end_heading)


# ------------------------------------------------------------- manobra ----
@dataclass(frozen=True)
class TurnSettings:
    min_turn_radius_m: float
    mode: TurnMode = TurnMode.AUTO
    keep_inside: bool = True
    respect_direction: bool = True
    include_border: bool = False
    endpoint_tolerance_m: float = 0.05
    angle_tolerance_deg: float = 2.0
    geometry_tolerance_m: float = 0.05
    arc_step_deg: float = 2.0

    def validate(self) -> None:
        if not self.min_turn_radius_m or self.min_turn_radius_m <= 0:
            raise HeadlandTurnError("Informe o raio mínimo de manobra da máquina (m).")
        if self.mode not in IMPLEMENTED_TURN_MODES:
            raise HeadlandTurnError(f"{self.mode.value} ainda não implementado; use AUTO ou U_TURN.")
        if self.arc_step_deg / 2.0 > self.angle_tolerance_deg:
            raise HeadlandTurnError("Passo do arco maior que a tolerância angular.")


@dataclass(frozen=True)
class HeadlandTurn:
    turn_id: str
    from_pass: int
    to_pass: int
    from_line_id: str
    to_line_id: str
    turn_type: str
    radius_m: float | None
    length_m: float
    status: str
    sequence: int
    points: tuple[Point, ...]
    pass_spacing_m: float
    message: str = ""

    def attributes(self, source_layer: str) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "from_pass": self.from_pass,
            "to_pass": self.to_pass,
            "turn_type": self.turn_type,
            "radius_m": None if self.radius_m is None else round(self.radius_m, 3),
            "length_m": round(self.length_m, 3),
            "status": self.status,
            "sequence": self.sequence,
            "source_layer": source_layer,
            "simulation_only": True,
            "pass_spacing_m": round(self.pass_spacing_m, 3),
            "from_line_id": self.from_line_id,
            "to_line_id": self.to_line_id,
            "message": self.message,
        }


@dataclass(frozen=True)
class HeadlandTurnPlan:
    turns: list[HeadlandTurn]
    report: dict[str, Any]


def turn_id_for(from_number: int, to_number: int) -> str:
    def fmt(number: int) -> str:
        return f"{number:03d}" if number >= 0 else f"M{abs(number):03d}"

    return f"T{fmt(from_number)}_{fmt(to_number)}"


def _radius_candidates(r_max: float, r_min: float) -> list[float]:
    if r_max - r_min < 0.01:
        return [max(r_max, r_min)]
    return [r_max - k * (r_max - r_min) / 4.0 for k in range(5)]


def connect_passes(
    from_pass: OperationalPass,
    to_pass: OperationalPass,
    sequence: int,
    settings: TurnSettings,
    *,
    turning_area: Any = None,
    obstacles: Any = None,
) -> HeadlandTurn:
    """U-turn tangente entre o fim operacional de uma passada e o inicio da proxima."""
    exit_point = get_operational_end(from_pass)
    entry_point = get_operational_start(to_pass)
    delta = _sub(entry_point.point, exit_point.point)
    spacing = abs(_cross(exit_point.heading, delta))

    def result(status, points=(), radius=None, message=""):
        return HeadlandTurn(
            turn_id=turn_id_for(from_pass.number, to_pass.number),
            from_pass=from_pass.number,
            to_pass=to_pass.number,
            from_line_id=from_pass.key,
            to_line_id=to_pass.key,
            turn_type=TurnMode.U_TURN.value,
            radius_m=radius,
            length_m=polyline_length(points),
            status=status,
            sequence=sequence,
            points=tuple(points),
            pass_spacing_m=spacing,
            message=message,
        )

    problem = check_connection(from_pass, to_pass, endpoint_tolerance_m=settings.endpoint_tolerance_m)
    if problem:
        return result(STATUS_DIRECTION_CONFLICT, message=problem)

    r_min = settings.min_turn_radius_m
    r_max = spacing / 2.0
    if r_max + settings.geometry_tolerance_m < r_min:
        return result(
            STATUS_INFEASIBLE_RADIUS,
            message=(
                f"espaçamento {spacing:.2f} m permite U com raio até {r_max:.2f} m "
                f"(< mínimo {r_min:.2f} m)"
            ),
        )

    area = prep(turning_area.buffer(settings.geometry_tolerance_m)) \
        if settings.keep_inside and turning_area is not None and not turning_area.is_empty else None
    blocked = prep(obstacles) if obstacles is not None and not obstacles.is_empty else None
    turn_left = _cross(exit_point.heading, delta) > 0
    inside_but_blocked = None
    outside_candidate = None
    for radius in _radius_candidates(r_max, r_min):
        radius = max(radius, r_min)
        built = u_turn_path(
            exit_point.point, exit_point.heading, entry_point.point, entry_point.heading, radius,
            turn_left=turn_left, arc_step_deg=settings.arc_step_deg,
        )
        if built is None:
            continue
        points = built[0]
        if _norm(_sub(points[-1], entry_point.point)) > settings.endpoint_tolerance_m:
            continue
        points = (exit_point.point, *points[1:-1], entry_point.point)
        start_error, end_error = tangent_errors_deg(points, exit_point.heading, entry_point.heading)
        if max(start_error, end_error) > settings.angle_tolerance_deg:
            continue
        line = LineString(points)
        if area is not None and not area.covers(line):
            outside_candidate = outside_candidate or (points, radius)
            continue
        if blocked is not None and blocked.intersects(line):
            inside_but_blocked = inside_but_blocked or (points, radius)
            continue
        return result(STATUS_OK, points, radius)
    if inside_but_blocked is not None:
        points, radius = inside_but_blocked
        return result(STATUS_OBSTACLE_CONFLICT, points, radius, "curva cruza obstáculo/zona de segurança")
    if outside_candidate is not None:
        return result(
            STATUS_INFEASIBLE_RADIUS,
            message=(
                f"nenhum raio entre {r_min:.2f} e {max(r_max, r_min):.2f} m cabe na área de manobra "
                "sem alterar as passadas"
            ),
        )
    return result(STATUS_INFEASIBLE_RADIUS, message="sem U tangente com o raio mínimo")


def mark_crossings(turns: list[HeadlandTurn]) -> list[HeadlandTurn]:
    """Manobras aceitas que se cruzam viram WARNING_CROSSING (nao sao escondidas)."""
    lines = {
        index: LineString(turn.points)
        for index, turn in enumerate(turns)
        if turn.status == STATUS_OK and len(turn.points) >= 2
    }
    crossed: dict[int, list[str]] = {}
    keys = sorted(lines)
    for position, i in enumerate(keys):
        for j in keys[position + 1:]:
            a, b = lines[i], lines[j]
            if a.crosses(b) or a.overlaps(b):
                crossed.setdefault(i, []).append(turns[j].turn_id)
                crossed.setdefault(j, []).append(turns[i].turn_id)
    output = list(turns)
    for index, others in crossed.items():
        output[index] = replace(
            turns[index], status=STATUS_WARNING_CROSSING, message="cruza " + ", ".join(others)
        )
    return output


def plan_headland_turns(
    passes: list[LogicalPass],
    settings: TurnSettings,
    *,
    turning_area: Any = None,
    obstacles: Any = None,
    ab_heading: Point | None = None,
    source_layer: str = "",
) -> HeadlandTurnPlan:
    """Uma manobra por par consecutivo da sequencia MAIN (N passadas -> N-1 manobras)."""
    settings.validate()
    selected = [p for p in passes if settings.include_border or p.pass_class is PassClass.MAIN]
    ordered = sorted(selected, key=lambda p: (p.number, p.key))
    operational, direction_source = resolve_operational_directions(
        ordered, respect_direction=settings.respect_direction, ab_heading=ab_heading
    )
    turns = [
        connect_passes(a, b, sequence, settings, turning_area=turning_area, obstacles=obstacles)
        for sequence, (a, b) in enumerate(zip(operational, operational[1:]), start=1)
    ]
    turns = mark_crossings(turns)
    counts: dict[str, int] = {}
    for turn in turns:
        counts[turn.status] = counts.get(turn.status, 0) + 1
    return HeadlandTurnPlan(
        turns=turns,
        report={
            "source_layer": source_layer,
            "turn_mode": settings.mode.value,
            "candidates": [mode.value for mode in AUTO_CANDIDATES],
            "min_turn_radius_m": settings.min_turn_radius_m,
            "keep_inside": settings.keep_inside,
            "respect_direction": settings.respect_direction,
            "turning_area_used": turning_area is not None and settings.keep_inside,
            "obstacles_checked": obstacles is not None,
            "direction_source": direction_source,
            "pass_count": len(ordered),
            "border_passes_ignored": len(passes) - len(selected),
            "turn_count": len(turns),
            "status_counts": counts,
            "tolerances": {
                "endpoint_tolerance_m": settings.endpoint_tolerance_m,
                "angle_tolerance_deg": settings.angle_tolerance_deg,
                "geometry_tolerance_m": settings.geometry_tolerance_m,
            },
            "passes_modified": False,
            "generator_called": False,
        },
    )
