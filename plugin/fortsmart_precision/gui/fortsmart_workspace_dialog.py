# -*- coding: utf-8 -*-
"""Workspace unificado FortSmart Precision Lines."""

from __future__ import annotations

import time
from dataclasses import replace

from qgis.PyQt.QtCore import QEvent, QVariant
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsFillSymbol,
    QgsGeometry,
    QgsLineSymbol,
    QgsPalLayerSettings,
    QgsPointXY,
    QgsProject,
    QgsSingleSymbolRenderer,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
    QgsWkbTypes,
)
from qgis.gui import QgsMapLayerComboBox

from ..core.workspace_cross_utils import project_avoidance_enabled
from ..core.cross_workflow import (
    build_cross_work_area,
    resolve_planting_rows_for_cross,
    resolve_spraying_passes_for_cross,
    run_cross_shutoff,
    session_ready_for_cross,
)
from ..core.crs import CrsValidationError, inspect_authid, normalize_authid
from ..core.line_geometry import decimate_polyline, polyline_length
from ..core.zone_converter import build_zone_conversion_plan, explain_ab_mismatch
from ..core.line_geometry import circle_ring_polygon
from ..core.boundary_engine import headland_status_note
from ..core.precision_lines_engine import PrecisionLinesResult, run_precision_lines
from ..core.spray_headland_turns import SPRAY_HEADLAND_TURN_PROPERTY
from .generation_runner import run_precision_lines_with_progress
from .operational_preview import build_operational_preview_layers
from ..core.preview_layer_names import (
    LEGACY_PREVIEW_GROUP_NAME,
    NAMED_PREVIEW_LAYERS,
    PREVIEW_GROUP_PROPERTY,
    PREVIEW_LAYER_GEOM,
    PREVIEW_LAYER_PROPERTY,
    find_preview_layer,
    is_plugin_preview_layer,
    is_planting_preview_line_layer,
    is_spraying_preview_line_layer,
    preview_group_name,
    preview_layer_base_name,
    unique_layer_name,
)
from ..core.layer_roles import (
    HEADLAND_TURN_ROLE,
    ab_source_rejection_reason,
    apply_qgis_layer_role,
    canonical_field_name,
    find_layer_by_role,
    is_generated_layer,
    is_persisted_layer,
    layer_field_id,
    layer_role_definition,
)
from ..core.persistence_manager import (
    MESSAGES as STORAGE_MESSAGES,
    PROJECT_NOT_SAVED,
    STATUS_KEPT_PREVIOUS,
    FortSmartPersistenceManager,
    PersistenceError,
)
from ..core.operational_generation import build_operational_generation
from ..core.operational_persistence import (
    OperationalPersistenceError,
    OperationalPersistenceStore,
)
from ..domain.operational_contract import CrossSourceMode
from .layer_tree_organizer import (
    generated_layers_for_role,
    insert_layer_ordered,
    move_layers_to_auxiliaries,
    project_group,
    project_group_of,
    prune_empty_sections,
    publish_persisted,
    remove_group_if_empty,
    section_group,
)
from ..core.preview_render_utils import (
    preview_layer_draw_order,
    preview_line_width_mm,
    traffic_pass_points,
)
from ..core.shutoff_engine import (
    aggregate_shutoff_on_passes,
    apply_row_shutoff,
    pass_shutoff_table,
    shutoff_summary,
)
from ..core.parallel_pass_engine import (
    PASS_SEGMENT_FIELDS,
    line_label_for_pass,
    pass_segment_layout,
    source_candidate_index_for,
)
from ..core.planting_line_cut_engine import line_id_for
from ..core.tramline_engine import generate_tramline_zones
from ..domain.avoidance_configuration import AvoidanceConfiguration, AvoidanceMode
from ..domain.guidance_reference import GuidanceMode, GuidanceReference, classify_guidance_mode
from ..domain.headland_layout import HeadlandLayout
from ..domain.obstacle_model import obstacle_from_point, obstacle_from_polygon
from ..domain.planting_avoidance_configuration import (
    PlantingAvoidanceConfiguration,
    PlantingAvoidanceStrategy,
)
from ..domain.planting_kinematics import PlantingKinematics
from ..domain.precision_project import (
    SPRAY_HEADLAND_TURN_AUTOMATIC,
    SPRAY_HEADLAND_TURN_MANUAL,
    ABLine,
    FieldGeometry,
    PrecisionOperation,
    PrecisionProject,
)
from ..domain.sprayer_overlap import machine_pass_overlap_attributes
from .cross_confirm_dialog import CrossConfirmDialog
from .crs_reproject_service import ensure_layers_metric, layer_centroid_lonlat
from .crs_zone_converter_dialog import CrsZoneConverterDialog
from .geometry_bridge import (
    assert_not_degenerate_field,
    pick_field_qgs_geometry,
    qgs_geometry_to_multipolygon,
    vertex_count,
)
from .layer_combo_utils import (
    configure_layer_combo,
    extract_points_from_geometry,
    geometry_type_label,
    is_line_like_vector_layer,
    is_point_like_vector_layer,
    is_polygon_like_vector_layer,
    prefer_metric_polygon_layer,
    prefer_nonempty_obstacle_layer,
    refresh_line_layer_combo,
    refresh_obstacle_layer_combo,
    refresh_polygon_layer_combo,
)
from .line_import_utils import (
    multipolygon_from_polygon_layer,
    planting_rows_from_line_layer,
    spray_passes_from_line_layer,
)
from .line_layer_utils import extract_line_vertices
from .machine_config_widgets import PlanterConfigWidget, SprayerConfigWidget
from .machine_work_geometry_widget import MachineWorkGeometryBox
from .maptools.capture_ab_line_tool import CaptureABLineTool
from .maptools.spray_pass_pick_tool import SprayPassPickTool
from .planting_line_cut_dialog import PlantingLineCutDialog
from .strategy_dialog import StrategyAnalyzerDialog
from ..feature_flags import (
    ENABLE_SPRAY_BORDER_ENTRY_V1,
    ENABLE_STRATEGY_ANALYZER,
    is_enabled,
)
from .metric_work_context import (
    prepare_workspace_metric_context,
    resolve_metric_target_crs,
)


SPRAY_CROSS_SOURCE_LINE_BASE = "line_base"
SPRAY_CROSS_SOURCE_EXISTING_PASSES = "existing_passes"


def _merge_avoided_paths_by_operation(current, previous):
    """Substitui desvios da operacao atual sem acumular historico a cada geracao."""
    if not previous:
        return list(current)
    current_ops = {item.operation_id for item in current}
    kept = [item for item in previous if item.operation_id not in current_ops]
    return list(current) + kept


