# -*- coding: utf-8 -*-
"""Relatorio visual, somente leitura, de prontidao canonica para exportacao."""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsMessageLog, QgsProject, Qgis

from ..core.export_readiness_validator import (
    CANONICAL_NOT_READY,
    CANONICAL_READY,
    CanonicalExportReadinessValidator,
    ExportReadinessReport,
    available_export_field_ids,
    resolve_export_field_id,
)


class ExportReadinessDialog(QDialog):
    """Seleciona um talhao e apresenta diagnostico sem alterar o projeto."""

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.validator = CanonicalExportReadinessValidator()
        self.last_report: ExportReadinessReport | None = None
        self.setWindowTitle("FortSmart Precision - Validar projeto para exportacao")
        self.resize(920, 680)

        layout = QVBoxLayout(self)
        selector = QHBoxLayout()
        selector.addWidget(QLabel("Talhao:"))
        self.field_combo = QComboBox()
        self.field_combo.setMinimumWidth(280)
        selector.addWidget(self.field_combo, 1)
        self.refresh_button = QPushButton("Atualizar")
        self.validate_button = QPushButton("Validar")
        selector.addWidget(self.refresh_button)
        selector.addWidget(self.validate_button)
        layout.addLayout(selector)

        self.status_label = QLabel("Selecione um talhao e execute a validacao.")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-weight: 600; padding: 7px;")
        layout.addWidget(self.status_label)

        tabs = QTabWidget()
        layout.addWidget(tabs, 1)

        summary_page = QWidget()
        summary_layout = QVBoxLayout(summary_page)
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        summary_layout.addWidget(self.summary_label)
        self.role_table = QTableWidget(0, 5)
        self.role_table.setHorizontalHeaderLabels(
            ["Role", "Camadas", "Feicoes", "Geometria", "Status"]
        )
        self.role_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.role_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.role_table.horizontalHeader().setStretchLastSection(True)
        summary_layout.addWidget(self.role_table, 1)
        tabs.addTab(summary_page, "Objetos")

        self.issue_table = QTableWidget(0, 4)
        self.issue_table.setHorizontalHeaderLabels(
            ["Severidade", "Codigo", "Role/Camada", "Mensagem"]
        )
        self.issue_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.issue_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.issue_table.horizontalHeader().setStretchLastSection(True)
        tabs.addTab(self.issue_table, "Diagnosticos")

        self.technical_log = QTextEdit()
        self.technical_log.setReadOnly(True)
        tabs.addTab(self.technical_log, "Log tecnico")

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.refresh_button.clicked.connect(self.refresh_fields)
        self.validate_button.clicked.connect(self.validate_selected)
        self.refresh_fields()

    def selected_field_id(self) -> str:
        return str(self.field_combo.currentData() or "")

    def refresh_fields(self) -> None:
        project = QgsProject.instance()
        active_field = resolve_export_field_id(self.iface.activeLayer(), project)
        current = self.selected_field_id() or active_field
        self.field_combo.blockSignals(True)
        self.field_combo.clear()
        for field_id in available_export_field_ids(project):
            self.field_combo.addItem(field_id, field_id)
        preferred = self.field_combo.findData(current)
        if preferred >= 0:
            self.field_combo.setCurrentIndex(preferred)
        self.field_combo.blockSignals(False)
        self.validate_button.setEnabled(self.field_combo.count() > 0)
        if self.field_combo.count() == 0:
            self.status_label.setText(
                "Nenhum talhao canonico foi encontrado. Gere ou organize as camadas FortSmart."
            )

    def validate_selected(self) -> None:
        field_id = self.selected_field_id()
        if not field_id:
            QMessageBox.warning(self, "FortSmart Precision", "Selecione um talhao para validar.")
            return
        report = self.validator.validate(field_id, project=QgsProject.instance())
        self.render_report(report)
        QgsMessageLog.logMessage(
            report.to_json(), "FortSmart Export Readiness", Qgis.Info
        )

    def render_report(self, report: ExportReadinessReport) -> None:
        self.last_report = report
        color = "#1b5e20" if report.status == CANONICAL_READY else (
            "#b00020" if report.status == CANONICAL_NOT_READY else "#8a5400"
        )
        self.status_label.setText(report.status)
        self.status_label.setStyleSheet(
            f"font-weight: 700; padding: 7px; color: {color};"
        )
        self.summary_label.setText(
            f"Talhao: {report.field_name} | Area: {report.area_ha:.2f} ha | "
            f"CRS: {report.crs or 'nao identificado'}"
        )

        self.role_table.setRowCount(len(report.role_report))
        for row, item in enumerate(report.role_report):
            values = (
                item.role,
                item.layer_count,
                item.feature_count,
                "/".join(item.geometry_types),
                item.status,
            )
            for column, value in enumerate(values):
                self.role_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.role_table.resizeColumnsToContents()

        self.issue_table.setRowCount(len(report.issues))
        colors = {
            "ERROR": QColor("#b00020"),
            "WARNING": QColor("#8a5400"),
            "INFO": QColor("#245b8a"),
        }
        for row, issue in enumerate(report.issues):
            context = " / ".join(value for value in (issue.role, issue.layer_name) if value)
            values = (issue.severity, issue.code, context, issue.message)
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if column == 0:
                    cell.setForeground(colors.get(issue.severity, QColor(Qt.black)))
                self.issue_table.setItem(row, column, cell)
        self.issue_table.resizeColumnsToContents()
        self.technical_log.setPlainText(report.to_json())
