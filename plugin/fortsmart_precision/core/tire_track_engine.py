# -*- coding: utf-8 -*-
"""Rastros fisicos de pneu a partir da trajetoria ja desviada."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from .guidance_engine import TrafficPass
from .line_geometry import (
    Point,
    Polygon,
    add,
    build_polyline_strip_polygon,
    decimate_polyline,
    mul,
    normalize,
    perpendicular_left,
    sub,
)

if False:  # TYPE_CHECKING
    from ..domain.sprayer_traffic_configuration import SprayerTrafficConfiguration


class TireTrackEngineError(ValueError):
    """Erro ao gerar rastros de pneu."""


@dataclass(frozen=True)
class TireTrack:
    pass_id: int
    side: str
    offset_m: float
    tire_width_m: float
    track_width_m: float
    points: tuple[Point, ...]
    track_id: str = ""
    source_feature_id: str = ""
    physical_tire_width_m: float = 0.0
    safety_margin_m: float = 0.0

    def attributes(self) -> dict[str, object]:
        return {
            "pass_id": self.pass_id,
            "side": self.side,
            "offset_m": self.offset_m,
            "tire_width_m": self.tire_width_m,
            "track_width_m": self.track_width_m,
            "track_id": self.track_id,
            "source_feature_id": self.source_feature_id,
            "physical_tire_width_m": self.physical_tire_width_m or self.tire_width_m,
            "safety_margin_m": self.safety_margin_m,
            "effective_exclusion_width_m": self.tire_width_m,
        }

    def as_strip_polygon(self) -> Polygon | None:
        """Faixa poligonal do pneu ao longo da trajetoria completa (retas + arcos)."""
        return build_polyline_strip_polygon(
            self.points,
            half_width_m=self.tire_width_m / 2.0,
        )


def offset_polyline(points: tuple[Point, ...] | list[Point], offset_m: float) -> tuple[Point, ...]:
    """Desloca polilinha na perpendicular esquerda (offset positivo = esquerda)."""
    pts = list(points)
    if len(pts) < 2:
        return tuple(pts)
    out: list[Point] = []
    last = len(pts) - 1
    for index, point in enumerate(pts):
        if index == 0:
            direction = normalize(sub(pts[1], pts[0]))
        elif index == last:
            direction = normalize(sub(pts[index], pts[index - 1]))
        else:
            d1 = sub(pts[index], pts[index - 1])
            d2 = sub(pts[index + 1], pts[index])
            combined = add(d1, d2)
            try:
                direction = normalize(combined)
            except ValueError:
                direction = normalize(d2 if (d2[0] ** 2 + d2[1] ** 2) > 1e-18 else d1)
        left = perpendicular_left(direction)
        out.append(add(point, mul(left, offset_m)))
    return tuple(out)


def generate_tire_tracks(
    passes: list[TrafficPass],
    *,
    track_width_m: float,
    tire_width_m: float,
) -> list[TireTrack]:
    """Duas polilinhas por passada: centros dos pneus sobre a trajetoria final."""
    if track_width_m <= 0 or tire_width_m <= 0:
        raise TireTrackEngineError("Bitola e largura de pneu devem ser maiores que zero.")
    half = track_width_m / 2.0
    return _generate_at_offsets(
        passes,
        offsets=(("left", half), ("right", -half)),
        tire_width_m=tire_width_m,
        track_width_m=track_width_m,
        physical_tire_width_m=tire_width_m,
        safety_margin_m=0.0,
    )


def generate_tire_tracks_from_traffic(
    passes: list[TrafficPass],
    traffic: "SprayerTrafficConfiguration",
) -> list[TireTrack]:
    """Rastros nos centros das zonas de pneu (trajetoria completa, inclusive arcos)."""
    traffic.validate()
    left, right = traffic.calculate_tire_zones()
    track = traffic.to_machine_track()
    # Frame da maquina: centro negativo = esquerda → offset path = -center_m
    return _generate_at_offsets(
        passes,
        offsets=(("left", -left.center_m), ("right", -right.center_m)),
        tire_width_m=traffic.exclusion_width_m,
        track_width_m=track.track_width_m,
        physical_tire_width_m=traffic.resolved_tire_width_m(),
        safety_margin_m=traffic.safety_margin_m,
    )


def generate_tire_track_polygons(tracks: list[TireTrack]) -> list[tuple[TireTrack, Polygon]]:
    """Poligonos de faixa para cada rastro (fonte de verdade para tramline/shutoff)."""
    result: list[tuple[TireTrack, Polygon]] = []
    for track in tracks:
        polygon = track.as_strip_polygon()
        if polygon is not None:
            result.append((track, polygon))
    return result


def tire_tracks_multipolygon(tracks: list[TireTrack]) -> list[Polygon]:
    """Multipoligono das faixas de pneu."""
    return [poly for _track, poly in generate_tire_track_polygons(tracks)]


def _generate_at_offsets(
    passes: list[TrafficPass],
    *,
    offsets: tuple[tuple[str, float], ...],
    tire_width_m: float,
    track_width_m: float,
    physical_tire_width_m: float,
    safety_margin_m: float,
) -> list[TireTrack]:
    """Gera rastros sobre a trajetoria COMPLETA (retas + arcos de desvio).

    Antes decimava a 4 m / 100 pts e transformava curva/desvio em corda reta —
    o shutoff da plantadeira lia um rastro falso. Agora preserva a polilinha
    com passo fino o bastante para acompanhar o contorno do obstaculo.
    """
    tracks: list[TireTrack] = []
    for traffic_pass in passes:
        raw = list(traffic_pass.line_points())
        if len(raw) < 2:
            continue
        # Passo fino: desvio circular e A-B curva precisam sobreviver ao offset.
        points = decimate_polyline(raw, min_step_m=0.75, max_points=720)
        if len(points) < 2:
            continue
        for side, offset in offsets:
            tracks.append(
                TireTrack(
                    pass_id=traffic_pass.pass_no,
                    side=side,
                    offset_m=offset,
                    tire_width_m=tire_width_m,
                    track_width_m=track_width_m,
                    points=offset_polyline(points, offset),
                    track_id=f"TT_{traffic_pass.fs_id}_{side.upper()}_{uuid4().hex[:8]}",
                    source_feature_id=traffic_pass.fs_id,
                    physical_tire_width_m=physical_tire_width_m,
                    safety_margin_m=safety_margin_m,
                )
            )
    return tracks
