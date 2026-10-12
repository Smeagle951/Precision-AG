# -*- coding: utf-8 -*-
"""Widget de status do projeto FortSmart."""

from __future__ import annotations

from pathlib import Path

from qgis.PyQt.QtWidgets import QFormLayout, QGroupBox, QLabel

from ...core.project_manager import validate_project


class ProjectStatusWidget(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("PROJETO ATUAL", parent)
        self.project_root = None
        layout = QFormLayout(self)
        self.lbl_project = QLabel("-")
        self.lbl_property = QLabel("-")
        self.lbl_season = QLabel("-")
        self.lbl_crs = QLabel("-")
        self.lbl_status = QLabel("Projeto nao selecionado")
        layout.addRow("Projeto:", self.lbl_project)
        layout.addRow("Fazenda:", self.lbl_property)
        layout.addRow("Safra:", self.lbl_season)
        layout.addRow("CRS:", self.lbl_crs)
        layout.addRow("Status:", self.lbl_status)

    def set_project_root(self, project_root):
        self.project_root = Path(project_root) if project_root else None
        return self.refresh()

    def refresh(self):
        if not self.project_root:
            self.lbl_project.setText("-")
            self.lbl_property.setText("-")
            self.lbl_season.setText("-")
            self.lbl_crs.setText("-")
            self.lbl_status.setText("Projeto nao selecionado")
            return {"status": "missing", "errors": ["Projeto nao selecionado"], "warnings": [], "config": None}

        validation = validate_project(self.project_root)
        config = validation.get("config") or {}
        self.lbl_project.setText(config.get("project_name", "-"))
        self.lbl_property.setText(config.get("property_name", "-"))
        self.lbl_season.setText(config.get("season_name", "-"))
        self.lbl_crs.setText(config.get("master_crs", "-"))
        self.lbl_status.setText(validation["status"])
        return validation

