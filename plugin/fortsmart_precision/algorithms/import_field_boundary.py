# -*- coding: utf-8 -*-
"""Algoritmo Processing para importar limite de talhao de forma nao destrutiva."""

from __future__ import annotations

import json

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFile,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterString,
    QgsProcessingOutputString,
)

from ..io.import_service import ImportService


class ImportFieldBoundaryAlgorithm(QgsProcessingAlgorithm):
    PROJECT_ROOT = "PROJECT_ROOT"
    INPUT = "INPUT"
    X_FIELD = "X_FIELD"
    Y_FIELD = "Y_FIELD"
    DELIMITER = "DELIMITER"
    CRS_AUTHID = "CRS_AUTHID"
    REPORT = "REPORT"

    def tr(self, text):
        return QCoreApplication.translate("FortSmartPrecision", text)

    def createInstance(self):
        return ImportFieldBoundaryAlgorithm()

    def name(self):
        return "import_field_boundary"

    def displayName(self):
        return self.tr("Importar limite de talhao")

    def group(self):
        return self.tr("Importacao")

    def groupId(self):
        return "import"

    def shortHelpString(self):
        return self.tr("Copia o original, valida e registra importacao no projeto FortSmart.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFolderDestination(self.PROJECT_ROOT, self.tr("Pasta do projeto FortSmart")))
        self.addParameter(QgsProcessingParameterFile(self.INPUT, self.tr("Arquivo de entrada")))
        self.addParameter(QgsProcessingParameterString(self.X_FIELD, self.tr("Campo X/longitude para CSV"), optional=True))
        self.addParameter(QgsProcessingParameterString(self.Y_FIELD, self.tr("Campo Y/latitude para CSV"), optional=True))
        self.addParameter(QgsProcessingParameterString(self.DELIMITER, self.tr("Separador CSV"), defaultValue=";", optional=True))
        self.addParameter(QgsProcessingParameterString(self.CRS_AUTHID, self.tr("CRS do CSV, ex. EPSG:4326"), optional=True))
        self.addOutput(QgsProcessingOutputString(self.REPORT, self.tr("Relatorio JSON")))

    def processAlgorithm(self, parameters, context, feedback):
        result = ImportService().import_field_boundary(
            self.parameterAsString(parameters, self.PROJECT_ROOT, context),
            self.parameterAsFile(parameters, self.INPUT, context),
            x_field=self.parameterAsString(parameters, self.X_FIELD, context) or None,
            y_field=self.parameterAsString(parameters, self.Y_FIELD, context) or None,
            delimiter=self.parameterAsString(parameters, self.DELIMITER, context) or None,
            crs_authid=self.parameterAsString(parameters, self.CRS_AUTHID, context) or None,
        )
        report = result.to_dict()
        feedback.pushInfo(json.dumps(report, ensure_ascii=False, indent=2))
        return {self.REPORT: json.dumps(report, ensure_ascii=False)}

