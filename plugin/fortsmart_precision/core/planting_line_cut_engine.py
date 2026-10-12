# -*- coding: utf-8 -*-
"""Corte de linhas por zonas de exclusao, preservando a trajetoria original."""

from __future__ import annotations

from dataclasses import dataclass

from .line_geometry import (
    MultiPolygon,
    Point,
    Segment,
    point_in_multipolygon,
    segment_samples,
)
from .preview_layer_names import match_preview_layer_name


class PlantingLineCutError(ValueError):
    """Configuracao invalida para corte de linhas."""


def is_obstacle_layer_name(name: str) -> bool:
    """Reconhece nomes comuns, inclusive Flag{UUID}, sem depender do UUID."""
    normalized = "".join(
        character for character in str(name or "").casefold() if character.isalnum()
    )
    return normalized.startswith(("flag", "obstacle", "obst", "point", "pnt", "poste"))


FIELD_BOUNDARY_PREFIXES = ("boundary", "talhao", "contorno")
SAME_LAYER_MESSAGE = "A camada de obstáculos não pode ser a mesma camada do talhão."
BOUNDARY_AS_OBSTACLE_MESSAGE = "Contorno do talhão (Boundary) não pode ser usado como obstáculo."
OFFSET_MISSING_MESSAGE = "Informe o offset longitudinal da última linha ativa."
GEOMETRY_INCOMPLETE = "GEOMETRY_INCOMPLETE"
READY = "READY"


def _normalized_name(name: str) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    return "".join(character for character in text.casefold() if character.isalnum())


def is_field_boundary_layer_name(name: str) -> bool:
    return _normalized_name(name).startswith(FIELD_BOUNDARY_PREFIXES)


def obstacle_layer_priority(name: str) -> int | None:
    """Prioridade de auto-deteccao: Flag{UUID}, Flag, Poste, Obstacle/Obstaculo.

    Boundary nunca e candidato; None = camada nao e de obstaculo.
    """
    raw = str(name or "").strip()
    normalized = _normalized_name(raw)
    if not normalized or is_field_boundary_layer_name(raw) or is_safety_zone_layer_name(raw):
        return None
    if normalized.startswith("flag") and "{" in raw and "}" in raw:
        return 0
    if normalized.startswith("flag"):
        return 1
    if normalized.startswith("poste"):
        return 2
    if normalized.startswith(("obstacle", "obstaculo")):
        return 3
    return None


def validate_obstacle_layer_choice(
    *,
    obstacle_layer_id: str | None,
    obstacle_layer_name: str,
    field_layer_id: str | None,
    geometry_kind: str,
) -> str | None:
    """Mensagem de bloqueio, ou None se a camada de obstaculos for aceitavel.

    geometry_kind: "point", "line" ou "polygon". Poligono so e aceito quando
    nao e o talhao; o Boundary nunca vira poste.
    """
    if not obstacle_layer_id:
        return "Selecione a camada de obstáculos."
    if field_layer_id and obstacle_layer_id == field_layer_id:
        return SAME_LAYER_MESSAGE
    if is_field_boundary_layer_name(obstacle_layer_name):
        return BOUNDARY_AS_OBSTACLE_MESSAGE
    if is_safety_zone_layer_name(obstacle_layer_name):
        return "Selecione os obstáculos originais, não uma zona de corte já expandida."
    if geometry_kind not in ("point", "line", "polygon"):
        return "Geometria de obstáculo não suportada."
    return None


SAME_LINES_AND_OBSTACLES_MESSAGE = "A camada de linhas não pode ser a mesma camada de obstáculos."


def validate_line_layer_choice(
    *, line_layer_id: str | None, obstacle_layer_id: str | None, line_layer_name: str = ""
) -> str | None:
    """As linhas cortadas sao sempre as linhas ja geradas, nunca os proprios obstaculos."""
    if not line_layer_id:
        return "Selecione a camada de linhas geradas."
    if obstacle_layer_id and line_layer_id == obstacle_layer_id:
        return SAME_LINES_AND_OBSTACLES_MESSAGE
    if is_field_boundary_layer_name(line_layer_name):
        return "O contorno do talhão não é uma camada de linhas geradas."
    return None


def cut_preview_readiness(*, longitudinal: bool, working_offset_m: float | None) -> tuple[str, str]:
    """GEOMETRY_INCOMPLETE bloqueia preview/salvar so nas estrategias longitudinais."""
    if longitudinal and working_offset_m is None:
        return GEOMETRY_INCOMPLETE, OFFSET_MISSING_MESSAGE
    return READY, ""


