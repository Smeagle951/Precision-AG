# -*- coding: utf-8 -*-
"""Motor de zonas de tramline (trafego de maquina)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from ..domain.machine_model import SprayerMachine
from .guidance_engine import TrafficPass
from .line_geometry import MultiPolygon, Polygon, point_in_multipolygon
from .tire_track_engine import (
    TireTrack,
    generate_tire_track_polygons,
    generate_tire_tracks,
    generate_tire_tracks_from_traffic,
)


class TramlineEngineError(ValueError):
    """Erro no motor de tramlines."""


@dataclass(frozen=True)
class TramlineZone:
    fs_id: str
    tramline_id: str
    operation_id: str
    machine_id: str
    pass_id: int
    side: str
    width_m: float
    track_width_m: float
    source: str
    polygon: Polygon

    def attributes(self) -> dict[str, object]:
        return {
            "fs_id": self.fs_id,
            "tramline_id": self.tramline_id,
            "operation_id": self.operation_id,
            "machine_id": self.machine_id,
            "pass_id": self.pass_id,
            "side": self.side,
            "width_m": self.width_m,
            "track_width_m": self.track_width_m,
            "source": self.source,
        }


def generate_tramline_zones(
    passes: list[TrafficPass],
    sprayer: SprayerMachine,
    *,
    clip_area: MultiPolygon | None = None,
) -> list[TramlineZone]:
    """Gera TRAMLINE_ZONE a partir dos rastros de pneu (path completo + arcos)."""
    sprayer.validate()
    if not passes:
        return []

    if sprayer.traffic is not None:
        tracks = generate_tire_tracks_from_traffic(passes, sprayer.traffic)
    else:
        tracks = generate_tire_tracks(
            passes,
            track_width_m=sprayer.track.track_width_m,
            tire_width_m=sprayer.track.tire_width_m,
        )
    operation_id = passes[0].operation_id if passes else "spraying"
    return generate_tramline_zones_from_tire_tracks(
        tracks,
        machine_id=sprayer.machine_id,
        operation_id=operation_id,
        clip_area=clip_area,
    )


def generate_tramline_zones_from_tire_tracks(
    tracks: list[TireTrack],
    *,
    machine_id: str,
    operation_id: str = "spraying",
    clip_area: MultiPolygon | None = None,
) -> list[TramlineZone]:
    """Tramlines a partir dos poligonos de rastro (fonte unica de verdade)."""
    zones: list[TramlineZone] = []
    for track, polygon in generate_tire_track_polygons(tracks):
        if clip_area is not None:
            clipped = _clip_strip_to_area(polygon, clip_area)
            if clipped is None:
                continue
            polygon = clipped
        zone_id = f"{track.pass_id}_{track.side}"
        zones.append(
            TramlineZone(
                fs_id=str(uuid4()),
                tramline_id=zone_id,
                operation_id=operation_id,
                machine_id=machine_id,
                pass_id=track.pass_id,
                side=track.side,
                width_m=track.tire_width_m,
                track_width_m=track.track_width_m,
                source="tire_track",
                polygon=polygon,
            )
        )
    return zones


def _clip_strip_to_area(strip: Polygon, area: MultiPolygon) -> Polygon | None:
    """Mantem faixa se o centro geometrico da faixa esta dentro da area."""
    outer, _ = strip
    if len(outer) < 4:
        return None
    pts = outer[:-1] if outer and outer[0] == outer[-1] else list(outer)
    if len(pts) < 3:
        return None
    cx = sum(point[0] for point in pts) / len(pts)
    cy = sum(point[1] for point in pts) / len(pts)
    if not point_in_multipolygon((cx, cy), area):
        return None
    return strip
