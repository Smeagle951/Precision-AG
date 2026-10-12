# -*- coding: utf-8 -*-
"""Montagem e avaliacao do contrato intermediario para exportadores."""

from __future__ import annotations

from ..domain.operational_contract import (
    ExportOperationBundle,
    ExportSemanticReport,
    ExporterCapabilities,
    OperationalGeneration,
)


def build_export_operation_bundle(
    generation: OperationalGeneration,
    *,
    target_crs: str = "",
) -> ExportOperationBundle:
    """Constroi bundle somente a partir da geracao canonica persistida."""
    generation.validate()
    bundle = ExportOperationBundle(
        manifest=generation.manifest,
        planting_rows=generation.planting_rows,
        spray_passes=generation.spray_passes,
        tire_tracks=generation.tire_tracks,
        shutoff_segments=generation.segments,
        relations=generation.relations,
        source_crs=generation.manifest.source_crs,
        working_crs=generation.manifest.working_crs,
        target_crs=target_crs,
    )
    bundle.validate()
    return bundle


def assess_export_capabilities(
    bundle: ExportOperationBundle,
    capabilities: ExporterCapabilities,
) -> ExportSemanticReport:
    """Relata perda semantica; nunca converte nem descarta silenciosamente."""
    bundle.validate()
    warnings: list[str] = []
    native: dict[str, int] = {}
    auxiliary: dict[str, int] = {}
    skipped: dict[str, int] = {}

    def classify(role: str, count: int, supported: bool) -> None:
        if count <= 0:
            return
        if supported:
            native[role] = count
            return
        if capabilities.auxiliary_layers:
            auxiliary[role] = count
            warnings.append(
                f"{role}: {count} objeto(s) sem representacao nativa; enviar como camada auxiliar."
            )
        else:
            skipped[role] = count
            warnings.append(
                f"{role}: {count} objeto(s) sem suporte no formato alvo; exportacao exige decisao explicita."
            )

    classify("PLANTING_ROW", len(bundle.planting_rows), capabilities.supports_guidance)
    classify("SPRAY_PASS", len(bundle.spray_passes), capabilities.supports_guidance)
    classify("TIRE_TRACK", len(bundle.tire_tracks), capabilities.supports_tire_tracks)
    classify("SHUTOFF", len(bundle.shutoff_segments), capabilities.supports_work_states)
    return ExportSemanticReport(
        exporter_name=capabilities.name,
        generation_id=bundle.manifest.generation_id,
        warnings=tuple(warnings),
        native_counts=native,
        auxiliary_counts=auxiliary,
        skipped_counts=skipped,
    )
