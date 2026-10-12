# -*- coding: utf-8 -*-
"""Algoritmo Processing para criar linhas agricolas paralelas."""

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
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsWkbTypes,
)

from ..core.crs import CrsValidationError, require_projected_metric
from ..domain.agricultural_lines import (
    AgriculturalLineParams,
    generate_parallel_agricultural_lines,
)
from ..gui.agricultural_lines_dialog import qgs_geometry_to_multipolygon, to_qgs_point


class CreateParallelAgriculturalLinesAlgorithm(QgsProcessingAlgorithm):
    FIELD = "FIELD"
    AB_LINE = "AB_LINE"
    SELECTED_ONLY = "SELECTED_ONLY"
    SPACING = "SPACING"
    HEADLAND = "HEADLAND"
    EXTENSION = "EXTENSION"
    MIN_LENGTH = "MIN_LENGTH"
    OUTPUT = "OUTPUT"

    def tr(self, text):
        return QCoreApplication.translate("FortSmartPrecision", text)

    def createInstance(self):
        return CreateParallelAgriculturalLinesAlgorithm()

    def name(self):
        return "create_parallel_agricultural_lines"

    def displayName(self):
        return self.tr("Gerar linhas agricolas paralelas")

    def group(self):
        return self.tr("Agricultura")

    def groupId(self):
        return "agriculture"

    def shortHelpString(self):
        return self.tr(
            "Gera linhas paralelas a partir de um talhao poligonal e uma linha A-B, "
            "exigindo CRS projetado metrico."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.FIELD,
                self.tr("Talhao poligonal"),
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
            QgsProcessingParameterBoolean(
                self.SELECTED_ONLY,
                self.tr("Usar somente feicoes selecionadas do talhao"),
                defaultValue=False,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SPACING,
                self.tr("Espacamento entre linhas (m)"),
                QgsProcessingParameterNumber.Double,
                defaultValue=18.0,
                minValue=0.01,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.HEADLAND,
                self.tr("Bordadura interna (m)"),
                QgsProcessingParameterNumber.Double,
                defaultValue=0.0,
                minValue=0.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.EXTENSION,
                self.tr("Extensao alem do limite (m)"),
                QgsProcessingParameterNumber.Double,
                defaultValue=20.0,
                minValue=0.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MIN_LENGTH,
                self.tr("Comprimento minimo do segmento (m)"),
                QgsProcessingParameterNumber.Double,
                defaultValue=0.0,
                minValue=0.0,
            )
        )
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT, self.tr("Linhas agricolas")))

    def processAlgorithm(self, parameters, context, feedback):
        field_source = self.parameterAsSource(parameters, self.FIELD, context)
        ab_source = self.parameterAsSource(parameters, self.AB_LINE, context)
        if field_source is None or ab_source is None:
            raise QgsProcessingException(self.tr("Camadas de entrada invalidas."))

        try:
            require_projected_metric(field_source.sourceCrs().authid(), "geracao de linhas agricolas")
        except CrsValidationError as exc:
            raise QgsProcessingException(str(exc)) from exc

        feedback.setProgress(10)
        field_geometries = []
        for feature in field_source.getFeatures():
            geom = feature.geometry()
            if geom and not geom.isEmpty():
                field_geometries.append(QgsGeometry(geom))
        if not field_geometries:
            raise QgsProcessingException(self.tr("Talhao sem geometria valida."))

        geometry = field_geometries[0] if len(field_geometries) == 1 else QgsGeometry.unaryUnion(field_geometries)
        headland = self.parameterAsDouble(parameters, self.HEADLAND, context)
        if headland > 0:
            geometry = geometry.buffer(-headland, 16)
            if geometry.isEmpty():
                raise QgsProcessingException(self.tr("A bordadura eliminou o limite operacional."))

        ab_feature = next(ab_source.getFeatures(), None)
        if ab_feature is None:
            raise QgsProcessingException(self.tr("Linha A-B ausente."))
        ab_geom = ab_feature.geometry()
        points = ab_geom.asMultiPolyline()[0] if ab_geom.isMultipart() else ab_geom.asPolyline()
        if len(points) < 2:
            raise QgsProcessingException(self.tr("Linha A-B precisa possuir ao menos dois vertices."))

        params = AgriculturalLineParams(
            polygons=qgs_geometry_to_multipolygon(geometry),
            ab_start=(points[0].x(), points[0].y()),
            ab_end=(points[-1].x(), points[-1].y()),
            spacing_m=self.parameterAsDouble(parameters, self.SPACING, context),
            extension_m=self.parameterAsDouble(parameters, self.EXTENSION, context),
            min_length_m=self.parameterAsDouble(parameters, self.MIN_LENGTH, context),
            operation="custom",
            source_ab_id=str(ab_feature.id()),
        )
        lines = generate_parallel_agricultural_lines(params)
        feedback.setProgress(70)

        fields = output_fields()
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

        for line in lines:
            feature = QgsFeature(fields)
            attrs = line.attributes()
            feature.setAttributes(
                [
                    attrs["fs_id"],
                    attrs["line_no"],
                    attrs["line_type"],
                    attrs["operation"],
                    attrs["spacing_m"],
                    attrs["pass_id"],
                    attrs["implement_position"],
                    attrs["sex"],
                    attrs["azimuth_deg"],
                    attrs["length_m"],
                    attrs["direction"],
                    attrs["source_ab_id"],
                ]
            )
            feature.setGeometry(
                QgsGeometry.fromPolylineXY(
                    [to_qgs_point(line.segment.start), to_qgs_point(line.segment.end)]
                )
            )
            sink.addFeature(feature)
        feedback.setProgress(100)
        return {self.OUTPUT: dest_id}


def output_fields():
    fields = QgsFields()
    fields.append(QgsField("fs_id", QVariant.String))
    fields.append(QgsField("line_no", QVariant.Int))
    fields.append(QgsField("line_type", QVariant.String))
    fields.append(QgsField("operation", QVariant.String))
    fields.append(QgsField("spacing_m", QVariant.Double))
    fields.append(QgsField("pass_id", QVariant.Int))
    fields.append(QgsField("implement_position", QVariant.Int))
    fields.append(QgsField("sex", QVariant.String))
    fields.append(QgsField("azimuth_deg", QVariant.Double))
    fields.append(QgsField("length_m", QVariant.Double))
    fields.append(QgsField("direction", QVariant.String))
    fields.append(QgsField("source_ab_id", QVariant.String))
    return fields
