# -*- coding: utf-8 -*-
"""Tela 'Comparar projecao de plantio': escolher -> analisar -> ver no mapa -> usar."""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsMapLayerProxyModel,
    QgsMessageLog,
    QgsProject,
)
from qgis.gui import QgsMapLayerComboBox

from ..strategy_analyzer.curve_strategy import (
    CURVE_SOURCE_AB,
    CURVE_SOURCE_AUTO,
    CURVE_SOURCE_BOUNDARY,
    CURVE_SOURCE_LABELS,
    CURVE_SOURCE_LAYER,
    ab_curve_usable,
    choose_curve_reference,
    with_curve_reference,
)
from ..strategy_analyzer.field_context import build_field_context
from ..strategy_analyzer.models import (
    CRITERION_LINE_COUNT,
    CRITERION_TOTAL_LENGTH,
    CRITERION_TURN_COUNT,
    CURVE_REFERENCE_REQUIRED,
    STRATEGY_ANALYSIS_NO_VALID_STRAIGHT,
    StrategyAnalysisConfig,
    StrategyAnalysisError,
    StrategyCandidate,
    StrategyTolerances,
    StrategyType,
)
from ..strategy_analyzer.strategy_analyzer import LineStrategyAnalyzer, log_summary
from ..strategy_analyzer.strategy_preview import StrategyPreviewManager
from ..strategy_analyzer.strategy_ranker import format_km, summary_rows
from ..strategy_analyzer.strategy_save import (
    SAVE_NEW_VERSION,
    SAVE_REPLACE,
    has_existing_work_path,
    materialize_as_work_path,
)
from .line_layer_utils import extract_line_vertices

LOG_TAG = "FortSmart Projeção"
DIALOG_TITLE = "Comparar projeção de plantio"
EXISTING_MESSAGE = "Já existe um projeto de linhas para este talhão."

COMPARE_BOTH = "both"
COMPARE_STRAIGHT = "straight"
COMPARE_CURVE = "curve"
STRAIGHT_AUTO = "auto"
STRAIGHT_AB = "ab"
MAP_COMPARE = "__compare__"
USE_LABEL = "USAR PROJEÇÃO SELECIONADA"

_STYLE = """
QLabel#projTitle { font-size: 14pt; font-weight: bold; color: #1d2a3a; }
QLabel#stepTitle { font-weight: bold; color: #1d2a3a; }
QLabel#mutedText { color: #5b6b7d; }
QLabel#noticeText { color: #9a5b00; }
QPushButton#choiceBtn {
    background: #e8edf3; color: #1d2a3a; border: 1px solid #c9d3df;
    border-radius: 4px; padding: 6px 14px;
}
QPushButton#choiceBtn:checked { background: #1f6feb; color: white; border-color: #1f6feb; }
QPushButton#choiceBtn:disabled { color: #9aa7b5; }
QPushButton#bigBtn { font-weight: bold; font-size: 11pt; min-height: 40px; }
QPushButton#linkBtn { border: none; background: transparent; color: #1f6feb; text-decoration: underline; padding: 0 4px; }
QFrame#projectionCard { border: 1px solid #c9d3df; border-radius: 8px; background: #ffffff; }
QFrame#projectionCard[selected="true"] { border: 2px solid #1f6feb; background: #eef5ff; }
"""


def reference_points_from_layer(layer, target_crs) -> list[tuple[float, float]]:
    """Feicao selecionada (ou a primeira) da camada, no CRS metrico do talhao; a camada nao muda."""
    if layer is None:
        return []
    features = list(layer.getSelectedFeatures()) or list(layer.getFeatures())
    if not features:
        return []
    geometry = features[0].geometry()
    if geometry is None or geometry.isEmpty():
        return []
    geometry = QgsGeometry(geometry)
    if layer.crs().isValid() and target_crs.isValid() and layer.crs() != target_crs:
        geometry.transform(QgsCoordinateTransform(layer.crs(), target_crs, QgsProject.instance()))
    return extract_line_vertices(geometry)


def card_title(candidate: StrategyCandidate) -> str:
    if candidate.strategy_type is StrategyType.STRAIGHT and candidate.angle_deg is not None:
        return f"RETA — {candidate.angle_deg:g}°"
    return candidate.label


