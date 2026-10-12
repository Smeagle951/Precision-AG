# -*- coding: utf-8 -*-
"""Tela inicial simples para quando nenhum projeto esta aberto."""

from __future__ import annotations

from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


class StartPage(QWidget):
    createProjectRequested = pyqtSignal()
    openProjectRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        title = QLabel("FortSmart Precision")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        subtitle = QLabel("Crie ou abra um projeto para iniciar a importacao segura de dados.")
        subtitle.setWordWrap(True)
        self.btn_create = QPushButton("Criar novo projeto")
        self.btn_open = QPushButton("Abrir projeto existente")
        self.btn_create.clicked.connect(self.createProjectRequested.emit)
        self.btn_open.clicked.connect(self.openProjectRequested.emit)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.btn_create)
        layout.addWidget(self.btn_open)
        layout.addStretch()

