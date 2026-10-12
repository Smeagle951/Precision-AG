# -*- coding: utf-8 -*-
"""Ferramenta manual "Desvio de Obstáculo": uma linha + um obstaculo por vez.

A pre-visualizacao usa rubber bands no mapa (nenhuma camada e criada ou
alterada). So APLICAR edita a linha escolhida, com confirmacao e Ctrl+Z.
"""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)
from qgis.core import QgsGeometry, QgsMapLayerProxyModel, QgsProject, QgsVectorLayer, QgsWkbTypes
from qgis.gui import QgsMapLayerComboBox, QgsMapToolIdentifyFeature, QgsRubberBand

from ..core.obstacle_detour import (
    DETOUR_TYPE_LABELS,
    LINE_DIRECTION_LABELS,
    V1_DETOUR_TYPES,
    DetourParameters,
    DetourType,
    LineDirection,
    selection_error,
    suggest_lateral_distances,
)
from ..core.obstacle_detour.models import MSG_SELECT_LINE, MSG_SELECT_OBSTACLE
from ..core.planting_line_cut_engine import obstacle_layer_priority
from .obstacle_detour_service import (
    DetourServiceError,
    active_record,
    apply_detour,
    compute_detour,
    ensure_detour_layer,
    field_layer_priority,
    find_detour_layer,
    implement_width_from,
    is_area_obstacle,
    line_label,
    obstacle_label,
    obstacle_radius_from,
    restore_original,
    to_qgs,
    to_shapely,
    transformed,
)

TOOL_TITLE = "↪ Desvio de Obstáculo"
TOOL_TOOLTIP = "Criar desvio manual de uma linha ao redor de um obstáculo"

ORIGINAL_COLOR = QColor(130, 130, 130, 230)
PATH_COLOR = QColor(30, 110, 230, 255)
ZONE_COLOR = QColor(220, 40, 40, 70)
ZONE_OUTLINE = QColor(200, 30, 30, 255)
CONTROL_COLOR = QColor(250, 210, 0, 255)
SELECTION_COLOR = QColor(255, 140, 0, 220)


class DetourPreview:
    """Camadas visuais temporarias no canvas; nunca tocam os dados."""

    def __init__(self, canvas):
        self.canvas = canvas
        self.bands: list[QgsRubberBand] = []

    def _band(self, geometry_type, color, width=2.0, fill=None, style=Qt.SolidLine):
        band = QgsRubberBand(self.canvas, geometry_type)
        band.setStrokeColor(color)
        band.setWidth(width)
        band.setLineStyle(style)
        if fill is not None:
            band.setFillColor(fill)
        self.bands.append(band)
        return band

    def clear(self) -> None:
        for band in self.bands:
            band.reset()
            self.canvas.scene().removeItem(band)
        self.bands = []

    def highlight(self, geometry: QgsGeometry, crs) -> None:
        geometry_type = QgsWkbTypes.geometryType(geometry.wkbType())
        if geometry_type == QgsWkbTypes.PointGeometry:
            band = self._band(QgsWkbTypes.PointGeometry, SELECTION_COLOR, 3.0)
            band.setIcon(QgsRubberBand.ICON_CIRCLE)
            band.setIconSize(14)
        elif geometry_type == QgsWkbTypes.PolygonGeometry:
            band = self._band(QgsWkbTypes.PolygonGeometry, SELECTION_COLOR, 3.0, QColor(255, 140, 0, 50))
        else:
            band = self._band(QgsWkbTypes.LineGeometry, SELECTION_COLOR, 5.0)
        band.setToGeometry(geometry, crs)

    def show(self, computation, obstacle_geometry: QgsGeometry, obstacle_crs) -> None:
        detour = computation.detour
        metric = computation.metric_crs
        if detour.safety_zone is not None:
            zone = self._band(QgsWkbTypes.PolygonGeometry, ZONE_OUTLINE, 1.0, ZONE_COLOR)
            zone.setToGeometry(to_qgs(detour.safety_zone), metric)
        if detour.clearance_zone is not None:
            clearance = self._band(QgsWkbTypes.LineGeometry, ZONE_OUTLINE, 1.0, style=Qt.DashLine)
            clearance.setToGeometry(to_qgs(detour.clearance_zone.boundary), metric)
        self.highlight(obstacle_geometry, obstacle_crs)
        original = self._band(QgsWkbTypes.LineGeometry, ORIGINAL_COLOR, 2.0, style=Qt.DashLine)
        original.setToGeometry(to_qgs(detour.original_geometry), metric)
        if detour.ok and detour.result_geometry is not None:
            path = self._band(QgsWkbTypes.LineGeometry, PATH_COLOR, 3.0)
            path.setToGeometry(to_qgs(detour.result_geometry), metric)
        if detour.control_points:
            points = self._band(QgsWkbTypes.PointGeometry, CONTROL_COLOR, 2.0)
            points.setIcon(QgsRubberBand.ICON_CIRCLE)
            points.setIconSize(10)
            points.setFillColor(CONTROL_COLOR)
            for x, y in detour.control_points:
                points.addGeometry(QgsGeometry.fromWkt(f"POINT ({x!r} {y!r})"), metric)


