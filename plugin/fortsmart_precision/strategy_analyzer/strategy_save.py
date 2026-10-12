# -*- coding: utf-8 -*-
"""Materializa o candidato escolhido como a unica camada 12_Passadas_Plantio (WORK_PATH)."""

from __future__ import annotations

from dataclasses import dataclass, field

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor, QFont
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsLineSymbol,
    QgsPalLayerSettings,
    QgsPointXY,
    QgsProject,
    QgsSingleSymbolRenderer,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)

from ..core.layer_roles import (
    LEGACY_INTERNAL_KEY_PROPERTY,
    layer_role_definition,
    set_layer_role_properties,
)
from ..core.parallel_pass_engine import line_label_for_pass
from ..core.persistence_manager import FortSmartPersistenceManager, PersistenceError
from ..core.planting_line_cut_engine import line_id_for
from .models import ANALYSIS_VERSION, STRATEGY_SAVE_FAILED, StrategyAnalysisError, StrategyCandidate

WORK_PATH_KEY = "06_Passadas_Plantio"
SAVE_REPLACE = "replace"
SAVE_NEW_VERSION = "version"

STRATEGY_TYPE_PROPERTY = "strategy_type"
STRATEGY_ANGLE_PROPERTY = "strategy_angle"
STRATEGY_ANALYZED_PROPERTY = "strategy_analyzed"
ANALYSIS_VERSION_PROPERTY = "analysis_version"
STRATEGY_VERSION_PROPERTY = "strategy_version"
SOURCE_CANDIDATE_PROPERTY = "source_candidate_id"

_FIELDS = (
    ("line_id", QVariant.String),
    ("line_number", QVariant.Int),
    ("line_no", QVariant.Int),
    ("pass_id", QVariant.Int),
    ("label", QVariant.String),
    ("spacing_m", QVariant.Double),
    ("width_m", QVariant.Double),
    ("strategy_type", QVariant.String),
    ("strategy_angle", QVariant.Double),
    ("strategy_version", QVariant.Int),
    ("source_candidate_id", QVariant.String),
)


@dataclass
class MaterializeResult:
    layer: QgsVectorLayer
    persisted: bool
    version: int
    archived_table: str | None = None
    path: str = ""
    warnings: list = field(default_factory=list)


def work_path_definition():
    return layer_role_definition(WORK_PATH_KEY)


def existing_work_path(project, field_name) -> list:
    """Camadas definitivas WORK_PATH do talhao (memoria ou GPKG), sem previews."""
    from ..gui.layer_tree_organizer import generated_layers_for_role

    return generated_layers_for_role(project, work_path_definition().role, field_name)


def has_existing_work_path(project, field_name) -> bool:
    if existing_work_path(project, field_name):
        return True
    manager = FortSmartPersistenceManager(project)
    if not (manager.storage_available() and field_name):
        return False
    path = manager.get_field_storage_path(field_name)
    return manager.table_feature_count(path, work_path_definition().display_name) is not None


def _current_version(project, field_name) -> int:
    versions = [
        int(layer.customProperty(STRATEGY_VERSION_PROPERTY, 0) or 0)
        for layer in existing_work_path(project, field_name)
    ]
    manager = FortSmartPersistenceManager(project)
    if manager.storage_available() and field_name:
        path = manager.get_field_storage_path(field_name)
        versions.extend(manager.archived_versions(path, work_path_definition().display_name))
    return max(versions, default=0)


def _enable_labels(layer: QgsVectorLayer) -> None:
    settings = QgsPalLayerSettings()
    settings.fieldName = "label"
    settings.enabled = True
    settings.placement = QgsPalLayerSettings.Line
    text = QgsTextFormat()
    text.setSize(9)
    text.setColor(QColor(0, 100, 0))
    text.setFont(QFont("Arial", 9, QFont.Bold))
    settings.setFormat(text)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)


