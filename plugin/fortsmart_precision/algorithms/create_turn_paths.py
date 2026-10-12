# -*- coding: utf-8 -*-
"""Algoritmo Processing para caminhos de volta (Etapa 4)."""

from __future__ import annotations

import json

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
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsWkbTypes,
)

from ..core.crs import CrsValidationError, require_projected_metric
from ..core.parallel_pass_engine import ParallelPassParams, generate_parallel_passes
from ..core.turn_path_engine import filter_savable_turns, generate_turn_paths
from ..domain.boundary_areas import build_inner_and_headland
from ..domain.headland_layout import HeadlandLayout
from ..domain.turn_configuration import (
    PassSequenceMode,
    SafetyMargins,
    TurnConfiguration,
    TurnFinishMode,
    TurnType,
)
from ..gui.agricultural_lines_dialog import qgs_geometry_to_multipolygon, to_qgs_point
from ..validators.turn_validator import validate_turn_paths


class CreateTurnPathsAlgorithm(QgsProcessingAlgorithm):
    FIELD = "FIELD"
    AB_LINE = "AB_LINE"
    EXTERNAL = "EXTERNAL"
    WIDTH = "WIDTH"
    SPACING = "SPACING"
    HEADLAND_PASSES = "HEADLAND_PASSES"
    FINISH_MODE = "FINISH_MODE"
    TURN_TYPE = "TURN_TYPE"
    SEQUENCE_MODE = "SEQUENCE_MODE"
    SKIP_PASSES = "SKIP_PASSES"
    RADIUS = "RADIUS"
    MARGIN = "MARGIN"
    EXTENSION = "EXTENSION"
    GENERATE = "GENERATE"
    ALLOW_OUTSIDE = "ALLOW_OUTSIDE"
    OUTPUT_TURNS = "OUTPUT_TURNS"
    OUTPUT_INVALID = "OUTPUT_INVALID"

    FINISH_OPTIONS = [
        TurnFinishMode.NONE.value,
        TurnFinishMode.INSIDE_HEADLAND.value,
        TurnFinishMode.OUTSIDE_BOUNDARY.value,
        TurnFinishMode.MANEUVER_AREA.value,
    ]
    TURN_TYPE_OPTIONS = [
        TurnType.U.value,
        TurnType.DROP.value,
        TurnType.SKIP_PASS.value,
        TurnType.OMEGA.value,
        TurnType.THREE_POINT.value,
    ]
    SEQUENCE_OPTIONS = [
        PassSequenceMode.SEQUENTIAL.value,
        PassSequenceMode.ALTERNATING.value,
        PassSequenceMode.SKIP_ONE.value,
        PassSequenceMode.SKIP_TWO.value,
        PassSequenceMode.BLOCKS.value,
    ]

    def tr(self, text):
        return QCoreApplication.translate("FortSmartPrecision", text)

    def createInstance(self):
        return CreateTurnPathsAlgorithm()

    def name(self):
        return "create_turn_paths"

    def displayName(self):
        return self.tr("Criar caminhos de volta (Etapa 4)")

    def group(self):
        return self.tr("Agricultura")

    def groupId(self):
        return "agriculture"

    def shortHelpString(self):
        return self.tr(
            "Gera voltas U/gota/pula/omega/tres pontos na bordadura ou fora do limite. "
            "Suporta sequencia por blocos e implemento rebocado."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(self.FIELD, self.tr("Limite operacional"), [QgsProcessing.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterFeatureSource(self.AB_LINE, self.tr("Linha A-B"), [QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterFeatureSource(self.EXTERNAL, self.tr("Area externa autorizada (opcional)"), [QgsProcessing.TypeVectorPolygon], optional=True))
        self.addParameter(QgsProcessingParameterNumber(self.WIDTH, self.tr("Largura operacional (m)"), QgsProcessingParameterNumber.Double, defaultValue=18.0, minValue=0.01))
        self.addParameter(QgsProcessingParameterNumber(self.SPACING, self.tr("Espacamento entre passadas (m)"), QgsProcessingParameterNumber.Double, defaultValue=18.0, minValue=0.01))
        self.addParameter(QgsProcessingParameterNumber(self.HEADLAND_PASSES, self.tr("Passadas de bordadura"), QgsProcessingParameterNumber.Integer, defaultValue=2, minValue=0, maxValue=20))
        self.addParameter(QgsProcessingParameterEnum(self.FINISH_MODE, self.tr("Modo de finalizacao"), options=["Sem volta", "Dentro da bordadura", "Fora do limite", "Area de manobra"], defaultValue=1))
        self.addParameter(QgsProcessingParameterEnum(self.TURN_TYPE, self.tr("Tipo de volta"), options=["U", "Gota", "Pula-faixa", "Omega", "Tres pontos"], defaultValue=0))
        self.addParameter(QgsProcessingParameterEnum(self.SEQUENCE_MODE, self.tr("Sequencia"), options=["Sequencial", "Alternada", "Pula uma", "Pula duas", "Blocos"], defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber(self.SKIP_PASSES, self.tr("Pular quantas faixas"), QgsProcessingParameterNumber.Integer, defaultValue=0, minValue=0, maxValue=10))
        self.addParameter(QgsProcessingParameterNumber("BLOCK_SIZE", self.tr("Tamanho do bloco"), QgsProcessingParameterNumber.Integer, defaultValue=4, minValue=1, maxValue=50))
        self.addParameter(QgsProcessingParameterBoolean("TOWED", self.tr("Implemento rebocado"), defaultValue=False))
        self.addParameter(QgsProcessingParameterNumber(self.RADIUS, self.tr("Raio minimo (m, 0=nao informado)"), QgsProcessingParameterNumber.Double, defaultValue=0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(self.MARGIN, self.tr("Margem recomendada (m)"), QgsProcessingParameterNumber.Double, defaultValue=2.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(self.EXTENSION, self.tr("Extensao fora do limite (m)"), QgsProcessingParameterNumber.Double, defaultValue=20.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterBoolean(self.ALLOW_OUTSIDE, self.tr("Permitir manobra fora do limite"), defaultValue=False))
        self.addParameter(QgsProcessingParameterBoolean(self.GENERATE, self.tr("Gerar voltas"), defaultValue=True))
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT_TURNS, self.tr("Voltas validas")))
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT_INVALID, self.tr("Voltas invalidas")))

    def processAlgorithm(self, parameters, context, feedback):
        field_source = self.parameterAsSource(parameters, self.FIELD, context)
        ab_source = self.parameterAsSource(parameters, self.AB_LINE, context)
        if field_source is None or ab_source is None:
            raise QgsProcessingException(self.tr("Entradas invalidas."))
        try:
            require_projected_metric(field_source.sourceCrs().authid(), "geracao de caminhos de volta")
        except CrsValidationError as exc:
            raise QgsProcessingException(str(exc)) from exc

        geometries = [
            QgsGeometry(feature.geometry())
            for feature in field_source.getFeatures()
            if feature.geometry() and not feature.geometry().isEmpty()
        ]
        if not geometries:
            raise QgsProcessingException(self.tr("Limite operacional vazio."))
        operational_qgs = geometries[0] if len(geometries) == 1 else QgsGeometry.unaryUnion(geometries)
        operational = qgs_geometry_to_multipolygon(operational_qgs)

        ab_feature = next(ab_source.getFeatures(), None)
        if ab_feature is None:
            raise QgsProcessingException(self.tr("Linha A-B ausente."))
        ab_geom = ab_feature.geometry()
        points = ab_geom.asMultiPolyline()[0] if ab_geom.isMultipart() else ab_geom.asPolyline()
        if len(points) < 2:
            raise QgsProcessingException(self.tr("Linha A-B invalida."))

        width = self.parameterAsDouble(parameters, self.WIDTH, context)
        spacing = self.parameterAsDouble(parameters, self.SPACING, context)
        headland_passes = self.parameterAsInt(parameters, self.HEADLAND_PASSES, context)
        finish_mode = TurnFinishMode(self.FINISH_OPTIONS[self.parameterAsEnum(parameters, self.FINISH_MODE, context)])
        turn_type = TurnType(self.TURN_TYPE_OPTIONS[self.parameterAsEnum(parameters, self.TURN_TYPE, context)])
        sequence_mode = PassSequenceMode(self.SEQUENCE_OPTIONS[self.parameterAsEnum(parameters, self.SEQUENCE_MODE, context)])
        skip_passes = self.parameterAsInt(parameters, self.SKIP_PASSES, context)
        block_size = self.parameterAsInt(parameters, "BLOCK_SIZE", context)
        towed = self.parameterAsBool(parameters, "TOWED", context)
        radius = self.parameterAsDouble(parameters, self.RADIUS, context)
        margin = self.parameterAsDouble(parameters, self.MARGIN, context)
        extension = self.parameterAsDouble(parameters, self.EXTENSION, context)
        allow_outside = self.parameterAsBool(parameters, self.ALLOW_OUTSIDE, context)
        generate = self.parameterAsBool(parameters, self.GENERATE, context)

        external_poly = None
        external_source = self.parameterAsSource(parameters, self.EXTERNAL, context)
        if external_source is not None:
            external_geoms = [
                QgsGeometry(feature.geometry())
                for feature in external_source.getFeatures()
                if feature.geometry() and not feature.geometry().isEmpty()
            ]
            if external_geoms:
                external_qgs = external_geoms[0] if len(external_geoms) == 1 else QgsGeometry.unaryUnion(external_geoms)
                external_poly = qgs_geometry_to_multipolygon(external_qgs)

        layout = HeadlandLayout(
            pass_count=headland_passes,
            width_m=width,
            effective_spacing_m=spacing,
            mode="parallel_ab" if headland_passes else "none",
        )
        reserved = layout.reserved_width_m
        work_geometry = operational_qgs
        if reserved > 0:
            work_geometry = operational_qgs.buffer(-reserved, 16)
            if work_geometry.isEmpty():
                raise QgsProcessingException(self.tr("A bordadura eliminou o talhao."))

        areas = build_inner_and_headland(operational, reserved, external_turn_area=external_poly)
        passes = generate_parallel_passes(
            ParallelPassParams(
                polygons=qgs_geometry_to_multipolygon(work_geometry),
                ab_start=(points[0].x(), points[0].y()),
                ab_end=(points[-1].x(), points[-1].y()),
                pass_spacing_m=spacing,
                operation_width_m=width,
                extension_m=0.0,
                operation_id="operation",
            )
        )

        config = TurnConfiguration(
            finish_mode=finish_mode if generate else TurnFinishMode.NONE,
            turn_type=turn_type,
            sequence_mode=sequence_mode,
            generate_turns=generate and finish_mode != TurnFinishMode.NONE,
            min_turn_radius_m=None if radius <= 0 else radius,
            skip_passes=skip_passes,
            block_size=block_size,
            implement_mounted=False if towed else None,
            external_extension_m=extension,
            extension_before_m=extension,
            extension_after_m=extension,
            allow_outside_boundary=allow_outside or finish_mode == TurnFinishMode.OUTSIDE_BOUNDARY,
            use_maneuver_area=finish_mode == TurnFinishMode.MANEUVER_AREA,
            safety=SafetyMargins(recommended_clearance_m=margin),
        )
        try:
            result = generate_turn_paths(passes, config, areas)
        except Exception as exc:
            raise QgsProcessingException(str(exc)) from exc

        report = validate_turn_paths(result, config, areas, allow_save_invalid=True)
        feedback.pushInfo(json.dumps(report.as_dict(), ensure_ascii=True))

        turn_fields = turn_path_fields()
        valid_sink, valid_id = self.parameterAsSink(
            parameters, self.OUTPUT_TURNS, context, turn_fields, QgsWkbTypes.LineString, field_source.sourceCrs()
        )
        invalid_sink, invalid_id = self.parameterAsSink(
            parameters, self.OUTPUT_INVALID, context, turn_fields, QgsWkbTypes.LineString, field_source.sourceCrs()
        )
        if valid_sink is None or invalid_sink is None:
            raise QgsProcessingException(self.tr("Nao foi possivel criar saidas."))

        valid = filter_savable_turns(result.turns)
        invalid = [turn for turn in result.turns if turn not in valid]
        for turn in valid:
            valid_sink.addFeature(_turn_feature(turn_fields, turn))
        for turn in invalid:
            invalid_sink.addFeature(_turn_feature(turn_fields, turn))

        return {
            self.OUTPUT_TURNS: valid_id,
            self.OUTPUT_INVALID: invalid_id,
        }


def turn_path_fields() -> QgsFields:
    fields = QgsFields()
    for name, typ in (
        ("fs_id", QVariant.String),
        ("from_pass", QVariant.Int),
        ("to_pass", QVariant.Int),
        ("turn_type", QVariant.String),
        ("turn_location", QVariant.String),
        ("sequence_no", QVariant.Int),
        ("radius_m", QVariant.Double),
        ("required_width_m", QVariant.Double),
        ("available_width_m", QVariant.Double),
        ("clearance_m", QVariant.Double),
        ("status", QVariant.String),
        ("is_estimated", QVariant.Bool),
        ("outside_boundary", QVariant.Bool),
        ("external_area_id", QVariant.String),
        ("length_m", QVariant.Double),
        ("label", QVariant.String),
        ("configured_extension_m", QVariant.Double),
        ("minimum_extension_m", QVariant.Double),
    ):
        fields.append(QgsField(name, typ))
    return fields


def _turn_feature(fields: QgsFields, turn) -> QgsFeature:
    attrs = turn.attributes()
    feature = QgsFeature(fields)
    feature.setAttributes([
        attrs["fs_id"],
        attrs["from_pass"],
        attrs["to_pass"],
        attrs["turn_type"],
        attrs["turn_location"],
        attrs["sequence_no"],
        attrs["radius_m"],
        attrs["required_width_m"],
        attrs["available_width_m"],
        attrs["clearance_m"],
        attrs["status"],
        attrs["is_estimated"],
        attrs["outside_boundary"],
        attrs["external_area_id"],
        attrs["length_m"],
        attrs["label"],
        attrs["configured_extension_m"],
        attrs["minimum_extension_m"],
    ])
    feature.setGeometry(QgsGeometry.fromPolylineXY([to_qgs_point(point) for point in turn.points]))
    return feature