def classify_transversal_clearance(
    *,
    lateral_distance_m: float,
    implement_width_m: float,
    obstacle_radius_m: float = 0.0,
    safety_margin_m: float = 0.0,
) -> str:
    """Analise transversal: a meia largura da barra, nao a linha central, decide."""
    if implement_width_m <= 0:
        raise PlantingLineCutError("A largura do implemento deve ser maior que zero.")
    if obstacle_radius_m < 0 or safety_margin_m < 0:
        raise PlantingLineCutError("Raio e margem nao podem ser negativos.")
    reach = implement_width_m / 2.0 + obstacle_radius_m + safety_margin_m
    return "CONFLICT" if abs(lateral_distance_m) < reach else "CLEAR"


def machine_schematic_layout(
    *, working_offset_m: float | None, work_width_m: float, width_px: float, height_px: float
) -> dict[str, object]:
    """Coordenadas do desenho do conjunto (sentido de deslocamento para cima).

    Offset negativo = barra abaixo (atras) do ponto GNSS; positivo = acima.
    """
    margin = 0.12 * height_px
    center_x = width_px / 2.0
    usable = height_px - 2.0 * margin
    bar_px = min(width_px * 0.8, max(width_px * 0.25, width_px * 0.8 * min(1.0, work_width_m / 40.0)))
    if working_offset_m is None:
        return {
            "complete": False,
            "gnss": (center_x, height_px / 2.0),
            "bar": None,
            "bar_half_px": bar_px / 2.0,
            "position": "unknown",
        }
    if working_offset_m < 0:
        gnss_y, bar_y, position = margin, margin + usable, "behind"
    elif working_offset_m > 0:
        gnss_y, bar_y, position = margin + usable, margin, "ahead"
    else:
        gnss_y = bar_y = height_px / 2.0
        position = "aligned"
    return {
        "complete": True,
        "gnss": (center_x, gnss_y),
        "bar": (center_x, bar_y),
        "bar_half_px": bar_px / 2.0,
        "position": position,
    }


def is_safety_zone_layer_name(name: str) -> bool:
    """Zonas ja expandidas nao podem ser usadas como obstaculo (buffer duplo)."""
    text = str(name or "").strip()
    if text.casefold().endswith(" - zona de corte"):
        return True
    return any(
        match_preview_layer_name(text, short)
        for short in ("10_Zonas_Seguranca", "11_Desvios_Obstaculos")
    )


def derived_cut_layer_names(
    source_line_name: str, obstacle_layer_name: str
) -> tuple[str, str]:
    """Cria nomes derivados sem alterar nem empilhar sufixos nas fontes."""
    return (
        _derived_layer_name(source_line_name, "corte", "linhas"),
        _derived_layer_name(obstacle_layer_name, "zona de corte", "obstaculos"),
    )


def _derived_layer_name(source_name: str, suffix: str, fallback: str) -> str:
    base = str(source_name or "").strip() or fallback
    marker = f" - {suffix}"
    return base if base.casefold().endswith(marker.casefold()) else f"{base}{marker}"


@dataclass(frozen=True)
class SafeLineSegment:
    source_id: str
    segment_id: str
    path_points: tuple[Point, ...]
    obstacle_cut: bool
    obstacle_count: int

    @property
    def segment(self) -> Segment:
        return Segment(self.path_points[0], self.path_points[-1])


def calculate_safety_radius(
    *,
    method: str,
    manual_radius_m: float = 0.0,
    implement_width_m: float = 0.0,
    safety_margin_m: float = 0.0,
    obstacle_radius_m: float = 0.0,
) -> float:
    """Resolve o raio: manual ou meia largura + raio fisico do obstaculo + margem."""
    if safety_margin_m < 0:
        raise PlantingLineCutError("A margem de seguranca nao pode ser negativa.")
    if obstacle_radius_m < 0:
        raise PlantingLineCutError("O raio fisico do obstaculo nao pode ser negativo.")
    if method == "manual":
        if manual_radius_m <= 0:
            raise PlantingLineCutError("O raio manual deve ser maior que zero.")
        return manual_radius_m
    if method == "half_width_margin":
        if implement_width_m <= 0:
            raise PlantingLineCutError("A largura do implemento deve ser maior que zero.")
        return implement_width_m / 2.0 + obstacle_radius_m + safety_margin_m
    raise PlantingLineCutError(f"Metodo de distancia desconhecido: {method}")


