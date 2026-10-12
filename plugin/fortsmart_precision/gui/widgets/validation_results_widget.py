# -*- coding: utf-8 -*-
"""Tabela de resultados de validacao."""

from __future__ import annotations

from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class ValidationResultsWidget(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Validação", parent)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Gravidade", "Codigo", "Descricao", "Feicao", "Acao"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.table)

    def set_messages(self, messages, locate_callback=None):
        self.table.setRowCount(0)
        for msg in messages:
            row = self.table.rowCount()
            self.table.insertRow(row)
            severity = getattr(msg, "severity", None) or msg.get("severity", "")
            code = getattr(msg, "code", None) or msg.get("code", "")
            text = getattr(msg, "message", None) or msg.get("message", "")
            feature_id = getattr(msg, "feature_id", None) or msg.get("feature_id")
            for col, value in enumerate([severity, code, text, feature_id or "-"]):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))
            btn = QPushButton("Localizar")
            btn.setEnabled(bool(feature_id and locate_callback))
            if feature_id and locate_callback:
                btn.clicked.connect(lambda checked=False, fid=feature_id: locate_callback(fid))
            self.table.setCellWidget(row, 4, btn)

