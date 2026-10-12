# -*- coding: utf-8 -*-
"""Grupo de GUI: geometria do conjunto, bordadura do obstaculo e estrategia."""

from __future__ import annotations

from qgis.PyQt.QtCore import QPointF, QRectF, Qt, pyqtSignal
from qgis.PyQt.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QSizePolicy,
    QWidget,
)
from qgis.core import QgsSettings

from ..core.planting_line_cut_engine import cut_preview_readiness, machine_schematic_layout
from ..domain.operation_simulation import (
    MachineReferenceType,
    MachineWorkGeometry,
    ObstacleBorderMode,
)

SETTINGS_PREFIX = "fortsmart_precision/work_geometry/"
OFFSET_LABEL = "Offset da última linha ativa:"
OFFSET_PLACEHOLDER = "Ex.: -18,00 m"
OFFSET_HELP = (
    "Distância longitudinal entre o ponto de referência e a última linha/elemento "
    "que efetivamente realiza a operação. Negativo = atrás da referência. "
    "Positivo = à frente."
)
BORDER_HELP = (
    "Bordadura do obstáculo = faixa lateral de proteção (passada de contorno). "
    "Não define a distância de corte: a linha desliga quando a barra encosta na "
    "zona (raio do poste + margem), menos a antecipação."
)
ANTICIPATION_HELP = (
    "Quanto antes de entrar na zona do obstáculo, no sentido da passada, a operação desliga. "
    "Independente da largura, do espaçamento e da bordadura."
)
STRATEGY_RADIAL = "RADIAL"
REFERENCE_LABELS = (
    (MachineReferenceType.GNSS_ANTENNA, "Antena GNSS"),
    (MachineReferenceType.HITCH_PIN, "Pino de engate"),
    (MachineReferenceType.REAR_AXLE, "Eixo traseiro"),
    (MachineReferenceType.FRONT_AXLE, "Eixo dianteiro"),
    (MachineReferenceType.TRACTOR_FRONT, "Frente do trator"),
    (MachineReferenceType.IMPLEMENT_REFERENCE, "Referencia do implemento"),
    (MachineReferenceType.CUSTOM, "Personalizada"),
)


