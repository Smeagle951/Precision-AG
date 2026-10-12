# -*- coding: utf-8 -*-
"""Processing: corte longitudinal real por obstaculo + passada de bordadura."""

from __future__ import annotations

import json
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputString,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterNumber,
    QgsProject,
    QgsWkbTypes,
)
from shapely import wkt as shapely_wkt

from ..core.crs import CrsValidationError, require_projected_metric
from ..core.longitudinal_cut_engine import LongitudinalCutError, ObstacleInput
from ..core.planting_line_cut_engine import (
    line_id_field,
    line_id_for,
    line_number_field,
    spatial_line_numbers,
)
from ..core.obstacle_border_pass_engine import (
    cut_work_line_records,
    polygonal_part,
    simulate_obstacle_cut,
    work_event_records,
)
from ..domain.operation_simulation import (
    MachineReferenceType,
    MachineWorkGeometry,
    ObstacleBorderMode,
    ObstacleStrategy,
)

REFERENCE_TYPES = list(MachineReferenceType)
BORDER_MODES = [
    ObstacleBorderMode.ONE_IMPLEMENT_PASS,
    ObstacleBorderMode.CUSTOM,
    ObstacleBorderMode.NONE,
]
STRATEGIES = [ObstacleStrategy.CUT_FOR_BORDER, ObstacleStrategy.CUT_ONLY]

SINKS = (
    ("SIM_WORK_LINES", "Linhas existentes cortadas (mesma numeracao)", QgsWkbTypes.LineString),
    ("SIM_MACHINE_PATH", "Trajetoria da referencia (maquina)", QgsWkbTypes.LineString),
    ("SIM_WORKING_PATH", "Trajetoria da ultima linha ativa", QgsWkbTypes.LineString),
    ("SIM_WORK_OFF_ON", "Eventos WORK_OFF / WORK_ON", QgsWkbTypes.Point),
    ("SIM_SAFETY_ZONE", "Zona de seguranca do obstaculo", QgsWkbTypes.MultiPolygon),
    ("SIM_MAIN_WORK_AREA", "Area trabalhada na passada principal", QgsWkbTypes.MultiPolygon),
    ("SIM_UNWORKED_BORDER", "Area deixada para bordadura", QgsWkbTypes.MultiPolygon),
    ("SIM_BORDER_PASS", "Passada de bordadura", QgsWkbTypes.LineString),
    ("SIM_BORDER_COVERAGE", "Cobertura da bordadura", QgsWkbTypes.MultiPolygon),
    ("SIM_BORDER_GAPS", "Falhas apos bordadura", QgsWkbTypes.MultiPolygon),
    ("SIM_BORDER_OVERLAPS", "Sobreposicoes", QgsWkbTypes.MultiPolygon),
)


def _to_shapely(geometry: QgsGeometry):
    return shapely_wkt.loads(geometry.asWkt())


def _to_qgs(geometry) -> QgsGeometry:
    return QgsGeometry.fromWkt(geometry.wkt)


def _area_to_qgs(geometry) -> QgsGeometry | None:
    polygonal = polygonal_part(geometry)
    if polygonal is None:
        return None
    result = QgsGeometry.fromWkt(polygonal.wkt)
    result.convertToMultiType()
    return result


