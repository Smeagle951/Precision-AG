# -*- coding: utf-8 -*-
"""Algoritmo Processing para passadas centrais de operacao agricola."""

from __future__ import annotations

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsWkbTypes,
)

from ..core.crs import CrsValidationError, require_projected_metric
from ..core.parallel_pass_engine import ParallelPassParams, generate_parallel_passes
from ..gui.agricultural_lines_dialog import qgs_geometry_to_multipolygon, to_qgs_point


class CreateOperationPassesAlgorithm(QgsProcessingAlgorithm):
    FIELD = "FIELD"
    AB_LINE = "AB_LINE"
    WIDTH = "WIDTH"
    SPACING = "SPACING"
    EXTENSION = "EXTENSION"
    AB_OFFSET_RIGHT = "AB_OFFSET_RIGHT"
    OUTPUT = "OUTPUT"

    def tr(self, text):
        return QCoreApplication.translate("FortSmartPrecision", text)

    def createInstance(self):
        return CreateOperationPassesAlgorithm()

    def name(self):
        return "create_operation_passes"

    def displayName(self):
        return self.tr("Criar passadas de operacao agricola")

    def group(self):
        return self.tr("Agricultura")

    def groupId(self):
        return "agriculture"

    def shortHelpString(self):
        return self.tr("Gera linhas centrais paralelas usando a A-B como centro operacional.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(self.FIELD, self.tr("Talhao"), [QgsProcessing.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterFeatureSource(self.AB_LINE, self.tr("Linha A-B"), [QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterNumber(self.WIDTH, self.tr("Largura operacional (m)"), QgsProcessingParameterNumber.Double, defaultValue=18.0, minValue=0.01))
        self.addParameter(QgsProcessingParameterNumber(self.SPACING, self.tr("Espacamento efetivo entre passadas (m)"), QgsProcessingParameterNumber.Double, defaultValue=18.0, minValue=0.01))
        self.addParameter(QgsProcessingParameterNumber(self.EXTENSION, self.tr("Extensao alem do limite (m)"), QgsProcessingParameterNumber.Double, defaultValue=20.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(self.AB_OFFSET_RIGHT, self.tr("Offset da A-B para direita (m)"), QgsProcessingParameterNumber.Double, defaultValue=0.0))
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT, self.tr("Passadas centrais")))

    def processAlgorithm(self, parameters, context, feedback):
        field_source = self.parameterAsSource(parameters, self.FIELD, context)
        ab_source = self.parameterAsSource(parameters, self.AB_LINE, context)
        if field_source is None or ab_source is None:
            raise QgsProcessingException(self.tr("Entradas invalidas."))
        try:
            require_projected_metric(field_source.sourceCrs().authid(), "geracao de passadas agricolas")
        except CrsValidationError as exc:
            raise QgsProcessingException(str(exc)) from exc

        geometries = [QgsGeometry(feature.geometry()) for feature in field_source.getFeatures() if feature.geometry() and not feature.geometry().isEmpty()]
        if not geometries:
            raise QgsProcessingException(self.tr("Talhao vazio."))
        field_geometry = geometries[0] if len(geometries) == 1 else QgsGeometry.unaryUnion(geometries)

        ab_feature = next(ab_source.getFeatures(), None)
        if ab_feature is None:
            raise QgsProcessingException(self.tr("Linha A-B ausente."))
        ab_geom = ab_feature.geometry()
        points = ab_geom.asMultiPolyline()[0] if ab_geom.isMultipart() else ab_geom.asPolyline()
        if len(points) < 2:
            raise QgsProcessingException(self.tr("Linha A-B invalida."))

        passes = generate_parallel_passes(
            ParallelPassParams(
                polygons=qgs_geometry_to_multipolygon(field_geometry),
                ab_start=(points[0].x(), points[0].y()),
                ab_end=(points[-1].x(), points[-1].y()),
                pass_spacing_m=self.parameterAsDouble(parameters, self.SPACING, context),
                operation_width_m=self.parameterAsDouble(parameters, self.WIDTH, context),
                extension_m=self.parameterAsDouble(parameters, self.EXTENSION, context),
                ab_offset_right_m=self.parameterAsDouble(parameters, self.AB_OFFSET_RIGHT, context),
                operation_id="operation",
            )
        )

        fields = operation_pass_fields()
        sink, dest_id = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            fields,
            QgsWkbTypes.LineString,
            field_source.sourceCrs(),
        )
        if sink is None:
            raise QgsProcessingException(self.tr("Nao foi possivel criar a saida."))
        for pass_line in passes:
            feature = QgsFeature(fields)
            attrs = pass_line.attributes()
            feature.setAttributes([
                attrs["fs_id"],
                attrs["operation_id"],
                attrs["pass_no"],
                attrs["spacing_m"],
                attrs["width_m"],
                attrs["half_width_m"],
                attrs["offset_m"],
                attrs["azimuth_deg"],
                attrs["length_m"],
                attrs["is_headland"],
            ])
            feature.setGeometry(QgsGeometry.fromPolylineXY([to_qgs_point(pass_line.guidance_segment.start), to_qgs_point(pass_line.guidance_segment.end)]))
            sink.addFeature(feature)
        return {self.OUTPUT: dest_id}


def operation_pass_fields():
    fields = QgsFields()
    fields.append(QgsField("fs_id", QVariant.String))
    fields.append(QgsField("operation_id", QVariant.String))
    fields.append(QgsField("pass_no", QVariant.Int))
    fields.append(QgsField("spacing_m", QVariant.Double))
    fields.append(QgsField("width_m", QVariant.Double))
    fields.append(QgsField("half_width_m", QVariant.Double))
    fields.append(QgsField("offset_m", QVariant.Double))
    fields.append(QgsField("azimuth_deg", QVariant.Double))
    fields.append(QgsField("length_m", QVariant.Double))
    fields.append(QgsField("is_headland", QVariant.Bool))
    return fields
