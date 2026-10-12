# -*- coding: utf-8 -*-
"""Importa linhas de plantio/aplicacao a partir de camadas QGIS para cruzamento."""

from __future__ import annotations

from qgis.core import QgsCoordinateTransform, QgsGeometry, QgsProject, QgsWkbTypes

from ..core.guidance_engine import TrafficPass
from ..core.line_geometry import MultiPolygon, Segment, azimuth_degrees
from ..core.row_engine import PlantingRow
from .geometry_bridge import GeometryBridgeError, qgs_geometry_to_multipolygon
from .line_layer_utils import extract_line_vertices


def _feature_value(feature, names, default=None):
    field_names = set(feature.fields().names())
    for name in names:
        if name not in field_names:
            continue
        value = feature[name]
        if value not in (None, ""):
            return value
    return default


def _feature_lines(layer, target_crs, *, selected_only=False):
    transform = None
    if layer.crs() != target_crs:
        transform = QgsCoordinateTransform(layer.crs(), target_crs, QgsProject.instance())

    source_features = layer.selectedFeatures() if selected_only else layer.getFeatures()
    lines = []
    for index, feature in enumerate(source_features, start=1):
        geom = feature.geometry()
        if geom is None or geom.isEmpty():
            continue
        if geom.type() != QgsWkbTypes.LineGeometry:
            continue
        points = extract_line_vertices(geom)
        if len(points) < 2:
            continue
        if transform is not None:
            points = [
                ((t := transform.transform(x, y)).x(), t.y())
                for x, y in points
            ]
        source_id = str(
            _feature_value(
                feature,
                ("fs_id", "source_id", "line_id", "pass_id"),
                f"{layer.id()}:{feature.id()}",
            )
        )
        lines.append((index, points, feature, source_id))
    return lines


def multipolygon_from_polygon_layer(layer, target_crs) -> MultiPolygon:
    """Converte camada poligonal em MultiPolygon no CRS alvo (bordadura / off)."""
    if layer is None:
        return []
    transform = None
    if layer.crs() != target_crs:
        transform = QgsCoordinateTransform(layer.crs(), target_crs, QgsProject.instance())

    result: MultiPolygon = []
    for feature in layer.getFeatures():
        geom = feature.geometry()
        if geom is None or geom.isEmpty():
            continue
        if geom.type() != QgsWkbTypes.PolygonGeometry:
            continue
        work = QgsGeometry(geom)
        if transform is not None:
            try:
                work.transform(transform)
            except Exception:
                continue
        try:
            result.extend(qgs_geometry_to_multipolygon(work))
        except GeometryBridgeError:
            continue
    return result


def planting_rows_from_line_layer(
    layer,
    target_crs,
    *,
    machine_id="imported_planter",
    selected_only=False,
):
    """Converte camada de linhas em PlantingRow para shutoff."""
    rows = []
    for index, points, feature, source_id in _feature_lines(
        layer, target_crs, selected_only=selected_only
    ):
        segment = Segment(start=points[0], end=points[-1])
        row_id = int(_feature_value(feature, ("row_id", "line_no", "line_number"), index))
        pass_id = int(_feature_value(feature, ("pass_id", "pass_no", "pass_number"), 1))
        rows.append(
            PlantingRow(
                fs_id=source_id,
                row_id=row_id,
                pass_id=pass_id,
                machine_id=machine_id,
                spacing_m=0.0,
                direction="forward",
                offset_m=0.0,
                azimuth_deg=azimuth_degrees(points[0], points[-1]),
                segment=segment,
                path_points=tuple(points),
            )
        )
    return rows


def spray_passes_from_line_layer(
    layer,
    target_crs,
    *,
    machine_id="imported_sprayer",
    width_m=1.0,
    selected_only=False,
):
    """Converte camada de linhas de aplicacao em TrafficPass."""
    passes = []
    for index, points, feature, source_id in _feature_lines(
        layer, target_crs, selected_only=selected_only
    ):
        segment = Segment(start=points[0], end=points[-1])
        pass_no = int(
            _feature_value(feature, ("pass_id", "pass_no", "pass_number", "line_no"), index)
        )
        passes.append(
            TrafficPass(
                pass_no=pass_no,
                fs_id=source_id,
                operation_id="spraying",
                spacing_m=width_m,
                width_m=width_m,
                offset_m=0.0,
                azimuth_deg=azimuth_degrees(points[0], points[-1]),
                direction="forward",
                clipped_segment=segment,
                guidance_segment=segment,
                path_points=tuple(points),
            )
        )
    return passes
