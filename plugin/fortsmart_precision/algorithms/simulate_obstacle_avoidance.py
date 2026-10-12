# -*- coding: utf-8 -*-
"""Algoritmo Processing: simular desvio de obstaculos."""

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
    QgsProcessingParameterString,
)

from ..core.crs import CrsValidationError, require_projected_metric
from ..core.precision_lines_engine import run_precision_lines
from ..domain.avoidance_configuration import AvoidanceConfiguration, AvoidanceMode
from ..domain.headland_layout import HeadlandLayout
from ..domain.machine_model import load_machine_presets
from ..domain.obstacle_model import obstacle_from_point
from ..domain.precision_project import ABLine, FieldGeometry, PrecisionOperation, PrecisionProject
from ..gui.agricultural_lines_dialog import qgs_geometry_to_multipolygon, to_qgs_point


class SimulateObstacleAvoidanceAlgorithm(QgsProcessingAlgorithm):
    FIELD = "FIELD"
    AB_LINE = "AB_LINE"
    OBSTACLES = "OBSTACLES"
    SPRAYER_ID = "SPRAYER_ID"
    OBSTACLE_RADIUS = "OBSTACLE_RADIUS"
    SAFETY_MARGIN = "SAFETY_MARGIN"
    REPORT = "REPORT"

    def tr(self, text):
        return QCoreApplication.translate("FortSmartPrecision", text)

    def createInstance(self):
        return SimulateObstacleAvoidanceAlgorithm()

    def name(self):
        return "simulate_obstacle_avoidance"

    def displayName(self):
        return self.tr("Simular desvio de obstaculos (Precision Lines v2)")

    def group(self):
        return self.tr("Precision Lines")

    def groupId(self):
        return "precision_lines"

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.FIELD, self.tr("Talhao"), [QgsProcessing.TypeVectorPolygon]
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.AB_LINE, self.tr("Linha A-B"), [QgsProcessing.TypeVectorLine]
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.OBSTACLES, self.tr("Obstaculos (pontos)"), [QgsProcessing.TypeVectorPoint], optional=True
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.SPRAYER_ID, self.tr("ID pulverizador"), defaultValue="uniport_5030_103x035"
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.OBSTACLE_RADIUS, self.tr("Raio fisico obstaculo (m)"), defaultValue=0.0, minValue=0.0
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SAFETY_MARGIN, self.tr("Margem seguranca (m)"), defaultValue=0.0, minValue=0.0
            )
        )
        self.addOutput(QgsProcessingOutputString(self.REPORT, self.tr("Relatorio")))

    def processAlgorithm(self, parameters, context, feedback):
        field_source = self.parameterAsSource(parameters, self.FIELD, context)
        ab_source = self.parameterAsSource(parameters, self.AB_LINE, context)
        obs_source = self.parameterAsSource(parameters, self.OBSTACLES, context)
        if field_source is None or ab_source is None:
            raise QgsProcessingException(self.tr("Talhao e A-B obrigatorios."))
        try:
            require_projected_metric(field_source.sourceCrs().authid())
        except CrsValidationError as exc:
            raise QgsProcessingException(str(exc)) from exc

        field_feature = next(field_source.getFeatures(), None)
        ab_feature = next(ab_source.getFeatures(), None)
        if field_feature is None or ab_feature is None:
            raise QgsProcessingException(self.tr("Camadas vazias."))

        operational = qgs_geometry_to_multipolygon(field_feature.geometry())
        ab_geom = ab_feature.geometry()
        ab_line_pts = ab_geom.asPolyline() if not ab_geom.isMultipart() else ab_geom.asMultiPolyline()[0]

        presets = load_machine_presets()
        sprayer = presets[self.parameterAsString(parameters, self.SPRAYER_ID, context)]
        obs_radius = self.parameterAsDouble(parameters, self.OBSTACLE_RADIUS, context)
        safety = self.parameterAsDouble(parameters, self.SAFETY_MARGIN, context)

        obstacles = []
        if obs_source is not None:
            for feat in obs_source.getFeatures():
                pt = feat.geometry().asPoint()
                obstacles.append(
                    obstacle_from_point(
                        to_qgs_point((pt.x(), pt.y())),
                        obstacle_radius_m=obs_radius,
                        safety_margin_m=safety,
                        name=str(feat.id()),
                    )
                )

        project = PrecisionProject(
            field=FieldGeometry(
                field_boundary=operational,
                operational_boundary=operational,
                crs_authid=field_source.sourceCrs().authid(),
            ),
            ab_line=ABLine(start=to_qgs_point(ab_line_pts[0]), end=to_qgs_point(ab_line_pts[-1])),
            spraying=PrecisionOperation(
                operation_id="spraying",
                machine=sprayer,
                headland=HeadlandLayout(pass_count=0),
            ),
            obstacles=tuple(obstacles),
            avoidance=AvoidanceConfiguration(mode=AvoidanceMode.CONCENTRIC_RING),
        )
        result = run_precision_lines(project)
        payload = {
            "avoided_paths": len(result.avoided_paths),
            "avoidance_table": result.avoidance_table,
            "validation_ok": result.validation.ok,
        }
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        feedback.pushInfo(text)
        return {self.REPORT: text}
