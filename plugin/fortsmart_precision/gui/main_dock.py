# -*- coding: utf-8 -*-
"""Painel lateral principal do FortSmart Precision."""

from __future__ import annotations

from pathlib import Path

from qgis.PyQt.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QDockWidget,
)
from qgis.core import QgsRasterLayer, QgsVectorLayer

from ..core.project_manager import create_project
from .import_wizard import ImportWizard
from .start_page import StartPage
from .widgets.layer_summary_widget import LayerSummaryWidget
from .widgets.project_status_widget import ProjectStatusWidget


class FortSmartDock(QDockWidget):
    """Painel que mostra estado do projeto/camada e abre assistentes."""

    def __init__(self, iface, project_root=None, parent=None):
        super().__init__("FortSmart Precision", parent or iface.mainWindow())
        self.iface = iface
        self.project_root = Path(project_root) if project_root else None
        self._layer_signal_connected = False
        self._build_ui()
        self._connect_qgis_signals()
        self.refresh()

    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)

        self.stack = QStackedWidget()
        self.start_page = StartPage()
        self.start_page.createProjectRequested.connect(self.create_project_dialog)
        self.start_page.openProjectRequested.connect(self.choose_project)

        self.main_page = QWidget()
        main_layout = QVBoxLayout(self.main_page)
        self.project_widget = ProjectStatusWidget()
        self.layer_widget = LayerSummaryWidget("CAMADA ATIVA")
        main_layout.addWidget(self.project_widget)
        main_layout.addWidget(self.layer_widget)

        actions = QGroupBox("ACOES RAPIDAS")
        actions_layout = QVBoxLayout(actions)
        row1 = QHBoxLayout()
        self.btn_create = QPushButton("Criar projeto")
        self.btn_open = QPushButton("Abrir projeto")
        row1.addWidget(self.btn_create)
        row1.addWidget(self.btn_open)
        row2 = QHBoxLayout()
        self.btn_import = QPushButton("Importar")
        self.btn_validate = QPushButton("Validar")
        row2.addWidget(self.btn_import)
        row2.addWidget(self.btn_validate)
        row3 = QHBoxLayout()
        self.btn_plan = QPushButton("Planejar")
        self.btn_export = QPushButton("Exportar")
        row3.addWidget(self.btn_plan)
        row3.addWidget(self.btn_export)
        actions_layout.addLayout(row1)
        actions_layout.addLayout(row2)
        actions_layout.addLayout(row3)
        main_layout.addWidget(actions)
        main_layout.addStretch()

        self.btn_create.clicked.connect(self.create_project_dialog)
        self.btn_open.clicked.connect(self.choose_project)
        self.btn_import.clicked.connect(self.open_import_dialog)
        self.btn_validate.setEnabled(False)
        self.btn_plan.setEnabled(False)
        self.btn_export.setEnabled(False)

        self.stack.addWidget(self.start_page)
        self.stack.addWidget(self.main_page)
        layout.addWidget(self.stack)
        self.setWidget(root)
        self._root_layout = layout
        self.tabs = None
        self.agrocad = None
        self.organizer = None
        self.context_service = None
        self._tool_actions = {}

    def apply_feature_flags(self):
        """Abas 'AgroCAD' e 'Camadas' por flag; com as duas desligadas o painel fica como antes."""
        from ..feature_flags import ENABLE_AGROCAD_PANEL_V1, ENABLE_LAYER_ORGANIZER_V1, is_enabled

        want_agrocad = is_enabled(ENABLE_AGROCAD_PANEL_V1)
        want_layers = is_enabled(ENABLE_LAYER_ORGANIZER_V1)
        if (want_agrocad or want_layers) and self.tabs is None:
            self.tabs = QTabWidget()
            self._root_layout.removeWidget(self.stack)
            self.tabs.addTab(self.stack, "Projeto")
            self._root_layout.addWidget(self.tabs)
        if self.tabs is None:
            return
        if want_agrocad and self.agrocad is None:
            from .agrocad_panel import AgroCadPanel

            self.agrocad = AgroCadPanel(
                self.iface, service=self._shared_context(), tool_actions=self._tool_actions, parent=self.tabs
            )
            self.tabs.insertTab(1, self.agrocad, "AgroCAD")
        elif not want_agrocad and self.agrocad is not None:
            self.agrocad = self._drop_tab(self.agrocad)
        if self.agrocad is not None:
            self.agrocad.apply_feature_flags()
        if want_layers and self.organizer is None:
            from .layer_organizer_panel import LayerOrganizerPanel

            self.organizer = LayerOrganizerPanel(self.iface, parent=self.tabs, service=self._shared_context())
            self.tabs.addTab(self.organizer, "Camadas")
        elif not want_layers and self.organizer is not None:
            self.organizer = self._drop_tab(self.organizer)
        if not (want_agrocad or want_layers):
            self._root_layout.removeWidget(self.tabs)
            self.tabs.removeTab(self.tabs.indexOf(self.stack))
            self._root_layout.addWidget(self.stack)
            self.stack.show()
            self.tabs.deleteLater()
            self.tabs = None
            self.context_service = None

    def _shared_context(self):
        """Um contexto so para as abas: o talhao escolhido vale para AgroCAD e Camadas."""
        if self.context_service is None:
            from ..core.project_context import ProjectContextService

            self.context_service = ProjectContextService(None, self.iface)
        return self.context_service

    def _drop_tab(self, panel):
        panel.shutdown()
        self.tabs.removeTab(self.tabs.indexOf(panel))
        panel.deleteLater()
        return None

    def set_tool_actions(self, mapping):
        """Acoes existentes do plugin que o AgroCAD pode acionar (mesmas do menu)."""
        self._tool_actions = dict(mapping or {})
        if self.agrocad is not None:
            self.agrocad.set_tool_actions(self._tool_actions)

    def _connect_qgis_signals(self):
        if self._layer_signal_connected:
            return
        try:
            self.iface.currentLayerChanged.connect(self.on_current_layer_changed)
            self._layer_signal_connected = True
        except Exception:
            pass

    def _disconnect_qgis_signals(self):
        try:
            self.iface.currentLayerChanged.disconnect(self.on_current_layer_changed)
        except Exception:
            pass
        self._layer_signal_connected = False

    def showEvent(self, event):
        super().showEvent(event)
        if not self._layer_signal_connected:
            self._connect_qgis_signals()
            self.refresh_layer()

    def closeEvent(self, event):
        self._disconnect_qgis_signals()
        super().closeEvent(event)

    def shutdown(self):
        """Descarregamento do plugin: nenhum sinal do QGIS fica apontando para o dock."""
        self._disconnect_qgis_signals()
        for panel in (self.agrocad, self.organizer):
            if panel is not None:
                panel.shutdown()

    def on_current_layer_changed(self, layer):
        self.refresh_layer()

    def set_project_root(self, project_root):
        self.project_root = Path(project_root) if project_root else None
        self.refresh()

    def create_project_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, "Pasta do novo projeto FortSmart", str(Path.home()))
        if not folder:
            return
        project_name, ok = QInputDialog.getText(self, "Novo projeto", "Nome do projeto:")
        if not ok or not project_name.strip():
            return
        property_name, ok = QInputDialog.getText(self, "Novo projeto", "Fazenda/propriedade:")
        if not ok or not property_name.strip():
            return
        season_name, ok = QInputDialog.getText(self, "Novo projeto", "Safra:", text="2026/27")
        if not ok or not season_name.strip():
            return
        crs_authid, ok = QInputDialog.getText(self, "Novo projeto", "CRS mestre:", text="EPSG:31981")
        if not ok or not crs_authid.strip():
            return
        try:
            create_project(
                folder,
                project_name=project_name.strip(),
                property_name=property_name.strip(),
                season_name=season_name.strip(),
                master_crs=crs_authid.strip(),
                created_by="qgis_gui",
            )
            self.set_project_root(folder)
            QMessageBox.information(self, "FortSmart Precision", "Projeto criado com sucesso.")
        except Exception as exc:
            QMessageBox.critical(self, "FortSmart Precision", f"Erro ao criar projeto:\n{exc}")

    def choose_project(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Selecione a pasta do projeto FortSmart",
            str(self.project_root or Path.home()),
        )
        if folder:
            self.set_project_root(folder)

    def active_layer(self):
        return self.iface.activeLayer()

    def refresh(self):
        self.apply_feature_flags()
        if self.project_root:
            self.stack.setCurrentWidget(self.main_page)
            self.project_widget.set_project_root(self.project_root)
        else:
            self.stack.setCurrentWidget(self.start_page)
        self.refresh_layer()
        self._update_actions()

    def refresh_layer(self):
        layer = self.active_layer()
        if isinstance(layer, (QgsVectorLayer, QgsRasterLayer)):
            self.layer_widget.set_layer(layer)
        else:
            self.layer_widget.set_no_layer()
        self._update_actions()

    def _update_actions(self):
        has_project = self.project_root is not None
        has_vector = isinstance(self.active_layer(), QgsVectorLayer) and self.active_layer().isValid()
        self.btn_import.setEnabled(has_project)
        self.btn_validate.setEnabled(False)
        self.btn_plan.setEnabled(False)
        self.btn_export.setEnabled(False)

    def open_import_dialog(self):
        if not self.project_root:
            QMessageBox.warning(self, "FortSmart Precision", "Crie ou abra um projeto antes de importar.")
            return
        dialog = ImportWizard(self.iface, self.project_root, self)
        if dialog.exec_():
            self.refresh()

    # Compatibilidade com o menu antigo.
    def open_import_active_dialog(self):
        self.open_import_dialog()

