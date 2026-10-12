# -*- coding: utf-8 -*-
"""Algoritmo minimo para validar instalacao do provider."""

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingOutputString,
)


class HealthCheckAlgorithm(QgsProcessingAlgorithm):
    OUTPUT = "OUTPUT"

    def tr(self, text):
        return QCoreApplication.translate("FortSmartPrecision", text)

    def createInstance(self):
        return HealthCheckAlgorithm()

    def name(self):
        return "health_check"

    def displayName(self):
        return self.tr("Verificar instalacao FortSmart")

    def group(self):
        return self.tr("Sistema")

    def groupId(self):
        return "system"

    def shortHelpString(self):
        return self.tr(
            "Confirma que o provider FortSmart Precision esta carregado. "
            "Este algoritmo nao altera dados."
        )

    def initAlgorithm(self, config=None):
        self.addOutput(QgsProcessingOutputString(self.OUTPUT, self.tr("Status")))

    def processAlgorithm(self, parameters, context, feedback):
        feedback.pushInfo("FortSmart Precision Provider ativo.")
        feedback.pushInfo("Fase atual: fundacao e auditoria do legado AAP GIS.")
        return {self.OUTPUT: "OK"}

