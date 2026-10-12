# -*- coding: utf-8 -*-
"""Tela do simulador de rota: le as passadas, anima a maquina e mostra o progresso."""

from __future__ import annotations

from qgis.PyQt.QtCore import QElapsedTimer, QTimer
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsCsException, QgsMapLayerProxyModel, QgsProject
from qgis.gui import QgsMapLayerComboBox
from shapely.errors import GEOSException

from ..core.coverage_engine import CoverageEngine, CoverageSettings
from ..core.crs import CrsValidationError
from ..core.layer_roles import find_layer_by_role
from ..core.route_simulation_engine import SPEED_MULTIPLIERS, RouteSimulationEngine, SimulationError
from ..core.simulation_route import RouteMode, RouteValidationError, build_ordered_route
from ..domain.machine_profile import MACHINE_TYPE_LABELS, MachineProfile, MachineType
from ..validator.route_validator_engine import RouteValidatorEngine
from ..validator.validation_config import ValidationConfig
from ..validator.validation_result import ValidationResult
from ..validator.warning_model import Severity
from .route_coverage_renderer import COVERAGE_OPACITIES, DEFAULT_COVERAGE_OPACITY, CoverageRenderer
from .route_simulation_renderer import RouteSimulationRenderer
from .route_simulation_source import RouteSource, read_allowed_area, read_obstacles, read_route_source
from .route_warning_panel import RouteWarningPanel

TICK_MS = 50
MODE_LABELS = (
    (RouteMode.SERPENTINE, "Vai-e-volta"),
    (RouteMode.SAME_DIRECTION, "Mesmo sentido"),
    (RouteMode.CUSTOM_SEQUENCE, "Sentido desenhado na camada"),
)


def format_duration(seconds: float) -> str:
    total = int(round(seconds))
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def _constant_attribute(layer, name: str) -> float | None:
    """Valor positivo unico do campo em todas as feicoes; senao None (nada e inventado)."""
    if layer is None or name not in layer.fields().names():
        return None
    values = {feature[name] for feature in layer.getFeatures()}
    values = {float(v) for v in values if isinstance(v, (int, float)) and v > 0}
    return values.pop() if len(values) == 1 else None


def format_pass_warnings(warnings) -> str:
    if not warnings:
        return "nenhum"
    critical = sum(1 for item in warnings if item.severity is Severity.CRITICAL)
    return f"{len(warnings)} ({critical} critico(s))" if critical else str(len(warnings))


