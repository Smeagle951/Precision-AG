# -*- coding: utf-8 -*-
"""Gerenciador central de previas no canvas (Subfase 0E).

So desenha QgsRubberBand: nao cria camada, GeoPackage nem altera camadas do
projeto. Limpa sozinho quando o projeto e trocado ou quando a camada de origem
de uma previa e removida.
"""

from __future__ import annotations

from dataclasses import dataclass

from qgis.core import QgsCoordinateReferenceSystem, QgsProject, QgsWkbTypes
from qgis.gui import QgsRubberBand
from qgis.PyQt.QtCore import QObject, Qt
from qgis.PyQt.QtGui import QColor

STYLE_LINE = "line"
STYLE_POLYGON = "polygon"
STYLE_POINT = "point"
STYLE_HIGHLIGHT = "highlight"
STYLE_REFERENCE = "reference"
STYLE_WARNING = "warning"
STYLE_START = "start"
STYLE_END = "end"

_LINE_STYLES = {"solid": Qt.SolidLine, "dash": Qt.DashLine, "dot": Qt.DotLine}
_ICONS = {"circle": QgsRubberBand.ICON_CIRCLE, "box": QgsRubberBand.ICON_BOX, "x": QgsRubberBand.ICON_X}


@dataclass(frozen=True)
class PreviewStyle:
    color: tuple
    width: float = 2.0
    line: str = "solid"
    fill_alpha: int = 0
    icon: str = "circle"
    icon_size: int = 10


DEFAULT_STYLES = {
    STYLE_LINE: PreviewStyle((30, 90, 200, 255), 3.0),
    STYLE_POLYGON: PreviewStyle((230, 120, 0, 255), 2.0, fill_alpha=50),
    STYLE_POINT: PreviewStyle((30, 90, 200, 255), 2.0, icon_size=12),
    STYLE_HIGHLIGHT: PreviewStyle((255, 140, 0, 255), 5.0, fill_alpha=40),
    STYLE_REFERENCE: PreviewStyle((110, 110, 110, 255), 1.5, line="dash"),
    STYLE_WARNING: PreviewStyle((210, 30, 30, 255), 3.0, line="dot", fill_alpha=40, icon="x"),
    STYLE_START: PreviewStyle((20, 150, 60, 255), 2.0, icon="circle", icon_size=12),
    STYLE_END: PreviewStyle((200, 30, 30, 255), 2.0, icon="box", icon_size=12),
}


def _geometry_kind(geometry):
    return QgsWkbTypes.geometryType(geometry.wkbType())


class PreviewManager(QObject):
    """Bandas agrupadas por (estilo, tipo de geometria, camada de origem)."""

    def __init__(self, canvas, project=None, parent=None):
        super().__init__(parent)
        self._canvas = canvas
        self._project = project if project is not None else QgsProject.instance()
        self._styles = dict(DEFAULT_STYLES)
        self._bands: dict = {}
        self._counts: dict = {}
        self._connections: list = []
        self._disposed = False

    # ------------------------------------------------------------ estado --
    @property
    def count(self) -> int:
        return sum(self._counts.values())

    @property
    def band_count(self) -> int:
        return len(self._bands)

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    @property
    def disposed(self) -> bool:
        return self._disposed

    def register_style(self, name: str, style: PreviewStyle) -> None:
        self._styles[name] = style

    def style(self, name) -> PreviewStyle:
        if isinstance(name, PreviewStyle):
            return name
        if name not in self._styles:
            raise KeyError(f"Estilo de prévia desconhecido: {name}")
        return self._styles[name]

    # ------------------------------------------------------------ sinais --
    def _connect(self):
        if self._connections:
            return
        pairs = [
            (self._project.cleared, self._on_project_reset),
            (self._project.readProject, self._on_project_reset),
            (self._project.layersWillBeRemoved, self._on_layers_will_be_removed),
            (self._canvas.destroyed, self._on_canvas_destroyed),
        ]
        for signal, slot in pairs:
            signal.connect(slot)
            self._connections.append((signal, slot))

    def _disconnect(self):
        for signal, slot in self._connections:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._connections = []

    def _on_project_reset(self, *args):
        self.clear()

    def _on_layers_will_be_removed(self, layer_ids):
        for layer_id in set(layer_ids or ()):
            self.clear(source_layer_id=layer_id)

    def _on_canvas_destroyed(self, *args):
        self._bands = {}
        self._counts = {}
        self._canvas = None
        self._disconnect()
        self._disposed = True

    # ------------------------------------------------------------- desenho --
    def _band(self, style_name, style: PreviewStyle, kind, source_layer_id):
        key = (style_name if not isinstance(style_name, PreviewStyle) else id(style_name), int(kind), source_layer_id)
        band = self._bands.get(key)
        if band is not None:
            return key, band
        band = QgsRubberBand(self._canvas, kind)
        color = QColor(*style.color)
        band.setStrokeColor(color)
        fill = QColor(color)
        fill.setAlpha(style.fill_alpha)
        band.setFillColor(fill)
        band.setWidth(style.width)
        band.setLineStyle(_LINE_STYLES.get(style.line, Qt.SolidLine))
        if kind == QgsWkbTypes.PointGeometry:
            band.setIcon(_ICONS.get(style.icon, QgsRubberBand.ICON_CIRCLE))
            band.setIconSize(style.icon_size)
        self._bands[key] = band
        self._counts[key] = 0
        return key, band

    def show_geometry(self, geometry, style=STYLE_LINE, *, crs=None, source_layer_id=None) -> bool:
        """Desenha uma geometria; `crs` e o da geometria (reprojeta para o canvas)."""
        if self._disposed or self._canvas is None:
            raise RuntimeError("Gerenciador de prévia já descartado.")
        if geometry is None or geometry.isNull() or geometry.isEmpty():
            return False
        kind = _geometry_kind(geometry)
        if kind not in (QgsWkbTypes.PointGeometry, QgsWkbTypes.LineGeometry, QgsWkbTypes.PolygonGeometry):
            return False
        self._connect()
        key, band = self._band(style, self.style(style), kind, source_layer_id)
        band.addGeometry(geometry, crs if crs is not None else QgsCoordinateReferenceSystem())
        self._counts[key] += 1
        return True

    def show_geometries(self, geometries, styles=STYLE_LINE, *, crs=None, source_layer_id=None) -> int:
        """`styles` e um estilo para todas ou uma sequencia alinhada com `geometries`."""
        geometries = list(geometries)
        if isinstance(styles, (str, PreviewStyle)):
            styles = [styles] * len(geometries)
        styles = list(styles)
        if len(styles) != len(geometries):
            raise ValueError("Quantidade de estilos diferente da quantidade de geometrias.")
        return sum(
            1 for geometry, style in zip(geometries, styles)
            if self.show_geometry(geometry, style, crs=crs, source_layer_id=source_layer_id)
        )

    def clear(self, source_layer_id=None) -> int:
        """Remove todas as previas, ou so as da camada de origem indicada."""
        removed = 0
        for key in [key for key in self._bands if source_layer_id is None or key[2] == source_layer_id]:
            band = self._bands.pop(key)
            removed += self._counts.pop(key, 0)
            try:
                band.reset()
                if self._canvas is not None:
                    self._canvas.scene().removeItem(band)
            except RuntimeError:
                pass
        if not self._bands:
            self._disconnect()
        return removed

    def dispose(self) -> None:
        if self._disposed:
            return
        self.clear()
        self._disconnect()
        self._canvas = None
        self._disposed = True
