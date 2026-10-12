# -*- coding: utf-8 -*-
"""Algoritmo Processing: validacao do projeto Precision Lines."""

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
from ..core.validation_engine import validate_precision_project
from ..domain.headland_layout import HeadlandLayout
from ..domain.machine_model import load_machine_presets
from ..domain.precision_project import ABLine, FieldGeometry, PrecisionOperation, PrecisionProject
from ..gui.agricultural_lines_dialog import qgs_geometry_to_multipolygon, to_qgs_point


class ValidatePrecisionProjectAlgorithm(QgsProcessingAlgorithm):
    FIELD = "FIELD"
    AB_LINE = "AB_LINE"
    PLANTER_ID = "PLANTER_ID"
    SPRAYER_ID = "SPRAYER_ID"
    HEADLAND_PASSES = "HEADLAND_PASSES"
    REPORT = "REPORT"

    def tr(self, text):
        return QCoreApplication.translate("FortSmartPrecision", text)

    def createInstance(self):
        return ValidatePrecisionProjectAlgorithm()

    def name(self):
        return "validate_precision_project"

    def displayName(self):
        return self.tr("Validar projeto Precision Lines")

    def group(self):
        return self.tr("Precision Lines")

    def groupId(self):
        return "precision_lines"

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.FIELD,
                self.tr("Talhao"),
                [QgsProcessing.TypeVectorPolygon],
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.AB_LINE,
                self.tr("Linha A-B"),
                [QgsProcessing.TypeVectorLine],
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.PLANTER_ID,
                self.tr("ID plantadeira (preset)"),
                defaultValue="db27_36x050",
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.SPRAYER_ID,
                self.tr("ID pulverizador (preset)"),
                defaultValue="uniport_5030_103x035",
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.HEADLAND_PASSES,
                self.tr("Passadas de bordadura"),
                QgsProcessingParameterNumber.Integer,
                defaultValue=1,
                minValue=0,
                maxValue=10,
            )
        )
        self.addOutput(QgsProcessingOutputString(self.REPORT, self.tr("Relatorio de validacao")))

    def processAlgorithm(self, parameters, context, feedback):
        field_source = self.parameterAsSource(parameters, self.FIELD, context)
        ab_source = self.parameterAsSource(parameters, self.AB_LINE, context)
        if field_source is None or ab_source is None:
            raise QgsProcessingException(self.tr("Talhao e linha A-B sao obrigatorios."))

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
        ab_line = ab_geom.asPolyline() if not ab_geom.isMultipart() else ab_geom.asMultiPolyline()[0]
        presets = load_machine_presets()
        planter = presets[self.parameterAsString(parameters, self.PLANTER_ID, context)]
        sprayer = presets[self.parameterAsString(parameters, self.SPRAYER_ID, context)]
        headland_passes = self.parameterAsInt(parameters, self.HEADLAND_PASSES, context)

        project = PrecisionProject(
            field=FieldGeometry(
                field_boundary=operational,
                operational_boundary=operational,
                crs_authid=field_source.sourceCrs().authid(),
            ),
            ab_line=ABLine(start=to_qgs_point(ab_line[0]), end=to_qgs_point(ab_line[-1])),
            planting=PrecisionOperation(
                operation_id="planting",
                machine=planter,
                headland=HeadlandLayout(
                    pass_count=headland_passes,
                    width_m=planter.operational_width_m,
                    effective_spacing_m=planter.operational_width_m,
                    mode="parallel_ab",
                ),
            ),
            spraying=PrecisionOperation(operation_id="spraying", machine=sprayer),
        )

        pipeline = run_precision_lines(project)
        report = validate_precision_project(
            project,
            boundary=pipeline.boundary,
            planting_passes=pipeline.planting_passes,
            planting_rows=pipeline.planting_rows,
            tramline_zones=pipeline.tramline_zones,
            shutoff_segments=pipeline.shutoff_segments,
        )
        payload = json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
        if not report.ok:
            feedback.reportError(self.tr("Validacao falhou."))
        else:
            feedback.pushInfo(self.tr("Validacao OK."))
        return {self.REPORT: payload}