def short_label(candidate: StrategyCandidate, candidates) -> str:
    """'RETA'/'CURVA'; com duas retas na tela, o angulo diferencia."""
    if candidate.strategy_type is StrategyType.STRAIGHT:
        straights = [item for item in candidates if item.strategy_type is StrategyType.STRAIGHT]
        return candidate.label if len(straights) > 1 else "RETA"
    return "CURVA"


def _decimal(value: float, digits: int) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


class ProjectionCard(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, candidate: StrategyCandidate, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.candidate_id = candidate.candidate_id
        self.setObjectName("projectionCard")
        self.setProperty("selected", False)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(190)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        title = QLabel(card_title(candidate))
        title.setObjectName("projTitle")
        layout.addWidget(title)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("mutedText")
            sub.setWordWrap(True)
            layout.addWidget(sub)
        self.lines_label = QLabel(f"{candidate.line_count} passadas")
        self.length_label = QLabel(format_km(candidate.total_length_m))
        self.turns_label = QLabel(f"{candidate.turn_count} manobras")
        for label in (self.lines_label, self.length_label, self.turns_label):
            layout.addWidget(label)
        details = []
        if candidate.gap_ha is not None:
            details.append(f"Falha {_decimal(candidate.gap_ha, 2)} ha")
        if candidate.overlap_ha is not None:
            details.append(f"Sobreposição {_decimal(candidate.overlap_ha, 2)} ha")
        if candidate.short_segment_count:
            details.append(f"{candidate.short_segment_count} trecho(s) curto(s)")
        if details:
            detail = QLabel(" · ".join(details))
            detail.setObjectName("mutedText")
            detail.setWordWrap(True)
            layout.addWidget(detail)
        layout.addStretch(1)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def is_selected(self) -> bool:
        return bool(self.property("selected"))

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self.candidate_id)
        super().mousePressEvent(event)


