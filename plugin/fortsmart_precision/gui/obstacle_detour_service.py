# -*- coding: utf-8 -*-
"""Ponte QGIS do desvio manual: CRS metrico, aplicar com undo, historico e restauracao.

Somente a feicao escolhida e alterada, sempre dentro de um comando de edicao
da camada (Ctrl+Z). A geometria original fica na camada de desvios, que guarda
uma versao por aplicacao.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsGeometry,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
    QgsWkbTypes,
)
from shapely import wkb as shapely_wkb

from ..core.crs import inspect_authid, require_projected_metric, suggest_sirgas_utm_epsg
from ..core.layer_roles import layer_role
from ..core.obstacle_detour import DetourParameters, NearbyObstacle, ObstacleDetour, build_manual_detour
from ..core.planting_line_cut_engine import is_field_boundary_layer_name
from ..core.planting_line_cut_engine import line_id_field, line_number_field

DETOUR_LAYER_NAME = "FortSmart_Desvios_Obstaculos"
DETOUR_LAYER_PROPERTY = "fortsmart/manual_obstacle_detours"
STATUS_APPLIED = "APPLIED"
STATUS_SUPERSEDED = "SUPERSEDED"
STATUS_RESTORED = "RESTORED"
SAME_GEOMETRY_TOLERANCE_M = 0.001
# Folga da busca de obstaculos vizinhos alem de largura + zona (cobre o deslocamento lateral do desvio).
NEARBY_SEARCH_MARGIN_M = 20.0
FIELD_BOUNDARY_ROLES = ("EXTERNAL_BOUNDARY",)

DETOUR_FIELDS = (
    ("detour_id", QVariant.String),
    ("line_id", QVariant.String),
    ("obstacle_id", QVariant.String),
    ("detour_type", QVariant.String),
    ("side", QVariant.String),
    ("obstacle_radius_m", QVariant.Double),
    ("safety_margin_m", QVariant.Double),
    ("anticipation_m", QVariant.Double),
    ("return_m", QVariant.Double),
    ("reference_to_operation_m", QVariant.Double),
    ("created_at", QVariant.String),
    ("implement_width_m", QVariant.Double),
    ("direction", QVariant.String),
    ("version", QVariant.Int),
    ("status", QVariant.String),
    ("line_layer_id", QVariant.String),
    ("line_fid", QVariant.LongLong),
    ("obstacle_layer_id", QVariant.String),
    ("obstacle_fid", QVariant.LongLong),
    ("original_wkt", QVariant.String),
    ("result_wkt", QVariant.String),
    ("restored_at", QVariant.String),
    ("warnings", QVariant.String),
)

WIDTH_FIELDS = ("width_m", "work_width_m", "working_width_m", "implement_width_m", "largura_m", "largura")
RADIUS_FIELDS = ("radius_m", "obstacle_radius_m", "raio_m", "raio", "radius")
OBSTACLE_ID_FIELDS = ("obstacle_id", "obst_id", "id_obstaculo", "name", "nome", "id")


class DetourServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class DetourComputation:
    detour: ObstacleDetour
    metric_crs: QgsCoordinateReferenceSystem
    base_geometry: QgsGeometry
    superseded_record_id: int | None = None


def to_shapely(geometry: QgsGeometry):
    return shapely_wkb.loads(bytes(geometry.asWkb()))


def to_qgs(shape) -> QgsGeometry:
    geometry = QgsGeometry()
    geometry.fromWkb(shape.wkb)
    return geometry


def _transform(source, target):
    if source == target:
        return None
    return QgsCoordinateTransform(source, target, QgsProject.instance())


def transformed(geometry: QgsGeometry, source, target) -> QgsGeometry:
    result = QgsGeometry(geometry)
    transform = _transform(source, target)
    if transform is not None:
        result.transform(transform)
    return result


def metric_crs_for(layer_crs, geometry: QgsGeometry) -> QgsCoordinateReferenceSystem:
    """CRS da camada se projetado metrico; senao SIRGAS 2000 / UTM temporario."""
    info = inspect_authid(layer_crs.authid())
    if not info.is_geographic:
        require_projected_metric(layer_crs.authid(), "desvio manual de obstaculo")
        return layer_crs
    geographic = QgsCoordinateReferenceSystem("EPSG:4674")
    center = transformed(geometry, layer_crs, geographic).centroid().asPoint()
    return QgsCoordinateReferenceSystem(suggest_sirgas_utm_epsg(center.x(), center.y()))


def _attribute(feature: QgsFeature, candidates) -> object | None:
    names = {name.casefold(): name for name in feature.fields().names()}
    for candidate in candidates:
        name = names.get(candidate.casefold())
        if name is None:
            continue
        value = feature[name]
        if value not in (None, "") and str(value) != "NULL":
            return value
    return None


def line_label(feature: QgsFeature) -> str:
    names = feature.fields().names()
    id_field = line_id_field(names)
    if id_field and feature[id_field] not in (None, "") and str(feature[id_field]) != "NULL":
        return str(feature[id_field])
    number_field = line_number_field(names)
    if number_field:
        try:
            number = int(feature[number_field])
            return f"L{number:04d}" if number >= 0 else f"L-{abs(number):04d}"
        except (TypeError, ValueError):
            pass
    return f"F{feature.id()}"


def obstacle_label(feature: QgsFeature) -> str:
    value = _attribute(feature, OBSTACLE_ID_FIELDS)
    return str(value) if value is not None else f"OB-{feature.id()}"


def _positive_float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def implement_width_from(feature: QgsFeature) -> float | None:
    """Largura gravada na linha; None quando a linha nao informa (nunca inventa)."""
    return _positive_float(_attribute(feature, WIDTH_FIELDS))


def obstacle_radius_from(feature: QgsFeature) -> float | None:
    return _positive_float(_attribute(feature, RADIUS_FIELDS))


def field_layer_priority(layer) -> int | None:
    """Auto-deteccao do limite do talhao: role primeiro, depois nome."""
    if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
        return None
    if QgsWkbTypes.geometryType(layer.wkbType()) != QgsWkbTypes.PolygonGeometry:
        return None
    if layer_role(layer) in FIELD_BOUNDARY_ROLES:
        return 0
    name = layer.name().casefold().replace(" ", "_")
    if "limite_externo" in name:
        return 1
    if is_field_boundary_layer_name(layer.name()):
        return 2
    return None


def is_area_obstacle(feature: QgsFeature) -> bool:
    return QgsWkbTypes.geometryType(feature.geometry().wkbType()) == QgsWkbTypes.PolygonGeometry


def _same_geometry(first: QgsGeometry, second: QgsGeometry, layer_crs) -> bool:
    if first.isEmpty() or second.isEmpty():
        return first.isEmpty() and second.isEmpty()
    metric = metric_crs_for(layer_crs, first)
    a = to_shapely(transformed(first, layer_crs, metric))
    b = to_shapely(transformed(second, layer_crs, metric))
    return a.hausdorff_distance(b) <= SAME_GEOMETRY_TOLERANCE_M


# --- camada de desvios -----------------------------------------------------


def find_detour_layer(project=None) -> QgsVectorLayer | None:
    project = project or QgsProject.instance()
    for layer in project.mapLayers().values():
        if isinstance(layer, QgsVectorLayer) and layer.customProperty(DETOUR_LAYER_PROPERTY):
            return layer
    return None


def ensure_detour_layer(crs, project=None) -> QgsVectorLayer:
    project = project or QgsProject.instance()
    layer = find_detour_layer(project)
    if layer is not None:
        missing = [QgsField(name, kind) for name, kind in DETOUR_FIELDS if layer.fields().indexFromName(name) < 0]
        if missing and layer.dataProvider().addAttributes(missing):
            layer.updateFields()
        return layer
    layer = QgsVectorLayer(f"MultiLineString?crs={crs.authid()}", DETOUR_LAYER_NAME, "memory")
    layer.dataProvider().addAttributes([QgsField(name, kind) for name, kind in DETOUR_FIELDS])
    layer.updateFields()
    layer.setCustomProperty(DETOUR_LAYER_PROPERTY, True)
    project.addMapLayer(layer)
    return layer


def _records(record_layer: QgsVectorLayer | None, line_layer_id: str, line_fid: int) -> list[QgsFeature]:
    if record_layer is None:
        return []
    result = [
        feature
        for feature in record_layer.getFeatures()
        if feature["line_layer_id"] == line_layer_id and int(feature["line_fid"]) == int(line_fid)
    ]
    return sorted(result, key=lambda feature: (str(feature["created_at"]), int(feature["version"] or 0)))


def line_history(record_layer, line_layer, line_fid) -> list[QgsFeature]:
    return _records(record_layer, line_layer.id(), line_fid)


def active_record(record_layer, line_layer, line_fid, obstacle_id: str | None = None) -> QgsFeature | None:
    """Ultimo desvio APPLIED da linha (opcionalmente do obstaculo)."""
    applied = [
        feature
        for feature in _records(record_layer, line_layer.id(), line_fid)
        if feature["status"] == STATUS_APPLIED and (obstacle_id is None or feature["obstacle_id"] == obstacle_id)
    ]
    return applied[-1] if applied else None


def _record_is_current(record: QgsFeature, line_layer: QgsVectorLayer, line_fid: int) -> bool:
    feature = line_layer.getFeature(int(line_fid))
    if not feature.isValid():
        return False
    result = QgsGeometry.fromWkt(record["result_wkt"])
    main = _main_part(result, line_layer)
    return _same_geometry(feature.geometry(), main, line_layer.crs())


# --- calculo -----------------------------------------------------------------


def _metric_rect_in(layer, metric, line_shape, margin_m):
    minx, miny, maxx, maxy = line_shape.buffer(margin_m).bounds
    rect = QgsRectangle(minx, miny, maxx, maxy)
    transform = _transform(metric, layer.crs())
    return transform.transformBoundingBox(rect) if transform is not None else rect


def nearby_obstacles(obstacle_layer, obstacle_fid, metric, line_shape, params) -> list[NearbyObstacle]:
    """Outros obstaculos da mesma camada perto da linha (so para avisos)."""
    margin = params.implement_width_m + params.safety_radius_m + NEARBY_SEARCH_MARGIN_M
    request = QgsFeatureRequest().setFilterRect(_metric_rect_in(obstacle_layer, metric, line_shape, margin))
    result = []
    for feature in obstacle_layer.getFeatures(request):
        if feature.id() == obstacle_fid or feature.geometry().isEmpty():
            continue
        geometry = to_shapely(transformed(feature.geometry(), obstacle_layer.crs(), metric))
        result.append(NearbyObstacle(obstacle_label(feature), geometry, obstacle_radius_from(feature)))
    return result


def field_area_for(field_layer, metric, line_shape):
    """Uniao dos talhoes que tocam a linha, em CRS metrico; None sem camada."""
    if field_layer is None:
        return None
    request = QgsFeatureRequest().setFilterRect(_metric_rect_in(field_layer, metric, line_shape, 1.0))
    geometries = [
        transformed(feature.geometry(), field_layer.crs(), metric)
        for feature in field_layer.getFeatures(request)
        if not feature.geometry().isEmpty()
    ]
    if not geometries:
        return None
    union = geometries[0] if len(geometries) == 1 else QgsGeometry.unaryUnion(geometries)
    return to_shapely(union)


def compute_detour(
    line_layer: QgsVectorLayer,
    line_feature: QgsFeature,
    obstacle_layer: QgsVectorLayer,
    obstacle_feature: QgsFeature,
    params: DetourParameters,
    record_layer: QgsVectorLayer | None = None,
    field_layer: QgsVectorLayer | None = None,
) -> DetourComputation:
    """Desvio em CRS metrico; nenhuma camada e alterada."""
    obstacle_id = obstacle_label(obstacle_feature)
    base = QgsGeometry(line_feature.geometry())
    superseded = None
    record = active_record(record_layer, line_layer, line_feature.id(), obstacle_id)
    if record is not None and _record_is_current(record, line_layer, line_feature.id()):
        base = QgsGeometry.fromWkt(record["original_wkt"])
        superseded = record.id()
    if base.isEmpty():
        raise DetourServiceError("Selecione uma linha de plantio.")
    metric = metric_crs_for(line_layer.crs(), base)
    line = to_shapely(transformed(base, line_layer.crs(), metric))
    obstacle = to_shapely(transformed(obstacle_feature.geometry(), obstacle_layer.crs(), metric))
    detour = build_manual_detour(
        line,
        obstacle,
        params,
        line_id=line_label(line_feature),
        obstacle_id=obstacle_id,
        nearby_obstacles=nearby_obstacles(obstacle_layer, obstacle_feature.id(), metric, line, params),
        field_area=field_area_for(field_layer, metric, line),
    )
    return DetourComputation(detour, metric, base, superseded)


# --- aplicar / restaurar -----------------------------------------------------


def _layer_geometry(shape_or_geometry, metric, line_layer: QgsVectorLayer) -> QgsGeometry:
    geometry = shape_or_geometry if isinstance(shape_or_geometry, QgsGeometry) else to_qgs(shape_or_geometry)
    geometry = transformed(geometry, metric, line_layer.crs())
    return _match_layer_type(geometry, line_layer)


def _match_layer_type(geometry: QgsGeometry, line_layer: QgsVectorLayer) -> QgsGeometry:
    wkb_type = line_layer.wkbType()
    if QgsWkbTypes.isMultiType(wkb_type):
        geometry.convertToMultiType()
    elif geometry.isMultipart() and len(geometry.asGeometryCollection()) == 1:
        geometry.convertToSingleType()
    if QgsWkbTypes.hasZ(wkb_type) and not QgsWkbTypes.hasZ(geometry.wkbType()):
        geometry.get().addZValue(0.0)
    if QgsWkbTypes.hasM(wkb_type) and not QgsWkbTypes.hasM(geometry.wkbType()):
        geometry.get().addMValue(0.0)
    return geometry


def _parts(geometry: QgsGeometry) -> list[QgsGeometry]:
    if geometry.isMultipart():
        return [QgsGeometry(part) for part in geometry.asGeometryCollection()]
    return [QgsGeometry(geometry)]


def _main_part(result: QgsGeometry, line_layer: QgsVectorLayer) -> QgsGeometry:
    """Geometria que fica na feicao original (camadas simples recebem so a 1a parte)."""
    if QgsWkbTypes.isMultiType(line_layer.wkbType()) or not result.isMultipart():
        return _match_layer_type(QgsGeometry(result), line_layer)
    return _match_layer_type(_parts(result)[0], line_layer)


def _extra_feature_ids(line_layer: QgsVectorLayer, line_fid: int, result: QgsGeometry) -> list[int]:
    """Feicoes adicionais criadas por corte em camada de parte simples."""
    if QgsWkbTypes.isMultiType(line_layer.wkbType()) or not result.isMultipart():
        return []
    extras = [_match_layer_type(part, line_layer) for part in _parts(result)[1:]]
    found: list[int] = []
    for part in extras:
        request = QgsFeatureRequest().setFilterRect(part.boundingBox())
        for feature in line_layer.getFeatures(request):
            if feature.id() == int(line_fid) or feature.id() in found:
                continue
            if _same_geometry(feature.geometry(), part, line_layer.crs()):
                found.append(feature.id())
                break
    return found


def _copy_feature(line_layer: QgsVectorLayer, source: QgsFeature, geometry: QgsGeometry) -> QgsFeature:
    feature = QgsFeature(line_layer.fields())
    feature.setAttributes(list(source.attributes()))
    for index in line_layer.primaryKeyAttributes():
        feature.setAttribute(index, None)
    feature.setGeometry(geometry)
    return feature


def _ensure_editing(line_layer: QgsVectorLayer) -> None:
    if not line_layer.isEditable() and not line_layer.startEditing():
        raise DetourServiceError(f"Não foi possível editar a camada {line_layer.name()}.")


def apply_detour(
    line_layer: QgsVectorLayer,
    line_fid: int,
    computation: DetourComputation,
    record_layer: QgsVectorLayer,
    *,
    obstacle_layer: QgsVectorLayer | None = None,
    obstacle_fid: int | None = None,
) -> QgsFeature:
    """Altera so a feicao escolhida (comando de edicao, Ctrl+Z) e grava o historico."""
    detour = computation.detour
    if not detour.ok:
        raise DetourServiceError("O desvio não está válido; pré-visualize e corrija antes de aplicar.")
    original_feature = line_layer.getFeature(int(line_fid))
    if not original_feature.isValid():
        raise DetourServiceError("A linha selecionada não existe mais na camada.")
    result = _layer_geometry(detour.result_geometry, computation.metric_crs, line_layer)
    if result.isEmpty():
        raise DetourServiceError("⚠ O desvio gerou geometria vazia.")
    superseded = record_layer.getFeature(computation.superseded_record_id) if computation.superseded_record_id is not None else None

    _ensure_editing(line_layer)
    line_layer.beginEditCommand(f"FortSmart: desvio {detour.parameters.detour_type.value} {detour.line_id}")
    try:
        if superseded is not None and superseded.isValid():
            previous = QgsGeometry.fromWkt(superseded["result_wkt"])
            for fid in _extra_feature_ids(line_layer, line_fid, previous):
                line_layer.deleteFeature(fid)
        parts = [result] if QgsWkbTypes.isMultiType(line_layer.wkbType()) else _parts(result)
        main = _match_layer_type(parts[0], line_layer)
        if not line_layer.changeGeometry(int(line_fid), main):
            raise DetourServiceError("A camada recusou a nova geometria.")
        for part in parts[1:]:
            if not line_layer.addFeature(_copy_feature(line_layer, original_feature, _match_layer_type(part, line_layer))):
                raise DetourServiceError("A camada recusou a parte adicional do corte.")
        line_layer.endEditCommand()
    except Exception:
        line_layer.destroyEditCommand()
        raise
    line_layer.triggerRepaint()
    return _write_record(
        record_layer, line_layer, line_fid, computation, result, superseded, obstacle_layer, obstacle_fid
    )


def _write_record(record_layer, line_layer, line_fid, computation, result, superseded, obstacle_layer, obstacle_fid):
    detour = computation.detour
    history = _records(record_layer, line_layer.id(), line_fid)
    version = 1 + max((int(item["version"] or 0) for item in history), default=0)
    provider = record_layer.dataProvider()
    if superseded is not None and superseded.isValid():
        index = record_layer.fields().indexFromName("status")
        provider.changeAttributeValues({superseded.id(): {index: STATUS_SUPERSEDED}})
    record_geometry = transformed(result, line_layer.crs(), record_layer.crs())
    record_geometry.convertToMultiType()
    values = detour.record_attributes(datetime.now().isoformat(timespec="seconds"))
    values.update(
        implement_width_m=detour.parameters.implement_width_m,
        direction=detour.parameters.direction.value,
        version=version,
        status=STATUS_APPLIED,
        line_layer_id=line_layer.id(),
        line_fid=int(line_fid),
        obstacle_layer_id=obstacle_layer.id() if obstacle_layer is not None else "",
        obstacle_fid=int(obstacle_fid) if obstacle_fid is not None else None,
        original_wkt=computation.base_geometry.asWkt(17),
        result_wkt=result.asWkt(17),
        warnings=" | ".join(detour.warnings),
    )
    feature = QgsFeature(record_layer.fields())
    feature.setGeometry(record_geometry)
    for name, value in values.items():
        index = record_layer.fields().indexFromName(name)
        if index >= 0:
            feature.setAttribute(index, value)
    ok, added = provider.addFeatures([feature])
    if not ok:
        raise DetourServiceError("Não foi possível gravar o histórico do desvio.")
    record_layer.triggerRepaint()
    return added[0]


def restore_original(line_layer: QgsVectorLayer, line_fid: int, record_layer: QgsVectorLayer) -> QgsFeature:
    """Volta a linha para a geometria anterior ao ultimo desvio aplicado (Ctrl+Z desfaz)."""
    record = active_record(record_layer, line_layer, line_fid)
    if record is None:
        raise DetourServiceError("Esta linha não possui desvio aplicado.")
    original = _match_layer_type(QgsGeometry.fromWkt(record["original_wkt"]), line_layer)
    result = QgsGeometry.fromWkt(record["result_wkt"])
    extras = _extra_feature_ids(line_layer, line_fid, result)
    _ensure_editing(line_layer)
    line_layer.beginEditCommand(f"FortSmart: restaurar linha {record['line_id']}")
    try:
        for fid in extras:
            line_layer.deleteFeature(fid)
        if not line_layer.changeGeometry(int(line_fid), original):
            raise DetourServiceError("A camada recusou a geometria original.")
        line_layer.endEditCommand()
    except Exception:
        line_layer.destroyEditCommand()
        raise
    line_layer.triggerRepaint()
    fields = record_layer.fields()
    record_layer.dataProvider().changeAttributeValues({
        record.id(): {
            fields.indexFromName("status"): STATUS_RESTORED,
            fields.indexFromName("restored_at"): datetime.now().isoformat(timespec="seconds"),
        }
    })
    record_layer.triggerRepaint()
    return record
