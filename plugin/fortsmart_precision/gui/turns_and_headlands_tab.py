# -*- coding: utf-8 -*-
"""Aba Voltas e Manobras (Etapa 4: omega, tres pontos, blocos, rebocado)."""

from __future__ import annotations

from qgis.PyQt.QtCore import QVariant, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsMapLayerProxyModel,
    QgsVectorLayer,
)
from qgis.gui import QgsMapLayerComboBox

from ..core.turn_path_engine import TurnPath, filter_savable_turns
from ..domain.turn_configuration import (
    DEFAULT_EXTERNAL_EXTENSION_M,
    AllowedTurnSide,
    PassSequenceMode,
    SafetyMargins,
    TurnFinishMode,
    TurnStatus,
    TurnType,
    TurnConfiguration,
)
from .agricultural_lines_dialog import to_qgs_point


class TurnsAndHeadlandsTab(QWidget):
    """Controles de volta automatica para a Configuracao da Operacao."""

    request_space_calc = pyqtSignal()
    request_preview = pyqtSignal()
    request_validate = pyqtSignal()
    request_remove_invalid = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._wire()
        self.refresh_enabled_state()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.generate_check = QCheckBox("Gerar voltas")
        self.allow_headland_check = QCheckBox("Permitir volta dentro da bordadura")
        self.allow_headland_check.setChecked(True)
        self.allow_outside_check = QCheckBox("Permitir manobra fora do limite")
        self.use_maneuver_check = QCheckBox("Usar area de manobra")
        self.avoid_planted_check = QCheckBox("Evitar area ja plantada")
        self.avoid_planted_check.setChecked(True)
        self.avoid_obstacles_check = QCheckBox("Evitar obstaculos")
        self.avoid_obstacles_check.setChecked(True)

        self.finish_mode_combo = QComboBox()
        self.finish_mode_combo.addItem("Sem volta automatica", TurnFinishMode.NONE.value)
        self.finish_mode_combo.addItem("Volta dentro da bordadura", TurnFinishMode.INSIDE_HEADLAND.value)
        self.finish_mode_combo.addItem("Volta fora do limite", TurnFinishMode.OUTSIDE_BOUNDARY.value)
        self.finish_mode_combo.addItem("Volta em area de manobra", TurnFinishMode.MANEUVER_AREA.value)

        self.turn_type_combo = QComboBox()
        self.turn_type_combo.addItem("U", TurnType.U.value)
        self.turn_type_combo.addItem("Gota", TurnType.DROP.value)
        self.turn_type_combo.addItem("Pula-faixa", TurnType.SKIP_PASS.value)
        self.turn_type_combo.addItem("Omega", TurnType.OMEGA.value)
        self.turn_type_combo.addItem("Tres pontos", TurnType.THREE_POINT.value)

        self.sequence_combo = QComboBox()
        self.sequence_combo.addItem("Sequencial", PassSequenceMode.SEQUENTIAL.value)
        self.sequence_combo.addItem("Alternada", PassSequenceMode.ALTERNATING.value)
        self.sequence_combo.addItem("Pula uma faixa", PassSequenceMode.SKIP_ONE.value)
        self.sequence_combo.addItem("Pula duas faixas", PassSequenceMode.SKIP_TWO.value)
        self.sequence_combo.addItem("Por blocos", PassSequenceMode.BLOCKS.value)

        self.skip_spin = QSpinBox()
        self.skip_spin.setRange(0, 10)
        self.skip_spin.setValue(0)

        self.block_size_spin = QSpinBox()
        self.block_size_spin.setRange(1, 50)
        self.block_size_spin.setValue(4)

        self.implement_mounted_combo = QComboBox()
        self.implement_mounted_combo.addItem("Nao informado", "unknown")
        self.implement_mounted_combo.addItem("Montado", "mounted")
        self.implement_mounted_combo.addItem("Rebocado", "towed")

        self.radius_spin = QDoubleSpinBox()
        self.radius_spin.setRange(0.0, 500.0)
        self.radius_spin.setDecimals(2)
        self.radius_spin.setSuffix(" m")
        self.radius_spin.setSpecialValueText("Nao informado")
        self.radius_spin.setValue(0.0)

        self.ensemble_length_spin = QDoubleSpinBox()
        self.ensemble_length_spin.setRange(0.0, 200.0)
        self.ensemble_length_spin.setDecimals(2)
        self.ensemble_length_spin.setSuffix(" m")
        self.ensemble_length_spin.setSpecialValueText("Nao informado")
        self.ensemble_length_spin.setValue(0.0)

        self.margin_spin = QDoubleSpinBox()
        self.margin_spin.setRange(0.0, 50.0)
        self.margin_spin.setDecimals(2)
        self.margin_spin.setValue(2.0)
        self.margin_spin.setSuffix(" m")

        self.extension_before_spin = QDoubleSpinBox()
        self.extension_before_spin.setRange(0.0, 1000.0)
        self.extension_before_spin.setDecimals(2)
        self.extension_before_spin.setValue(DEFAULT_EXTERNAL_EXTENSION_M)
        self.extension_before_spin.setSuffix(" m")

        self.extension_after_spin = QDoubleSpinBox()
        self.extension_after_spin.setRange(0.0, 1000.0)
        self.extension_after_spin.setDecimals(2)
        self.extension_after_spin.setValue(DEFAULT_EXTERNAL_EXTENSION_M)
        self.extension_after_spin.setSuffix(" m")

        self.max_outside_spin = QDoubleSpinBox()
        self.max_outside_spin.setRange(0.0, 1000.0)
        self.max_outside_spin.setDecimals(2)
        self.max_outside_spin.setSpecialValueText("Sem limite")
        self.max_outside_spin.setValue(0.0)
        self.max_outside_spin.setSuffix(" m")

        self.allowed_side_combo = QComboBox()
        self.allowed_side_combo.addItem("Ambos os lados", AllowedTurnSide.BOTH.value)
        self.allowed_side_combo.addItem("Esquerda", AllowedTurnSide.LEFT.value)
        self.allowed_side_combo.addItem("Direita", AllowedTurnSide.RIGHT.value)

        self.surface_edit = QLineEdit()
        self.surface_edit.setPlaceholderText("Ex.: estrada, patio, faicao externa")

        self.external_layer_combo = QgsMapLayerComboBox()
        self.external_layer_combo.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        self.external_layer_combo.setAllowEmptyLayer(True)

        self.available_width_label = QLabel("-")
        self.required_width_label = QLabel("-")
        self.clearance_label = QLabel("-")
        self.extension_label = QLabel("-")
        self.status_label = QLabel("-")

        form.addRow("", self.generate_check)
        form.addRow("", self.allow_headland_check)
        form.addRow("", self.allow_outside_check)
        form.addRow("", self.use_maneuver_check)
        form.addRow("", self.avoid_planted_check)
        form.addRow("", self.avoid_obstacles_check)
        form.addRow("Modo de volta:", self.finish_mode_combo)
        form.addRow("Tipo de volta:", self.turn_type_combo)
        form.addRow("Sequencia:", self.sequence_combo)
        form.addRow("Pular quantas faixas:", self.skip_spin)
        form.addRow("Tamanho do bloco:", self.block_size_spin)
        form.addRow("Implemento:", self.implement_mounted_combo)
        form.addRow("Raio minimo:", self.radius_spin)
        form.addRow("Comprimento do conjunto:", self.ensemble_length_spin)
        form.addRow("Margem recomendada:", self.margin_spin)
        form.addRow("Extensao antes do limite:", self.extension_before_spin)
        form.addRow("Extensao depois do limite:", self.extension_after_spin)
        form.addRow("Distancia maxima fora:", self.max_outside_spin)
        form.addRow("Lado permitido:", self.allowed_side_combo)
        form.addRow("Tipo de superficie:", self.surface_edit)
        form.addRow("Area externa autorizada:", self.external_layer_combo)
        form.addRow("Largura disponivel:", self.available_width_label)
        form.addRow("Largura necessaria:", self.required_width_label)
        form.addRow("Margem calculada:", self.clearance_label)
        form.addRow("Extensao:", self.extension_label)
        form.addRow("Status:", self.status_label)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        self.btn_calc = QPushButton("Calcular espaco necessario")
        self.btn_preview = QPushButton("Pre-visualizar voltas")
        self.btn_validate = QPushButton("Validar todas")
        self.btn_remove_invalid = QPushButton("Remover voltas invalidas")
        for button in (self.btn_calc, self.btn_preview, self.btn_validate, self.btn_remove_invalid):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        layout.addStretch()

    def _wire(self):
        self.generate_check.toggled.connect(self.refresh_enabled_state)
        self.finish_mode_combo.currentIndexChanged.connect(self.refresh_enabled_state)
        self.turn_type_combo.currentIndexChanged.connect(self.refresh_enabled_state)
        self.sequence_combo.currentIndexChanged.connect(self.refresh_enabled_state)
        self.allow_outside_check.toggled.connect(self.refresh_enabled_state)
        self.use_maneuver_check.toggled.connect(self.refresh_enabled_state)
        self.btn_calc.clicked.connect(self.request_space_calc.emit)
        self.btn_preview.clicked.connect(self.request_preview.emit)
        self.btn_validate.clicked.connect(self.request_validate.emit)
        self.btn_remove_invalid.clicked.connect(self.request_remove_invalid.emit)

    def refresh_enabled_state(self):
        generating = self.generate_check.isChecked()
        mode = self.finish_mode_combo.currentData()
        need_turns = generating and mode != TurnFinishMode.NONE.value
        outside = mode in {
            TurnFinishMode.OUTSIDE_BOUNDARY.value,
            TurnFinishMode.MANEUVER_AREA.value,
        }
        for widget in (
            self.turn_type_combo,
            self.sequence_combo,
            self.skip_spin,
            self.block_size_spin,
            self.implement_mounted_combo,
            self.radius_spin,
            self.ensemble_length_spin,
            self.btn_calc,
            self.btn_preview,
            self.btn_validate,
            self.btn_remove_invalid,
        ):
            widget.setEnabled(need_turns)
        for widget in (
            self.extension_before_spin,
            self.extension_after_spin,
            self.max_outside_spin,
            self.allowed_side_combo,
            self.surface_edit,
            self.external_layer_combo,
        ):
            widget.setEnabled(need_turns and outside)
        self.allow_outside_check.setEnabled(generating)
        self.use_maneuver_check.setEnabled(generating)
        if generating and mode == TurnFinishMode.NONE.value:
            self.finish_mode_combo.setCurrentIndex(1)
        if mode == TurnFinishMode.OUTSIDE_BOUNDARY.value and not self.allow_outside_check.isChecked():
            self.allow_outside_check.setChecked(True)
        if mode == TurnFinishMode.MANEUVER_AREA.value and not self.use_maneuver_check.isChecked():
            self.use_maneuver_check.setChecked(True)
        turn_type = self.turn_type_combo.currentData()
        sequence = self.sequence_combo.currentData()
        skip_useful = turn_type == TurnType.SKIP_PASS.value or sequence in {
            PassSequenceMode.SKIP_ONE.value,
            PassSequenceMode.SKIP_TWO.value,
        }
        self.skip_spin.setEnabled(need_turns and skip_useful)
        self.block_size_spin.setEnabled(need_turns and sequence == PassSequenceMode.BLOCKS.value)

    def external_layer(self):
        layer = self.external_layer_combo.currentLayer()
        return layer if isinstance(layer, QgsVectorLayer) else None

    def build_configuration(self) -> TurnConfiguration:
        radius = self.radius_spin.value()
        ensemble = self.ensemble_length_spin.value()
        finish = TurnFinishMode(self.finish_mode_combo.currentData())
        if not self.generate_check.isChecked():
            finish = TurnFinishMode.NONE
        max_outside = self.max_outside_spin.value()
        external_layer = self.external_layer()
        mounted_raw = self.implement_mounted_combo.currentData()
        if mounted_raw == "mounted":
            mounted = True
        elif mounted_raw == "towed":
            mounted = False
        else:
            mounted = None
        return TurnConfiguration(
            finish_mode=finish,
            turn_type=TurnType(self.turn_type_combo.currentData()),
            sequence_mode=PassSequenceMode(self.sequence_combo.currentData()),
            generate_turns=self.generate_check.isChecked() and finish != TurnFinishMode.NONE,
            min_turn_radius_m=None if radius <= 0 else radius,
            tractor_length_m=None if ensemble <= 0 else ensemble,
            implement_length_m=None,
            wheelbase_m=None,
            implement_mounted=mounted,
            skip_passes=self.skip_spin.value(),
            block_size=self.block_size_spin.value(),
            external_extension_m=max(self.extension_before_spin.value(), self.extension_after_spin.value()),
            extension_before_m=self.extension_before_spin.value(),
            extension_after_m=self.extension_after_spin.value(),
            max_outside_distance_m=None if max_outside <= 0 else max_outside,
            allowed_side=AllowedTurnSide(self.allowed_side_combo.currentData()),
            surface_type=self.surface_edit.text().strip(),
            external_area_id=external_layer.id() if external_layer else "",
            allow_outside_boundary=self.allow_outside_check.isChecked(),
            allow_inside_headland=self.allow_headland_check.isChecked(),
            use_maneuver_area=self.use_maneuver_check.isChecked(),
            avoid_planted_area=self.avoid_planted_check.isChecked(),
            avoid_obstacles=self.avoid_obstacles_check.isChecked(),
            safety=SafetyMargins(recommended_clearance_m=self.margin_spin.value()),
        )

    def update_space_labels(
        self,
        available_m: float,
        required_m: float | None,
        clearance_m: float | None,
        status: str,
        extension_text: str | None = None,
    ):
        self.available_width_label.setText(f"{available_m:.2f} m")
        self.required_width_label.setText("-" if required_m is None else f"{required_m:.2f} m")
        self.clearance_label.setText("-" if clearance_m is None else f"{clearance_m:.2f} m")
        self.extension_label.setText(extension_text or "-")
        self.status_label.setText(status)

    def show_report_message(self, title: str, text: str, *, critical: bool = False):
        if critical:
            QMessageBox.critical(self, title, text)
        else:
            QMessageBox.information(self, title, text)


