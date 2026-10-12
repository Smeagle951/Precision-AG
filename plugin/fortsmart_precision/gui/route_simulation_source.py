# -*- coding: utf-8 -*-
"""Leitura somente das passadas de uma camada QGIS para o simulador de rota."""

from __future__ import annotations

from dataclasses import dataclass, field

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsProject,
)

from shapely import wkb as shapely_wkb
from shapely.ops import unary_union

from ..core.crs import inspect_authid, require_projected_metric, suggest_sirgas_utm_epsg
from ..core.headland_turn_engine import PassRecord, build_logical_passes
from ..core.layer_roles import ROLE_PROPERTY, layer_role
from ..core.planting_line_cut_engine import line_id_field, line_number_field
from ..core.simulation_route import RoutePassInput
from ..validator.obstacle_validator import ObstacleInput

FIELD_ID_FIELDS = ("fortsmart_field_id", "field_id")
OPERATION_ID_FIELDS = ("operation_id",)
ROUTE_TYPE_FIELDS = ("route_type",)
OBSTACLE_ID_FIELDS = ("obstacle_id", "id", "nome", "name")


@dataclass(frozen=True)
class RouteSource:
    passes: list[RoutePassInput]
    crs: QgsCoordinateReferenceSystem
    sequence_source: str
    feature_count: int
    # Feicoes da camada que formam cada passada (botao Corrigir).
    feature_ids: dict[str, tuple[int, ...]] = field(default_factory=dict)


def metric_crs_for_layer(layer) -> QgsCoordinateReferenceSystem:
    """CRS da camada se for metrico; camada geografica usa a zona SIRGAS/UTM do centro."""
    info = inspect_authid(layer.crs().authid())
    if not info.is_geographic:
        require_projected_metric(layer.crs().authid(), "simulacao de rota")
        return layer.crs()
    center = layer.extent().center()
    geographic = QgsCoordinateReferenceSystem("EPSG:4674")
    if layer.crs() != geographic:
        center = QgsCoordinateTransform(layer.crs(), geographic, QgsProject.instance()).transform(center)
    return QgsCoordinateReferenceSystem(suggest_sirgas_utm_epsg(center.x(), center.y()))


def _first(attributes: dict, names: tuple[str, ...]):
    lowered = {str(k).casefold(): v for k, v in attributes.items()}
    for name in names:
        value = lowered.get(name)
        if value not in (None, "") and str(value).upper() not in {"NULL", "NONE"}:
            return str(value)
    return None


