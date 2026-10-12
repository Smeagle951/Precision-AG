# -*- coding: utf-8 -*-
"""Previews temporarios (memoria) dos candidatos; sem fortsmart_role, nunca exportados."""

from __future__ import annotations

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsLineSymbol,
    QgsPointXY,
    QgsProject,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
)

from ..core.layer_roles import (
    FIELD_ID_PROPERTY,
    STRATEGY_PREVIEW_PROPERTY,
    TEMPORARY_PREVIEW_PROPERTY,
    canonical_field_name,
)
from .models import STRATEGY_PREVIEW_FAILED, StrategyAnalysisError, StrategyCandidate, StrategyType

CANDIDATE_PROPERTY = "fortsmart_strategy_candidate"
PREVIEW_STRAIGHT_NAME = "PREVIEW_RETA"
PREVIEW_CURVE_NAME = "PREVIEW_CURVA"

_STYLES = {
    StrategyType.STRAIGHT: {"color": "30,110,230", "width": "0.8", "line_style": "dash"},
    StrategyType.CURVE: {"color": "235,120,0", "width": "0.9", "line_style": "solid"},
}


def preview_layers(project, field_name=None) -> list[QgsVectorLayer]:
    field_id = canonical_field_name(field_name) if field_name else ""
    return [
        layer
        for layer in project.mapLayers().values()
        if str(layer.customProperty(STRATEGY_PREVIEW_PROPERTY, "")).lower() in ("true", "1")
        and (not field_id or layer.customProperty(FIELD_ID_PROPERTY, "") in ("", field_id))
    ]


class StrategyPreviewManager:
    """Um preview por candidato; mostrar de novo substitui. Alteracoes so na thread principal."""

    def __init__(self, crs_authid: str, field_name: str | None = None, project=None):
        self.project = project or QgsProject.instance()
        self.crs_authid = crs_authid
        self.field_name = field_name
        self._layers: dict[str, str] = {}

    def _name_for(self, candidate: StrategyCandidate) -> str:
        if candidate.strategy_type is StrategyType.CURVE:
            return PREVIEW_CURVE_NAME
        taken = [
            layer_id for cid, layer_id in self._layers.items()
            if cid != candidate.candidate_id and self.project.mapLayer(layer_id) is not None
            and self.project.mapLayer(layer_id).name().startswith(PREVIEW_STRAIGHT_NAME)
        ]
        suffix = f"_{len(taken) + 1}" if taken else ""
        return f"{PREVIEW_STRAIGHT_NAME}{suffix} {candidate.label.split(' ', 1)[-1]}"

    def _target_group(self):
        root = self.project.layerTreeRoot()
        if not self.field_name:
            return root
        from ..gui.layer_tree_organizer import preview_group, project_group

        return preview_group(project_group(root, self.field_name))

    def build_layer(self, candidate: StrategyCandidate) -> QgsVectorLayer:
        layer = QgsVectorLayer(f"LineString?crs={self.crs_authid}", self._name_for(candidate), "memory")
        if not layer.isValid():
            raise StrategyAnalysisError(STRATEGY_PREVIEW_FAILED)
        provider = layer.dataProvider()
        provider.addAttributes(
            [
                QgsField("candidate_id", QVariant.String),
                QgsField("strategy_type", QVariant.String),
                QgsField("pass_no", QVariant.Int),
                QgsField("length_m", QVariant.Double),
            ]
        )
        layer.updateFields()
        features = []
        for line in candidate.lines:
            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in line.points]))
            feature.setAttributes(
                [candidate.candidate_id, candidate.strategy_type.value, line.pass_no, round(line.length_m, 3)]
            )
            features.append(feature)
        if features and not provider.addFeatures(features)[0]:
            raise StrategyAnalysisError(STRATEGY_PREVIEW_FAILED)
        layer.updateExtents()
        layer.setCustomProperty(STRATEGY_PREVIEW_PROPERTY, True)
        layer.setCustomProperty(TEMPORARY_PREVIEW_PROPERTY, True)
        layer.setCustomProperty(CANDIDATE_PROPERTY, candidate.candidate_id)
        if self.field_name:
            layer.setCustomProperty(FIELD_ID_PROPERTY, canonical_field_name(self.field_name))
        symbol = QgsLineSymbol.createSimple(dict(_STYLES.get(candidate.strategy_type, _STYLES[StrategyType.STRAIGHT])))
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        return layer

    def show_candidate(self, candidate: StrategyCandidate) -> QgsVectorLayer:
        self.hide_candidate(candidate.candidate_id)
        try:
            layer = self.build_layer(candidate)
            self.project.addMapLayer(layer, False)
            self._target_group().insertLayer(0, layer)
        except StrategyAnalysisError:
            raise
        except Exception as exc:
            raise StrategyAnalysisError(STRATEGY_PREVIEW_FAILED, f"{STRATEGY_PREVIEW_FAILED}: {exc}") from exc
        self._layers[candidate.candidate_id] = layer.id()
        return layer

    def layer_for(self, candidate_id: str) -> QgsVectorLayer | None:
        layer_id = self._layers.get(candidate_id)
        return self.project.mapLayer(layer_id) if layer_id else None

    def set_visible(self, candidate_id: str, visible: bool) -> None:
        layer = self.layer_for(candidate_id)
        node = self.project.layerTreeRoot().findLayer(layer.id()) if layer is not None else None
        if node is not None:
            node.setItemVisibilityChecked(visible)

    def is_visible(self, candidate_id: str) -> bool:
        layer = self.layer_for(candidate_id)
        node = self.project.layerTreeRoot().findLayer(layer.id()) if layer is not None else None
        return bool(node is not None and node.itemVisibilityChecked())

    def show_only(self, candidate_ids) -> None:
        """Mapa mostra so estes previews (RETA, CURVA ou os dois em COMPARAR)."""
        wanted = set(candidate_ids)
        for candidate_id in list(self._layers):
            self.set_visible(candidate_id, candidate_id in wanted)

    def combined_extent(self):
        extent = None
        for candidate_id in self._layers:
            layer = self.layer_for(candidate_id)
            if layer is None or layer.featureCount() == 0:
                continue
            if extent is None:
                extent = layer.extent()
            else:
                extent.combineExtentWith(layer.extent())
        return extent

    def hide_candidate(self, candidate_id: str) -> None:
        layer_id = self._layers.pop(candidate_id, None)
        if layer_id and self.project.mapLayer(layer_id) is not None:
            self.project.removeMapLayer(layer_id)

    def clear_previews(self) -> None:
        """Remove os previews deste gerenciador e sobras de sessoes anteriores do talhao."""
        ids = set(self._layers.values()) | {layer.id() for layer in preview_layers(self.project, self.field_name)}
        self._layers.clear()
        existing = [layer_id for layer_id in ids if self.project.mapLayer(layer_id) is not None]
        if existing:
            self.project.removeMapLayers(existing)
        if self.field_name:
            from ..gui.layer_tree_organizer import preview_group, project_group, remove_group_if_empty

            group = project_group(self.project.layerTreeRoot(), self.field_name, create=False)
            if group is not None:
                remove_group_if_empty(preview_group(group, create=False))