class StrategyAnalyzerDialog(QDialog):
    strategySaved = pyqtSignal(object)

    def __init__(
        self,
        precision_project,
        *,
        field_name,
        crs_authid,
        reference_layer=None,
        canvas=None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(DIALOG_TITLE)
        self.setStyleSheet(_STYLE)
        self.precision_project = precision_project
        self.field_name = field_name
        self.crs_authid = crs_authid
        self.canvas = canvas
        self.result = None
        self.saved_result = None
        self.curve_reference = None
        self.selected_id = None
        self.map_mode = MAP_COMPARE
        self.cards: dict[str, ProjectionCard] = {}
        self.map_buttons: dict[str, QPushButton] = {}
        self._cancel_requested = False
        self._running = False
        ab_path = tuple(precision_project.effective_ab_line().line_points())
        self.ab_is_curve = ab_curve_usable(ab_path, StrategyTolerances())
        self.previews = StrategyPreviewManager(crs_authid, field_name)
        layout = QVBoxLayout(self)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_setup_page(reference_layer))
        self.pages.addWidget(self._build_results_page())
        layout.addWidget(self.pages)
        self._update_setup_state()

    # ------------------------------------------------------------ pagina 1 --
    def _build_setup_page(self, reference_layer) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel("ANALISAR MELHOR PROJEÇÃO")
        title.setObjectName("projTitle")
        layout.addWidget(title)
        planting = self.precision_project.planting
        width = planting.machine.operational_width_m if planting is not None else 0.0
        info = QLabel(f"Talhão: {self.field_name or '-'}\nImplemento: {_decimal(width, 2)} m")
        info.setObjectName("mutedText")
        layout.addWidget(info)

        step1 = QGroupBox()
        step1_layout = QVBoxLayout(step1)
        step1_title = QLabel("1. O que você quer comparar?")
        step1_title.setObjectName("stepTitle")
        step1_layout.addWidget(step1_title)
        self.mode_group = QButtonGroup(self)
        self.mode_buttons = {}
        for mode, text in (
            (COMPARE_BOTH, "Reta × Curva"),
            (COMPARE_STRAIGHT, "Somente reta"),
            (COMPARE_CURVE, "Somente curva"),
        ):
            button = QRadioButton(text)
            self.mode_group.addButton(button)
            self.mode_buttons[mode] = button
            step1_layout.addWidget(button)
        self.mode_buttons[COMPARE_BOTH].setChecked(True)
        self.mode_group.buttonToggled.connect(lambda *_args: self._update_setup_state())
        layout.addWidget(step1)

        step2 = QGroupBox()
        step2_layout = QVBoxLayout(step2)
        step2_title = QLabel("2. Como gerar a referência?")
        step2_title.setObjectName("stepTitle")
        step2_layout.addWidget(step2_title)

        self.straight_section = QWidget()
        straight_row = QHBoxLayout(self.straight_section)
        straight_row.setContentsMargins(0, 0, 0, 0)
        straight_label = QLabel("RETA")
        straight_label.setMinimumWidth(60)
        straight_row.addWidget(straight_label)
        self.straight_group = QButtonGroup(self)
        self.straight_auto_btn = self._choice_button("Automático", "Testa todos os ângulos e refina o melhor.")
        self.straight_ab_btn = self._choice_button("Usar linha A/B", "Usa só a direção da linha A/B atual.")
        for button in (self.straight_auto_btn, self.straight_ab_btn):
            self.straight_group.addButton(button)
            straight_row.addWidget(button)
        self.straight_auto_btn.setChecked(True)
        straight_row.addStretch(1)
        step2_layout.addWidget(self.straight_section)

        self.curve_section = QWidget()
        curve_layout = QVBoxLayout(self.curve_section)
        curve_layout.setContentsMargins(0, 0, 0, 0)
        curve_row = QHBoxLayout()
        curve_label = QLabel("CURVA")
        curve_label.setMinimumWidth(60)
        curve_row.addWidget(curve_label)
        self.curve_source_label = QLabel("")
        curve_row.addWidget(self.curve_source_label)
        self.curve_change_btn = QPushButton("alterar")
        self.curve_change_btn.setObjectName("linkBtn")
        self.curve_change_btn.setCursor(Qt.PointingHandCursor)
        self.curve_change_btn.clicked.connect(self._toggle_curve_options)
        curve_row.addWidget(self.curve_change_btn)
        curve_row.addStretch(1)
        curve_layout.addLayout(curve_row)
        self.curve_options = QFrame()
        options_layout = QVBoxLayout(self.curve_options)
        options_layout.setContentsMargins(64, 0, 0, 0)
        self.curve_source_group = QButtonGroup(self)
        self.curve_source_buttons = {}
        for source, text in (
            (CURVE_SOURCE_AUTO, "Automática"),
            (CURVE_SOURCE_AB, "Usar curva A/B atual"),
            (CURVE_SOURCE_BOUNDARY, "Usar borda do talhão"),
            (CURVE_SOURCE_LAYER, "Selecionar outra linha"),
        ):
            button = QRadioButton(text)
            self.curve_source_group.addButton(button)
            self.curve_source_buttons[source] = button
            options_layout.addWidget(button)
        if not self.ab_is_curve:
            self.curve_source_buttons[CURVE_SOURCE_AB].setEnabled(False)
            self.curve_source_buttons[CURVE_SOURCE_AB].setToolTip("A linha A/B atual é reta.")
        self.curve_source_buttons[CURVE_SOURCE_AUTO].setChecked(True)
        self.reference_combo = QgsMapLayerComboBox()
        self.reference_combo.setFilters(QgsMapLayerProxyModel.LineLayer)
        self.reference_combo.setAllowEmptyLayer(True)
        self.reference_combo.setLayer(reference_layer)
        self.reference_combo.layerChanged.connect(lambda *_args: self._update_setup_state())
        options_layout.addWidget(self.reference_combo)
        self.curve_source_group.buttonToggled.connect(lambda *_args: self._update_setup_state())
        self.curve_options.setVisible(False)
        curve_layout.addWidget(self.curve_options)
        step2_layout.addWidget(self.curve_section)
        layout.addWidget(step2)

        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("Configurações avançadas")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.advanced_toggle.setArrowType(Qt.RightArrow)
        self.advanced_toggle.setStyleSheet("QToolButton { border: none; }")
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        layout.addWidget(self.advanced_toggle)
        self.advanced_frame = QFrame()
        advanced = QFormLayout(self.advanced_frame)
        self.angle_start = self._angle_spin(0.0, 0.0, 179.5)
        self.angle_end = self._angle_spin(175.0, 0.5, 180.0)
        self.angle_step = self._angle_spin(5.0, 0.5, 90.0)
        advanced.addRow("Busca de reta — início (°):", self.angle_start)
        advanced.addRow("Fim (°):", self.angle_end)
        advanced.addRow("Passo inicial (°):", self.angle_step)
        self.refine_check = QCheckBox("Refinar melhor resultado")
        self.refine_check.setChecked(True)
        advanced.addRow(self.refine_check)
        self.criterion_combo = QComboBox()
        self.criterion_combo.addItem("Menos passadas", CRITERION_LINE_COUNT)
        self.criterion_combo.addItem("Menor percurso", CRITERION_TOTAL_LENGTH)
        self.criterion_combo.addItem("Menos manobras", CRITERION_TURN_COUNT)
        advanced.addRow("Critério de ordenação:", self.criterion_combo)
        self.advanced_frame.setVisible(False)
        layout.addWidget(self.advanced_frame)

        self.analyze_btn = QPushButton("ANALISAR TALHÃO")
        self.analyze_btn.setObjectName("bigBtn")
        self.analyze_btn.clicked.connect(self.run_analysis)
        layout.addWidget(self.analyze_btn)
        progress_row = QHBoxLayout()
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("mutedText")
        self.progress_label.setWordWrap(True)
        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.clicked.connect(self.request_cancel)
        self.cancel_btn.setVisible(False)
        progress_row.addWidget(self.progress_label, 1)
        progress_row.addWidget(self.cancel_btn)
        layout.addLayout(progress_row)
        layout.addStretch(1)
        footer = QHBoxLayout()
        footer.addStretch(1)
        self.close_btn = QPushButton("Fechar")
        self.close_btn.clicked.connect(self.reject)
        footer.addWidget(self.close_btn)
        layout.addLayout(footer)
        return page

    def _choice_button(self, text: str, tooltip: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("choiceBtn")
        button.setCheckable(True)
        button.setToolTip(tooltip)
        return button

    @staticmethod
    def _angle_spin(value, minimum, maximum) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setDecimals(1)
        spin.setSingleStep(0.5)
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        return spin

    def _toggle_advanced(self, opened: bool) -> None:
        self.advanced_toggle.setArrowType(Qt.DownArrow if opened else Qt.RightArrow)
        self.advanced_frame.setVisible(opened)

    def _toggle_curve_options(self) -> None:
        self.curve_options.setVisible(not self.curve_options.isVisible())

    def compare_mode(self) -> str:
        return next(mode for mode, button in self.mode_buttons.items() if button.isChecked())

    def straight_mode(self) -> str:
        return STRAIGHT_AB if self.straight_ab_btn.isChecked() else STRAIGHT_AUTO

    def curve_source(self) -> str:
        return next(source for source, button in self.curve_source_buttons.items() if button.isChecked())

    def _curve_source_text(self) -> str:
        source = self.curve_source()
        if source == CURVE_SOURCE_AUTO:
            resolved = CURVE_SOURCE_AB if self.ab_is_curve else CURVE_SOURCE_BOUNDARY
            return f"Referência: Automática ({CURVE_SOURCE_LABELS[resolved]})"
        if source == CURVE_SOURCE_LAYER:
            layer = self.reference_combo.currentLayer()
            return f"Referência: {layer.name() if layer is not None else 'selecione a linha'}"
        return f"Referência: {CURVE_SOURCE_LABELS[source]}"

    def _update_setup_state(self) -> None:
        mode = self.compare_mode()
        self.straight_section.setEnabled(mode != COMPARE_CURVE)
        self.curve_section.setEnabled(mode != COMPARE_STRAIGHT)
        self.reference_combo.setEnabled(self.curve_source() == CURVE_SOURCE_LAYER)
        self.curve_source_label.setText(self._curve_source_text())

    # ------------------------------------------------------------ pagina 2 --
    def _build_results_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel("COMPARAÇÃO DO TALHÃO")
        title.setObjectName("projTitle")
        layout.addWidget(title)
        self.notice_label = QLabel("")
        self.notice_label.setObjectName("noticeText")
        self.notice_label.setWordWrap(True)
        layout.addWidget(self.notice_label)
        self.cards_row = QHBoxLayout()
        layout.addLayout(self.cards_row)
        self.summary_label = QLabel("")
        self.summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.summary_label)
        map_row = QHBoxLayout()
        map_row.addWidget(QLabel("No mapa:"))
        self.map_group = QButtonGroup(self)
        self.map_row = map_row
        self.compare_btn = self._choice_button("COMPARAR", "Mostra as projeções juntas.")
        self.compare_btn.clicked.connect(lambda: self.set_map_mode(MAP_COMPARE))
        self.map_group.addButton(self.compare_btn)
        map_row.addWidget(self.compare_btn)
        map_row.addStretch(1)
        layout.addLayout(map_row)
        self.use_btn = QPushButton(USE_LABEL)
        self.use_btn.setObjectName("bigBtn")
        self.use_btn.clicked.connect(self.use_selected)
        layout.addWidget(self.use_btn)
        footer = QHBoxLayout()
        self.back_btn = QPushButton("Nova análise")
        self.back_btn.setObjectName("secondaryBtn")
        self.back_btn.clicked.connect(self.new_analysis)
        footer.addWidget(self.back_btn)
        footer.addStretch(1)
        self.results_close_btn = QPushButton("Fechar")
        self.results_close_btn.clicked.connect(self.reject)
        footer.addWidget(self.results_close_btn)
        layout.addLayout(footer)
        return page

    # ------------------------------------------------------------ analise --
    def config(self, ab_azimuth_deg: float | None = None) -> StrategyAnalysisConfig:
        mode = self.compare_mode()
        fixed = ab_azimuth_deg if self.straight_mode() == STRAIGHT_AB else None
        return StrategyAnalysisConfig(
            test_straight=mode != COMPARE_CURVE,
            test_curve=mode != COMPARE_STRAIGHT,
            straight_angle_start=self.angle_start.value(),
            straight_angle_end=self.angle_end.value(),
            straight_angle_step=self.angle_step.value(),
            straight_fixed_angle=fixed,
            refine=self.refine_check.isChecked(),
            ranking_criterion=self.criterion_combo.currentData(),
            max_preview_candidates=2,
        )

    def _context_and_config(self):
        context = build_field_context(self.precision_project)
        config = self.config(context.ab_azimuth_deg)
        self.curve_reference = None
        if config.test_curve:
            layer = self.reference_combo.currentLayer() if self.curve_source() == CURVE_SOURCE_LAYER else None
            points = reference_points_from_layer(layer, QgsCoordinateReferenceSystem(self.crs_authid))
            self.curve_reference = choose_curve_reference(
                self.curve_source(),
                ab_points=context.ab_path,
                boundary_polygons=context.work_area,
                layer_points=points,
                layer_id=layer.id() if layer is not None else "",
                tolerances=config.tolerances,
            )
            context = with_curve_reference(context, self.curve_reference)
        return context, config

    def _on_progress(self, message: str) -> None:
        self.progress_label.setText(message)
        QApplication.processEvents()

    def request_cancel(self) -> None:
        self._cancel_requested = True
        self.progress_label.setText("Cancelando...")

    def _set_running(self, running: bool) -> None:
        self._running = running
        self.analyze_btn.setEnabled(not running)
        self.cancel_btn.setVisible(running)

    def run_analysis(self) -> None:
        """Tudo em memoria; o projeto so muda ao desenhar os previews dos resultados."""
        if self._running:
            return
        self._cancel_requested = False
        self.previews.clear_previews()
        self.result = None
        self._set_running(True)
        self.progress_label.setText("Preparando talhão...")
        try:
            context, config = self._context_and_config()
            config.validate()
            analyzer = LineStrategyAnalyzer(progress=self._on_progress, is_cancelled=lambda: self._cancel_requested)
            result = analyzer.analyze(context, config)
        except (StrategyAnalysisError, ValueError) as exc:
            self.progress_label.setText(str(exc))
            self._show_warning(str(exc))
            return
        finally:
            self._set_running(False)
        if result.cancelled:
            self.progress_label.setText("Análise cancelada. Nenhuma camada foi alterada.")
            return
        QgsMessageLog.logMessage(log_summary(result), LOG_TAG, Qgis.Info)
        if not result.preview_candidates:
            message = self._notice_text(result) or "Nenhuma projeção válida para este talhão."
            self.progress_label.setText(message)
            self._show_warning(message)
            return
        self.result = result
        self.progress_label.setText("")
        self._show_results()

    def _notice_text(self, result) -> str:
        notes = []
        curve = result.curve_candidate()
        if curve is not None and not curve.valid:
            reasons = [item.split(": ", 1)[-1] for item in curve.warnings]
            notes.append("Curva descartada: " + "; ".join(reasons))
        if CURVE_REFERENCE_REQUIRED in result.issue_codes:
            notes.append("Curva não analisada: nenhuma curva de referência disponível.")
        if STRATEGY_ANALYSIS_NO_VALID_STRAIGHT in result.issue_codes:
            notes.append("Nenhuma reta válida para este talhão.")
        return "\n".join(notes)

    def _clear_results(self) -> None:
        for card in self.cards.values():
            self.cards_row.removeWidget(card)
            card.deleteLater()
        for button in self.map_buttons.values():
            self.map_group.removeButton(button)
            self.map_row.removeWidget(button)
            button.deleteLater()
        self.cards.clear()
        self.map_buttons.clear()
        self.selected_id = None

    def _show_results(self) -> None:
        self._clear_results()
        candidates = self.result.preview_candidates
        for index, candidate in enumerate(candidates):
            subtitle = ""
            if candidate.strategy_type is StrategyType.CURVE and self.curve_reference is not None:
                subtitle = f"Referência: {self.curve_reference.description}"
            elif candidate.strategy_type is StrategyType.STRAIGHT and self.straight_mode() == STRAIGHT_AB:
                subtitle = "Direção da linha A/B"
            card = ProjectionCard(candidate, subtitle)
            card.clicked.connect(self.set_map_mode)
            self.cards[candidate.candidate_id] = card
            self.cards_row.addWidget(card)
            button = self._choice_button(short_label(candidate, candidates), f"Mostra só {card_title(candidate)} no mapa.")
            button.clicked.connect(lambda _checked=False, cid=candidate.candidate_id: self.set_map_mode(cid))
            self.map_group.addButton(button)
            self.map_buttons[candidate.candidate_id] = button
            self.map_row.insertWidget(1 + index, button)
            try:
                self.previews.show_candidate(candidate)
            except StrategyAnalysisError as exc:
                self._show_warning(str(exc))
        self.compare_btn.setVisible(len(candidates) > 1)
        self.compare_btn.setEnabled(True)
        self.notice_label.setText(self._notice_text(self.result))
        self.notice_label.setVisible(bool(self.notice_label.text()))
        rows = summary_rows(candidates)
        self.summary_label.setText("\n".join(rows))
        self.summary_label.setVisible(bool(rows))
        self.pages.setCurrentIndex(1)
        if len(candidates) == 1:
            self.set_map_mode(candidates[0].candidate_id)
        else:
            self.set_map_mode(MAP_COMPARE)
        self._update_use_button()
        self._zoom_to_previews()
        self._dock_to_side()

    # ------------------------------------------------------------- selecao --
    def selected_candidate(self) -> StrategyCandidate | None:
        if self.result is None or self.selected_id is None:
            return None
        return self.result.candidate(self.selected_id)

    def curve_candidate(self) -> StrategyCandidate | None:
        if self.result is None:
            return None
        curve = self.result.curve_candidate()
        return curve if curve is not None and curve.valid else None

    def straight_candidate(self) -> StrategyCandidate | None:
        if self.result is None:
            return None
        return next(
            (item for item in self.result.preview_candidates if item.strategy_type is StrategyType.STRAIGHT), None
        )

    def select_candidate(self, candidate_id: str | None) -> None:
        self.selected_id = candidate_id if candidate_id in self.cards else None
        for cid, card in self.cards.items():
            card.set_selected(cid == self.selected_id)
        self._update_use_button()

    def set_map_mode(self, mode: str) -> None:
        """RETA/CURVA: mostra so ela e a seleciona; COMPARAR: mostra todas, mantem a selecao."""
        if mode == MAP_COMPARE:
            self.previews.show_only(list(self.cards))
            self.compare_btn.setChecked(True)
        elif mode in self.cards:
            self.previews.show_only([mode])
            self.map_buttons[mode].setChecked(True)
            self.select_candidate(mode)
        else:
            return
        self.map_mode = mode

    def _update_use_button(self) -> None:
        candidate = self.selected_candidate()
        if candidate is None:
            self.use_btn.setText("Selecione uma projeção (clique no cartão)")
            self.use_btn.setEnabled(False)
        else:
            self.use_btn.setText(f"{USE_LABEL} — {card_title(candidate)}")
            self.use_btn.setEnabled(self.saved_result is None)

    def new_analysis(self) -> None:
        self.previews.clear_previews()
        self._clear_results()
        self.result = None
        self.saved_result = None
        self.pages.setCurrentIndex(0)
        self.progress_label.setText("")

    # ---------------------------------------------------------------- mapa --
    def _zoom_to_previews(self) -> None:
        if self.canvas is None:
            return
        extent = self.previews.combined_extent()
        if extent is None or extent.isEmpty():
            return
        try:
            destination = self.canvas.mapSettings().destinationCrs()
            source = QgsCoordinateReferenceSystem(self.crs_authid)
            if destination.isValid() and source.isValid() and destination != source:
                extent = QgsCoordinateTransform(source, destination, QgsProject.instance()).transformBoundingBox(extent)
            extent.scale(1.1)
            self.canvas.setExtent(extent)
            self.canvas.refresh()
        except Exception as exc:
            QgsMessageLog.logMessage(f"Zoom no preview falhou: {exc}", LOG_TAG, Qgis.Warning)

    def _dock_to_side(self) -> None:
        """Resultados ficam compactos e no canto direito, liberando o mapa."""
        if not self.isVisible():
            return
        self.adjustSize()
        screen = self.screen() if hasattr(self, "screen") else QApplication.primaryScreen()
        area = screen.availableGeometry()
        self.move(area.right() - self.frameGeometry().width() - 16, area.top() + 80)

    # -------------------------------------------------------------- salvar --
    def _confirm(self, candidate: StrategyCandidate) -> bool:
        answer = QMessageBox.question(
            self,
            DIALOG_TITLE,
            f"Gravar {card_title(candidate)} ({candidate.line_count} passadas, "
            f"{format_km(candidate.total_length_m)}) como 12_Passadas_Plantio?",
        )
        return answer == QMessageBox.Yes

    def _ask_save_mode(self, allow_version: bool) -> str | None:
        box = QMessageBox(self)
        box.setWindowTitle("Projeto de linhas existente")
        box.setText(EXISTING_MESSAGE)
        replace = box.addButton("Substituir", QMessageBox.AcceptRole)
        version = box.addButton("Salvar como nova versão", QMessageBox.ActionRole)
        version.setEnabled(allow_version)
        if not allow_version:
            version.setToolTip("Salve o projeto QGIS para manter versões no GeoPackage.")
        cancel = box.addButton("Cancelar", QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        box.exec_()
        clicked = box.clickedButton()
        if clicked is replace:
            return SAVE_REPLACE
        if clicked is version and allow_version:
            return SAVE_NEW_VERSION
        return None

    def _show_warning(self, message: str) -> None:
        QMessageBox.warning(self, DIALOG_TITLE, message)

    def use_selected(self):
        return self.use_candidate(self.selected_candidate())

    def use_candidate(self, candidate: StrategyCandidate | None):
        """validar -> confirmar -> (existente? substituir/versao/cancelar) -> materializar."""
        if candidate is None or not candidate.valid or not candidate.lines:
            self._show_warning("Selecione uma projeção válida.")
            return None
        if not self._confirm(candidate):
            return None
        mode = SAVE_REPLACE
        project = QgsProject.instance()
        if has_existing_work_path(project, self.field_name):
            mode = self._ask_save_mode(allow_version=bool(project.fileName()) and bool(self.field_name))
            if mode is None:
                return None
        try:
            saved = materialize_as_work_path(
                candidate, crs_authid=self.crs_authid, field_name=self.field_name, mode=mode
            )
        except StrategyAnalysisError as exc:
            self._show_warning(str(exc))
            return None
        self.previews.clear_previews()
        self.saved_result = saved
        QgsMessageLog.logMessage(
            f"Field: {self.field_name} / SAVED {candidate.label} lines={candidate.line_count} "
            f"version={saved.version} archived={saved.archived_table or '-'}",
            LOG_TAG,
            Qgis.Info,
        )
        for button in list(self.map_buttons.values()) + [self.compare_btn]:
            button.setEnabled(False)
        self.notice_label.setText(
            f"{card_title(candidate)} gravada como 12_Passadas_Plantio (versão {saved.version})."
        )
        self.notice_label.setVisible(True)
        self._update_use_button()
        self.strategySaved.emit(saved)
        return saved

    def done(self, result_code) -> None:
        self._cancel_requested = True
        self.previews.clear_previews()
        super().done(result_code)

    def closeEvent(self, event) -> None:
        self._cancel_requested = True
        self.previews.clear_previews()
        super().closeEvent(event)
