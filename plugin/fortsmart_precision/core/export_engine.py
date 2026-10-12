# -*- coding: utf-8 -*-
"""Orquestrador de exportacao com validacao obrigatoria."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..domain.planting_avoidance_result import PlantingAvoidanceResult
from ..exporters.geopackage_exporter import ExportResult, export_precision_lines_geojson
from .boundary_engine import BoundaryPlan
from .guidance_engine import TrafficPass
from .obstacle_buffer_engine import ForbiddenRegion, ObstacleSafetyEnvelope
from .obstacle_engine import AvoidedPath
from .row_engine import PlantingRow
from .shutoff_engine import RowShutoffSegment
from .tire_track_engine import TireTrack
from .tramline_engine import TramlineZone
from .validation_engine import ValidationReport


class ExportBlockedError(ValueError):
    """Exportacao bloqueada por falha de validacao."""


@dataclass(frozen=True)
class ExportPackageResult:
    export: ExportResult
    validation: ValidationReport


def export_precision_lines_package(
    output_dir: Path,
    *,
    passes: list[TrafficPass],
    rows: list[PlantingRow],
    tramline_zones: list[TramlineZone],
    shutoff_segments: list[RowShutoffSegment],
    validation_report: ValidationReport,
    force: bool = False,
    avoided_paths: list[AvoidedPath] | None = None,
    obstacle_envelopes: list[ObstacleSafetyEnvelope] | None = None,
    boundary: BoundaryPlan | None = None,
    planting_avoidance_results: list[PlantingAvoidanceResult] | None = None,
    forbidden_regions: list[ForbiddenRegion] | None = None,
    tire_tracks: list[TireTrack] | None = None,
) -> ExportPackageResult:
    """Exporta pacote somente se validacao passar (salvo force=True para debug)."""
    if not validation_report.ok and not force:
        raise ExportBlockedError(
            "Exportacao bloqueada: " + "; ".join(item.message for item in validation_report.errors)
        )

    export = export_precision_lines_geojson(
        output_dir,
        passes=passes,
        rows=rows,
        tramline_zones=tramline_zones,
        shutoff_segments=shutoff_segments,
        validation_report=validation_report,
        avoided_paths=avoided_paths,
        obstacle_envelopes=obstacle_envelopes,
        boundary=boundary,
        planting_avoidance_results=planting_avoidance_results,
        forbidden_regions=forbidden_regions,
        tire_tracks=tire_tracks,
    )
    return ExportPackageResult(export=export, validation=validation_report)
