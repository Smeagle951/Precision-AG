# -*- coding: utf-8 -*-
"""Ferramenta de mapa para escolher as passadas reais de pulverizacao com cliques."""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.core import (
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
)
from qgis.gui import QgsMapTool

from ...core.preview_layer_names import is_planting_preview_line_layer
from ..layer_combo_utils import is_line_like_vector_layer

PICK_TOLERANCE_PX = 8


def spray_pick_candidate_layers(project=None) -> list[QgsVectorLayer]:
    """Camadas de linha visiveis na arvore, sem as linhas/passadas de plantio."""
    project = project or QgsProject.instance()
    root = project.layerTreeRoot()
    layers = []
    for node in root.findLayers():
        layer = node.layer()
        if (
            node.isVisible()
            and is_line_like_vector_layer(layer)
            and not is_planting_preview_line_layer(layer)
        ):
            layers.append(layer)
    return layers


def pick_line_feature(layers, point: QgsPointXY, map_crs, tolerance: float, preferred=None, project=None):
    """(camada, fid) da linha mais proxima do clique, ou None fora da tolerancia.

    Distancias medidas no CRS do mapa; empate favorece a camada preferida.
    """
    project = project or QgsProject.instance()
    best = None
    click = QgsGeometry.fromPointXY(point)
    area = QgsRectangle(
        point.x() - tolerance, point.y() - tolerance, point.x() + tolerance, point.y() + tolerance
    )
    for layer in layers:
        to_layer = QgsCoordinateTransform(map_crs, layer.crs(), project)
        to_map = QgsCoordinateTransform(layer.crs(), map_crs, project)
        try:
            search = to_layer.transformBoundingBox(area)
        except Exception:
            continue
        request = QgsFeatureRequest().setFilterRect(search).setNoAttributes()
        for feature in layer.getFeatures(request):
            geometry = QgsGeometry(feature.geometry())
            if geometry.isEmpty():
                continue
            try:
                geometry.transform(to_map)
            except Exception:
                continue
            dist = geometry.distance(click)
            if dist > tolerance:
                continue
            rank = (dist, 0 if layer is preferred else 1)
            if best is None or rank < best[0]:
                best = (rank, layer, feature.id())
    return None if best is None else (best[1], best[2])


class SprayPassPickTool(QgsMapTool):
    """Clique seleciona a passada e conclui; Shift+clique soma e Enter/botao direito conclui.

    Esc cancela e devolve a selecao que as camadas tinham antes.
    """

    finished = pyqtSignal(object)
    message = pyqtSignal(str)

    def __init__(self, canvas, preferred_layer=None, project=None):
        super().__init__(canvas)
        self.canvas = canvas
        self.preferred_layer = preferred_layer
        self.project = project or QgsProject.instance()
        self.picked_layer = None
        self._original_selection: dict[str, tuple[QgsVectorLayer, list[int]]] = {}
        self._done = False
        # Outra ferramenta assumiu o mapa: quem chamou nao deve restaurar a anterior.
        self.switched_away = False
        self.setCursor(Qt.CrossCursor)

    def canvasReleaseEvent(self, event):
        if self._done:
            return
        if event.button() == Qt.RightButton:
            self._finish(self.picked_layer)
            return
        point = QgsPointXY(self.toMapCoordinates(event.pos()))
        hit = pick_line_feature(
            spray_pick_candidate_layers(self.project),
            point,
            self.canvas.mapSettings().destinationCrs(),
            self.canvas.mapUnitsPerPixel() * PICK_TOLERANCE_PX,
            preferred=self.picked_layer or self.preferred_layer,
            project=self.project,
        )
        if hit is None:
            self.message.emit("Nenhuma linha de pulverizacao visivel perto do clique.")
            return
        layer, fid = hit
        add = bool(event.modifiers() & Qt.ShiftModifier)
        self.select(layer, fid, add=add)
        if not add:
            self._finish(layer)
        else:
            self.message.emit(
                f"{layer.name()}: {layer.selectedFeatureCount()} passada(s) selecionada(s). "
                "Enter ou botao direito conclui."
            )

    def select(self, layer: QgsVectorLayer, fid: int, *, add: bool) -> None:
        if self.picked_layer is not None and layer is not self.picked_layer:
            self._remember(self.picked_layer)
            self.picked_layer.removeSelection()
        self._remember(layer)
        if add and layer is self.picked_layer:
            ids = set(layer.selectedFeatureIds())
            ids.symmetric_difference_update({fid})
            layer.selectByIds(sorted(ids))
        else:
            layer.selectByIds([fid])
        self.picked_layer = layer

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.cancel()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._finish(self.picked_layer)

    def cancel(self) -> None:
        if self._done:
            return
        for layer, ids in self._original_selection.values():
            layer.selectByIds(ids)
        self._finish(None)

    def deactivate(self):
        if not self._done:
            self.switched_away = True
            self._finish(self.picked_layer)
        super().deactivate()

    def _remember(self, layer: QgsVectorLayer) -> None:
        if layer.id() not in self._original_selection:
            self._original_selection[layer.id()] = (layer, list(layer.selectedFeatureIds()))

    def _finish(self, layer) -> None:
        if self._done:
            return
        self._done = True
        self.finished.emit(layer)
