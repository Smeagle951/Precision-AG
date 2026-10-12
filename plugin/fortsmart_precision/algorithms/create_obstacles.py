# -*- coding: utf-8 -*-
"""Algoritmo Processing: cadastro de obstaculos a partir de pontos."""

from __future__ import annotations

import json

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputString,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
)

from ..core.crs import CrsValidationError, require_projected_metric
from ..domain.obstacle_model import obstacle_from_point
from ..gui.agricultural_lines_dialog import to_qgs_point


class CreateObstaclesAlgorithm(QgsProcessingAlgorithm):
    OBSTACLES = "OBSTACLES"
    RADIUS = "RADIUS"
    MARGIN = "MARGIN"
    REPORT = "REPORT"

    def tr(self, text):
        return QCoreApplication.translate("FortSmartPrecision", text)

    def createInstance(self):
        return CreateObstaclesAlgorithm()

    def name(self):
        return "create_obstacles"

    def displayName(self):
        return self.tr("Cadastrar obstaculos (pontos)")

    def group(self):
        return self.tr("Precision Lines")

    def groupId(self):
        return "precision_lines"

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.OBSTACLES, self.tr("Pontos"), [QgsProcessing.TypeVectorPoint]
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.RADIUS, self.tr("Raio fisico (m)"), defaultValue=0.0, minValue=0.0
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MARGIN, self.tr("Margem (m)"), defaultValue=0.0, minValue=0.0
            )
        )
        self.addOutput(QgsProcessingOutputString(self.REPORT, self.tr("Obstaculos JSON")))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.OBSTACLES, context)
        if source is None:
            raise QgsProcessingException(self.tr("Camada de pontos obrigatoria."))
        try:
            require_projected_metric(source.sourceCrs().authid())
        except CrsValidationError as exc:
            raise QgsProcessingException(str(exc)) from exc

        radius = self.parameterAsDouble(parameters, self.RADIUS, context)
        margin = self.parameterAsDouble(parameters, self.MARGIN, context)
        items = []
        for feat in source.getFeatures():
            pt = feat.geometry().asPoint()
            obs = obstacle_from_point(
                to_qgs_point((pt.x(), pt.y())),
                obstacle_radius_m=radius,
                safety_margin_m=margin,
                name=str(feat.id()),
            )
            items.append(
                {
                    "obstacle_id": obs.obstacle_id,
                    "center": obs.center,
                    "obstacle_radius_m": obs.obstacle_radius_m,
                    "safety_margin_m": obs.safety_margin_m,
                }
            )
        text = json.dumps(items, indent=2)
        feedback.pushInfo(text)
        return {self.REPORT: text}
