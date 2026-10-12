# -*- coding: utf-8 -*-
"""Algoritmo Processing para inspecionar arquivo de entrada."""

from __future__ import annotations

import json

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFile,
    QgsProcessingOutputString,
)

from ..io.input_inspector import InputInspector
from ..validators.input_validator import InputValidator


class InspectInputAlgorithm(QgsProcessingAlgorithm):
    INPUT = "INPUT"
    REPORT = "REPORT"

    def tr(self, text):
        return QCoreApplication.translate("FortSmartPrecision", text)

    def createInstance(self):
        return InspectInputAlgorithm()

    def name(self):
        return "inspect_input"

    def displayName(self):
        return self.tr("Inspecionar arquivo de entrada")

    def group(self):
        return self.tr("Importacao")

    def groupId(self):
        return "import"

    def shortHelpString(self):
        return self.tr("Inspeciona arquivo vetorial sem alterar nem importar.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(self.INPUT, self.tr("Arquivo de entrada")))
        self.addOutput(QgsProcessingOutputString(self.REPORT, self.tr("Relatorio JSON")))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsFile(parameters, self.INPUT, context)
        inspection = InputInspector().inspect(source)
        validation = InputValidator().validate(inspection)
        report = validation.to_dict()
        feedback.pushInfo(json.dumps(report, ensure_ascii=False, indent=2))
        return {self.REPORT: json.dumps(report, ensure_ascii=False)}

