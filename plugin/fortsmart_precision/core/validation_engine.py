# -*- coding: utf-8 -*-
"""Validacao do projeto Precision Lines antes de exportar."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.crs import CrsValidationError, require_projected_metric
from ..domain.planter_geometry import PlanterGeometryValidator
from ..domain.precision_project import PrecisionProject
from .boundary_engine import BoundaryPlan
from .guidance_engine import TrafficPass
from .row_engine import PlantingRow
from .shutoff_engine import RowShutoffSegment
from .tramline_engine import TramlineZone


@dataclass
class ValidationIssue:
    level: str
    code: str
    message: str


@dataclass
class ValidationReport:
    ok: bool = True
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)

    def add_error(self, code: str, message: str) -> None:
        self.ok = False
        self.errors.append(ValidationIssue("error", code, message))

    def add_warning(self, code: str, message: str) -> None:
        self.warnings.append(ValidationIssue("warning", code, message))

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "checks": list(self.checks),
            "errors": [{"code": i.code, "message": i.message} for i in self.errors],
            "warnings": [{"code": i.code, "message": i.message} for i in self.warnings],
        }


def validate_precision_project(
    project: PrecisionProject,
    *,
    boundary: BoundaryPlan | None = None,
    planting_passes: list[TrafficPass] | None = None,
    planting_rows: list[PlantingRow] | None = None,
    tramline_zones: list[TramlineZone] | None = None,
    shutoff_segments: list[RowShutoffSegment] | None = None,
) -> ValidationReport:
    """Checklist completo antes de exportacao."""
    report = ValidationReport()

    try:
        require_projected_metric(project.field.crs_authid, "planejamento Precision Lines")
        report.checks.append("CRS metrico")
    except CrsValidationError as exc:
        report.add_error("CRS_INVALID", str(exc))
        return report

    try:
        project.validate()
        report.checks.append("Projeto valido")
    except ValueError as exc:
        report.add_error("PROJECT_INVALID", str(exc))
        return report

    if project.planting is not None:
        planter = project.planting.machine
        report.checks.append(
            f"Largura de trabalho da plantadeira: {planter.operational_width_m:.2f} m"
        )
        geometry = getattr(planter, "geometry_config", None)
        if geometry is not None:
            for issue in PlanterGeometryValidator().validate(geometry):
                if issue.level == "error":
                    report.add_error(issue.code, issue.message)
                else:
                    report.add_warning(issue.code, issue.message)

    if project.spraying is not None:
        sprayer = project.spraying.machine
        comparison = sprayer.width_comparison()
        report.checks.append("Largura pulverizador calculada")
        if not comparison.is_compatible:
            report.add_warning(
                "SPRAYER_WIDTH_DIVERGENCE",
                f"Largura da barra diverge {comparison.difference_m:.3f} m de bicos * espacamento.",
            )

    if boundary is not None:
        report.checks.append("Bordadura gerada")
        if boundary.reserved_width_m < 0:
            report.add_error("HEADLAND_INVALID", "Reserva de bordadura invalida.")
        expected_passes = project.planting.headland.pass_count if project.planting else 0
        if expected_passes > 0 and len(boundary.headland_centerlines) != expected_passes:
            report.add_warning(
                "HEADLAND_CENTERLINE_COUNT",
                "Quantidade de centros de bordadura difere do configurado.",
            )

    if planting_passes is not None:
        report.checks.append(f"Passadas: {len(planting_passes)}")
        if project.planting and not planting_passes:
            report.add_error("NO_PASSES", "Nenhuma passada gerada no miolo.")

    if planting_rows is not None and project.planting is not None:
        report.checks.append(f"Linhas fisicas: {len(planting_rows)}")
        expected_per_pass = project.planting.machine.row_count
        if planting_passes:
            for p in planting_passes:
                count = sum(1 for r in planting_rows if r.pass_id == p.pass_no)
                if count != expected_per_pass:
                    report.add_warning(
                        "ROW_COUNT_PER_PASS",
                        f"Passada {p.pass_no}: {count} linhas (esperado {expected_per_pass}).",
                    )

    if tramline_zones is not None:
        report.checks.append(f"Tramlines: {len(tramline_zones)}")
        for zone in tramline_zones:
            if zone.width_m <= 0:
                report.add_error("TRAMLINE_WIDTH", "Largura de tramline invalida.")

    if shutoff_segments is not None:
        report.checks.append(f"Segmentos shutoff: {len(shutoff_segments)}")
        if not shutoff_segments and planting_rows:
            report.add_warning("NO_SHUTOFF", "Nenhum segmento de desligamento gerado.")

    return report
