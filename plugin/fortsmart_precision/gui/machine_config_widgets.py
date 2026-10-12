# -*- coding: utf-8 -*-
"""Widgets de cadastro livre de maquinas (padrao monitores agricolas)."""

from __future__ import annotations

from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..domain.machine_model import PlanterMachine, SprayerMachine
from ..domain.precision_project import (
    SPRAY_HEADLAND_TURN_AUTOMATIC,
    SPRAY_HEADLAND_TURN_MANUAL,
)
from ..domain.planter_geometry import (
    GEOMETRY_WIDTH_MISMATCH,
    PlanterGeometryConfig,
    PlanterGeometryValidator,
    resolve_effective_working_width,
    validate_interpass_row_gap,
)
from ..domain.headland_layout import (
    HEADLAND_CORNER_AUTO,
    HEADLAND_CORNER_FOLLOW_BOUNDARY,
    HEADLAND_CORNER_STRAIGHT_THROUGH,
    HEADLAND_MODE_FIDELITY,
    HEADLAND_MODE_LEGACY,
    HeadlandLayout,
)
from ..domain.sprayer_overlap import (
    OVERLAP_MODE_METERS,
    OVERLAP_MODE_NONE,
    OVERLAP_MODE_NOZZLES,
    SprayerOverlapError,
    effective_pass_spacing_m,
    resolve_sprayer_overlap_m,
)
from ..domain.sprayer_traffic_configuration import (
    SprayerTrafficConfiguration,
    TrafficMeasureResolution,
)
from ..core.spray_headland_preview import format_m, spray_headland_summary
from .spray_headland_schematic_widget import SprayHeadlandSchematicWidget


def build_headland_mode_combo() -> QComboBox:
    combo = QComboBox()
    combo.addItem("Atual (LEGACY)", HEADLAND_MODE_LEGACY)
    combo.addItem("Fiel ao limite (FIDELITY - em teste)", HEADLAND_MODE_FIDELITY)
    combo.setToolTip(
        "FIDELITY desloca o limite real sem reamostrar: preserva recuos, desvios de "
        "poste/arvore e curvas pequenas. Se a validacao falhar, o LEGACY e usado."
    )
    return combo

