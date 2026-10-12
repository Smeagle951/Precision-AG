# -*- coding: utf-8 -*-
"""Agrupamento de envelopes / zonas proibidas de obstaculos proximos."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.obstacle_model import Obstacle, ObstacleSafetyEnvelope
from .line_geometry import Point, circle_ring_polygon, distance


@dataclass(frozen=True)
class ObstacleGroup:
    """Grupo de obstaculos que formam uma unica zona operacional de conflito."""

    group_id: str
    obstacle_ids: tuple[str, ...]
    center: Point
    application_radius_m: float
    envelope: ObstacleSafetyEnvelope

    @property
    def is_merged(self) -> bool:
        return len(self.obstacle_ids) > 1


def group_overlapping(
    items: list,
    merge_distance_m: float,
    *,
    center_of,
    radius_of,
) -> list[list]:
    """Agrupa itens cujas ZONAS OPERACIONAIS se tocam, de forma transitiva.

    Comparar so a distancia entre centros e insuficiente: dois postes a 10 m um
    do outro, cada um com envelope de 18 m, formam uma barreira continua para a
    maquina. O criterio correto e a sobreposicao das zonas:

        distancia(c1, c2) <= r1 + r2 + folga_de_agrupamento

    O agrupamento e transitivo: uma fileira de postes vira UM corredor, evitando
    a trajetoria absurda "desvia -> volta -> desvia -> volta".
    """
    if merge_distance_m <= 0 or len(items) <= 1:
        return [[item] for item in items]

    groups: list[list] = []
    for item in items:
        center = center_of(item)
        radius = radius_of(item)
        touching: list[int] = []
        for index, group in enumerate(groups):
            for other in group:
                gap = distance(center, center_of(other)) - radius - radius_of(other)
                if gap <= merge_distance_m:
                    touching.append(index)
                    break
        if not touching:
            groups.append([item])
            continue
        first = touching[0]
        groups[first].append(item)
        # Este item pode ter unido grupos antes separados: funde-os.
        for index in reversed(touching[1:]):
            groups[first].extend(groups.pop(index))
    return groups


# Ate 5x o raio do maior membro o contorno ainda e uma curva agricola; acima
# disso o "circulo" viraria uma volta de centenas de metros.
_MAX_GROUP_ELONGATION = 5.0


def split_elongated_groups(
    groups: list[list],
    *,
    center_of,
    radius_of,
    max_elongation: float = _MAX_GROUP_ELONGATION,
) -> list[list]:
    """Quebra corredores muito longos em trechos com contorno viavel.

    Uma fileira de 40 postes num quilometro nao pode virar UM circulo de 500 m
    de raio: isso nao e trajetoria agricola, e o motor de contorno nao consegue
    fechar a curva. Cada subgrupo fica compacto o bastante para gerar um arco
    real, e os subgrupos seguem encadeados ao longo da fileira.
    """
    out: list[list] = []
    for group in groups:
        if len(group) <= 1:
            out.append(group)
            continue
        ordered = sorted(group, key=lambda item: (center_of(item)[0], center_of(item)[1]))
        current: list = []
        for item in ordered:
            candidate = current + [item]
            if len(candidate) == 1:
                current = candidate
                continue
            _center, radius = enclosing_circle(
                [(center_of(member), radius_of(member)) for member in candidate]
            )
            budget = max(radius_of(member) for member in candidate) * max_elongation
            if radius <= budget:
                current = candidate
                continue
            out.append(current)
            current = [item]
        if current:
            out.append(current)
    return out


def enclosing_circle(centers_radii: list[tuple[Point, float]]) -> tuple[Point, float]:
    """Circulo que cobre TODAS as zonas do grupo (centroide + alcance maximo).

    Usar o raio maximo do grupo em torno do centroide deixaria os obstaculos das
    pontas de fora — a trajetoria passaria por cima deles.
    """
    cx = sum(center[0] for center, _ in centers_radii) / len(centers_radii)
    cy = sum(center[1] for center, _ in centers_radii) / len(centers_radii)
    center = (cx, cy)
    radius = max(distance(center, item_center) + item_radius for item_center, item_radius in centers_radii)
    return center, radius


def merge_adjacent_envelopes(
    envelopes: list[ObstacleSafetyEnvelope],
    merge_distance_m: float,
) -> list[ObstacleSafetyEnvelope]:
    """Funde envelopes cujas zonas se sobrepoem (corredor de postes)."""
    if merge_distance_m <= 0 or len(envelopes) <= 1:
        return list(envelopes)

    groups = split_elongated_groups(
        group_overlapping(
            envelopes,
            merge_distance_m,
            center_of=lambda item: item.center,
            radius_of=lambda item: item.application_radius_m,
        ),
        center_of=lambda item: item.center,
        radius_of=lambda item: item.application_radius_m,
    )

    merged: list[ObstacleSafetyEnvelope] = []
    for group in groups:
        if len(group) == 1:
            merged.append(group[0])
            continue
        center, radius = enclosing_circle(
            [(item.center, item.application_radius_m) for item in group]
        )
        ids = "+".join(item.obstacle_id for item in group)
        merged.append(
            ObstacleSafetyEnvelope(
                obstacle_id=ids,
                geometry=circle_ring_polygon(center, radius, segments=48),
                application_radius_m=radius,
                center=center,
            )
        )
    return merged


def group_obstacles(
    obstacles: list[Obstacle],
    envelopes: list[ObstacleSafetyEnvelope],
    merge_distance_m: float,
) -> list[ObstacleGroup]:
    """Agrupa obstaculos por proximidade de centros ou envelopes fundidos."""
    merged = merge_adjacent_envelopes(envelopes, merge_distance_m)
    result: list[ObstacleGroup] = []
    for env in merged:
        ids = tuple(part for part in env.obstacle_id.split("+") if part)
        if not ids:
            ids = (env.obstacle_id,)
        result.append(
            ObstacleGroup(
                group_id=env.obstacle_id,
                obstacle_ids=ids,
                center=env.center,
                application_radius_m=env.application_radius_m,
                envelope=env,
            )
        )
    return result
