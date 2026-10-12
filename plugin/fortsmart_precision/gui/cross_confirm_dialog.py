# -*- coding: utf-8 -*-
"""Confirmacao de bitola/largura antes do cruzamento shutoff."""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..domain.machine_model import PlanterMachine, SprayerMachine


class CrossConfirmDialog(QDialog):
    """Resume maquinas e fontes antes de calcular LIGA/DESLIGA."""

    def __init__(
        self,
        parent,
        *,
        planter: PlanterMachine,
        sprayer: SprayerMachine,
        plant_count: int,
        spray_count: int,
        plant_source: str,
        spray_source: str,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("FortSmart — Confirmar cruzamento")
        self.setMinimumWidth(480)
        self.setMaximumHeight(520)

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.addWidget(
            QLabel(
                "Confirme as configuracoes das maquinas. "
                "O shutoff cruza linhas de plantio com os rastros da pulverizacao."
            )
        )

        form = QFormLayout()
        track = sprayer.effective_track
        traffic = sprayer.traffic
        margin = traffic.safety_margin_m if traffic is not None else 0.0
        exclusion_width = traffic.exclusion_width_m if traffic is not None else track.tire_width_m
        form.addRow(
            QLabel("<b>Plantio</b>"),
            QLabel(
                f"{planter.name} — {planter.row_count} linhas × "
                f"{planter.row_spacing_m:.2f} m "
                f"(largura {planter.operational_width_m:.2f} m)"
            ),
        )
        form.addRow("Passadas plantio:", QLabel(f"{plant_count} ({plant_source})"))
        form.addRow(
            QLabel("<b>Pulverizacao</b>"),
            QLabel(
                f"{sprayer.name} — barra {sprayer.operational_width_m:.2f} m | "
                f"bitola {track.track_width_m:.2f} m | "
                f"pneu {track.tire_width_m:.2f} m | margem {margin:.2f} m/lado | "
                f"faixa de exclusao {exclusion_width:.2f} m"
            ),
        )
        form.addRow("Passadas aplicacao:", QLabel(f"{spray_count} ({spray_source})"))
        layout.addLayout(form)

        scroll.setWidget(content)
        outer.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