class PlanterConfigWidget(QWidget):
    """Plantadeira: linhas, espacamento, hitch e raio de giro (como no monitor)."""

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        box = QGroupBox("Plantadeira")
        form = QFormLayout(box)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Nome / modelo no monitor")
        form.addRow("Nome / modelo:", self.name_edit)

        self.row_count_spin = QSpinBox()
        self.row_count_spin.setRange(0, 200)
        self.row_count_spin.setSpecialValueText("informar")
        form.addRow("Numero de linhas:", self.row_count_spin)

        self.row_spacing_spin = QDoubleSpinBox()
        self.row_spacing_spin.setRange(0.0, 2.0)
        self.row_spacing_spin.setDecimals(3)
        self.row_spacing_spin.setSingleStep(0.05)
        self.row_spacing_spin.setSpecialValueText("informar")
        self.row_spacing_spin.setSuffix(" m")
        form.addRow("Espacamento entre linhas:", self.row_spacing_spin)

        self.informed_width_spin = QDoubleSpinBox()
        self.informed_width_spin.setRange(0.0, 80.0)
        self.informed_width_spin.setDecimals(3)
        self.informed_width_spin.setSpecialValueText("informar")
        self.informed_width_spin.setSuffix(" m")
        self.informed_width_spin.setValue(0.0)
        self.informed_width_spin.setToolTip(
            "Distancia entre passadas (P1 = 1 x largura, P2 = 2 x largura...). "
            "Linhas e espacamento apenas conferem o encontro entre passadas."
        )
        form.addRow("Largura de trabalho:", self.informed_width_spin)

        self.use_calculated_width_check = QCheckBox(
            "Usar linhas × espacamento como largura de trabalho (confirmar)"
        )
        form.addRow(self.use_calculated_width_check)

        self.physical_width_spin = QDoubleSpinBox()
        self.physical_width_spin.setRange(0.0, 100.0)
        self.physical_width_spin.setDecimals(3)
        self.physical_width_spin.setSpecialValueText("nao informado")
        self.physical_width_spin.setSuffix(" m")
        self.physical_width_spin.setToolTip(
            "Largura fisica total medida, separada da distancia entre passadas. "
            "Nao altera o espacamento das linhas de plantio."
        )
        form.addRow("Largura fisica total:", self.physical_width_spin)

        self.calc_width_label = QLabel("0,000 m")
        form.addRow("Largura equivalente (linhas x esp.):", self.calc_width_label)

        self.width_status_label = QLabel("")
        self.width_status_label.setWordWrap(True)
        form.addRow("Status:", self.width_status_label)

        self.planter_summary_label = QLabel("")
        self.planter_summary_label.setWordWrap(True)
        form.addRow("Resumo:", self.planter_summary_label)

        tractor_box = QGroupBox("Trator / implemento (monitor)")
        tractor_form = QFormLayout(tractor_box)

        self.hitch_spin = QDoubleSpinBox()
        self.hitch_spin.setRange(0.0, 20.0)
        self.hitch_spin.setDecimals(2)
        self.hitch_spin.setSingleStep(0.1)
        self.hitch_spin.setSuffix(" m")
        tractor_form.addRow("Distancia pino do trator → plantadeira:", self.hitch_spin)

        self.turn_radius_spin = QDoubleSpinBox()
        self.turn_radius_spin.setRange(0.0, 50.0)
        self.turn_radius_spin.setDecimals(2)
        self.turn_radius_spin.setSpecialValueText("nao informado")
        self.turn_radius_spin.setSuffix(" m")
        tractor_form.addRow("Raio de giro:", self.turn_radius_spin)

        note = QLabel(
            "Bitola e pneu nao sao solicitados no plantio — apenas hitch e raio de giro, "
            "como nos monitores, para o giro bater com o implemento."
        )
        note.setWordWrap(True)
        tractor_form.addRow(note)

        self.meeting_label = QLabel("")
        self.meeting_label.setWordWrap(True)
        form.addRow("Encontro ida/volta:", self.meeting_label)

        self.headland_check = QCheckBox("Criar bordadura de plantio")
        self.headland_check.setChecked(True)
        form.addRow(self.headland_check)

        self.headland_width_spin = QDoubleSpinBox()
        self.headland_width_spin.setRange(0.0, 500.0)
        self.headland_width_spin.setDecimals(2)
        self.headland_width_spin.setSingleStep(1.0)
        self.headland_width_spin.setSpecialValueText("usar passadas")
        self.headland_width_spin.setSuffix(" m")
        self.headland_width_spin.setValue(0.0)
        form.addRow("Largura da bordadura (m):", self.headland_width_spin)

        self.headland_spin = QSpinBox()
        self.headland_spin.setRange(1, 20)
        self.headland_spin.setValue(1)
        form.addRow("Passadas de bordadura:", self.headland_spin)

        self.headland_corner_combo = QComboBox()
        self.headland_corner_combo.addItem(
            "Automatico - reta somente em ponta aguda", HEADLAND_CORNER_AUTO
        )
        self.headland_corner_combo.addItem(
            "Seguir o limite", HEADLAND_CORNER_FOLLOW_BOUNDARY
        )
        self.headland_corner_combo.addItem(
            "Prolongar reto na ponta mais fechada", HEADLAND_CORNER_STRAIGHT_THROUGH
        )
        form.addRow("Cantos da bordadura:", self.headland_corner_combo)

        self.headland_mode_combo = build_headland_mode_combo()
        form.addRow("Geracao da bordadura:", self.headland_mode_combo)

        self.headland_status_label = QLabel("")
        self.headland_status_label.setWordWrap(True)
        form.addRow("Faixa resultante:", self.headland_status_label)

        self.extension_spin = QDoubleSpinBox()
        self.extension_spin.setRange(0.0, 100.0)
        self.extension_spin.setDecimals(1)
        self.extension_spin.setValue(10.0)
        self.extension_spin.setSuffix(" m")
        form.addRow("Extensao externa (fora do limite):", self.extension_spin)

        self.turn_mode_combo = QComboBox()
        self.turn_mode_combo.addItem("Extensao reta (como pulverizacao)", "extend")
        self.turn_mode_combo.addItem("Volta offset (curva na bordadura)", "offset_turn")
        form.addRow("Modo de cabeceira:", self.turn_mode_combo)

        root.addWidget(box)
        root.addWidget(tractor_box)

        for w in (
            self.row_count_spin,
            self.row_spacing_spin,
            self.informed_width_spin,
            self.physical_width_spin,
            self.headland_width_spin,
            self.headland_spin,
            self.extension_spin,
            self.turn_radius_spin,
            self.hitch_spin,
        ):
            w.valueChanged.connect(self._refresh)
        self.use_calculated_width_check.toggled.connect(self._refresh)
        self.headland_check.toggled.connect(self._refresh)
        self.headland_corner_combo.currentIndexChanged.connect(self._refresh)
        self.headland_mode_combo.currentIndexChanged.connect(self._refresh)
        self.turn_mode_combo.currentIndexChanged.connect(self._refresh)
        self.name_edit.textChanged.connect(self._refresh)
        self._refresh()

    def configured_width_m(self) -> float | None:
        value = self.informed_width_spin.value()
        return value if value > 0 else None

    def geometry_config(self) -> PlanterGeometryConfig:
        return PlanterGeometryConfig(
            row_count=self.row_count_spin.value(),
            row_spacing_m=self.row_spacing_spin.value(),
            configured_width_m=self.configured_width_m(),
        )

    def calculated_width_m(self) -> float:
        return self.geometry_config().row_based_width_m

    def effective_width_m(self) -> float:
        return resolve_effective_working_width(self.geometry_config())

    def _refresh(self) -> None:
        if self.row_count_spin.value() <= 0 or self.row_spacing_spin.value() <= 0:
            self.calc_width_label.setText("Informe linhas e espacamento")
            self.width_status_label.setText("Informe as medidas reais da plantadeira.")
            self.planter_summary_label.setText("")
            self.meeting_label.setText("")
            self.headland_status_label.setText("Aguardando medidas da plantadeira.")
            self.changed.emit()
            return
        config = self.geometry_config()
        self.calc_width_label.setText(f"{config.row_based_width_m:.3f} m (apenas conferencia)")
        if self.configured_width_m() is None and not self.use_calculated_width_check.isChecked():
            self.width_status_label.setText(
                "Informe a largura real ou confirme o uso de linhas × espacamento."
            )
            self.planter_summary_label.setText("")
            self.meeting_label.setText("")
            self.headland_status_label.setText("Aguardando largura da plantadeira.")
            self.changed.emit()
            return
        issues = PlanterGeometryValidator().validate(config)
        mismatch = [item for item in issues if item.code == GEOMETRY_WIDTH_MISMATCH]
        width = self.effective_width_m()
        if mismatch:
            self.width_status_label.setText(
                f"⚠ {GEOMETRY_WIDTH_MISMATCH}\n{mismatch[0].message}\n"
                f"Distancia entre passadas mantida: {width:.2f} m"
            )
            self.width_status_label.setStyleSheet("color: #b26a00;")
        else:
            self.width_status_label.setText(f"Distancia entre passadas: {width:.2f} m")
            self.width_status_label.setStyleSheet("")
        self._refresh_meeting()
        self._refresh_headland()
        self.changed.emit()

    def _refresh_meeting(self) -> None:
        """Encontro entre passadas vizinhas: nao pode remontar nem falhar."""
        spacing = self.row_spacing_spin.value()
        gap_report = validate_interpass_row_gap(
            self.effective_width_m(), self.row_count_spin.value(), spacing
        )
        gap = gap_report.actual_gap_m
        diff = gap_report.error_m
        self.planter_summary_label.setText(
            f"Plantadeira: {self.row_count_spin.value()} linhas × {spacing:.2f} m\n"
            f"Largura de trabalho: {self.effective_width_m():.2f} m\n"
            f"Largura pelas linhas: {self.calculated_width_m():.2f} m\n"
            f"Encontro entre passadas: {gap:.2f} m"
            + (
                f"\nLargura fisica total: {self.physical_width_spin.value():.2f} m"
                if self.physical_width_spin.value() > 0 else ""
            )
        )
        if abs(diff) <= 0.01:
            texto = f"{gap:.3f} m — igual ao espacamento interno (ok)"
        elif diff < 0:
            texto = (
                f"{gap:.3f} m — REMONTE de {abs(diff):.3f} m: a linha da volta cai "
                f"perto demais da linha da ida (interno {spacing:.3f} m)"
            )
        else:
            texto = (
                f"{gap:.3f} m — FALHA de {diff:.3f} m sem semente entre as passadas "
                f"(interno {spacing:.3f} m)"
            )
        self.meeting_label.setText(texto)

    def _refresh_headland(self) -> None:
        enabled = self.headland_check.isChecked()
        informed = self.headland_width_spin.value()
        self.headland_spin.setEnabled(enabled and informed <= 0)
        self.headland_width_spin.setEnabled(enabled)
        if not enabled:
            self.headland_status_label.setText("Sem bordadura.")
            return
        width = self.effective_width_m()
        count = self.headland_pass_count()
        total = count * width
        if informed > 0:
            self.headland_status_label.setText(
                f"{count} passada(s) x {width:.3f} m = {total:.3f} m "
                f"(informado {informed:.2f} m) | trator a {width / 2.0:.3f} m do limite"
            )
        else:
            self.headland_status_label.setText(
                f"{count} passada(s) x {width:.3f} m = {total:.3f} m "
                f"| trator a {width / 2.0:.3f} m do limite"
            )

    def build_machine(self) -> PlanterMachine:
        if self.configured_width_m() is None and not self.use_calculated_width_check.isChecked():
            raise ValueError(
                "Informe a largura de trabalho real da plantadeira ou confirme "
                "explicitamente o uso de linhas × espacamento."
            )
        name = self.name_edit.text().strip() or "Plantadeira"
        slug = "".join(ch if ch.isalnum() else "_" for ch in name.lower())[:40] or "planter"
        machine = PlanterMachine(
            machine_id=f"custom_{slug}",
            name=name,
            row_count=self.row_count_spin.value(),
            row_spacing_m=self.row_spacing_spin.value(),
            track=None,
            informed_operational_width_m=self.configured_width_m(),
            physical_width_m=(
                self.physical_width_spin.value()
                if self.physical_width_spin.value() > 0 else None
            ),
        )
        machine.validate()
        return machine

    def headland_pass_count(self) -> int:
        if not self.headland_check.isChecked():
            return 0
        informed = self.headland_width_spin.value()
        if informed > 0:
            from ..domain.headland_layout import passes_for_total_width

            return passes_for_total_width(informed, self.effective_width_m())
        return self.headland_spin.value()

    def headland_total_width_m(self) -> float:
        """Faixa de bordadura realmente reservada (passadas x largura)."""
        return self.headland_pass_count() * self.effective_width_m()

    def headland_corner_mode(self) -> str:
        return str(self.headland_corner_combo.currentData())

    def headland_mode(self) -> str:
        return str(self.headland_mode_combo.currentData())

    def extension_m(self) -> float:
        return self.extension_spin.value()

    def headland_turn_mode(self) -> str:
        return self.turn_mode_combo.currentData()

    def turn_radius_m(self) -> float | None:
        value = self.turn_radius_spin.value()
        return None if value <= 0 else value

    def hitch_distance_m(self) -> float:
        return self.hitch_spin.value()


