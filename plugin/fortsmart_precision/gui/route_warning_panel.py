# -*- coding: utf-8 -*-
"""Painel VALIDACAO DA ROTA: lista, filtra, localiza e marca avisos (nunca corrige)."""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QBrush
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsCoordinateTransform, QgsPointXY, QgsProject
from qgis.gui import QgsMapToolEmitPoint

from ..validator.validation_result import ValidationResult
from ..validator.warning_model import RouteWarning, Severity, WarningStatus, WarningType
from .route_warning_layer import SEVERITY_COLORS, RouteWarningLayers
from .route_warning_renderer import RouteWarningHighlighter, warning_extent

CATEGORY_FILTERS = (
    ("ALL", "Todos"),
    ("CRITICAL", "Criticos"),
    ("SPACING", "Espacamento"),
    ("OBSTACLE", "Obstaculo"),
    ("BOUNDARY", "Limite"),
    ("CROSSING", "Cruzamento"),
    ("GEOMETRY", "Geometria"),
    ("SEQUENCE", "Sequencia"),
)
SEVERITY_LABELS = {Severity.CRITICAL: "CRITICO", Severity.WARNING: "AVISO", Severity.INFO: "INFO"}
TYPE_LABELS = {
    WarningType.OUTSIDE_ALLOWED_AREA: "Fora do limite",
    WarningType.OBSTACLE_INTERSECTION: "Obstaculo",
    WarningType.UNEXPECTED_ROUTE_CROSSING: "Cruzamento",
    WarningType.SPACING_OUT_OF_TOLERANCE: "Espacamento",
    WarningType.DUPLICATED_ROUTE: "Duplicada",
    WarningType.ROUTE_TOO_SHORT: "Muito curta",
    WarningType.INVALID_GEOMETRY: "Geometria invalida",
    WarningType.EMPTY_ROUTE: "Sem geometria",
    WarningType.ZERO_LENGTH_ROUTE: "Comprimento zero",
    WarningType.SHARP_DIRECTION_CHANGE: "Quebra de direcao",
    WarningType.NEXT_ROUTE_TOO_FAR: "Proxima distante",
    WarningType.ROUTE_SEQUENCE_SUSPECT: "Sequencia suspeita",
}
STATUS_LABELS = {
    WarningStatus.OPEN: "Aberto",
    WarningStatus.REVIEWED: "Revisado",
    WarningStatus.RESOLVED: "Resolvido",
    WarningStatus.IGNORED: "Ignorado",
}
COLUMNS = ("ID", "Severidade", "Tipo", "Passada", "Mensagem", "Status")
PICK_TOLERANCE_PX = 8


def warning_details(warning: RouteWarning) -> str:
    lines = [
        f"{warning.id} - {SEVERITY_LABELS[warning.severity]} - {warning.warning_type.value}",
        f"Passada: {warning.pass_id}" + (f" / relacionada: {warning.related_pass_id}" if warning.related_pass_id else ""),
    ]
    if warning.obstacle_id:
        lines.append(f"Obstaculo: {warning.obstacle_id}")
    if warning.distance_m is not None:
        lines.append(f"Posicao na passada: {warning.distance_m:.1f} a {warning.end_distance_m or warning.distance_m:.1f} m")
    lines += ["", warning.message, "", f"Status: {STATUS_LABELS[warning.status]}"]
    return "\n".join(lines)