class RouteSimulationDialog(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.engine: RouteSimulationEngine | None = None
        self.renderer: RouteSimulationRenderer | None = None
        self.coverage: CoverageEngine | None = None
        self.coverage_renderer: CoverageRenderer | None = None
        self.validator = RouteValidatorEngine()
        self.validation: ValidationResult | None = None
        self._last_pass_id: str | None = None
        self.sequence_source = ""
        self.timer = QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self._tick)
        self.clock = QElapsedTimer()
        self.setWindowTitle("Simulador de rota")
        self._build()
        self._select_default_layer()
        self._update_buttons()

    # ------------------------------------------------------------- tela ----
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs)
        simulation_page = QWidget()
        root = QVBoxLayout(simulation_page)
        self.tabs.addTab(simulation_page, "Simulacao")
        self.tabs.addTab(self._build_validation_page(), "Validacao")

        source_box = QGroupBox("Rota (passadas existentes)")
        source_form = QFormLayout(source_box)
        self.layer_combo = QgsMapLayerComboBox()
        self.layer_combo.setFilters(QgsMapLayerProxyModel.LineLayer)
        source_form.addRow("Passadas:", self.layer_combo)
        self.selected_check = QCheckBox("Somente feicoes selecionadas")
        source_form.addRow(self.selected_check)
        self.mode_combo = QComboBox()
        for mode, label in MODE_LABELS:
            self.mode_combo.addItem(label, mode)
        source_form.addRow("Sentido:", self.mode_combo)
        root.addWidget(source_box)

        machine_box = QGroupBox("Maquina (somente visual)")
        machine_form = QFormLayout(machine_box)
        self.machine_name_edit = QLineEdit("Maquina")
        machine_form.addRow("Nome:", self.machine_name_edit)
        self.machine_type_combo = QComboBox()
        for machine_type, label in MACHINE_TYPE_LABELS.items():
            self.machine_type_combo.addItem(label, machine_type)
        machine_form.addRow("Tipo:", self.machine_type_combo)
        self.width_spin = self._size_spin()
        machine_form.addRow("Largura:", self.width_spin)
        self.length_spin = self._size_spin()
        machine_form.addRow("Comprimento:", self.length_spin)
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.5, 60.0)
        self.speed_spin.setDecimals(1)
        self.speed_spin.setValue(8.0)
        self.speed_spin.setSuffix(" km/h")
        machine_form.addRow("Velocidade:", self.speed_spin)
        self.multiplier_combo = QComboBox()
        for value in SPEED_MULTIPLIERS:
            self.multiplier_combo.addItem(f"{value:g}x", value)
        machine_form.addRow("Animacao:", self.multiplier_combo)
        self.coverage_check = QCheckBox("Pintar faixa de cobertura (largura da maquina)")
        self.coverage_check.setChecked(True)
        machine_form.addRow(self.coverage_check)
        self.opacity_combo = QComboBox()
        for value in COVERAGE_OPACITIES:
            self.opacity_combo.addItem(f"{value:.0%}", value)
        self.opacity_combo.setCurrentIndex(COVERAGE_OPACITIES.index(DEFAULT_COVERAGE_OPACITY))
        machine_form.addRow("Opacidade da cobertura:", self.opacity_combo)
        root.addWidget(machine_box)

        buttons = QHBoxLayout()
        self.start_button = QPushButton("▶ Iniciar")
        self.pause_button = QPushButton("⏸ Pausar")
        self.resume_button = QPushButton("▶ Continuar")
        self.stop_button = QPushButton("⏹ Parar")
        self.restart_button = QPushButton("↺ Reiniciar")
        for button in (self.start_button, self.pause_button, self.resume_button, self.stop_button, self.restart_button):
            buttons.addWidget(button)
        root.addLayout(buttons)

        progress_box = QGroupBox("Progresso")
        grid = QGridLayout(progress_box)
        self.value_labels: dict[str, QLabel] = {}
        rows = (
            ("pass", "Passada atual"),
            ("passes", "Completas / ativa / planejadas"),
            ("total", "Distancia total"),
            ("done", "Distancia percorrida"),
            ("left", "Distancia restante"),
            ("percent", "Percentual"),
            ("time", "Tempo de simulacao"),
            ("heading", "Rumo"),
            ("warnings", "Avisos da passada"),
            ("coverage", "Area coberta"),
            ("overlap", "Sobreposicao"),
        )
        for row, (key, label) in enumerate(rows):
            grid.addWidget(QLabel(f"{label}:"), row, 0)
            value = QLabel("-")
            grid.addWidget(value, row, 1)
            self.value_labels[key] = value
        root.addWidget(progress_box)

        self.validate_button = QPushButton("VALIDAR ROTA")
        self.validate_button.setToolTip("Roda todas as verificacoes da rota (somente leitura) antes de simular.")
        outer.addWidget(self.validate_button)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

        self.validate_button.clicked.connect(self.validate_route)
        self.start_button.clicked.connect(self.start)
        self.pause_button.clicked.connect(self.pause)
        self.resume_button.clicked.connect(self.resume)
        self.stop_button.clicked.connect(self.stop)
        self.restart_button.clicked.connect(self.restart)
        self.multiplier_combo.currentIndexChanged.connect(self._apply_multiplier)
        self.coverage_check.toggled.connect(self._toggle_coverage)
        self.opacity_combo.currentIndexChanged.connect(self._apply_opacity)
        self.layer_combo.layerChanged.connect(self._on_source_changed)
        self.selected_check.toggled.connect(self._invalidate)
        self.mode_combo.currentIndexChanged.connect(self._invalidate)
        for widget in (self.width_spin, self.length_spin, self.speed_spin):
            widget.valueChanged.connect(self._invalidate)
        self.machine_type_combo.currentIndexChanged.connect(self._invalidate)

    def _build_validation_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        box = QGroupBox("Parametros da validacao (nada e alterado na rota)")
        form = QFormLayout(box)
        self.area_combo = self._optional_layer_combo(QgsMapLayerProxyModel.PolygonLayer)
        form.addRow("Area permitida:", self.area_combo)
        self.overrun_check = QCheckBox("Avanco de cabeceira na ponta da passada e so informativo")
        self.overrun_check.setChecked(True)
        form.addRow(self.overrun_check)
        self.obstacle_combo = self._optional_layer_combo(QgsMapLayerProxyModel.PolygonLayer)
        form.addRow("Obstaculos:", self.obstacle_combo)
        self.buffer_spin = self._metric_spin(0.0, 100.0, 0.0)
        form.addRow("Buffer de seguranca:", self.buffer_spin)
        self.spacing_spin = self._metric_spin(0.0, 200.0, 0.0)
        self.spacing_spin.setSpecialValueText("nao validar")
        form.addRow("Espacamento esperado:", self.spacing_spin)
        self.tolerance_spin = self._metric_spin(0.01, 5.0, ValidationConfig.spacing_tolerance_m)
        form.addRow("Tolerancia de espacamento:", self.tolerance_spin)
        self.allow_warnings_check = QCheckBox("Simular mesmo com avisos abertos")
        self.allow_warnings_check.setChecked(ValidationConfig.allow_simulation_with_warnings)
        form.addRow(self.allow_warnings_check)
        layout.addWidget(box)
        self.warning_panel = RouteWarningPanel(self.iface, page)
        layout.addWidget(self.warning_panel, 1)
        return page

    @staticmethod
    def _optional_layer_combo(filters) -> QgsMapLayerComboBox:
        combo = QgsMapLayerComboBox()
        combo.setFilters(filters)
        combo.setAllowEmptyLayer(True)
        combo.setLayer(None)
        return combo

    @staticmethod
    def _metric_spin(minimum: float, maximum: float, value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(2)
        spin.setSingleStep(0.05)
        spin.setSuffix(" m")
        spin.setValue(value)
        return spin

    @staticmethod
    def _size_spin() -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 200.0)
        spin.setDecimals(2)
        spin.setSuffix(" m")
        spin.setSpecialValueText("nao informado")
        return spin

    def _select_default_layer(self) -> None:
        layer = find_layer_by_role(
            QgsProject.instance().mapLayers().values(), "FINAL_WORK_PATH", "WORK_PATH", non_empty=True
        )
        if layer is not None:
            self.layer_combo.setLayer(layer)
        layers = QgsProject.instance().mapLayers().values()
        for combo, role in ((self.area_combo, "EXTERNAL_BOUNDARY"), (self.obstacle_combo, "OBSTACLE")):
            found = find_layer_by_role(layers, role, non_empty=True)
            if found is not None:
                combo.setLayer(found)
        self._on_source_changed()

    def _on_source_changed(self, *_args) -> None:
        layer = self.layer_combo.currentLayer()
        width = _constant_attribute(layer, "width_m")
        if width is not None:
            self.width_spin.setValue(width)
        # Passadas do FortSmart: P_n = n x largura, entao o espacamento esperado e a largura.
        spacing = _constant_attribute(layer, "spacing_m") or width
        if spacing is not None:
            self.spacing_spin.setValue(spacing)
        self._invalidate()

    # ------------------------------------------------------------ rota ----
    def profile(self) -> MachineProfile:
        machine_type = self.machine_type_combo.currentData() or MachineType.TRACTOR
        return MachineProfile(
            id=machine_type.value.lower(),
            name=self.machine_name_edit.text().strip() or "Maquina",
            machine_type=machine_type,
            width_m=self.width_spin.value() or None,
            length_m=self.length_spin.value() or None,
        )

    def _invalidate(self, *_args) -> None:
        if self.engine is None:
            return
        self.timer.stop()
        self.engine = None
        if self.renderer is not None:
            self.renderer.clear()
        self.coverage = None
        if self.coverage_renderer is not None:
            self.coverage_renderer.clear()
        self._set_status("Parametros alterados: clique em Iniciar para recarregar a rota.")
        self._update_buttons()

    # -------------------------------------------------------- validacao ----
    def validation_config(self) -> ValidationConfig:
        return ValidationConfig(
            allow_headland_overrun=self.overrun_check.isChecked(),
            obstacle_safety_buffer_m=self.buffer_spin.value(),
            spacing_tolerance_m=self.tolerance_spin.value(),
            allow_simulation_with_warnings=self.allow_warnings_check.isChecked(),
        )

    def _read_source(self) -> RouteSource | None:
        layer = self.layer_combo.currentLayer()
        if layer is None:
            self._set_status("Selecione a camada de passadas.", error=True)
            return None
        try:
            return read_route_source(layer, selected_only=self.selected_check.isChecked())
        except (CrsValidationError, ValueError) as exc:
            self._set_status(f"SIMULATION_ROUTE_INVALID\n{exc}", error=True)
            return None

    def validate_route(self) -> ValidationResult | None:
        """Botao VALIDAR ROTA: roda todas as verificacoes; camadas e rota nao sao alteradas."""
        source = self._read_source()
        if source is None:
            return None
        result = self._validate(source)
        if result is not None:
            self.tabs.setCurrentIndex(1)
        return result

    def _validate(self, source: RouteSource) -> ValidationResult | None:
        config = self.validation_config()
        if self.validator.config != config:
            self.validator = RouteValidatorEngine(config)
        try:
            area = read_allowed_area(self.area_combo.currentLayer(), source.crs)
            obstacles = read_obstacles(self.obstacle_combo.currentLayer(), source.crs)
            result = self.validator.validate(
                source.passes, allowed_area=area, obstacles=obstacles,
                expected_spacing_m=self.spacing_spin.value() or None,
            )
        except (QgsCsException, GEOSException, ValueError) as exc:
            self._set_status(f"Falha na validacao da rota: {exc}", error=True)
            return None
        if result is not self.validation:
            self.validation = result
            self.warning_panel.set_result(
                result, source.crs, {p.id: p.segments for p in source.passes},
                source.feature_ids, self.layer_combo.currentLayer(),
            )
        self._last_pass_id = None
        blocked = result.blocked_pass_ids()
        text = result.summary()
        if blocked:
            text += "\nSimulacao bloqueada: passada(s) sem geometria valida: " + ", ".join(blocked[:12])
        self._set_status(text, error=bool(blocked or result.critical_count))
        return result

    def load_route(self) -> bool:
        source = self._read_source()
        if source is None:
            return False
        result = self._validate(source)
        if result is None:
            return False
        config = self.validator.config
        if result.blocks_simulation(config.allow_simulation_with_warnings):
            blocked = result.blocked_pass_ids()
            reason = (
                "passada(s) sem geometria valida: " + ", ".join(blocked[:12])
                if blocked else "avisos abertos e simulacao com avisos desligada"
            )
            self._set_status(f"SIMULATION_ROUTE_INVALID: simulacao bloqueada ({reason}).\n{result.summary()}", error=True)
            self.tabs.setCurrentIndex(1)
            return False
        mode = self.mode_combo.currentData()
        try:
            custom = [p.id for p in source.passes] if mode is RouteMode.CUSTOM_SEQUENCE else None
            route = build_ordered_route(source.passes, mode, custom_order=custom, crs_authid=source.crs.authid())
            engine = RouteSimulationEngine(
                route, self.profile(), self.speed_spin.value() / 3.6,
                speed_multiplier=self.multiplier_combo.currentData(),
            )
        except RouteValidationError as exc:
            self._set_status(f"{exc.code}\n" + "\n".join(exc.problems[:12]), error=True)
            return False
        except (CrsValidationError, ValueError) as exc:
            self._set_status(f"SIMULATION_ROUTE_INVALID\n{exc}", error=True)
            return False
        if self.renderer is not None:
            self.renderer.remove()
        self.renderer = RouteSimulationRenderer(self.iface.mapCanvas(), source.crs)
        self.engine = engine
        coverage_note = self._setup_coverage(engine, source.crs)
        self.sequence_source = source.sequence_source
        origin = {
            "attribute": "numeracao da camada",
            "spatial_order": "ordem espacial (camada sem numeracao)",
            "attribute+spatial_order": "numeracao da camada + ordem espacial",
        }.get(source.sequence_source, source.sequence_source)
        self._set_status(
            f"{route.route_count} passada(s) de {source.feature_count} feicao(oes) | "
            f"sequencia: {origin} | CRS {source.crs.authid()}\nValidacao: {result.summary()}\n{coverage_note}"
        )
        self._last_pass_id = None
        return True

    # -------------------------------------------------------- cobertura ----
    def _setup_coverage(self, engine: RouteSimulationEngine, crs) -> str:
        """Nova rota: cobertura do zero (nunca mistura simulacoes). Sem largura, nao pinta."""
        if self.coverage_renderer is not None:
            if self.coverage_renderer.crs == crs:
                self.coverage_renderer.clear()
            else:
                self.coverage_renderer.remove()
                self.coverage_renderer = None
        width = engine.machine_profile.width_m
        if not width:
            self.coverage = None
            return "Cobertura: informe a largura da maquina para pintar a faixa."
        self.coverage = CoverageEngine(CoverageSettings(working_width_m=width))
        if self.coverage_renderer is None:
            self.coverage_renderer = CoverageRenderer(QgsProject.instance(), crs, self.opacity_combo.currentData())
        return f"Cobertura: faixa de {width:.2f} m ({width / 2.0:.3f} m para cada lado da passada)."

    def _toggle_coverage(self, enabled: bool) -> None:
        if self.coverage_renderer is None:
            return
        if enabled and self.coverage is not None:
            self.coverage_renderer.render(self.coverage.state)
        elif not enabled:
            self.coverage_renderer.remove()

    def _apply_opacity(self, *_args) -> None:
        if self.coverage_renderer is not None:
            self.coverage_renderer.set_opacity(self.opacity_combo.currentData())

    def _refresh_coverage(self) -> None:
        labels = self.value_labels
        if self.coverage is None:
            labels["coverage"].setText("-")
            labels["overlap"].setText("-")
            return
        if self.coverage.update(self.engine) and self.coverage_renderer is not None and self.coverage_check.isChecked():
            self.coverage_renderer.render(self.coverage.state)
        state = self.coverage.state
        labels["coverage"].setText(
            f"{state.unique_area_m2 / 10000.0:.2f} ha (bruta {state.gross_area_m2 / 10000.0:.2f} ha)"
        )
        labels["overlap"].setText(f"{state.overlap_area_m2 / 10000.0:.2f} ha")

    # --------------------------------------------------------- controles ----
    def start(self) -> None:
        if self.engine is None and not self.load_route():
            return
        self._run(self.engine.start)

    def pause(self) -> None:
        if self.engine is not None:
            self.timer.stop()
            self._run(self.engine.pause)

    def resume(self) -> None:
        if self.engine is not None:
            self._run(self.engine.resume)

    def stop(self) -> None:
        if self.engine is not None:
            self.timer.stop()
            self._run(self.engine.stop)

    def restart(self) -> None:
        if self.engine is None and not self.load_route():
            return
        self._run(self.engine.restart)

    def _apply_multiplier(self, *_args) -> None:
        if self.engine is not None:
            self.engine.set_speed_multiplier(self.multiplier_combo.currentData())

    def _run(self, action) -> None:
        try:
            state = action()
        except SimulationError as exc:
            self.timer.stop()
            self._set_status(str(exc), error=True)
            return
        if state.is_running and not state.is_paused:
            self.clock.restart()
            self.timer.start()
        self._refresh()

    def advance(self, delta_time_s: float) -> None:
        if self.engine is None:
            return
        try:
            state = self.engine.advance(delta_time_s)
        except SimulationError as exc:
            self.timer.stop()
            self._set_status(str(exc), error=True)
            return
        if not state.is_running:
            self.timer.stop()
        self._refresh()

    def _tick(self) -> None:
        self.advance(self.clock.restart() / 1000.0)

    # ---------------------------------------------------------- display ----
    def _refresh(self) -> None:
        if self.engine is None:
            return
        state = self.engine.state
        if self.renderer is not None:
            self.renderer.render(self.engine)
        self._refresh_coverage()
        labels = self.value_labels
        labels["pass"].setText(
            f"{state.current_pass_id} ({state.current_pass_index + 1}/{state.route_count}) "
            f"{state.current_distance_m:.1f} / {state.current_pass_length_m:.1f} m"
        )
        labels["passes"].setText(
            f"{state.completed_pass_count} / {state.active_pass_count} / {state.planned_pass_count}"
        )
        labels["total"].setText(f"{state.total_route_distance_m:.1f} m")
        labels["done"].setText(f"{state.completed_distance_m:.1f} m")
        labels["left"].setText(f"{state.remaining_distance_m:.1f} m")
        labels["percent"].setText(f"{state.progress_percent:.1f} %")
        labels["time"].setText(format_duration(state.elapsed_time_s))
        labels["heading"].setText(f"{state.current_heading_deg:.1f}°")
        if state.current_pass_id != self._last_pass_id:
            # So consulta o resultado ja calculado; nenhuma validacao por frame.
            self._last_pass_id = state.current_pass_id
            labels["warnings"].setText(format_pass_warnings(self.warning_panel.show_pass_warnings(state.current_pass_id)))
        if state.is_finished:
            self._set_status("Simulacao concluida: todas as passadas percorridas.")
        self._update_buttons()

    def _update_buttons(self) -> None:
        state = self.engine.state if self.engine is not None else None
        running = bool(state and state.is_running)
        paused = bool(state and state.is_paused)
        self.start_button.setEnabled(not running)
        self.pause_button.setEnabled(running and not paused)
        self.resume_button.setEnabled(running and paused)
        self.stop_button.setEnabled(running)
        self.restart_button.setEnabled(state is not None)
        self.speed_spin.setEnabled(not running)

    def _set_status(self, text: str, *, error: bool = False) -> None:
        self.status_label.setText(text)
        self.status_label.setStyleSheet("color: #b00020;" if error else "")

    def closeEvent(self, event) -> None:
        self.timer.stop()
        if self.renderer is not None:
            self.renderer.remove()
            self.renderer = None
        if self.coverage_renderer is not None:
            self.coverage_renderer.remove()
            self.coverage_renderer = None
        self.coverage = None
        self.warning_panel.cleanup()
        super().closeEvent(event)
