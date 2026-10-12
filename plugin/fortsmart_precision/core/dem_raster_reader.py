# -*- coding: utf-8 -*-
"""Leitura somente leitura de rasters e do limite do talhao para o Inspetor DEM.

Nada e gravado: o limite e transformado so numa copia em memoria e a amostra
de pixels usa um clone do provider dentro de uma QgsTask.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from qgis.core import (
    Qgis,
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsGeometry,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsTask,
)

from .dem_inspector import (
    COVERAGE_NONE,
    COVERAGE_UNKNOWN,
    FIELD_BOUNDARY_AMBIGUOUS,
    FIELD_BOUNDARY_MISSING,
    FIELD_GEOMETRY_INVALID,
    FIELD_NOT_SELECTED,
    TRANSFORM_FAILED,
    UNIT_DEGREES,
    UNIT_FEET,
    UNIT_METERS,
    CoverageResult,
    DemMetadata,
    classify_coverage,
    classify_raster,
    coverage_diagnostics,
    resolve_vertical_unit,
)
from .layer_roles import classify_layer
from .project_context import SEVERITY_ERROR, SEVERITY_INFO, SEVERITY_WARNING, Diagnostic, crs_summary

MAX_SAMPLE_SIDE = 256
BOUNDARY_ROLES = ("EXTERNAL_BOUNDARY", "OPERATIONAL_BOUNDARY")

_DISTANCE_UNITS = {
    Qgis.DistanceUnit.Meters: UNIT_METERS,
    Qgis.DistanceUnit.Degrees: UNIT_DEGREES,
    Qgis.DistanceUnit.Feet: UNIT_FEET,
    Qgis.DistanceUnit.FeetUSSurvey: UNIT_FEET,
}


# ------------------------------------------------------------- descoberta --
def raster_layers(project) -> list:
    layers = [layer for layer in project.mapLayers().values() if isinstance(layer, QgsRasterLayer)]
    return sorted(layers, key=lambda layer: layer.name().casefold())


def distance_unit(crs) -> str | None:
    if crs is None or not crs.isValid():
        return None
    return _DISTANCE_UNITS.get(crs.mapUnits())


def data_type_name(provider, band: int = 1) -> str:
    try:
        return Qgis.DataType(int(provider.dataType(band))).name
    except (TypeError, ValueError):
        return ""


def file_path(layer) -> str:
    """Caminho do arquivo so para provider de arquivo; servicos nao expoem a URL."""
    if layer.providerType() != "gdal":
        return ""
    return layer.source().split("|", 1)[0]


def band_unit_type(path: str) -> str:
    if not path:
        return ""
    try:
        from osgeo import gdal

        dataset = gdal.OpenEx(path, gdal.OF_RASTER | gdal.OF_READONLY)
        if dataset is None:
            return ""
        try:
            return str(dataset.GetRasterBand(1).GetUnitType() or "")
        finally:
            dataset = None
    except Exception:
        return ""


def vertical_crs_unit(crs) -> str | None:
    getter = getattr(crs, "verticalCrs", None)
    if crs is None or not callable(getter):
        return None
    try:
        vertical = getter()
    except Exception:
        return None
    if vertical is None or not vertical.isValid():
        return None
    return distance_unit(vertical)


def nodata_values(provider, band: int = 1) -> tuple:
    values = []
    if provider.sourceHasNoDataValue(band) and provider.useSourceNoDataValue(band):
        values.append(f"{provider.sourceNoDataValue(band):g}")
    for item in provider.userNoDataValues(band) or ():
        low, high = item.min(), item.max()
        values.append(f"{low:g}" if low == high else f"{low:g} a {high:g}")
    return tuple(values)


def read_metadata(layer, *, declared_vertical=None) -> DemMetadata:
    """Metadados do cabecalho; nenhum pixel e lido."""
    provider = layer.dataProvider()
    crs = layer.crs()
    path = file_path(layer)
    data_type = data_type_name(provider)
    extent = layer.extent()
    return DemMetadata(
        layer_id=layer.id(),
        name=layer.name(),
        source=path or f"{layer.providerType()} (serviço)",
        provider=layer.providerType(),
        crs=crs_summary(crs) if crs.isValid() else None,
        horizontal_unit=distance_unit(crs),
        res_x=float(layer.rasterUnitsPerPixelX()),
        res_y=float(layer.rasterUnitsPerPixelY()),
        extent=(extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum()),
        width=int(layer.width()),
        height=int(layer.height()),
        band_count=int(layer.bandCount()),
        data_type=data_type,
        nodata=nodata_values(provider),
        vertical=resolve_vertical_unit(
            declared=declared_vertical,
            band_unit=band_unit_type(path),
            vertical_crs_unit=vertical_crs_unit(crs),
        ),
        suitability=classify_raster(
            band_count=int(layer.bandCount()), data_type=data_type, provider=layer.providerType()
        ),
    )


# ---------------------------------------------------------------- talhao --
@dataclass
class FieldBoundary:
    field_id: str | None
    geometry: object = None
    crs: object = None
    layer_id: str = ""
    diagnostics: tuple = ()

    @property
    def available(self) -> bool:
        return self.geometry is not None

    @property
    def crs_authid(self) -> str:
        return self.crs.authid() if self.crs is not None and self.crs.isValid() else ""


def field_boundary(service, field_id) -> FieldBoundary:
    """Limite externo (ou operacional) do talhao, unido e validado so em memoria."""
    if not field_id:
        return FieldBoundary(None, diagnostics=(Diagnostic(
            FIELD_NOT_SELECTED, SEVERITY_INFO,
            "Talhão não definido: escolha o talhão de trabalho para verificar a cobertura."),))
    by_role = {role: [] for role in BOUNDARY_ROLES}
    for layer in service.field_layers(field_id):
        role, _source = classify_layer(layer)
        if role in by_role and getattr(layer, "featureCount", lambda: 0)() > 0:
            by_role[role].append(layer)
    role = next((name for name in BOUNDARY_ROLES if by_role[name]), None)
    if role is None:
        return FieldBoundary(field_id, diagnostics=(Diagnostic(
            FIELD_BOUNDARY_MISSING, SEVERITY_WARNING,
            f"Talhão '{field_id}' sem limite externo ou operacional com feições."),))
    layers = by_role[role]
    if len(layers) > 1:
        visible = service.visible_layer_ids(layers)
        shown = [layer for layer in layers if layer.id() in visible]
        layers = shown if shown else layers
    if len(layers) > 1:
        names = ", ".join(layer.name() for layer in layers)
        return FieldBoundary(field_id, diagnostics=(Diagnostic(
            FIELD_BOUNDARY_AMBIGUOUS, SEVERITY_ERROR,
            f"Mais de uma camada de limite no talhão '{field_id}' ({names}); deixe só uma visível."),))
    layer = layers[0]
    request = QgsFeatureRequest().setNoAttributes()
    parts = [feature.geometry() for feature in layer.getFeatures(request) if feature.hasGeometry()]
    geometry = QgsGeometry.unaryUnion(parts) if parts else QgsGeometry()
    diagnostics = []
    if not geometry.isNull() and not geometry.isEmpty() and not geometry.isGeosValid():
        geometry = geometry.makeValid()
        diagnostics.append(Diagnostic(
            FIELD_GEOMETRY_INVALID, SEVERITY_WARNING,
            f"Geometria do limite '{layer.name()}' inválida; a verificação usa uma cópia corrigida só em memória.",
            layer.id()))
    if geometry.isNull() or geometry.isEmpty() or geometry.area() <= 0:
        return FieldBoundary(field_id, layer_id=layer.id(), diagnostics=tuple(diagnostics) + (Diagnostic(
            FIELD_BOUNDARY_MISSING, SEVERITY_WARNING, f"Limite '{layer.name()}' sem área.", layer.id()),))
    return FieldBoundary(field_id, geometry, layer.crs(), layer.id(), tuple(diagnostics))


# -------------------------------------------------------------- cobertura --
@dataclass
class CoverageJob:
    layer_id: str
    provider: object
    geometry: object
    extent: object
    res_x: float
    res_y: float
    vertical_unit: str | None = None
    diagnostics: tuple = field(default_factory=tuple)


def prepare_coverage(layer, boundary: FieldBoundary, *, project=None, vertical_unit=None):
    """Prepara no thread principal; devolve (job ou None, diagnosticos)."""
    found = list(boundary.diagnostics)
    if not boundary.available or not layer.crs().isValid():
        return None, tuple(found)
    geometry = QgsGeometry(boundary.geometry)
    if boundary.crs is not None and boundary.crs.isValid() and boundary.crs != layer.crs():
        try:
            transform = QgsCoordinateTransform(boundary.crs, layer.crs(), project or QgsProject.instance())
            if geometry.transform(transform) != Qgis.GeometryOperationResult.Success:
                raise ValueError("transformação recusada")
        except Exception as exc:
            found.append(Diagnostic(
                TRANSFORM_FAILED, SEVERITY_ERROR,
                f"Não foi possível levar o limite de {boundary.crs_authid} para o CRS do raster: {exc}",
                layer.id()))
            return None, tuple(found)
    job = CoverageJob(
        layer_id=layer.id(),
        provider=layer.dataProvider().clone(),
        geometry=geometry,
        extent=QgsRectangle(layer.extent()),
        res_x=float(layer.rasterUnitsPerPixelX()) or 1.0,
        res_y=float(layer.rasterUnitsPerPixelY()) or 1.0,
        vertical_unit=vertical_unit,
        diagnostics=tuple(found),
    )
    return job, tuple(found)


def _canceled(feedback) -> bool:
    return feedback is not None and feedback.isCanceled()


def _inside_mask(geometry, xs, ys):
    import numpy
    import shapely

    polygon = shapely.from_wkb(bytes(geometry.asWkb()))
    grid_x, grid_y = numpy.meshgrid(xs, ys)
    return shapely.contains_xy(polygon, grid_x, grid_y)


def analyze_coverage(job: CoverageJob, feedback=None) -> CoverageResult | None:
    """Area do talhao dentro do raster + amostra limitada de pixels (NoData e faixa de valores)."""
    import numpy

    field_area = job.geometry.area()
    if field_area <= 0:
        return CoverageResult(COVERAGE_UNKNOWN, diagnostics=job.diagnostics)
    inside = job.geometry.intersection(QgsGeometry.fromRect(job.extent))
    covered = max(0.0, min(1.0, inside.area() / field_area)) if not inside.isEmpty() else 0.0
    if covered <= 0.0:
        result = CoverageResult(COVERAGE_NONE, field_area, 0.0)
        return _with_diagnostics(result, job)
    if _canceled(feedback):
        return None
    rect = inside.boundingBox()
    cols = max(1, min(MAX_SAMPLE_SIDE, math.ceil(rect.width() / job.res_x)))
    rows = max(1, min(MAX_SAMPLE_SIDE, math.ceil(rect.height() / job.res_y)))
    block = job.provider.block(1, rect, cols, rows)
    if _canceled(feedback):
        return None
    values = block.as_numpy(use_masking=True)
    mask = numpy.ma.getmaskarray(values)
    cell_w, cell_h = rect.width() / cols, rect.height() / rows
    xs = rect.xMinimum() + (numpy.arange(cols) + 0.5) * cell_w
    ys = rect.yMaximum() - (numpy.arange(rows) + 0.5) * cell_h
    in_field = _inside_mask(inside, xs, ys)
    if feedback is not None:
        feedback.setProgress(80)
    sampled = int(in_field.sum())
    nodata = int((in_field & mask).sum())
    valid = numpy.asarray(numpy.ma.getdata(values))[in_field & ~mask]
    valid = valid[numpy.isfinite(valid)]
    elevation = (float(valid.min()), float(valid.max()), float(valid.mean())) if valid.size else None
    nodata_fraction = (nodata / sampled) if sampled else None
    result = CoverageResult(
        classify_coverage(covered, nodata_fraction),
        field_area,
        covered,
        nodata_fraction,
        sampled,
        inside.area() / (job.res_x * job.res_y),
        elevation,
    )
    return _with_diagnostics(result, job)


def _with_diagnostics(result: CoverageResult, job: CoverageJob) -> CoverageResult:
    diagnostics = job.diagnostics + coverage_diagnostics(result, vertical_unit=job.vertical_unit,
                                                         layer_id=job.layer_id)
    return CoverageResult(
        result.status, result.field_area, result.covered_fraction, result.nodata_fraction,
        result.sampled_pixels, result.pixels_in_field, result.elevation, diagnostics,
    )


class DemCoverageTask(QgsTask):
    """Roda `analyze_coverage` fora da interface; `on_done(task, ok)` volta no thread principal."""

    def __init__(self, job: CoverageJob, on_done=None):
        super().__init__("FortSmart: verificar cobertura do DEM", QgsTask.CanCancel)
        self.job = job
        self.result = None
        self.error = ""
        self.on_done = on_done

    def run(self) -> bool:
        try:
            self.result = analyze_coverage(self.job, self)
        except Exception as exc:
            self.error = str(exc)
            return False
        return self.result is not None and not self.isCanceled()

    def finished(self, ok):
        callback, self.on_done = self.on_done, None
        self.job.provider = None
        if callback is not None:
            callback(self, ok)