def cut_polyline_by_zones(
    points: tuple[Point, ...] | list[Point],
    exclusion_zones: MultiPolygon,
    *,
    source_id: str,
    obstacle_count: int = 0,
    minimum_length_m: float = 0.05,
    densify_m: float = 0.10,
) -> list[SafeLineSegment]:
    """Remove apenas trechos dentro das zonas e conserva os trechos externos."""
    path = tuple(points)
    if len(path) < 2:
        raise PlantingLineCutError("A linha precisa ter ao menos dois vertices.")
    if minimum_length_m < 0 or densify_m <= 0:
        raise PlantingLineCutError("Tolerancias de corte invalidas.")

    if not exclusion_zones:
        return [
            SafeLineSegment(
                source_id=source_id,
                segment_id=f"{source_id}_S01",
                path_points=path,
                obstacle_cut=False,
                obstacle_count=0,
            )
        ]

    inside, outside = _split_polyline_precisely(path, exclusion_zones, densify_m)
    if not inside:
        return [
            SafeLineSegment(
                source_id=source_id,
                segment_id=f"{source_id}_S01",
                path_points=path,
                obstacle_cut=False,
                obstacle_count=0,
            )
        ]
    valid = [tuple(chunk) for chunk in outside if _path_length(chunk) >= minimum_length_m]
    was_cut = bool(inside)
    return [
        SafeLineSegment(
            source_id=source_id,
            segment_id=f"{source_id}_S{index:02d}",
            path_points=chunk,
            obstacle_cut=was_cut,
            obstacle_count=obstacle_count if was_cut else 0,
        )
        for index, chunk in enumerate(valid, start=1)
    ]


LINE_NUMBER_FIELDS = ("line_number", "line_no", "pass_number", "pass_no", "pass_id", "numero", "linha")
LINE_ID_FIELDS = ("line_id", "parent_line_id")


def _find_field(field_names, candidates) -> str | None:
    by_key = {str(name).casefold(): str(name) for name in field_names}
    for candidate in candidates:
        if candidate in by_key:
            return by_key[candidate]
    return None


def line_number_field(field_names) -> str | None:
    """Campo de numeracao herdado da camada (line_number > line_no > pass_number...)."""
    return _find_field(field_names, LINE_NUMBER_FIELDS)


def line_id_field(field_names) -> str | None:
    return _find_field(field_names, LINE_ID_FIELDS)


def line_id_for(number: int) -> str:
    return f"L{number:04d}" if number >= 0 else f"L-{abs(number):04d}"


def spatial_line_numbers(lines: dict[object, tuple[Point, ...]]) -> dict[object, int]:
    """Numeracao deterministica 1..N pela ordem transversal das passadas.

    Eixo = direcao da linha mais longa (normalizada, independe do sentido de
    digitalizacao); ordena pelo afastamento lateral do ponto medio, depois pela
    posicao ao longo do eixo e pela chave. Nao depende da ordem do provider.
    """
    valid = {key: tuple(points) for key, points in lines.items() if len(points) >= 2}
    if not valid:
        return {}
    reference_key = max(sorted(valid, key=str), key=lambda key: _path_length(valid[key]))
    reference = valid[reference_key]
    ax, ay = reference[-1][0] - reference[0][0], reference[-1][1] - reference[0][1]
    norm = (ax * ax + ay * ay) ** 0.5 or 1.0
    ax, ay = ax / norm, ay / norm
    if ax < 0 or (abs(ax) < 1e-12 and ay < 0):
        ax, ay = -ax, -ay
    nx, ny = -ay, ax
    ox, oy = reference[0]

    def sort_key(key):
        mx, my = _point_at(valid[key], _path_length(valid[key]) / 2.0)
        return (round((mx - ox) * nx + (my - oy) * ny, 3), round((mx - ox) * ax + (my - oy) * ay, 3), str(key))

    return {key: index for index, key in enumerate(sorted(valid, key=sort_key), start=1)}


def _point_at(points: tuple[Point, ...], station: float) -> Point:
    travelled = 0.0
    for a, b in zip(points, points[1:]):
        length = Segment(a, b).length
        if length > 0 and travelled + length >= station:
            t = (station - travelled) / length
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        travelled += length
    return points[-1]


