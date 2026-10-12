# -*- coding: utf-8 -*-
"""Exportacao Precision Lines: GeoJSON + relatorio (GPKG via QGIS quando disponivel)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..core.boundary_engine import BoundaryPlan
from ..core.obstacle_buffer_engine import ForbiddenRegion, ObstacleSafetyEnvelope
from ..core.obstacle_engine import AvoidedPath
from ..core.guidance_engine import TrafficPass
from ..core.row_engine import PlantingRow
from ..core.shutoff_engine import RowShutoffSegment
from ..core.tramline_engine import TramlineZone
from ..core.validation_engine import ValidationReport
from ..domain.planting_avoidance_result import PlantingAvoidanceResult


@dataclass(frozen=True)
class ExportResult:
    output_dir: Path
    files: tuple[str, ...]
    validation_report: ValidationReport

    def report_path(self) -> Path:
        return self.output_dir / "validation_report.json"


def _segment_feature(segment, properties: dict) -> dict:
    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[segment.start[0], segment.start[1]], [segment.end[0], segment.end[1]]],
        },
        "properties": properties,
    }


def _polygon_feature(polygon, properties: dict) -> dict:
    outer, _holes = polygon
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[x, y] for x, y in outer]],
        },
        "properties": properties,
    }


def _polyline_feature(points: tuple, properties: dict) -> dict:
    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[p[0], p[1]] for p in points],
        },
        "properties": properties,
    }


def _line_feature(line_points: tuple, properties: dict) -> dict:
    if len(line_points) >= 2:
        return _polyline_feature(line_points, properties)
    raise ValueError("Linha precisa de ao menos dois pontos.")


def export_precision_lines_geojson(
    output_dir: Path,
    *,
    passes: list[TrafficPass],
    rows: list[PlantingRow],
    tramline_zones: list[TramlineZone],
    shutoff_segments: list[RowShutoffSegment],
    validation_report: ValidationReport,
    avoided_paths: list[AvoidedPath] | None = None,
    obstacle_envelopes: list[ObstacleSafetyEnvelope] | None = None,
    boundary: BoundaryPlan | None = None,
    planting_avoidance_results: list[PlantingAvoidanceResult] | None = None,
    forbidden_regions: list[ForbiddenRegion] | None = None,
    tire_tracks: list | None = None,
) -> ExportResult:
    """Grava camadas em GeoJSON + validation_report.json."""
    output_dir.mkdir(parents=True, exist_ok=True)
    files: list[str] = []
    avoided_paths = avoided_paths or []
    obstacle_envelopes = obstacle_envelopes or []
    planting_avoidance_results = planting_avoidance_results or []
    forbidden_regions = forbidden_regions or []
    tire_tracks = tire_tracks or []

    layers = {
        # Passadas do trator (visiveis / piloto).
        "passes.geojson": [_line_feature(p.line_points(), p.attributes()) for p in passes],
        # Linhas de semente: NAO exportar geometria no pacote principal
        # (poluem o mapa se carregadas). Ficam so no motor/shutoff.
        "rows.geojson": [],
        "tramline_zones.geojson": [_polygon_feature(z.polygon, z.attributes()) for z in tramline_zones],
        "shutoff_segments.geojson": [
            _line_feature(s.line_points(), s.attributes())
            for s in shutoff_segments
            if s.shutoff_state == "off"
        ],
        "tire_tracks.geojson": [
            _polyline_feature(track.points, track.attributes())
            for track in tire_tracks
            if len(track.points) >= 2
        ],
        "tire_track_polygons.geojson": [
            _polygon_feature(poly, track.attributes())
            for track in tire_tracks
            for poly in ([track.as_strip_polygon()] if track.as_strip_polygon() is not None else [])
        ],
        "avoided_paths.geojson": [
            _polyline_feature(path.modified_points, path.attributes()) for path in avoided_paths
        ],
        "obstacle_envelopes.geojson": [
            _polygon_feature(
                env.geometry,
                {
                    "obstacle_id": env.obstacle_id,
                    "application_radius_m": env.application_radius_m,
                },
            )
            for env in obstacle_envelopes
        ],
        "planting_avoidance_results.geojson": [
            _polyline_feature(item.avoidance_path, item.attributes())
            for item in planting_avoidance_results
            if len(item.avoidance_path) >= 2
        ],
        "forbidden_regions.geojson": [
            _polygon_feature(
                region.geometry,
                {
                    "obstacle_id": region.obstacle_id,
                    "safety_radius_m": region.safety_radius_m,
                    "tractor_clearance_radius_m": region.tractor_clearance_radius_m,
                    "implement_clearance_radius_m": region.implement_clearance_radius_m,
                },
            )
            for region in forbidden_regions
        ],
    }
    # `rows` = linhas virtuais de semente; NAO exportar geometria (polui o mapa).
    _ = rows
    if boundary is not None:
        layers["headland_centerlines.geojson"] = [
            _line_feature(line.line_points(), line.attributes()) for line in boundary.headland_centerlines
        ]
        if boundary.headland_inner_limits:
            layers["headland_inner_limits.geojson"] = [
                _line_feature(limit.points, limit.attributes())
                for limit in boundary.headland_inner_limits
            ]

    for name, features in layers.items():
        path = output_dir / name
        collection = {"type": "FeatureCollection", "features": features}
        path.write_text(json.dumps(collection, indent=2), encoding="utf-8")
        files.append(name)

    report_path = output_dir / "validation_report.json"
    report_path.write_text(json.dumps(validation_report.to_dict(), indent=2), encoding="utf-8")
    files.append("validation_report.json")

    return ExportResult(
        output_dir=output_dir,
        files=tuple(files),
        validation_report=validation_report,
    )
