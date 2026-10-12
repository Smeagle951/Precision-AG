# -*- coding: utf-8 -*-
"""Motor de passadas de trafego (linha mestra / guidance)."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.precision_project import ABLine, PrecisionOperation
from .line_geometry import MultiPolygon, Point, Segment
from .parallel_pass_engine import (
    LOGGER,
    ParallelPass,
    ParallelPassParams,
    StraightFamilyStats,
    generate_parallel_passes_with_stats,
)


class GuidanceEngineError(ValueError):
    """Erro no motor de passadas."""


@dataclass(frozen=True)
class TrafficPass:
    pass_no: int
    fs_id: str
    operation_id: str
    spacing_m: float
    width_m: float
    offset_m: float
    azimuth_deg: float
    direction: str
    clipped_segment: Segment
    guidance_segment: Segment
    path_points: tuple[Point, ...] = ()

    def line_points(self) -> tuple[Point, ...]:
        if self.path_points:
            return self.path_points
        return (self.guidance_segment.start, self.guidance_segment.end)

    @classmethod
    def from_parallel_pass(cls, item: ParallelPass, *, direction: str = "forward") -> TrafficPass:
        return cls(
            pass_no=item.pass_no,
            fs_id=item.fs_id,
            operation_id=item.operation_id,
            spacing_m=item.spacing_m,
            width_m=item.width_m,
            offset_m=item.offset_m,
            azimuth_deg=item.azimuth_deg,
            direction=direction,
            clipped_segment=item.clipped_segment,
            guidance_segment=item.guidance_segment,
        )

    def attributes(self) -> dict[str, object]:
        return {
            "pass_id": self.pass_no,
            "line_no": self.pass_no,
            "fs_id": self.fs_id,
            "operation_id": self.operation_id,
            "spacing_m": self.spacing_m,
            "width_m": self.width_m,
            "offset_m": self.offset_m,
            "azimuth_deg": self.azimuth_deg,
            "direction": self.direction,
            "length_m": self.guidance_segment.length,
        }


def generate_traffic_passes(
    inner_boundary: MultiPolygon,
    ab_line: ABLine,
    operation: PrecisionOperation,
    *,
    clip_boundary: MultiPolygon | None = None,
) -> list[TrafficPass]:
    """Gera passadas centrais.

    `inner_boundary`: area de cobertura (miolo ou operacional) — define offsets.
    `clip_boundary`: limite original a expandir com `operation.extension_m`
    (processing = buffer). Sem segundo clip no limite original.
    """
    if not inner_boundary:
        raise GuidanceEngineError("Limite interno vazio para gerar passadas.")

    master = ab_line.line_points()
    params = ParallelPassParams(
        polygons=inner_boundary,
        ab_start=ab_line.start,
        ab_end=ab_line.end,
        pass_spacing_m=operation.pass_spacing_m,
        operation_width_m=operation.machine.operational_width_m,
        extension_m=operation.extension_m,
        operation_id=operation.operation_id,
        master_path=master,
        clip_boundary=clip_boundary if clip_boundary else inner_boundary,
    )
    raw, stats = generate_parallel_passes_with_stats(params)
    if stats is not None:
        _log_family_coverage(raw, params, stats)
    passes: list[TrafficPass] = []
    first_pass_no = raw[0].pass_no if raw else 0
    for item in raw:
        # Partes da mesma candidata seguem no mesmo sentido.
        direction = "forward" if (item.pass_no - first_pass_no) % 2 == 0 else "reverse"
        traffic = TrafficPass.from_parallel_pass(item, direction=direction)
        if item.path_points:
            traffic = TrafficPass(
                pass_no=traffic.pass_no,
                fs_id=traffic.fs_id,
                operation_id=traffic.operation_id,
                spacing_m=traffic.spacing_m,
                width_m=traffic.width_m,
                offset_m=traffic.offset_m,
                azimuth_deg=traffic.azimuth_deg,
                direction=traffic.direction,
                clipped_segment=traffic.clipped_segment,
                guidance_segment=traffic.guidance_segment,
                path_points=item.path_points,
            )
        passes.append(traffic)
    return passes


def traffic_pass_spacing_report(
    passes: list[TrafficPass],
    ab_line: ABLine,
    operation: PrecisionOperation,
    *,
    label: str = "plantio",
):
    """Mede cada passada reta na normal da familia (None para linha mestra curva).

    Indice da passada vem do desenho (offset_m = -indice * espacamento); a
    posicao real vem das coordenadas exportadas.
    """
    from .parallel_pass_engine import straight_family_frame
    from .spacing_validation import validate_pass_spacing

    if not passes:
        return None
    frame = straight_family_frame(ab_line.start, ab_line.end, ab_line.line_points())
    if frame is None:
        return None
    origin, _direction, normal = frame
    spacing = operation.pass_spacing_m
    return validate_pass_spacing(
        ((round(-item.offset_m / spacing), item.line_points()) for item in passes),
        origin,
        normal,
        spacing,
        label=label,
    )


def _log_family_coverage(
    raw: list[ParallelPass],
    params: ParallelPassParams,
    stats: StraightFamilyStats,
) -> None:
    """Diagnostico somente leitura; nunca interrompe a geracao."""
    from .pass_family_coverage import log_family_coverage, validate_family_coverage

    try:
        report = validate_family_coverage(
            raw,
            params.coverage_polygons(),
            implement_width_m=params.operation_width_m,
            pass_spacing_m=params.pass_spacing_m,
            stats=stats,
            label=params.operation_id or "talhao",
        )
    except Exception as exc:  # GEOS pode falhar em limites degenerados
        LOGGER.debug("Diagnostico de cobertura indisponivel: %s", exc)
        return
    log_family_coverage(report)
