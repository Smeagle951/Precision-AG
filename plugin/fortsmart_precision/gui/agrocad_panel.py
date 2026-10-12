# -*- coding: utf-8 -*-
"""Painel AgroCAD dentro do dock FortSmart (Subfase 0D).

So aciona o que ja existe: acoes nativas do QGIS, as mesmas QActions do menu do
plugin e a pilha de desfazer da camada ativa. Nao grava nada no projeto.
"""

from __future__ import annotations

from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.agrocad_tools import (
    PANEL_UNDO,
    SECTIONS,
    SECTION_EDITOR,
    SECTION_TERRAIN,
    SOURCE_NATIVE,
    SOURCE_PANEL,
    SOURCE_PLUGIN,
    SOURCE_UNAVAILABLE,
    LayerFacts,
    ToolState,
    tool_by_key,
    tool_state,
    tools_for,
)
from ..core.logical_layer_tree import layer_geometry
from ..core.project_context import (
    FIELD_AMBIGUOUS,
    FIELD_RESOLVED,
    SEVERITY_WARNING,
    SOURCE_EXPLICIT,
    ProjectContextService,
)

DEBOUNCE_MS = 80
NO_VALUE = "—"
PREVIEW_TOOLTIP = "A prévia central de geometrias chega na Subfase 0E."
PREVIEW_READY = "Mostra a seleção da camada ativa no mapa, só como desenho temporário."


def _separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    return line


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


