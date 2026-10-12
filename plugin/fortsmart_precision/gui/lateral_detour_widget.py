# -*- coding: utf-8 -*-
"""Grupo 'TRATAMENTO DO OBSTÁCULO': cortar e retomar (padrao) ou desviar lateralmente."""

from __future__ import annotations

from qgis.PyQt.QtCore import QSettings, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.lateral_detour.engine import contour_radius_for, required_turn_radius
from ..domain.obstacle_strategy import (
    ENABLE_LATERAL_DETOUR,
    ContourStrategy,
    DetourSide,
    ObstacleConfig,
    ObstacleConfigError,
    ObstacleHandlingStrategy,
)

SETTINGS_PREFIX = "fortsmart_precision/lateral_detour/"


class ObstacleTreatmentBox(QGroupBox):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Tratamento do obstaculo", parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 9, 8, 7)
        layout.setSpacing(5)
        self.setStyleSheet(
            "QGroupBox { border: 1px solid #b9c4cf; border-radius: 5px; "
            "margin-top: 7px; background: #fafbfc; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 9px; padding: 0 4px; "
            "font-weight: 600; color: #263746; }"
        )

        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(2, 0, 2, 0)
        mode_row.setSpacing(18)
        self.cut_radio = QRadioButton("Cortar linha e retomar")
        self.detour_radio = QRadioButton("Desviar lateralmente")
        # Sempre abre no comportamento existente, independente do ultimo uso.
        self.cut_radio.setChecked(True)
        self._buttons = QButtonGroup(self)
        self._buttons.addButton(self.cut_radio)
        self._buttons.addButton(self.detour_radio)
        self.cut_radio.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.detour_radio.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        mode_row.addWidget(self.cut_radio)
        mode_row.addWidget(self.detour_radio)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        self.params = QWidget(self)
        form = QGridLayout(self.params)
        form.setContentsMargins(12, 2, 2, 2)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(4)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)

        self.row_count = QSpinBox()
        self.row_count.setRange(0, 200)
        self.row_count.setSpecialValueText("Informe")
        form.addWidget(QLabel("Linhas da plantadeira:"), 0, 0)
        form.addWidget(self.row_count, 0, 1)

        self.row_spacing = QDoubleSpinBox()
        self.row_spacing.setRange(0.0, 3.0)
        self.row_spacing.setDecimals(3)
        self.row_spacing.setSingleStep(0.05)
        self.row_spacing.setSpecialValueText("Informe")
        self.row_spacing.setSuffix(" m")
        form.addWidget(QLabel("Espacamento:"), 0, 2)
        form.addWidget(self.row_spacing, 0, 3)

        self.machine_width = QLabel("-")
        form.addWidget(QLabel("Largura calculada:"), 1, 0)
        form.addWidget(self.machine_width, 1, 1)

        self.safety_margin = self._distance(0.0, 50.0, 0.50)
        form.addWidget(QLabel("Margem de seguranca:"), 1, 2)
        form.addWidget(self.safety_margin, 1, 3)
        self.approach_distance = self._distance(0.0, 500.0, 12.0)
        form.addWidget(QLabel("Antes do desvio:"), 2, 0)
        form.addWidget(self.approach_distance, 2, 1)
        self.return_distance = self._distance(0.0, 500.0, 12.0)
        form.addWidget(QLabel("Apos o desvio:"), 2, 2)
        form.addWidget(self.return_distance, 2, 3)
        self.minimum_turn_radius = self._distance(0.5, 200.0, 8.0)
        form.addWidget(QLabel("Raio minimo:"), 3, 0)
        form.addWidget(self.minimum_turn_radius, 3, 1)

        self.side_combo = QComboBox()
        self.side_combo.addItem("Automático", DetourSide.AUTO.value)
        self.side_combo.addItem("Esquerda", DetourSide.LEFT.value)
        self.side_combo.addItem("Direita", DetourSide.RIGHT.value)
        form.addWidget(QLabel("Lado do desvio:"), 3, 2)
        form.addWidget(self.side_combo, 3, 3)

        self.contour_combo = QComboBox()
        self.contour_combo.addItem("Suave (envoltoria convexa)", ContourStrategy.CONVEX_SMOOTH.value)
        self.contour_combo.addItem("Justo (respeita raio minimo)", ContourStrategy.CONVEX_TIGHT.value)
        self.contour_combo.setToolTip(
            "Contorno suave pela envoltoria convexa ou contorno justo somente quando respeita o raio minimo."
        )
        self.contour_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.contour_combo.setMinimumContentsLength(18)
        self.contour_combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        form.addWidget(QLabel("Estrategia de contorno:"), 4, 0)
        form.addWidget(self.contour_combo, 4, 1, 1, 3)

        self.planting_check = QCheckBox("Plantar no desvio (WORK_ON)")
        self.planting_check.setToolTip("Manter a operacao ativa durante toda a trajetoria do desvio.")
        self.planting_check.setChecked(True)
        form.addWidget(self.planting_check, 5, 0, 1, 4)
        self.rows_check = QCheckBox("Gerar linhas da plantadeira")
        self.rows_check.setToolTip("Gerar as linhas fisicas da plantadeira ao longo das passadas desviadas.")
        self.rows_check.setChecked(True)
        form.addWidget(self.rows_check, 6, 0, 1, 4)
        self.fallback_check = QCheckBox("Se inviavel, cortar e retomar")
        self.fallback_check.setToolTip(
            "Quando nao houver desvio geometricamente viavel, aplicar o corte e retomar a mesma linha."
        )
        self.fallback_check.setChecked(True)
        form.addWidget(self.fallback_check, 7, 0, 1, 4)
        for check in (self.planting_check, self.rows_check, self.fallback_check):
            check.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

        self.radius_info = QLabel("")
        self.radius_info.setWordWrap(True)
        self.radius_info.setStyleSheet(
            "QLabel { background: #eef4fb; border-radius: 3px; padding: 4px 6px; color: #29435c; }"
        )
        form.addWidget(self.radius_info, 8, 0, 1, 4)
        for label in self.params.findChildren(QLabel):
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.side_combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        layout.addWidget(self.params)

        self._load_settings()
        self.params.setVisible(False)
        self.setVisible(ENABLE_LATERAL_DETOUR)

        self.detour_radio.toggled.connect(self._on_mode_toggled)
        for spin in (
            self.row_count,
            self.row_spacing,
            self.safety_margin,
            self.approach_distance,
            self.return_distance,
            self.minimum_turn_radius,
        ):
            spin.valueChanged.connect(self._on_value_changed)
        for combo in (self.side_combo, self.contour_combo):
            combo.currentIndexChanged.connect(self._on_value_changed)
        for check in (self.planting_check, self.rows_check, self.fallback_check):
            check.toggled.connect(self._on_value_changed)
        self._refresh_info()

    @staticmethod
    def _distance(minimum, maximum, value):
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(2)
        spin.setValue(value)
        spin.setSuffix(" m")
        return spin

    def is_lateral(self) -> bool:
        return ENABLE_LATERAL_DETOUR and self.detour_radio.isChecked()

    def strategy(self) -> ObstacleHandlingStrategy:
        return ObstacleHandlingStrategy.LATERAL_DETOUR if self.is_lateral() else ObstacleHandlingStrategy.STOP_CUT_RESUME

    def config(self, obstacle_radius: float = 0.0) -> ObstacleConfig:
        return ObstacleConfig(
            strategy=self.strategy(),
            row_count=self.row_count.value(),
            row_spacing=self.row_spacing.value(),
            safety_margin=self.safety_margin.value(),
            obstacle_radius=obstacle_radius,
            approach_distance=self.approach_distance.value(),
            return_distance=self.return_distance.value(),
            minimum_turn_radius=self.minimum_turn_radius.value(),
            detour_side=DetourSide(self.side_combo.currentData()),
            contour_strategy=ContourStrategy(self.contour_combo.currentData()),
            planting_during_detour=self.planting_check.isChecked(),
            allow_fallback=self.fallback_check.isChecked(),
            generate_rows=self.rows_check.isChecked(),
        )

    def config_error(self, obstacle_radius: float = 0.0) -> str | None:
        if not self.is_lateral():
            return None
        try:
            self.config(obstacle_radius).validate()
        except ObstacleConfigError as exc:
            return str(exc)
        return None

    def summary(self, obstacle_radius: float = 0.0) -> str:
        config = self.config(obstacle_radius)
        if config.row_count < 1 or config.row_spacing <= 0:
            return "Informe linhas e espaçamento da plantadeira."
        return (
            f"Largura {config.machine_width:.2f} m | meia largura {config.half_machine:.2f} + "
            f"poste {obstacle_radius:.2f} + margem {config.safety_margin:.2f} m = envelope "
            f"{config.half_machine + obstacle_radius + config.safety_margin:.2f} m"
        )

    def _on_mode_toggled(self, checked):
        self.params.setVisible(bool(checked))
        self.changed.emit()

    def _on_value_changed(self, *_args):
        self._refresh_info()
        self._save_settings()
        self.changed.emit()

    def _refresh_info(self):
        config = self.config()
        if config.row_count < 1 or config.row_spacing <= 0:
            self.machine_width.setText("-")
            self.radius_info.setText("")
            return
        self.machine_width.setText(f"{config.row_count} × {config.row_spacing:.3f} = {config.machine_width:.2f} m")
        required = required_turn_radius(config)
        note = (
            f"Raio efetivo {required:.2f} m (mínimo informado {config.minimum_turn_radius:.2f} m; "
            f"meia largura + 0,25 m evita laço na linha mais interna). "
            f"Contorno a {contour_radius_for(config, required):.2f} m do obstáculo."
        )
        self.radius_info.setText(note)

    def _load_settings(self):
        settings = QSettings()
        try:
            self.row_count.setValue(int(settings.value(SETTINGS_PREFIX + "row_count", 0)))
            for key, spin in (
                ("row_spacing", self.row_spacing),
                ("safety_margin", self.safety_margin),
                ("approach_distance", self.approach_distance),
                ("return_distance", self.return_distance),
                ("minimum_turn_radius", self.minimum_turn_radius),
            ):
                stored = settings.value(SETTINGS_PREFIX + key, None)
                if stored not in (None, ""):
                    spin.setValue(float(stored))
        except (TypeError, ValueError):
            pass

    def _save_settings(self):
        settings = QSettings()
        settings.setValue(SETTINGS_PREFIX + "row_count", self.row_count.value())
        for key, spin in (
            ("row_spacing", self.row_spacing),
            ("safety_margin", self.safety_margin),
            ("approach_distance", self.approach_distance),
            ("return_distance", self.return_distance),
            ("minimum_turn_radius", self.minimum_turn_radius),
        ):
            settings.setValue(SETTINGS_PREFIX + key, spin.value())