class MachineSchematicWidget(QWidget):
    """Desenho do conjunto: ponto GNSS, offset e barra (sentido para cima)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.working_offset_m = None
        self.work_width_m = 0.0
        self.border_width_m = 0.0
        self.reference_label = "Antena GNSS"

    def set_geometry(self, *, working_offset_m, work_width_m, border_width_m, reference_label):
        self.working_offset_m = working_offset_m
        self.work_width_m = work_width_m
        self.border_width_m = border_width_m
        self.reference_label = reference_label
        self.update()

    def layout_data(self) -> dict[str, object]:
        return machine_schematic_layout(
            working_offset_m=self.working_offset_m,
            work_width_m=self.work_width_m,
            width_px=float(max(self.width(), 200)),
            height_px=float(max(self.height(), 150)),
        )

    def paintEvent(self, _event):
        data = self.layout_data()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(250, 250, 247))
        width = float(max(self.width(), 200))
        height = float(max(self.height(), 150))

        painter.setPen(QPen(QColor(120, 120, 120), 1))
        arrow_x = 18.0
        painter.drawLine(QPointF(arrow_x, height - 12), QPointF(arrow_x, 12))
        painter.setBrush(QBrush(QColor(120, 120, 120)))
        painter.drawPolygon(QPolygonF([
            QPointF(arrow_x, 6), QPointF(arrow_x - 5, 16), QPointF(arrow_x + 5, 16),
        ]))
        painter.drawText(QRectF(arrow_x + 6, 2, 90, 16), Qt.AlignLeft, "Sentido")

        gnss_x, gnss_y = data["gnss"]
        if not data["complete"]:
            painter.setPen(QPen(QColor(200, 40, 40), 1))
            painter.drawText(
                QRectF(0, gnss_y + 10, width, 34), Qt.AlignHCenter | Qt.TextWordWrap,
                "Offset da última linha ativa não informado (GEOMETRY_INCOMPLETE)",
            )
        else:
            bar_x, bar_y = data["bar"]
            half = float(data["bar_half_px"])
            if data["position"] != "aligned":
                painter.setPen(QPen(QColor(60, 60, 60), 1, Qt.DashLine))
                painter.drawLine(QPointF(gnss_x, gnss_y), QPointF(bar_x, bar_y))
                middle = (gnss_y + bar_y) / 2.0
                side = "atrás" if data["position"] == "behind" else "à frente"
                painter.drawText(
                    QRectF(gnss_x + 8, middle - 9, width / 2.0 - 12, 18), Qt.AlignLeft,
                    f"{abs(self.working_offset_m):.2f} m {side}".replace(".", ","),
                )
            painter.setPen(QPen(QColor(30, 140, 60), 5, Qt.SolidLine, Qt.FlatCap))
            painter.drawLine(QPointF(bar_x - half, bar_y), QPointF(bar_x + half, bar_y))
            painter.setPen(QPen(QColor(30, 100, 50), 1))
            label_y = bar_y + 6 if data["position"] != "ahead" else bar_y - 22
            painter.drawText(
                QRectF(bar_x - half, label_y, 2 * half, 16), Qt.AlignHCenter,
                f"Barra {self.work_width_m:.2f} m | bordadura {self.border_width_m:.2f} m".replace(".", ","),
            )
        painter.setPen(QPen(QColor(20, 60, 160), 1))
        painter.setBrush(QBrush(QColor(20, 90, 220)))
        painter.drawEllipse(QPointF(gnss_x, gnss_y), 6, 6)
        label_y = gnss_y - 22 if data["position"] != "ahead" else gnss_y + 8
        painter.drawText(QRectF(gnss_x + 10, label_y, width / 2.0, 16), Qt.AlignLeft, self.reference_label)
        painter.end()


class MachineWorkGeometryBox(QGroupBox):
    """Offset longitudinal com sinal, bordadura e estrategia; sem valores inventados."""

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Geometria do conjunto e bordadura do obstaculo", parent)
        form = QFormLayout(self)

        self.strategy_combo = QComboBox()
        self.strategy_combo.addItem("CUT + bordadura (ultima linha ativa)", "CUT_FOR_BORDER")
        self.strategy_combo.addItem("Somente corte (ultima linha ativa)", "CUT_ONLY")
        self.strategy_combo.addItem("Corte radial simples (zona circular)", STRATEGY_RADIAL)
        form.addRow("Estrategia:", self.strategy_combo)

        self.reference_combo = QComboBox()
        for reference, label in REFERENCE_LABELS:
            self.reference_combo.addItem(label, reference.value)
        form.addRow("Ponto de referencia:", self.reference_combo)

        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(-60.01, 60.0)
        self.offset_spin.setDecimals(2)
        self.offset_spin.setSuffix(" m")
        self.offset_spin.setSpecialValueText(OFFSET_PLACEHOLDER)
        self.offset_spin.setValue(self.offset_spin.minimum())
        self.offset_spin.setToolTip(OFFSET_HELP)
        self.offset_label = QLabel(OFFSET_LABEL)
        self.offset_label.setToolTip(OFFSET_HELP)
        form.addRow(self.offset_label, self.offset_spin)
        offset_help = QLabel(OFFSET_HELP)
        offset_help.setWordWrap(True)
        form.addRow(offset_help)

        self.border_combo = QComboBox()
        self.border_combo.addItem("Uma passada do implemento", ObstacleBorderMode.ONE_IMPLEMENT_PASS.value)
        self.border_combo.addItem("Personalizada", ObstacleBorderMode.CUSTOM.value)
        self.border_combo.addItem("Nenhuma", ObstacleBorderMode.NONE.value)
        self.border_combo.setToolTip(BORDER_HELP)
        form.addRow("Bordadura do obstaculo (faixa lateral):", self.border_combo)

        self.border_spin = QDoubleSpinBox()
        self.border_spin.setRange(0.0, 200.0)
        self.border_spin.setDecimals(2)
        self.border_spin.setSuffix(" m")
        form.addRow("Bordadura personalizada:", self.border_spin)
        border_help = QLabel(BORDER_HELP)
        border_help.setWordWrap(True)
        form.addRow(border_help)

        self.anticipation_spin = QDoubleSpinBox()
        self.anticipation_spin.setRange(0.0, 50.0)
        self.anticipation_spin.setDecimals(2)
        self.anticipation_spin.setSuffix(" m")
        self.anticipation_spin.setToolTip(ANTICIPATION_HELP)
        form.addRow("Antecipacao de desligamento:", self.anticipation_spin)

        self.lateral_margin_spin = QDoubleSpinBox()
        self.lateral_margin_spin.setRange(0.0, 50.0)
        self.lateral_margin_spin.setDecimals(2)
        self.lateral_margin_spin.setSuffix(" m")
        form.addRow("Margem lateral:", self.lateral_margin_spin)

        self.schematic = MachineSchematicWidget(self)
        form.addRow("Confira o conjunto:", self.schematic)

        self._load_settings()
        for signal in (
            self.strategy_combo.currentIndexChanged,
            self.reference_combo.currentIndexChanged,
            self.offset_spin.valueChanged,
            self.border_combo.currentIndexChanged,
            self.border_spin.valueChanged,
            self.anticipation_spin.valueChanged,
            self.lateral_margin_spin.valueChanged,
        ):
            signal.connect(self._on_changed)
        self._sync_enabled()

    def strategy_key(self) -> str:
        return self.strategy_combo.currentData()

    def is_longitudinal(self) -> bool:
        return self.strategy_key() != STRATEGY_RADIAL

    def working_offset_m(self):
        value = self.offset_spin.value()
        return None if value <= self.offset_spin.minimum() + 1e-9 else value

    def readiness(self) -> tuple[str, str]:
        return cut_preview_readiness(
            longitudinal=self.is_longitudinal(), working_offset_m=self.working_offset_m()
        )

    def work_geometry(self, work_width_m: float) -> MachineWorkGeometry:
        return MachineWorkGeometry(
            work_width_m=work_width_m,
            reference_type=MachineReferenceType(self.reference_combo.currentData()),
            reference_to_working_line_longitudinal_m=self.working_offset_m(),
            safety_margin_lateral_m=self.lateral_margin_spin.value(),
            obstacle_border_width_m=self.border_spin.value(),
            border_mode=ObstacleBorderMode(self.border_combo.currentData()),
            longitudinal_anticipation_m=self.anticipation_spin.value(),
        )

    def refresh_schematic(self, work_width_m: float) -> None:
        try:
            border = self.work_geometry(work_width_m).desired_border_width_m()
        except ValueError:
            border = 0.0
        self.schematic.set_geometry(
            working_offset_m=self.working_offset_m(),
            work_width_m=work_width_m,
            border_width_m=border,
            reference_label=self.reference_combo.currentText(),
        )

    def _on_changed(self, *_args) -> None:
        self._sync_enabled()
        self._save_settings()
        self.changed.emit()

    def _sync_enabled(self) -> None:
        longitudinal = self.is_longitudinal()
        for widget in (
            self.reference_combo, self.offset_spin, self.border_combo,
            self.anticipation_spin, self.lateral_margin_spin,
        ):
            widget.setEnabled(longitudinal)
        self.border_spin.setEnabled(
            longitudinal and self.border_combo.currentData() == ObstacleBorderMode.CUSTOM.value
        )

    def _load_settings(self) -> None:
        settings = QgsSettings()
        for combo, key in (
            (self.strategy_combo, "strategy"),
            (self.reference_combo, "reference"),
            (self.border_combo, "border_mode"),
        ):
            index = combo.findData(settings.value(SETTINGS_PREFIX + key, "", type=str))
            if index >= 0:
                combo.setCurrentIndex(index)
        offset = settings.value(SETTINGS_PREFIX + "offset", "", type=str)
        if offset not in ("", None):
            try:
                self.offset_spin.setValue(float(offset))
            except ValueError:
                pass
        self.border_spin.setValue(settings.value(SETTINGS_PREFIX + "border_width", 0.0, type=float))
        self.anticipation_spin.setValue(settings.value(SETTINGS_PREFIX + "anticipation", 0.0, type=float))
        self.lateral_margin_spin.setValue(
            settings.value(SETTINGS_PREFIX + "lateral_margin", 0.0, type=float)
        )

    def _save_settings(self) -> None:
        settings = QgsSettings()
        settings.setValue(SETTINGS_PREFIX + "strategy", self.strategy_key())
        settings.setValue(SETTINGS_PREFIX + "reference", self.reference_combo.currentData())
        settings.setValue(SETTINGS_PREFIX + "border_mode", self.border_combo.currentData())
        offset = self.working_offset_m()
        settings.setValue(SETTINGS_PREFIX + "offset", "" if offset is None else str(offset))
        settings.setValue(SETTINGS_PREFIX + "border_width", self.border_spin.value())
        settings.setValue(SETTINGS_PREFIX + "anticipation", self.anticipation_spin.value())
        settings.setValue(SETTINGS_PREFIX + "lateral_margin", self.lateral_margin_spin.value())