class AgroCadPanel(QWidget):
    """Atalhos agricolas e contexto da camada ativa; o mapa continua sendo a area de trabalho."""

    def __init__(self, iface=None, service=None, tool_actions=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.service = service if service is not None else ProjectContextService(None, iface)
        self._tool_actions = dict(tool_actions or {})
        self._connections: list = []
        self._layer_connections: list = []
        self._bound_layer_id: str | None = None
        self._current_tool: str | None = None
        self._map_tool_active = False
        self._preview = None
        self._selection = None
        self.dem_inspector = None
        self._dem_scroll = None
        self._effective_field = None
        self._populating = False
        self._pending_context = False
        self._pending_layer = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self._flush)
        self._build_ui()

    # ------------------------------------------------------------------ UI --
    def _build_ui(self):
        layout = QVBoxLayout(self)
        title = QLabel("FORTSMART AGROCAD")
        font = QFont(title.font())
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)
        self.project_label = QLabel()
        self.project_label.setWordWrap(True)
        layout.addWidget(self.project_label)
        self.file_label = QLabel()
        self.file_label.setWordWrap(True)
        self.file_label.setStyleSheet("color: #666;")
        layout.addWidget(self.file_label)
        field_row = QHBoxLayout()
        field_row.addWidget(QLabel("Talhão de trabalho:"))
        self.field_combo = QComboBox()
        self.field_combo.setToolTip("Automático usa o talhão da camada ativa; a escolha vale só nesta sessão.")
        self.field_combo.currentIndexChanged.connect(self._on_field_chosen)
        field_row.addWidget(self.field_combo, 1)
        layout.addLayout(field_row)
        layout.addWidget(_separator())

        grid = QGridLayout()
        self.section_group = QButtonGroup(self)
        self.section_group.setExclusive(True)
        self.section_buttons: dict = {}
        self.tool_pages = QStackedWidget()
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        self.tool_buttons: dict = {}
        self._section_pages: dict = {}
        self._pages: dict = {}
        for index, (section, label) in enumerate(SECTIONS):
            button = QPushButton(label)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, value=section: self.select_section(value))
            self.section_group.addButton(button)
            self.section_buttons[section] = button
            grid.addWidget(button, index // 2, index % 2)
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            for tool in tools_for(section):
                tool_button = QPushButton(tool.label)
                tool_button.setCheckable(True)
                tool_button.setEnabled(tool.source != SOURCE_UNAVAILABLE)
                tool_button.clicked.connect(lambda _checked=False, value=tool.key: self.select_tool(value))
                self.tool_group.addButton(tool_button)
                self.tool_buttons[tool.key] = tool_button
                page_layout.addWidget(tool_button)
            page_layout.addStretch()
            self._pages[section] = page
            self._section_pages[section] = self.tool_pages.addWidget(page)
        layout.addLayout(grid)
        layout.addWidget(self.tool_pages, 1)
        layout.addWidget(_separator())

        active = QGroupBox("Ferramenta ativa")
        form = QFormLayout(active)
        self.tool_label = QLabel(NO_VALUE)
        self.layer_label = QLabel(NO_VALUE)
        self.selection_label = QLabel(NO_VALUE)
        self.params_label = QLabel(NO_VALUE)
        for label in (self.tool_label, self.layer_label, self.selection_label, self.params_label):
            label.setWordWrap(True)
        form.addRow("Ferramenta:", self.tool_label)
        form.addRow("Camada:", self.layer_label)
        form.addRow("Seleção:", self.selection_label)
        form.addRow("Parâmetros:", self.params_label)
        layout.addWidget(active)

        actions = QHBoxLayout()
        self.btn_preview = QPushButton("Prévia")
        self.btn_apply = QPushButton("Aplicar")
        self.btn_cancel = QPushButton("Cancelar")
        for button in (self.btn_preview, self.btn_apply, self.btn_cancel):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.btn_preview.setEnabled(False)
        self.btn_preview.setToolTip(PREVIEW_TOOLTIP)
        self.btn_preview.clicked.connect(self.preview_selection)
        self.btn_apply.clicked.connect(self.apply)
        self.btn_cancel.clicked.connect(self.cancel)
        self.status_label = QLabel("Status: pronto.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.select_section(SECTION_EDITOR)

    # --------------------------------------------------------------- sinais --
    @property
    def connection_count(self) -> int:
        return len(self._connections) + len(self._layer_connections)

    @staticmethod
    def _safe_disconnect(signal, slot):
        try:
            signal.disconnect(slot)
        except (RuntimeError, TypeError):
            pass

    def _connect(self):
        if self._connections:
            return
        project = self.service.project
        root = project.layerTreeRoot()
        pairs = [
            (project.layersWillBeRemoved, self._on_layers_will_be_removed),
            (project.layersAdded, self._on_structure_changed),
            (project.layersRemoved, self._on_structure_changed),
            (project.cleared, self._on_project_reset),
            (project.readProject, self._on_project_reset),
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

    def _disconnect(self):
        for signal, slot in self._connections:
            self._safe_disconnect(signal, slot)
        self._connections = []
        self._unbind_layer()

    def _bind_layer(self, layer):
        """Selecao, edicao e pilha de desfazer da camada ativa; so uma camada por vez."""
        self._unbind_layer()
        if layer is None:
            return
        pairs = []
        for name, slot in (
            ("selectionChanged", self._on_selection_changed),
            ("editingStarted", self._on_layer_state_changed),
            ("editingStopped", self._on_layer_state_changed),
        ):
            signal = getattr(layer, name, None)
            if signal is not None:
                pairs.append((signal, slot))
        stack = self._undo_stack(layer)
        if stack is not None:
            pairs.append((stack.indexChanged, self._on_selection_changed))
        for signal, slot in pairs:
            signal.connect(slot)
            self._layer_connections.append((signal, slot))
        self._bound_layer_id = layer.id()

    def _unbind_layer(self):
        for signal, slot in self._layer_connections:
            self._safe_disconnect(signal, slot)
        self._layer_connections = []
        self._bound_layer_id = None

    def showEvent(self, event):
        super().showEvent(event)
        self._connect()
        self.refresh()

    def hideEvent(self, event):
        self._timer.stop()
        self._disconnect()
        self.clear_preview()
        super().hideEvent(event)

    def shutdown(self):
        self._timer.stop()
        self._disconnect()
        if self.dem_inspector is not None:
            self.dem_inspector.shutdown()
        if self._preview is not None:
            self._preview.dispose()
            self._preview = None

    def _on_structure_changed(self, *args):
        self._schedule(context=True)

    def _on_layers_will_be_removed(self, layer_ids):
        if self._bound_layer_id in set(layer_ids or ()):
            self._unbind_layer()
        self._schedule(context=True)

    def _on_project_reset(self, *args):
        self.service.clear_explicit_field()
        self.clear_preview()
        self._clear_tool()
        self._set_status("projeto trocado; ferramenta cancelada.")
        self._schedule(context=True)

    def _on_current_layer_changed(self, *args):
        if self.clear_preview():
            self._set_status("prévia limpa: a camada ativa mudou.")
        self._schedule(context=True)

    def _on_layer_state_changed(self, *args):
        self._schedule(layer=True)

    def _on_selection_changed(self, *args):
        if self.clear_preview():
            self._set_status("prévia limpa: a seleção ou a geometria mudou.")
        self._schedule()

    def _schedule(self, *, context: bool = False, layer: bool = False):
        self._pending_context = self._pending_context or context
        self._pending_layer = self._pending_layer or layer or context
        self._timer.start()

    # ------------------------------------------------------------- estado --
    def set_tool_actions(self, mapping):
        self._tool_actions = dict(mapping or {})
        self._update_tools(self._active_layer())

    def _active_layer(self):
        layer = self.service.active_layer()
        if layer is None:
            return None
        try:
            layer_id = layer.id()
        except RuntimeError:
            return None
        return layer if self.service.project.mapLayer(layer_id) is layer else None

    @staticmethod
    def _undo_stack(layer):
        try:
            return layer.undoStack() if layer is not None else None
        except (AttributeError, RuntimeError):
            return None

    def _layer_facts(self, layer) -> LayerFacts:
        if layer is None:
            return LayerFacts()
        is_vector = callable(getattr(layer, "selectedFeatureCount", None))
        stack = self._undo_stack(layer)
        editable = bool(is_vector and layer.isEditable())
        return LayerFacts(
            present=True,
            is_vector=is_vector,
            is_editable=editable,
            can_undo=bool(editable and stack is not None and stack.canUndo()),
            can_redo=bool(editable and stack is not None and stack.canRedo()),
        )

    def _native_action(self, name: str):
        method = getattr(self.iface, name, None)
        if not callable(method):
            return None
        try:
            return method()
        except Exception:
            return None

    def _available(self, tool) -> bool:
        if tool.source == SOURCE_NATIVE:
            return self._native_action(tool.target) is not None
        if tool.source == SOURCE_PLUGIN:
            return self._tool_actions.get(tool.target) is not None
        return tool.source == SOURCE_PANEL

    def state_of(self, key: str, layer=None) -> ToolState:
        tool = tool_by_key(key)
        layer = self._active_layer() if layer is None else layer
        return tool_state(tool, available=self._available(tool), facts=self._layer_facts(layer))

    # ------------------------------------------------------------ refresh --
    def apply_feature_flags(self):
        """Inspetor DEM na secao Terreno so com ENABLE_DEM_INSPECTOR_V1; desligada, fica como na 0D."""
        from ..feature_flags import ENABLE_DEM_INSPECTOR_V1, is_enabled

        enabled = is_enabled(ENABLE_DEM_INSPECTOR_V1)
        page = self._pages[SECTION_TERRAIN]
        buttons = [self.tool_buttons[tool.key] for tool in tools_for(SECTION_TERRAIN)]
        if enabled and self.dem_inspector is None:
            from qgis.PyQt.QtWidgets import QScrollArea

            from .dem_inspector_widget import DemInspectorWidget

            self._dem_scroll = QScrollArea(page)
            self._dem_scroll.setWidgetResizable(True)
            self._dem_scroll.setFrameShape(QFrame.NoFrame)
            self.dem_inspector = DemInspectorWidget(self.iface, self.service)
            self._dem_scroll.setWidget(self.dem_inspector)
            page.layout().insertWidget(0, self._dem_scroll, 1)
            for button in buttons:
                button.hide()
            self.dem_inspector.set_field(self._effective_field)
        elif not enabled and self.dem_inspector is not None:
            self.dem_inspector.shutdown()
            page.layout().removeWidget(self._dem_scroll)
            self._dem_scroll.deleteLater()
            self.dem_inspector = None
            self._dem_scroll = None
            for button in buttons:
                button.show()

    def refresh(self):
        self.apply_feature_flags()
        self._timer.stop()
        self._pending_context = True
        self._pending_layer = True
        self._flush()

    def _flush(self):
        layer = self._active_layer()
        layer_id = layer.id() if layer is not None else None
        if self._connections and layer_id != self._bound_layer_id:
            self._bind_layer(layer)
        if self._pending_context:
            self._update_context(layer)
        if self._pending_layer:
            self._update_layer(layer)
        self._pending_context = False
        self._pending_layer = False
        self._update_selection(layer)
        self._update_tools(layer)

    def _update_context(self, layer):
        snapshot = self.service.snapshot(layer)
        project_name = snapshot.project_title or (
            snapshot.project_file.replace("\\", "/").rsplit("/", 1)[-1] if snapshot.project_file else ""
        )
        farm = snapshot.farm
        if farm.status == FIELD_RESOLVED:
            farm_text = farm.name
        elif farm.status == FIELD_AMBIGUOUS:
            farm_text = "Fazenda ambígua"
        else:
            farm_text = "Fazenda não registrada"
        field = snapshot.field
        if field.resolved:
            origin = "escolhido" if field.source == SOURCE_EXPLICIT else "pela camada ativa"
            field_text = f"{field.field_id} ({origin})"
        elif field.status == FIELD_AMBIGUOUS:
            field_text = "Talhão ambíguo"
        else:
            field_text = "Talhão não definido"
        self.project_label.setText(f"Projeto: {farm_text} / {field_text}")
        self._effective_field = field.field_id if field.resolved else None
        if self.dem_inspector is not None:
            self.dem_inspector.set_field(self._effective_field)
        crs = snapshot.project_crs.authid if snapshot.project_crs is not None else ""
        self.file_label.setText(
            f"Arquivo: {project_name or 'projeto não salvo'} · CRS do projeto: {crs or 'não definido'}"
        )
        self._fill_field_combo(snapshot)

    def _fill_field_combo(self, snapshot):
        self._populating = True
        try:
            self.field_combo.clear()
            self.field_combo.addItem("Automático (camada ativa)", None)
            for item in snapshot.fields:
                self.field_combo.addItem(item.field_id, item.field_id)
            index = self.field_combo.findData(snapshot.explicit_field) if snapshot.explicit_field else 0
            self.field_combo.setCurrentIndex(max(index, 0))
        finally:
            self._populating = False

    def _update_layer(self, layer):
        if layer is None:
            self.layer_label.setText("Nenhuma camada ativa no QGIS.")
            return
        context = self.service.describe_layer(layer)
        role = f"papel {context.role}" if context.role else "sem papel FortSmart"
        parts = [context.name, role, layer_geometry(layer)[0]]
        if context.field.resolved:
            parts.append(f"talhão {context.field.field_id}")
        if context.crs is not None:
            parts.append(context.crs.authid or "CRS inválido")
        if context.is_editing:
            parts.append("em edição")
        self.layer_label.setText(" · ".join(parts))

    def _update_selection(self, layer):
        self._selection = None
        self.selection_label.setToolTip("")
        if layer is None or not callable(getattr(layer, "selectedFeatureCount", None)):
            self.selection_label.setText(NO_VALUE)
        elif self.preview_enabled:
            self._show_selection_info(layer)
        else:
            count = int(layer.selectedFeatureCount())
            self.selection_label.setText(
                _plural(count, "feição selecionada", "feições selecionadas") if count else "nenhuma feição selecionada"
            )
        self._update_preview_button(layer)

    def _show_selection_info(self, layer):
        from ..core.selection_reader import read_selection

        info = read_selection(layer, self.service)
        self._selection = info
        text = info.text()
        warnings = [item.message for item in info.diagnostics if item.severity == SEVERITY_WARNING]
        if warnings:
            text += f" · aviso: {warnings[0]}"
        self.selection_label.setText(text)
        self.selection_label.setToolTip("\n".join(item.message for item in info.diagnostics))

    # ------------------------------------------------------------- previa --
    @property
    def preview_enabled(self) -> bool:
        from ..feature_flags import ENABLE_PREVIEW_MANAGER_V1, is_enabled

        return is_enabled(ENABLE_PREVIEW_MANAGER_V1)

    @property
    def preview(self):
        return self._preview

    def current_selection(self):
        """Selecao nativa da camada ativa lida agora (None sem camada vetorial)."""
        from ..core.selection_reader import read_selection

        return read_selection(self._active_layer(), self.service)

    def _canvas(self):
        getter = getattr(self.iface, "mapCanvas", None)
        try:
            return getter() if callable(getter) else None
        except Exception:
            return None

    def _preview_block_reason(self, layer) -> str:
        if not self.preview_enabled:
            return PREVIEW_TOOLTIP
        if self._canvas() is None:
            return "Mapa do QGIS indisponível."
        if layer is None or not callable(getattr(layer, "selectedFeatureCount", None)):
            return "Selecione uma camada vetorial no QGIS."
        if not layer.selectedFeatureCount():
            return "Selecione feições no mapa para ver a prévia."
        return ""

    def _update_preview_button(self, layer):
        reason = self._preview_block_reason(layer)
        self.btn_preview.setEnabled(not reason)
        self.btn_preview.setToolTip(reason or PREVIEW_READY)

    def _preview_manager(self):
        if self._preview is None or self._preview.disposed:
            from .preview_manager import PreviewManager

            self._preview = PreviewManager(self._canvas(), project=self.service.project, parent=self)
        return self._preview

    def preview_selection(self) -> int:
        """Desenha a selecao atual: destaque, inicio (verde) e fim (vermelho) das linhas."""
        from qgis.core import QgsWkbTypes

        from ..core.selection_reader import selected_geometries
        from .preview_manager import STYLE_END, STYLE_HIGHLIGHT, STYLE_POINT, STYLE_START

        layer = self._active_layer()
        reason = self._preview_block_reason(layer)
        if reason:
            self._set_status(reason)
            return 0
        manager = self._preview_manager()
        manager.clear()
        crs = layer.crs()
        shown = 0
        for _fid, geometry in selected_geometries(layer):
            kind = QgsWkbTypes.geometryType(geometry.wkbType())
            style = STYLE_POINT if kind == QgsWkbTypes.PointGeometry else STYLE_HIGHLIGHT
            if manager.show_geometry(geometry, style, crs=crs, source_layer_id=layer.id()):
                shown += 1
            if kind == QgsWkbTypes.LineGeometry:
                for part in geometry.constParts():
                    vertices = list(part.vertices())
                    if len(vertices) >= 2:
                        self._show_vertex(manager, vertices[0], STYLE_START, crs, layer.id())
                        self._show_vertex(manager, vertices[-1], STYLE_END, crs, layer.id())
        self._set_status(f"prévia: {shown} geometria(s) de '{layer.name()}'; só desenho, nada foi gravado.")
        self._update_active_tool(self._layer_facts(layer))
        return shown

    @staticmethod
    def _show_vertex(manager, vertex, style, crs, layer_id):
        from qgis.core import QgsGeometry, QgsPointXY

        manager.show_geometry(
            QgsGeometry.fromPointXY(QgsPointXY(vertex.x(), vertex.y())), style, crs=crs, source_layer_id=layer_id
        )

    def clear_preview(self) -> bool:
        if self._preview is None or not self._preview.count:
            return False
        self._preview.clear()
        return True

    def _update_tools(self, layer):
        facts = self._layer_facts(layer)
        for key, button in self.tool_buttons.items():
            tool = tool_by_key(key)
            state = tool_state(tool, available=self._available(tool), facts=facts)
            button.setEnabled(tool.source != SOURCE_UNAVAILABLE)
            button.setToolTip(tool.description if state.enabled else f"{tool.description}\n{state.reason}")
        self._update_active_tool(facts)

    def _update_active_tool(self, facts: LayerFacts):
        tool = tool_by_key(self._current_tool) if self._current_tool else None
        if tool is None:
            self.tool_label.setText(NO_VALUE)
            self.params_label.setText("Escolha uma ferramenta acima.")
            self.btn_apply.setEnabled(False)
            self.btn_cancel.setEnabled(self._map_tool_active or bool(self._preview and self._preview.count))
            return
        state = tool_state(tool, available=self._available(tool), facts=facts)
        origin = {
            SOURCE_NATIVE: "ação nativa do QGIS",
            SOURCE_PLUGIN: "tela existente do FortSmart",
            SOURCE_PANEL: "pilha de desfazer da camada",
        }.get(tool.source, "indisponível")
        self.tool_label.setText(f"{tool.label} ({origin})")
        self.params_label.setText(tool.description if state.enabled else f"{tool.description} {state.reason}")
        self.btn_apply.setEnabled(state.enabled)
        self.btn_apply.setToolTip("" if state.enabled else state.reason)
        self.btn_cancel.setEnabled(True)

    # ------------------------------------------------------------- acoes --
    @property
    def current_section(self) -> str:
        return next(
            (section for section, button in self.section_buttons.items() if button.isChecked()), SECTION_EDITOR
        )

    @property
    def current_tool(self) -> str | None:
        return self._current_tool

    def select_section(self, section: str):
        self.section_buttons[section].setChecked(True)
        self.tool_pages.setCurrentIndex(self._section_pages[section])

    def select_tool(self, key: str):
        tool = tool_by_key(key)
        if tool is None or tool.source == SOURCE_UNAVAILABLE:
            return
        self.select_section(tool.section)
        self._current_tool = key
        self.tool_buttons[key].setChecked(True)
        self._update_active_tool(self._layer_facts(self._active_layer()))
        self._set_status(f"'{tool.label}' escolhida; use Aplicar.")

    def apply(self) -> bool:
        tool = tool_by_key(self._current_tool) if self._current_tool else None
        if tool is None:
            self._set_status("escolha uma ferramenta antes de aplicar.")
            return False
        layer = self._active_layer()
        state = tool_state(tool, available=self._available(tool), facts=self._layer_facts(layer))
        if not state.enabled:
            self._set_status(state.reason)
            return False
        try:
            if tool.source == SOURCE_NATIVE:
                self._native_action(tool.target).trigger()
                self._map_tool_active = tool.map_tool
                message = (
                    f"ferramenta do QGIS ativa: {tool.label}. Cancelar volta para a navegação."
                    if tool.map_tool else f"{tool.label} acionado."
                )
            elif tool.source == SOURCE_PLUGIN:
                self._tool_actions[tool.target].trigger()
                message = f"tela aberta: {tool.label}."
            else:
                stack = self._undo_stack(layer)
                stack.undo() if tool.target == PANEL_UNDO else stack.redo()
                layer.triggerRepaint()
                message = f"{tool.label.lower()} em '{layer.name()}'."
        except Exception as exc:
            self._set_status(f"falha ao acionar '{tool.label}': {exc}")
            return False
        self._set_status(message)
        self._schedule(layer=True)
        return True

    def cancel(self):
        if self._map_tool_active:
            pan = self._native_action("actionPan")
            if pan is not None:
                pan.trigger()
        cleared = self.clear_preview()
        self._clear_tool()
        self._set_status("ferramenta cancelada" + ("; prévia limpa." if cleared else "."))

    def _clear_tool(self):
        self._map_tool_active = False
        self._current_tool = None
        self.tool_group.setExclusive(False)
        for button in self.tool_buttons.values():
            button.setChecked(False)
        self.tool_group.setExclusive(True)
        self._update_active_tool(self._layer_facts(self._active_layer()))

    def _on_field_chosen(self, index):
        if self._populating or index < 0:
            return
        field_id = self.field_combo.itemData(index)
        if field_id is None:
            self.service.clear_explicit_field()
            self._set_status("talhão automático (pela camada ativa).")
        else:
            try:
                self.service.set_explicit_field(field_id)
            except ValueError as exc:
                self._set_status(str(exc))
                return
            self._set_status(f"talhão de trabalho: {field_id}.")
        self._schedule(context=True)

    def _set_status(self, text: str):
        self.status_label.setText(f"Status: {text}")