class FortSmartWorkspaceDialog(QDialog):
    """Fluxo: aplicacao -> plantio -> cruzamento (shutoff/tramlines)."""

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.ab_start = None
        self.ab_end = None
        self.ab_path_points = ()
        self.ab_source_crs = None
        self.guidance_reference = None
        self.previous_map_tool = None
        self.capture_tool = None
        self.last_result = None
        self.border_entry_preview = None
        self.operational_draft = None
        self.active_operational_generation = None
        self.fast_cut_dialog = None
        self.work_crs_authid = None
        self.setWindowTitle("FortSmart Precision — Planejamento")
        self.resize(900, 620)
        self.setMinimumSize(720, 480)
        self._apply_workspace_style()
        self._build_ui()
        self._load_active_operational_generation()

    def _wrap_scroll(self, content: QWidget) -> QScrollArea:
        """Envolve o conteudo da aba em area rolavel (evita cortar botoes em telas menores)."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(content)
        return scroll

    def _apply_workspace_style(self) -> None:
        self.setStyleSheet(
            """
            QDialog { background: #f4f6f8; }
            QGroupBox {
                font-weight: 600;
                border: 1px solid #c5cdd6;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 8px;
                background: #ffffff;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QTabWidget::pane { border: 1px solid #c5cdd6; background: #ffffff; }
            QTabBar::tab {
                padding: 8px 14px;
                margin-right: 2px;
                background: #e8edf2;
                border: 1px solid #c5cdd6;
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected { background: #ffffff; font-weight: 600; }
            QPushButton {
                padding: 7px 12px;
                border-radius: 4px;
                background: #1f6feb;
                color: white;
                font-weight: 600;
            }
            QPushButton:hover { background: #1858bc; }
            QPushButton#secondaryBtn {
                background: #5c6773;
            }
            QPushButton#secondaryBtn:hover { background: #4a545e; }
            QLabel#workflowHeader {
                font-size: 13px;
                font-weight: 600;
                color: #1a3a5c;
                padding: 6px 8px;
                background: #e3eef9;
                border: 1px solid #b8d4f0;
                border-radius: 4px;
            }
            QLabel#statusChip {
                padding: 4px 8px;
                border-radius: 10px;
                background: #eef2f6;
                color: #334155;
            }
            """
        )

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.workflow_header = QLabel(
            "Fluxo: 1 Talhao/A-B → 2 Aplicacao → 3 Plantio → 4 Desvio (opcional) → 5 Cruzamento shutoff"
        )
        self.workflow_header.setObjectName("workflowHeader")
        self.workflow_header.setWordWrap(True)
        layout.addWidget(self.workflow_header)

        status_row = QHBoxLayout()
        self.status_plant_chip = QLabel("Plantio: pendente")
        self.status_plant_chip.setObjectName("statusChip")
        self.status_spray_chip = QLabel("Aplicacao: pendente")
        self.status_spray_chip.setObjectName("statusChip")
        self.status_cross_chip = QLabel("Cruzamento: aguardando")
        self.status_cross_chip.setObjectName("statusChip")
        status_row.addWidget(self.status_plant_chip)
        status_row.addWidget(self.status_spray_chip)
        status_row.addWidget(self.status_cross_chip)
        status_row.addStretch(1)
        layout.addLayout(status_row)

        self.tabs = QTabWidget()
        self._tab_idx_field = 0
        self.tabs.addTab(self._wrap_scroll(self._tab_field()), "1. Camadas / A-B")
        self.sprayer_tab = self._tab_sprayer()
        self._tab_idx_sprayer = 1
        self.tabs.addTab(self._wrap_scroll(self.sprayer_tab), "2. Aplicacao")
        self.planter_tab = self._tab_planter()
        self._tab_idx_planter = 2
        self.tabs.addTab(self._wrap_scroll(self.planter_tab), "3. Plantio")
        self.obstacles_tab = self._tab_obstacles()
        self._tab_idx_obstacles = 3
        self.tabs.addTab(self._wrap_scroll(self.obstacles_tab), "4. Obstaculos")
        self.cross_tab = self._tab_cross()
        self._tab_idx_cross = 4
        self.tabs.addTab(self._wrap_scroll(self.cross_tab), "5. Cruzamento")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs)

        self.planter_widget.changed.connect(self._sync_fast_cut_from_planter)
        self.planter_widget.changed.connect(self._invalidate_operational_draft)
        self.sprayer_widget.changed.connect(self._invalidate_operational_draft)
        self._sync_fast_cut_from_planter()

        project = QgsProject.instance()
        project.layersAdded.connect(self._on_project_layers_changed)
        project.layersRemoved.connect(self._on_project_layers_changed)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Modo de processamento:"))
        self.processing_mode_combo = QComboBox()
        self.processing_mode_combo.addItem("Rapido — Preview (conferir tracado)", "preview")
        self.processing_mode_combo.addItem("Precisao — Final (exportar)", "final")
        self.processing_mode_combo.setCurrentIndex(1)
        self.processing_mode_combo.setToolTip(
            "Rapido: mesma deteccao de obstaculo, mesmo raio operacional e mesma "
            "bordadura; arcos com menos vertices, validacao amostrada e sem "
            "materializar as linhas virtuais da plantadeira.\n"
            "Precisao: geometria completa, validacao total, cruzamento linha x "
            "pneu e todos os segmentos LIGA/DESLIGA."
        )
        self.processing_mode_combo.currentIndexChanged.connect(self._on_processing_mode_changed)
        mode_row.addWidget(self.processing_mode_combo, 1)
        self.processing_mode_hint = QLabel("")
        self.processing_mode_hint.setWordWrap(True)
        mode_row.addWidget(self.processing_mode_hint, 2)
        layout.addLayout(mode_row)

        actions = QHBoxLayout()
        self.gen_spray_btn = QPushButton("1. Gerar aplicacao")
        self.gen_plant_btn = QPushButton("2. Gerar plantio")
        self.apply_avoidance_btn = QPushButton("3. Corte obstaculos")
        self.apply_avoidance_btn.setObjectName("secondaryBtn")
        self.cross_btn = QPushButton("4. Cruzar + shutoff")
        self.clear_btn = QPushButton("Limpar preview")
        self.clear_btn.setObjectName("secondaryBtn")
        self.gen_spray_btn.setToolTip("Gera passadas de pulverizacao (independente do plantio).")
        self.gen_plant_btn.setToolTip("Gera passadas de plantio (independente da aplicacao).")
        self.cross_btn.setToolTip(
            "Cruza plantio × rastros da pulverizacao. "
            "Puxa automaticamente as camadas geradas na sessao ou no preview."
        )
        actions.addWidget(self.gen_spray_btn)
        actions.addWidget(self.gen_plant_btn)
        actions.addWidget(self.apply_avoidance_btn)
        actions.addWidget(self.cross_btn)
        self.strategy_btn = None
        if ENABLE_STRATEGY_ANALYZER:
            self.strategy_btn = QPushButton("COMPARAR PROJEÇÃO")
            self.strategy_btn.setObjectName("secondaryBtn")
            self.strategy_btn.setToolTip(
                "Compara reta e curva em preview temporário. "
                "Só grava 12_Passadas_Plantio quando você escolher."
            )
            self.strategy_btn.clicked.connect(self._open_strategy_analyzer)
            actions.addWidget(self.strategy_btn)
        actions.addWidget(self.clear_btn)
        layout.addLayout(actions)

        self._build_spray_border_entry_box(layout)

        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.generation_progress = QProgressBar()
        self.generation_progress.setRange(0, 100)
        self.generation_progress.setValue(0)
        self.generation_progress.setTextVisible(True)
        self.generation_progress.setFormat("%p%")
        self.generation_progress.setFixedWidth(220)
        self.generation_progress.hide()
        status_row = QHBoxLayout()
        status_row.addWidget(self.summary, 1)
        status_row.addWidget(self.generation_progress, 0)
        layout.addLayout(status_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.capture_btn.clicked.connect(self._capture_ab)
        self.use_ab_layer_btn.clicked.connect(self._load_ab_from_layer)
        self.gen_spray_btn.clicked.connect(self._generate_application)
        self.gen_plant_btn.clicked.connect(self._generate_planting)
        self.apply_avoidance_btn.clicked.connect(self._open_fast_obstacle_cut)
        self.cross_btn.clicked.connect(self._cross_layers)
        self.clear_btn.clicked.connect(self._clear_preview)

    def _spray_border_entry_flag_on(self) -> bool:
        try:
            return bool(is_enabled(ENABLE_SPRAY_BORDER_ENTRY_V1))
        except Exception:
            return False

    def _build_spray_border_entry_box(self, layout: QVBoxLayout) -> None:
        self.border_entry_box = QGroupBox("Entra e sai automático")
        box = QVBoxLayout(self.border_entry_box)
        self.border_entry_summary = QLabel(
            "Gere a aplicação para reconhecer passadas e a bordadura."
        )
        self.border_entry_summary.setWordWrap(True)
        box.addWidget(self.border_entry_summary)
        inspect_row = QHBoxLayout()
        self.border_entry_connection_combo = QComboBox()
        self.border_entry_connection_combo.setMinimumWidth(150)
        self.border_entry_connection_combo.addItem("Todas as conexoes", "")
        self.border_entry_component_combo = QComboBox()
        self.border_entry_component_combo.addItem("Todos os componentes", "all")
        self.border_entry_component_combo.addItem("Saida A-B", "exit")
        self.border_entry_component_combo.addItem("Transito B-D", "transit")
        self.border_entry_component_combo.addItem("Entrada D-E", "entry")
        inspect_row.addWidget(self.border_entry_connection_combo)
        inspect_row.addWidget(self.border_entry_component_combo)
        inspect_row.addStretch(1)
        box.addLayout(inspect_row)
        self.border_entry_detail = QLabel("Selecione uma conexao para inspecionar.")
        self.border_entry_detail.setWordWrap(True)
        self.border_entry_detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box.addWidget(self.border_entry_detail)
        row = QHBoxLayout()
        self.border_entry_preview_btn = QPushButton("Pré-visualizar")
        self.border_entry_confirm_btn = QPushButton("Confirmar")
        self.border_entry_cancel_btn = QPushButton("Cancelar")
        self.border_entry_confirm_btn.setObjectName("secondaryBtn")
        self.border_entry_cancel_btn.setObjectName("secondaryBtn")
        self.border_entry_confirm_btn.setEnabled(False)
        self.border_entry_confirm_btn.setToolTip(
            "Fase 2: previa em memoria, sem gravacao definitiva."
        )
        self.border_entry_preview_btn.clicked.connect(self._preview_spray_border_entry)
        self.border_entry_cancel_btn.clicked.connect(self._cancel_spray_border_entry)
        self.border_entry_connection_combo.currentIndexChanged.connect(
            self._refresh_spray_border_entry_view
        )
        self.border_entry_component_combo.currentIndexChanged.connect(
            self._refresh_spray_border_entry_view
        )
        row.addWidget(self.border_entry_preview_btn)
        row.addWidget(self.border_entry_confirm_btn)
        row.addWidget(self.border_entry_cancel_btn)
        row.addStretch(1)
        box.addLayout(row)
        layout.addWidget(self.border_entry_box)
        self.border_entry_box.setVisible(self._spray_border_entry_flag_on())

    def _tab_field(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        field_box = QGroupBox("Perimetro / talhao")
        field_form = QFormLayout(field_box)
        self.field_combo = QgsMapLayerComboBox()
        configure_layer_combo(self.field_combo, "PolygonLayer")
        field_form.addRow("Camada do perimetro/talhao:", self.field_combo)
        self.field_info = QLabel("Selecione a camada poligonal do talhao")
        field_form.addRow(self.field_info)
        self.field_crs_info = QLabel("")
        self.field_crs_info.setWordWrap(True)
        self.field_crs_info.setStyleSheet("color: #b00020;")
        field_form.addRow("CRS:", self.field_crs_info)
        self.field_combo.layerChanged.connect(self._on_field_changed)
        self.field_combo.layerChanged.connect(self._load_active_operational_generation)
        self.use_selected_field = QCheckBox(
            "Se houver feicao selecionada no mapa, usar so ela "
            "(senao escolhe automaticamente o pivo circular, nao o bbox)"
        )
        self.use_selected_field.setChecked(True)
        field_form.addRow(self.use_selected_field)
        crs_row = QHBoxLayout()
        self.crs_converter_btn = QPushButton("Conversor de zona / CRS…")
        self.crs_converter_btn.clicked.connect(self._open_crs_converter)
        self.auto_convert_btn = QPushButton("Converter automaticamente todas as camadas")
        self.auto_convert_btn.setToolTip(
            "Reprojeta limite, A-B, obstaculos e demais camadas do fluxo "
            "para SIRGAS 2000 / UTM recomendado (uma vez)."
        )
        self.auto_convert_btn.clicked.connect(self._auto_convert_all_layers)
        self.refresh_layers_btn = QPushButton("Atualizar listas de camadas")
        self.refresh_layers_btn.clicked.connect(self._refresh_all_layer_combos)
        crs_row.addWidget(self.crs_converter_btn)
        crs_row.addWidget(self.auto_convert_btn)
        crs_row.addWidget(self.refresh_layers_btn)
        crs_row.addStretch(1)
        field_form.addRow("", crs_row)
        layout.addWidget(field_box)

        ab_box = QGroupBox("Linha A-B de referencia (reta, curva ou adaptativa)")
        ab_form = QFormLayout(ab_box)
        ab_row = QHBoxLayout()
        self.capture_btn = QPushButton("Capturar A-B no mapa")
        self.ab_label = QLabel("A-B nao definida")
        ab_row.addWidget(self.capture_btn)
        ab_row.addWidget(self.ab_label, 1)
        ab_form.addRow("Captura:", ab_row)

        self.ab_layer_combo = QgsMapLayerComboBox()
        configure_layer_combo(self.ab_layer_combo, "VectorLayer")
        ab_form.addRow("Camada de linha (SHP/GPKG/curva):", self.ab_layer_combo)
        self.ab_layers_hint = QLabel("")
        self.ab_layers_hint.setWordWrap(True)
        ab_form.addRow("Linhas no projeto:", self.ab_layers_hint)

        self.use_selected_ab = QCheckBox("Usar apenas feicao selecionada na camada")
        self.use_selected_ab.setChecked(True)
        ab_form.addRow(self.use_selected_ab)

        self.use_ab_layer_btn = QPushButton("Usar linha da camada / selecao")
        ab_form.addRow(self.use_ab_layer_btn)
        ab_form.addRow(
            QLabel(
                "A linha A-B e a referencia das passadas (nao e a bordadura).\n"
                "Bordadura e definida nas abas Aplicacao/Plantio: informe a metragem\n"
                "da faixa (ex.: 18 m) ou o numero de passadas.\n"
                "Prefira o talhao ja em UTM (ex.: '... (EPSG:31981)'). "
                "Se so tiver EPSG:4326, use o Conversor de zona."
            )
        )
        layout.addWidget(ab_box)
        layout.addStretch(1)
        self._refresh_all_layer_combos()
        return widget

    def _on_field_changed(self, layer) -> None:
        if layer is None:
            self.field_info.setText("Nenhuma camada selecionada")
            self.field_crs_info.setText("")
            return
        # Evita talhao metrico vazio (ex.: Boundary … (EPSG:31981) com 0 feicoes).
        if isinstance(layer, QgsVectorLayer) and int(layer.featureCount() or 0) <= 0:
            fixed = prefer_metric_polygon_layer(self.field_combo)
            if fixed is not None and fixed is not layer and int(fixed.featureCount() or 0) > 0:
                layer = fixed
            else:
                self.field_info.setText(
                    f"{layer.name()} (0 feicoes) — camada VAZIA, escolha Boundary/LIMITE com geometria"
                )
                self.field_crs_info.setStyleSheet("color: #b00020;")
                self.field_crs_info.setText(
                    "Talhao sem feicoes. Selecione 'Boundary PV 1' original "
                    "(com poligono) ou clique 'Converter automaticamente todas as camadas'."
                )
                return

        authid = layer.crs().authid() or "?"
        self.field_info.setText(f"{layer.name()} ({layer.featureCount()} feicao(oes))")
        try:
            centroid = layer_centroid_lonlat(layer) if isinstance(layer, QgsVectorLayer) else None
        except Exception:
            centroid = None
        if centroid is not None:
            try:
                plan = build_zone_conversion_plan(authid, centroid[0], centroid[1])
            except Exception as exc:
                self.field_crs_info.setStyleSheet("color: #b00020;")
                self.field_crs_info.setText(f"{authid} — erro ao analisar CRS: {exc}")
                return
            if plan.needs_reprojection:
                self.field_crs_info.setStyleSheet("color: #b00020;")
                self.field_crs_info.setText(
                    f"{plan.summary()}\n\n"
                    "Clique 'Converter automaticamente todas as camadas' "
                    f"para gerar a versao em {plan.target_authid}."
                )
            else:
                self.field_crs_info.setStyleSheet("color: #1b5e20;")
                self.field_crs_info.setText(plan.summary())
        elif authid in ("EPSG:4326", "EPSG:4674"):
            self.field_crs_info.setStyleSheet("color: #b00020;")
            self.field_crs_info.setText(
                f"{authid} (geografico) — use 'Converter automaticamente todas as camadas'."
            )
        else:
            self.field_crs_info.setStyleSheet("")
            self.field_crs_info.setText(authid)

    def _open_crs_converter(self) -> None:
        try:
            dialog = CrsZoneConverterDialog(self.iface, parent=self)
            layer = self.field_combo.currentLayer()
            if layer is not None:
                dialog.layer_combo.setLayer(layer)
            dialog.exec_()
        except Exception as exc:
            QMessageBox.warning(self, "FortSmart — Conversor CRS", str(exc))
        self._refresh_all_layer_combos()

    def _workspace_layers_for_crs(self) -> list:
        """Camadas do fluxo: talhao, A-B, obstaculos, plantio, spray, cruzamento."""
        combos = (
            getattr(self, "field_combo", None),
            getattr(self, "ab_layer_combo", None),
            getattr(self, "obstacle_combo", None),
            getattr(self, "cross_obstacle_combo", None),
            getattr(self, "plant_line_combo", None),
            getattr(self, "planting_line_combo", None),
            getattr(self, "plant_headland_combo", None),
            getattr(self, "plant_headland_cross_combo", None),
            getattr(self, "spray_pass_combo", None),
            getattr(self, "spray_ab_combo", None),
            getattr(self, "plant_ab_combo", None),
            getattr(self, "spray_line_combo", None),
            getattr(self, "spray_headland_combo", None),
            getattr(self, "spray_headland_cross_combo", None),
        )
        layers = []
        seen = set()
        for combo in combos:
            if combo is None:
                continue
            layer = combo.currentLayer()
            if layer is None or not isinstance(layer, QgsVectorLayer):
                continue
            if layer.id() in seen:
                continue
            seen.add(layer.id())
            layers.append(layer)
        return layers

    def _apply_crs_mapping_to_combos(self, mapping: dict) -> None:
        """Atualiza combos para as camadas ja metricas."""
        combos = (
            getattr(self, "field_combo", None),
            getattr(self, "ab_layer_combo", None),
            getattr(self, "obstacle_combo", None),
            getattr(self, "cross_obstacle_combo", None),
            getattr(self, "plant_line_combo", None),
            getattr(self, "planting_line_combo", None),
            getattr(self, "plant_headland_combo", None),
            getattr(self, "plant_headland_cross_combo", None),
            getattr(self, "spray_pass_combo", None),
            getattr(self, "spray_ab_combo", None),
            getattr(self, "plant_ab_combo", None),
            getattr(self, "spray_line_combo", None),
            getattr(self, "spray_headland_combo", None),
            getattr(self, "spray_headland_cross_combo", None),
        )
        for combo in combos:
            if combo is None:
                continue
            current = combo.currentLayer()
            if current is None:
                continue
            mapped = mapping.get(current.id())
            if mapped is not None and mapped is not current:
                cur_n = int(current.featureCount() or 0)
                map_n = int(mapped.featureCount() or 0)
                if map_n <= 0 and cur_n > 0:
                    continue
                try:
                    combo.setLayer(mapped)
                except Exception:
                    pass

    def _auto_convert_all_layers(self) -> None:
        """Converte automaticamente camadas do fluxo + relacionadas no projeto."""
        try:
            from .crs_reproject_service import collect_project_vector_layers, ensure_layers_metric

            # 1) Camadas ja apontadas nos combos.
            layers = self._workspace_layers_for_crs()
            # 2) Demais vetores do projeto que ainda nao estao no destino
            #    (limite, plantio, pulverizacao, base, obstaculos, etc.).
            existing_ids = {layer.id() for layer in layers}
            for layer in collect_project_vector_layers():
                if layer.id() in existing_ids:
                    continue
                name = layer.name().upper()
                keywords = (
                    "BOUNDARY",
                    "LIMITE",
                    "TALHAO",
                    "PIVO",
                    "PLANTIO",
                    "PULVER",
                    "BASE",
                    "OBST",
                    "POSTE",
                    "PEDRA",
                    "DUTOV",
                    "AB",
                    "LINHA",
                )
                if any(key in name for key in keywords):
                    layers.append(layer)
                    existing_ids.add(layer.id())

            if not layers:
                prefer_metric_polygon_layer(self.field_combo)
                layers = self._workspace_layers_for_crs()
            if not layers:
                raise ValueError(
                    "Nenhuma camada vetorial encontrada. "
                    "Carregue limite, A-B, obstaculos, plantio e/ou pulverizacao."
                )

            result = ensure_layers_metric(layers)
            if result.target_authid:
                self.work_crs_authid = result.target_authid
            self._apply_crs_mapping_to_combos(result.mapping)
            self._refresh_all_layer_combos()
            self._apply_crs_mapping_to_combos(result.mapping)
            prefer_metric_polygon_layer(self.field_combo)
            prefer_nonempty_obstacle_layer(self.obstacle_combo)
            self._on_field_changed(self.field_combo.currentLayer())
            ab_layer = self.ab_layer_combo.currentLayer() if hasattr(self, "ab_layer_combo") else None
            if ab_layer is not None:
                self.ab_source_crs = ab_layer.crs()

            extra = ""
            if result.failed:
                empty_names = [name for name, err in result.failed if "0 feicoes" in err]
                if empty_names:
                    extra = (
                        "\n\nCamadas vazias (ignoradas): "
                        + ", ".join(empty_names[:8])
                        + ("…" if len(empty_names) > 8 else "")
                    )

            QMessageBox.information(
                self,
                "FortSmart",
                "Conversao automatica concluida.\n\n"
                f"{result.summary()}\n\n"
                "Os seletores do Planejamento foram atualizados para as camadas metricas."
                f"{extra}",
            )
        except Exception as exc:
            self._warn_crs_error(exc)

    def _ensure_workspace_layers_metric(self, *, silent: bool = True):
        """Garante camadas do workspace no CRS metrico antes de gerar."""
        # Troca talhao metrico vazio pela Boundary original com geometria.
        prefer_metric_polygon_layer(self.field_combo)
        field = self.field_combo.currentLayer()
        if (
            isinstance(field, QgsVectorLayer)
            and int(field.featureCount() or 0) <= 0
        ):
            raise ValueError(
                f"Talhao '{field.name()}' tem 0 feicoes. "
                "Selecione a Boundary/LIMITE com poligono "
                "(nao a copia '(EPSG:…)' vazia) e clique "
                "'Converter automaticamente todas as camadas'."
            )

        if isinstance(field, QgsVectorLayer):
            auth = normalize_authid(field.crs().authid() or "")
            if auth and inspect_authid(auth).is_projected_metric:
                self.work_crs_authid = auth
                return None

        layers = self._workspace_layers_for_crs()
        if not layers:
            return None

        result = ensure_layers_metric(layers)
        if result.target_authid:
            self.work_crs_authid = result.target_authid
        self._apply_crs_mapping_to_combos(result.mapping)

        # Se A-B veio de camada convertida, atualiza CRS fonte.
        ab_layer = self.ab_layer_combo.currentLayer() if hasattr(self, "ab_layer_combo") else None
        if ab_layer is not None and self.ab_source_crs is not None:
            self.ab_source_crs = ab_layer.crs()

        self._refresh_all_layer_combos()
        # Reaplica mapping apos refresh (combos podem ter resetado).
        self._apply_crs_mapping_to_combos(result.mapping)

        if not silent and (result.converted or result.failed):
            pass  # caller mostra mensagem
        elif not silent and not result.converted and not result.failed:
            QMessageBox.information(
                self,
                "FortSmart",
                f"Camadas ja compativeis com {result.target_authid}.",
            )
        return result

    def _set_generation_busy(self, busy: bool) -> None:
        for btn in (
            self.gen_spray_btn,
            self.gen_plant_btn,
            self.apply_avoidance_btn,
            self.cross_btn,
            self.clear_btn,
            getattr(self, "strategy_btn", None),
            getattr(self, "border_entry_preview_btn", None),
            getattr(self, "border_entry_cancel_btn", None),
        ):
            if btn is not None:
                btn.setEnabled(not busy)

    def _run_precision_lines_job(
        self,
        project,
        *,
        title: str,
        status_message: str,
    ) -> PrecisionLinesResult:
        self._pulse_generation_status(status_message)
        return run_precision_lines_with_progress(
            self,
            project,
            title=title,
            bar=self.generation_progress,
        )

    def _apply_ab_polyline(
        self,
        points: list[tuple[float, float]],
        ab_crs,
        *,
        label: str,
    ) -> bool:
        """Define A-B a partir de polilinha; retorna False se direcao invalida."""
        from ..core.ab_direction import resolve_ab_direction_end
        from ..core.line_geometry import sanitize_master_polyline

        points = sanitize_master_polyline(points)
        self.ab_start = points[0]
        self.ab_end = points[-1]
        self.ab_path_points = tuple(points)
        try:
            self.ab_end = resolve_ab_direction_end(
                self.ab_start, self.ab_end, self.ab_path_points
            )
        except ValueError as exc:
            QMessageBox.warning(self, "A-B invalida", str(exc))
            self.ab_start = None
            self.ab_end = None
            self.ab_path_points = ()
            self.ab_label.setText("A-B invalida — capture novamente ou escolha outra linha")
            return False
        self.ab_source_crs = ab_crs
        mode_name = classify_guidance_mode(points)
        mode = {
            "straight": GuidanceMode.STRAIGHT,
            "curved": GuidanceMode.CURVED,
            "adaptive": GuidanceMode.ADAPTIVE,
        }.get(mode_name, GuidanceMode.STRAIGHT)
        self.guidance_reference = GuidanceReference(
            mode=mode,
            start=points[0],
            end=points[-1],
            control_points=tuple(points) if mode != GuidanceMode.STRAIGHT else (),
        )
        auth = ab_crs.authid() if ab_crs and ab_crs.isValid() else ""
        if auth in ("EPSG:4326", "EPSG:4674"):
            fmt = ".6f"
        else:
            fmt = ".2f"
        self.ab_label.setText(
            f"{label} ({mode_name}, {len(points)} pts, {auth}): "
            f"({points[0][0]:{fmt}}, {points[0][1]:{fmt}}) → "
            f"({self.ab_end[0]:{fmt}}, {self.ab_end[1]:{fmt}})"
        )
        return True

    def _pulse_generation_status(self, message: str) -> None:
        """Atualiza o resumo e repinta a UI (evita sensacao de travamento)."""
        self.summary.setText(message)
        try:
            from qgis.PyQt.QtWidgets import QApplication

            QApplication.processEvents()
        except Exception:
            pass

    def _maybe_warn_heavy_avoidance(self, project) -> None:
        """Avisa quando desvio + muitos obstaculos tende a demorar minutos."""
        n_obs = len(project.obstacles or ())
        if n_obs < 8:
            return
        spray_on = project.avoidance.enabled() and project.spraying is not None
        plant_on = project.planting_avoidance.is_enabled() and project.planting is not None
        if not spray_on and not plant_on:
            return
        self._pulse_generation_status(
            f"Desvio com {n_obs} obstaculo(s) e geometria complexa — "
            "1–3 min e normal (QGIS fica ocupado). Aguarde..."
        )

    def _warn_crs_error(self, exc: Exception) -> None:
        from ..core.workspace_cross_utils import format_workspace_error_message

        QMessageBox.warning(self, "FortSmart", format_workspace_error_message(str(exc)))

    def _tab_sprayer(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(
            QLabel(
                "Etapa 1: configure o pulverizador e gere as linhas de aplicacao. "
                "Selecione (ou deixe preencher apos gerar) a bordadura e as passadas."
            )
        )
        self.sprayer_widget = SprayerConfigWidget()
        layout.addWidget(self.sprayer_widget)

        layers_box = QGroupBox("Camadas de aplicacao (bordadura e linhas)")
        form = QFormLayout(layers_box)
        self.spray_headland_combo = QgsMapLayerComboBox()
        configure_layer_combo(self.spray_headland_combo, "VectorLayer")
        form.addRow("Bordadura de pulverizacao (poligono):", self.spray_headland_combo)

        self.spray_ab_combo = QgsMapLayerComboBox()
        configure_layer_combo(self.spray_ab_combo, "VectorLayer")
        try:
            self.spray_ab_combo.setAllowEmptyLayer(True)
            self.spray_ab_combo.setLayer(None)
        except Exception:
            pass
        form.addRow("Linha-base de pulverizacao (opcional):", self.spray_ab_combo)

        self.spray_ab_selected_only = QCheckBox(
            "Usar somente a feicao selecionada da linha-base"
        )
        self.spray_ab_selected_only.setChecked(False)
        form.addRow(self.spray_ab_selected_only)

        self.spray_ab_summary = QLabel("Nenhuma linha-base especifica selecionada.")
        self.spray_ab_summary.setWordWrap(True)
        form.addRow("Referencia adotada:", self.spray_ab_summary)

        self.spray_pass_combo = QgsMapLayerComboBox()
        configure_layer_combo(self.spray_pass_combo, "VectorLayer")
        form.addRow("Linhas / passadas de pulverizacao:", self.spray_pass_combo)

        self.spray_layers_hint = QLabel(
            "Linha-base opcional: se preenchida, a geracao de aplicacao usa ESTA linha "
            "(independente do plantio). Vazia = A-B da aba 1. "
            "Apos gerar, seleciona 05_Passadas — nunca a camada de plantio."
        )
        self.spray_layers_hint.setWordWrap(True)
        form.addRow(self.spray_layers_hint)
        self.spray_ab_combo.layerChanged.connect(self._refresh_spray_ab_summary)
        self.spray_ab_selected_only.toggled.connect(self._refresh_spray_ab_summary)
        layout.addWidget(layers_box)
        layout.addStretch(1)
        return widget

    def _tab_planter(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(
            QLabel(
                "Etapa 2: configure a plantadeira e gere as linhas de plantio. "
                "Selecione bordadura e linhas de plantio (ou use as geradas no preview)."
            )
        )
        self.planter_widget = PlanterConfigWidget()
        layout.addWidget(self.planter_widget)

        layers_box = QGroupBox("Camadas de plantio (bordadura e linhas)")
        layers_form = QFormLayout(layers_box)
        self.plant_headland_combo = QgsMapLayerComboBox()
        configure_layer_combo(self.plant_headland_combo, "VectorLayer")
        layers_form.addRow("Bordadura de plantio (poligono):", self.plant_headland_combo)

        self.plant_ab_combo = QgsMapLayerComboBox()
        configure_layer_combo(self.plant_ab_combo, "VectorLayer")
        try:
            self.plant_ab_combo.setAllowEmptyLayer(True)
            self.plant_ab_combo.setLayer(None)
        except Exception:
            pass
        layers_form.addRow("A-B / referencia do plantio (opcional):", self.plant_ab_combo)

        self.plant_line_combo = QgsMapLayerComboBox()
        configure_layer_combo(self.plant_line_combo, "VectorLayer")
        layers_form.addRow("Linhas de plantio:", self.plant_line_combo)

        self.plant_layers_hint = QLabel(
            "A-B opcional: se preenchida, a geracao de plantio usa ESTA linha "
            "(independente da pulverizacao). Vazia = A-B da aba 1. "
            "Apos gerar, seleciona 06_Passadas_Plantio."
        )
        self.plant_layers_hint.setWordWrap(True)
        layers_form.addRow(self.plant_layers_hint)
        layout.addWidget(layers_box)

        avoid = QGroupBox("Desvio de obstaculos (plantio)")
        form = QFormLayout(avoid)
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItem("Automatico", PlantingAvoidanceStrategy.AUTO.value)
        self.strategy_combo.addItem("Lateral", PlantingAvoidanceStrategy.LATERAL.value)
        self.strategy_combo.addItem("Arco curto (circular)", PlantingAvoidanceStrategy.CIRCULAR.value)
        self.strategy_combo.addItem("Contorno da geometria", PlantingAvoidanceStrategy.CONTOUR.value)
        form.addRow("Estrategia:", self.strategy_combo)
        plant_avoid_hint = QLabel(
            "Plantio usa arco curto ou contorno — o giro 360° e so na pulverizacao (aba 4)."
        )
        plant_avoid_hint.setWordWrap(True)
        form.addRow(plant_avoid_hint)

        self.inner_margin_spin = QDoubleSpinBox()
        self.inner_margin_spin.setRange(0.0, 5.0)
        self.inner_margin_spin.setDecimals(2)
        self.inner_margin_spin.setValue(0.50)
        self.inner_margin_spin.setSuffix(" m")
        form.addRow("Margem interna de seguranca:", self.inner_margin_spin)

        self.outer_margin_spin = QDoubleSpinBox()
        self.outer_margin_spin.setRange(0.0, 5.0)
        self.outer_margin_spin.setDecimals(2)
        self.outer_margin_spin.setValue(0.50)
        self.outer_margin_spin.setSuffix(" m")
        form.addRow("Margem externa de seguranca:", self.outer_margin_spin)

        self.merge_spin = QDoubleSpinBox()
        self.merge_spin.setRange(0.0, 50.0)
        self.merge_spin.setDecimals(2)
        self.merge_spin.setValue(2.0)
        self.merge_spin.setSuffix(" m")
        form.addRow("Agrupar obstaculos ate:", self.merge_spin)
        layout.addWidget(avoid)
        layout.addStretch(1)
        return widget

    def _tab_obstacles(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)

        hint = QLabel(
            "Corte rapido: escolha qualquer camada vetorial de obstaculos "
            "(pontos, linhas ou poligonos — Postes, Pedras, Dutovia, area de exclusao). "
            "Informe as medidas abaixo e use '3. Corte obstaculos'. A linha para "
            "antes da zona e continua depois dela, sem calcular desvios."
        )
        hint.setWordWrap(True)
        form.addRow(hint)

        self.obstacle_combo = QgsMapLayerComboBox()
        configure_layer_combo(self.obstacle_combo, "VectorLayer")
        self.obstacle_combo.setEnabled(True)
        form.addRow("Camada de obstaculos:", self.obstacle_combo)

        obs_btns = QHBoxLayout()
        self.refresh_obstacles_btn = QPushButton("Atualizar lista de camadas")
        self.refresh_obstacles_btn.clicked.connect(self._refresh_obstacle_layers)
        obs_btns.addWidget(self.refresh_obstacles_btn)
        obs_btns.addStretch(1)
        form.addRow("", obs_btns)

        self.obstacle_layers_hint = QLabel("")
        self.obstacle_layers_hint.setWordWrap(True)
        form.addRow("Disponiveis no projeto:", self.obstacle_layers_hint)

        self.obstacle_layer_info = QLabel("Nenhuma camada selecionada")
        self.obstacle_layer_info.setWordWrap(True)
        form.addRow("Camada ativa:", self.obstacle_layer_info)
        self.obstacle_combo.layerChanged.connect(self._on_obstacle_layer_changed)

        self.use_selected_obstacles = QCheckBox(
            "Usar apenas feicoes SELECIONADAS da camada (senao usa todas)"
        )
        self.use_selected_obstacles.setChecked(False)
        self.use_selected_obstacles.setEnabled(True)
        form.addRow(self.use_selected_obstacles)

        self.obstacle_operation_combo = QComboBox()
        self.obstacle_operation_combo.addItem("Plantio", "planting")
        self.obstacle_operation_combo.addItem("Pulverização", "spraying")
        form.addRow("Operação:", self.obstacle_operation_combo)

        self.planting_obstacle_panel = QWidget()
        plant_form = QFormLayout(self.planting_obstacle_panel)
        plant_form.setContentsMargins(0, 0, 0, 0)

        self.obs_radius_spin = QDoubleSpinBox()
        self.obs_radius_spin.setRange(0.0, 100.0)
        self.obs_radius_spin.setDecimals(2)
        self.obs_radius_spin.setValue(1.0)
        self.obs_radius_spin.setSuffix(" m")
        self.obs_radius_spin.setEnabled(True)
        plant_form.addRow("Raio fisico do obstaculo:", self.obs_radius_spin)

        self.spray_margin_spin = QDoubleSpinBox()
        self.spray_margin_spin.setRange(0.0, 50.0)
        self.spray_margin_spin.setDecimals(2)
        self.spray_margin_spin.setValue(0.5)
        self.spray_margin_spin.setSuffix(" m")
        self.spray_margin_spin.setEnabled(True)
        plant_form.addRow("Margem adicional do corte:", self.spray_margin_spin)

        cut_box = QGroupBox("Medidas do corte rapido")
        cut_form = QFormLayout(cut_box)
        self.fast_cut_width_spin = QDoubleSpinBox()
        self.fast_cut_width_spin.setRange(0.01, 200.0)
        self.fast_cut_width_spin.setDecimals(2)
        self.fast_cut_width_spin.setValue(20.0)
        self.fast_cut_width_spin.setSuffix(" m")
        cut_form.addRow("Largura da plantadeira:", self.fast_cut_width_spin)
        self.fast_cut_result_label = QLabel("")
        self.fast_cut_result_label.setWordWrap(True)
        cut_form.addRow("Distancia efetiva:", self.fast_cut_result_label)
        cut_note = QLabel(
            "Formula: metade da largura + raio fisico + margem. "
            "Ex.: 20 m / 2 + 0 m + 1 m = corte a 11 m do poste."
        )
        cut_note.setWordWrap(True)
        cut_form.addRow(cut_note)
        plant_form.addRow(cut_box)

        self.fast_cut_width_spin.valueChanged.connect(self._refresh_fast_cut_measurement)
        self.obs_radius_spin.valueChanged.connect(self._refresh_fast_cut_measurement)
        self.spray_margin_spin.valueChanged.connect(self._refresh_fast_cut_measurement)
        self._refresh_fast_cut_measurement()

        self.fast_cut_geometry_box = MachineWorkGeometryBox(self.planting_obstacle_panel)
        self.fast_cut_geometry_box.changed.connect(self._refresh_fast_cut_measurement)
        plant_form.addRow(self.fast_cut_geometry_box)
        self.fast_cut_geometry_box.refresh_schematic(self.fast_cut_width_spin.value())
        form.addRow(self.planting_obstacle_panel)

        self.enable_avoidance = QCheckBox(
            "Ativar desvio de obstaculos (botao 3 — exige camada com geometrias validas)"
        )
        self.enable_avoidance.setChecked(False)
        self.enable_avoidance.setEnabled(True)
        self.enable_avoidance.setVisible(False)
        form.addRow(self.enable_avoidance)

        self.spray_avoid_box = QGroupBox("Desvio na pulverização")
        spray_form = QFormLayout(self.spray_avoid_box)
        spray_intro = QLabel(
            "Usa o pulverizador da aba 2 (barra fisica, bicos e transpasse). Cada passada "
            "e analisada contra cada obstaculo: so desvia onde a barra encontra a zona de "
            "seguranca, com o menor deslocamento e retorno exato a passada original."
        )
        spray_intro.setWordWrap(True)
        spray_form.addRow(spray_intro)
        self.spray_avoid_enable_check = QCheckBox(
            "Desviar obstaculos ao gerar a aplicacao (botao 1)"
        )
        self.spray_avoid_enable_check.setChecked(False)
        spray_form.addRow(self.spray_avoid_enable_check)
        self.spray_machine_info_label = QLabel("")
        self.spray_machine_info_label.setWordWrap(True)
        spray_form.addRow("Pulverizador (aba 2):", self.spray_machine_info_label)

        self.spray_obstacle_radius_spin = QDoubleSpinBox()
        self.spray_obstacle_radius_spin.setRange(0.0, 100.0)
        self.spray_obstacle_radius_spin.setDecimals(2)
        self.spray_obstacle_radius_spin.setValue(0.5)
        self.spray_obstacle_radius_spin.setSuffix(" m")
        spray_form.addRow("Raio fisico do obstaculo:", self.spray_obstacle_radius_spin)
        self.spray_safety_margin_spin = QDoubleSpinBox()
        self.spray_safety_margin_spin.setRange(0.0, 50.0)
        self.spray_safety_margin_spin.setDecimals(2)
        self.spray_safety_margin_spin.setValue(1.0)
        self.spray_safety_margin_spin.setSuffix(" m")
        spray_form.addRow("Margem de seguranca:", self.spray_safety_margin_spin)
        self.spray_safe_radius_label = QLabel("")
        spray_form.addRow("Raio da zona de seguranca:", self.spray_safe_radius_label)

        self.spray_turn_radius_spin = QDoubleSpinBox()
        self.spray_turn_radius_spin.setRange(0.0, 200.0)
        self.spray_turn_radius_spin.setDecimals(2)
        self.spray_turn_radius_spin.setSuffix(" m")
        self.spray_turn_radius_spin.setSpecialValueText("Nao informado")
        self.spray_turn_radius_spin.setValue(0.0)
        spray_form.addRow("Raio minimo de giro do pulverizador:", self.spray_turn_radius_spin)

        self.spray_avoid_side_combo = QComboBox()
        self.spray_avoid_side_combo.addItem("Automatico (menor desvio)", "auto")
        self.spray_avoid_side_combo.addItem("Esquerda", "left")
        self.spray_avoid_side_combo.addItem("Direita", "right")
        spray_form.addRow("Lado do desvio:", self.spray_avoid_side_combo)

        self.spray_avoid_mode_combo = QComboBox()
        self.spray_avoid_mode_combo.addItem(
            "Desvio minimo (lateral ou contorno so onde a barra encontra a zona)",
            "minimum_deviation",
        )
        self.spray_avoid_mode_combo.addItem(
            "Arco curto (entra e sai na passada)",
            "short_arc",
        )
        self.spray_avoid_mode_combo.addItem(
            "Giro 360° em volta do obstaculo circular",
            "orbit_360",
        )
        self.spray_avoid_mode_combo.setCurrentIndex(0)
        spray_form.addRow("Modo do desvio:", self.spray_avoid_mode_combo)

        self.spray_prep_distance_spin = QDoubleSpinBox()
        self.spray_prep_distance_spin.setRange(0.0, 200.0)
        self.spray_prep_distance_spin.setDecimals(2)
        self.spray_prep_distance_spin.setSuffix(" m")
        self.spray_prep_distance_spin.setSpecialValueText("Automatica")
        spray_form.addRow("Distancia minima de preparacao:", self.spray_prep_distance_spin)
        self.spray_return_distance_spin = QDoubleSpinBox()
        self.spray_return_distance_spin.setRange(0.0, 200.0)
        self.spray_return_distance_spin.setDecimals(2)
        self.spray_return_distance_spin.setSuffix(" m")
        self.spray_return_distance_spin.setSpecialValueText("Automatica")
        spray_form.addRow("Distancia minima de retorno:", self.spray_return_distance_spin)

        self.spray_avoid_status_label = QLabel("")
        self.spray_avoid_status_label.setWordWrap(True)
        spray_form.addRow(self.spray_avoid_status_label)
        form.addRow(self.spray_avoid_box)

        self.spray_avoid_enable_check.toggled.connect(self._sync_spray_avoid_controls)
        self.spray_avoid_mode_combo.currentIndexChanged.connect(self._sync_spray_avoid_controls)
        self.spray_turn_radius_spin.valueChanged.connect(self._sync_spray_avoid_controls)
        self.spray_obstacle_radius_spin.valueChanged.connect(self._refresh_spray_avoid_info)
        self.spray_safety_margin_spin.valueChanged.connect(self._refresh_spray_avoid_info)
        self.sprayer_widget.changed.connect(self._refresh_spray_avoid_info)
        self.sprayer_widget.changed.connect(self._sync_spray_avoid_controls)
        self.obstacle_operation_combo.currentIndexChanged.connect(self._on_obstacle_operation_changed)
        self._refresh_spray_avoid_info()
        self._sync_spray_avoid_controls()
        self._on_obstacle_operation_changed()

        audit_panel = self._build_avoidance_audit_panel()
        audit_panel.setVisible(False)
        form.addRow(audit_panel)

        self._refresh_obstacle_layers()
        return widget

    def _refresh_fast_cut_measurement(self, *_args) -> None:
        if not hasattr(self, "fast_cut_result_label"):
            return
        half_width = self.fast_cut_width_spin.value() / 2.0
        radius = self.obs_radius_spin.value()
        margin = self.spray_margin_spin.value()
        effective = half_width + radius + margin
        self.fast_cut_result_label.setText(
            f"{half_width:.2f} + {radius:.2f} + {margin:.2f} = "
            f"{effective:.2f} m antes/depois do obstaculo"
        )
        box = getattr(self, "fast_cut_geometry_box", None)
        if box is not None:
            box.refresh_schematic(self.fast_cut_width_spin.value())

    def _sync_fast_cut_from_planter(self, *_args) -> None:
        """A largura do corte vem da mesma plantadeira configurada na etapa 3."""
        if not hasattr(self, "fast_cut_width_spin") or not hasattr(self, "planter_widget"):
            return
        self.fast_cut_width_spin.setValue(self.planter_widget.effective_width_m())

    @staticmethod
    def _copy_combo_value(source, destination) -> None:
        index = destination.findData(source.currentData())
        if index >= 0:
            destination.setCurrentIndex(index)

    def _copy_fast_cut_geometry(self, destination: MachineWorkGeometryBox) -> None:
        source = self.fast_cut_geometry_box
        for source_combo, destination_combo in (
            (source.strategy_combo, destination.strategy_combo),
            (source.reference_combo, destination.reference_combo),
            (source.border_combo, destination.border_combo),
        ):
            self._copy_combo_value(source_combo, destination_combo)
        destination.offset_spin.setValue(source.offset_spin.value())
        destination.border_spin.setValue(source.border_spin.value())
        destination.lateral_margin_spin.setValue(source.lateral_margin_spin.value())

    def _on_fast_cut_saved(self, saved_names) -> None:
        """Faz o resultado do corte continuar no fluxo principal do Planejamento."""
        self._refresh_operation_layer_combos()
        final_layer = find_layer_by_role(self._field_scoped_layers(), "FINAL_WORK_PATH")
        if final_layer is not None:
            self.plant_line_combo.setLayer(final_layer)
        names = ", ".join(str(name) for name in saved_names)
        self.summary.setText(
            f"Corte e bordadura salvos no Planejamento: {names}. "
            "31_Linhas_Finais agora e a camada de plantio ativa."
        )

    def _open_fast_obstacle_cut(self) -> None:
        line_layer = self.plant_line_combo.currentLayer()
        if not is_line_like_vector_layer(line_layer):
            line_layer = find_layer_by_role(self._field_scoped_layers(), "WORK_PATH", non_empty=True)
        field_layer = self.field_combo.currentLayer()
        obstacle_layer = self.obstacle_combo.currentLayer()
        if not is_line_like_vector_layer(line_layer):
            QMessageBox.warning(
                self,
                "FortSmart — Corte",
                "Gere o plantio ou selecione a camada de linhas na aba 3.",
            )
            return
        if not is_polygon_like_vector_layer(field_layer):
            QMessageBox.warning(self, "FortSmart — Corte", "Selecione o talhao na aba 1.")
            return
        if obstacle_layer is None:
            QMessageBox.warning(
                self, "FortSmart — Corte", "Selecione a camada de obstaculos nesta aba."
            )
            return

        self.fast_cut_dialog = PlantingLineCutDialog(self.iface, self)
        self.fast_cut_dialog.lines_combo.setLayer(line_layer)
        self.fast_cut_dialog.field_combo.setLayer(field_layer)
        self.fast_cut_dialog.obstacle_combo.setLayer(obstacle_layer)
        self.fast_cut_dialog.implement_width.setValue(self.fast_cut_width_spin.value())
        self.fast_cut_dialog.obstacle_radius.setValue(self.obs_radius_spin.value())
        self.fast_cut_dialog.safety_margin.setValue(self.spray_margin_spin.value())
        self._copy_fast_cut_geometry(self.fast_cut_dialog.work_geometry_box)
        self.fast_cut_dialog.selected_obstacles_check.setChecked(
            self.use_selected_obstacles.isChecked()
        )
        self.fast_cut_dialog.setWindowTitle(
            "FortSmart Precision — Planejamento — Corte e bordadura"
        )
        self.fast_cut_dialog.resultSaved.connect(self._on_fast_cut_saved)
        self.fast_cut_dialog.show()
        self.fast_cut_dialog.raise_()
        self.fast_cut_dialog.preview()

    def _on_obstacle_operation_changed(self, *_args) -> None:
        """Plantio mantem o fluxo de corte atual; Pulverizacao mostra o desvio da barra."""
        spraying = self.obstacle_operation_combo.currentData() == "spraying"
        self.planting_obstacle_panel.setVisible(not spraying)
        self.spray_avoid_box.setVisible(spraying)
        if spraying:
            self._refresh_spray_avoid_info()

    def _refresh_spray_avoid_info(self, *_args) -> None:
        from ..core.spray_avoidance_preview import spray_machine_summary, spray_safe_radius_text

        widget = self.sprayer_widget
        self.spray_machine_info_label.setText(
            spray_machine_summary(
                boom_width_m=widget.effective_boom_m(),
                nozzle_count=widget.nozzle_count_spin.value(),
                nozzle_spacing_m=widget.nozzle_spacing_spin.value(),
                overlap_m=widget.resolved_overlap_m(),
            )
        )
        self.spray_safe_radius_label.setText(
            spray_safe_radius_text(
                self.spray_obstacle_radius_spin.value(), self.spray_safety_margin_spin.value()
            )
        )

    def _sync_spray_avoid_controls(self, *_args) -> None:
        """Campos do desvio so com o desvio ativo; lado/distancias so no desvio minimo."""
        if getattr(self, "spray_avoid_enable_check", None) is None:
            return
        enabled = self.spray_avoid_enable_check.isChecked()
        minimum = self.spray_avoid_mode_combo.currentData() == "minimum_deviation"
        for widget in (
            self.spray_obstacle_radius_spin,
            self.spray_safety_margin_spin,
            self.spray_turn_radius_spin,
            self.spray_avoid_mode_combo,
        ):
            widget.setEnabled(enabled)
        auto_turns = self.sprayer_widget.spray_headland_turn_mode() == SPRAY_HEADLAND_TURN_AUTOMATIC
        if auto_turns:
            self.spray_turn_radius_spin.setEnabled(True)
        self._sync_spray_headland_turn_hint(auto_turns)
        for widget in (
            self.spray_avoid_side_combo,
            self.spray_prep_distance_spin,
            self.spray_return_distance_spin,
        ):
            widget.setEnabled(enabled and minimum)
        if enabled and self._sprayer_turn_radius_m() is None:
            self.spray_avoid_status_label.setText(
                "Informe o raio minimo de giro do PULVERIZADOR: sem ele o desvio nao e "
                "calculado (o raio da plantadeira nunca e usado)."
            )
        else:
            self.spray_avoid_status_label.setText("")

    def _sync_spray_headland_turn_hint(self, auto_turns: bool) -> None:
        """Manobra automatica sem raio do pulverizador: aviso na aba 2 (geracao bloqueia)."""
        hint = self.sprayer_widget.spray_turn_mode_hint
        if auto_turns and self._sprayer_turn_radius_m() is None:
            hint.setText(
                "⚠ Manobra automatica sem raio: informe o 'Raio minimo de giro do "
                "pulverizador' na aba 4 > Pulverizacao (o raio da plantadeira nao e usado)."
            )
            hint.setStyleSheet("color: #b00020;")
        else:
            hint.setStyleSheet("")

    def _spray_avoidance_requested(self) -> bool:
        check = getattr(self, "spray_avoid_enable_check", None)
        return bool(check is not None and check.isChecked())

    def _sprayer_turn_radius_m(self) -> float | None:
        """Raio do pulverizador informado na aba 4; None = nao informado (nunca inventado)."""
        spin = getattr(self, "spray_turn_radius_spin", None)
        if spin is None or spin.value() <= 0:
            return None
        return float(spin.value())

    def _spray_avoidance_configuration(self) -> AvoidanceConfiguration:
        mode = self.spray_avoid_mode_combo.currentData()
        return AvoidanceConfiguration(
            mode=AvoidanceMode.CONCENTRIC_RING,
            minimum_turn_radius_m=self._sprayer_turn_radius_m(),
            orbit_360=mode == "orbit_360",
            minimum_deviation=mode == "minimum_deviation",
            side_preference=str(self.spray_avoid_side_combo.currentData()),
            preparation_distance_m=self.spray_prep_distance_spin.value(),
            return_distance_m=self.spray_return_distance_spin.value(),
        )

    def _build_avoidance_audit_panel(self) -> QGroupBox:
        """Painel auditavel: raio operacional, clearance e cobertura do desvio."""
        box = QGroupBox("Auditoria do desvio (preenchido apos gerar)")
        layout = QVBoxLayout(box)

        self.audit_hint = QLabel(
            "Raio operacional = raio do obstaculo + meia largura da maquina + margem.\n"
            "Clearance = folga que sobrou entre a ponta da barra e o obstaculo na "
            "trajetoria final (negativo = invasao)."
        )
        self.audit_hint.setWordWrap(True)
        layout.addWidget(self.audit_hint)

        self.audit_table = QTableWidget(0, 2)
        self.audit_table.setHorizontalHeaderLabels(["Medida", "Valor"])
        self.audit_table.verticalHeader().setVisible(False)
        self.audit_table.setMinimumHeight(220)
        try:
            self.audit_table.horizontalHeader().setStretchLastSection(True)
        except Exception:
            pass
        layout.addWidget(self.audit_table)

        self.audit_status = QLabel("Sem dados de desvio nesta sessao.")
        self.audit_status.setWordWrap(True)
        layout.addWidget(self.audit_status)
        return box

    def _current_audits(self, result: PrecisionLinesResult) -> list:
        """Auditoria de pulverizacao e/ou plantio a partir do resultado atual."""
        from ..core.avoidance_audit_engine import build_avoidance_audit

        project = result.project
        if project is None or not project.obstacles:
            return []
        obstacles = list(project.obstacles)
        paths = list(result.avoided_paths or [])
        audits = []
        if project.spraying is not None:
            audits.append(
                build_avoidance_audit(
                    operation_id=project.spraying.operation_id,
                    machine=project.spraying.machine,
                    obstacles=obstacles,
                    avoided_paths=paths,
                    safety_margin_m=(
                        self.spray_safety_margin_spin.value()
                        if self._spray_avoidance_requested()
                        else self.spray_margin_spin.value()
                    ),
                    minimum_turn_radius_m=project.avoidance.minimum_turn_radius_m or 0.0,
                    extension_m=project.spraying.extension_m,
                )
            )
        if project.planting is not None:
            audits.append(
                build_avoidance_audit(
                    operation_id=project.planting.operation_id,
                    machine=project.planting.machine,
                    obstacles=obstacles,
                    avoided_paths=paths,
                    safety_margin_m=self.outer_margin_spin.value(),
                    minimum_turn_radius_m=project.planting_avoidance.minimum_turn_radius_m or 0.0,
                    extension_m=project.planting.extension_m,
                )
            )
        return audits

    def _update_avoidance_audit(self, result: PrecisionLinesResult) -> None:
        """Atualiza o painel de auditoria da aba de obstaculos."""
        if not hasattr(self, "audit_table"):
            return
        self.audit_table.setRowCount(0)
        try:
            audits = self._current_audits(result)
        except Exception as exc:
            self.audit_status.setText(f"Auditoria indisponivel: {exc}")
            return
        if not audits:
            self.audit_status.setText(
                "Sem obstaculos no projeto — nada a auditar. "
                "Selecione a camada de obstaculos e gere novamente."
            )
            return

        row_i = 0
        problems = 0
        for audit in audits:
            label = "PULVERIZACAO" if audit.operation_id == "spraying" else "PLANTIO"
            self.audit_table.insertRow(row_i)
            header = QTableWidgetItem(f"— {label} ({audit.machine_name}) —")
            self.audit_table.setItem(row_i, 0, header)
            self.audit_table.setItem(row_i, 1, QTableWidgetItem(""))
            row_i += 1
            for name, value in audit.rows():
                self.audit_table.insertRow(row_i)
                self.audit_table.setItem(row_i, 0, QTableWidgetItem(name))
                self.audit_table.setItem(row_i, 1, QTableWidgetItem(value))
                row_i += 1
            problems += len(audit.unsafe)

        if problems:
            self.audit_status.setText(
                f"ATENCAO: {problems} trecho(s) com a ponta do implemento sem folga. "
                "Aumente a margem de seguranca ou reduza o raio minimo de giro."
            )
        else:
            self.audit_status.setText(
                "Todas as trajetorias mantem a ponta do implemento fora do obstaculo."
            )

    def _tab_cross(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        intro = QGroupBox("Cruzamento plantio × pulverizacao (shutoff)")
        intro_layout = QVBoxLayout(intro)
        intro_layout.addWidget(
            QLabel(
                "Etapa final: calcula LIGA/DESLIGA da semente onde o rastro do "
                "pulverizador cruza as linhas de plantio.\n\n"
                "• Gere plantio e aplicacao separadamente (botoes 1 e 2).\n"
                "• As camadas do preview sao selecionadas automaticamente.\n"
                "• Confirme bitola/pneu e clique em '4. Cruzar + shutoff'."
            )
        )
        layout.addWidget(intro)

        form = QFormLayout()
        self.planting_line_combo = QgsMapLayerComboBox()
        configure_layer_combo(self.planting_line_combo, "VectorLayer")
        form.addRow("Linhas de plantio:", self.planting_line_combo)

        self.plant_headland_cross_combo = QgsMapLayerComboBox()
        configure_layer_combo(self.plant_headland_cross_combo, "VectorLayer")
        form.addRow("Bordadura plantio (opcional):", self.plant_headland_cross_combo)

        self.spray_line_combo = QgsMapLayerComboBox()
        configure_layer_combo(self.spray_line_combo, "VectorLayer")
        self.spray_source_mode_combo = QComboBox()
        self.spray_source_mode_combo.addItem(
            "Linha-base (passadas geradas na etapa 1)",
            SPRAY_CROSS_SOURCE_LINE_BASE,
        )
        self.spray_source_mode_combo.addItem(
            "Passadas existentes (feicoes selecionadas)",
            SPRAY_CROSS_SOURCE_EXISTING_PASSES,
        )
        form.addRow("Origem da pulverizacao:", self.spray_source_mode_combo)
        form.addRow("Camada de pulverizacao:", self.spray_line_combo)

        self.spray_passes_selected_only = QCheckBox(
            "Usar somente as feicoes selecionadas no mapa"
        )
        self.spray_passes_selected_only.setChecked(True)
        form.addRow(self.spray_passes_selected_only)

        self.spray_cross_selection_summary = QLabel("")
        self.spray_cross_selection_summary.setWordWrap(True)
        form.addRow("Selecao da pulverizacao:", self.spray_cross_selection_summary)

        self.pick_spray_pass_btn = QPushButton("Selecionar passada no mapa")
        self.pick_spray_pass_btn.clicked.connect(self._pick_spray_pass_on_map)
        form.addRow(self.pick_spray_pass_btn)

        refresh_spray_selection = QPushButton("Atualizar selecao do mapa")
        refresh_spray_selection.clicked.connect(self._refresh_cross_spray_selection)
        form.addRow(refresh_spray_selection)

        self.spray_headland_cross_combo = QgsMapLayerComboBox()
        configure_layer_combo(self.spray_headland_cross_combo, "VectorLayer")
        form.addRow("Bordadura aplicacao (opcional):", self.spray_headland_cross_combo)

        self.cross_obstacle_combo = QgsMapLayerComboBox()
        configure_layer_combo(self.cross_obstacle_combo, "VectorLayer")
        form.addRow("Obstaculos (opcional):", self.cross_obstacle_combo)

        self.cross_layers_hint = QLabel("")
        self.cross_layers_hint.setWordWrap(True)
        form.addRow("Disponiveis:", self.cross_layers_hint)

        self.use_generated_for_cross = QCheckBox(
            "Usar linhas de plantio geradas nesta sessao"
        )
        self.use_generated_for_cross.setChecked(True)
        form.addRow(self.use_generated_for_cross)

        self.shutoff_tramline_check = QCheckBox(
            "Desligar semente no rastro do pneu (tramline)"
        )
        self.shutoff_tramline_check.setChecked(True)
        form.addRow(self.shutoff_tramline_check)

        self.shutoff_headland_check = QCheckBox(
            "Desligar semente na bordadura interna"
        )
        self.shutoff_headland_check.setChecked(True)
        form.addRow(self.shutoff_headland_check)

        self.cross_result_summary = QLabel("Cruzamento ainda nao calculado.")
        self.cross_result_summary.setWordWrap(True)
        form.addRow("Resultado:", self.cross_result_summary)
        self.operational_state_label = QLabel("Nao calculado")
        self.operational_state_label.setWordWrap(True)
        form.addRow("Estado operacional:", self.operational_state_label)
        self.save_operational_btn = QPushButton("Salvar resultado operacional")
        self.save_operational_btn.setEnabled(False)
        self.save_operational_btn.clicked.connect(self._save_operational_result)
        form.addRow(self.save_operational_btn)
        layout.addLayout(form)

        self.spray_source_mode_combo.currentIndexChanged.connect(
            self._refresh_cross_spray_selection
        )
        self.spray_line_combo.layerChanged.connect(self._refresh_cross_spray_selection)
        self.spray_ab_combo.layerChanged.connect(self._refresh_cross_spray_selection)
        self.spray_ab_selected_only.toggled.connect(self._refresh_cross_spray_selection)
        self.spray_passes_selected_only.toggled.connect(
            self._refresh_cross_spray_selection
        )
        self.planting_line_combo.layerChanged.connect(self._invalidate_operational_draft)
        self._refresh_cross_spray_selection()

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Passada", "Linha/Obst.", "Acao", "Detalhe", "Valor"]
        )
        layout.addWidget(self.table)
        return widget

    def _refresh_cross_spray_selection(self, *_args) -> None:
        mode = self.spray_source_mode_combo.currentData()
        existing_mode = mode == SPRAY_CROSS_SOURCE_EXISTING_PASSES
        self.spray_line_combo.setEnabled(existing_mode)
        self.spray_passes_selected_only.setEnabled(existing_mode)
        if hasattr(self, "cross_result_summary"):
            self.cross_result_summary.setText(
                "Fonte ou selecao alterada; recalcule os cruzamentos."
            )
        self._invalidate_operational_draft()
        if not existing_mode:
            layer = self.spray_ab_combo.currentLayer()
            self._bind_cross_spray_selection_layer(layer)
            if layer is None:
                self.spray_cross_selection_summary.setText(
                    "Linha-base geral da aba 1; gere a aplicacao antes do cruzamento."
                )
            else:
                self.spray_cross_selection_summary.setText(
                    f"Linha-base: {layer.name()} | {self.spray_ab_summary.text()}"
                )
            return
        layer = self.spray_line_combo.currentLayer()
        self._bind_cross_spray_selection_layer(layer)
        if layer is None:
            self.spray_cross_selection_summary.setText(
                "Selecione uma camada linear com passadas reais de pulverizacao."
            )
            return
        selected = layer.selectedFeatureCount()
        total = layer.featureCount()
        self.spray_cross_selection_summary.setText(
            f"{layer.name()} | selecionadas: {selected} de {total} | {layer.crs().authid()}"
        )

    def _pick_spray_pass_on_map(self) -> None:
        index = self.spray_source_mode_combo.findData(SPRAY_CROSS_SOURCE_EXISTING_PASSES)
        if index >= 0:
            self.spray_source_mode_combo.setCurrentIndex(index)
        canvas = self.iface.mapCanvas()
        previous_tool = canvas.mapTool()
        tool = SprayPassPickTool(canvas, preferred_layer=self.spray_line_combo.currentLayer())
        self.spray_pick_tool = tool
        tool.message.connect(lambda text: self.iface.messageBar().pushInfo("FortSmart", text))

        def on_finished(layer):
            if not tool.switched_away and canvas.mapTool() is tool and previous_tool is not None:
                canvas.setMapTool(previous_tool)
            if layer is not None:
                self.spray_line_combo.setLayer(layer)
                self.spray_passes_selected_only.setChecked(True)
            self._refresh_cross_spray_selection()
            self.showNormal()
            self.raise_()
            self.activateWindow()

        tool.finished.connect(on_finished)
        canvas.setMapTool(tool)
        self.iface.messageBar().pushInfo(
            "FortSmart",
            "Clique na passada de pulverizacao. Shift+clique soma passadas "
            "(Enter conclui); Esc cancela.",
        )
        self.showMinimized()

    def _bind_cross_spray_selection_layer(self, layer) -> None:
        previous = getattr(self, "_cross_spray_selection_layer", None)
        if previous is layer:
            return
        if previous is not None:
            try:
                previous.selectionChanged.disconnect(self._refresh_cross_spray_selection)
            except (TypeError, RuntimeError):
                pass
        self._cross_spray_selection_layer = layer
        if isinstance(layer, QgsVectorLayer):
            layer.selectionChanged.connect(self._refresh_cross_spray_selection)

    def _update_workflow_status(self) -> None:
        lr = self.last_result
        if lr is None:
            self.status_plant_chip.setText("Plantio: pendente")
            self.status_spray_chip.setText("Aplicacao: pendente")
            self.status_cross_chip.setText("Cruzamento: aguardando")
            return
        n_plant = len(lr.planting_passes) or len(lr.planting_rows)
        n_spray = len(lr.spraying_passes)
        self.status_plant_chip.setText(
            f"Plantio: {n_plant} passadas" if n_plant else "Plantio: pendente"
        )
        self.status_spray_chip.setText(
            f"Aplicacao: {n_spray} passadas" if n_spray else "Aplicacao: pendente"
        )
        if session_ready_for_cross(lr):
            self.status_cross_chip.setText("Cruzamento: pronto")
        elif n_plant or n_spray:
            self.status_cross_chip.setText("Cruzamento: falta plantio ou aplicacao")
        else:
            self.status_cross_chip.setText("Cruzamento: aguardando")

    def _refresh_all_layer_combos(self, *_args) -> None:
        """Atualiza combos de poligono/linha/obstaculo (QGIS 4 + camadas novas)."""
        try:
            n_poly = refresh_polygon_layer_combo(self.field_combo)
            prefer_metric_polygon_layer(self.field_combo)
            self._on_field_changed(self.field_combo.currentLayer())
        except Exception:
            n_poly = 0
        try:
            n_line = refresh_line_layer_combo(self.ab_layer_combo)
            if hasattr(self, "ab_layers_hint"):
                if n_line == 0:
                    self.ab_layers_hint.setText(
                        "Nenhuma camada de LINHA no projeto. "
                        "Carregue um SHP/GPKG de linha A-B (ou curva) no QGIS, "
                        "ou use 'Capturar A-B no mapa'. "
                        "Camadas de poligono (LIMITE/Boundary) nao aparecem aqui."
                    )
                else:
                    self.ab_layers_hint.setText(
                        f"{n_line} camada(s) de linha disponivel(is). "
                        "Selecione e clique 'Usar linha da camada / selecao'."
                    )
        except Exception:
            n_line = 0
        try:
            self._refresh_operation_layer_combos()
        except Exception:
            pass
        try:
            self._refresh_obstacle_layers()
        except Exception:
            pass
        _ = n_poly

    def _refresh_operation_layer_combos(self) -> None:
        """Atualiza combos de bordadura/linhas em Aplicacao, Plantio e Cruzamento."""
        n_plant_line = n_spray_line = n_poly = n_obs = 0
        if getattr(self, "plant_line_combo", None) is not None:
            n_plant_line = refresh_line_layer_combo(self.plant_line_combo)
        if getattr(self, "planting_line_combo", None) is not None:
            n_plant_line = refresh_line_layer_combo(self.planting_line_combo)
        if getattr(self, "spray_ab_combo", None) is not None:
            self._refresh_ab_reference_combo(self.spray_ab_combo)
        if getattr(self, "plant_ab_combo", None) is not None:
            self._refresh_ab_reference_combo(self.plant_ab_combo)
        if getattr(self, "spray_pass_combo", None) is not None:
            n_spray_line = refresh_line_layer_combo(self.spray_pass_combo)
        if getattr(self, "spray_line_combo", None) is not None:
            n_spray_line = refresh_line_layer_combo(self.spray_line_combo)
        if getattr(self, "plant_headland_combo", None) is not None:
            n_poly = refresh_polygon_layer_combo(self.plant_headland_combo)
        if getattr(self, "spray_headland_combo", None) is not None:
            n_poly = refresh_polygon_layer_combo(self.spray_headland_combo)
        if getattr(self, "plant_headland_cross_combo", None) is not None:
            refresh_polygon_layer_combo(self.plant_headland_cross_combo)
        if getattr(self, "spray_headland_cross_combo", None) is not None:
            refresh_polygon_layer_combo(self.spray_headland_cross_combo)
        if getattr(self, "cross_obstacle_combo", None) is not None:
            n_obs = refresh_obstacle_layer_combo(self.cross_obstacle_combo)

        if getattr(self, "plant_layers_hint", None) is not None:
            self.plant_layers_hint.setText(
                f"Linhas: {n_plant_line} | Poligonos (bordadura): {n_poly}. "
                "Selecione bordadura e linhas de plantio, ou gere com o botao 2."
            )
        if getattr(self, "spray_layers_hint", None) is not None:
            self.spray_layers_hint.setText(
                f"Passadas: {n_spray_line} | Poligonos (bordadura): {n_poly}. "
                "Selecione bordadura e linhas de pulverizacao, ou gere com o botao 1."
            )
        if getattr(self, "cross_layers_hint", None) is not None:
            self.cross_layers_hint.setText(
                f"Plantio linhas: {n_plant_line} | Spray linhas: {n_spray_line} | "
                f"Bordaduras (poligono): {n_poly} | Obstaculos: {n_obs}. "
                "Ou marque 'Usar resultado gerado nesta sessao'."
            )

    @staticmethod
    def _refresh_ab_reference_combo(combo) -> None:
        """A-B opcional: lista so linhas que nao sao passadas geradas; nunca troca por outra linha.

        Camada que nem e linha volta a vazio (A-B da aba 1). Uma passada gerada
        escolhida continua visivel para a geracao recusar com aviso.
        """
        current = combo.currentLayer()
        if current is not None and not is_line_like_vector_layer(current):
            current = None
        configure_layer_combo(combo, "VectorLayer")
        layers = list(QgsProject.instance().mapLayers().values())
        excepted = [
            layer for layer in layers
            if layer is not current
            and (not is_line_like_vector_layer(layer) or ab_source_rejection_reason(layer) is not None)
        ]
        try:
            combo.setExceptedLayerList(excepted)
        except Exception:
            pass
        if combo.currentLayer() is not current:
            try:
                combo.setLayer(current)
            except Exception:
                pass

    def _refresh_obstacle_layers(self, *_args) -> None:
        # Sempre liberar controles — desvio e camada sao opcionais e livres.
        for widget in (
            getattr(self, "obstacle_combo", None),
            getattr(self, "enable_avoidance", None),
            getattr(self, "obs_radius_spin", None),
            getattr(self, "spray_margin_spin", None),
            getattr(self, "use_selected_obstacles", None),
            getattr(self, "apply_avoidance_btn", None),
        ):
            if widget is not None:
                widget.setEnabled(True)

        count = refresh_obstacle_layer_combo(self.obstacle_combo)
        prefer_nonempty_obstacle_layer(self.obstacle_combo)
        if count == 0:
            self.obstacle_layers_hint.setText(
                "Nenhuma camada vetorial de obstaculo encontrada. "
                "Carregue SHP/GPKG de pontos, linhas ou poligonos "
                "(Postes, Pedras, Dutovia, exclusao) e clique "
                "'Atualizar lista de camadas'."
            )
        else:
            self.obstacle_layers_hint.setText(
                f"{count} camada(s) de obstaculo disponivel(is) "
                "(ponto, linha ou poligono). Selecione a correta."
            )
        self._on_obstacle_layer_changed(self.obstacle_combo.currentLayer())

    def _on_project_layers_changed(self, *_args) -> None:
        self._refresh_all_layer_combos()

    def _on_tab_changed(self, index: int) -> None:
        if index == getattr(self, "_tab_idx_obstacles", 3):
            self._refresh_obstacle_layers()
        elif index == getattr(self, "_tab_idx_field", 0):
            self._refresh_all_layer_combos()
        elif index == getattr(self, "_tab_idx_sprayer", 1):
            self._refresh_operation_layer_combos()
        elif index == getattr(self, "_tab_idx_planter", 2):
            self._refresh_operation_layer_combos()
        elif index == getattr(self, "_tab_idx_cross", 4):
            self._refresh_operation_layer_combos()

    def showEvent(self, event: QEvent) -> None:
        super().showEvent(event)
        self._refresh_all_layer_combos()

    def _on_obstacle_layer_changed(self, layer) -> None:
        # Nunca desabilitar o checkbox — o usuario escolhe quando ativar.
        if getattr(self, "enable_avoidance", None) is not None:
            self.enable_avoidance.setEnabled(True)
        if getattr(self, "obstacle_combo", None) is not None:
            self.obstacle_combo.setEnabled(True)

        if layer is None:
            self.obstacle_layer_info.setText(
                "Nenhuma camada selecionada — carregue pontos/linhas/poligonos e atualize."
            )
            return
        n_feat = int(layer.featureCount() or 0)
        crs = layer.crs().authid() if layer.crs().isValid() else "?"
        kind = geometry_type_label(layer)
        if n_feat <= 0:
            self.obstacle_layer_info.setText(
                f"{layer.name()} [{crs}] ({kind}) — 0 feicoes (camada VAZIA). "
                "Escolha outra camada ou carregue o SHP dos obstaculos."
            )
            self.obstacle_layer_info.setStyleSheet("color: #b00020;")
        else:
            extra = ""
            if is_point_like_vector_layer(layer) or is_line_like_vector_layer(layer):
                extra = " Informe o raio fisico."
            self.obstacle_layer_info.setText(
                f"{layer.name()} [{crs}] — {n_feat} feicao(oes) ({kind})."
                f"{extra} Marque 'Ativar desvio' e use o botao 3, ou regenere 1/2."
            )
            self.obstacle_layer_info.setStyleSheet("color: #1b5e20;")

    def _capture_ab(self) -> None:
        canvas = self.iface.mapCanvas()
        self.previous_map_tool = canvas.mapTool()
        self.capture_tool = CaptureABLineTool(canvas)
        self.ab_label.setText("Clique o ponto A, depois o ponto B no mapa...")
        QMessageBox.information(
            self,
            "Capturar A-B",
            "A ferramenta esta ativa no mapa.\n"
            "1) Clique o ponto A\n"
            "2) Clique o ponto B\n"
            "Esc cancela.",
        )

        def on_line(a, b):
            self._set_captured_ab(a, b)
            self.showNormal()
            self.raise_()
            if self.previous_map_tool is not None:
                canvas.setMapTool(self.previous_map_tool)

        self.capture_tool.lineCaptured.connect(on_line)
        canvas.setMapTool(self.capture_tool)
        self.showMinimized()

    def _load_ab_from_layer(self) -> None:
        layer = self.ab_layer_combo.currentLayer()
        if layer is None or not isinstance(layer, QgsVectorLayer):
            QMessageBox.warning(self, "A-B", "Selecione uma camada de linha (SHP, GPKG, curva...).")
            return

        if layer.geometryType() != QgsWkbTypes.LineGeometry:
            QMessageBox.warning(
                self,
                "A-B",
                f"A camada '{layer.name()}' nao e de linha "
                f"(tipo={QgsWkbTypes.geometryDisplayString(layer.geometryType())}).",
            )
            return
        rejection = ab_source_rejection_reason(layer)
        if rejection:
            QMessageBox.warning(self, "A-B", rejection)
            return

        features = []
        if self.use_selected_ab.isChecked() and layer.selectedFeatureCount() > 0:
            features = list(layer.selectedFeatures())
        if not features:
            features = list(layer.getFeatures())
        if not features:
            QMessageBox.warning(self, "A-B", "Camada sem feicoes de linha.")
            return

        # Escolhe a linha mais longa (evita feicao degenerada A=B).
        best_points = None
        best_len = -1.0
        for feat in features:
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue
            pts = extract_line_vertices(geom)
            if len(pts) < 2:
                continue
            length = 0.0
            for a, b in zip(pts, pts[1:]):
                length += ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
            if length > best_len:
                best_len = length
                best_points = pts

        if best_points is None or len(best_points) < 2:
            QMessageBox.warning(
                self,
                "A-B",
                "Nao foi possivel ler vertices da linha.\n"
                "Verifique se e LineString, MultiLineString ou curva valida.",
            )
            return

        points = best_points
        if len(points) > 400:
            points = decimate_polyline(points, min_step_m=2.0, max_points=400)
        auth = layer.crs().authid() if layer.crs().isValid() else ""
        min_span = 1e-5 if auth in ("EPSG:4326", "EPSG:4674") else 0.5
        dx = points[-1][0] - points[0][0]
        dy = points[-1][1] - points[0][1]
        span = (dx * dx + dy * dy) ** 0.5
        if span < min_span and best_len < min_span:
            QMessageBox.warning(
                self,
                "A-B invalida",
                f"A linha em '{layer.name()}' tem comprimento ~0 "
                f"(A e B iguais: {points[0]} → {points[-1]}, CRS {auth}).\n\n"
                "Use uma camada de linha A-B real (reta ou curva no talhao), "
                "nao uma passada de pulverizacao com ponto unico.\n"
                "Ou capture A-B no mapa com dois cliques separados "
                "(preferivel com o projeto em EPSG:31981 / SIRGAS 2000 UTM).",
            )
            self.ab_start = None
            self.ab_end = None
            self.ab_path_points = ()
            self.ab_label.setText("A-B invalida — capture novamente ou escolha outra linha")
            return

        # Alinha A-B ao CRS do talhao automaticamente (sem popup bloqueante).
        field = self.field_combo.currentLayer()
        ab_crs = layer.crs()
        note = ""
        if (
            field is not None
            and isinstance(field, QgsVectorLayer)
            and field.crs().isValid()
            and ab_crs.isValid()
            and normalize_authid(field.crs().authid()) != normalize_authid(ab_crs.authid())
        ):
            try:
                from qgis.core import QgsCoordinateTransform, QgsPointXY

                transform = QgsCoordinateTransform(ab_crs, field.crs(), QgsProject.instance())
                converted = []
                for x, y in points:
                    pt = transform.transform(QgsPointXY(x, y))
                    converted.append((pt.x(), pt.y()))
                if len(converted) >= 2:
                    points = converted
                    ab_crs = field.crs()
                    auth = ab_crs.authid() or auth
                    note = f" [convertida → {auth}]"
            except Exception:
                note = " [CRS diferente do talhao — conversao na geracao]"

        if not self._apply_ab_polyline(
            points,
            ab_crs,
            label=f"A-B '{layer.name()}'{note}",
        ):
            return

    def _set_captured_ab(self, start, end) -> None:
        ax, ay = float(start.x()), float(start.y())
        bx, by = float(end.x()), float(end.y())
        dx, dy = bx - ax, by - ay
        # Distancia no CRS do canvas; se geografico, ~graus.
        span = (dx * dx + dy * dy) ** 0.5
        canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        auth = canvas_crs.authid() if canvas_crs else ""
        min_span = 1e-5 if auth in ("EPSG:4326", "EPSG:4674") else 0.5
        if span < min_span:
            QMessageBox.warning(
                self,
                "A-B invalida",
                "Os pontos A e B estao iguais (ou quase). "
                "Capture de novo com dois cliques bem separados no talhao.\n"
                "Dica: use o mapa com CRS UTM (EPSG:31981) para capturar em metros.",
            )
            self.ab_label.setText("A-B invalida — capture novamente")
            return
        self.ab_start = (ax, ay)
        self.ab_end = (bx, by)
        self.ab_path_points = (self.ab_start, self.ab_end)
        self.ab_source_crs = canvas_crs
        self.guidance_reference = GuidanceReference.from_ab(self.ab_start, self.ab_end)
        crs_txt = auth or "?"
        if abs(ax) <= 180 and abs(ay) <= 90:
            fmt = ".6f"
        else:
            fmt = ".2f"
        self.ab_label.setText(
            f"A-B capturada ({crs_txt}) "
            f"({ax:{fmt}}, {ay:{fmt}}) → ({bx:{fmt}}, {by:{fmt}})"
        )
        field = self.field_combo.currentLayer()
        if field is not None:
            warning = explain_ab_mismatch(
                field.crs().authid(),
                ax,
                ay,
                ab_crs_authid=crs_txt,
            )
            if warning:
                QMessageBox.warning(self, "FortSmart — CRS", warning)

    def _build_obstacles(
        self,
        target_crs,
        *,
        layer=None,
        required: bool = False,
        obstacle_radius_m: float | None = None,
        safety_margin_m: float | None = None,
    ):
        """Le obstaculos de ponto, linha (buffer) ou poligono."""
        obstacles = []
        radius_value = (
            self.obs_radius_spin.value() if obstacle_radius_m is None else float(obstacle_radius_m)
        )
        margin_value = (
            self.spray_margin_spin.value() if safety_margin_m is None else float(safety_margin_m)
        )
        if not self.enable_avoidance.isChecked() and layer is None and not required:
            return obstacles

        obs_layer = layer if layer is not None else self.obstacle_combo.currentLayer()
        if obs_layer is None:
            if required:
                raise ValueError(
                    "Desvio ativo: selecione a camada de obstaculos na aba 4 "
                    "(pontos, linhas ou poligonos — Postes, Pedras, Dutovia, etc.)."
                )
            return obstacles

        geom_type = obs_layer.geometryType()
        line_buffer_m = radius_value
        # Linha sem raio informado: segue a geometria da linha (buffer minimo tecnico).
        if geom_type == QgsWkbTypes.LineGeometry and line_buffer_m <= 0:
            line_buffer_m = max(0.05, margin_value * 0.05)

        use_selected = (
            getattr(self, "use_selected_obstacles", None) is not None
            and self.use_selected_obstacles.isChecked()
            and obs_layer.selectedFeatureCount() > 0
            and layer is None
        )
        feature_iter = obs_layer.selectedFeatures() if use_selected else obs_layer.getFeatures()

        layer_name = obs_layer.name().strip() or "Obstaculo"
        from qgis.core import QgsCoordinateTransform

        transform = None
        if obs_layer.crs() != target_crs:
            transform = QgsCoordinateTransform(
                obs_layer.crs(), target_crs, QgsProject.instance()
            )

        point_index = 0
        for feat in feature_iter:
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue
            work = QgsGeometry(geom)
            if transform is not None:
                try:
                    work.transform(transform)
                except Exception:
                    continue

            feat_name = ""
            for field in ("nome", "name", "tipo", "type", "id"):
                if field in feat.fields().names():
                    value = feat.attribute(field)
                    if value not in (None, ""):
                        feat_name = str(value)
                        break

            feat_id = feat.id() if feat.id() >= 0 else point_index + 1

            if work.type() == QgsWkbTypes.PointGeometry:
                points = extract_points_from_geometry(work)
                for pt_index, point in enumerate(points, start=1):
                    point_index += 1
                    suffix = (
                        f"{feat_name}-{pt_index}" if feat_name and len(points) > 1 else feat_name
                    )
                    label = (
                        f"{layer_name}-{suffix}" if suffix else f"{layer_name}-{point_index}"
                    )
                    obstacles.append(
                        obstacle_from_point(
                            point,
                            obstacle_radius_m=radius_value,
                            safety_margin_m=margin_value,
                            name=label,
                            obstacle_id=(
                                f"{layer_name}_{feat_id}"
                                f"_{pt_index if len(points) > 1 else 0}"
                            ),
                        )
                    )
                continue

            if work.type() == QgsWkbTypes.LineGeometry:
                radius = line_buffer_m
                buffered = work.buffer(radius, 16)
                if buffered is None or buffered.isEmpty():
                    continue
                work = buffered

            if work.type() != QgsWkbTypes.PolygonGeometry:
                continue

            try:
                polygons = qgs_geometry_to_multipolygon(work)
            except Exception:
                continue
            for poly_index, polygon in enumerate(polygons, start=1):
                point_index += 1
                suffix = (
                    f"{feat_name}-{poly_index}"
                    if feat_name and len(polygons) > 1
                    else feat_name
                )
                label = f"{layer_name}-{suffix}" if suffix else f"{layer_name}-{point_index}"
                obstacles.append(
                    obstacle_from_polygon(
                        polygon,
                        obstacle_radius_m=0.0,
                        safety_margin_m=margin_value,
                        name=label,
                        obstacle_id=f"{layer_name}_{feat_id}_{poly_index}",
                    )
                )

        if not obstacles:
            detail = "selecao vazia" if use_selected else "0 feicoes validas"
            message = (
                f"Camada '{layer_name}' nao tem geometrias utilizaveis ({detail}). "
                "Use ponto (com raio), linha (com raio → buffer) ou poligono."
            )
            if required:
                raise ValueError(message)
            return obstacles
        return obstacles


    def _refresh_spray_ab_summary(self, *_args) -> None:
        layer = self.spray_ab_combo.currentLayer()
        if layer is None:
            self.spray_ab_summary.setText(
                "Nenhuma: sera usada a referencia geral da aba 1."
            )
            return
        if not isinstance(layer, QgsVectorLayer) or layer.geometryType() != QgsWkbTypes.LineGeometry:
            self.spray_ab_summary.setText("Camada invalida: selecione uma camada linear.")
            return
        selected = layer.selectedFeatureCount()
        total = layer.featureCount()
        if self.spray_ab_selected_only.isChecked():
            if selected == 1:
                feature_id = layer.selectedFeatures()[0].id()
                self.spray_ab_summary.setText(
                    f"{layer.name()} | feicao selecionada ID {feature_id} | {layer.crs().authid()}"
                )
            else:
                self.spray_ab_summary.setText(
                    f"{layer.name()} | selecione exatamente 1 feicao (selecionadas: {selected})."
                )
            return
        if total == 1:
            feature_id = next(layer.getFeatures()).id()
            self.spray_ab_summary.setText(
                f"{layer.name()} | unica feicao ID {feature_id} | {layer.crs().authid()}"
            )
        else:
            self.spray_ab_summary.setText(
                f"{layer.name()} possui {total} feicoes. Selecione uma e marque a opcao acima."
            )

    def _ab_snapshot_from_layer(
        self,
        layer,
        *,
        selected_only: bool = False,
        require_single: bool = False,
    ):
        """Le vertices A-B de uma camada de linha (sem exigir botao da aba 1)."""
        if layer is None or not isinstance(layer, QgsVectorLayer):
            return None
        if layer.geometryType() != QgsWkbTypes.LineGeometry:
            return None
        features = []
        use_sel = getattr(self, "use_selected_ab", None)
        if selected_only:
            if layer.selectedFeatureCount() != 1:
                raise ValueError(
                    "Selecione exatamente uma feicao na camada da linha-base de pulverizacao."
                )
            features = list(layer.selectedFeatures())
        elif require_single:
            features = list(layer.getFeatures())
            if len(features) != 1:
                raise ValueError(
                    "A camada da linha-base possui varias feicoes. Selecione uma feicao "
                    "no QGIS e marque 'Usar somente a feicao selecionada'."
                )
        elif use_sel is not None and use_sel.isChecked() and layer.selectedFeatureCount() > 0:
            features = list(layer.selectedFeatures())
        if not features:
            features = list(layer.getFeatures())
        best_points = None
        best_len = -1.0
        for feat in features:
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue
            pts = extract_line_vertices(geom)
            if len(pts) < 2:
                continue
            length = 0.0
            for a, b in zip(pts, pts[1:]):
                length += ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
            if length > best_len:
                best_len = length
                best_points = pts
        if best_points is None or len(best_points) < 2:
            return None
        points = list(best_points)
        if len(points) > 400:
            points = list(decimate_polyline(points, min_step_m=2.0, max_points=400))
        return {
            "start": points[0],
            "end": points[-1],
            "path": tuple(points),
            "crs": layer.crs(),
            "layer_name": layer.name(),
            "feature_id": features[0].id() if len(features) == 1 else None,
        }

    def _activate_ab_for_operation(self, operation: str) -> None:
        """Plantio e pulverizacao podem usar A-B diferentes (combos opcionais)."""
        combo = None
        if operation == "spraying":
            combo = getattr(self, "spray_ab_combo", None)
        elif operation == "planting":
            combo = getattr(self, "plant_ab_combo", None)
        layer = combo.currentLayer() if combo is not None else None
        if layer is None:
            return
        rejection = ab_source_rejection_reason(layer)
        if rejection:
            raise ValueError(
                f"{rejection} Escolha a A-B original no combo opcional de {operation} "
                "ou deixe-o vazio para usar a A-B da aba 1."
            )
        selected_only = bool(
            operation == "spraying"
            and getattr(self, "spray_ab_selected_only", None) is not None
            and self.spray_ab_selected_only.isChecked()
        )
        snap = self._ab_snapshot_from_layer(
            layer,
            selected_only=selected_only,
            require_single=(operation == "spraying" and not selected_only),
        )
        if snap is None:
            raise ValueError(
                f"A-B opcional de {operation} invalida na camada '{layer.name()}'. "
                "Escolha outra linha ou deixe o combo vazio para usar a A-B da aba 1."
            )
        points = list(snap["path"])
        ab_crs = snap["crs"]
        field = self.field_combo.currentLayer()
        if (
            field is not None
            and isinstance(field, QgsVectorLayer)
            and field.crs().isValid()
            and ab_crs.isValid()
            and normalize_authid(field.crs().authid()) != normalize_authid(ab_crs.authid())
        ):
            try:
                from qgis.core import QgsCoordinateTransform, QgsPointXY

                transform = QgsCoordinateTransform(ab_crs, field.crs(), QgsProject.instance())
                converted = []
                for x, y in points:
                    pt = transform.transform(QgsPointXY(x, y))
                    converted.append((pt.x(), pt.y()))
                if len(converted) >= 2:
                    points = converted
                    ab_crs = field.crs()
            except Exception:
                pass
        if not self._apply_ab_polyline(
            points,
            ab_crs,
            label=f"A-B {operation} '{snap['layer_name']}'",
        ):
            raise ValueError(
                f"A-B de {operation} invalida na camada '{snap['layer_name']}'. "
                "Use uma linha aberta com pelo menos dois pontos separados."
            )

    def _build_project(
        self,
        *,
        include_planting: bool,
        include_spraying: bool,
        require_obstacles: bool = False,
    ) -> PrecisionProject:
        layer = self.field_combo.currentLayer()
        if layer is None:
            raise ValueError("Selecione a camada do perimetro/talhao.")
        if self.ab_start is None or self.ab_end is None:
            raise ValueError("Defina a linha A-B (captura no mapa ou camada de linha).")
        if not include_planting and not include_spraying:
            raise ValueError("Ative plantio e/ou pulverizacao.")

        ab_crs = self.ab_source_crs or layer.crs()
        ctx = prepare_workspace_metric_context(
            layer,
            self.ab_start,
            self.ab_end,
            ab_path_points=self.ab_path_points,
            ab_source_crs=ab_crs,
            selected_features_only=self.use_selected_field.isChecked(),
        )
        # A-B precisa ter comprimento real ja no CRS metrico de trabalho.
        dx = ctx.ab_end[0] - ctx.ab_start[0]
        dy = ctx.ab_end[1] - ctx.ab_start[1]
        if (dx * dx + dy * dy) ** 0.5 < 0.5:
            raise ValueError(
                "Linha A-B invalida (comprimento ~0 m no CRS de trabalho "
                f"{ctx.crs_authid}). Capture A e B separados no mapa, ou carregue "
                "uma linha A-B real (nao use passada degenerada)."
            )
        self.work_crs_authid = ctx.crs_authid
        target_crs = QgsCoordinateReferenceSystem(ctx.crs_authid)

        # NUNCA unaryUnion de todas as feicoes: bbox+pivo vira quadrado.
        picked = pick_field_qgs_geometry(
            ctx.field_geometries,
            ab_start=ctx.ab_start,
            ab_end=ctx.ab_end,
        )
        operational = qgs_geometry_to_multipolygon(picked)
        assert_not_degenerate_field(operational)
        field_boundary = operational
        n_verts = vertex_count(picked)
        if n_verts < 8:
            # Aviso nao bloqueante via summary — pivo tipico tem dezenas de vertices.
            pass

        planting = None
        kinematics = None
        planting_avoidance = PlantingAvoidanceConfiguration(enabled=False)
        if include_planting:
            planter = self.planter_widget.build_machine()
            width = planter.operational_width_m
            headland_n = self.planter_widget.headland_pass_count()
            planting = PrecisionOperation(
                operation_id="planting",
                machine=planter,
                headland=HeadlandLayout(
                    pass_count=headland_n,
                    width_m=width if headland_n > 0 else 0.0,
                    effective_spacing_m=width if headland_n > 0 else None,
                    mode="follow_boundary" if headland_n > 0 else "none",
                    corner_mode=self.planter_widget.headland_corner_mode(),
                    headland_mode=self.planter_widget.headland_mode(),
                ),
                extension_m=self.planter_widget.extension_m(),
            )
            turn_r = self.planter_widget.turn_radius_m()
            kinematics = PlantingKinematics(
                operational_width_m=width,
                track_width_m=0.0,
                hitch_distance_m=self.planter_widget.hitch_distance_m(),
                minimum_turn_radius_m=turn_r,
                row_count=planter.row_count,
                row_spacing_m=planter.row_spacing_m,
            )
            planting_avoidance = PlantingAvoidanceConfiguration(
                strategy=PlantingAvoidanceStrategy(self.strategy_combo.currentData()),
                inner_margin_m=self.inner_margin_spin.value(),
                outer_margin_m=self.outer_margin_spin.value(),
                merge_obstacles_m=self.merge_spin.value(),
                minimum_turn_radius_m=turn_r,
                enabled=False,
            )

        spraying = None
        sprayer_turn_radius = self._sprayer_turn_radius_m()
        spray_config = AvoidanceConfiguration(
            mode=AvoidanceMode.NONE,
            minimum_turn_radius_m=sprayer_turn_radius,
        )
        spray_avoid_requested = include_spraying and self._spray_avoidance_requested()
        if spray_avoid_requested and sprayer_turn_radius is None:
            raise ValueError(
                "Desvio na pulverizacao ativo: informe o raio minimo de giro do "
                "pulverizador na aba 4 (o raio da plantadeira nao e usado)."
            )
        spray_turn_mode = SPRAY_HEADLAND_TURN_MANUAL
        if include_spraying:
            spray_turn_mode = self.sprayer_widget.spray_headland_turn_mode()
        spray_auto_turns = spray_turn_mode == SPRAY_HEADLAND_TURN_AUTOMATIC
        if spray_auto_turns and sprayer_turn_radius is None:
            raise ValueError(
                "Cabeceira 'Manobra automatica': informe o raio minimo de giro do "
                "pulverizador na aba 4 > Pulverizacao (o raio da plantadeira nao e usado)."
            )
        if include_spraying:
            sprayer = self.sprayer_widget.build_machine()
            if sprayer_turn_radius is not None:
                sprayer = replace(sprayer, sprayer_minimum_turn_radius_m=sprayer_turn_radius)
            spraying = PrecisionOperation(
                operation_id="spraying",
                machine=sprayer,
                # Meia barra FISICA + passo efetivo (barra - transpasse) + faixa para fora.
                headland=self.sprayer_widget.build_headland_layout(sprayer),
                extension_m=self.sprayer_widget.extension_m(),
            )

        obstacles = self._build_obstacles(target_crs, required=require_obstacles)
        if spray_avoid_requested and not include_planting:
            obstacles = self._build_obstacles(
                target_crs,
                required=True,
                obstacle_radius_m=self.spray_obstacle_radius_spin.value(),
                safety_margin_m=self.spray_safety_margin_spin.value(),
            )
        elif spray_auto_turns and not include_planting and not obstacles:
            # So para a curva nao cruzar zona de seguranca; o desvio segue desligado.
            obstacle_layer = self.obstacle_combo.currentLayer()
            if obstacle_layer is not None:
                obstacles = self._build_obstacles(
                    target_crs,
                    layer=obstacle_layer,
                    obstacle_radius_m=self.spray_obstacle_radius_spin.value(),
                    safety_margin_m=self.spray_safety_margin_spin.value(),
                )
        avoidance_on = project_avoidance_enabled(
            user_enabled=self.enable_avoidance.isChecked(),
            obstacle_count=len(obstacles),
        )
        if include_planting and avoidance_on:
            planting_avoidance = PlantingAvoidanceConfiguration(
                strategy=PlantingAvoidanceStrategy(self.strategy_combo.currentData()),
                inner_margin_m=self.inner_margin_spin.value(),
                outer_margin_m=self.outer_margin_spin.value(),
                merge_obstacles_m=self.merge_spin.value(),
                minimum_turn_radius_m=self.planter_widget.turn_radius_m(),
                enabled=True,
            )
        if include_spraying and (avoidance_on or (spray_avoid_requested and obstacles)):
            spray_config = self._spray_avoidance_configuration()

        guidance = None
        if self.guidance_reference is not None:
            full_path = tuple(ctx.ab_path_points) if len(ctx.ab_path_points) >= 2 else (ctx.ab_start, ctx.ab_end)
            guidance = GuidanceReference(
                mode=self.guidance_reference.mode,
                start=ctx.ab_start,
                end=ctx.ab_end,
                # Geometria mestra completa (curva preservada).
                control_points=full_path
                if self.guidance_reference.mode != GuidanceMode.STRAIGHT
                else (),
            )

        note = ""
        if ctx.source_was_geographic:
            note = f" (reprojetado para {ctx.crs_authid})"
        self.field_crs_info.setText(f"Trabalho metrico: {ctx.crs_authid}{note}")

        turn_mode = "extend"
        if include_planting:
            turn_mode = self.planter_widget.headland_turn_mode()

        return PrecisionProject(
            field=FieldGeometry(
                field_boundary=field_boundary,
                operational_boundary=operational,
                crs_authid=ctx.crs_authid,
            ),
            ab_line=ABLine(
                start=ctx.ab_start,
                end=ctx.ab_end,
                path_points=tuple(ctx.ab_path_points)
                if len(ctx.ab_path_points) >= 2
                else (),
            ),
            planting=planting,
            spraying=spraying,
            obstacles=tuple(obstacles),
            avoidance=spray_config,
            planting_avoidance=planting_avoidance,
            planting_kinematics=kinematics,
            guidance_reference=guidance,
            shutoff_on_tramlines=self.shutoff_tramline_check.isChecked(),
            shutoff_on_headland_inner=self.shutoff_headland_check.isChecked(),
            headland_turn_mode=turn_mode,
            processing=self._processing_profile(),
            spray_headland_turn_mode=spray_turn_mode,
        )

    def _on_processing_mode_changed(self) -> None:
        profile = self._processing_profile()
        if profile.is_preview:
            self.processing_mode_hint.setText(
                "Precisao geometrica preservada; shutoff e linhas virtuais so no modo Final."
            )
        else:
            self.processing_mode_hint.setText(
                "Geometria completa: shutoff, linhas virtuais e validacao total."
            )

    def _processing_profile(self):
        """Perfil de processamento escolhido na GUI (Rapido x Precisao)."""
        from ..domain.processing_profile import final_profile, profile_from_mode

        combo = getattr(self, "processing_mode_combo", None)
        if combo is None:
            return final_profile()
        try:
            return profile_from_mode(combo.currentData())
        except Exception:
            return final_profile()

    def _generate_application(self) -> None:
        try:
            if self.isMinimized():
                self.showNormal()
            self._set_generation_busy(True)
            self._pulse_generation_status(
                "Gerando aplicacao... a barra mostra o progresso. "
                "Em talhoes grandes pode levar 15–60 s."
            )
            t0 = time.perf_counter()
            self._ensure_workspace_layers_metric(silent=True)
            if self.ab_start is None or self.ab_end is None:
                raise ValueError(
                    "Defina a linha A-B na aba 1 (Capturar no mapa OU "
                    "selecione a camada e clique em 'Usar linha da camada / selecao')."
                )
            self._activate_ab_for_operation("spraying")
            project = self._build_project(include_planting=False, include_spraying=True)
            self._maybe_warn_heavy_avoidance(project)
            result = self._run_precision_lines_job(
                project,
                title="FortSmart — Gerando aplicacao",
                status_message="Gerando aplicacao...",
            )
            if self.last_result is not None:
                result = PrecisionLinesResult(
                    project=project,
                    boundary=result.boundary or self.last_result.boundary,
                    planting_passes=self.last_result.planting_passes,
                    planting_rows=self.last_result.planting_rows,
                    spraying_passes=result.spraying_passes,
                    tramline_zones=result.tramline_zones,
                    shutoff_segments=self.last_result.shutoff_segments,
                    shutoff_table=self.last_result.shutoff_table,
                    avoided_paths=_merge_avoided_paths_by_operation(
                        result.avoided_paths, self.last_result.avoided_paths
                    ),
                    obstacle_envelopes=result.obstacle_envelopes or self.last_result.obstacle_envelopes,
                    avoidance_table=list(result.avoidance_table) + list(self.last_result.avoidance_table),
                    planting_avoidance_results=self.last_result.planting_avoidance_results,
                    forbidden_regions=self.last_result.forbidden_regions or result.forbidden_regions,
                    validation=result.validation,
                    spraying_boundary=result.spraying_boundary,
                    tire_tracks=result.tire_tracks,
                    tractor_axes=self.last_result.tractor_axes,
                    spray_avoidance_records=result.spray_avoidance_records,
                    spray_headland_turns=result.spray_headland_turns,
                )
            self._require_visible_geometry(
                result,
                need_spray=True,
                step="aplicacao",
            )
            self.last_result = result
            self._show_result(
                result,
                step="Aplicacao gerada",
                elapsed_s=time.perf_counter() - t0,
            )
            self._select_preview_layers_in_cross_combos(for_planting=False, for_spraying=True)
            self._update_workflow_status()
            self._announce_generation(result, "Aplicacao")
        except Exception as exc:
            if self.isMinimized():
                self.showNormal()
            self._warn_crs_error(exc)
        finally:
            self._set_generation_busy(False)
            self.generation_progress.hide()

    def _generate_planting(self) -> None:
        try:
            if self.isMinimized():
                self.showNormal()
            self._set_generation_busy(True)
            self._pulse_generation_status(
                "Gerando plantio... acompanhe a barra de progresso. "
                "Plantadeiras com muitas linhas podem levar 20–90 s."
            )
            t0 = time.perf_counter()
            self._ensure_workspace_layers_metric(silent=True)
            if self.ab_start is None or self.ab_end is None:
                raise ValueError(
                    "Defina a linha A-B na aba 1 (Capturar no mapa OU "
                    "selecione a camada e clique em 'Usar linha da camada / selecao')."
                )
            self._activate_ab_for_operation("planting")
            project = self._build_project(include_planting=True, include_spraying=False)
            self._maybe_warn_heavy_avoidance(project)
            result = self._run_precision_lines_job(
                project,
                title="FortSmart — Gerando plantio",
                status_message="Gerando plantio...",
            )
            if self.last_result is not None:
                result = PrecisionLinesResult(
                    project=project,
                    boundary=result.boundary or self.last_result.boundary,
                    planting_passes=result.planting_passes,
                    planting_rows=result.planting_rows,
                    spraying_passes=self.last_result.spraying_passes,
                    tramline_zones=self.last_result.tramline_zones,
                    shutoff_segments=[],
                    shutoff_table=[],
                    avoided_paths=_merge_avoided_paths_by_operation(
                        result.avoided_paths, self.last_result.avoided_paths
                    ),
                    obstacle_envelopes=result.obstacle_envelopes or self.last_result.obstacle_envelopes,
                    avoidance_table=result.avoidance_table + list(self.last_result.avoidance_table),
                    planting_avoidance_results=result.planting_avoidance_results,
                    forbidden_regions=result.forbidden_regions,
                    validation=result.validation,
                    spraying_boundary=self.last_result.spraying_boundary,
                    tire_tracks=self.last_result.tire_tracks,
                    tractor_axes=result.tractor_axes,
                    spray_avoidance_records=self.last_result.spray_avoidance_records,
                    spray_headland_turns=self.last_result.spray_headland_turns,
                )
            self._require_visible_geometry(
                result,
                need_plant=True,
                step="plantio",
            )
            self.last_result = result
            self._show_result(
                result,
                step="Plantio gerado",
                elapsed_s=time.perf_counter() - t0,
            )
            self._select_preview_layers_in_cross_combos(for_planting=True, for_spraying=False)
            self._update_workflow_status()
            self._announce_generation(result, "Plantio")
        except Exception as exc:
            if self.isMinimized():
                self.showNormal()
            self._warn_crs_error(exc)
        finally:
            self._set_generation_busy(False)
            self.generation_progress.hide()

    def _open_strategy_analyzer(self) -> None:
        """Mesmo projeto/area do 'Gerar plantio'; a analise nunca grava camada final sozinha."""
        try:
            self._ensure_workspace_layers_metric(silent=True)
            if self.ab_start is None or self.ab_end is None:
                raise ValueError(
                    "Defina a linha A-B na aba 1: ela ancora a numeração e a bordadura da análise."
                )
            self._activate_ab_for_operation("planting")
            project = self._build_project(include_planting=True, include_spraying=False)
        except Exception as exc:
            self._warn_crs_error(exc)
            return
        self.strategy_dialog = StrategyAnalyzerDialog(
            project,
            field_name=self._current_field_name(),
            crs_authid=project.field.crs_authid,
            reference_layer=self.ab_layer_combo.currentLayer(),
            canvas=self.iface.mapCanvas() if hasattr(self.iface, "mapCanvas") else None,
            parent=self,
        )
        self.strategy_dialog.strategySaved.connect(self._on_strategy_saved)
        self.strategy_dialog.show()
        self.strategy_dialog.raise_()

    def _on_strategy_saved(self, saved) -> None:
        self.plant_line_combo.setLayer(saved.layer)
        self.summary.setText(
            f"Estratégia gravada em 12_Passadas_Plantio (versão {saved.version})."
            + ("" if saved.persisted else " " + STORAGE_MESSAGES[PROJECT_NOT_SAVED])
        )
        self._update_workflow_status()

    def _apply_obstacle_avoidance(self) -> None:
        """Etapa livre: aplica desvio nas linhas ja geradas (ou gera o que faltar)."""
        try:
            if self.isMinimized():
                self.showNormal()
            self._set_generation_busy(True)
            self._ensure_workspace_layers_metric(silent=True)
            self.enable_avoidance.setChecked(True)
            self.enable_avoidance.setEnabled(True)

            has_plant = bool(self.last_result and self.last_result.planting_passes)
            has_spray = bool(self.last_result and self.last_result.spraying_passes)
            if not has_plant and not has_spray:
                raise ValueError(
                    "Gere primeiro as linhas (botao 1 aplicacao e/ou botao 2 plantio), "
                    "depois volte a aba 4, escolha a camada de pontos com feicoes, "
                    "informe o raio e clique de novo em 'Aplicar desvio'."
                )

            project = self._build_project(
                include_planting=has_plant,
                include_spraying=has_spray,
                require_obstacles=True,
            )
            self._maybe_warn_heavy_avoidance(project)
            if not project.obstacles:
                raise ValueError(
                    "Nenhum obstaculo carregado. Selecione uma camada com pontos, linhas "
                    "ou poligonos validos na aba 4 (nao use camada vazia)."
                )
            result = self._run_precision_lines_job(
                project,
                title="FortSmart — Desvio de obstaculos",
                status_message=f"Aplicando desvio ({len(project.obstacles)} obstaculo(s))...",
            )
            # Preserva o lado que nao foi regenerado (nao deveria ocorrer se ambos True).
            if self.last_result is not None:
                result = PrecisionLinesResult(
                    project=project,
                    boundary=result.boundary or self.last_result.boundary,
                    planting_passes=result.planting_passes or self.last_result.planting_passes,
                    planting_rows=result.planting_rows or self.last_result.planting_rows,
                    spraying_passes=result.spraying_passes or self.last_result.spraying_passes,
                    tramline_zones=result.tramline_zones or self.last_result.tramline_zones,
                    shutoff_segments=result.shutoff_segments or self.last_result.shutoff_segments,
                    shutoff_table=result.shutoff_table or self.last_result.shutoff_table,
                    avoided_paths=result.avoided_paths,
                    obstacle_envelopes=result.obstacle_envelopes,
                    avoidance_table=result.avoidance_table,
                    planting_avoidance_results=result.planting_avoidance_results
                    or self.last_result.planting_avoidance_results,
                    forbidden_regions=result.forbidden_regions or self.last_result.forbidden_regions,
                    validation=result.validation,
                    spraying_boundary=result.spraying_boundary or self.last_result.spraying_boundary,
                    tire_tracks=result.tire_tracks or self.last_result.tire_tracks,
                    tractor_axes=result.tractor_axes or self.last_result.tractor_axes,
                    spray_avoidance_records=result.spray_avoidance_records
                    or self.last_result.spray_avoidance_records,
                    spray_headland_turns=result.spray_headland_turns
                    if result.spraying_passes
                    else self.last_result.spray_headland_turns,
                )
            self.last_result = result
            self._show_result(
                result,
                step=f"Desvio aplicado ({len(project.obstacles)} obstaculo(s))",
            )
            self._select_preview_layers_in_cross_combos()
            self._announce_generation(result, "Desvio de obstaculos")
        except Exception as exc:
            if self.isMinimized():
                self.showNormal()
            self._warn_crs_error(exc)
        finally:
            self._set_generation_busy(False)
            self.generation_progress.hide()

    def _require_visible_geometry(
        self,
        result: PrecisionLinesResult,
        *,
        need_spray: bool = False,
        need_plant: bool = False,
        step: str,
    ) -> None:
        """Falha com mensagem clara se o motor nao produziu geometria."""
        if need_spray and not result.spraying_passes:
            raise ValueError(
                f"Geracao de {step} nao produziu passadas de aplicacao.\n"
                "Verifique: (1) A-B definida e no mesmo talhao, "
                "(2) CRS metrico via Conversor de zona, "
                "(3) largura da barra > 0."
            )
        if need_plant and not result.planting_rows and not result.planting_passes:
            raise ValueError(
                f"Geracao de {step} nao produziu linhas/passadas de plantio.\n"
                "Verifique: (1) A-B definida e cruzando o talhao, "
                "(2) CRS metrico, (3) numero de linhas e espacamento."
            )

    def _announce_generation(self, result: PrecisionLinesResult, title: str) -> None:
        counts: list[str] = []
        empty: list[str] = []
        project_layers = self._field_scoped_layers()
        for short_name in NAMED_PREVIEW_LAYERS:
            found = find_preview_layer(project_layers, short_name)
            n_feat = int(found.featureCount()) if found is not None else 0
            suffix = "" if n_feat else " (vazia)"
            counts.append(f"{short_name}: {n_feat} feicoes{suffix}")
            if n_feat == 0:
                empty.append(short_name)
        empty_note = ""
        if empty:
            empty_note = (
                "\nCamadas vazias (0 feicoes, ainda visiveis no grupo): "
                + ", ".join(empty)
                + ".\n"
            )
        msg = (
            f"{title} concluida.\n\n"
            + "\n".join(counts)
            + f"\n\nPassadas de plantio no mapa: {len(result.planting_passes)} "
            f"(espacamento = largura operacional)\n"
            f"Linhas de semente: {len(result.planting_rows)} virtuais "
            f"(motor/shutoff — NAO desenhadas)\n"
            f"Rastros de pneu: {len(result.tire_tracks)}\n"
            f"CRS das camadas: {self.work_crs_authid or '?'}\n"
            f"{empty_note}\n"
            f"Grupo '{self._preview_group_title()}' adicionado ao mapa."
        )
        storage_note = getattr(self, "_storage_note", "")
        if storage_note:
            msg += f"\n\n{storage_note}"
        QMessageBox.information(self, "FortSmart", msg)

    def _cross_layers(self) -> None:
        try:
            if self.isMinimized():
                self.showNormal()
            self.setEnabled(False)
            try:
                from qgis.PyQt.QtCore import Qt
                from qgis.PyQt.QtWidgets import QApplication

                QApplication.setOverrideCursor(Qt.WaitCursor)
            except Exception:
                pass
            self._ensure_workspace_layers_metric(silent=True)
            self._select_preview_layers_in_cross_combos()

            planter = self.planter_widget.build_machine()
            sprayer = self.sprayer_widget.build_machine()
            spray_source_mode = self.spray_source_mode_combo.currentData()
            crs_authid = self.work_crs_authid
            target_crs = None

            session_rows = None
            session_plant_passes = None
            session_spray_passes = None
            if self.use_generated_for_cross.isChecked() and self.last_result is not None:
                session_rows = self.last_result.planting_rows or None
                session_plant_passes = self.last_result.planting_passes or None
                crs_authid = self.work_crs_authid or (
                    self.last_result.project.field.crs_authid
                    if self.last_result.project
                    else None
                )
            if (
                spray_source_mode == SPRAY_CROSS_SOURCE_LINE_BASE
                and self.last_result is not None
            ):
                session_spray_passes = self.last_result.spraying_passes or None

            imported_plant = None
            imported_spray = None
            plant_layer = self._resolve_line_layer(
                getattr(self, "planting_line_combo", None),
                getattr(self, "plant_line_combo", None),
            )
            spray_layer = None
            if spray_source_mode == SPRAY_CROSS_SOURCE_EXISTING_PASSES:
                spray_layer = self._resolve_line_layer(
                    getattr(self, "spray_line_combo", None),
                )
            field = self.field_combo.currentLayer()
            if field is None:
                raise ValueError("Selecione o talhao na aba 1.")
            if not crs_authid:
                crs_authid, target_crs, _was_geo = resolve_metric_target_crs(field)
                self.work_crs_authid = crs_authid
            if target_crs is None:
                target_crs = QgsCoordinateReferenceSystem(crs_authid)

            if plant_layer is not None:
                imported_plant = planting_rows_from_line_layer(
                    plant_layer, target_crs, machine_id=planter.machine_id
                )
            if spray_layer is not None:
                if is_planting_preview_line_layer(spray_layer):
                    raise ValueError(
                        "A camada selecionada pertence ao plantio e nao pode ser usada "
                        "como passada de pulverizacao."
                    )
                if not self.spray_passes_selected_only.isChecked():
                    raise ValueError(
                        "Por seguranca, marque 'Usar somente as feicoes selecionadas no mapa'."
                    )
                if spray_layer.selectedFeatureCount() <= 0:
                    raise ValueError(
                        "Selecione no mapa uma ou mais passadas reais de pulverizacao. "
                        "Nenhuma feicao sera usada silenciosamente."
                    )
                imported_spray = spray_passes_from_line_layer(
                    spray_layer,
                    target_crs,
                    width_m=sprayer.operational_width_m,
                    selected_only=True,
                )

            use_session = bool(
                getattr(self, "use_generated_for_cross", None) is not None
                and self.use_generated_for_cross.isChecked()
            )
            prefer_spray_layer = bool(
                spray_source_mode == SPRAY_CROSS_SOURCE_EXISTING_PASSES
                and imported_spray
            )
            prefer_plant_layer = bool(
                imported_plant and (not use_session or not (session_rows or session_plant_passes))
            )

            kinematics = PlantingKinematics(
                operational_width_m=planter.operational_width_m,
                track_width_m=planter.track.track_width_m,
                hitch_distance_m=self.planter_widget.hitch_distance_m(),
                minimum_turn_radius_m=self.planter_widget.turn_radius_m(),
                row_count=planter.row_count,
                row_spacing_m=planter.row_spacing_m,
            )
            operational = []
            if self.last_result is not None and self.last_result.project is not None:
                operational = list(self.last_result.project.field.operational_boundary or [])
            if not operational and field is not None and is_polygon_like_vector_layer(field):
                operational = multipolygon_from_polygon_layer(field, target_crs)
            work_area = build_cross_work_area(operational, self.planter_widget.extension_m())

            planting_rows, plant_src = resolve_planting_rows_for_cross(
                session_rows=session_rows,
                session_passes=session_plant_passes,
                imported_rows=imported_plant,
                planter=planter,
                prefer_imported=prefer_plant_layer,
                kinematics=kinematics,
                work_area=work_area,
            )
            spraying_passes, spray_src = resolve_spraying_passes_for_cross(
                session_passes=(
                    session_spray_passes
                    if spray_source_mode == SPRAY_CROSS_SOURCE_LINE_BASE
                    else None
                ),
                imported_passes=imported_spray,
                prefer_imported=prefer_spray_layer,
            )

            if not planting_rows:
                raise ValueError(
                    "Sem linhas de plantio. Gere o plantio (botao 2) ou selecione "
                    "'06_Passadas_Plantio'."
                )
            if not spraying_passes:
                if spray_source_mode == SPRAY_CROSS_SOURCE_LINE_BASE:
                    raise ValueError(
                        "Modo Linha-base: selecione a referencia na aba Aplicacao e gere "
                        "as passadas com o botao 1 antes de calcular o cruzamento."
                    )
                raise ValueError(
                    "Modo Passadas existentes: selecione uma ou mais feicoes reais no mapa."
                )

            dlg = CrossConfirmDialog(
                self,
                planter=planter,
                sprayer=sprayer,
                plant_count=len(planting_rows),
                spray_count=len(spraying_passes),
                plant_source=plant_src,
                spray_source=spray_src,
            )
            if dlg.exec_() != QDialog.Accepted:
                return

            boundary = None
            if self.last_result is not None:
                boundary = self.last_result.boundary or getattr(
                    self.last_result, "spraying_boundary", None
                )
            headland_off = self._resolve_headland_off_areas(target_crs)
            cross = run_cross_shutoff(
                planting_rows=planting_rows,
                spraying_passes=spraying_passes,
                planter=planter,
                sprayer=sprayer,
                plant_source=plant_src,
                spray_source=spray_src,
                shutoff_on_tramlines=self.shutoff_tramline_check.isChecked(),
                shutoff_on_headland_inner=self.shutoff_headland_check.isChecked(),
                off_areas=headland_off,
                boundary=boundary,
                # Recalcula com pneu/bitola/margem atualmente informados. Rastros
                # da previa anterior podem ter sido gerados com outras medidas.
                existing_tire_tracks=None,
                clip_area=work_area or None,
            )
            planting_rows = cross.planting_rows
            shutoff_segments = cross.shutoff_segments
            shutoff_table = cross.shutoff_table
            tire_tracks = cross.tire_tracks
            tramline_zones = cross.tramline_zones

            if self.last_result is None:
                project = self._build_cross_stub_project(
                    crs_authid=crs_authid,
                    target_crs=target_crs,
                    planting_rows=planting_rows,
                    spraying_passes=spraying_passes,
                )
                result = PrecisionLinesResult(
                    project=project,
                    boundary=None,
                    planting_passes=[],
                    planting_rows=planting_rows,
                    spraying_passes=spraying_passes,
                    tramline_zones=tramline_zones,
                    shutoff_segments=shutoff_segments,
                    shutoff_table=shutoff_table,
                    tire_tracks=tire_tracks,
                )
            else:
                result = PrecisionLinesResult(
                    project=self.last_result.project,
                    boundary=self.last_result.boundary,
                    planting_passes=self.last_result.planting_passes,
                    planting_rows=planting_rows,
                    spraying_passes=spraying_passes,
                    tramline_zones=tramline_zones,
                    shutoff_segments=shutoff_segments,
                    shutoff_table=shutoff_table,
                    avoided_paths=self.last_result.avoided_paths,
                    obstacle_envelopes=self.last_result.obstacle_envelopes,
                    avoidance_table=self.last_result.avoidance_table,
                    planting_avoidance_results=self.last_result.planting_avoidance_results,
                    forbidden_regions=self.last_result.forbidden_regions,
                    validation=self.last_result.validation,
                    spraying_boundary=self.last_result.spraying_boundary,
                    tire_tracks=tire_tracks or self.last_result.tire_tracks,
                    tractor_axes=self.last_result.tractor_axes,
                    spray_avoidance_records=self.last_result.spray_avoidance_records,
                    spray_headland_turns=self.last_result.spray_headland_turns,
                )
            self.last_result = result
            off_segments = list(cross.tire_shutoff_segments)
            affected_rows = {(item.pass_id, item.row_id) for item in off_segments}
            excluded_m = sum(
                polyline_length(list(item.line_points())) for item in off_segments
            )
            if off_segments:
                self.cross_result_summary.setText(
                    f"Passadas analisadas: {len(spraying_passes)} | "
                    f"linhas de plantio afetadas: {len(affected_rows)} | "
                    f"intersecoes: {len(off_segments)} | "
                    f"exclusao: {excluded_m:.2f} m"
                )
            else:
                self.cross_result_summary.setText(
                    f"Passadas analisadas: {len(spraying_passes)} | "
                    "nenhuma intersecao com as linhas de plantio."
                )
            self._show_result(result, step="Cruzamento concluido")
            # A publicacao do preview atualiza combos e selecoes. O rascunho nasce
            # depois desses sinais para nao ser invalidado pela propria renderizacao.
            self.operational_draft = self._build_operational_draft(
                cross,
                sprayer=sprayer,
                crs_authid=crs_authid,
                plant_source=plant_src,
                spray_source=spray_src,
            )
            self.operational_state_label.setText(
                "Calculado - nao salvo | Generation: "
                + self.operational_draft.manifest.generation_id
            )
            self.save_operational_btn.setEnabled(True)
            self._update_workflow_status()
            self.tabs.setCurrentIndex(getattr(self, "_tab_idx_cross", 4))
        except Exception as exc:
            if self.isMinimized():
                self.showNormal()
            self._warn_crs_error(exc)
        finally:
            self.setEnabled(True)
            try:
                from qgis.PyQt.QtWidgets import QApplication

                QApplication.restoreOverrideCursor()
            except Exception:
                pass

    def _build_operational_draft(
        self,
        cross,
        *,
        sprayer,
        crs_authid: str,
        plant_source: str,
        spray_source: str,
    ):
        field_name = self._current_field_name() or "PROJETO"
        field_id = canonical_field_name(field_name)
        mode = self.spray_source_mode_combo.currentData()
        source_mode = (
            CrossSourceMode.EXISTING_PASSES
            if mode == SPRAY_CROSS_SOURCE_EXISTING_PASSES
            else CrossSourceMode.GENERATED_BASELINE
        )
        spray_layer = (
            self.spray_line_combo.currentLayer()
            if source_mode == CrossSourceMode.EXISTING_PASSES
            else self.spray_ab_combo.currentLayer()
        )
        plant_layer = self.planting_line_combo.currentLayer()
        selected_ids = ()
        if source_mode == CrossSourceMode.EXISTING_PASSES and spray_layer is not None:
            selected_ids = tuple(str(feature.id()) for feature in spray_layer.selectedFeatures())
        return build_operational_generation(
            cross=cross,
            field_id=field_id,
            field_name=field_name,
            source_crs=(spray_layer.crs().authid() if spray_layer is not None else crs_authid),
            working_crs=crs_authid,
            source_mode=source_mode,
            sprayer=sprayer,
            planting_layer=(plant_layer.name() if plant_layer is not None else plant_source),
            spray_layer=(spray_layer.name() if spray_layer is not None else spray_source),
            spray_source_layer_id=(spray_layer.id() if spray_layer is not None else ""),
            selected_spray_feature_ids=selected_ids,
        )

    def _invalidate_operational_draft(self, *_args) -> None:
        if getattr(self, "operational_draft", None) is None:
            return
        self.operational_draft = None
        if hasattr(self, "save_operational_btn"):
            self.save_operational_btn.setEnabled(False)
        if hasattr(self, "operational_state_label"):
            self.operational_state_label.setText("Desatualizado - recalcule antes de salvar")

    def _operational_store(self, *, create: bool = False):
        field_name = self._current_field_name()
        manager = FortSmartPersistenceManager(QgsProject.instance())
        if not manager.storage_available():
            raise PersistenceError(PROJECT_NOT_SAVED)
        path = manager.get_field_storage_path(field_name)
        if create:
            path = manager.ensure_geopackage(path)
        return OperationalPersistenceStore(path)

    def _save_operational_result(self) -> None:
        draft = getattr(self, "operational_draft", None)
        if draft is None:
            QMessageBox.warning(
                self, "FortSmart Precision", "Recalcule o cruzamento antes de salvar."
            )
            return
        try:
            saved = self._operational_store(create=True).save_generation(draft)
        except (PersistenceError, OperationalPersistenceError, ValueError) as exc:
            QMessageBox.critical(
                self, "FortSmart Precision", f"Resultado operacional nao foi salvo:\n{exc}"
            )
            return
        self.operational_draft = None
        self.active_operational_generation = saved
        self.save_operational_btn.setEnabled(False)
        self.operational_state_label.setText(
            f"Persistido | Generation: {saved.manifest.generation_id} | "
            f"{saved.manifest.intersection_count} interseccao(oes) | "
            f"{saved.manifest.excluded_length_m:.2f} m OFF"
        )
        QMessageBox.information(
            self,
            "FortSmart Precision",
            "Resultado operacional salvo no GeoPackage do talhao.\n"
            f"Generation: {saved.manifest.generation_id}",
        )

    def _load_active_operational_generation(self, *_args) -> None:
        if not hasattr(self, "operational_state_label"):
            return
        field_name = self._current_field_name()
        if not field_name:
            return
        try:
            active = self._operational_store().load_active(canonical_field_name(field_name))
        except (PersistenceError, OperationalPersistenceError, OSError):
            return
        self.active_operational_generation = active
        if active is None:
            if self.operational_draft is None:
                self.operational_state_label.setText("Nao calculado")
            return
        manifest = active.manifest
        self.operational_state_label.setText(
            f"Persistido | Generation: {manifest.generation_id} | "
            f"{manifest.intersection_count} interseccao(oes) | "
            f"{manifest.excluded_length_m:.2f} m OFF"
        )
        self.cross_result_summary.setText(
            f"Passadas analisadas: {manifest.selected_spray_count} | "
            f"linhas afetadas: {manifest.affected_rows_count} | "
            f"intersecoes: {manifest.intersection_count} | "
            f"exclusao: {manifest.excluded_length_m:.2f} m (recuperado do GeoPackage)"
        )
        self._restore_operational_preview_layers(active)

    def _restore_operational_preview_layers(self, generation) -> None:
        project = QgsProject.instance()
        field_name = generation.manifest.field_name
        field_id = generation.manifest.field_id
        group = project_group(project.layerTreeRoot(), field_name)
        existing_roles = {
            layer.customProperty("fortsmart_role", "")
            for layer in project.mapLayers().values()
            if layer_field_id(layer) == field_id
        }
        for definition, layer in build_operational_preview_layers(generation):
            if definition.role in existing_roles:
                continue
            project.addMapLayer(layer, False)
            insert_layer_ordered(section_group(group, definition.section), layer)

    def _build_cross_stub_project(
        self,
        *,
        crs_authid: str,
        target_crs: QgsCoordinateReferenceSystem,
        planting_rows,
        spraying_passes,
    ) -> PrecisionProject:
        """Projeto minimo para cruzar camadas ja existentes — nao exige A-B capturada."""
        from ..core.workspace_cross_utils import ab_proxy_from_traffic_or_rows

        ab_start, ab_end, ab_path = ab_proxy_from_traffic_or_rows(
            spraying_passes,
            planting_rows,
        )

        operational = []
        field_layer = self.field_combo.currentLayer()
        if field_layer is not None and is_polygon_like_vector_layer(field_layer):
            try:
                operational = multipolygon_from_polygon_layer(field_layer, target_crs)
            except Exception:
                operational = []
        if not operational:
            # Envelope das linhas — so para preencher o modelo; preview usa as linhas.
            xs: list[float] = []
            ys: list[float] = []
            for item in list(spraying_passes) + list(planting_rows):
                for pt in item.line_points():
                    xs.append(pt[0])
                    ys.append(pt[1])
            if not xs:
                raise ValueError("Sem geometria para montar o cruzamento.")
            pad = 10.0
            ring = [
                (min(xs) - pad, min(ys) - pad),
                (max(xs) + pad, min(ys) - pad),
                (max(xs) + pad, max(ys) + pad),
                (min(xs) - pad, max(ys) + pad),
                (min(xs) - pad, min(ys) - pad),
            ]
            operational = [(ring, [])]

        planter = self.planter_widget.build_machine()
        sprayer = self.sprayer_widget.build_machine()
        return PrecisionProject(
            field=FieldGeometry(
                field_boundary=operational,
                operational_boundary=operational,
                crs_authid=crs_authid,
            ),
            ab_line=ABLine(start=ab_start, end=ab_end, path_points=ab_path),
            planting=PrecisionOperation(
                operation_id="planting",
                machine=planter,
                headland=HeadlandLayout(pass_count=0, width_m=0.0, mode="none"),
                extension_m=self.planter_widget.extension_m(),
            ),
            spraying=PrecisionOperation(
                operation_id="spraying",
                machine=sprayer,
                headland=HeadlandLayout(pass_count=0, width_m=0.0, mode="none"),
                extension_m=self.sprayer_widget.extension_m(),
            ),
            shutoff_on_tramlines=self.shutoff_tramline_check.isChecked(),
            shutoff_on_headland_inner=self.shutoff_headland_check.isChecked(),
        )

    def _resolve_line_layer(self, *combos):
        for combo in combos:
            if combo is None:
                continue
            layer = combo.currentLayer()
            if layer is not None and is_line_like_vector_layer(layer):
                return layer
        return None

    def _resolve_polygon_layer(self, *combos):
        for combo in combos:
            if combo is None:
                continue
            layer = combo.currentLayer()
            if layer is not None and is_polygon_like_vector_layer(layer):
                return layer
        return None

    def _resolve_headland_off_areas(self, target_crs):
        """Bordadura para shutoff: camadas selecionadas e/ou sessao."""
        if not self.shutoff_headland_check.isChecked():
            return None

        off_areas = []
        plant_hl = self._resolve_polygon_layer(
            getattr(self, "plant_headland_cross_combo", None),
            getattr(self, "plant_headland_combo", None),
        )
        spray_hl = self._resolve_polygon_layer(
            getattr(self, "spray_headland_cross_combo", None),
            getattr(self, "spray_headland_combo", None),
        )
        if plant_hl is not None:
            off_areas.extend(multipolygon_from_polygon_layer(plant_hl, target_crs))
        if spray_hl is not None:
            off_areas.extend(multipolygon_from_polygon_layer(spray_hl, target_crs))

        if (
            not off_areas
            and self.last_result is not None
            and self.last_result.boundary is not None
            and self.last_result.boundary.areas.headland_area
        ):
            off_areas.extend(self.last_result.boundary.areas.headland_area)
        if (
            not off_areas
            and self.last_result is not None
            and getattr(self.last_result, "spraying_boundary", None) is not None
            and self.last_result.spraying_boundary.areas.headland_area
        ):
            off_areas.extend(self.last_result.spraying_boundary.areas.headland_area)

        return off_areas or None

    def _select_preview_layers_in_cross_combos(
        self,
        *,
        for_planting: bool = True,
        for_spraying: bool = True,
    ) -> None:
        """Apos gerar: aponta combos para o preview CORRETO (plantio != pulverizacao).

        A busca usa a marca do plugin na camada e aceita nomes antigos
        ('_fortsmart_workspace_05_Passadas (12)'); os dois combos nunca caem
        na mesma camada.
        """
        layers = self._field_scoped_layers()

        def _set_line(combos, *short_names: str, require_features: bool = True) -> None:
            layer = find_preview_layer(layers, *short_names)
            if layer is None or not is_line_like_vector_layer(layer):
                return
            if require_features and int(layer.featureCount() or 0) <= 0:
                return
            for combo in combos:
                if combo is not None:
                    try:
                        combo.setLayer(layer)
                    except Exception:
                        pass

        def _set_poly(combos, *short_names: str) -> None:
            layer = find_preview_layer(layers, *short_names)
            if layer is None or not is_polygon_like_vector_layer(layer):
                return
            for combo in combos:
                if combo is not None:
                    try:
                        combo.setLayer(layer)
                    except Exception:
                        pass

        if for_planting:
            _set_line(
                (
                    getattr(self, "planting_line_combo", None),
                    getattr(self, "plant_line_combo", None),
                ),
                "06_Passadas_Plantio",
                "06_Linhas_Plantio",
                "linhas_plantio",
                "rows",
                "passadas_plantio",
            )
            _set_poly(
                (
                    getattr(self, "plant_headland_combo", None),
                    getattr(self, "plant_headland_cross_combo", None),
                ),
                "02_Bordadura",
            )

        if for_spraying:
            # Nunca usar preview de plantio / linha do trator como pulverizacao.
            _set_line(
                (
                    getattr(self, "spray_line_combo", None),
                    getattr(self, "spray_pass_combo", None),
                ),
                "05_Passadas",
                "passadas_aplicacao",
                "spray",
            )
            _set_poly(
                (
                    getattr(self, "spray_headland_combo", None),
                    getattr(self, "spray_headland_cross_combo", None),
                ),
                "02_Bordadura",
            )

        obs = getattr(self, "obstacle_combo", None)
        cross_obs = getattr(self, "cross_obstacle_combo", None)
        if obs is not None and cross_obs is not None and obs.currentLayer() is not None:
            cross_obs.setLayer(obs.currentLayer())
        else:
            layer = find_preview_layer(layers, "09_Obstaculos_RTK")
            if layer is not None:
                for combo in (obs, cross_obs):
                    if combo is not None:
                        try:
                            combo.setLayer(layer)
                        except Exception:
                            pass

    def _show_result(self, result: PrecisionLinesResult, *, step: str, elapsed_s: float | None = None) -> None:
        crs_note = f" | CRS {self.work_crs_authid}" if self.work_crs_authid else ""
        timing = ""
        if elapsed_s is not None:
            timing = f" | {elapsed_s:.1f} s"
        self.summary.setText(
            f"{step}{timing}{crs_note} — "
            f"Plantio: {len(result.planting_passes)} passadas "
            f"(motor: {len(result.planting_rows)} linhas virtuais) | "
            f"Aplicacao: {len(result.spraying_passes)} passadas | "
            f"Rastros: {len(result.tire_tracks)} | "
            f"Tramlines: {len(result.tramline_zones)} | "
            f"Shutoff: {len(result.shutoff_segments)} | "
            f"Desvios: {len(result.avoided_paths)} | "
            f"Validacao: {'OK' if result.validation.ok else 'FALHOU'} | "
            f"Preview passadas: aplicacao={len(result.spraying_passes)}, plantio={len(result.planting_passes)}"
        )
        headland_note = headland_status_note(
            plantio=result.boundary if result.project.planting is not None else None,
            aplicacao=result.spraying_boundary,
        )
        if headland_note:
            self.summary.setText(f"{self.summary.text()} | {headland_note}")
        self._show_spray_avoidance_summary(result)
        self._show_spray_headland_turn_summary(result)

        self.table.setRowCount(0)
        row_i = 0
        # Tabela limpa: passada → linhas OFF (auditoria), nao uma linha por row.
        pass_visuals = aggregate_shutoff_on_passes(
            list(result.planting_passes),
            list(result.shutoff_segments),
        )
        for item in pass_shutoff_table(pass_visuals):
            self.table.insertRow(row_i)
            self.table.setItem(row_i, 0, QTableWidgetItem(str(item.get("pass_id", ""))))
            self.table.setItem(row_i, 1, QTableWidgetItem(str(item.get("row_ids_off", ""))))
            self.table.setItem(row_i, 2, QTableWidgetItem(str(item.get("action", "DESLIGA"))))
            self.table.setItem(
                row_i,
                3,
                QTableWidgetItem(f"{item.get('row_off_count', 0)} linhas"),
            )
            self.table.setItem(
                row_i,
                4,
                QTableWidgetItem(str(item.get("off_length_m", ""))),
            )
            row_i += 1
        for item in result.avoidance_table:
            self.table.insertRow(row_i)
            self.table.setItem(row_i, 0, QTableWidgetItem(str(item.get("pass_id", ""))))
            obs = item.get("obstacle_id") or item.get("obstacle_ids", "")
            self.table.setItem(row_i, 1, QTableWidgetItem(str(obs)))
            action = item.get("action") or item.get("strategy_used", "")
            self.table.setItem(row_i, 2, QTableWidgetItem(str(action)))
            self.table.setItem(row_i, 3, QTableWidgetItem(str(item.get("conflict_type", "avoid"))))
            radius = item.get("application_radius_m", item.get("tractor_radius_m", ""))
            self.table.setItem(row_i, 4, QTableWidgetItem(str(radius)))
            row_i += 1

        self._update_avoidance_audit(result)
        self._render_preview(result, progress_bar=self.generation_progress)

    def _show_spray_avoidance_summary(self, result: PrecisionLinesResult) -> None:
        """Contagem NONE/LATERAL/FULL_CONTOUR/UNRESOLVED e alerta das falhas seguras."""
        from ..core.spray_avoidance_preview import spray_avoidance_summary

        text, warnings = spray_avoidance_summary(
            list(getattr(result, "spray_avoidance_records", None) or [])
        )
        if not text:
            return
        note = text
        if warnings:
            note += (
                f" | ATENCAO: {len(warnings)} conflito(s) sem desvio seguro — "
                "trajetoria original mantida, revise antes de operar"
            )
        self.summary.setText(f"{self.summary.text()} | {note}")
        label = getattr(self, "spray_avoid_status_label", None)
        if label is not None:
            label.setText("\n".join([text, *warnings]))

    def _show_spray_headland_turn_summary(self, result: PrecisionLinesResult) -> None:
        """Manobra automatica: curvas aceitas e avisos (sem espaco / sem raio)."""
        from ..core.spray_headland_turns import spray_headland_turn_summary

        turns = getattr(result, "spray_headland_turns", None)
        text = spray_headland_turn_summary(turns)
        if text:
            self.summary.setText(f"{self.summary.text()} | {text}")
        if turns is not None and turns.warnings:
            self.sprayer_widget.spray_turn_mode_hint.setText(
                "\n".join([text, *turns.warnings[:6]])
                + (f"\n(+{len(turns.warnings) - 6} aviso(s))" if len(turns.warnings) > 6 else "")
            )
        self._refresh_spray_border_entry_summary()

    def _spray_border_entry_inputs(self):
        from ..core.spray_border_entry import HeadlandRingInput, SprayPassInput

        result = self.last_result
        if result is None:
            return (), ()
        passes = tuple(
            SprayPassInput(
                pass_id=int(item.pass_no),
                points=item.line_points(),
                direction=str(getattr(item, "direction", "forward") or "forward"),
                line_id=str(getattr(item, "fs_id", "") or ""),
            )
            for item in (result.spraying_passes or ())
        )
        plan = result.spraying_boundary
        rings = ()
        if plan is not None:
            rings = tuple(
                HeadlandRingInput(
                    pass_no=int(line.pass_no),
                    offset_m=float(line.offset_from_outer_m),
                    points=line.line_points(),
                    line_id=str(getattr(line, "fs_id", "") or ""),
                )
                for line in plan.headland_centerlines
            )
        return passes, rings

    def _refresh_spray_border_entry_summary(self) -> None:
        label = getattr(self, "border_entry_summary", None)
        if label is None or not self._spray_border_entry_flag_on():
            return
        from ..core.spray_border_entry import border_entry_summary, plan_spray_border_entries

        passes, rings = self._spray_border_entry_inputs()
        u_turns = (
            self.sprayer_widget.spray_headland_turn_mode() == SPRAY_HEADLAND_TURN_AUTOMATIC
        )
        plan = plan_spray_border_entries(passes, rings, u_turns_active=u_turns)
        turn_diagnostic = self._existing_spray_turn_diagnostic()
        label.setText(
            border_entry_summary(plan)
            + (f"\n{turn_diagnostic}" if turn_diagnostic else "")
        )

    def _existing_spray_turn_diagnostic(self) -> str:
        """Somente le 16_Manobras_Cabeceira; nunca remove ou altera feicoes."""
        field_id = canonical_field_name(self._current_field_name())
        layers = [
            layer for layer in QgsProject.instance().mapLayers().values()
            if str(layer.customProperty("fortsmart_role", "")) == HEADLAND_TURN_ROLE.role
            and layer_field_id(layer) in ("", field_id)
        ]
        counts = {"BORDER_TRANSIT": 0, "LEGACY_U": 0, "OTHER": 0}
        for layer in layers:
            field_index = layer.fields().indexFromName("turn_type")
            for feature in layer.getFeatures():
                turn_type = str(feature[field_index] or "").strip().upper() if field_index >= 0 else ""
                if turn_type == "BORDER_TRANSIT":
                    counts["BORDER_TRANSIT"] += 1
                elif turn_type in {"U", "U_TURN", "UTURN", "OMEGA", "DROP", "THREE_POINT"}:
                    counts["LEGACY_U"] += 1
                else:
                    counts["OTHER"] += 1
        total = sum(counts.values())
        if total == 0:
            return "16_Manobras_Cabeceira: nenhuma feicao existente; previa nova permanece em memoria."
        return (
            f"16_Manobras_Cabeceira: {total} feicao(oes) existente(s), somente leitura | "
            f"motor antigo={counts['LEGACY_U']} | BORDER_TRANSIT persistido={counts['BORDER_TRANSIT']} | "
            f"outros={counts['OTHER']}."
        )

    def _preview_spray_border_entry(self) -> None:
        from ..core.spray_border_entry import (
            BorderEntrySettings,
            border_entry_summary,
            plan_spray_border_entries,
        )
        from .spray_border_entry_preview import SprayBorderEntryPreview

        if not self._spray_border_entry_flag_on():
            return
        if self.last_result is None or not self.last_result.spraying_passes:
            QMessageBox.information(
                self, "Entra e sai automático", "Gere a aplicação antes de pré-visualizar."
            )
            return
        u_turns = (
            self.sprayer_widget.spray_headland_turn_mode() == SPRAY_HEADLAND_TURN_AUTOMATIC
        )
        if u_turns:
            QMessageBox.warning(
                self,
                "Entra e sai automático",
                "Essa função não roda junto da manobra automática (U). "
                "Volte o modo de cabeceira para extensão reta.",
            )
            return
        radius = self._sprayer_turn_radius_m()
        settings = BorderEntrySettings(min_turn_radius_m=radius)
        passes, rings = self._spray_border_entry_inputs()
        plan = plan_spray_border_entries(passes, rings, settings=settings, u_turns_active=False)
        self._last_border_entry_plan = plan
        turn_diagnostic = self._existing_spray_turn_diagnostic()
        self.border_entry_summary.setText(
            border_entry_summary(plan)
            + (f"\n{turn_diagnostic}" if turn_diagnostic else "")
        )
        combo = self.border_entry_connection_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Todas as conexoes", "")
        for item in plan.accepted:
            combo.addItem(f"{item.turn_id}: {item.from_line_id} -> {item.to_line_id}", item.turn_id)
        combo.blockSignals(False)
        if self.border_entry_preview is None:
            canvas = None
            try:
                canvas = self.iface.mapCanvas()
            except Exception:
                canvas = None
            self.border_entry_preview = SprayBorderEntryPreview(canvas)
        self._refresh_spray_border_entry_view()
        if not plan.accepted:
            QMessageBox.information(
                self,
                "Entra e sai automático",
                plan.warnings[0] if plan.warnings else "Manobra inviavel com os criterios atuais.",
            )

    def _cancel_spray_border_entry(self) -> None:
        if self.border_entry_preview is not None:
            self.border_entry_preview.clear()
        self._refresh_spray_border_entry_summary()

    def _refresh_spray_border_entry_view(self, *_args) -> None:
        from ..core.spray_border_entry import border_entry_connection_summary

        plan = getattr(self, "_last_border_entry_plan", None)
        if plan is None:
            return
        turn_id = str(self.border_entry_connection_combo.currentData() or "")
        component = str(self.border_entry_component_combo.currentData() or "all")
        selected = next(
            (item for item in plan.accepted if not turn_id or item.turn_id == turn_id),
            None,
        )
        self.border_entry_detail.setText(border_entry_connection_summary(selected))
        if self.border_entry_preview is not None:
            self.border_entry_preview.show(plan, component=component, turn_id=turn_id)

    def _current_field_name(self) -> str | None:
        combo = getattr(self, "field_combo", None)
        field = combo.currentLayer() if combo is not None else None
        return field.name() if field is not None else None

    def _preview_group_title(self) -> str:
        return preview_group_name(self._current_field_name())

    def _field_scoped_layers(self) -> list:
        """Camadas do talhao atual; as de outro talhao FORTSMART ficam de fora."""
        field_id = canonical_field_name(self._current_field_name())
        return [
            layer for layer in QgsProject.instance().mapLayers().values()
            if layer_field_id(layer) in ("", field_id)
        ]

    def _preview_group(self):
        root = QgsProject.instance().layerTreeRoot()
        group = project_group(root, self._current_field_name())
        group.setCustomProperty(PREVIEW_GROUP_PROPERTY, True)
        return group

    def _render_preview(self, result, *, progress_bar=None) -> None:
        self._clear_preview()
        canvas = None
        canvas_frozen = False
        try:
            canvas = self.iface.mapCanvas()
            canvas.setRenderFlag(False)
            canvas_frozen = True
        except Exception:
            pass
        try:
            self._render_preview_layers(result, progress_bar=progress_bar)
        finally:
            if canvas is not None and canvas_frozen:
                try:
                    canvas.setRenderFlag(True)
                    canvas.refresh()
                except Exception:
                    pass

    def _render_preview_layers(self, result, *, progress_bar=None) -> None:
        # _render_preview ja limpou; limpar de novo custa outra varredura do projeto.
        crs = self.work_crs_authid
        if not crs and result.project is not None:
            crs = result.project.field.crs_authid
        if not crs:
            layer = self.field_combo.currentLayer()
            if layer is None:
                return
            crs = layer.crs().authid()

        group = self._preview_group()
        added: list[QgsVectorLayer] = []

        colors = {
            "01_Limite_Externo": (QColor(30, 30, 30, 50), 0.6),
            "02_Bordadura": (QColor(200, 160, 40, 45), 0.6),
            "03_Limite_Interno": (QColor(40, 140, 40, 40), 0.5),
            "04_Linha_AB": (QColor(180, 0, 180), 1.2),
            "05_Passadas": (QColor(40, 100, 220), 1.0),
            "06_Passadas_Plantio": (QColor(20, 160, 20), 1.4),
            "07_Linha_Trator": (QColor(0, 0, 0), 1.2),
            "08_Rastros_Pneus": (QColor(120, 60, 20), 0.8),
            "09_Obstaculos_RTK": (QColor(220, 40, 40), 3.0),
            "10_Zonas_Seguranca": (QColor(255, 120, 0, 60), 0.5),
            "11_Desvios_Obstaculos": (QColor(255, 80, 80, 50), 0.5),
            "12_Linhas_Finais": (QColor(0, 90, 180), 1.0),
            "13_Shutoff": (QColor(200, 30, 30), 2.0),
            "14_Limite_Operacional": (QColor(0, 120, 180, 30), 0.8),
            "15_Passadas_Bordadura": (QColor(0, 90, 140), 1.8),
        }

        polygons: dict[str, list] = {name: [] for name in NAMED_PREVIEW_LAYERS}
        lines: dict[str, list] = {name: [] for name in NAMED_PREVIEW_LAYERS}
        points: dict[str, list] = {name: [] for name in NAMED_PREVIEW_LAYERS}
        line_attrs: dict[str, list] = {name: [] for name in NAMED_PREVIEW_LAYERS}

        planting_b = result.boundary
        spray_b = result.spraying_boundary
        boundaries = [b for b in (planting_b, spray_b) if b is not None]
        unique_boundaries = []
        for item in boundaries:
            if item not in unique_boundaries:
                unique_boundaries.append(item)

        if result.project is not None and result.project.field.operational_boundary:
            polygons["01_Limite_Externo"] = list(result.project.field.operational_boundary)
            # Limite operacional = original + max(extensao plantio, spray); so visual.
            ext_m = 0.0
            if result.project.spraying is not None:
                ext_m = max(ext_m, float(result.project.spraying.extension_m))
            if result.project.planting is not None:
                ext_m = max(ext_m, float(result.project.planting.extension_m))
            if ext_m > 0:
                from ..core.line_geometry import build_processing_boundary

                polygons["14_Limite_Operacional"] = build_processing_boundary(
                    result.project.field.operational_boundary,
                    ext_m,
                )

        for boundary in unique_boundaries:
            if boundary.areas.headland_area:
                polygons["02_Bordadura"].extend(boundary.areas.headland_area)
            if boundary.inner_boundary:
                polygons["03_Limite_Interno"].extend(boundary.inner_boundary)

        # Passadas fechadas da bordadura do TALHAO. Sao trajetorias operacionais
        # distintas da faixa poligonal 02_Bordadura e da bordadura de obstaculo.
        headland_boundary = result.boundary or result.spraying_boundary
        if headland_boundary is not None:
            centerlines = list(headland_boundary.headland_centerlines)
            for centerline, (segment_index, segment_count) in zip(
                centerlines, pass_segment_layout(centerlines)
            ):
                pts = centerline.line_points()
                if len(pts) < 2:
                    continue
                pass_number = centerline.pass_no + 1
                lines["15_Passadas_Bordadura"].append(pts)
                line_attrs["15_Passadas_Bordadura"].append(
                    {
                        "fs_id": centerline.fs_id,
                        "pass_no": pass_number,
                        "offset_m": centerline.offset_from_outer_m,
                        "length_m": centerline.length_m(),
                        "role": centerline.role,
                        "label": f"B{pass_number}",
                        "segment_index": segment_index,
                        "segment_count": segment_count,
                    }
                )

        if result.project is not None:
            ab = result.project.effective_ab_line()
            lines["04_Linha_AB"].append(ab.line_points())
            line_attrs["04_Linha_AB"].append(
                {"line_no": 0, "label": "0", "role": "AB"}
            )

        obstacles = list(result.project.obstacles) if result.project is not None else []
        spray_records = list(getattr(result, "spray_avoidance_records", None) or [])
        spray_zone_feats: list = []
        spray_detour_feats: list = []
        spray_pass_attrs: dict = {}
        if spray_records:
            from ..core.spray_avoidance_preview import (
                spray_detour_features,
                spray_pass_attributes,
                spray_safety_zone_features,
            )

            spray_zone_feats = spray_safety_zone_features(obstacles)
            spray_detour_feats = spray_detour_features(spray_records)
            spray_pass_attrs = spray_pass_attributes(spray_records)

        spray_project = result.project
        spray_overlap = machine_pass_overlap_attributes(
            result.spraying_passes,
            spray_project.spraying.machine
            if spray_project is not None and spray_project.spraying is not None
            else None,
        )
        for traffic in result.spraying_passes:
            pts = traffic_pass_points(traffic)
            if len(pts) < 2:
                continue
            lines["05_Passadas"].append(pts)
            line_attrs["05_Passadas"].append(
                {
                    "line_id": line_id_for(traffic.pass_no),
                    "line_number": traffic.pass_no,
                    "line_no": traffic.pass_no,
                    "pass_id": traffic.pass_no,
                    "label": line_label_for_pass(traffic.pass_no, machine_prefix="A"),
                    "spacing_m": traffic.spacing_m,
                    "width_m": traffic.width_m,
                    **spray_overlap.get(traffic.pass_no, {}),
                    **(
                        spray_pass_attrs.get(
                            traffic.pass_no, {"avoidance_type": "NONE", "obstacle_ids": ""}
                        )
                        if spray_records
                        else {}
                    ),
                }
            )
        # MAPA: somente trajetoria do trator (1 linha por passada = largura operacional).
        # NUNCA adicionar result.planting_rows aqui — sao virtuais (0,50 m).
        planting_segments = pass_segment_layout(result.planting_passes)
        for traffic, (segment_index, segment_count) in zip(result.planting_passes, planting_segments):
            pts = traffic_pass_points(traffic)
            if len(pts) >= 2:
                lines["06_Passadas_Plantio"].append(pts)
                line_attrs["06_Passadas_Plantio"].append(
                    {
                        "line_id": line_id_for(traffic.pass_no),
                        "line_number": traffic.pass_no,
                        "line_no": traffic.pass_no,
                        "pass_id": traffic.pass_no,
                        "label": line_label_for_pass(traffic.pass_no, machine_prefix="P"),
                        "spacing_m": traffic.spacing_m,
                        "width_m": traffic.width_m,
                        "pass_number": traffic.pass_no,
                        "segment_index": segment_index,
                        "segment_count": segment_count,
                        "source_candidate_index": source_candidate_index_for(traffic),
                    }
                )

        # 07 = eixos retos calculados no motor: A-B + offset + clip operacional.
        # Nunca copiar curva, bordadura, retorno ou conexao da camada 12.
        for axis in result.tractor_axes:
            lines["07_Linha_Trator"].append(axis.path_points)
            line_attrs["07_Linha_Trator"].append(
                {
                    "line_id": line_id_for(axis.pass_no),
                    "line_number": axis.pass_no,
                    "line_no": axis.pass_no,
                    "pass_id": axis.pass_no,
                    "label": line_label_for_pass(axis.pass_no, machine_prefix="T"),
                    "spacing_m": axis.spacing_m,
                    "width_m": axis.width_m,
                    "role": "tractor_axis",
                }
            )

        for track in result.tire_tracks:
            if len(track.points) >= 2:
                lines["08_Rastros_Pneus"].append(track.points)
                line_attrs["08_Rastros_Pneus"].append(
                    {"pass_id": track.pass_id, "side": track.side}
                )

        obstacle_sources: list = []
        for obs in obstacles:
            points["09_Obstaculos_RTK"].append(obs.center)
            # So geometria fonte do obstaculo. Contorno operacional fica na LINHA (05/06).
            if obs.polygon is not None:
                polygons["11_Desvios_Obstaculos"].append(obs.polygon)
                obstacle_sources.append((obs.polygon, {"obstacle_id": obs.obstacle_id}))

        final_lines = []
        if result.avoided_paths:
            from ..core.line_geometry import decimate_polyline

            for path in result.avoided_paths:
                pts = list(path.modified_points)
                if len(pts) > 480:
                    pts = decimate_polyline(pts, min_step_m=2.5, max_points=480)
                final_lines.append(tuple(pts))
        lines["12_Linhas_Finais"] = final_lines

        # Shutoff no mapa = trechos OFF na passada do trator (agregado).
        pass_off = aggregate_shutoff_on_passes(
            list(result.planting_passes),
            list(result.shutoff_segments),
        )
        for visual in pass_off:
            if len(visual.path_points) >= 2:
                lines["13_Shutoff"].append(visual.path_points)
                line_attrs["13_Shutoff"].append(
                    {
                        "pass_id": visual.pass_id,
                        "row_ids_off": ",".join(str(r) for r in visual.row_ids_off),
                    }
                )

        def _enable_pass_labels(lyr: QgsVectorLayer, *, text_color: QColor) -> None:
            try:
                settings = QgsPalLayerSettings()
                settings.fieldName = "label"
                settings.isExpression = False
                settings.enabled = True
                try:
                    settings.placement = QgsPalLayerSettings.Line
                except Exception:
                    pass
                fmt = QgsTextFormat()
                fmt.setSize(9)
                fmt.setColor(text_color)
                try:
                    from qgis.PyQt.QtGui import QFont

                    fmt.setFont(QFont("Arial", 9, QFont.Bold))
                except Exception:
                    pass
                settings.setFormat(fmt)
                lyr.setLabeling(QgsVectorLayerSimpleLabeling(settings))
                lyr.setLabelsEnabled(True)
            except Exception:
                pass

        def _style(lyr: QgsVectorLayer, short_name: str) -> None:
            color, size = colors[short_name]
            geom = PREVIEW_LAYER_GEOM[short_name]
            try:
                if geom == "LineString":
                    width = preview_line_width_mm(short_name, size)
                    line_symbol = QgsLineSymbol.createSimple(
                        {
                            "color": color.name(),
                            "width": str(width),
                            "capstyle": "round",
                            "joinstyle": "round",
                        }
                    )
                    lyr.setRenderer(QgsSingleSymbolRenderer(line_symbol))
                elif geom == "Point":
                    from qgis.core import QgsMarkerSymbol

                    marker = QgsMarkerSymbol.createSimple(
                        {
                            "color": color.name(),
                            "outline_color": "0,0,0,255",
                            "outline_width": "0.4",
                            "size": str(size),
                        }
                    )
                    lyr.setRenderer(QgsSingleSymbolRenderer(marker))
                elif short_name in ("01_Limite_Externo", "03_Limite_Interno"):
                    outline = "30,30,30,180" if short_name == "01_Limite_Externo" else "40,140,40,200"
                    fill = QgsFillSymbol.createSimple(
                        {
                            "color": "0,0,0,0",
                            "outline_color": outline,
                            "outline_width": "0.8" if short_name == "01_Limite_Externo" else "0.5",
                            "style": "no",
                        }
                    )
                    lyr.setRenderer(QgsSingleSymbolRenderer(fill))
                elif short_name == "14_Limite_Operacional":
                    fill = QgsFillSymbol.createSimple(
                        {
                            "color": "0,120,180,20",
                            "outline_color": "0,120,180,200",
                            "outline_width": "0.6",
                            "outline_style": "dash",
                            "style": "no",
                        }
                    )
                    lyr.setRenderer(QgsSingleSymbolRenderer(fill))
                elif geom == "Polygon":
                    fill = QgsFillSymbol.createSimple(
                        {
                            "color": f"{color.red()},{color.green()},{color.blue()},{color.alpha()}",
                            "outline_color": f"{color.red()},{color.green()},{color.blue()},200",
                            "outline_width": "0.5",
                        }
                    )
                    lyr.setRenderer(QgsSingleSymbolRenderer(fill))
            except Exception:
                pass
            if short_name == "04_Linha_AB":
                _enable_pass_labels(lyr, text_color=QColor(120, 0, 120))
            elif short_name == "05_Passadas":
                _enable_pass_labels(lyr, text_color=QColor(20, 60, 160))
            elif short_name == "06_Passadas_Plantio":
                _enable_pass_labels(lyr, text_color=QColor(0, 100, 0))
            elif short_name == "15_Passadas_Bordadura":
                _enable_pass_labels(lyr, text_color=QColor(0, 70, 110))

        def _add_line_feats_with_attrs(
            lyr: QgsVectorLayer,
            short_name: str,
            fields_spec: list[tuple[str, object]],
            attr_keys: list[str],
        ) -> list:
            provider = lyr.dataProvider()
            provider.addAttributes(
                [QgsField(name, qtype) for name, qtype in fields_spec]
            )
            lyr.updateFields()
            out = []
            for pts, attrs in zip(lines[short_name], line_attrs[short_name]):
                if len(pts) < 2:
                    continue
                feat = QgsFeature(lyr.fields())
                feat.setGeometry(
                    QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in pts])
                )
                feat.setAttributes([attrs.get(key) for key in attr_keys])
                out.append(feat)
            return out

        def _polygon_geometry(poly):
            outer, holes = poly
            if len(outer) < 4:
                return None
            rings = [[QgsPointXY(x, y) for x, y in outer]]
            rings.extend([QgsPointXY(x, y) for x, y in hole] for hole in holes if len(hole) >= 4)
            return QgsGeometry.fromPolygonXY(rings)

        def _boom_sweep_geometry(pts, boom_width_m):
            from qgis.core import Qgis

            line = QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in pts])
            return line.buffer(
                float(boom_width_m) / 2.0, 8, Qgis.EndCapStyle.Flat, Qgis.JoinStyle.Round, 2.0
            )

        def _spray_avoidance_feats(lyr: QgsVectorLayer, short_name: str) -> list:
            """22 = zona (raio + margem); 23 = faixa da barra no trecho desviado/UNRESOLVED."""
            from ..core.spray_avoidance_preview import SPRAY_DETOUR_FIELDS, SPRAY_ZONE_FIELDS

            qtypes = {"string": QVariant.String, "int": QVariant.Int, "double": QVariant.Double}
            spec = SPRAY_ZONE_FIELDS if short_name == "10_Zonas_Seguranca" else SPRAY_DETOUR_FIELDS
            lyr.dataProvider().addAttributes([QgsField(name, qtypes[kind]) for name, kind in spec])
            lyr.updateFields()
            if short_name == "10_Zonas_Seguranca":
                items = [(_polygon_geometry(poly), attrs) for poly, attrs in spray_zone_feats]
            else:
                items = [(_polygon_geometry(poly), attrs) for poly, attrs in obstacle_sources]
                items += [
                    (_boom_sweep_geometry(pts, attrs["boom_width_m"]), attrs)
                    for pts, attrs in spray_detour_feats
                ]
            out = []
            for geometry, attrs in items:
                if geometry is None or geometry.isEmpty():
                    continue
                feat = QgsFeature(lyr.fields())
                feat.setGeometry(geometry)
                feat.setAttributes([attrs.get(name) for name, _kind in spec])
                out.append(feat)
            return out

        # Sufixo _2 so para nao sobrescrever camada do usuario com o mesmo nome.
        taken_names = {
            lyr.name() for lyr in QgsProject.instance().mapLayers().values()
            if not is_generated_layer(lyr)
        }
        field_name = self._current_field_name()

        def _add_named_layer(short_name: str) -> QgsVectorLayer:
            geom = PREVIEW_LAYER_GEOM[short_name]
            layer_name = unique_layer_name(preview_layer_base_name(short_name), taken_names)
            taken_names.add(layer_name)
            lyr = QgsVectorLayer(f"{geom}?crs={crs}", layer_name, "memory")
            lyr.setCustomProperty(PREVIEW_LAYER_PROPERTY, short_name)
            provider = lyr.dataProvider()
            feats = []
            if short_name == "04_Linha_AB":
                feats = _add_line_feats_with_attrs(
                    lyr,
                    short_name,
                    [
                        ("line_no", QVariant.Int),
                        ("label", QVariant.String),
                        ("role", QVariant.String),
                    ],
                    ["line_no", "label", "role"],
                )
            elif short_name == "15_Passadas_Bordadura":
                feats = _add_line_feats_with_attrs(
                    lyr,
                    short_name,
                    [
                        ("fs_id", QVariant.String),
                        ("pass_no", QVariant.Int),
                        ("offset_m", QVariant.Double),
                        ("length_m", QVariant.Double),
                        ("role", QVariant.String),
                        ("label", QVariant.String),
                        ("segment_index", QVariant.Int),
                        ("segment_count", QVariant.Int),
                    ],
                    ["fs_id", "pass_no", "offset_m", "length_m", "role", "label", "segment_index", "segment_count"],
                )
            elif short_name in ("05_Passadas", "06_Passadas_Plantio", "07_Linha_Trator"):
                fields_spec = [
                    ("line_id", QVariant.String),
                    ("line_number", QVariant.Int),
                    ("line_no", QVariant.Int),
                    ("pass_id", QVariant.Int),
                    ("label", QVariant.String),
                    ("spacing_m", QVariant.Double),
                    ("width_m", QVariant.Double),
                ]
                if short_name == "06_Passadas_Plantio":
                    fields_spec += [(name, QVariant.Int) for name in PASS_SEGMENT_FIELDS]
                if short_name == "05_Passadas":
                    fields_spec += [
                        ("direction", QVariant.String),
                        ("overlap_side", QVariant.String),
                        ("overlap_nozzles", QVariant.Int),
                        ("overlap_m", QVariant.Double),
                    ]
                    if spray_records:
                        fields_spec += [
                            ("avoidance_type", QVariant.String),
                            ("obstacle_ids", QVariant.String),
                        ]
                feats = _add_line_feats_with_attrs(
                    lyr,
                    short_name,
                    fields_spec,
                    [name for name, _qtype in fields_spec],
                )
            elif spray_records and short_name in ("10_Zonas_Seguranca", "11_Desvios_Obstaculos"):
                feats = _spray_avoidance_feats(lyr, short_name)
            elif short_name == "13_Shutoff":
                provider.addAttributes(
                    [
                        QgsField("pass_id", QVariant.Int),
                        QgsField("row_ids_off", QVariant.String),
                    ]
                )
                lyr.updateFields()
                for pts, attrs in zip(lines[short_name], line_attrs[short_name]):
                    if len(pts) < 2:
                        continue
                    feat = QgsFeature(lyr.fields())
                    feat.setGeometry(
                        QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in pts])
                    )
                    feat.setAttributes(
                        [attrs.get("pass_id"), attrs.get("row_ids_off", "")]
                    )
                    feats.append(feat)
            elif short_name == "08_Rastros_Pneus":
                provider.addAttributes(
                    [QgsField("pass_id", QVariant.Int), QgsField("side", QVariant.String)]
                )
                lyr.updateFields()
                for pts, attrs in zip(lines[short_name], line_attrs[short_name]):
                    if len(pts) < 2:
                        continue
                    feat = QgsFeature(lyr.fields())
                    feat.setGeometry(
                        QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in pts])
                    )
                    feat.setAttributes([attrs.get("pass_id"), attrs.get("side")])
                    feats.append(feat)
            elif geom == "LineString":
                for pts in lines[short_name]:
                    if len(pts) < 2:
                        continue
                    feat = QgsFeature()
                    feat.setGeometry(
                        QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in pts])
                    )
                    feats.append(feat)
            elif geom == "Polygon":
                for poly in polygons[short_name]:
                    outer, holes = poly
                    if len(outer) < 4:
                        continue
                    rings = [[QgsPointXY(x, y) for x, y in outer]]
                    for hole in holes:
                        if len(hole) >= 4:
                            rings.append([QgsPointXY(x, y) for x, y in hole])
                    feat = QgsFeature()
                    feat.setGeometry(QgsGeometry.fromPolygonXY(rings))
                    feats.append(feat)
            else:
                for pt in points[short_name]:
                    feat = QgsFeature()
                    feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(pt[0], pt[1])))
                    feats.append(feat)
            if feats:
                provider.addFeatures(feats)
                lyr.updateExtents()
            apply_qgis_layer_role(lyr, layer_role_definition(short_name), field_name=field_name)
            _style(lyr, short_name)
            return lyr

        # Monta TODAS as camadas em memoria antes de tocar no projeto: publicar
        # uma a uma dispara signals da arvore de camadas e repaint por camada.
        layer_order = preview_layer_draw_order()
        total_layers = len(layer_order)
        built: list[QgsVectorLayer] = []
        for index, short_name in enumerate(layer_order):
            if progress_bar is not None:
                pct = int(100 * (index + 1) / max(1, total_layers))
                progress_bar.setValue(pct)
                progress_bar.setFormat(f"%p% — Preview {short_name}")
                progress_bar.show()
                # Manter a GUI viva sem processar eventos a cada camada.
                if index % 4 == 0 or index == total_layers - 1:
                    try:
                        from qgis.PyQt.QtWidgets import QApplication

                        QApplication.processEvents()
                    except Exception:
                        pass
            built.append(_add_named_layer(short_name))
        definitions = [layer_role_definition(short_name) for short_name in layer_order]
        # Cabeceira automatica: curvas no role HEADLAND_TURN existente; manual = nenhuma.
        self._remove_spray_headland_turn_layers(field_name)
        turn_layer = self._spray_headland_turn_layer(result, crs, field_name)
        if turn_layer is not None:
            definitions.append(HEADLAND_TURN_ROLE)
            built.append(turn_layer)

        # Projeto salvo: cada role vai para a tabela do GPKG do talhao (fica apos
        # reabrir). Sem projeto salvo: publicacao em memoria, um addMapLayers; cada
        # role substitui a camada gerada do mesmo talhao, e uma camada vazia nunca
        # apaga um resultado salvo.
        project_instance = QgsProject.instance()
        manager = FortSmartPersistenceManager(project_instance)
        persist = manager.storage_available() and bool(field_name)
        persisted_layers = []
        kept_previous = []
        storage_errors = []
        published = []
        replaced_ids = []
        for definition, lyr in zip(definitions, built):
            if persist:
                try:
                    stored = manager.persist_layer(lyr, definition, field_name)
                except PersistenceError as exc:
                    storage_errors.append(str(exc))
                else:
                    publish_persisted(
                        project_instance, lyr, stored.layer,
                        reused=stored.reused_layer, field_name=field_name, definition=definition,
                    )
                    if definition is HEADLAND_TURN_ROLE:
                        stored.layer.setCustomProperty(SPRAY_HEADLAND_TURN_PROPERTY, True)
                    persisted_layers.append(stored.layer)
                    if stored.status == STATUS_KEPT_PREVIOUS:
                        kept_previous.append(definition.display_name)
                    continue
            existing = generated_layers_for_role(project_instance, definition.role, field_name)
            if any(is_persisted_layer(item) for item in existing):
                continue
            if lyr.featureCount() == 0 and any(item.featureCount() != 0 for item in existing):
                continue
            replaced_ids.extend(item.id() for item in existing)
            published.append((definition, lyr))
        if replaced_ids:
            project_instance.removeMapLayers(replaced_ids)
        layers_to_add = [lyr for _definition, lyr in published]
        try:
            project_instance.addMapLayers(layers_to_add, False)
        except Exception:
            for lyr in layers_to_add:
                project_instance.addMapLayer(lyr, False)
        for definition, lyr in published:
            section = section_group(group, definition.section)
            node = insert_layer_ordered(section, lyr)
            if node is not None:
                # Contagem exibida pelo proprio QGIS, fora do nome da camada.
                node.setCustomProperty("showFeatureCount", True)
        added.extend(layers_to_add)
        added.extend(persisted_layers)
        self._storage_note = self._storage_summary(
            persist, manager, field_name, kept_previous, storage_errors, persisted_layers
        )
        move_layers_to_auxiliaries(
            project_instance.layerTreeRoot(),
            group,
            [
                combo.currentLayer()
                for combo in (
                    getattr(self, "field_combo", None),
                    getattr(self, "ab_layer_combo", None),
                    getattr(self, "obstacle_combo", None),
                )
                if combo is not None
            ],
        )

        # Combos plantio/spray sao atualizados pelo chamador com flags
        # for_planting/for_spraying — evita misturar as duas operacoes.
        self._zoom_to_layers(
            added,
            priority_tokens=("05_Passadas", "06_Passadas_Plantio", "04_Linha_AB"),
        )

    @staticmethod
    def _remove_spray_headland_turn_layers(field_name) -> None:
        """Curvas automaticas anteriores do Workspace saem do projeto (GPKG intacto)."""
        project = QgsProject.instance()
        stale = [
            layer.id()
            for layer in generated_layers_for_role(
                project, HEADLAND_TURN_ROLE.role, field_name, include_temporary=True
            )
            if layer.customProperty(SPRAY_HEADLAND_TURN_PROPERTY, False)
        ]
        if stale:
            project.removeMapLayers(stale)

    @staticmethod
    def _spray_headland_turn_layer(result, crs, field_name):
        """16_Manobras_Cabeceira com as curvas aceitas; None no modo manual ou sem curva."""
        from ..core.headland_turn_engine import HEADLAND_TURN_FIELDS

        turns = getattr(result, "spray_headland_turns", None)
        features = turns.features() if turns is not None else []
        if not features:
            return None
        qtypes = {
            "string": QVariant.String,
            "int": QVariant.Int,
            "double": QVariant.Double,
            "bool": QVariant.Bool,
        }
        layer = QgsVectorLayer(f"LineString?crs={crs}", HEADLAND_TURN_ROLE.display_name, "memory")
        layer.dataProvider().addAttributes(
            [QgsField(name, qtypes[kind]) for name, kind in HEADLAND_TURN_FIELDS]
        )
        layer.updateFields()
        feats = []
        for points, attrs in features:
            feat = QgsFeature(layer.fields())
            feat.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in points]))
            feat.setAttributes([attrs.get(name) for name, _kind in HEADLAND_TURN_FIELDS])
            feats.append(feat)
        layer.dataProvider().addFeatures(feats)
        layer.updateExtents()
        layer.setCustomProperty(PREVIEW_LAYER_PROPERTY, HEADLAND_TURN_ROLE.key)
        layer.setCustomProperty(SPRAY_HEADLAND_TURN_PROPERTY, True)
        apply_qgis_layer_role(layer, HEADLAND_TURN_ROLE, field_name=field_name)
        layer.setRenderer(
            QgsSingleSymbolRenderer(
                QgsLineSymbol.createSimple(
                    {"color": "230,120,0,255", "width": "0.8", "capstyle": "round", "joinstyle": "round"}
                )
            )
        )
        return layer

    @staticmethod
    def _storage_summary(persist, manager, field_name, kept_previous, errors, persisted_layers) -> str:
        if not persist:
            return STORAGE_MESSAGES[PROJECT_NOT_SAVED] + " As camadas ficaram apenas em memória."
        lines = []
        if persisted_layers:
            lines.append(f"Resultados salvos em {manager.get_field_storage_path(field_name)}")
        if kept_previous:
            lines.append(
                "Resultado vazio. A camada persistida anterior foi mantida: " + ", ".join(kept_previous) + "."
            )
        lines.extend(errors)
        return "\n".join(lines)

    def _zoom_to_layers(
        self,
        layers: list,
        *,
        priority_tokens: tuple[str, ...] = (),
    ) -> None:
        if not layers:
            return
        try:
            extent = None
            pool = layers
            if priority_tokens:
                preferred = [
                    lyr
                    for lyr in layers
                    if lyr.featureCount() > 0
                    and any(token in lyr.name() for token in priority_tokens)
                ]
                if preferred:
                    pool = preferred
            for lyr in pool:
                if lyr.featureCount() <= 0:
                    continue
                ext = lyr.extent()
                if ext is None or ext.isEmpty():
                    continue
                extent = ext if extent is None else extent.combinedExtentWith(ext)
            if extent is None or extent.isEmpty():
                return
            canvas = self.iface.mapCanvas()
            # Se o CRS do canvas for diferente, tenta transformar a extent.
            layer_crs = layers[0].crs()
            canvas_crs = canvas.mapSettings().destinationCrs()
            if layer_crs != canvas_crs:
                from qgis.core import QgsCoordinateTransform

                transform = QgsCoordinateTransform(
                    layer_crs, canvas_crs, QgsProject.instance()
                )
                extent = transform.transformBoundingBox(extent)
            canvas.setExtent(extent)
            canvas.zoomOut()  # pequena folga visual
            canvas.refresh()
        except Exception:
            try:
                self.iface.mapCanvas().refresh()
            except Exception:
                pass

    def _clear_preview(self) -> None:
        """Remove o preview do talhao atual; outros talhoes, originais e resultados salvos ficam."""
        if getattr(self, "border_entry_preview", None) is not None:
            self.border_entry_preview.clear()
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        field_name = self._current_field_name()
        field_id = canonical_field_name(field_name)
        current_group = project_group(root, field_name, create=False)
        legacy_names = (
            "Linhas_Plantio",
            "linhas_plantio",
            "_rows",
            "planting_rows",
        )
        ids = []
        for lyr in project.mapLayers().values():
            name = lyr.name()
            legacy = any(token in name for token in legacy_names) and name.startswith("_fortsmart")
            if not (is_plugin_preview_layer(lyr) or legacy) or is_persisted_layer(lyr):
                continue
            owner = layer_field_id(lyr)
            if owner:
                if owner == field_id:
                    ids.append(lyr.id())
                continue
            holder = project_group_of(root, lyr)
            if holder is None or holder is current_group:
                ids.append(lyr.id())
        if ids:
            project.removeMapLayers(ids)
        for group in root.findGroups(True):
            if group.name() == LEGACY_PREVIEW_GROUP_NAME:
                (group.parent() or root).removeChildNode(group)
        if current_group is not None:
            prune_empty_sections(current_group)
            remove_group_if_empty(current_group)