class SimulateObstacleBorderCutAlgorithm(QgsProcessingAlgorithm):
    PASSES = "PASSES"
    FIELD = "FIELD"
    OBSTACLES = "OBSTACLES"
    WORK_WIDTH = "WORK_WIDTH"
    REFERENCE_TYPE = "REFERENCE_TYPE"
    WORKING_OFFSET = "WORKING_OFFSET"
    REFERENCE_LATERAL = "REFERENCE_LATERAL"
    IMPLEMENT_LATERAL = "IMPLEMENT_LATERAL"
    BORDER_MODE = "BORDER_MODE"
    BORDER_WIDTH = "BORDER_WIDTH"
    STRATEGY = "STRATEGY"
    OBSTACLE_RADIUS = "OBSTACLE_RADIUS"
    SAFETY_MARGIN = "SAFETY_MARGIN"
    LATERAL_MARGIN = "LATERAL_MARGIN"
    LONGITUDINAL_MARGIN = "LONGITUDINAL_MARGIN"
    ANTICIPATION = "ANTICIPATION"
    MIN_TURN_RADIUS = "MIN_TURN_RADIUS"
    TOLERANCE = "TOLERANCE"
    GROUP = "GROUP"
    REPORT_FILE = "REPORT_FILE"
    REPORT = "REPORT"

    def tr(self, text):
        return QCoreApplication.translate("FortSmartPrecision", text)

    def createInstance(self):
        return SimulateObstacleBorderCutAlgorithm()

    def name(self):
        return "simulate_obstacle_border_cut"

    def displayName(self):
        return self.tr("Corte longitudinal por obstaculo + bordadura")

    def group(self):
        return self.tr("Simulador de Operacao")

    def groupId(self):
        return "operation_simulator"

    def shortHelpString(self):
        return self.tr(
            "As linhas de entrada sao a trajetoria do ponto de referencia da maquina e nao "
            "sao regeradas: SIM_WORK_LINES e a mesma camada, com os mesmos atributos e "
            "numeracao, sem os trechos em que a ultima linha ativa fica levantada; linhas "
            "sem obstaculo saem identicas e nada e recortado pelo talhao. "
            "WORK_OFF/WORK_ON sao calculados pela posicao real da ultima linha ativa "
            "(offset longitudinal com sinal: negativo = atras da referencia). "
            "A barra desliga quando encosta na zona do obstaculo (raio fisico + margem), "
            "antecipada no sentido da passada pela antecipacao de desligamento; a largura "
            "do implemento, o espacamento e a bordadura nao definem a distancia de corte. "
            "Simula a passada de bordadura e mede falha, sobreposicao, colisao e saida "
            "do talhao. Exige CRS projetado em metros; as camadas originais nao sao alteradas."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.PASSES, self.tr("Passadas (trajetoria da referencia)"),
            [QgsProcessing.TypeVectorLine],
        ))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.FIELD, self.tr("Talhao"), [QgsProcessing.TypeVectorPolygon], optional=True,
        ))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.OBSTACLES, self.tr("Obstaculos"), [QgsProcessing.TypeVectorAnyGeometry],
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.WORK_WIDTH, self.tr("Largura de trabalho (m)"),
            QgsProcessingParameterNumber.Double, defaultValue=20.0, minValue=0.01,
        ))
        self.addParameter(QgsProcessingParameterEnum(
            self.REFERENCE_TYPE, self.tr("Ponto de referencia"),
            options=[item.value for item in REFERENCE_TYPES], defaultValue=0,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.WORKING_OFFSET,
            self.tr("Posicao da ultima linha de trabalho (m; negativo = atras da referencia)"),
            QgsProcessingParameterNumber.Double, optional=True,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.REFERENCE_LATERAL, self.tr("Offset lateral da referencia (m, + direita)"),
            QgsProcessingParameterNumber.Double, defaultValue=0.0,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.IMPLEMENT_LATERAL, self.tr("Offset lateral do implemento (m, + direita)"),
            QgsProcessingParameterNumber.Double, defaultValue=0.0,
        ))
        self.addParameter(QgsProcessingParameterEnum(
            self.BORDER_MODE, self.tr("Bordadura do obstaculo"),
            options=[
                self.tr("Uma passada do implemento"),
                self.tr("Personalizada"),
                self.tr("Nenhuma"),
            ],
            defaultValue=0,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.BORDER_WIDTH, self.tr("Bordadura personalizada (m)"),
            QgsProcessingParameterNumber.Double, defaultValue=0.0, minValue=0.0,
        ))
        self.addParameter(QgsProcessingParameterEnum(
            self.STRATEGY, self.tr("Estrategia"),
            options=[self.tr("CUT + bordadura"), self.tr("Somente corte")], defaultValue=0,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.OBSTACLE_RADIUS, self.tr("Raio fisico do obstaculo (m)"),
            QgsProcessingParameterNumber.Double, defaultValue=0.0, minValue=0.0,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.SAFETY_MARGIN, self.tr("Margem de seguranca do obstaculo (m)"),
            QgsProcessingParameterNumber.Double, defaultValue=0.5, minValue=0.0,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.LATERAL_MARGIN, self.tr("Margem lateral (m)"),
            QgsProcessingParameterNumber.Double, defaultValue=0.0, minValue=0.0,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.LONGITUDINAL_MARGIN, self.tr("Margem longitudinal adicional (m)"),
            QgsProcessingParameterNumber.Double, defaultValue=0.0, minValue=0.0,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.ANTICIPATION, self.tr("Antecipacao de desligamento (m, antes de entrar na zona)"),
            QgsProcessingParameterNumber.Double, defaultValue=0.0, minValue=0.0,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.MIN_TURN_RADIUS, self.tr("Raio minimo de giro (m, opcional)"),
            QgsProcessingParameterNumber.Double, optional=True, minValue=0.0,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.TOLERANCE, self.tr("Tolerancia da distancia de corte (m)"),
            QgsProcessingParameterNumber.Double, defaultValue=0.05, minValue=0.001,
        ))
        self.addParameter(QgsProcessingParameterBoolean(
            self.GROUP, self.tr("Agrupar obstaculos proximos antes da bordadura"), defaultValue=True,
        ))
        for key, label, _geom in SINKS:
            self.addParameter(QgsProcessingParameterFeatureSink(
                key, self.tr(label), optional=True, createByDefault=True,
            ))
        self.addParameter(QgsProcessingParameterFileDestination(
            self.REPORT_FILE, self.tr("Relatorio de validacao (JSON)"),
            "JSON (*.json)", optional=True,
        ))
        self.addOutput(QgsProcessingOutputString(self.REPORT, self.tr("Relatorio")))

    def _geometry_profile(self, parameters, context) -> MachineWorkGeometry:
        offset = parameters.get(self.WORKING_OFFSET)
        has_offset = offset not in (None, "") and str(offset).upper() != "NULL"
        turn = parameters.get(self.MIN_TURN_RADIUS)
        has_turn = turn not in (None, "") and str(turn).upper() != "NULL"
        return MachineWorkGeometry(
            work_width_m=self.parameterAsDouble(parameters, self.WORK_WIDTH, context),
            reference_type=REFERENCE_TYPES[self.parameterAsEnum(parameters, self.REFERENCE_TYPE, context)],
            reference_to_working_line_longitudinal_m=(
                self.parameterAsDouble(parameters, self.WORKING_OFFSET, context) if has_offset else None
            ),
            reference_lateral_offset_m=self.parameterAsDouble(parameters, self.REFERENCE_LATERAL, context),
            implement_lateral_offset_m=self.parameterAsDouble(parameters, self.IMPLEMENT_LATERAL, context),
            safety_margin_longitudinal_m=self.parameterAsDouble(parameters, self.LONGITUDINAL_MARGIN, context),
            longitudinal_anticipation_m=self.parameterAsDouble(parameters, self.ANTICIPATION, context),
            safety_margin_lateral_m=self.parameterAsDouble(parameters, self.LATERAL_MARGIN, context),
            obstacle_border_width_m=self.parameterAsDouble(parameters, self.BORDER_WIDTH, context),
            border_mode=BORDER_MODES[self.parameterAsEnum(parameters, self.BORDER_MODE, context)],
            min_turn_radius_m=(
                self.parameterAsDouble(parameters, self.MIN_TURN_RADIUS, context) or None
            ) if has_turn else None,
        )

    def processAlgorithm(self, parameters, context, feedback):
        passes_source = self.parameterAsSource(parameters, self.PASSES, context)
        obstacle_source = self.parameterAsSource(parameters, self.OBSTACLES, context)
        field_source = self.parameterAsSource(parameters, self.FIELD, context)
        if passes_source is None or obstacle_source is None:
            raise QgsProcessingException(self.tr("Passadas e obstaculos sao obrigatorios."))
        crs = passes_source.sourceCrs()
        try:
            require_projected_metric(crs.authid(), "corte longitudinal por obstaculo")
        except CrsValidationError as exc:
            raise QgsProcessingException(str(exc)) from exc

        def transform_from(source):
            if source.sourceCrs() == crs:
                return None
            return QgsCoordinateTransform(source.sourceCrs(), crs, QgsProject.instance())

        passes = []
        self._source_lines = []
        for feature in passes_source.getFeatures():
            geometry = QgsGeometry(feature.geometry())
            if geometry.isNull() or geometry.isEmpty():
                continue
            parts = geometry.asMultiPolyline() if geometry.isMultipart() else [geometry.asPolyline()]
            part_ids = []
            for index, part in enumerate(parts, start=1):
                if len(part) >= 2:
                    pass_id = str(feature.id()) if len(parts) == 1 else f"{feature.id()}_{index}"
                    passes.append((pass_id, [(p.x(), p.y()) for p in part]))
                    part_ids.append((pass_id, part))
            if part_ids:
                self._source_lines.append((feature, part_ids))
        self._source_fields = passes_source.fields()

        radius = self.parameterAsDouble(parameters, self.OBSTACLE_RADIUS, context)
        obstacle_transform = transform_from(obstacle_source)
        obstacles = []
        ignored_obstacles = 0
        for feature in obstacle_source.getFeatures():
            geometry = QgsGeometry(feature.geometry())
            if geometry.isNull() or geometry.isEmpty():
                ignored_obstacles += 1
                continue
            if obstacle_transform is not None:
                geometry.transform(obstacle_transform)
            obstacles.append(ObstacleInput(str(feature.id()), _to_shapely(geometry), radius))

        field_polygon = None
        if field_source is not None:
            field_transform = transform_from(field_source)
            geometries = []
            for feature in field_source.getFeatures():
                geometry = QgsGeometry(feature.geometry())
                if geometry.isEmpty():
                    continue
                if field_transform is not None:
                    geometry.transform(field_transform)
                geometries.append(geometry)
            if geometries:
                field_polygon = _to_shapely(QgsGeometry.unaryUnion(geometries))

        tolerance = self.parameterAsDouble(parameters, self.TOLERANCE, context)
        try:
            simulation = simulate_obstacle_cut(
                passes,
                obstacles,
                self._geometry_profile(parameters, context),
                crs_authid=crs.authid(),
                field_polygon=field_polygon,
                safety_margin_m=self.parameterAsDouble(parameters, self.SAFETY_MARGIN, context),
                strategy=STRATEGIES[self.parameterAsEnum(parameters, self.STRATEGY, context)],
                tolerance_m=tolerance,
                group_obstacles=self.parameterAsBoolean(parameters, self.GROUP, context),
            )
        except (LongitudinalCutError, ValueError) as exc:
            raise QgsProcessingException(str(exc)) from exc

        report = dict(simulation.report)
        report["ignored_obstacle_features"] = ignored_obstacles
        if ignored_obstacles:
            feedback.pushWarning(
                self.tr(f"{ignored_obstacles} obstaculo(s) sem geometria foram ignorados.")
            )
        work_fields, work_features, identity = self._work_lines_output(simulation)
        report.update(identity)
        results = {}
        for key, _label, geom_type in SINKS:
            fields = work_fields if key == "SIM_WORK_LINES" else self._fields_for(key)
            sink, dest = self.parameterAsSink(parameters, key, context, fields, geom_type, crs)
            if sink is None:
                continue
            rows = work_features if key == "SIM_WORK_LINES" else self._features_for(key, simulation, tolerance)
            for attributes, geometry in rows:
                feature = QgsFeature(fields)
                feature.setGeometry(geometry)
                feature.setAttributes(attributes)
                sink.addFeature(feature, QgsFeatureSink.FastInsert)
            results[key] = dest

        text = json.dumps(report, indent=2, ensure_ascii=False)
        report_path = self.parameterAsFileOutput(parameters, self.REPORT_FILE, context)
        if report_path:
            Path(report_path).write_text(text, encoding="utf-8")
            results[self.REPORT_FILE] = report_path
        feedback.pushInfo(text)
        results[self.REPORT] = text
        return results

    def _work_lines_output(self, simulation):
        """Mesma camada de linhas: atributos herdados, numeracao herdada, so os cortes mudam."""
        source_fields = self._source_fields
        names = source_fields.names()
        number_field = line_number_field(names)
        id_field = line_id_field(names)
        computed = {} if number_field else spatial_line_numbers({
            feature.id(): tuple((p.x(), p.y()) for p in parts[0][1]) for feature, parts in self._source_lines
        })
        fields = QgsFields(source_fields)
        extras = [
            ("line_id", QVariant.String), ("line_number", QVariant.Int),
            ("parent_line_id", QVariant.String), ("segment_index", QVariant.Int),
            ("segment_count", QVariant.Int), ("obstacle_cut", QVariant.Int),
            ("work_off_m", QVariant.Double), ("work_on_m", QVariant.Double),
        ]
        added = [name for name, qtype in extras if name not in names]
        for name, qtype in extras:
            if name in added:
                fields.append(QgsField(name, qtype))
        by_pass = {record["pass_id"]: record for record in cut_work_line_records(simulation)}

        rows = []
        cut_lines = 0
        for feature, parts in self._source_lines:
            attrs = list(feature.attributes())
            raw_number = feature[number_field] if number_field else computed.get(feature.id())
            try:
                number = int(raw_number)
            except (TypeError, ValueError):
                number = computed.get(feature.id()) or 0
            parent_id = str(feature[id_field]) if id_field and feature[id_field] not in (None, "") \
                else line_id_for(number)
            pieces = []
            affected = False
            off = on = None
            for pass_id, original_part in parts:
                record = by_pass[pass_id]
                if not record["affected"]:
                    pieces.append(None if len(parts) == 1 else self._polyline_qgs(original_part))
                    continue
                affected = True
                off = record["work_off_m"] if off is None else off
                on = record["work_on_m"]
                pieces.extend(self._polyline(segment) for segment in record["segments"])
            cut_lines += int(affected)
            for index, geometry in enumerate(pieces, start=1):
                if geometry is None:
                    geometry = QgsGeometry(feature.geometry())
                values = {
                    "line_id": parent_id, "line_number": number, "parent_line_id": parent_id,
                    "segment_index": index, "segment_count": len(pieces),
                    "obstacle_cut": int(affected), "work_off_m": off, "work_on_m": on,
                }
                row = list(attrs)
                for name in names:
                    if name in values and name not in (number_field, id_field):
                        row[names.index(name)] = values[name]
                row.extend(values[name] for name in added)
                rows.append((row, geometry))
        identity = {
            "source_line_count": len(self._source_lines),
            "output_logical_line_count": len(self._source_lines),
            "cut_line_count": cut_lines,
            "output_segment_count": len(rows),
            "line_number_source": number_field or "computed_spatial_order",
            "clipped_by_field": False,
            "source_geometry_preserved_when_uncut": True,
        }
        return fields, rows, identity

    @staticmethod
    def _polyline_qgs(points) -> QgsGeometry:
        return QgsGeometry.fromPolylineXY(list(points))

    @staticmethod
    def _fields_for(key: str) -> QgsFields:
        fields = QgsFields()
        specs = {
            "SIM_MACHINE_PATH": [("pass_id", QVariant.String)],
            "SIM_WORKING_PATH": [("pass_id", QVariant.String)],
            "SIM_WORK_OFF_ON": [
                ("event", QVariant.String), ("pass_id", QVariant.String),
                ("reference", QVariant.String), ("offset_long_m", QVariant.Double),
                ("width_m", QVariant.Double), ("border_target_m", QVariant.Double),
                ("distance_m", QVariant.Double), ("tolerance_m", QVariant.Double),
                ("within_tol", QVariant.Int), ("station_m", QVariant.Double),
                ("working_x", QVariant.Double), ("working_y", QVariant.Double),
                ("obstacle_ids", QVariant.String), ("note", QVariant.String),
            ],
            "SIM_SAFETY_ZONE": [("obstacle_id", QVariant.String)],
            "SIM_BORDER_PASS": [
                ("cluster_id", QVariant.String), ("obstacle_ids", QVariant.String),
                ("status", QVariant.String), ("issues", QVariant.String),
            ],
        }
        for name, qtype in specs.get(key, [("area_m2", QVariant.Double)]):
            fields.append(QgsField(name, qtype))
        return fields

    @staticmethod
    def _polyline(points) -> QgsGeometry:
        return QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in points])

    def _features_for(self, key, simulation, tolerance):
        def area_feature(geometry):
            converted = _area_to_qgs(geometry)
            if converted is None:
                return []
            return [([round(geometry.area, 4)], converted)]

        if key == "SIM_MACHINE_PATH":
            return [([p.pass_id], self._polyline(p.reference_path)) for p in simulation.passes]
        if key == "SIM_WORKING_PATH":
            return [([p.pass_id], self._polyline(p.working_path)) for p in simulation.passes]
        if key == "SIM_WORK_OFF_ON":
            rows = []
            for record in work_event_records(simulation, tolerance):
                rows.append((
                    [
                        record["event"], record["pass_id"], record["reference"],
                        record["offset_long_m"], record["width_m"], record["border_target_m"],
                        record["distance_m"], record["tolerance_m"], int(record["within_tol"]),
                        record["station_m"], record["working_xy"][0], record["working_xy"][1],
                        record["obstacle_ids"], record["note"],
                    ],
                    QgsGeometry.fromPointXY(QgsPointXY(*record["reference_xy"])),
                ))
            return rows
        if key == "SIM_SAFETY_ZONE":
            return [
                ([z.obstacle_id], _area_to_qgs(z.safety_zone))
                for z in simulation.zones
                if _area_to_qgs(z.safety_zone) is not None
            ]
        if key == "SIM_MAIN_WORK_AREA":
            return area_feature(simulation.main_work_area)
        if key == "SIM_UNWORKED_BORDER":
            return area_feature(simulation.unworked_area)
        if key == "SIM_BORDER_PASS":
            return [
                ([b.cluster_id, ",".join(b.obstacle_ids), b.status.value, ",".join(b.issues)],
                 _to_qgs(b.trajectory))
                for b in simulation.border_passes
            ]
        if key == "SIM_BORDER_COVERAGE":
            rows = []
            for border in simulation.border_passes:
                rows.extend(area_feature(border.swept_area))
            return rows
        if key == "SIM_BORDER_GAPS":
            return area_feature(simulation.final_gap)
        if key == "SIM_BORDER_OVERLAPS":
            return area_feature(simulation.final_overlap)
        return []