class SprayerConfigWidget(QWidget):
    """Pulverizador generico: barra (aplicacao) + trafego/pneus (shutoff plantio)."""

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)

        boom_box = QGroupBox("Barra / aplicacao")
        boom_form = QFormLayout(boom_box)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Fabricante / modelo (opcional)")
        boom_form.addRow("Nome / modelo:", self.name_edit)

        self.nozzle_count_spin = QSpinBox()
        self.nozzle_count_spin.setRange(0, 1000000)
        self.nozzle_count_spin.setSpecialValueText("informar")
        boom_form.addRow("Numero de bicos:", self.nozzle_count_spin)

        self.nozzle_spacing_spin = QDoubleSpinBox()
        self.nozzle_spacing_spin.setRange(0.0, 1000000.0)
        self.nozzle_spacing_spin.setDecimals(3)
        self.nozzle_spacing_spin.setSpecialValueText("informar")
        self.nozzle_spacing_spin.setSuffix(" m")
        boom_form.addRow("Espacamento entre bicos:", self.nozzle_spacing_spin)

        self.calc_boom_label = QLabel("0,000 m")
        boom_form.addRow("Largura calculada (bicos x esp.):", self.calc_boom_label)

        self.boom_spin = QDoubleSpinBox()
        self.boom_spin.setRange(0.0, 1000000.0)
        self.boom_spin.setDecimals(3)
        self.boom_spin.setSpecialValueText("usar bicos × esp. (se informados)")
        self.boom_spin.setSuffix(" m")
        self.boom_spin.setValue(0.0)
        boom_form.addRow("Largura real da barra (manual):", self.boom_spin)

        self.overlap_mode_combo = QComboBox()
        self.overlap_mode_combo.addItem("Sem transpasse", OVERLAP_MODE_NONE)
        self.overlap_mode_combo.addItem("Em metros", OVERLAP_MODE_METERS)
        self.overlap_mode_combo.addItem("Em numero de bicos", OVERLAP_MODE_NOZZLES)
        # "Em metros" com 0 reproduz o resultado anterior (inclui o transpasse
        # automatico quando a barra informada e menor que a calculada).
        self.overlap_mode_combo.setCurrentIndex(
            self.overlap_mode_combo.findData(OVERLAP_MODE_METERS)
        )
        self.overlap_mode_combo.setToolTip(
            "Transpasse posiciona as passadas (passo = barra fisica - transpasse). "
            "Nao encolhe a barra e nao desliga bicos."
        )
        boom_form.addRow("Modo de transpasse:", self.overlap_mode_combo)

        self.overlap_spin = QDoubleSpinBox()
        self.overlap_spin.setRange(0.0, 1000000.0)
        self.overlap_spin.setDecimals(3)
        self.overlap_spin.setSuffix(" m")
        self.overlap_spin.setValue(0.0)
        self.overlap_label = QLabel("Transpasse (m):")
        boom_form.addRow(self.overlap_label, self.overlap_spin)

        self.overlap_nozzles_spin = QSpinBox()
        self.overlap_nozzles_spin.setRange(0, max(0, self.nozzle_count_spin.value() - 1))
        self.overlap_nozzles_spin.setValue(0)
        self.overlap_nozzles_spin.setToolTip(
            "Transpasse = bicos de transpasse x espacamento entre bicos."
        )
        self.overlap_nozzles_label = QLabel("Bicos de transpasse:")
        boom_form.addRow(self.overlap_nozzles_label, self.overlap_nozzles_spin)

        self.auto_overlap_hint = QLabel("")
        self.auto_overlap_hint.setWordWrap(True)
        boom_form.addRow("Calculo:", self.auto_overlap_hint)

        self.overlap_status_label = QLabel("")
        boom_form.addRow("Espacamento efetivo de passada:", self.overlap_status_label)

        root.addWidget(boom_box)

        traffic_box = QGroupBox("Trafego / pneus (desligamento do plantio)")
        traffic_form = QFormLayout(traffic_box)

        traffic_hint = QLabel(
            "Informe medidas fisicas reais. O plugin calcula zonas de pneu, "
            "rastros e quais linhas da plantadeira desligam — sem digitar ±1,715 m."
        )
        traffic_hint.setWordWrap(True)
        traffic_form.addRow(traffic_hint)

        self.tire_spin = QDoubleSpinBox()
        self.tire_spin.setRange(0.0, 1000000.0)
        self.tire_spin.setDecimals(3)
        self.tire_spin.setSpecialValueText("informar")
        self.tire_spin.setSuffix(" m")
        self.tire_spin.setToolTip("Medida livre informada pelo usuario; nao usa perfil fixo.")
        traffic_form.addRow("Largura do pneu:", self.tire_spin)

        self.inner_clearance_spin = QDoubleSpinBox()
        self.inner_clearance_spin.setRange(0.0, 1000000.0)
        self.inner_clearance_spin.setDecimals(3)
        self.inner_clearance_spin.setSpecialValueText("informar")
        self.inner_clearance_spin.setSuffix(" m")
        self.inner_clearance_spin.setToolTip("Medida livre entre as faces internas dos pneus.")
        traffic_form.addRow("Vao livre entre pneus:", self.inner_clearance_spin)

        self.outer_width_spin = QDoubleSpinBox()
        self.outer_width_spin.setRange(0.0, 1000000.0)
        self.outer_width_spin.setDecimals(3)
        self.outer_width_spin.setSpecialValueText("informar")
        self.outer_width_spin.setSuffix(" m")
        self.outer_width_spin.setToolTip("Medida externa livre; divergencias sao mostradas antes de gerar.")
        traffic_form.addRow("Largura externa total:", self.outer_width_spin)

        self.tire_safety_margin_spin = QDoubleSpinBox()
        self.tire_safety_margin_spin.setRange(0.0, 1000000.0)
        self.tire_safety_margin_spin.setDecimals(3)
        self.tire_safety_margin_spin.setValue(0.0)
        self.tire_safety_margin_spin.setSuffix(" m")
        self.tire_safety_margin_spin.setToolTip(
            "Margem aplicada em cada lado do pneu somente na faixa de exclusao."
        )
        traffic_form.addRow("Margem por lado do pneu:", self.tire_safety_margin_spin)

        self.measure_status_label = QLabel("")
        self.measure_status_label.setWordWrap(True)
        traffic_form.addRow("Validacao:", self.measure_status_label)

        self.resolution_combo = QComboBox()
        self.resolution_combo.addItem(
            "Usar largura externa (se inconsistente)", TrafficMeasureResolution.USE_OUTER.value
        )
        self.resolution_combo.addItem(
            "Usar vao + 2×pneu (se inconsistente)", TrafficMeasureResolution.USE_INNER_AND_TIRES.value
        )
        traffic_form.addRow("Se medidas divergirem:", self.resolution_combo)

        self.zones_preview_label = QLabel("")
        self.zones_preview_label.setWordWrap(True)
        traffic_form.addRow("Zonas calculadas:", self.zones_preview_label)

        root.addWidget(traffic_box)

        ops_box = QGroupBox("Operacao")
        ops_form = QFormLayout(ops_box)

        self.headland_check = QCheckBox("Criar bordadura de aplicacao")
        self.headland_check.setChecked(True)
        ops_form.addRow(self.headland_check)

        self.headland_outside_overlap_spin = QDoubleSpinBox()
        self.headland_outside_overlap_spin.setRange(0.0, 40.0)
        self.headland_outside_overlap_spin.setDecimals(2)
        self.headland_outside_overlap_spin.setSingleStep(0.05)
        self.headland_outside_overlap_spin.setValue(0.0)
        self.headland_outside_overlap_spin.setSuffix(" m")
        self.headland_outside_overlap_spin.setToolTip(
            "Quantos metros da barra FISICA podem ficar fora do limite do talhao "
            "na passada de bordadura. Linha central = meia barra - este valor. "
            "Nao e a extensao externa das passadas."
        )
        ops_form.addRow(
            "Faixa permitida para fora do limite:", self.headland_outside_overlap_spin
        )

        self.headland_width_spin = QDoubleSpinBox()
        self.headland_width_spin.setRange(0.0, 500.0)
        self.headland_width_spin.setDecimals(2)
        self.headland_width_spin.setValue(0.0)
        self.headland_width_spin.setSuffix(" m")
        self.headland_width_spin.setToolTip(
            "Faixa total de bordadura. Deixe 0 para usar exatamente uma passada "
            "de barra. O numero de passadas sai da largura da barra."
        )
        ops_form.addRow("Largura da bordadura (0 = 1 barra):", self.headland_width_spin)

        self.headland_corner_combo = QComboBox()
        self.headland_corner_combo.addItem(
            "Automatico - reta somente em ponta aguda", HEADLAND_CORNER_AUTO
        )
        self.headland_corner_combo.addItem(
            "Seguir o limite", HEADLAND_CORNER_FOLLOW_BOUNDARY
        )
        self.headland_corner_combo.addItem(
            "Prolongar reto na ponta mais fechada", HEADLAND_CORNER_STRAIGHT_THROUGH
        )
        ops_form.addRow("Cantos da bordadura:", self.headland_corner_combo)

        self.headland_mode_combo = build_headland_mode_combo()
        ops_form.addRow("Geracao da bordadura:", self.headland_mode_combo)

        self.half_boom_label = QLabel("—")
        self.half_boom_label.setToolTip(
            "Meia barra: distancia do limite do talhao ate a linha onde o centro "
            "do pulverizador trafega na bordadura."
        )
        ops_form.addRow("Meia barra (linha do trator):", self.half_boom_label)

        self.headland_band_label = QLabel("—")
        self.headland_band_label.setWordWrap(True)
        ops_form.addRow("Faixa reservada:", self.headland_band_label)

        self.headland_summary_label = QLabel("—")
        self.headland_summary_label.setWordWrap(True)
        ops_form.addRow("1a passada da bordadura:", self.headland_summary_label)

        self.headland_schematic = SprayHeadlandSchematicWidget()
        ops_form.addRow(self.headland_schematic)

        self.extension_spin = QDoubleSpinBox()
        self.extension_spin.setRange(0.0, 100.0)
        self.extension_spin.setDecimals(1)
        self.extension_spin.setValue(10.0)
        self.extension_spin.setSuffix(" m")
        ops_form.addRow("Extensao externa (fora do limite):", self.extension_spin)

        self.spray_turn_mode_combo = QComboBox()
        self.spray_turn_mode_combo.addItem(
            "Extensão reta / operador manobra", SPRAY_HEADLAND_TURN_MANUAL
        )
        self.spray_turn_mode_combo.addItem("Manobra automática", SPRAY_HEADLAND_TURN_AUTOMATIC)
        self.spray_turn_mode_combo.setToolTip(
            "Cabeceira = como a maquina sai de uma passada e entra na proxima. "
            "Independente da bordadura (passada junto ao perimetro) e do desvio de obstaculo."
        )
        ops_form.addRow("Modo de cabeceira:", self.spray_turn_mode_combo)
        self.spray_turn_mode_hint = QLabel("")
        self.spray_turn_mode_hint.setWordWrap(True)
        ops_form.addRow(self.spray_turn_mode_hint)

        root.addWidget(ops_box)

        for w in (
            self.nozzle_count_spin,
            self.nozzle_spacing_spin,
            self.boom_spin,
            self.overlap_spin,
            self.tire_spin,
            self.inner_clearance_spin,
            self.outer_width_spin,
            self.tire_safety_margin_spin,
            self.extension_spin,
            self.headland_width_spin,
            self.overlap_nozzles_spin,
            self.headland_outside_overlap_spin,
        ):
            w.valueChanged.connect(self._refresh)
        self.overlap_mode_combo.currentIndexChanged.connect(self._refresh)
        self.resolution_combo.currentIndexChanged.connect(self._refresh)
        self.headland_check.toggled.connect(self._refresh)
        self.headland_corner_combo.currentIndexChanged.connect(self._refresh)
        self.headland_mode_combo.currentIndexChanged.connect(self._refresh)
        self.spray_turn_mode_combo.currentIndexChanged.connect(self._refresh)
        self.name_edit.textChanged.connect(self._refresh)
        self._refresh()

    def spray_headland_turn_mode(self) -> str:
        return str(self.spray_turn_mode_combo.currentData())

    def _refresh_turn_mode_hint(self) -> None:
        if self.spray_headland_turn_mode() == SPRAY_HEADLAND_TURN_AUTOMATIC:
            self.spray_turn_mode_hint.setText(
                "Curva U entre passadas (raio >= minimo do PULVERIZADOR, aba 4 > "
                "Pulverizacao), dentro da extensao externa e da bordadura. "
                "As passadas nao mudam; sem espaco = aviso, sem curva forcada."
            )
        else:
            self.spray_turn_mode_hint.setText(
                "Cada passada segue reta alem do limite (extensao externa); "
                "o operador manobra. Nenhuma ligacao automatica."
            )

    def calculated_boom_m(self) -> float:
        return self.nozzle_count_spin.value() * self.nozzle_spacing_spin.value()

    def effective_boom_m(self) -> float:
        if self.boom_spin.value() > 0:
            return self.boom_spin.value()
        return self.calculated_boom_m()

    def overlap_mode(self) -> str:
        return str(self.overlap_mode_combo.currentData())

    def overlap_nozzle_count(self) -> int:
        return self.overlap_nozzles_spin.value()

    def resolved_overlap_m(self) -> float:
        """Transpasse pelo modo escolhido (regra unica em domain.sprayer_overlap)."""
        return resolve_sprayer_overlap_m(
            self.overlap_mode(),
            nozzle_count=self.nozzle_count_spin.value(),
            nozzle_spacing_m=self.nozzle_spacing_spin.value(),
            boom_width_m=self.effective_boom_m(),
            overlap_m=self.overlap_spin.value(),
            overlap_nozzle_count=self.overlap_nozzle_count(),
            legacy_auto_from_boom=True,
        )

    def _sync_overlap_inputs(self) -> None:
        mode = self.overlap_mode()
        meters = mode == OVERLAP_MODE_METERS
        nozzles = mode == OVERLAP_MODE_NOZZLES
        self.overlap_label.setVisible(meters)
        self.overlap_spin.setVisible(meters)
        self.overlap_nozzles_label.setVisible(nozzles)
        self.overlap_nozzles_spin.setVisible(nozzles)
        self.overlap_nozzles_spin.blockSignals(True)
        self.overlap_nozzles_spin.setMaximum(max(0, self.nozzle_count_spin.value() - 1))
        self.overlap_nozzles_spin.blockSignals(False)

    def _overlap_hint(self, boom: float, calc: float, overlap: float) -> str:
        mode = self.overlap_mode()
        if mode == OVERLAP_MODE_NONE:
            return "Sem transpasse: passo = barra fisica."
        if mode == OVERLAP_MODE_NOZZLES:
            return (
                f"{self.overlap_nozzle_count()} bico(s) × "
                f"{self.nozzle_spacing_spin.value():.3f} m = transpasse {overlap:.3f} m"
            )
        if self.overlap_spin.value() > 0:
            return f"Transpasse informado: {self.overlap_spin.value():.3f} m"
        if calc <= 0:
            return "Barra informada manualmente; sem calculo por bicos e sem transpasse."
        if boom < calc - 0.001:
            return (
                f"Transpasse automatico: faixa ({boom:.3f} m) < calculada ({calc:.3f} m) "
                f"→ {overlap:.3f} m"
            )
        if self.boom_spin.value() > calc + 0.001:
            return (
                f"Faixa informada ({self.boom_spin.value():.3f} m) > calculada ({calc:.3f} m). "
                f"Informe o transpasse manualmente se desejar."
            )
        return "Sem transpasse (informe um valor ou uma faixa menor que a calculada)."

    def _refresh(self) -> None:
        calc = self.calculated_boom_m()
        self.calc_boom_label.setText(
            f"{calc:.3f} m" if calc > 0 else "Informe bicos e espacamento"
        )
        boom = self.effective_boom_m()
        self._sync_overlap_inputs()
        if boom <= 0:
            self.auto_overlap_hint.setText("Informe a largura real da barra ou bicos e espacamento.")
            self.overlap_status_label.setText("Aguardando largura da pulverizacao.")
            self.half_boom_label.setText("—")
            self.headland_band_label.setText("Aguardando largura da barra.")
            self.headland_summary_label.setText("—")
            self._refresh_traffic_preview()
            self._refresh_turn_mode_hint()
            self.changed.emit()
            return
        try:
            overlap = self.resolved_overlap_m()
        except SprayerOverlapError as exc:
            self.auto_overlap_hint.setText(str(exc))
            self.overlap_status_label.setText("Aguardando medidas do transpasse.")
            self._refresh_traffic_preview()
            self._refresh_turn_mode_hint()
            self.changed.emit()
            return

        self.auto_overlap_hint.setText(self._overlap_hint(boom, calc, overlap))
        spacing = boom - overlap
        self.overlap_status_label.setText(
            f"Faixa {boom:.3f} m − transpasse {overlap:.3f} m = passo {spacing:.3f} m"
        )
        self._refresh_headland_preview()
        self._refresh_traffic_preview()
        self._refresh_turn_mode_hint()
        self.changed.emit()

    def _refresh_headland_preview(self) -> None:
        """Meia barra FISICA, linhas centrais e miolo — auditoria antes de gerar."""
        boom = self.effective_boom_m()
        self.headland_outside_overlap_spin.blockSignals(True)
        self.headland_outside_overlap_spin.setMaximum(max(0.0, boom / 2.0 - 0.01))
        self.headland_outside_overlap_spin.blockSignals(False)
        self.half_boom_label.setText(f"{boom / 2.0:.3f} m")
        self.headland_schematic.set_geometry(
            boom_width_m=boom, outside_overlap_m=self.headland_outside_overlap_m()
        )
        passes = self.headland_pass_count()
        if passes <= 0:
            self.headland_band_label.setText("Sem bordadura de aplicacao.")
            self.headland_summary_label.setText("—")
            return
        try:
            layout = self.build_headland_layout()
            offsets = layout.center_offsets_m()
        except ValueError as exc:
            self.headland_band_label.setText(str(exc))
            self.headland_summary_label.setText("—")
            return
        centers = "; ".join(format_m(offset) for offset in offsets)
        self.headland_band_label.setText(
            f"{passes} passada(s). Linha(s) do trator a {centers} do limite; "
            f"miolo comeca a {format_m(layout.reserved_width_m)}."
        )
        self.headland_summary_label.setText(spray_headland_summary(layout))

    def build_traffic_configuration(self) -> SprayerTrafficConfiguration:
        resolution = TrafficMeasureResolution(self.resolution_combo.currentData())
        traffic = SprayerTrafficConfiguration(
            boom_width_m=self.effective_boom_m(),
            tire_width_m=self.tire_spin.value(),
            inner_clearance_m=self.inner_clearance_spin.value(),
            outer_width_m=self.outer_width_spin.value(),
            resolution=resolution,
            safety_margin_m=self.tire_safety_margin_spin.value(),
        )
        traffic.validate()
        return traffic

    def _refresh_traffic_preview(self) -> None:
        try:
            traffic = self.build_traffic_configuration()
            check = traffic.measure_check()
            left, right = traffic.calculate_tire_zones()
            if check.is_consistent:
                self.measure_status_label.setText("Medidas consistentes.")
                self.measure_status_label.setStyleSheet("color: #1b5e20;")
            else:
                self.measure_status_label.setText(
                    f"⚠ {check.message()} Escolha abaixo qual referencia usar."
                )
                self.measure_status_label.setStyleSheet("color: #b00020;")

            self.zones_preview_label.setText(
                f"Bitola (centro a centro): {traffic.track_width_m:.3f} m\n"
                f"Faixa de exclusao por pneu: {traffic.exclusion_width_m:.3f} m "
                f"(pneu + 2 x margem)\n"
                f"Pneu E: [{left.min_m:.3f} ; {left.max_m:.3f}] m\n"
                f"Pneu D: [{right.min_m:.3f} ; {right.max_m:.3f}] m\n"
                f"Vao central livre: [{left.max_m:.3f} ; {right.min_m:.3f}] m"
            )
        except Exception as exc:
            self.measure_status_label.setText(str(exc))
            self.measure_status_label.setStyleSheet("color: #b00020;")
            self.zones_preview_label.setText("")

    def build_machine(self) -> SprayerMachine:
        if self.effective_boom_m() <= 0:
            raise ValueError("Informe a largura real da barra ou bicos e espacamento.")
        if (self.nozzle_count_spin.value() > 0) != (self.nozzle_spacing_spin.value() > 0):
            raise ValueError("Informe numero e espacamento de bicos juntos.")
        if self.overlap_mode() == OVERLAP_MODE_NOZZLES and self.nozzle_count_spin.value() <= 0:
            raise ValueError("Transpasse em bicos exige numero e espacamento reais.")
        name = self.name_edit.text().strip() or "Pulverizador"
        slug = "".join(ch if ch.isalnum() else "_" for ch in name.lower())[:40] or "sprayer"
        boom = self.effective_boom_m()
        overlap = self.resolved_overlap_m()
        if boom - overlap <= 0:
            raise ValueError("Transpasse deve ser menor que a largura da faixa.")
        traffic = self.build_traffic_configuration()
        track = traffic.to_machine_track()
        machine = SprayerMachine(
            machine_id=f"custom_{slug}",
            name=name,
            nozzle_count=self.nozzle_count_spin.value(),
            nozzle_spacing_m=self.nozzle_spacing_spin.value(),
            boom_width_m=boom,
            track=track,
            overlap_m=overlap,
            traffic=traffic,
            overlap_mode=self.overlap_mode(),
            overlap_nozzle_count=(
                self.overlap_nozzle_count() if self.overlap_mode() == OVERLAP_MODE_NOZZLES else 0
            ),
        )
        machine.validate()
        return machine

    def headland_outside_overlap_m(self) -> float:
        return self.headland_outside_overlap_spin.value()

    def build_headland_layout(self, machine: SprayerMachine | None = None) -> HeadlandLayout:
        """Bordadura da aplicacao: meia barra FISICA, passo efetivo, faixa para fora."""
        passes = self.headland_pass_count()
        if passes <= 0:
            return HeadlandLayout(
                pass_count=0,
                width_m=0.0,
                effective_spacing_m=None,
                mode="none",
                corner_mode=self.headland_corner_mode(),
                headland_mode=self.headland_mode(),
            )
        if machine is not None:
            boom = machine.boom_width_m
            spacing = machine.effective_pass_spacing_m
        else:
            boom = self.effective_boom_m()
            spacing = effective_pass_spacing_m(boom, self.resolved_overlap_m())
        layout = HeadlandLayout(
            pass_count=passes,
            width_m=boom,
            effective_spacing_m=spacing,
            mode="follow_boundary",
            corner_mode=self.headland_corner_mode(),
            headland_mode=self.headland_mode(),
            outside_overlap_m=self.headland_outside_overlap_m(),
        )
        layout.validate()
        return layout

    def headland_pass_count(self) -> int:
        """Passadas de bordadura a partir da faixa informada (0 = uma barra)."""
        if not self.headland_check.isChecked():
            return 0
        informed = self.headland_width_spin.value()
        if informed > 0:
            from ..domain.headland_layout import passes_for_total_width

            return passes_for_total_width(informed, self.effective_width_m())
        return 1

    def effective_width_m(self) -> float:
        """Largura operacional real por passada (faixa menos transpasse)."""
        try:
            return effective_pass_spacing_m(self.effective_boom_m(), self.resolved_overlap_m())
        except SprayerOverlapError:
            return self.effective_boom_m()

    def headland_corner_mode(self) -> str:
        return str(self.headland_corner_combo.currentData())

    def headland_mode(self) -> str:
        return str(self.headland_mode_combo.currentData())

    def extension_m(self) -> float:
        return self.extension_spin.value()