def _spin(value: float, maximum: float = 500.0, suffix: str = " m") -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setDecimals(2)
    spin.setRange(0.0, maximum)
    spin.setSingleStep(0.25)
    spin.setValue(value)
    spin.setSuffix(suffix)
    return spin


class ObstacleDetourDialog(QDialog):
    """Painel compacto do desvio manual."""

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.setWindowTitle(TOOL_TITLE)
        self.line_fid: int | None = None
        self.obstacle_fid: int | None = None
        self.computation = None
        self.previous_tool = None
        self.pick_tool = None
        self.preview = DetourPreview(self.canvas)
        self._build_ui()
        self._auto_select_layers()
        self._update_summary()

    # --- UI -----------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.line_combo = QgsMapLayerComboBox()
        self.line_combo.setFilters(QgsMapLayerProxyModel.LineLayer)
        self.obstacle_combo = QgsMapLayerComboBox()
        self.obstacle_combo.setFilters(
            QgsMapLayerProxyModel.PointLayer | QgsMapLayerProxyModel.LineLayer | QgsMapLayerProxyModel.PolygonLayer
        )
        self.field_combo = QgsMapLayerComboBox()
        self.field_combo.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        self.field_combo.setAllowEmptyLayer(True)
        self.field_combo.setLayer(None)
        self.field_combo.setToolTip("Limite do talhão: avisa se o desvio sair dele (opcional).")
        form.addRow("Camada de linhas:", self.line_combo)
        form.addRow("Camada de obstáculos:", self.obstacle_combo)
        form.addRow("Talhão (limite):", self.field_combo)
        layout.addLayout(form)

        picks = QHBoxLayout()
        self.pick_line_button = QPushButton("Selecionar linha no mapa")
        self.pick_obstacle_button = QPushButton("Selecionar obstáculo no mapa")
        self.use_selection_button = QPushButton("Usar seleção do mapa")
        for button in (self.pick_line_button, self.pick_obstacle_button, self.use_selection_button):
            picks.addWidget(button)
        layout.addLayout(picks)

        params = QFormLayout()
        self.line_label = QLabel("—")
        self.obstacle_label = QLabel("—")
        self.type_combo = QComboBox()
        for detour_type in DetourType:
            planned = detour_type not in V1_DETOUR_TYPES
            label = DETOUR_TYPE_LABELS[detour_type] + (" (planejado)" if planned else "")
            self.type_combo.addItem(label, detour_type.value)
            if planned:
                self.type_combo.model().item(self.type_combo.count() - 1).setEnabled(False)
        self.type_combo.setCurrentIndex(self.type_combo.findData(DetourType.LATERAL_LEFT.value))
        self.direction_combo = QComboBox()
        for direction, label in LINE_DIRECTION_LABELS.items():
            self.direction_combo.addItem(label, direction.value)
        self.radius_spin = _spin(1.0)
        self.margin_spin = _spin(0.5)
        self.anticipation_spin = _spin(3.0)
        self.return_spin = _spin(3.0)
        self.tractor_spin = _spin(0.0, 100.0)
        self.width_spin = _spin(0.0, 100.0)
        self.turn_spin = _spin(0.0, 200.0)
        self.tractor_spin.setToolTip("Medida da máquina: informe a distância real do trator ao implemento.")
        self.width_spin.setToolTip("Largura de trabalho do implemento; lida da linha quando houver atributo.")
        self.turn_spin.setToolTip("0 = só a geometria da plantadeira (meia largura + folga da linha interna).")
        params.addRow("Linha:", self.line_label)
        params.addRow("Obstáculo:", self.obstacle_label)
        params.addRow("Tipo:", self.type_combo)
        params.addRow("Sentido da linha:", self.direction_combo)
        params.addRow("Raio do obstáculo:", self.radius_spin)
        params.addRow("Margem de segurança:", self.margin_spin)
        params.addRow("Antecipação:", self.anticipation_spin)
        params.addRow("Retorno:", self.return_spin)
        params.addRow("Distância trator → implemento:", self.tractor_spin)
        params.addRow("Largura do implemento:", self.width_spin)
        params.addRow("Raio mínimo de curva:", self.turn_spin)
        layout.addLayout(params)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        self.preview_button = QPushButton("PRÉ-VISUALIZAR")
        self.apply_button = QPushButton("APLICAR")
        self.restore_button = QPushButton("Restaurar original")
        self.cancel_button = QPushButton("CANCELAR")
        self.apply_button.setEnabled(False)
        for button in (self.preview_button, self.apply_button, self.restore_button, self.cancel_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self.pick_line_button.clicked.connect(lambda: self._start_pick("line"))
        self.pick_obstacle_button.clicked.connect(lambda: self._start_pick("obstacle"))
        self.use_selection_button.clicked.connect(self.use_map_selection)
        self.preview_button.clicked.connect(self.run_preview)
        self.apply_button.clicked.connect(self.apply_with_confirmation)
        self.restore_button.clicked.connect(self.restore_with_confirmation)
        self.cancel_button.clicked.connect(self.close)
        self.line_combo.layerChanged.connect(lambda _layer: self._reset_line())
        self.obstacle_combo.layerChanged.connect(lambda _layer: self._reset_obstacle())
        self.field_combo.layerChanged.connect(self._invalidate)
        for widget in (
            self.radius_spin, self.margin_spin, self.anticipation_spin, self.return_spin,
            self.tractor_spin, self.width_spin, self.turn_spin,
        ):
            widget.valueChanged.connect(self._invalidate)
        self.type_combo.currentIndexChanged.connect(self._invalidate)
        self.direction_combo.currentIndexChanged.connect(self._invalidate)

    def _auto_select_layers(self) -> None:
        candidates = []
        fields = []
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                continue
            priority = obstacle_layer_priority(layer.name())
            if priority is not None:
                candidates.append((priority, layer.name(), layer))
            field_priority = field_layer_priority(layer)
            if field_priority is not None:
                fields.append((field_priority, layer.name(), layer))
        if candidates:
            self.obstacle_combo.setLayer(min(candidates, key=lambda item: (item[0], item[1]))[2])
        if fields:
            self.field_combo.setLayer(min(fields, key=lambda item: (item[0], item[1]))[2])

    def field_layer(self) -> QgsVectorLayer | None:
        layer = self.field_combo.currentLayer()
        return layer if isinstance(layer, QgsVectorLayer) and layer.isValid() else None

    # --- estado -------------------------------------------------------------

    def line_layer(self) -> QgsVectorLayer | None:
        layer = self.line_combo.currentLayer()
        return layer if isinstance(layer, QgsVectorLayer) and layer.isValid() else None

    def obstacle_layer(self) -> QgsVectorLayer | None:
        layer = self.obstacle_combo.currentLayer()
        return layer if isinstance(layer, QgsVectorLayer) and layer.isValid() else None

    def parameters(self) -> DetourParameters:
        return DetourParameters(
            detour_type=DetourType(self.type_combo.currentData()),
            obstacle_radius_m=self.radius_spin.value(),
            safety_margin_m=self.margin_spin.value(),
            longitudinal_anticipation_m=self.anticipation_spin.value(),
            longitudinal_return_m=self.return_spin.value(),
            tractor_to_implement_m=self.tractor_spin.value(),
            implement_width_m=self.width_spin.value(),
            minimum_turn_radius_m=self.turn_spin.value(),
            direction=LineDirection(self.direction_combo.currentData()),
        )

    def _set_status(self, text: str, error: bool = False, warning: bool = False) -> None:
        self.status_label.setStyleSheet("color: #b00020;" if error else "color: #b35c00;" if warning else "")
        self.status_label.setText(text)

    def _update_summary(self) -> None:
        params = self.parameters()
        self.summary_label.setText(
            f"Zona de segurança: {params.safety_radius_m:.2f} m (raio + margem). "
            f"Folga do centro da plantadeira: {params.centerline_clearance_m:.2f} m além do obstáculo "
            f"(margem + meia largura)."
        )

    def _invalidate(self, *_args) -> None:
        self.computation = None
        self.apply_button.setEnabled(False)
        self._update_summary()

    def _reset_line(self) -> None:
        self.line_fid = None
        self.line_label.setText("—")
        self._invalidate()

    def _reset_obstacle(self) -> None:
        self.obstacle_fid = None
        self.obstacle_label.setText("—")
        self._invalidate()

    def set_line(self, feature) -> None:
        self.line_fid = feature.id()
        self.line_label.setText(line_label(feature))
        width = implement_width_from(feature)
        if width is not None:
            self.width_spin.setValue(width)
        self._invalidate()
        self._show_selection()

    def set_obstacle(self, feature) -> None:
        self.obstacle_fid = feature.id()
        self.obstacle_label.setText(obstacle_label(feature))
        radius = obstacle_radius_from(feature)
        if radius is not None:
            self.radius_spin.setValue(radius)
        elif is_area_obstacle(feature):
            self.radius_spin.setValue(0.0)
        self._invalidate()
        self._show_selection()

    def _feature(self, layer, fid):
        if layer is None or fid is None:
            return None
        feature = layer.getFeature(int(fid))
        return feature if feature.isValid() else None

    def _show_selection(self) -> None:
        self.preview.clear()
        for layer, fid in ((self.line_layer(), self.line_fid), (self.obstacle_layer(), self.obstacle_fid)):
            feature = self._feature(layer, fid)
            if feature is not None:
                self.preview.highlight(feature.geometry(), layer.crs())

    # --- selecao no mapa ------------------------------------------------------

    def _start_pick(self, kind: str) -> None:
        layer = self.line_layer() if kind == "line" else self.obstacle_layer()
        if layer is None:
            self._set_status(MSG_SELECT_LINE if kind == "line" else MSG_SELECT_OBSTACLE, True)
            return
        self._stop_pick()
        self.previous_tool = self.canvas.mapTool()
        self.pick_tool = QgsMapToolIdentifyFeature(self.canvas, layer)
        self.pick_tool.featureIdentified.connect(lambda feature: self._picked(kind, feature))
        self.canvas.setMapTool(self.pick_tool)
        self._set_status("Clique na linha de plantio." if kind == "line" else "Clique no obstáculo.")

    def _picked(self, kind: str, feature) -> None:
        if kind == "line":
            self.set_line(feature)
            if self.obstacle_fid is None:
                self._start_pick("obstacle")
            else:
                self._stop_pick()
        else:
            self.set_obstacle(feature)
            self._stop_pick()
        if self.line_fid is not None and self.obstacle_fid is not None:
            self._set_status("Linha e obstáculo selecionados. Ajuste os parâmetros e pré-visualize.")

    def _stop_pick(self) -> None:
        if self.pick_tool is not None:
            if self.canvas.mapTool() is self.pick_tool:
                self.canvas.unsetMapTool(self.pick_tool)
                if self.previous_tool is not None:
                    self.canvas.setMapTool(self.previous_tool)
            self.pick_tool = None

    def use_map_selection(self) -> bool:
        lines, obstacles = self.line_layer(), self.obstacle_layer()
        line_count = lines.selectedFeatureCount() if lines is not None else 0
        obstacle_count = obstacles.selectedFeatureCount() if obstacles is not None else 0
        error = selection_error(line_count, obstacle_count)
        if error:
            self._set_status(error, True)
            return False
        self.set_line(lines.selectedFeatures()[0])
        self.set_obstacle(obstacles.selectedFeatures()[0])
        self._set_status("Linha e obstáculo selecionados. Ajuste os parâmetros e pré-visualize.")
        return True

    # --- acoes ---------------------------------------------------------------

    def run_preview(self) -> bool:
        line_layer, obstacle_layer = self.line_layer(), self.obstacle_layer()
        line = self._feature(line_layer, self.line_fid)
        obstacle = self._feature(obstacle_layer, self.obstacle_fid)
        error = selection_error(int(line is not None), int(obstacle is not None))
        if error:
            self._set_status(error, True)
            return False
        params = self.parameters()
        try:
            computation = compute_detour(
                line_layer, line, obstacle_layer, obstacle, params, find_detour_layer(), self.field_layer()
            )
        except Exception as exc:  # noqa: BLE001 - mensagem ao operador
            self._set_status(f"⚠ {exc}", True)
            return False
        self.computation = computation
        self.preview.clear()
        self.preview.show(computation, obstacle.geometry(), obstacle_layer.crs())
        detour = computation.detour
        self.apply_button.setEnabled(detour.ok)
        self._set_status(
            self._preview_text(computation, line_layer, obstacle_layer, obstacle),
            not detour.ok,
            bool(detour.warnings),
        )
        return detour.ok

    def _preview_text(self, computation, line_layer, obstacle_layer, obstacle) -> str:
        detour = computation.detour
        params = detour.parameters
        lines = list(detour.warnings) + list(detour.messages)
        if detour.ok:
            start, end = detour.maneuver_start_station_m, detour.maneuver_end_station_m
            lines.insert(0, (
                f"Pré-visualização válida: manobra de {min(start, end):.2f} m a {max(start, end):.2f} m da linha "
                f"(antecipação {params.longitudinal_anticipation_m:.2f} m, retorno {params.longitudinal_return_m:.2f} m)."
            ))
            if params.tractor_to_implement_m > 0:
                lines.append(
                    f"Trator {params.tractor_to_implement_m:.2f} m à frente do implemento em cada evento "
                    "(a trajetória do implemento não muda)."
                )
            if computation.superseded_record_id is not None:
                lines.append("Recalculado a partir da geometria original (nova versão do desvio).")
        elif params.detour_type is not DetourType.CUT_RESUME and line_layer is not None:
            metric = computation.metric_crs
            line_shape = to_shapely(transformed(computation.base_geometry, line_layer.crs(), metric))
            obstacle_shape = to_shapely(transformed(obstacle.geometry(), obstacle_layer.crs(), metric))
            suggestion = suggest_lateral_distances(line_shape, obstacle_shape, params)
            if suggestion is not None:
                lines.append(
                    f"Sugestão: antecipação ≥ {suggestion[0]:.2f} m e retorno ≥ {suggestion[1]:.2f} m "
                    "(nada é alterado automaticamente)."
                )
        return "\n".join(lines)

    def apply_with_confirmation(self) -> bool:
        if self.computation is None or not self.computation.detour.ok:
            self._set_status("Pré-visualize um desvio válido antes de aplicar.", True)
            return False
        detour = self.computation.detour
        text = (
            "Aplicar desvio?\n\n"
            f"Linha: {detour.line_id}\n"
            f"Obstáculo: {detour.obstacle_id}\n"
            f"Tipo: {DETOUR_TYPE_LABELS[detour.parameters.detour_type]}\n\n"
            "A geometria original será preservada."
        )
        default = QMessageBox.Yes
        if detour.warnings:
            text += "\n\nATENÇÃO:\n" + "\n".join(detour.warnings) + "\n\nAplicar mesmo assim?"
            default = QMessageBox.No
        answer = QMessageBox.question(
            self, "Aplicar desvio?", text, QMessageBox.Yes | QMessageBox.No, default
        )
        if answer != QMessageBox.Yes:
            return False
        return self.apply_current()

    def apply_current(self) -> bool:
        line_layer = self.line_layer()
        try:
            record_layer = ensure_detour_layer(line_layer.crs())
            record = apply_detour(
                line_layer,
                self.line_fid,
                self.computation,
                record_layer,
                obstacle_layer=self.obstacle_layer(),
                obstacle_fid=self.obstacle_fid,
            )
        except DetourServiceError as exc:
            self._set_status(str(exc), True)
            return False
        self.preview.clear()
        self.computation = None
        self.apply_button.setEnabled(False)
        self._set_status(
            f"Desvio {record['detour_id']} aplicado (versão {record['version']}). "
            "Ctrl+Z desfaz; salve as edições da camada para gravar."
        )
        return True

    def restore_with_confirmation(self) -> bool:
        line_layer = self.line_layer()
        if line_layer is None or self.line_fid is None:
            self._set_status(MSG_SELECT_LINE, True)
            return False
        record = active_record(find_detour_layer(), line_layer, self.line_fid)
        if record is None:
            self._set_status("Esta linha não possui desvio aplicado.", True)
            return False
        answer = QMessageBox.question(
            self,
            "Restaurar linha original?",
            f"Remover o desvio {record['detour_id']} ({record['obstacle_id']}) da linha {record['line_id']}?",
        )
        if answer != QMessageBox.Yes:
            return False
        return self.restore_current()

    def restore_current(self) -> bool:
        line_layer = self.line_layer()
        try:
            record = restore_original(line_layer, self.line_fid, find_detour_layer())
        except DetourServiceError as exc:
            self._set_status(str(exc), True)
            return False
        self.preview.clear()
        self.computation = None
        self.apply_button.setEnabled(False)
        self._set_status(f"Linha restaurada (desvio {record['detour_id']} removido). Ctrl+Z desfaz.")
        return True

    def closeEvent(self, event) -> None:  # noqa: N802 - API Qt
        self._stop_pick()
        self.preview.clear()
        super().closeEvent(event)
