# -*- coding: utf-8 -*-
"""Conversor de zonas UTM / CRS — lote automatico + padroes SIRGAS 2000 / UTM."""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)
from qgis.core import QgsCoordinateReferenceSystem, QgsProject, QgsVectorLayer
from qgis.gui import QgsMapLayerComboBox

from ..core.crs import (
    inspect_authid,
    list_sirgas_utm_south_standards,
    normalize_authid,
    sirgas_utm_standard_summary,
)
from ..core.zone_converter import (
    build_zone_conversion_plan,
    classify_coordinate_pair,
    crs_status,
)
from .crs_reproject_service import (
    collect_project_vector_layers,
    ensure_layers_metric,
    layer_centroid_lonlat,
    layer_needs_reprojection,
    reproject_layers_batch,
    reproject_vector_layer,
    suggest_target_from_layers,
)
from .layer_combo_utils import (
    configure_layer_combo,
    is_polygon_like_vector_layer,
    prefer_metric_polygon_layer,
    refresh_polygon_layer_combo,
)


class CrsZoneConverterDialog(QDialog):
    """Converte uma ou varias camadas para SIRGAS 2000 / UTM (lista oficial)."""

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.setWindowTitle("FortSmart — Conversor de zona / coordenadas")
        self.resize(760, 720)
        self._last_plan = None
        self._build_ui()
        self.layer_combo.layerChanged.connect(self._refresh_analysis)
        self.target_combo.currentIndexChanged.connect(self._on_target_changed)
        self._refresh_layer_checklist()
        self._refresh_analysis()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        intro = QLabel(
            "<b>Padrao FortSmart:</b> somente <b>SIRGAS 2000 / UTM</b> "
            "(EPSG:31978–31985). Converta <b>varias camadas de uma vez</b> "
            "(limite, A-B, obstaculos, plantio, pulverizacao) — nao so a bordadura."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        guide = QTextEdit()
        guide.setReadOnly(True)
        guide.setMaximumHeight(100)
        guide.setPlainText(sirgas_utm_standard_summary())
        layout.addWidget(guide)

        # --- Lote ---
        batch_box = QGroupBox("Conversao automatica em lote")
        batch_layout = QVBoxLayout(batch_box)
        batch_layout.addWidget(
            QLabel(
                "Marque as camadas (ou use 'Selecionar todas que precisam') e "
                "clique em converter. O destino e o SIRGAS recomendado pela longitude."
            )
        )
        self.layer_list = QListWidget()
        self.layer_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.layer_list.setMinimumHeight(140)
        batch_layout.addWidget(self.layer_list)

        batch_btns = QHBoxLayout()
        self.btn_refresh_list = QPushButton("Atualizar lista")
        self.btn_refresh_list.clicked.connect(self._refresh_layer_checklist)
        self.btn_select_needed = QPushButton("Selecionar todas que precisam")
        self.btn_select_needed.clicked.connect(self._select_layers_needing)
        self.btn_select_none = QPushButton("Limpar selecao")
        self.btn_select_none.clicked.connect(self._clear_layer_selection)
        self.btn_convert_batch = QPushButton("Converter marcadas automaticamente")
        self.btn_convert_batch.setStyleSheet("font-weight: bold;")
        self.btn_convert_batch.clicked.connect(self._convert_batch)
        batch_btns.addWidget(self.btn_refresh_list)
        batch_btns.addWidget(self.btn_select_needed)
        batch_btns.addWidget(self.btn_select_none)
        batch_layout.addLayout(batch_btns)
        batch_layout.addWidget(self.btn_convert_batch)
        layout.addWidget(batch_box)

        # --- Destino ---
        target_box = QGroupBox("Destino (somente padroes oficiais)")
        target_form = QFormLayout(target_box)
        self.recommended_label = QLabel("-")
        self.recommended_label.setWordWrap(True)
        self.recommended_label.setStyleSheet("font-weight: bold; color: #0d47a1;")
        target_form.addRow("Recomendado:", self.recommended_label)
        self.target_combo = QComboBox()
        self._fill_target_combo()
        target_form.addRow("Converter para:", self.target_combo)
        self.target_reason = QLabel("")
        self.target_reason.setWordWrap(True)
        target_form.addRow("Motivo:", self.target_reason)
        layout.addWidget(target_box)

        # --- Uma camada (detalhe) ---
        layer_box = QGroupBox("Detalhe de uma camada (opcional)")
        form = QFormLayout(layer_box)
        self.layer_combo = QgsMapLayerComboBox()
        configure_layer_combo(self.layer_combo, "VectorLayer")
        form.addRow("Camada:", self.layer_combo)
        prefer_row = QHBoxLayout()
        self.btn_prefer_metric = QPushButton("Preferir poligono metrico")
        self.btn_prefer_metric.clicked.connect(self._prefer_metric_polygon)
        prefer_row.addWidget(self.btn_prefer_metric)
        form.addRow("", prefer_row)
        self.crs_label = QLabel("-")
        form.addRow("CRS atual:", self.crs_label)
        self.status_label = QLabel("-")
        self.status_label.setWordWrap(True)
        form.addRow("Status:", self.status_label)
        self.metric_hint = QLabel("")
        self.metric_hint.setWordWrap(True)
        form.addRow("Ja metrico no projeto:", self.metric_hint)
        layout.addWidget(layer_box)

        coord_box = QGroupBox("Conferir coordenadas (opcional)")
        coord_form = QFormLayout(coord_box)
        self.x_spin = QDoubleSpinBox()
        self.x_spin.setRange(-99999999, 99999999)
        self.x_spin.setDecimals(6)
        self.y_spin = QDoubleSpinBox()
        self.y_spin.setRange(-99999999, 99999999)
        self.y_spin.setDecimals(6)
        coord_form.addRow("X / Lon:", self.x_spin)
        coord_form.addRow("Y / Lat:", self.y_spin)
        self.coord_hint = QLabel("")
        self.coord_hint.setWordWrap(True)
        coord_form.addRow("Interpretacao:", self.coord_hint)
        coord_btns = QHBoxLayout()
        self.btn_use_centroid = QPushButton("Usar centroide")
        self.btn_use_centroid.clicked.connect(self._fill_centroid)
        test_btn = QPushButton("Analisar")
        test_btn.clicked.connect(self._analyze_coordinates)
        coord_btns.addWidget(self.btn_use_centroid)
        coord_btns.addWidget(test_btn)
        coord_form.addRow(coord_btns)
        layout.addWidget(coord_box)

        self.report = QTextEdit()
        self.report.setReadOnly(True)
        layout.addWidget(self.report)

        actions = QHBoxLayout()
        self.btn_reproject = QPushButton("Reprojetar so a camada do detalhe")
        self.btn_reproject.clicked.connect(self._reproject_layer)
        self.btn_set_project = QPushButton("Definir CRS do projeto = destino")
        self.btn_set_project.clicked.connect(self._set_project_crs)
        actions.addWidget(self.btn_reproject)
        actions.addWidget(self.btn_set_project)
        layout.addLayout(actions)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _fill_target_combo(self, *, preferred: str | None = None) -> None:
        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        for authid, zone, hint in list_sirgas_utm_south_standards():
            self.target_combo.addItem(
                f"{authid} — SIRGAS 2000 / UTM {zone}S — {hint}",
                authid,
            )
        if preferred:
            idx = self.target_combo.findData(preferred)
            if idx >= 0:
                self.target_combo.setCurrentIndex(idx)
        self.target_combo.blockSignals(False)

    def _selected_target(self) -> str:
        data = self.target_combo.currentData()
        return str(data) if data else "EPSG:31981"

    def _current_layer(self) -> QgsVectorLayer | None:
        layer = self.layer_combo.currentLayer()
        return layer if isinstance(layer, QgsVectorLayer) else None

    def _resolve_target_authid(self) -> str:
        target = self._selected_target()
        layers = collect_project_vector_layers()
        suggested = suggest_target_from_layers(layers)
        if suggested and (
            self._last_plan is None
            or normalize_authid(self._last_plan.target_authid) == normalize_authid(suggested)
        ):
            # Mantem escolha do usuario se diferir; senao sincroniza sugerido.
            pass
        if self.target_combo.currentIndex() < 0 and suggested:
            self._fill_target_combo(preferred=suggested)
            return suggested
        return target

    def _refresh_layer_checklist(self) -> None:
        target = self._selected_target()
        suggested = suggest_target_from_layers(collect_project_vector_layers())
        if suggested:
            self._fill_target_combo(preferred=suggested)
            target = suggested
            self.recommended_label.setText(
                f"{suggested} — recomendado pela longitude das camadas do projeto"
            )

        self.layer_list.clear()
        for layer in collect_project_vector_layers():
            auth = normalize_authid(layer.crs().authid()) or "?"
            needs = layer_needs_reprojection(layer, target)
            status = crs_status(auth)
            tag = "PRECISA" if needs else "OK"
            if status.value == "geographic":
                tag = "GRAUS→UTM"
            label = f"[{tag}] {layer.name()}  ({auth})"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, layer.id())
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if needs else Qt.Unchecked)
            self.layer_list.addItem(item)

    def _select_layers_needing(self) -> None:
        target = self._selected_target()
        for i in range(self.layer_list.count()):
            item = self.layer_list.item(i)
            layer = QgsProject.instance().mapLayer(item.data(Qt.UserRole))
            if isinstance(layer, QgsVectorLayer) and layer_needs_reprojection(layer, target):
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)

    def _clear_layer_selection(self) -> None:
        for i in range(self.layer_list.count()):
            self.layer_list.item(i).setCheckState(Qt.Unchecked)

    def _checked_layers(self) -> list[QgsVectorLayer]:
        layers: list[QgsVectorLayer] = []
        for i in range(self.layer_list.count()):
            item = self.layer_list.item(i)
            if item.checkState() != Qt.Checked:
                continue
            layer = QgsProject.instance().mapLayer(item.data(Qt.UserRole))
            if isinstance(layer, QgsVectorLayer):
                layers.append(layer)
        return layers

    def _convert_batch(self) -> None:
        layers = self._checked_layers()
        if not layers:
            QMessageBox.warning(
                self,
                "FortSmart",
                "Marque ao menos uma camada, ou clique "
                "'Selecionar todas que precisam'.",
            )
            return
        target = self._resolve_target_authid()
        try:
            result = ensure_layers_metric(layers, target_authid=target)
        except Exception as exc:
            QMessageBox.warning(self, "FortSmart", str(exc))
            return

        self.iface.mapCanvas().refresh()
        self._refresh_layer_checklist()
        self.report.setPlainText(result.summary())
        if result.failed and not result.converted:
            QMessageBox.warning(self, "FortSmart", result.summary())
            return
        QMessageBox.information(
            self,
            "FortSmart",
            f"Conversao em lote concluida.\n\n{result.summary()}\n\n"
            "Use as camadas com (EPSG:…) no nome no Planejamento "
            "(limite, A-B, obstaculos, plantio, pulverizacao).",
        )

    def _prefer_metric_polygon(self) -> None:
        refresh_polygon_layer_combo(self.layer_combo)
        prefer_metric_polygon_layer(self.layer_combo)
        current = self.layer_combo.currentLayer()
        info = inspect_authid(current.crs().authid() if current else "")
        if info.is_projected_metric:
            self._refresh_analysis()
            return
        for layer in QgsProject.instance().mapLayers().values():
            if not is_polygon_like_vector_layer(layer):
                continue
            auth = normalize_authid(layer.crs().authid())
            if auth.startswith("EPSG:3197") or auth.startswith("EPSG:3198"):
                self.layer_combo.setLayer(layer)
                break
        self._refresh_analysis()

    def _metric_layers_hint(self, recommended_authid: str) -> str:
        matches = []
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if normalize_authid(layer.crs().authid()) == recommended_authid:
                matches.append(layer.name())
        if matches:
            names = ", ".join(matches[:6])
            extra = f" (+{len(matches) - 6})" if len(matches) > 6 else ""
            return f"Ja em {recommended_authid}: {names}{extra}"
        return f"Nenhuma camada ainda em {recommended_authid}."

    def _refresh_analysis(self, *_args) -> None:
        layer = self._current_layer()
        if layer is None:
            self.crs_label.setText("-")
            self.status_label.setText("-")
            self.report.setPlainText(
                "Use a conversao em lote acima para limite, A-B, obstaculos, etc."
            )
            return

        authid = layer.crs().authid() or "?"
        status = crs_status(authid)
        self.crs_label.setText(authid)
        status_text = {
            "ok": "OK — CRS metrico",
            "geographic": "Geografico (graus) — converter",
            "unsupported": "Fora do padrao — converter para SIRGAS 2000 / UTM",
            "missing": "CRS ausente",
        }.get(status.value, status.value)
        self.status_label.setText(status_text)

        centroid = layer_centroid_lonlat(layer)
        if centroid is None:
            self.recommended_label.setText("-")
            self.report.setPlainText(f"Camada '{layer.name()}' sem geometria.")
            return
        lon, lat = centroid
        self.x_spin.setValue(lon)
        self.y_spin.setValue(lat)
        try:
            plan = build_zone_conversion_plan(
                authid, lon, lat, preferred_target=self._selected_target()
            )
        except Exception:
            plan = build_zone_conversion_plan(authid, lon, lat)
        self._apply_plan_to_ui(plan, select_primary=True)

    def _apply_plan_to_ui(self, plan, *, select_primary: bool) -> None:
        self._last_plan = plan
        primary = next(
            (item for item in plan.recommended_targets if item.get("is_primary")),
            None,
        )
        if primary:
            self.recommended_label.setText(
                f"{primary['authid']} (zona {primary['zone']}S) — {primary['reason']}"
            )
            if select_primary:
                self._fill_target_combo(preferred=str(primary["authid"]))
        else:
            self.recommended_label.setText(plan.target_authid)
        auth_for_hint = str(primary["authid"]) if primary else plan.target_authid
        self.metric_hint.setText(self._metric_layers_hint(auth_for_hint))
        self._update_target_reason()
        self._show_plan(plan)

    def _update_target_reason(self) -> None:
        if self._last_plan is None:
            return
        chosen = self._selected_target()
        for item in self._last_plan.recommended_targets:
            if item.get("authid") == chosen:
                mark = " ★ RECOMENDADO" if item.get("is_primary") else ""
                self.target_reason.setText(f"{item.get('reason', '')}{mark}")
                return
        self.target_reason.setText("Destino oficial SIRGAS 2000 / UTM.")

    def _on_target_changed(self, *_args) -> None:
        self._update_target_reason()
        layer = self._current_layer()
        if layer is None:
            return
        try:
            plan = build_zone_conversion_plan(
                layer.crs().authid(),
                self.x_spin.value(),
                self.y_spin.value(),
                preferred_target=self._selected_target(),
            )
            self._last_plan = plan
            self._show_plan(plan)
        except Exception as exc:
            self.report.setPlainText(str(exc))

    def _show_plan(self, plan) -> None:
        lines = [
            plan.summary(),
            "",
            f"Origem: {plan.source_authid}",
            f"Destino: {plan.target_authid} (zona {plan.utm_zone}S)",
            f"Centro: lon {plan.longitude:.6f}, lat {plan.latitude:.6f}",
            f"Reprojecao necessaria: {'sim' if plan.needs_reprojection else 'nao'}",
            "",
            "Dica: use 'Converter marcadas automaticamente' para limite + A-B + "
            "obstaculos + plantio + pulverizacao de uma vez.",
        ]
        self.report.setPlainText("\n".join(lines))

    def _fill_centroid(self) -> None:
        layer = self._current_layer()
        if layer is None:
            return
        centroid = layer_centroid_lonlat(layer)
        if centroid is None:
            QMessageBox.warning(self, "FortSmart", "Camada sem geometria.")
            return
        self.x_spin.setValue(centroid[0])
        self.y_spin.setValue(centroid[1])
        self._analyze_coordinates()

    def _analyze_coordinates(self) -> None:
        layer = self._current_layer()
        x = self.x_spin.value()
        y = self.y_spin.value()
        self.coord_hint.setText(classify_coordinate_pair(x, y).explanation)
        if layer is None:
            return
        try:
            plan = build_zone_conversion_plan(
                layer.crs().authid(),
                x,
                y,
                preferred_target=self._selected_target(),
            )
        except Exception as exc:
            self.report.setPlainText(str(exc))
            return
        self._apply_plan_to_ui(plan, select_primary=True)

    def _reproject_layer(self) -> None:
        layer = self._current_layer()
        if layer is None:
            QMessageBox.warning(self, "FortSmart", "Selecione uma camada no detalhe.")
            return
        target = self._selected_target()
        try:
            result = ensure_layers_metric([layer], target_authid=target)
        except Exception as exc:
            QMessageBox.warning(self, "FortSmart", str(exc))
            return
        mapped = result.mapping.get(layer.id())
        if mapped is not None:
            self.layer_combo.setLayer(mapped)
        self.iface.mapCanvas().refresh()
        self._refresh_layer_checklist()
        self._refresh_analysis()
        QMessageBox.information(self, "FortSmart", result.summary())

    def _set_project_crs(self) -> None:
        target = self._selected_target()
        crs = QgsCoordinateReferenceSystem(target)
        if not crs.isValid():
            QMessageBox.warning(self, "FortSmart", f"CRS invalido: {target}")
            return
        QgsProject.instance().setCrs(crs)
        self.iface.mapCanvas().refresh()
        QMessageBox.information(
            self,
            "FortSmart",
            f"CRS do projeto definido para {target}.",
        )