def turn_status_color(status: str) -> QColor:
    mapping = {
        TurnStatus.VALID.value: QColor(0, 160, 70),
        TurnStatus.VALID_LOW_MARGIN.value: QColor(220, 180, 0),
        TurnStatus.IMPOSSIBLE.value: QColor(200, 40, 40),
        TurnStatus.INSUFFICIENT_DATA.value: QColor(120, 120, 120),
    }
    return mapping.get(status, QColor(80, 80, 80))


def turn_paths_memory_layer(name: str, crs_authid: str, turns: list[TurnPath]) -> QgsVectorLayer:
    layer = QgsVectorLayer(f"LineString?crs={crs_authid}", name, "memory")
    provider = layer.dataProvider()
    provider.addAttributes([
        QgsField("fs_id", QVariant.String),
        QgsField("from_pass", QVariant.Int),
        QgsField("to_pass", QVariant.Int),
        QgsField("turn_type", QVariant.String),
        QgsField("turn_location", QVariant.String),
        QgsField("sequence_no", QVariant.Int),
        QgsField("radius_m", QVariant.Double),
        QgsField("required_width_m", QVariant.Double),
        QgsField("available_width_m", QVariant.Double),
        QgsField("clearance_m", QVariant.Double),
        QgsField("status", QVariant.String),
        QgsField("is_estimated", QVariant.Bool),
        QgsField("outside_boundary", QVariant.Bool),
        QgsField("external_area_id", QVariant.String),
        QgsField("length_m", QVariant.Double),
        QgsField("label", QVariant.String),
        QgsField("configured_extension_m", QVariant.Double),
        QgsField("minimum_extension_m", QVariant.Double),
        QgsField("is_special_maneuver", QVariant.Bool),
    ])
    layer.updateFields()
    features = []
    for turn in turns:
        attrs = turn.attributes()
        feature = QgsFeature(layer.fields())
        feature.setAttributes([
            attrs["fs_id"],
            attrs["from_pass"],
            attrs["to_pass"],
            attrs["turn_type"],
            attrs["turn_location"],
            attrs["sequence_no"],
            attrs["radius_m"],
            attrs["required_width_m"],
            attrs["available_width_m"],
            attrs["clearance_m"],
            attrs["status"],
            attrs["is_estimated"],
            attrs["outside_boundary"],
            attrs["external_area_id"],
            attrs["length_m"],
            attrs["label"],
            attrs["configured_extension_m"],
            attrs["minimum_extension_m"],
            attrs["is_special_maneuver"],
        ])
        feature.setGeometry(
            QgsGeometry.fromPolylineXY([to_qgs_point(point) for point in turn.points])
        )
        features.append(feature)
    provider.addFeatures(features)
    layer.updateExtents()
    if turns:
        layer.renderer().symbol().setColor(turn_status_color(turns[0].status))
    return layer


def split_valid_invalid(turns: list[TurnPath]) -> tuple[list[TurnPath], list[TurnPath]]:
    valid = filter_savable_turns(turns)
    invalid = [turn for turn in turns if turn not in valid]
    return valid, invalid