def _as_int(value) -> int | None:
    try:
        if value in (None, "") or str(value).upper() == "NULL":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def read_route_source(layer, *, selected_only: bool = False) -> RouteSource:
    """Passadas logicas (trechos da mesma passada juntos) em CRS metrico.

    A camada nao e editada. Feicao sem geometria entra sem partes para a
    validacao do simulador reprovar (nada e descartado em silencio).
    """
    target = metric_crs_for_layer(layer)
    transform = None if layer.crs() == target else QgsCoordinateTransform(layer.crs(), target, QgsProject.instance())
    names = layer.fields().names()
    number_field = line_number_field(names)
    id_field = line_id_field(names)
    segment_field = "segment_index" if "segment_index" in names else None
    features = list(layer.getSelectedFeatures() if selected_only else layer.getFeatures())
    role = layer_role(layer)
    records: list[PassRecord] = []
    empty: list[RoutePassInput] = []
    meta: dict[str, tuple[str | None, str | None, str | None]] = {}
    fids: dict[str, list[int]] = {}
    feature_ids: dict[str, tuple[int, ...]] = {}
    for feature in features:
        attributes = dict(zip(names, feature.attributes()))
        if role and not _first(attributes, (ROLE_PROPERTY,)):
            attributes[ROLE_PROPERTY] = role
        number = _as_int(attributes.get(number_field)) if number_field else None
        line_id = attributes.get(id_field) if id_field else None
        line_id = None if line_id in (None, "") or str(line_id).upper() == "NULL" else str(line_id)
        segment = _as_int(attributes.get(segment_field)) if segment_field else None
        geometry = QgsGeometry(feature.geometry())
        if geometry.isNull() or geometry.isEmpty():
            pass_id = f"fid{feature.id()}"
            empty.append(RoutePassInput(pass_id, (), number))
            feature_ids[pass_id] = (feature.id(),)
            continue
        if transform is not None:
            geometry.transform(transform)
        parts = geometry.asMultiPolyline() if geometry.isMultipart() else [geometry.asPolyline()]
        degenerate = [part for part in parts if len(part) < 2]
        if degenerate:
            pass_id = f"fid{feature.id()}"
            empty.append(RoutePassInput(pass_id, tuple(tuple((p.x(), p.y()) for p in part) for part in parts), number))
            feature_ids[pass_id] = (feature.id(),)
            continue
        if len(parts) > 1:
            segment = None
            if line_id is None and number is None:
                line_id = f"fid{feature.id()}"
        identity = (
            _first(attributes, FIELD_ID_FIELDS),
            _first(attributes, OPERATION_ID_FIELDS),
            _first(attributes, ROUTE_TYPE_FIELDS),
        )
        for part in parts:
            # Mesma chave de identidade usada por build_logical_passes.
            key = line_id if line_id is not None else (f"N{number}" if number is not None else f"F{len(records)}")
            meta.setdefault(key, identity)
            if feature.id() not in fids.setdefault(key, []):
                fids[key].append(feature.id())
            records.append(PassRecord(tuple((p.x(), p.y()) for p in part), line_id, number, segment, attributes))
    logical, sequence_source = build_logical_passes(records)
    passes = []
    for item in sorted(logical, key=lambda p: p.number):
        field_id, operation_id, route_type = meta.get(item.key, (None, None, None))
        pass_id = f"P{item.number:02d}"
        feature_ids[pass_id] = tuple(fids.get(item.key, ()))
        passes.append(
            RoutePassInput(
                id=pass_id,
                segments=item.segments,
                sequence=item.number,
                field_id=field_id,
                operation_id=operation_id,
                route_type=(route_type or item.pass_class.value).upper(),
            )
        )
    return RouteSource(passes + empty, target, sequence_source, len(features), feature_ids)


def _to_shapely(geometry: QgsGeometry, transform):
    geometry = QgsGeometry(geometry)
    if geometry.isNull() or geometry.isEmpty():
        return None
    if transform is not None:
        geometry.transform(transform)
    shape = shapely_wkb.loads(bytes(geometry.asWkb()))
    return shape if shape.is_valid else shape.buffer(0)


def read_allowed_area(layer, target_crs: QgsCoordinateReferenceSystem):
    """Uniao dos poligonos da camada de limite no CRS metrico da rota (camada nao e editada)."""
    if layer is None:
        return None
    transform = None if layer.crs() == target_crs else QgsCoordinateTransform(layer.crs(), target_crs, QgsProject.instance())
    shapes = [s for s in (_to_shapely(f.geometry(), transform) for f in layer.getFeatures()) if s is not None]
    return unary_union(shapes) if shapes else None


def read_obstacles(layer, target_crs: QgsCoordinateReferenceSystem) -> list[ObstacleInput]:
    """Uma entrada por feicao (id = atributo id/nome/fid) no CRS metrico da rota."""
    if layer is None:
        return []
    transform = None if layer.crs() == target_crs else QgsCoordinateTransform(layer.crs(), target_crs, QgsProject.instance())
    names = layer.fields().names()
    obstacles = []
    for feature in layer.getFeatures():
        shape = _to_shapely(feature.geometry(), transform)
        if shape is None:
            continue
        label = _first(dict(zip(names, feature.attributes())), OBSTACLE_ID_FIELDS) or f"fid{feature.id()}"
        obstacles.append(ObstacleInput(label, shape))
    return obstacles
