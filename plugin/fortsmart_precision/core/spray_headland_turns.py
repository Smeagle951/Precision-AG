# -*- coding: utf-8 -*-
"""Cabeceira da pulverizacao: Extensao reta / operador ou Manobra automatica.

Cabeceira e como o pulverizador sai de uma passada e entra na proxima. Nao e
bordadura (passada junto ao perimetro) nem desvio de obstaculo (motor de
aplicacao). No modo manual nada e gerado: cada passada segue reta, com a
extensao do gerador, independente da vizinha.

O modo automatico reutiliza o motor de manobras (``headland_turn_engine``): a
curva sai onde a passada deixa a area de trabalho principal (miolo, ou o
talhao quando nao ha bordadura), fica dentro do limite operacional (talhao +
extensao) afastada meia largura externa do conjunto, nao volta ao miolo e nao
cruza zona de seguranca. O que nao couber vira aviso, sem curva forcada.
As passadas nunca sao alteradas; as curvas sao feicoes separadas
(``16_Manobras_Cabeceira``). Distancias em metros, CRS projetado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from shapely.geometry import LineString
from shapely.geometry import Point as ShapelyPoint
from shapely.ops import substring, unary_union

from ..domain.precision_project import SPRAY_HEADLAND_TURN_AUTOMATIC
from .headland_turn_engine import (
    STATUS_OK,
    STATUS_WARNING_CROSSING,
    HeadlandTurn,
    PassRecord,
    TurnMode,
    TurnSettings,
    build_logical_passes,
    plan_headland_turns,
)
from .line_geometry import Point
from .obstacle_ring_bypass import _to_shapely_polygon
from .planting_line_cut_engine import line_id_for

SPRAY_HEADLAND_SOURCE_LAYER = "11_Passadas"
# Marca as curvas publicadas pelo Workspace (distintas das salvas no painel de manobras).
SPRAY_HEADLAND_TURN_PROPERTY = "fortsmart_precision/spray_headland_turns"
SPRAY_HEADLAND_RADIUS_MISSING = "SPRAY_HEADLAND_RADIUS_MISSING"
SPRAY_HEADLAND_NO_LIMIT = "SPRAY_HEADLAND_NO_LIMIT"
SPRAY_HEADLAND_TURN_SHAPE = "U (arco - reta - arco tangentes)"
DRAWABLE_TURN_STATUSES = (STATUS_OK, STATUS_WARNING_CROSSING)
RADIUS_MISSING_MESSAGE = (
    "Manobra automatica: informe o raio minimo de giro do PULVERIZADOR "
    "(o raio da plantadeira nunca e usado)."
)
_MIN_PART_M = 0.05


@dataclass(frozen=True)
class SprayHeadlandTurnResult:
    """Curvas aceitas (desenhaveis), recusadas e avisos da cabeceira automatica."""

    mode: str = SPRAY_HEADLAND_TURN_AUTOMATIC
    turns: tuple[HeadlandTurn, ...] = ()
    rejected: tuple[HeadlandTurn, ...] = ()
    warnings: tuple[str, ...] = ()
    report: dict[str, Any] = field(default_factory=dict)

    def features(self) -> list[tuple[tuple[Point, ...], dict[str, object]]]:
        """(geometria, atributos HEADLAND_TURN_FIELDS) das curvas aceitas."""
        return [
            (turn.points, turn.attributes(SPRAY_HEADLAND_SOURCE_LAYER))
            for turn in self.turns
            if len(turn.points) >= 2
        ]


def machine_half_outer_width_m(machine) -> float:
    """Meia largura externa do conjunto (bitola + pneu) do cadastro do pulverizador."""
    track = machine.effective_track
    return (float(track.track_width_m) + float(track.tire_width_m)) / 2.0


def _shape(multipolygon) -> Any:
    polygons = [_to_shapely_polygon(polygon) for polygon in (multipolygon or ())]
    polygons = [polygon for polygon in polygons if polygon is not None]
    return unary_union(polygons) if polygons else None


def trim_to_area(points: Iterable[Point], area) -> tuple[Point, ...]:
    """Trecho da passada entre a primeira entrada e a ultima saida da area."""
    line = LineString(points)
    if area is None:
        return tuple(line.coords)
    inside = line.intersection(area)
    parts = [
        geom for geom in getattr(inside, "geoms", [inside])
        if geom.geom_type == "LineString" and geom.length > _MIN_PART_M
    ]
    if not parts:
        return ()
    stations = [
        line.project(ShapelyPoint(coord)) for part in parts for coord in (part.coords[0], part.coords[-1])
    ]
    start, end = min(stations), max(stations)
    if end - start <= _MIN_PART_M:
        return ()
    return tuple((float(x), float(y)) for x, y in substring(line, start, end).coords)


def _pass_records(spraying_passes, work_area) -> list[PassRecord]:
    records = []
    for traffic in spraying_passes:
        points = trim_to_area(traffic.line_points(), work_area)
        if len(points) < 2:
            continue
        records.append(
            PassRecord(
                points,
                line_id=line_id_for(traffic.pass_no),
                number=int(traffic.pass_no),
                attributes={"direction": getattr(traffic, "direction", None)},
            )
        )
    return records


def _warning(turn: HeadlandTurn) -> str:
    return f"Cabeceira {turn.from_pass}->{turn.to_pass}: {turn.status} — {turn.message or 'sem curva segura'}"


def plan_spray_headland_turns(
    spraying_passes,
    *,
    work_area,
    operational_area,
    radius_m: float | None,
    clearance_m: float,
    obstacles=None,
    ab_heading: Point | None = None,
) -> SprayHeadlandTurnResult:
    """Uma curva por par consecutivo de passadas; sem raio ou sem espaco, so avisos."""
    report: dict[str, Any] = {
        "mode": SPRAY_HEADLAND_TURN_AUTOMATIC,
        "turn_shape": SPRAY_HEADLAND_TURN_SHAPE,
        "min_turn_radius_m": radius_m,
        "clearance_m": round(float(clearance_m), 3),
        "passes_modified": False,
    }
    if radius_m is None or radius_m <= 0:
        report["status"] = SPRAY_HEADLAND_RADIUS_MISSING
        return SprayHeadlandTurnResult(warnings=(RADIUS_MISSING_MESSAGE,), report=report)
    limit = _shape(operational_area)
    if limit is None or limit.is_empty:
        report["status"] = SPRAY_HEADLAND_NO_LIMIT
        return SprayHeadlandTurnResult(
            warnings=("Manobra automatica: limite operacional indisponivel.",), report=report
        )
    work = _shape(work_area)
    turning_area = limit.buffer(-float(clearance_m)) if clearance_m > 0 else limit
    if work is not None:
        turning_area = turning_area.difference(work)
    blocked = _shape(obstacles) if obstacles else None
    passes, number_source = build_logical_passes(_pass_records(spraying_passes, work))
    plan = plan_headland_turns(
        passes,
        TurnSettings(min_turn_radius_m=float(radius_m), mode=TurnMode.AUTO),
        turning_area=turning_area,
        obstacles=blocked,
        ab_heading=ab_heading,
        source_layer=SPRAY_HEADLAND_SOURCE_LAYER,
    )
    accepted = tuple(turn for turn in plan.turns if turn.status in DRAWABLE_TURN_STATUSES)
    rejected = tuple(turn for turn in plan.turns if turn.status not in DRAWABLE_TURN_STATUSES)
    report.update(plan.report)
    report.update({
        "status": "OK" if not rejected else "PARTIAL",
        "line_number_source": number_source,
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "radii_m": sorted({round(turn.radius_m, 3) for turn in accepted if turn.radius_m}),
    })
    warnings = tuple(_warning(turn) for turn in plan.turns if turn.status != STATUS_OK)
    return SprayHeadlandTurnResult(turns=accepted, rejected=rejected, warnings=warnings, report=report)


def spray_headland_turn_summary(result: SprayHeadlandTurnResult | None) -> str:
    """Resumo curto para a GUI; vazio no modo manual."""
    if result is None:
        return ""
    if result.report.get("status") in (SPRAY_HEADLAND_RADIUS_MISSING, SPRAY_HEADLAND_NO_LIMIT):
        return "Cabeceira automatica: nao gerada"
    radii = ", ".join(f"{radius:.2f}" for radius in result.report.get("radii_m", []))
    text = f"Cabeceira automatica: {len(result.turns)} curva(s)"
    if radii:
        text += f" (raio {radii} m)"
    if result.rejected:
        text += f", {len(result.rejected)} sem espaco/seguranca"
    return text
