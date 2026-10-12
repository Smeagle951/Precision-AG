# -*- coding: utf-8 -*-
"""Feicoes do desvio minimo da pulverizacao para as camadas ja existentes.

10_Zonas_Seguranca (22 persistida): zona = raio fisico + margem.
11_Desvios_Obstaculos (23 persistida): trecho desviado/UNRESOLVED por passada x obstaculo,
com entrada, saida/retorno e comprimento original x alternativo.
05_Passadas (11 persistida): pior classificacao da passada.
"""

from __future__ import annotations

from .application_obstacle_engine import (
    SprayAvoidanceType,
    SprayConflictRecord,
    build_spray_safety_zones,
    spray_conflict_counts,
    spray_pass_avoidance_types,
)
from .line_geometry import Point, Polygon, distance

SPRAY_ZONE_FIELDS: tuple[tuple[str, str], ...] = (
    ("operation", "string"),
    ("obstacle_id", "string"),
    ("obstacle_radius_m", "double"),
    ("safety_margin_m", "double"),
    ("safe_radius_m", "double"),
)

SPRAY_DETOUR_FIELDS: tuple[tuple[str, str], ...] = (
    ("operation", "string"),
    ("pass_id", "int"),
    ("obstacle_id", "string"),
    ("avoidance_type", "string"),
    ("side", "string"),
    ("boom_width_m", "double"),
    ("safe_radius_m", "double"),
    ("required_offset_m", "double"),
    ("applied_offset_m", "double"),
    ("entry_station_m", "double"),
    ("exit_station_m", "double"),
    ("minimum_turn_radius_m", "double"),
    ("pass_role", "string"),
    ("reason", "string"),
    ("entry_x", "double"),
    ("entry_y", "double"),
    ("exit_x", "double"),
    ("exit_y", "double"),
    ("original_length_m", "double"),
    ("detour_length_m", "double"),
)

SPRAY_PASS_FIELDS: tuple[tuple[str, str], ...] = (
    ("avoidance_type", "string"),
    ("obstacle_ids", "string"),
)


def spray_safety_zone_features(obstacles) -> list[tuple[Polygon, dict[str, object]]]:
    """(poligono, atributos) de cada zona de seguranca da pulverizacao."""
    return [
        (zone.polygon, zone.attributes("spraying"))
        for zone in build_spray_safety_zones(list(obstacles))
        if zone.polygon is not None
    ]


def spray_detour_features(
    records: list[SprayConflictRecord],
) -> list[tuple[tuple[Point, ...], dict[str, object]]]:
    """(trecho desviado ou trecho original em conflito, atributos) — sem NONE."""
    out: list[tuple[tuple[Point, ...], dict[str, object]]] = []
    for record in records:
        if record.avoidance_type == SprayAvoidanceType.NONE.value:
            continue
        if len(record.detour_points) < 2:
            continue
        points = tuple(record.detour_points)
        out.append((points, {**record.attributes(), **detour_geometry_attributes(points)}))
    return out


def detour_geometry_attributes(points) -> dict[str, float]:
    """Entrada do desvio, saida (retorno a linha) e comprimento original x alternativo.

    O trecho comeca e termina sobre a passada original; o comprimento original e a
    distancia entre entrada e saida medida na passada reta (CRS metrico).
    """
    entry, exit_ = points[0], points[-1]
    detour = sum(distance(a, b) for a, b in zip(points, points[1:]))
    return {
        "entry_x": round(float(entry[0]), 3),
        "entry_y": round(float(entry[1]), 3),
        "exit_x": round(float(exit_[0]), 3),
        "exit_y": round(float(exit_[1]), 3),
        "original_length_m": round(distance(entry, exit_), 3),
        "detour_length_m": round(detour, 3),
    }


def spray_pass_attributes(records: list[SprayConflictRecord]) -> dict[int, dict[str, str]]:
    """avoidance_type / obstacle_ids por passada (05_Passadas)."""
    return spray_pass_avoidance_types(records)


def spray_avoidance_summary(records: list[SprayConflictRecord]) -> tuple[str, list[str]]:
    """Resumo NONE/LATERAL/FULL_CONTOUR/UNRESOLVED e avisos das falhas seguras."""
    if not records:
        return "", []
    counts = spray_conflict_counts(records)
    text = "Desvio pulverizacao: " + ", ".join(
        f"{kind.value}={counts.get(kind.value, 0)}" for kind in SprayAvoidanceType
    )
    warnings = [
        (
            f"{'Bordadura' if record.pass_role == 'headland' else 'Passada'} "
            f"{record.pass_id} x {record.obstacle_id}: sem desvio seguro"
            + (f" ({record.reason})" if record.reason else "")
        )
        for record in records
        if record.avoidance_type == SprayAvoidanceType.UNRESOLVED.value
    ]
    return text, warnings


def spray_machine_summary(
    *,
    boom_width_m: float,
    nozzle_count: int,
    nozzle_spacing_m: float,
    overlap_m: float,
) -> str:
    """Barra fisica e passo efetivo lidos da aba 2 (nao sao perguntados de novo)."""
    return (
        f"Barra fisica {boom_width_m:.3f} m ({nozzle_count} bicos x {nozzle_spacing_m:.3f} m) | "
        f"transpasse {overlap_m:.3f} m | passo efetivo {boom_width_m - overlap_m:.3f} m"
    )


def spray_safe_radius_text(obstacle_radius_m: float, safety_margin_m: float) -> str:
    return (
        f"{obstacle_radius_m:.2f} + {safety_margin_m:.2f} = "
        f"{obstacle_radius_m + safety_margin_m:.2f} m"
    )
