# -*- coding: utf-8 -*-
"""Aba 'Camadas' do painel FortSmart: arvore logica 01-05, so apresentacao.

Nao move, renomeia nem cria grupos, camadas ou arquivos. A unica escrita e a
visibilidade do no original da camada, com restauracao. Os sinais do QGIS so
ficam conectados enquanto a aba esta visivel e sao agrupados antes de reconstruir.
"""

from __future__ import annotations

from functools import partial
from html import escape

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QBrush, QColor, QFont
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.logical_layer_tree import (
    STATUS_AMBIGUOUS,
    STATUS_NOT_IN_TREE,
    STATUS_NOTE,
    STATUS_WARNING,
    GeometryRiskChecker,
    LayerOrganizerModel,
    VisibilityJournal,
)
from ..core.project_context import (
    FIELD_AMBIGUOUS,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    ProjectContextService,
)

ITEM_FIELD = "field"
ITEM_CATEGORY = "category"
ITEM_LAYER = "layer"
DEBOUNCE_MS = 200
COLUMNS = ("Camada", "Geometria", "Talhão", "Status")
_SEVERITY_LABELS = {SEVERITY_ERROR: "Erro", SEVERITY_WARNING: "Aviso", SEVERITY_INFO: "Nota"}
_STATUS_COLORS = {
    STATUS_WARNING: "#b45309",
    STATUS_AMBIGUOUS: "#b91c1c",
    STATUS_NOT_IN_TREE: "#6b7280",
    STATUS_NOTE: "#1d4ed8",
}
_HIDDEN_BY_PARENT = "#9ca3af"


def _geometry_checker(service):
    from ..core.persistence_manager import FortSmartPersistenceManager, PersistenceError

    def storage_path(field_id):
        manager = FortSmartPersistenceManager(service.project)
        if not manager.storage_available():
            return None
        try:
            return manager.get_field_storage_path(field_id)
        except PersistenceError:
            return None

    return GeometryRiskChecker(storage_path, FortSmartPersistenceManager.table_geometry_type)


def _diagnostics_html(diagnostics) -> str:
    if not diagnostics:
        return "<p>Nenhum aviso.</p>"
    items = "".join(
        f"<li><b>{_SEVERITY_LABELS.get(item.severity, item.severity)}</b> "
        f"<code>{escape(item.code)}</code>: {escape(item.message)}</li>"
        for item in diagnostics
    )
    return f"<ul>{items}</ul>"