def build_work_path_layer(
    candidate: StrategyCandidate,
    crs_authid: str,
    field_name: str | None,
    *,
    version: int,
) -> QgsVectorLayer:
    """Mesmos campos/rotulos de 06_Passadas_Plantio do Workspace + campos de versao."""
    definition = work_path_definition()
    layer = QgsVectorLayer(f"LineString?crs={crs_authid}", definition.display_name, "memory")
    provider = layer.dataProvider()
    provider.addAttributes([QgsField(name, kind) for name, kind in _FIELDS])
    layer.updateFields()
    angle = candidate.angle_deg
    features = []
    for line in candidate.lines:
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in line.points]))
        feature.setAttributes(
            [
                line_id_for(line.pass_no),
                line.pass_no,
                line.pass_no,
                line.pass_no,
                line_label_for_pass(line.pass_no, machine_prefix="P"),
                line.spacing_m,
                line.width_m,
                candidate.strategy_type.value,
                angle,
                version,
                candidate.candidate_id,
            ]
        )
        features.append(feature)
    provider.addFeatures(features)
    layer.updateExtents()
    layer.setCustomProperty(LEGACY_INTERNAL_KEY_PROPERTY, WORK_PATH_KEY)
    set_layer_role_properties(layer, definition, field_name=field_name)
    symbol = QgsLineSymbol.createSimple(
        {"color": "20,160,20", "width": "0.6", "capstyle": "round", "joinstyle": "round"}
    )
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    _enable_labels(layer)
    return layer


def apply_strategy_metadata(layer, candidate: StrategyCandidate, version: int) -> None:
    layer.setCustomProperty(STRATEGY_TYPE_PROPERTY, candidate.strategy_type.value)
    layer.setCustomProperty(STRATEGY_ANGLE_PROPERTY, "" if candidate.angle_deg is None else candidate.angle_deg)
    layer.setCustomProperty(STRATEGY_ANALYZED_PROPERTY, True)
    layer.setCustomProperty(ANALYSIS_VERSION_PROPERTY, ANALYSIS_VERSION)
    layer.setCustomProperty(STRATEGY_VERSION_PROPERTY, version)
    layer.setCustomProperty(SOURCE_CANDIDATE_PROPERTY, candidate.candidate_id)


def materialize_as_work_path(
    candidate: StrategyCandidate,
    *,
    crs_authid: str,
    field_name: str | None,
    mode: str = SAVE_REPLACE,
    project=None,
) -> MaterializeResult:
    """Grava so o candidato escolhido; previews e demais candidatos nao sao tocados.

    replace: substitui a 12_Passadas_Plantio do talhao. version: arquiva a tabela
    atual como 12_Passadas_Plantio_v{n} no GPKG (exige projeto salvo) e grava a nova.
    """
    project = project or QgsProject.instance()
    if not candidate.valid or not candidate.lines:
        raise StrategyAnalysisError(STRATEGY_SAVE_FAILED, f"{STRATEGY_SAVE_FAILED}: candidato inválido.")
    if mode not in (SAVE_REPLACE, SAVE_NEW_VERSION):
        raise ValueError(f"Modo de gravação desconhecido: {mode}")
    from ..gui.layer_tree_organizer import place_generated_result, publish_persisted

    definition = work_path_definition()
    manager = FortSmartPersistenceManager(project)
    persist = manager.storage_available() and bool(field_name)
    if mode == SAVE_NEW_VERSION and not persist:
        raise StrategyAnalysisError(
            STRATEGY_SAVE_FAILED, f"{STRATEGY_SAVE_FAILED}: salve o projeto QGIS para manter versões."
        )
    if not persist:
        version = _current_version(project, field_name) + 1
        layer = build_work_path_layer(candidate, crs_authid, field_name, version=version)
        apply_strategy_metadata(layer, candidate, version)
        place_generated_result(project, layer, definition, field_name)
        if not field_name and project.mapLayer(layer.id()) is None:
            project.addMapLayer(layer)
        return MaterializeResult(layer, False, version)
    try:
        archived = manager.archive_role_table(field_name, definition) if mode == SAVE_NEW_VERSION else None
        version = _current_version(project, field_name) + 1
        layer = build_work_path_layer(candidate, crs_authid, field_name, version=version)
        apply_strategy_metadata(layer, candidate, version)
        stored = manager.persist_layer(layer, definition, field_name)
    except PersistenceError as exc:
        raise StrategyAnalysisError(STRATEGY_SAVE_FAILED, f"{STRATEGY_SAVE_FAILED}: {exc}") from exc
    final = publish_persisted(
        project, layer, stored.layer, reused=stored.reused_layer, field_name=field_name, definition=definition
    )
    apply_strategy_metadata(final, candidate, version)
    final.triggerRepaint()
    return MaterializeResult(final, True, version, archived, stored.path, list(stored.warnings))
