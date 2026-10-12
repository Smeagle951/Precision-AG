# -*- coding: utf-8 -*-
"""Worker em thread para geracao Precision Lines sem travar a UI do QGIS."""

from __future__ import annotations

from qgis.PyQt.QtCore import QThread, pyqtSignal

from ..core.precision_lines_engine import run_precision_lines
from ..domain.precision_project import PrecisionProject


class PrecisionLinesWorker(QThread):
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, project: PrecisionProject, parent=None) -> None:
        super().__init__(parent)
        self._project = project

    def run(self) -> None:
        try:
            result = run_precision_lines(
                self._project,
                progress=lambda pct, msg: self.progress.emit(pct, msg),
            )
            self.finished_ok.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
