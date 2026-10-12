# -*- coding: utf-8 -*-
"""Validacao de caminhos de volta e relatorio estruturado."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.turn_path_engine import TurnPath, TurnPathResult, filter_savable_turns
from ..domain.boundary_areas import BoundaryAreas
from ..domain.turn_configuration import (
    DEFAULT_EXTERNAL_EXTENSION_M,
    TurnConfiguration,
    TurnConfigurationError,
    TurnFinishMode,
    TurnStatus,
)


@dataclass
class TurnValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    turns_summary: dict[str, object] = field(default_factory=dict)
    savable_count: int = 0
    invalid_count: int = 0
    estimated_count: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "turns_summary": dict(self.turns_summary),
            "savable_count": self.savable_count,
            "invalid_count": self.invalid_count,
            "estimated_count": self.estimated_count,
        }


def validate_turn_configuration(
    config: TurnConfiguration,
    areas: BoundaryAreas | None = None,
) -> TurnValidationReport:
    """Valida configuracao antes de gerar voltas."""
    report = TurnValidationReport()
    try:
        config.validate()
    except TurnConfigurationError as exc:
        report.errors.append(str(exc))
        return report

    if not config.generate_turns or config.finish_mode == TurnFinishMode.NONE:
        report.turns_summary = {"mode": TurnFinishMode.NONE.value, "turn_count": 0}
        return report

    if config.requires_headland():
        if areas is None or areas.reserved_width_m <= 0 or not areas.headland_area:
            report.errors.append("Bordadura inexistente para volta interna.")

    if config.requires_external_area():
        if areas is None or not areas.external_turn_area:
            report.errors.append("Area externa autorizada nao informada para volta externa.")
        ext = config.extension_status()
        if ext["status"] == "insufficient":
            report.errors.append(
                f"Extensao configurada ({ext['configured_m']:.2f} m) insuficiente; "
                f"minima estimada {ext['minimum_m']:.2f} m."
            )
        elif ext["status"] == "insufficient_data":
            report.warnings.append(
                "Extensao minima estimada indisponivel (raio/parametros incompletos)."
            )
        if abs(config.external_extension_m - DEFAULT_EXTERNAL_EXTENSION_M) < 1e-9:
            report.warnings.append(
                f"Extensao externa padrao de {DEFAULT_EXTERNAL_EXTENSION_M:.0f} m e configuravel, "
                "nao obrigatoria."
            )

    if not config.has_complete_machine_params():
        report.warnings.append(
            "Parametros da maquina incompletos (raio minimo ausente); voltas serao ESTIMADAS."
        )

    if config.implement_mounted is False:
        report.warnings.append(
            "Implemento rebocado: espaco extra aplicado; verifique risco de cortar caminho."
        )

    if config.is_special_maneuver():
        report.warnings.append(
            "Volta de tres pontos marcada como manobra especial (sem giro continuo)."
        )

    return report


def validate_turn_paths(
    result: TurnPathResult,
    config: TurnConfiguration,
    areas: BoundaryAreas | None = None,
    *,
    allow_save_invalid: bool = False,
) -> TurnValidationReport:
    """Valida resultado do motor e monta relatorio de exportacao."""
    report = validate_turn_configuration(config, areas)
    if report.errors and not result.turns:
        report.turns_summary = result.report
        return report

    status_counts: dict[str, int] = {}
    for turn in result.turns:
        status_counts[turn.status] = status_counts.get(turn.status, 0) + 1
        if turn.is_estimated:
            report.estimated_count += 1
        if turn.status == TurnStatus.IMPOSSIBLE.value:
            report.invalid_count += 1
            msg = f"Volta {turn.sequence_no} ({turn.from_pass}->{turn.to_pass}) impossivel."
            if (
                turn.outside_boundary
                and turn.configured_extension_m is not None
                and turn.minimum_extension_m is not None
                and turn.configured_extension_m + 1e-9 < turn.minimum_extension_m
            ):
                msg += (
                    f" Extensao {turn.configured_extension_m:.2f} m < "
                    f"minima {turn.minimum_extension_m:.2f} m."
                )
            report.errors.append(msg)
        elif turn.status == TurnStatus.VALID_LOW_MARGIN.value:
            report.warnings.append(
                f"Volta {turn.sequence_no}: margem baixa "
                f"({turn.clearance_m:.2f} m < recomendado {config.safety.recommended_clearance_m:.2f} m)."
            )
        elif turn.status == TurnStatus.INSUFFICIENT_DATA.value:
            report.warnings.append(
                f"Volta {turn.sequence_no}: dados insuficientes (estimada)."
            )

        if turn.from_pass == turn.to_pass:
            report.errors.append(
                f"Volta {turn.sequence_no}: linhas de origem e destino nao sao compativeis."
            )

    savable = filter_savable_turns(result.turns)
    report.savable_count = len(savable)
    report.turns_summary = {
        **result.report,
        "status_counts": status_counts,
        "savable_count": report.savable_count,
        "invalid_count": report.invalid_count,
        "estimated_count": report.estimated_count,
    }

    if report.invalid_count and not allow_save_invalid:
        report.errors.append(
            "Existem voltas invalidas; remova-as ou confirme antes de salvar."
        )

    return report


def assert_can_save_turns(report: TurnValidationReport, *, confirm_invalid: bool = False) -> None:
    """Bloqueia salvamento de voltas invalidas sem confirmacao."""
    if confirm_invalid:
        remaining = [
            err
            for err in report.errors
            if "voltas invalidas" not in err.lower()
        ]
        if remaining:
            raise TurnConfigurationError("; ".join(remaining))
        return
    if report.errors:
        raise TurnConfigurationError("; ".join(report.errors))
