# -*- coding: utf-8 -*-
"""Processing para o raio-X visual das passadas ja existentes."""

from __future__ import annotations

from shapely import wkt

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingLayerPostProcessorInterface,
    QgsProcessingOutputString,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProject,
    QgsWkbTypes,
)

from ..core.crs import CrsValidationError, require_projected_metric
from ..core.layer_roles import definition_for_role
from ..core.visual_coverage_engine import VisualCoverageError, simulate_visual_coverage

OUTPUT_ROLES = {"COVERAGE": "COVERAGE", "OVERLAP": "OVERLAP", "GAP": "GAP"}


class SimulationRolePostProcessor(QgsProcessingLayerPostProcessorInterface):
    """Saida carregada no projeto recebe o role 41/42/43 e vai para 40_SIMULACAO do talhao."""

    def __init__(self, role, source_layer_id, boundary_layer_id=None):
        super().__init__()
        self.role = role
        self.source_layer_id = source_layer_id
        self.boundary_layer_id = boundary_layer_id

    def postProcessLayer(self, layer, context, feedback):
        from ..gui.layer_tree_organizer import field_name_for_layer, place_generated_result

        project = context.project() or QgsProject.instance()
        field_name = field_name_for_layer(project, project.mapLayer(self.source_layer_id or ""))
        if not field_name and self.boundary_layer_id:
            boundary = project.mapLayer(self.boundary_layer_id)
            field_name = boundary.name() if boundary is not None else None
        place_generated_result(project, layer, definition_for_role(self.role), field_name)


