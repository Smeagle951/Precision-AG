# -*- coding: utf-8 -*-
"""Dialogo de progresso + thread para geracao Precision Lines."""

from __future__ import annotations

from qgis.PyQt.QtCore import QEventLoop, Qt
from qgis.PyQt.QtWidgets import QProgressBar, QProgressDialog, QWidget

from ..domain.precision_project import PrecisionProject
from .precision_lines_worker import PrecisionLinesWorker


def run_precision_lines_with_progress(
    parent: QWidget,
    project: PrecisionProject,
    *,
    title: str = "FortSmart — Gerando linhas",
    bar: QProgressBar | None = None,
):
    """Executa o pipeline em thread secundaria com barra/modal de progresso."""
    dialog = QProgressDialog("Preparando geracao...", None, 0, 100, parent)
    dialog.setWindowTitle(title)
    dialog.setWindowModality(Qt.WindowModal)
    dialog.setMinimumDuration(0)
    dialog.setValue(0)
    dialog.setAutoClose(True)
    dialog.setAutoReset(False)
    dialog.setMinimumWidth(420)

    if bar is not None:
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.show()

    worker = PrecisionLinesWorker(project, parent=parent)
    loop = QEventLoop()
    result_holder: list[object] = []
    error_holder: list[str] = []

    def _apply_progress(percent: int, message: str) -> None:
        dialog.setValue(percent)
        dialog.setLabelText(message)
        if bar is not None:
            bar.setValue(percent)
            bar.setFormat(f"%p% — {message[:42]}")

    def _on_ok(result) -> None:
        result_holder.append(result)
        loop.quit()

    def _on_fail(message: str) -> None:
        error_holder.append(message)
        loop.quit()

    worker.progress.connect(_apply_progress)
    worker.finished_ok.connect(_on_ok)
    worker.failed.connect(_on_fail)
    worker.finished.connect(dialog.close)

    dialog.show()
    _apply_progress(0, "Iniciando geracao...")
    worker.start()
    loop.exec_()

    if error_holder:
        if bar is not None:
            bar.hide()
        raise ValueError(error_holder[0])
    if not result_holder:
        if bar is not None:
            bar.hide()
        raise RuntimeError("Geracao interrompida sem resultado.")

    _apply_progress(100, "Geracao concluida.")
    if bar is not None:
        bar.hide()
    return result_holder[0]
