# -*- coding: utf-8 -*-
"""Construcao de envelopes de aplicacao e zonas proibidas de plantio."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.machine_model import MachineProfile
from ..domain.obstacle_model import Obstacle, ObstacleSafetyEnvelope
from ..domain.planting_avoidance_configuration import PlantingAvoidanceConfiguration
from ..domain.planting_kinematics import PlantingKinematics
from .line_geometry import (
    MultiPolygon,
    Point,
    Polygon,
    circle_ring_polygon,
    expand_polygon,
    offset_axis_aligned_polygon,
)
from .obstacle_grouping_engine import merge_adjacent_envelopes

__all__ = [
    "ObstacleBufferError",
    "ForbiddenRegion",
    "build_safety_envelope",
    "build_safety_zone",
    "build_application_envelope",
    "build_all_envelopes",
    "build_planting_forbidden_region",
    "build_all_planting_forbidden_regions",
    "merge_adjacent_envelopes",
    "envelope_hits_segment",
    "allowed_area_multipolygon",
    "ObstacleSafetyEnvelope",
]


class ObstacleBufferError(ValueError):
    """Erro ao construir envelope de obstaculo."""


def build_safety_zone(obstacle: Obstacle) -> ObstacleSafetyEnvelope | None:
    """Zona de seguranca = obstaculo RTK + margem, sem W/2 da barra/plantadeira."""
    obstacle.validate()
    radius = obstacle.safety_zone_radius_m()
    if radius <= 0:
        return None
    if obstacle.is_circular() or obstacle.polygon is None:
        geometry = circle_ring_polygon(obstacle.center, radius, segments=48)
        center = obstacle.center
    else:
        geometry = expand_polygon(obstacle.polygon, radius)
        cx = sum(p[0] for p in geometry[0]) / len(geometry[0])
        cy = sum(p[1] for p in geometry[0]) / len(geometry[0])
        center = (cx, cy)
    return ObstacleSafetyEnvelope(
        obstacle_id=obstacle.obstacle_id,
        geometry=geometry,
        application_radius_m=radius,
        center=center,
    )


def build_safety_envelope(obstacle: Obstacle, machine: MachineProfile | None = None) -> ObstacleSafetyEnvelope | None:
    """Alias de zona de seguranca (machine ignorado: nao inclui meia largura)."""
    del machine
    return build_safety_zone(obstacle)


@dataclass(frozen=True)
class ForbiddenRegion:
    """Zona proibida para plantio (RTK + margens + envelope da maquina)."""

    obstacle_id: str
    geometry: Polygon
    center: Point
    safety_radius_m: float
    tractor_clearance_radius_m: float
    implement_clearance_radius_m: float
    obstacle_ids: tuple[str, ...] = ()

    def as_multipolygon(self) -> MultiPolygon:
        return [self.geometry]

    @property
    def group_ids(self) -> tuple[str, ...]:
        return self.obstacle_ids or (self.obstacle_id,)


def build_application_envelope(
    obstacle: Obstacle,
    machine: MachineProfile,
) -> ObstacleSafetyEnvelope:
    """Envelope externo onde a linha de centro da barra nao deve penetrar."""
    obstacle.validate()
    app_radius = obstacle.application_radius_m(machine)
    if obstacle.is_circular():
        geometry = circle_ring_polygon(obstacle.center, app_radius, segments=48)
        return ObstacleSafetyEnvelope(
            obstacle_id=obstacle.obstacle_id,
            geometry=geometry,
            application_radius_m=app_radius,
            center=obstacle.center,
        )
    if obstacle.polygon is not None:
        geometry = expand_polygon(obstacle.polygon, app_radius)
        cx = sum(p[0] for p in geometry[0]) / len(geometry[0])
        cy = sum(p[1] for p in geometry[0]) / len(geometry[0])
        return ObstacleSafetyEnvelope(
            obstacle_id=obstacle.obstacle_id,
            geometry=geometry,
            application_radius_m=app_radius,
            center=(cx, cy),
        )
    raise ObstacleBufferError(f"Obstaculo {obstacle.obstacle_id} sem geometria suportada.")


# Alias legado
build_safety_envelope = build_application_envelope


def build_all_envelopes(
    obstacles: list[Obstacle],
    machine: MachineProfile,
) -> list[ObstacleSafetyEnvelope]:
    return [build_application_envelope(item, machine) for item in obstacles]


def build_planting_forbidden_region(
    obstacle: Obstacle,
    kinematics: PlantingKinematics,
    config: PlantingAvoidanceConfiguration,
) -> ForbiddenRegion:
    """
    Zona proibida de plantio.

    A geometria RTK original permanece intacta; margens e envelope de maquina
    sao aplicados apenas na construcao da zona.
    """
    obstacle.validate()
    kinematics.validate()
    config.validate()

    base_radius = max(obstacle.obstacle_radius_m, 0.0) + config.total_margin_m()
    implement_clearance = base_radius + kinematics.half_operational_width_m
    tractor_clearance = base_radius + kinematics.half_track_width_m
    if kinematics.tractor_length_m is not None:
        tractor_clearance = max(tractor_clearance, base_radius + kinematics.tractor_length_m / 2.0)

    # Envelope de deteccao usa a plantadeira (maior largura operacional).
    safety_radius = implement_clearance

    if obstacle.is_circular():
        geometry = circle_ring_polygon(obstacle.center, safety_radius, segments=48)
        center = obstacle.center
    elif obstacle.polygon is not None:
        geometry = expand_polygon(obstacle.polygon, safety_radius)
        cx = sum(p[0] for p in geometry[0]) / len(geometry[0])
        cy = sum(p[1] for p in geometry[0]) / len(geometry[0])
        center = (cx, cy)
    else:
        raise ObstacleBufferError(f"Obstaculo {obstacle.obstacle_id} sem geometria suportada.")

    return ForbiddenRegion(
        obstacle_id=obstacle.obstacle_id,
        geometry=geometry,
        center=center,
        safety_radius_m=safety_radius,
        tractor_clearance_radius_m=tractor_clearance,
        implement_clearance_radius_m=implement_clearance,
        obstacle_ids=(obstacle.obstacle_id,),
    )


def build_all_planting_forbidden_regions(
    obstacles: list[Obstacle],
    kinematics: PlantingKinematics,
    config: PlantingAvoidanceConfiguration,
) -> list[ForbiddenRegion]:
    return [build_planting_forbidden_region(item, kinematics, config) for item in obstacles]


def merge_planting_forbidden_regions(
    regions: list[ForbiddenRegion],
    merge_distance_m: float,
) -> list[ForbiddenRegion]:
    """Funde zonas proibidas que se sobrepoem em um unico desvio continuo.

    O criterio e a sobreposicao das zonas de clearance do implemento, nao a
    distancia entre os centros: postes distantes 10 m com envelope de 10 m cada
    formam uma barreira continua e devem virar um corredor unico.
    """
    if merge_distance_m <= 0 or len(regions) <= 1:
        return list(regions)

    from .obstacle_grouping_engine import (
        enclosing_circle,
        group_overlapping,
        split_elongated_groups,
    )

    groups = split_elongated_groups(
        group_overlapping(
            regions,
            merge_distance_m,
            center_of=lambda item: item.center,
            radius_of=lambda item: item.implement_clearance_radius_m,
        ),
        center_of=lambda item: item.center,
        radius_of=lambda item: item.implement_clearance_radius_m,
    )

    merged: list[ForbiddenRegion] = []
    for group in groups:
        if len(group) == 1:
            merged.append(group[0])
            continue
        center, impl_radius = enclosing_circle(
            [(item.center, item.implement_clearance_radius_m) for item in group]
        )
        # Os demais raios crescem na mesma proporcao do alcance ate as pontas.
        _, safety_radius = enclosing_circle(
            [(item.center, item.safety_radius_m) for item in group]
        )
        _, tractor_radius = enclosing_circle(
            [(item.center, item.tractor_clearance_radius_m) for item in group]
        )
        ids = tuple(oid for item in group for oid in item.group_ids)
        group_id = "+".join(ids)
        merged.append(
            ForbiddenRegion(
                obstacle_id=group_id,
                geometry=circle_ring_polygon(center, safety_radius, segments=48),
                center=center,
                safety_radius_m=safety_radius,
                tractor_clearance_radius_m=tractor_radius,
                implement_clearance_radius_m=impl_radius,
                obstacle_ids=ids,
            )
        )
    return merged


def envelope_hits_segment(envelope: ObstacleSafetyEnvelope, segment_start: Point, segment_end: Point) -> bool:
    from .line_geometry import Segment

    seg = Segment(segment_start, segment_end)
    if _segment_hits_disc(envelope.center, float(envelope.application_radius_m), seg):
        return True
    if _is_circular_ring(envelope.geometry):
        return False
    from .line_geometry import segment_inside_intervals

    return bool(segment_inside_intervals(seg, envelope.as_multipolygon()))


def forbidden_hits_segment(region: ForbiddenRegion, segment_start: Point, segment_end: Point) -> bool:
    from .line_geometry import Segment

    seg = Segment(segment_start, segment_end)
    radius = float(region.implement_clearance_radius_m)
    if _segment_hits_disc(region.center, radius, seg):
        return True
    if _is_circular_ring(region.geometry):
        return False
    from .line_geometry import segment_inside_intervals

    return bool(segment_inside_intervals(seg, region.as_multipolygon()))


def forbidden_swath_hits_segment(
    region: ForbiddenRegion,
    segment: Segment,
    half_width_m: float,
) -> bool:
    """Detecta colisao da faixa do implemento (nao so o eixo do trator)."""
    if forbidden_hits_segment(region, segment.start, segment.end):
        return True
    if half_width_m <= 0.0:
        return False
    from .line_geometry import add, mul, normalize, perpendicular_left, sub

    direction = normalize(sub(segment.end, segment.start))
    left = perpendicular_left(direction)
    for side in (1.0, -1.0):
        off = mul(left, half_width_m * side)
        if forbidden_hits_segment(region, add(segment.start, off), add(segment.end, off)):
            return True
    return False


def envelope_swath_hits_segment(
    envelope: ObstacleSafetyEnvelope,
    segment: Segment,
    half_width_m: float,
) -> bool:
    """Detecta colisao da faixa da barra/plantadeira com o envelope."""
    if envelope_hits_segment(envelope, segment.start, segment.end):
        return True
    if half_width_m <= 0.0:
        return False
    from .line_geometry import add, mul, normalize, perpendicular_left, sub

    direction = normalize(sub(segment.end, segment.start))
    left = perpendicular_left(direction)
    for side in (1.0, -1.0):
        off = mul(left, half_width_m * side)
        if envelope_hits_segment(envelope, add(segment.start, off), add(segment.end, off)):
            return True
    return False


def _is_circular_ring(geometry: Polygon) -> bool:
    """Anel de buffer circular (poste / grupo) — evita point-in-polygon caro."""
    outer = geometry[0]
    return len(outer) <= 52


def _segment_hits_disc(center: Point, radius_m: float, segment: "Segment") -> bool:
    """Colisao segmento x disco (CRS metrico)."""
    from .line_geometry import distance

    if radius_m <= 0.0:
        return False
    if distance(center, segment.start) <= radius_m or distance(center, segment.end) <= radius_m:
        return True
    dx = segment.end[0] - segment.start[0]
    dy = segment.end[1] - segment.start[1]
    length2 = dx * dx + dy * dy
    if length2 <= 1e-12:
        return distance(center, segment.start) <= radius_m
    t = ((center[0] - segment.start[0]) * dx + (center[1] - segment.start[1]) * dy) / length2
    if t < 0.0 or t > 1.0:
        return False
    closest = (segment.start[0] + dx * t, segment.start[1] + dy * t)
    return distance(center, closest) <= radius_m


def allowed_area_multipolygon(
    work_area: MultiPolygon,
    envelopes: list[ObstacleSafetyEnvelope],
) -> MultiPolygon:
    """Representacao simplificada: work_area (subtracao real feita na validacao)."""
    del envelopes
    return work_area