class LayerOrganizerPanel(QWidget):
    """Visao logica por talhao sobre o contexto da 0B (ProjectContextService)."""

    def __init__(self, iface=None, project=None, parent=None, service=None):
        super().__init__(parent)
        self.iface = iface
        self.service = service if service is not None else ProjectContextService(project, iface)
        self.model = LayerOrganizerModel(self.service, geometry_risk=_geometry_checker(self.service))
        self.journal = VisibilityJournal()
        self._connections: list = []
        self._layer_connections: dict = {}
        self._populating = False
        self._pending_full = False
        self._pending_layers: set = set()
        self._expanded: set | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self._flush)
        self._build_ui()

    # ------------------------------------------------------------------ UI --
    def _build_ui(self):
        layout = QVBoxLayout(self)
        note = QLabel(
            "Visão lógica por talhão. Os grupos, camadas e arquivos reais do QGIS "
            "não são movidos, renomeados nem criados."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.context_label = QLabel()
        self.context_label.setWordWrap(True)
        layout.addWidget(self.context_label)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(COLUMNS))
        self.tree.setHeaderLabels(list(COLUMNS))
        self.tree.setUniformRowHeights(True)
        self.tree.setTextElideMode(Qt.ElideMiddle)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, len(COLUMNS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.currentItemChanged.connect(self._on_current_item_changed)
        self.tree.itemSelectionChanged.connect(self._update_buttons)

        self.details = QTextBrowser()
        self.details.setOpenLinks(False)
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.tree)
        splitter.addWidget(self.details)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        row1 = QHBoxLayout()
        self.btn_show = QPushButton("Mostrar")
        self.btn_hide = QPushButton("Ocultar")
        self.btn_restore = QPushButton("Restaurar visibilidade")
        for button in (self.btn_show, self.btn_hide, self.btn_restore):
            row1.addWidget(button)
        row2 = QHBoxLayout()
        self.btn_work_field = QPushButton("Usar como talhão de trabalho")
        self.btn_clear_field = QPushButton("Limpar escolha")
        self.btn_select = QPushButton("Selecionar no QGIS")
        self.btn_refresh = QPushButton("Atualizar")
        for button in (self.btn_work_field, self.btn_clear_field, self.btn_select, self.btn_refresh):
            row2.addWidget(button)
        layout.addLayout(row1)
        layout.addLayout(row2)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.btn_show.setToolTip("Marca a visibilidade das camadas selecionadas no nó original do QGIS.")
        self.btn_hide.setToolTip("Desmarca a visibilidade das camadas selecionadas no nó original do QGIS.")
        self.btn_restore.setToolTip(
            "Volta a visibilidade alterada por este painel; mudanças feitas depois no QGIS são mantidas."
        )
        self.btn_work_field.setToolTip("Só para talhões identificados pelo grupo; fica só nesta sessão.")
        self.btn_show.clicked.connect(lambda: self.set_selected_visibility(True))
        self.btn_hide.clicked.connect(lambda: self.set_selected_visibility(False))
        self.btn_restore.clicked.connect(self.restore_visibility)
        self.btn_work_field.clicked.connect(self.use_selected_field)
        self.btn_clear_field.clicked.connect(self.clear_work_field)
        self.btn_select.clicked.connect(self.select_in_qgis)
        self.btn_refresh.clicked.connect(self.refresh_full)
        self._update_buttons()

    # --------------------------------------------------------------- sinais --
    @property
    def connection_count(self) -> int:
        return len(self._connections) + sum(len(items) for items in self._layer_connections.values())

    def _connect(self):
        if self._connections:
            return
        project = self.service.project
        root = project.layerTreeRoot()
        pairs = [
            (project.layersAdded, self._on_structure_changed),
            (project.layersRemoved, self._on_structure_changed),
            (project.cleared, self._on_project_reset),
            (project.readProject, self._on_project_reset),
            (root.visibilityChanged, self._on_visibility_changed),
            (root.addedChildren, self._on_structure_changed),
            (root.removedChildren, self._on_structure_changed),
            (root.nameChanged, self._on_structure_changed),
        ]
        current_layer_changed = getattr(self.iface, "currentLayerChanged", None)
        if current_layer_changed is not None:
            pairs.append((current_layer_changed, self._on_current_layer_changed))
        for signal, slot in pairs:
            signal.connect(slot)
            self._connections.append((signal, slot))

    @staticmethod
    def _safe_disconnect(signal, slot):
        try:
            signal.disconnect(slot)
        except (RuntimeError, TypeError):
            pass

    def _disconnect(self):
        for signal, slot in self._connections:
            self._safe_disconnect(signal, slot)
        self._connections = []
        for items in self._layer_connections.values():
            for signal, slot in items:
                self._safe_disconnect(signal, slot)
        self._layer_connections = {}

    def _sync_layer_connections(self):
        """Edicao concluida ou metadado alterado invalida so aquela camada."""
        layers = self.service.project.mapLayers()
        for layer_id in list(self._layer_connections):
            if layer_id not in layers:
                for signal, slot in self._layer_connections.pop(layer_id):
                    self._safe_disconnect(signal, slot)
        for layer_id, layer in layers.items():
            if layer_id in self._layer_connections:
                continue
            slot = partial(self._on_layer_changed, layer_id)
            items = []
            for name in ("editingStopped", "customPropertyChanged"):
                signal = getattr(layer, name, None)
                if signal is not None:
                    signal.connect(slot)
                    items.append((signal, slot))
            self._layer_connections[layer_id] = items

    def showEvent(self, event):
        super().showEvent(event)
        self._connect()
        self.refresh_full()

    def hideEvent(self, event):
        self._timer.stop()
        self._disconnect()
        super().hideEvent(event)

    def shutdown(self):
        self._timer.stop()
        self._disconnect()

    def _on_structure_changed(self, *args):
        self._schedule(full=True)

    def _on_visibility_changed(self, *args):
        self._schedule()

    def _on_layer_changed(self, layer_id, *args):
        self._schedule(layer_ids=(layer_id,))

    def _on_project_reset(self, *args):
        self.journal.forget()
        self.service.clear_explicit_field()
        self._schedule(full=True)

    def _on_current_layer_changed(self, *args):
        self._update_context()

    def _schedule(self, *, full: bool = False, layer_ids=()):
        self._pending_full = self._pending_full or full
        self._pending_layers.update(layer_ids)
        self._timer.start()

    def _flush(self):
        if self._pending_full:
            self.model.invalidate()
        elif self._pending_layers:
            self.model.invalidate(self._pending_layers)
        self._pending_full = False
        self._pending_layers = set()
        self.refresh()

    # ------------------------------------------------------------ montagem --
    def refresh_full(self):
        self._timer.stop()
        self._pending_full = False
        self._pending_layers = set()
        self.model.invalidate()
        self.refresh()

    def refresh(self):
        tree = self.model.build()
        if self._connections:
            self._sync_layer_connections()
        self._populate(tree)
        self._update_context()
        self._update_buttons()
        self._show_details(self.tree.currentItem())

    @staticmethod
    def _key(item):
        value = item.data(0, Qt.UserRole) if item is not None else None
        return tuple(value) if isinstance(value, list) else value

    def _walk_items(self):
        stack = [self.tree.topLevelItem(index) for index in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            yield item
            stack.extend(item.child(index) for index in range(item.childCount()))

    def _populate(self, tree):
        expanded = {self._key(item) for item in self._walk_items() if item.isExpanded()}
        first = self._expanded is None
        current = self._key(self.tree.currentItem())
        scroll = self.tree.verticalScrollBar().value()
        self._populating = True
        self.tree.setUpdatesEnabled(False)
        try:
            self.tree.clear()
            restore = None
            for field in tree.all_fields():
                if not field.associated and not field.layers:
                    continue
                field_key = (ITEM_FIELD, field.key)
                field_item = QTreeWidgetItem([f"{field.title} ({len(field.layers)})", "", "", field.status])
                field_item.setData(0, Qt.UserRole, field_key)
                font = QFont(field_item.font(0))
                font.setBold(True)
                field_item.setFont(0, font)
                field_item.setToolTip(
                    0,
                    "Grupo(s) real(is): " + ", ".join(field.group_paths)
                    if field.associated
                    else "Camadas fora de um grupo 'FORTSMART - <talhão>' ou com talhão ambíguo.",
                )
                self._paint_status(field_item, field.status)
                self.tree.addTopLevelItem(field_item)
                restore = field_item if field_key == current else restore
                for category in field.categories:
                    category_key = (ITEM_CATEGORY, field.key, category.definition.code)
                    category_item = QTreeWidgetItem([f"{category.title} ({len(category.layers)})", "", "", ""])
                    category_item.setData(0, Qt.UserRole, category_key)
                    category_item.setToolTip(0, "Seção real: " + ", ".join(category.definition.sections))
                    field_item.addChild(category_item)
                    restore = category_item if category_key == current else restore
                    for layer in category.layers:
                        layer_item = self._layer_item(layer)
                        category_item.addChild(layer_item)
                        restore = layer_item if (ITEM_LAYER, layer.layer_id) == current else restore
                    category_item.setExpanded(
                        bool(category.layers) if first else category_key in expanded
                    )
                field_item.setExpanded(True if first else field_key in expanded)
            if restore is not None:
                self.tree.setCurrentItem(restore)
        finally:
            self.tree.setUpdatesEnabled(True)
            self._populating = False
        self._expanded = expanded
        self.tree.verticalScrollBar().setValue(scroll)

    def _layer_item(self, layer):
        if layer.field_id:
            field_text = layer.field_id
        elif layer.field_status == FIELD_AMBIGUOUS:
            field_text = "ambíguo: " + " / ".join(candidate for candidate, _source in layer.field_candidates)
        else:
            field_text = "—"
        item = QTreeWidgetItem([layer.name, layer.geometry, field_text, layer.status])
        item.setData(0, Qt.UserRole, (ITEM_LAYER, layer.layer_id))
        flags = item.flags()
        if layer.in_tree:
            item.setFlags(flags | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if layer.visible_checked else Qt.Unchecked)
        else:
            item.setFlags(flags & ~Qt.ItemIsUserCheckable)
        hidden_by_parent = layer.visible_checked and not layer.visible_effective
        if hidden_by_parent:
            item.setForeground(0, QBrush(QColor(_HIDDEN_BY_PARENT)))
        role = f"{layer.role} ({layer.role_source})" if layer.role else "sem papel FortSmart"
        lines = [
            f"Nome original: {layer.name}",
            f"Grupo real: {layer.group_path or '(fora da árvore)'}",
            f"Papel: {role}",
            f"Seção real: {layer.section or '—'}",
            f"Classe: {layer.kind_label}",
        ]
        if hidden_by_parent:
            lines.append("Marcada, mas oculta por um grupo pai desmarcado.")
        item.setToolTip(0, "\n".join(lines))
        self._paint_status(item, layer.status)
        return item

    @staticmethod
    def _paint_status(item, status):
        color = _STATUS_COLORS.get(status)
        if color:
            item.setForeground(3, QBrush(QColor(color)))

    # ------------------------------------------------------------- contexto --
    def _update_context(self):
        try:
            snapshot = self.service.snapshot()
        except Exception as exc:
            self.context_label.setText(f"Contexto indisponível: {exc}")
            return
        project = snapshot.project_file or "projeto não salvo"
        crs = (snapshot.project_crs.authid if snapshot.project_crs else "") or "—"
        if snapshot.field.resolved:
            origin = "escolha manual" if snapshot.explicit_field else "camada ativa"
            field = f"{snapshot.field.field_id} ({origin})"
        else:
            field = "não definido"
        farm = snapshot.farm.name or "não registrada"
        self.context_label.setText(
            f"Projeto: {project}\nCRS do projeto: {crs} · Talhão em uso: {field} · Fazenda: {farm}"
        )

    def _selected_entries(self):
        tree = self.model.tree
        if tree is None:
            return []
        found = []
        for item in self.tree.selectedItems() or ([self.tree.currentItem()] if self.tree.currentItem() else []):
            key = self._key(item)
            if not key:
                continue
            if key[0] == ITEM_LAYER:
                layer = tree.layer(key[1])
                found.extend([layer] if layer is not None else [])
            elif key[0] == ITEM_FIELD:
                field = tree.field(key[1])
                found.extend(field.layers if field is not None else [])
            elif key[0] == ITEM_CATEGORY:
                field = tree.field(key[1])
                category = next(
                    (item for item in (field.categories if field else ()) if item.definition.code == key[2]),
                    None,
                )
                found.extend(category.layers if category is not None else [])
        unique = {}
        for layer in found:
            unique.setdefault(layer.layer_id, layer)
        return list(unique.values())

    def _selected_field_id(self):
        """Talhao do item atual; None quando nao identificado ou ambiguo."""
        tree = self.model.tree
        key = self._key(self.tree.currentItem())
        if tree is None or not key:
            return None
        if key[0] in (ITEM_FIELD, ITEM_CATEGORY):
            field = tree.field(key[1])
            return field.field_id if field is not None else None
        layer = tree.layer(key[1])
        return layer.field_id if layer is not None else None

    def _update_buttons(self):
        layers = self._selected_entries()
        in_tree = any(layer.in_tree for layer in layers)
        self.btn_show.setEnabled(in_tree)
        self.btn_hide.setEnabled(in_tree)
        self.btn_restore.setEnabled(self.journal.pending > 0)
        self.btn_work_field.setEnabled(self._selected_field_id() is not None)
        self.btn_clear_field.setEnabled(self.service.explicit_field is not None)
        key = self._key(self.tree.currentItem())
        self.btn_select.setEnabled(bool(self.iface) and bool(key) and key[0] == ITEM_LAYER)

    def _show_details(self, item):
        tree = self.model.tree
        key = self._key(item)
        if tree is None:
            self.details.clear()
            return
        if not key:
            self.details.setHtml("<b>Projeto</b>" + _diagnostics_html(tree.diagnostics))
            return
        if key[0] == ITEM_LAYER:
            layer = tree.layer(key[1])
            if layer is None:
                self.details.clear()
                return
            text = (
                f"<b>{escape(layer.name)}</b> · {escape(layer.kind_label)} · {escape(layer.geometry)}<br>"
                f"Grupo real: <code>{escape(layer.group_path or '(fora da árvore)')}</code>"
            )
            if layer.field_status == FIELD_AMBIGUOUS:
                text += "<br>Talhão ambíguo: ações que dependem do talhão ficam bloqueadas."
            self.details.setHtml(text + _diagnostics_html(layer.diagnostics))
            return
        field = tree.field(key[1])
        if field is None:
            self.details.clear()
            return
        if key[0] == ITEM_CATEGORY:
            category = next((c for c in field.categories if c.definition.code == key[2]), None)
            sections = ", ".join(category.definition.sections) if category else ""
            self.details.setHtml(
                f"<b>{escape(category.title if category else '')}</b><br>"
                f"Rótulo de exibição da seção real <code>{escape(sections)}</code>; o nome do grupo no QGIS não muda."
            )
            return
        self.details.setHtml(f"<b>{escape(field.title)}</b>" + _diagnostics_html(field.diagnostics + tree.diagnostics))

    # --------------------------------------------------------------- acoes --
    def _on_current_item_changed(self, current, _previous):
        self._update_buttons()
        self._show_details(current)

    def _on_item_changed(self, item, column):
        if self._populating or column != 0:
            return
        key = self._key(item)
        if not key or key[0] != ITEM_LAYER or not (item.flags() & Qt.ItemIsUserCheckable):
            return
        report = self.journal.apply(
            self.service.project.layerTreeRoot(), [key[1]], item.checkState(0) == Qt.Checked
        )
        self.status_label.setText(report.text())
        self._update_buttons()

    def set_selected_visibility(self, visible: bool):
        ids = [layer.layer_id for layer in self._selected_entries() if layer.in_tree]
        report = self.journal.apply(self.service.project.layerTreeRoot(), ids, visible)
        self.status_label.setText(report.text())
        self._update_buttons()
        return report

    def restore_visibility(self):
        report = self.journal.restore(self.service.project.layerTreeRoot())
        self.status_label.setText(report.text(restoring=True))
        self._update_buttons()
        return report

    def use_selected_field(self):
        field_id = self._selected_field_id()
        if field_id is None:
            self.status_label.setText("Talhão não identificado pelo grupo; escolha um talhão válido.")
            return
        self.service.set_explicit_field(field_id)
        self.status_label.setText(f"Talhão de trabalho nesta sessão: {field_id}.")
        self._update_context()
        self._update_buttons()

    def clear_work_field(self):
        self.service.clear_explicit_field()
        self.status_label.setText("Escolha de talhão removida.")
        self._update_context()
        self._update_buttons()

    def select_in_qgis(self):
        key = self._key(self.tree.currentItem())
        if not self.iface or not key or key[0] != ITEM_LAYER:
            return
        layer = self.service.project.mapLayer(key[1])
        if layer is not None:
            self.iface.setActiveLayer(layer)
