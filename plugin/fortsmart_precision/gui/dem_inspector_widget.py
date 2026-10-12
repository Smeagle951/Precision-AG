# -*- coding: utf-8 -*-
"""Inspetor DEM na secao Terreno do AgroCAD (Subfase 0F); somente leitura."""

from __future__ import annotations

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..core.dem_inspector import (
    COVERAGE_LABELS,
    COVERAGE_UNKNOWN,
    UNIT_FEET,
    UNIT_LABELS,
    UNIT_METERS,
    CoverageResult,
    classify_raster,
    metadata_diagnostics,
    resolution_text,
)
from ..core.dem_raster_reader import (
    DemCoverageTask,
    data_type_name,
    field_boundary,
    prepare_coverage,
    raster_layers,
    read_metadata,
)
from ..core.project_context import SEVERITY_ERROR, SEVERITY_WARNING

NO_VALUE = "—"
FUTURE_ANALYSES = ("Declividade", "Curvas de nível", "Perfil de linhas", "Escoamento superficial")
_SEVERITY_MARK = {SEVERITY_ERROR: "Erro", SEVERITY_WARNING: "Aviso"}


class DemInspectorWidget(QWidget):
    """Escolhe um raster carregado, mostra metadados e verifica a cobertura do talhao."""

    def __init__(self, iface=None, service=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.service = service
        self._field_id: str | None = None
        self._layer_id: str | None = None
        self._meta = None
        self._coverage: CoverageResult | None = None
        self._coverage_diagnostics: tuple = ()
        self._declared: dict = {}
        self._generation = 0
        self._task = None
        self._connections: list = []
        self._layer_connections: list = []
        self._populating = False
        self._boundary_cache = None
        self._diagnostic_items: tuple = ()
        self._build_ui()

    # ------------------------------------------------------------------ UI --
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("FORTSMART — TERRENO")
        font = QFont(title.font())
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)
        self.field_label = QLabel()
        self.field_label.setWordWrap(True)
        layout.addWidget(self.field_label)

        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Fonte DEM:"))
        self.raster_combo = QComboBox()
        self.raster_combo.currentIndexChanged.connect(self._on_raster_chosen)
        source_row.addWidget(self.raster_combo, 1)
        layout.addLayout(source_row)

        form = QFormLayout()
        self.labels = {}
        for key, title_text in (
            ("suitability", "Avaliação:"),
            ("source", "Arquivo:"),
            ("crs", "CRS:"),
            ("resolution", "Resolução:"),
            ("size", "Bandas / tipo:"),
            ("nodata", "NoData:"),
            ("elevation", "Elevação:"),
            ("horizontal", "Unidade horizontal:"),
            ("vertical", "Unidade vertical:"),
            ("coverage", "Cobertura do talhão:"),
        ):
            label = QLabel(NO_VALUE)
            label.setWordWrap(True)
            self.labels[key] = label
            form.addRow(title_text, label)
            if key == "vertical":
                self.vertical_combo = QComboBox()
                self.vertical_combo.addItem("Não declarar", None)
                self.vertical_combo.addItem("Declarar: metros", UNIT_METERS)
                self.vertical_combo.addItem("Declarar: pés", UNIT_FEET)
                self.vertical_combo.setToolTip("Vale só nesta sessão; o arquivo e o projeto não são alterados.")
                self.vertical_combo.currentIndexChanged.connect(self._on_vertical_declared)
                form.addRow("Declarar unidade:", self.vertical_combo)
        layout.addLayout(form)

        box = QGroupBox("DIAGNÓSTICO")
        box_layout = QVBoxLayout(box)
        self.diagnostics = QTextBrowser()
        self.diagnostics.setOpenLinks(False)
        self.diagnostics.setMinimumHeight(90)
        box_layout.addWidget(self.diagnostics)
        self.btn_check = QPushButton("Verificar DEM")
        self.btn_check.setToolTip("Lê uma amostra limitada do raster em segundo plano; nada é gravado.")
        self.btn_check.clicked.connect(self.check)
        box_layout.addWidget(self.btn_check)
        layout.addWidget(box, 1)
        self.status_label = QLabel("Status: escolha um raster carregado no QGIS.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        future = QLabel(
            "Análises futuras (indisponíveis nesta versão):<br>"
            + "<br>".join(f"• {name} — indisponível" for name in FUTURE_ANALYSES)
        )
        future.setStyleSheet("color: #777;")
        future.setWordWrap(True)
        layout.addWidget(future)
        self._show_metadata(None)

    # --------------------------------------------------------------- sinais --
    @property
    def connection_count(self) -> int:
        return len(self._connections) + len(self._layer_connections)

    @property
    def project(self):
        return self.service.project

    @staticmethod
    def _safe_disconnect(signal, slot):
        try:
            signal.disconnect(slot)
        except (RuntimeError, TypeError):
            pass

    def _connect(self):
        if self._connections:
            return
        project = self.project
        for signal, slot in (
            (project.layersAdded, self._on_layers_added),
            (project.layersWillBeRemoved, self._on_layers_will_be_removed),
            (project.cleared, self._on_project_reset),
            (project.readProject, self._on_project_reset),
        ):
            signal.connect(slot)
            self._connections.append((signal, slot))
        self._bind_layer()

    def _disconnect(self):
        for signal, slot in self._connections:
            self._safe_disconnect(signal, slot)
        self._connections = []
        self._unbind_layer()

    def _bind_layer(self):
        self._unbind_layer()
        layer = self._layer()
        if layer is None or not self._connections:
            return
        layer.crsChanged.connect(self._on_raster_crs_changed)
        self._layer_connections.append((layer.crsChanged, self._on_raster_crs_changed))

    def _unbind_layer(self):
        for signal, slot in self._layer_connections:
            self._safe_disconnect(signal, slot)
        self._layer_connections = []

    def showEvent(self, event):
        super().showEvent(event)
        self._connect()
        self.refresh()

    def hideEvent(self, event):
        self._disconnect()
        self._cancel_task()
        super().hideEvent(event)

    def shutdown(self):
        self._disconnect()
        self._cancel_task()

    def _on_layers_added(self, layers):
        if any(hasattr(layer, "bandCount") for layer in layers or ()):
            self._fill_rasters()

    def _on_layers_will_be_removed(self, layer_ids):
        if self._layer_id in set(layer_ids or ()):
            self._unbind_layer()
            self._layer_id = None
            self._meta = None
            self.invalidate("o raster escolhido foi removido do projeto.")
            self._show_metadata(None)
        removed = set(layer_ids or ())
        self._fill_rasters(exclude=removed)

    def _on_project_reset(self, *args):
        self._declared = {}
        self._layer_id = None
        self._meta = None
        self.invalidate("projeto trocado.")
        self._fill_rasters()
        self._show_metadata(None)

    def _on_raster_crs_changed(self, *args):
        self.invalidate("o CRS do raster mudou.")
        self._load_metadata()

    # ------------------------------------------------------------- estado --
    @property
    def field_id(self) -> str | None:
        return self._field_id

    @property
    def layer_id(self) -> str | None:
        return self._layer_id

    @property
    def metadata(self):
        return self._meta

    @property
    def coverage(self) -> CoverageResult | None:
        return self._coverage

    @property
    def task(self):
        return self._task

    def _layer(self):
        if not self._layer_id:
            return None
        return self.project.mapLayer(self._layer_id)

    def set_field(self, field_id):
        """Talhao efetivo do AgroCAD (escolhido ou da camada ativa)."""
        if field_id == self._field_id:
            return
        self._field_id = field_id
        self._update_field_label()
        self.invalidate("o talhão mudou.")
        self._refresh_diagnostics()

    def refresh(self):
        self._update_field_label()
        self._fill_rasters()
        self._load_metadata()

    def _update_field_label(self):
        self.field_label.setText(
            f"Talhão: {self._field_id or 'não definido'} (troque em 'Talhão de trabalho', acima)"
        )

    def _fill_rasters(self, *, exclude=()):
        self._populating = True
        try:
            self.raster_combo.clear()
            self.raster_combo.addItem("Selecione um raster…", None)
            candidates, others = [], []
            for layer in raster_layers(self.project):
                if layer.id() in exclude:
                    continue
                suitable = classify_raster(
                    band_count=int(layer.bandCount()),
                    data_type=data_type_name(layer.dataProvider()),
                    provider=layer.providerType(),
                )
                (candidates if suitable.candidate else others).append((layer, suitable))
            for layer, suitable in candidates:
                self.raster_combo.addItem(layer.name(), layer.id())
                self.raster_combo.setItemData(self.raster_combo.count() - 1, suitable.text, Qt.ToolTipRole)
            for layer, suitable in others:
                self.raster_combo.addItem(f"{layer.name()} (não recomendado)", layer.id())
                self.raster_combo.setItemData(self.raster_combo.count() - 1, suitable.text, Qt.ToolTipRole)
            index = self.raster_combo.findData(self._layer_id) if self._layer_id else 0
            self.raster_combo.setCurrentIndex(max(index, 0))
        finally:
            self._populating = False

    def select_raster(self, layer_id):
        index = self.raster_combo.findData(layer_id)
        if index < 0:
            raise ValueError(f"Raster '{layer_id}' não está carregado no projeto.")
        self.raster_combo.setCurrentIndex(index)

    def _on_raster_chosen(self, index):
        if self._populating:
            return
        layer_id = self.raster_combo.itemData(index)
        if layer_id == self._layer_id:
            return
        self._layer_id = layer_id
        self._bind_layer()
        self.invalidate("a fonte DEM mudou." if layer_id else "nenhum raster escolhido.")
        self._load_metadata()

    def _on_vertical_declared(self, index):
        if self._populating or not self._layer_id:
            return
        unit = self.vertical_combo.itemData(index)
        if unit is None:
            self._declared.pop(self._layer_id, None)
        else:
            self._declared[self._layer_id] = unit
        self.invalidate("a unidade vertical declarada mudou.")
        self._load_metadata()

    def _load_metadata(self):
        layer = self._layer()
        if layer is None:
            self._meta = None
            self._show_metadata(None)
            return
        try:
            self._meta = read_metadata(layer, declared_vertical=self._declared.get(layer.id()))
        except Exception as exc:
            self._meta = None
            self._show_metadata(None)
            self._set_status(f"falha ao ler os metadados de '{layer.name()}': {exc}")
            return
        self._show_metadata(self._meta)

    # --------------------------------------------------------- apresentacao --
    def _show_metadata(self, meta):
        values = dict.fromkeys(self.labels, NO_VALUE)
        self.btn_check.setEnabled(meta is not None)
        self._populating = True
        try:
            declared = self._declared.get(meta.layer_id) if meta is not None else None
            self.vertical_combo.setCurrentIndex(max(self.vertical_combo.findData(declared), 0))
            self.vertical_combo.setEnabled(meta is not None)
        finally:
            self._populating = False
        if meta is not None:
            values.update(
                suitability=meta.suitability.text,
                source=meta.source,
                crs=meta.crs.authid if meta.crs is not None else "sem CRS",
                resolution=resolution_text(meta, latitude=self._latitude(meta)),
                size=f"{meta.band_count} banda(s) · {meta.data_type or 'tipo desconhecido'} · "
                     f"{meta.width} × {meta.height} pixels",
                nodata=", ".join(meta.nodata) if meta.has_nodata else "sem valor NoData definido",
                horizontal=UNIT_LABELS.get(meta.horizontal_unit, "não identificada"),
                vertical=meta.vertical.text,
            )
        values.update(self._coverage_values())
        for key, value in values.items():
            self.labels[key].setText(value)
        self._refresh_diagnostics()

    @staticmethod
    def _latitude(meta):
        if meta.horizontal_unit != "deg":
            return None
        return (meta.extent[1] + meta.extent[3]) / 2.0

    def _coverage_values(self) -> dict:
        coverage = self._coverage
        if coverage is None:
            return {"coverage": COVERAGE_LABELS[COVERAGE_UNKNOWN].capitalize() + " — use 'Verificar DEM'.",
                    "elevation": "não lida (use 'Verificar DEM')"}
        values = {"coverage": coverage.text}
        if coverage.elevation is not None:
            low, high, mean = coverage.elevation
            unit = self._meta.vertical.unit if self._meta is not None else None
            suffix = f" {UNIT_LABELS[unit]}" if unit else " (unidade não confirmada)"
            values["elevation"] = f"{low:.2f} a {high:.2f}, média {mean:.2f}{suffix} — amostra no talhão"
        else:
            values["elevation"] = "sem valores válidos no talhão" if coverage.sampled_pixels else NO_VALUE
        return values

    def _refresh_diagnostics(self):
        items = []
        if self._meta is not None:
            items.extend(metadata_diagnostics(self._meta, field_crs_authid=self._boundary_crs()))
        items.extend(self._coverage_diagnostics)
        self._diagnostic_items = tuple(items)
        if not items:
            self.diagnostics.setHtml("<i>Sem diagnóstico.</i>")
            return
        rows = []
        for item in items:
            mark = _SEVERITY_MARK.get(item.severity, "Nota")
            rows.append(f"<li><b>{mark}:</b> {item.message}</li>")
        self.diagnostics.setHtml("<ul>" + "".join(rows) + "</ul>")

    def _boundary_crs(self):
        if not self._field_id:
            return None
        cached = self._boundary_cache
        if cached is not None and cached[0] == self._field_id:
            return cached[1]
        try:
            authid = field_boundary(self.service, self._field_id).crs_authid or None
        except Exception:
            authid = None
        self._boundary_cache = (self._field_id, authid)
        return authid

    @property
    def diagnostic_codes(self) -> set:
        return {item.code for item in self._diagnostic_items}

    def _set_status(self, text: str):
        self.status_label.setText(f"Status: {text}")

    # ------------------------------------------------------------ verificar --
    def invalidate(self, reason: str = ""):
        """Descarta a verificacao anterior (fonte, talhao, CRS ou projeto mudou)."""
        self._generation += 1
        self._cancel_task()
        self._boundary_cache = None
        had_result = self._coverage is not None or bool(self._coverage_diagnostics)
        self._coverage = None
        self._coverage_diagnostics = ()
        for key, value in self._coverage_values().items():
            self.labels[key].setText(value)
        if reason:
            self._set_status(reason + (" Diagnóstico anterior descartado." if had_result else ""))
        self._refresh_diagnostics()

    def _cancel_task(self):
        task, self._task = self._task, None
        if task is not None:
            task.on_done = None
            try:
                task.cancel()
            except RuntimeError:
                pass
        self.btn_check.setEnabled(self._meta is not None)

    def check(self) -> bool:
        """Inicia a verificacao em segundo plano; False se nao houver o que verificar."""
        layer = self._layer()
        if layer is None or self._meta is None:
            self._set_status("escolha um raster antes de verificar.")
            return False
        self.invalidate()
        boundary = field_boundary(self.service, self._field_id)
        job, found = prepare_coverage(layer, boundary, project=self.project, vertical_unit=self._meta.vertical.unit)
        if job is None:
            self._coverage = CoverageResult(COVERAGE_UNKNOWN, diagnostics=found)
            self._coverage_diagnostics = found
            self._show_metadata(self._meta)
            self._set_status("cobertura não verificada; veja o diagnóstico.")
            return False
        generation = self._generation
        task = DemCoverageTask(job, lambda done, ok: self._on_task_done(done, ok, generation))
        self._task = task
        self.btn_check.setEnabled(False)
        self._set_status(f"verificando '{layer.name()}' em segundo plano…")
        QgsApplication.taskManager().addTask(task)
        return True

    def _on_task_done(self, task, ok, generation):
        if task is not self._task or generation != self._generation:
            return
        self._task = None
        self.btn_check.setEnabled(self._meta is not None)
        if not ok or task.result is None:
            self._set_status("verificação interrompida" + (f": {task.error}" if task.error else "."))
            return
        self._coverage = task.result
        self._coverage_diagnostics = task.result.diagnostics
        self._show_metadata(self._meta)
        self._set_status(f"verificação concluída: cobertura {COVERAGE_LABELS[task.result.status]}; nada foi gravado.")