class SimulateRealOperationAlgorithm(QgsProcessingAlgorithm):
    LINES = "LINES"
    WORK_WIDTH = "WORK_WIDTH"
    BOUNDARY = "BOUNDARY"
    WORK_STATE_FIELD = "WORK_STATE_FIELD"
    COVERAGE = "COVERAGE"
    OVERLAP = "OVERLAP"
    GAP = "GAP"
    REPORT = "REPORT"
    live_post_processors: list = []

    def tr(self, text):
        return QCoreApplication.translate("FortSmartPrecision", text)

    def createInstance(self):
        return SimulateRealOperationAlgorithm()

    def name(self):
        return "simulate_real_operation"

    def displayName(self):
        return self.tr("Simular cobertura visual das passadas")

    def group(self):
        return self.tr("Simulador de Operacao")

    def groupId(self):
        return "operation_simulator"

    def shortHelpString(self):
        return self.tr(
            "Cria 41_Cobertura, 42_Remonte e 43_Falha a partir das linhas existentes, "
            "na secao 40_SIMULACAO do talhao. Nao gera linhas novas, nao altera fontes e "
            "nao valida a operacao. Use 'Persistir camadas FortSmart' para salvar a simulacao."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.LINES, self.tr("Linhas / passadas existentes"), [QgsProcessing.TypeVectorLine]
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.WORK_WIDTH, self.tr("Largura do implemento (m)"),
            QgsProcessingParameterNumber.Double, defaultValue=10.0, minValue=0.01
        ))
        boundary = QgsProcessingParameterFeatureSource(
            self.BOUNDARY, self.tr("Talhao para recorte visual (opcional)"), [QgsProcessing.TypeVectorPolygon]
        )
        boundary.setFlags(boundary.flags() | QgsProcessingParameterDefinition.FlagOptional)
        self.addParameter(boundary)
        state = QgsProcessingParameterField(
            self.WORK_STATE_FIELD, self.tr("Campo WORK_ON / WORK_OFF (opcional)"),
            parentLayerParameterName=self.LINES, type=QgsProcessingParameterField.Any
        )
        state.setFlags(state.flags() | QgsProcessingParameterDefinition.FlagOptional)
        self.addParameter(state)
        for output in (self.COVERAGE, self.OVERLAP, self.GAP):
            self.addParameter(QgsProcessingParameterFeatureSink(
                output, definition_for_role(OUTPUT_ROLES[output]).display_name
            ))
        self.addOutput(QgsProcessingOutputString(self.REPORT, self.tr("Resumo visual")))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.LINES, context)
        if source is None:
            raise QgsProcessingException(self.tr("Camada de passadas obrigatoria."))
        try:
            require_projected_metric(source.sourceCrs().authid(), "simulacao visual de cobertura")
        except CrsValidationError as exc:
            raise QgsProcessingException(str(exc)) from exc

        state_field = self.parameterAsString(parameters, self.WORK_STATE_FIELD, context)
        lines = []
        ignored_off = 0
        for feature in source.getFeatures():
            if state_field and state_field in feature.fields().names():
                state = str(feature[state_field]).strip().upper()
                if state in {"WORK_OFF", "OFF", "0", "FALSE"}:
                    ignored_off += 1
                    continue
            geometry = feature.geometry()
            if geometry is None or geometry.isEmpty():
                continue
            parts = geometry.asMultiPolyline() if geometry.isMultipart() else [geometry.asPolyline()]
            lines.extend([[(point.x(), point.y()) for point in part] for part in parts if len(part) >= 2])

        analysis_area = None
        boundary_source = self.parameterAsSource(parameters, self.BOUNDARY, context)
        if boundary_source is not None:
            if boundary_source.sourceCrs() != source.sourceCrs():
                raise QgsProcessingException(self.tr("Talhao e passadas devem estar no mesmo CRS."))
            shapes = [feature.geometry().asWkt() for feature in boundary_source.getFeatures()
                      if feature.geometry() and not feature.geometry().isEmpty()]
            if shapes:
                from shapely.ops import unary_union
                analysis_area = unary_union([wkt.loads(item) for item in shapes])

        try:
            result = simulate_visual_coverage(
                lines,
                work_width_m=self.parameterAsDouble(parameters, self.WORK_WIDTH, context),
                analysis_area=analysis_area,
            )
        except VisualCoverageError as exc:
            raise QgsProcessingException(str(exc)) from exc

        fields = QgsFields()
        fields.append(QgsField("classe", QVariant.String))
        fields.append(QgsField("area_m2", QVariant.Double))
        coverage_sink, coverage_id = self.parameterAsSink(parameters, self.COVERAGE, context, fields, QgsWkbTypes.MultiPolygon, source.sourceCrs())
        overlap_sink, overlap_id = self.parameterAsSink(parameters, self.OVERLAP, context, fields, QgsWkbTypes.MultiPolygon, source.sourceCrs())
        gap_sink, gap_id = self.parameterAsSink(parameters, self.GAP, context, fields, QgsWkbTypes.MultiPolygon, source.sourceCrs())
        if not coverage_sink or not overlap_sink or not gap_sink:
            raise QgsProcessingException(self.tr("Nao foi possivel criar uma camada de simulacao."))
        self._write(coverage_sink, fields, result.normal_coverage, "COBERTURA")
        self._write(overlap_sink, fields, result.overlap, "REMONTE")
        if result.gap is not None:
            self._write(gap_sink, fields, result.gap, "FALHA")

        metrics = result.metrics
        report = {
            "largura_m": metrics.work_width_m,
            "passadas_work_on": metrics.pass_count,
            "trechos_work_off_ignorados": ignored_off,
            "cobertura_ha": round(metrics.covered_area_ha, 6),
            "remonte_ha": round(metrics.overlap_area_ha, 6),
            "falha_ha": None if metrics.gap_area_ha is None else round(metrics.gap_area_ha, 6),
        }
        feedback.pushInfo(str(report))
        self._attach_role_post_processors(
            parameters, context,
            {self.COVERAGE: coverage_id, self.OVERLAP: overlap_id, self.GAP: gap_id},
        )
        return {self.COVERAGE: coverage_id, self.OVERLAP: overlap_id, self.GAP: gap_id, self.REPORT: str(report)}

    def _attach_role_post_processors(self, parameters, context, outputs):
        source_layer = self.parameterAsVectorLayer(parameters, self.LINES, context)
        boundary_layer = self.parameterAsVectorLayer(parameters, self.BOUNDARY, context)
        # O Processing guarda so o ponteiro e a instancia do algoritmo pode morrer
        # antes do carregamento: os pos-processadores vivem na classe.
        processors = []
        for output, dest_id in outputs.items():
            if not dest_id or not context.willLoadLayerOnCompletion(dest_id):
                continue
            processor = SimulationRolePostProcessor(
                OUTPUT_ROLES[output],
                source_layer.id() if source_layer is not None else None,
                boundary_layer.id() if boundary_layer is not None else None,
            )
            details = context.layerToLoadOnCompletionDetails(dest_id)
            details.name = definition_for_role(OUTPUT_ROLES[output]).display_name
            details.setPostProcessor(processor)
            processors.append(processor)
        SimulateRealOperationAlgorithm.live_post_processors = processors

    @staticmethod
    def _write(sink, fields, geometry, label):
        if geometry.is_empty:
            return
        feature = QgsFeature(fields)
        qgs_geometry = QgsGeometry.fromWkt(geometry.wkt)
        if not qgs_geometry.isMultipart():
            qgs_geometry.convertToMultiType()
        feature.setGeometry(qgs_geometry)
        feature.setAttributes([label, float(geometry.area)])
        sink.addFeature(feature)