class RouteWarningPanel(QWidget):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.project = QgsProject.instance()
        self.result: ValidationResult | None = None
        self.crs = None
        self.pass_segments: dict = {}
        self.feature_ids: dict = {}
        self.source_layer = None
        self.layers = RouteWarningLayers(self.project)
        self.highlighter: RouteWarningHighlighter | None = None
        self.pick_tool: QgsMapToolEmitPoint | None = None
        self._previous_tool = None
        self._visible: list[RouteWarning] = []
        self._build()
        self._update_buttons()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(QLabel("<b>VALIDACAO DA ROTA</b>"))
        self.summary_label = QLabel("Rota ainda nao validada.")
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)
        filters = QHBoxLayout()
        filters.addWidget(QLabel("Filtro:"))
        self.filter_combo = QComboBox()
        for key, label in CATEGORY_FILTERS:
            self.filter_combo.addItem(label, key)
        filters.addWidget(self.filter_combo, 1)
        root.addLayout(filters)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        root.addWidget(self.table, 1)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(130)
        root.addWidget(self.details)

        actions = QHBoxLayout()
        self.zoom_button = QPushButton("Centralizar")
        self.fix_button = QPushButton("Corrigir")
        self.fix_button.setToolTip("Seleciona a passada, liga a edicao da camada e aproxima. Nada e alterado.")
        self.pick_button = QPushButton("Clicar no mapa")
        self.pick_button.setCheckable(True)
        self.pick_button.setToolTip("Clique sobre um aviso no mapa para ver os detalhes.")
        for button in (self.zoom_button, self.fix_button, self.pick_button):
            actions.addWidget(button)
        root.addLayout(actions)
        status_row = QHBoxLayout()
        self.status_buttons: dict[WarningStatus, QPushButton] = {}
        for status, label in (
            (WarningStatus.REVIEWED, "Revisado"),
            (WarningStatus.RESOLVED, "Resolvido"),
            (WarningStatus.IGNORED, "Ignorar"),
            (WarningStatus.OPEN, "Reabrir"),
        ):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, s=status: self.set_selected_status(s))
            status_row.addWidget(button)
            self.status_buttons[status] = button
        self.export_button = QPushButton("Exportar JSON")
        status_row.addWidget(self.export_button)
        root.addLayout(status_row)

        self.filter_combo.currentIndexChanged.connect(self._populate)
        self.table.itemSelectionChanged.connect(self._on_selection)
        self.zoom_button.clicked.connect(lambda: self.focus_warning(self.selected_warning()))
        self.fix_button.clicked.connect(self.fix_selected)
        self.pick_button.toggled.connect(self._toggle_pick)
        self.export_button.clicked.connect(lambda: self.export_json())

    # ---------------------------------------------------------- dados ----
    def set_result(self, result: ValidationResult, crs, pass_segments: dict, feature_ids: dict, source_layer) -> None:
        self.result = result
        self.pass_segments = dict(pass_segments)
        self.feature_ids = dict(feature_ids)
        self.source_layer = source_layer
        if self.highlighter is None or self.crs != crs:
            self._remove_highlighter()
            self.highlighter = RouteWarningHighlighter(self.canvas, crs)
        self.crs = crs
        self.layers.show(result, crs)
        self._populate()

    def _populate(self, *_args) -> None:
        self.table.setRowCount(0)
        self.details.clear()
        result = self.result
        if result is None:
            self._visible = []
            self._update_buttons()
            return
        self.summary_label.setText(result.summary())
        self._visible = result.filtered(self.filter_combo.currentData())
        self.table.setRowCount(len(self._visible))
        for row, warning in enumerate(self._visible):
            values = (
                warning.id,
                SEVERITY_LABELS[warning.severity],
                TYPE_LABELS[warning.warning_type],
                warning.pass_id + (f" x {warning.related_pass_id}" if warning.related_pass_id else ""),
                warning.message.splitlines()[0],
                STATUS_LABELS[warning.status],
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, warning.id)
                if column == 1:
                    item.setForeground(QBrush(SEVERITY_COLORS[warning.severity]))
                self.table.setItem(row, column, item)
        self._update_buttons()

    def visible_warnings(self) -> list[RouteWarning]:
        return list(self._visible)

    def selected_warning(self) -> RouteWarning | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows or self.result is None:
            return None
        return self._visible[rows[0].row()]

    def select_warning(self, warning_id: str) -> None:
        ids = [item.id for item in self._visible]
        if warning_id not in ids:
            self.filter_combo.setCurrentIndex(0)
            ids = [item.id for item in self._visible]
        if warning_id in ids:
            self.table.selectRow(ids.index(warning_id))

    def _on_selection(self) -> None:
        warning = self.selected_warning()
        self.details.setPlainText(warning_details(warning) if warning else "")
        if warning is not None:
            self.focus_warning(warning)
        self._update_buttons()

    # ----------------------------------------------------------- mapa ----
    def _to_canvas(self):
        destination = self.canvas.mapSettings().destinationCrs()
        if self.crs is None or not destination.isValid() or destination == self.crs:
            return None
        return QgsCoordinateTransform(self.crs, destination, self.project)

    def focus_warning(self, warning: RouteWarning | None) -> None:
        """Centraliza, aproxima e destaca a passada relacionada."""
        if warning is None or self.highlighter is None:
            return
        self.highlighter.show([warning], self.pass_segments)
        extent = warning_extent(warning, self.pass_segments.get(warning.pass_id, ()))
        if extent is None:
            return
        transform = self._to_canvas()
        if transform is not None:
            extent = transform.transformBoundingBox(extent)
        self.canvas.setExtent(extent)
        self.canvas.refresh()

    def show_pass_warnings(self, pass_id: str) -> list[RouteWarning]:
        """Consulta para a simulacao: destaca os avisos da passada atual sem recalcular nem aproximar."""
        if self.result is None:
            return []
        warnings = self.result.warnings_for_pass(pass_id)
        if self.highlighter is not None:
            if warnings:
                self.highlighter.show(warnings, {})
            else:
                self.highlighter.clear()
        return warnings

    def _toggle_pick(self, enabled: bool) -> None:
        if enabled:
            self.pick_tool = QgsMapToolEmitPoint(self.canvas)
            self.pick_tool.canvasClicked.connect(self._on_canvas_click)
            self._previous_tool = self.canvas.mapTool()
            self.canvas.setMapTool(self.pick_tool)
        elif self.pick_tool is not None:
            if self.canvas.mapTool() is self.pick_tool:
                self.canvas.unsetMapTool(self.pick_tool)
                if self._previous_tool is not None:
                    self.canvas.setMapTool(self._previous_tool)
            self.pick_tool = None

    def _on_canvas_click(self, point, _button=None) -> RouteWarning | None:
        return self.pick_at(point, PICK_TOLERANCE_PX * self.canvas.mapUnitsPerPixel())

    def pick_at(self, point: QgsPointXY, tolerance_canvas_units: float) -> RouteWarning | None:
        """Clique no mapa (CRS do canvas) -> aviso mais proximo selecionado no painel."""
        if self.result is None:
            return None
        transform = self._to_canvas()
        target, edge = QgsPointXY(point), QgsPointXY(point.x() + tolerance_canvas_units, point.y())
        if transform is not None:
            target = transform.transform(target, QgsCoordinateTransform.ReverseTransform)
            edge = transform.transform(edge, QgsCoordinateTransform.ReverseTransform)
        warning = self.result.nearest_warning(target.x(), target.y(), max(target.distance(edge), 0.01))
        if warning is not None:
            self.select_warning(warning.id)
        return warning

    # -------------------------------------------------------- acoes ----
    def set_selected_status(self, status: WarningStatus) -> None:
        warning = self.selected_warning()
        if warning is None or self.result is None:
            return
        self.result.set_status(warning.id, status)
        self.layers.sync_status(self.result)
        self._populate()
        self.select_warning(warning.id)

    def fix_selected(self) -> bool:
        """So seleciona as feicoes da passada, liga a edicao e aproxima; nada e modificado."""
        warning = self.selected_warning()
        layer = self.source_layer
        if warning is None or layer is None:
            return False
        ids = list(self.feature_ids.get(warning.pass_id, ()))
        if not ids:
            self.details.appendPlainText("\nPassada sem feicao correspondente na camada.")
            return False
        layer.selectByIds(ids)
        if not layer.isEditable():
            layer.startEditing()
        self.iface.setActiveLayer(layer)
        self.canvas.zoomToSelected(layer)
        self.canvas.refresh()
        return True

    def export_json(self, path: str | None = None):
        if self.result is None:
            return None
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Relatorio de validacao", "route_validation.json", "JSON (*.json)")
            if not path:
                return None
        return self.result.write_json(path)

    def _update_buttons(self) -> None:
        selected = self.selected_warning() is not None
        for button in (self.zoom_button, self.fix_button, *self.status_buttons.values()):
            button.setEnabled(selected)
        self.export_button.setEnabled(self.result is not None)
        self.pick_button.setEnabled(self.result is not None)

    def _remove_highlighter(self) -> None:
        if self.highlighter is not None:
            self.highlighter.remove()
            self.highlighter = None

    def cleanup(self) -> None:
        """Ao fechar o simulador: tira overlay e ferramenta; camadas de aviso ficam no projeto."""
        self.pick_button.setChecked(False)
        self._remove_highlighter()
