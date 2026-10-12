# -*- coding: utf-8 -*-
"""Contexto de trabalho metrico para o Workspace (QGIS 3.44 / 4.x)."""

from __future__ import annotations

from dataclasses import dataclass

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
)

from ..core.crs import CrsValidationError, inspect_authid, require_projected_metric, suggest_sirgas_utm_epsg
from ..core.ab_direction import resolve_ab_direction_end


@dataclass(frozen=True)
class MetricWorkContext:
    """Geometrias e A-B ja no CRS projetado metrico de trabalho."""

    crs_authid: str
    field_geometries: list
    ab_start: tuple[float, float]
    ab_end: tuple[float, float]
    ab_path_points: tuple[tuple[float, float], ...]
    source_was_geographic: bool


def _transform_point(x: float, y: float, transform: QgsCoordinateTransform) -> tuple[float, float]:
    point = transform.transform(x, y)
    return (point.x(), point.y())


def resolve_metric_target_crs(field_layer, sample_points=()):
    """Escolhe CRS metrico de trabalho a partir do talhao (ou pontos de apoio)."""
    source_crs = field_layer.crs()
    source_authid = source_crs.authid()
    info = inspect_authid(source_authid)

    if info.is_geographic:
        lon = lat = None
        # Preferir extent (rapido) — evita unaryUnion que pode travar o QGIS.
        extent = field_layer.extent()
        if extent is not None and not extent.isEmpty():
            center = extent.center()
            lon, lat = center.x(), center.y()
        else:
            for feature in field_layer.getFeatures():
                geom = feature.geometry()
                if geom is None or geom.isEmpty():
                    continue
                try:
                    center = geom.centroid().asPoint()
                except Exception:
                    box = geom.boundingBox()
                    center = box.center()
                lon, lat = center.x(), center.y()
                break

        if lon is None and sample_points:
            lon, lat = sample_points[0]
            if abs(lon) > 180 or abs(lat) > 90:
                raise CrsValidationError(
                    "Talhao em CRS geografico sem geometria util e A-B fora de graus. "
                    "Carregue o perimetro e a A-B no mesmo CRS, ou use shapefile metrico."
                )
        if lon is None:
            raise ValueError("Talhao sem geometria para sugerir zona UTM.")

        if source_authid not in ("EPSG:4326", "EPSG:4674") and source_crs.isValid():
            geographic_crs = QgsCoordinateReferenceSystem("EPSG:4674")
            pt = QgsCoordinateTransform(
                source_crs, geographic_crs, QgsProject.instance()
            ).transform(QgsPointXY(lon, lat))
            lon, lat = pt.x(), pt.y()

        target_authid = suggest_sirgas_utm_epsg(lon, lat)
        return target_authid, QgsCoordinateReferenceSystem(target_authid), True

    require_projected_metric(source_authid, "planejamento Precision Lines")
    return source_authid, source_crs, False


def prepare_workspace_metric_context(
    field_layer,
    ab_start,
    ab_end,
    *,
    ab_path_points=(),
    ab_source_crs=None,
    selected_features_only: bool = False,
) -> MetricWorkContext:
    """Reprojeta talhao e A-B para CRS metrico em memoria, sem alterar camadas de origem."""
    if ab_start is None or ab_end is None:
        raise ValueError("Defina a linha A-B antes de continuar.")

    ab_crs = ab_source_crs or field_layer.crs()
    target_authid, target_crs, was_geographic = resolve_metric_target_crs(
        field_layer,
        sample_points=(ab_start, ab_end),
    )

    field_transform = None
    if field_layer.crs() != target_crs:
        field_transform = QgsCoordinateTransform(
            field_layer.crs(), target_crs, QgsProject.instance()
        )

    if selected_features_only and field_layer.selectedFeatureCount() > 0:
        feature_iter = field_layer.selectedFeatures()
    else:
        # Sem selecao: usa todas e o pick_field escolhe o pivo circular (nao o bbox).
        feature_iter = field_layer.getFeatures()

    field_geometries = []
    for feature in feature_iter:
        if not feature.geometry() or feature.geometry().isEmpty():
            continue
        geometry = QgsGeometry(feature.geometry())
        if field_transform is not None:
            geometry.transform(field_transform)
        field_geometries.append(geometry)

    if not field_geometries:
        raise ValueError(
            "Talhao sem geometria. "
            "Na aba 1, selecione o poligono do pivo na camada LIMITE/Boundary "
            "JA EM CRS METRICO (ex.: 'Boundary PV 1 (EPSG:31981)'). "
            "Nao use camada vazia, linha (BASE) nem EPSG:4326. "
            "Se so tiver o limite em graus, abra o Conversor de zona e reprojete "
            "para SIRGAS 2000 / UTM (recomendado pela longitude)."
        )

    ab_transform = None
    if ab_crs != target_crs:
        ab_transform = QgsCoordinateTransform(ab_crs, target_crs, QgsProject.instance())

    path = list(ab_path_points) if ab_path_points else [ab_start, ab_end]
    if ab_transform is not None:
        path = [_transform_point(x, y, ab_transform) for x, y in path]
        start = _transform_point(ab_start[0], ab_start[1], ab_transform)
        end = _transform_point(ab_end[0], ab_end[1], ab_transform)
    else:
        start, end = ab_start, ab_end

    from ..core.line_geometry import sanitize_master_polyline

    path = sanitize_master_polyline(path)
    if len(path) < 2:
        path = [start, end]
    start = path[0]
    end = path[-1]
    end = resolve_ab_direction_end(start, end, tuple(path))

    return MetricWorkContext(
        crs_authid=target_authid,
        field_geometries=field_geometries,
        ab_start=start,
        ab_end=end,
        ab_path_points=tuple(path),
        source_was_geographic=was_geographic,
    )


def transform_points_to_crs(points, source_crs, target_crs):
    """Reprojeta lista de pontos (x, y) para o CRS alvo."""
    if not points or source_crs == target_crs:
        return list(points)
    transform = QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())
    return [_transform_point(x, y, transform) for x, y in points]
