# -*- coding: utf-8 -*-
"""Entrada principal do plugin FortSmart Precision."""

from pathlib import Path

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import QgsApplication, QgsMessageLog, Qgis

from .provider import FortSmartProvider
from .gui.fortsmart_workspace_dialog import FortSmartWorkspaceDialog
from .gui.crs_zone_converter_dialog import CrsZoneConverterDialog
from .gui.main_dock import FortSmartDock
from .gui.planting_line_cut_dialog import PlantingLineCutDialog
from .gui.obstacle_detour_dialog import TOOL_TITLE as OBSTACLE_DETOUR_TITLE
from .gui.obstacle_detour_dialog import TOOL_TOOLTIP as OBSTACLE_DETOUR_TOOLTIP
from .gui.obstacle_detour_dialog import ObstacleDetourDialog
from .gui.headland_turns_dialog import HeadlandTurnsDialog
from .gui.export_readiness_dialog import ExportReadinessDialog
from .gui.layer_tree_organizer import normalize_legacy_project_layers, persist_generated_memory_layers
from .core.persistence_manager import PersistenceError
from .feature_flags import ENABLE_STRATEGY_ANALYZER

OPERATION_SIMULATOR_ALGORITHM_ID = "fortsmart_precision:simulate_real_operation"


class FortSmartPrecisionPlugin:
    """Plugin QGIS FortSmart — menu unificado."""

    def __init__(self, iface):
        self.iface = iface
        self.action_workspace = None
        self.action_panel = None
        self.action_create_project = None
        self.action_open_project = None
        self.action_import_active = None
        self.action_crs_converter = None
        self.action_line_cut = None
        self.action_obstacle_detour = None
        self.action_headland_turns = None
        self.action_organize_layers = None
        self.action_persist_layers = None
        self.action_strategy_analyzer = None
        self.action_operation_simulator = None
        self.action_coverage_xray = None
        self.route_simulation_dialog = None
        self.action_export_readiness = None
        self.action_about = None
        self.provider = None
        self.dock = None
        self.workspace_dialog = None
        self.line_cut_dialog = None
        self.obstacle_detour_dialog = None
        self.headland_turns_dialog = None
        self.export_readiness_dialog = None

    def initGui(self):
        self.action_workspace = QAction("Planejamento Precision Lines", self.iface.mainWindow())
        self.action_workspace.triggered.connect(self.open_workspace)

        self.action_panel = QAction("Painel do projeto", self.iface.mainWindow())
        self.action_panel.triggered.connect(self.open_panel)

        self.action_create_project = QAction("Criar projeto", self.iface.mainWindow())
        self.action_create_project.triggered.connect(self.create_project)

        self.action_open_project = QAction("Abrir projeto", self.iface.mainWindow())
        self.action_open_project.triggered.connect(self.open_project)

        self.action_import_active = QAction("Importar camada", self.iface.mainWindow())
        self.action_import_active.triggered.connect(self.import_layer)

        self.action_crs_converter = QAction("Conversor de zona / CRS", self.iface.mainWindow())
        self.action_crs_converter.triggered.connect(self.open_crs_converter)

        self.action_line_cut = QAction("Cortar linhas por obstaculos", self.iface.mainWindow())
        self.action_line_cut.triggered.connect(self.open_line_cut)

        self.action_obstacle_detour = QAction(OBSTACLE_DETOUR_TITLE, self.iface.mainWindow())
        self.action_obstacle_detour.setToolTip(OBSTACLE_DETOUR_TOOLTIP)
        self.action_obstacle_detour.triggered.connect(self.open_obstacle_detour)

        self.action_headland_turns = QAction("Manobras de cabeceira", self.iface.mainWindow())
        self.action_headland_turns.triggered.connect(self.open_headland_turns)

        self.action_organize_layers = QAction("Organizar camadas FortSmart", self.iface.mainWindow())
        self.action_organize_layers.setToolTip(
            "Reconhece camadas antigas pelo role/alias e as coloca na arvore canonica, sem alterar dados"
        )
        self.action_organize_layers.triggered.connect(self.organize_layers)

        self.action_persist_layers = QAction("Persistir camadas FortSmart", self.iface.mainWindow())
        self.action_persist_layers.setToolTip(
            "Salva no GeoPackage do talhao as camadas geradas que ainda estao em memoria (inclui a simulacao)"
        )
        self.action_persist_layers.triggered.connect(self.persist_layers)

        self.action_operation_simulator = QAction("Simulador de Operacao", self.iface.mainWindow())
        self.action_operation_simulator.setToolTip(
            "Maquina percorrendo as passadas existentes, uma por vez (so o trecho percorrido aparece)"
        )
        self.action_operation_simulator.triggered.connect(self.open_route_simulator)

        self.action_coverage_xray = QAction("Raio-X de cobertura (analise)", self.iface.mainWindow())
        self.action_coverage_xray.setToolTip(
            "Analise estatica de cobertura, falhas e remonte das passadas (nao e animacao)"
        )
        self.action_coverage_xray.triggered.connect(self.open_operation_simulator)

        self.action_export_readiness = QAction(
            "Validar projeto para exportacao", self.iface.mainWindow()
        )
        self.action_export_readiness.setToolTip(
            "Verifica identidade, roles, geometrias, CRS e prontidao do talhao sem exportar arquivos"
        )
        self.action_export_readiness.triggered.connect(self.open_export_readiness)

        if ENABLE_STRATEGY_ANALYZER:
            self.action_strategy_analyzer = QAction("Comparar projeção de plantio", self.iface.mainWindow())
            self.action_strategy_analyzer.setToolTip(
                "Compara reta x curva em preview temporario; grava 12_Passadas_Plantio so na escolha manual"
            )
            self.action_strategy_analyzer.triggered.connect(self.open_strategy_analyzer)

        self.action_about = QAction("Sobre", self.iface.mainWindow())
        self.action_about.triggered.connect(self.show_about)

        for action in (
            self.action_workspace,
            self.action_panel,
            self.action_create_project,
            self.action_open_project,
            self.action_import_active,
            self.action_crs_converter,
            self.action_line_cut,
            self.action_obstacle_detour,
            self.action_headland_turns,
            self.action_strategy_analyzer,
            self.action_organize_layers,
            self.action_persist_layers,
            self.action_operation_simulator,
            self.action_coverage_xray,
            self.action_export_readiness,
            self.action_about,
        ):
            if action is not None:
                self.iface.addPluginToMenu("FortSmart Precision", action)

        self.iface.addToolBarIcon(self.action_workspace)
        self.iface.addToolBarIcon(self.action_panel)
        self.iface.addToolBarIcon(self.action_import_active)
        self.iface.addToolBarIcon(self.action_operation_simulator)
        self.iface.addToolBarIcon(self.action_obstacle_detour)

        self.provider = FortSmartProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)
        QgsMessageLog.logMessage(
            "FortSmart Precision Provider registrado.",
            "FortSmart Precision",
            Qgis.Info,
        )

    def unload(self):
        for action in (
            self.action_workspace,
            self.action_panel,
            self.action_create_project,
            self.action_open_project,
            self.action_import_active,
            self.action_crs_converter,
            self.action_line_cut,
            self.action_obstacle_detour,
            self.action_headland_turns,
            self.action_strategy_analyzer,
            self.action_organize_layers,
            self.action_persist_layers,
            self.action_operation_simulator,
            self.action_coverage_xray,
            self.action_export_readiness,
            self.action_about,
        ):
            if action is not None:
                self.iface.removePluginMenu("FortSmart Precision", action)

        if self.route_simulation_dialog is not None:
            self.route_simulation_dialog.close()
            self.route_simulation_dialog = None

        if self.obstacle_detour_dialog is not None:
            self.obstacle_detour_dialog.close()
            self.obstacle_detour_dialog = None

        for action in (
            self.action_workspace,
            self.action_panel,
            self.action_import_active,
            self.action_operation_simulator,
            self.action_obstacle_detour,
        ):
            if action is not None:
                self.iface.removeToolBarIcon(action)

        if self.dock is not None:
            self.dock.shutdown()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None

        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None

    def run(self):
        self.open_workspace()

    def open_workspace(self):
        self.workspace_dialog = FortSmartWorkspaceDialog(self.iface)
        self.workspace_dialog.show()
        self.workspace_dialog.raise_()

    def open_strategy_analyzer(self):
        """Usa talhao/A-B/plantadeira do Planejamento aberto (abre-o se preciso)."""
        if self.workspace_dialog is None or not self.workspace_dialog.isVisible():
            self.open_workspace()
        self.workspace_dialog._open_strategy_analyzer()

    def open_panel(self):
        if self.dock is None:
            workspace_root = Path(__file__).resolve().parents[2]
            default_project = workspace_root / "Projeto_FortSmart_Teste"
            project_root = default_project if (default_project / "fortsmart_project.json").exists() else None
            self.dock = FortSmartDock(self.iface, project_root=project_root)
            self.dock.set_tool_actions(self._tool_actions())
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.show()
        self.dock.raise_()
        self.dock.refresh()

    def _tool_actions(self):
        """Mesmas QActions do menu; o painel AgroCAD so as aciona."""
        from .core import agrocad_tools as tools

        return {
            tools.PLUGIN_WORKSPACE: self.action_workspace,
            tools.PLUGIN_HEADLAND_TURNS: self.action_headland_turns,
            tools.PLUGIN_STRATEGY_ANALYZER: self.action_strategy_analyzer,
            tools.PLUGIN_OBSTACLE_DETOUR: self.action_obstacle_detour,
            tools.PLUGIN_LINE_CUT: self.action_line_cut,
            tools.PLUGIN_OPERATION_SIMULATOR: self.action_operation_simulator,
            tools.PLUGIN_COVERAGE_XRAY: self.action_coverage_xray,
            tools.PLUGIN_EXPORT_READINESS: self.action_export_readiness,
            tools.PLUGIN_CRS_CONVERTER: self.action_crs_converter,
        }

    def create_project(self):
        self.open_panel()
        self.dock.create_project_dialog()

    def open_project(self):
        self.open_panel()
        self.dock.choose_project()

    def import_layer(self):
        self.open_panel()
        self.dock.open_import_dialog()

    def open_crs_converter(self):
        dialog = CrsZoneConverterDialog(self.iface)
        dialog.exec_()

    def open_line_cut(self):
        self.line_cut_dialog = PlantingLineCutDialog(self.iface)
        self.line_cut_dialog.show()
        self.line_cut_dialog.raise_()

    def open_obstacle_detour(self):
        if self.obstacle_detour_dialog is None:
            self.obstacle_detour_dialog = ObstacleDetourDialog(self.iface)
        self.obstacle_detour_dialog.show()
        self.obstacle_detour_dialog.raise_()

    def open_headland_turns(self):
        self.headland_turns_dialog = HeadlandTurnsDialog(self.iface)
        self.headland_turns_dialog.show()
        self.headland_turns_dialog.raise_()

    def organize_layers(self):
        report = normalize_legacy_project_layers()
        QMessageBox.information(self.iface.mainWindow(), "FortSmart Precision", report["text"])

    def persist_layers(self):
        try:
            report = persist_generated_memory_layers()
        except PersistenceError as exc:
            QMessageBox.warning(self.iface.mainWindow(), "FortSmart Precision", str(exc))
            return
        QMessageBox.information(self.iface.mainWindow(), "FortSmart Precision", report["text"])

    def open_route_simulator(self):
        from .gui.route_simulation_dialog import RouteSimulationDialog

        if self.route_simulation_dialog is None:
            self.route_simulation_dialog = RouteSimulationDialog(self.iface)
        self.route_simulation_dialog.show()
        self.route_simulation_dialog.raise_()

    def open_operation_simulator(self):
        try:
            import processing
        except ImportError:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "FortSmart Precision",
                "O plugin Processing do QGIS precisa estar ativo para abrir o Raio-X de cobertura.",
            )
            return
        processing.execAlgorithmDialog(OPERATION_SIMULATOR_ALGORITHM_ID, {})

    def open_export_readiness(self):
        self.export_readiness_dialog = ExportReadinessDialog(self.iface)
        self.export_readiness_dialog.show()
        self.export_readiness_dialog.raise_()

    def show_about(self):
        QMessageBox.information(
            self.iface.mainWindow(),
            "FortSmart Precision",
            "FortSmart Precision Lines\n\n"
            "Workspace unificado:\n"
            "• Cadastro livre de plantadeira e pulverizador (padrao monitores)\n"
            "• Bordadura, passadas, linhas, tramlines, shutoff\n"
            "• Desvio de obstaculos (aplicacao e plantio)\n"
            "• Simulador de Operacao (maquina percorrendo as passadas)\n"
            "• Raio-X de cobertura (falhas e remonte)\n"
            "• Conversor de zona UTM / CRS\n\n"
            "Use: FortSmart Precision → Planejamento Precision Lines",
        )