def substring_by_station(points, start_m: float, end_m: float) -> tuple[Point, ...]:
    """Trecho [start, end] da polilinha no sentido original, com os vertices da fonte."""
    path = tuple(points)
    if end_m <= start_m:
        return ()
    output: list[Point] = [_point_at(path, start_m)]
    travelled = 0.0
    for a, b in zip(path, path[1:]):
        travelled += Segment(a, b).length
        if start_m < travelled < end_m and b != output[-1]:
            output.append(b)
    last = _point_at(path, end_m)
    if last != output[-1]:
        output.append(last)
    return tuple(output) if len(output) >= 2 else ()


def cut_line_by_station_gaps(
    points, gaps, *, min_length_m: float = 0.01
) -> list[tuple[Point, ...]]:
    """Linha original menos os intervalos sem operacao (estacoes ao longo dela).

    Sem intervalo dentro da linha, devolve exatamente os vertices de entrada.
    Os trechos mantem o sentido da linha; nunca ha recorte por talhao.
    """
    path = tuple(points)
    if len(path) < 2:
        raise PlantingLineCutError("A linha precisa ter ao menos dois vertices.")
    length = _path_length(path)
    clipped = sorted(
        (max(0.0, float(a)), min(length, float(b))) for a, b in gaps if min(length, b) > max(0.0, a)
    )
    if not clipped:
        return [path]
    merged: list[list[float]] = []
    for start, end in clipped:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    keep: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in merged:
        if start - cursor >= min_length_m:
            keep.append((cursor, start))
        cursor = end
    if length - cursor >= min_length_m:
        keep.append((cursor, length))
    return [piece for piece in (substring_by_station(path, a, b) for a, b in keep) if piece]


def _path_length(points: tuple[Point, ...] | list[Point]) -> float:
    return sum(Segment(a, b).length for a, b in zip(points, points[1:]))


def _split_polyline_precisely(
    points: tuple[Point, ...], zones: MultiPolygon, sample_m: float
) -> tuple[list[list[Point]], list[list[Point]]]:
    # A amostragem serve somente para localizar cruzamentos. A geometria de
    # saida conserva os vertices da fonte e recebe apenas os pontos de corte.
    refined_points: list[Point] = []
    refined_flags: list[bool] = []
    found_inside = False
    for edge_start, edge_end in zip(points, points[1:]):
        sampled = segment_samples((edge_start, edge_end), densify_m=sample_m)
        flags = [
            point_in_multipolygon(point, zones, check_boundary=False)
            for point in sampled
        ]
        found_inside = found_inside or any(flags)
        edge_points = [edge_start]
        edge_flags = [flags[0]]
        for previous, current, previous_flag, current_flag in zip(
            sampled, sampled[1:], flags, flags[1:]
        ):
            if previous_flag != current_flag:
                boundary = _boundary_point(previous, current, previous_flag, zones)
                edge_points.extend((boundary, boundary))
                edge_flags.extend((previous_flag, current_flag))
        edge_points.append(edge_end)
        edge_flags.append(flags[-1])
        for point, flag in zip(edge_points, edge_flags):
            if refined_points and point == refined_points[-1] and flag == refined_flags[-1]:
                continue
            refined_points.append(point)
            refined_flags.append(flag)

    if not found_inside:
        return [], [list(points)]
    return _chunks_by_flag(refined_points, refined_flags)


def _boundary_point(a: Point, b: Point, a_inside: bool, zones: MultiPolygon) -> Point:
    low, high = a, b
    for _ in range(24):
        middle = ((low[0] + high[0]) / 2.0, (low[1] + high[1]) / 2.0)
        middle_inside = point_in_multipolygon(middle, zones, check_boundary=False)
        if middle_inside == a_inside:
            low = middle
        else:
            high = middle
    return ((low[0] + high[0]) / 2.0, (low[1] + high[1]) / 2.0)


def _chunks_by_flag(
    points: list[Point], flags: list[bool]
) -> tuple[list[list[Point]], list[list[Point]]]:
    inside_chunks: list[list[Point]] = []
    outside_chunks: list[list[Point]] = []
    current = [points[0]]
    current_flag = flags[0]
    for point, flag in zip(points[1:], flags[1:]):
        if flag == current_flag:
            if point != current[-1]:
                current.append(point)
            continue
        if len(current) >= 2:
            (inside_chunks if current_flag else outside_chunks).append(current)
        current = [current[-1], point] if point != current[-1] else [point]
        current_flag = flag
    if len(current) >= 2:
        (inside_chunks if current_flag else outside_chunks).append(current)
    return inside_chunks, outside_chunks
