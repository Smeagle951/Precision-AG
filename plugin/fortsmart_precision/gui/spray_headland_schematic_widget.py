# -*- coding: utf-8 -*-
"""Esquema da 1a passada de bordadura: limite, linha central e barra fisica."""

from __future__ import annotations

from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QBrush, QColor, QPainter, QPen
from qgis.PyQt.QtWidgets import QSizePolicy, QWidget

from ..core.spray_headland_preview import format_m, spray_headland_schematic_layout


class SprayHeadlandSchematicWidget(QWidget):
    """Barra fisica com a parte fora (laranja) e dentro (verde) do limite."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.boom_width_m = 0.0
        self.outside_overlap_m = 0.0
        self.center_offset_m = 0.0

    def set_geometry(self, *, boom_width_m: float, outside_overlap_m: float) -> None:
        self.boom_width_m = boom_width_m
        self.outside_overlap_m = outside_overlap_m
        self.center_offset_m = boom_width_m / 2.0 - outside_overlap_m
        self.update()

    def layout_data(self) -> dict[str, float | bool]:
        return spray_headland_schematic_layout(
            boom_width_m=self.boom_width_m,
            outside_overlap_m=self.outside_overlap_m,
            width_px=float(max(self.width(), 240)),
            height_px=float(max(self.height(), 110)),
        )

    def paintEvent(self, _event):
        data = self.layout_data()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(250, 250, 247))
        width = float(max(self.width(), 240))
        height = float(max(self.height(), 110))
        if not data.get("valid"):
            painter.end()
            return

        boundary_x = float(data["boundary_x"])
        painter.fillRect(QRectF(0, 0, boundary_x, height), QColor(235, 228, 220))
        painter.fillRect(QRectF(boundary_x, 0, width - boundary_x, height), QColor(228, 240, 226))
        painter.setPen(QPen(QColor(60, 60, 60), 2))
        painter.drawLine(QPointF(boundary_x, 4), QPointF(boundary_x, height - 4))
        painter.setPen(QPen(QColor(80, 80, 80), 1))
        painter.drawText(QRectF(4, 2, boundary_x - 6, 16), Qt.AlignRight, "Fora")
        painter.drawText(QRectF(boundary_x + 4, 2, 160, 16), Qt.AlignLeft, "Limite do talhao")

        center_x = float(data["center_x"])
        painter.setPen(QPen(QColor(20, 60, 160), 1, Qt.DashLine))
        painter.drawLine(QPointF(center_x, 18), QPointF(center_x, height - 4))
        painter.drawText(
            QRectF(center_x + 4, 18, width - center_x - 6, 16),
            Qt.AlignLeft,
            f"Linha central {format_m(self.center_offset_m)}",
        )

        bar_y = float(data["bar_y"])
        left_x = float(data["boom_left_x"])
        right_x = float(data["boom_right_x"])
        if data["has_outside"]:
            painter.setPen(QPen(QColor(220, 110, 20), 6, Qt.SolidLine, Qt.FlatCap))
            painter.drawLine(QPointF(left_x, bar_y), QPointF(boundary_x, bar_y))
        painter.setPen(QPen(QColor(30, 140, 60), 6, Qt.SolidLine, Qt.FlatCap))
        painter.drawLine(QPointF(max(left_x, boundary_x), bar_y), QPointF(right_x, bar_y))
        painter.setBrush(QBrush(QColor(20, 90, 220)))
        painter.setPen(QPen(QColor(20, 60, 160), 1))
        painter.drawEllipse(QPointF(center_x, bar_y), 4, 4)
        painter.setPen(QPen(QColor(40, 40, 40), 1))
        painter.drawText(
            QRectF(4, bar_y + 8, width - 8, 16),
            Qt.AlignHCenter,
            f"Barra fisica {format_m(self.boom_width_m)} | "
            f"fora {format_m(self.outside_overlap_m)} | "
            f"dentro {format_m(self.boom_width_m - self.outside_overlap_m)}",
        )
        painter.end()
