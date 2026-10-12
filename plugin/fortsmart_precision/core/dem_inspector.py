# -*- coding: utf-8 -*-
"""Regras do Inspetor DEM (Subfase 0F), sem Qt e sem QGIS.

So classifica e explica: nenhum raster e lido, copiado ou reprojetado aqui.
A leitura fica em `dem_raster_reader`; a tela, em `gui/dem_inspector_widget`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .project_context import SEVERITY_ERROR, SEVERITY_INFO, SEVERITY_WARNING, Diagnostic

ELEVATION_TYPES = frozenset({"Int8", "Int16", "UInt16", "Int32", "UInt32", "Float32", "Float64"})
IMAGE_TYPES = frozenset({"Byte", "ARGB32", "ARGB32_Premultiplied"})
FILE_PROVIDERS = frozenset({"gdal"})

UNIT_METERS = "m"
UNIT_FEET = "ft"
UNIT_DEGREES = "deg"
UNIT_LABELS = {UNIT_METERS: "metros", UNIT_FEET: "pés", UNIT_DEGREES: "graus"}
VERTICAL_UNCONFIRMED = "Unidade vertical não confirmada"

VERTICAL_DECLARED = "declarada pelo usuário nesta sessão"
VERTICAL_BAND = "metadado da banda"
VERTICAL_CRS = "CRS vertical"

COVERAGE_COMPLETE = "COMPLETE"
COVERAGE_PARTIAL = "PARTIAL"
COVERAGE_NONE = "NONE"
COVERAGE_UNKNOWN = "UNKNOWN"
COVERAGE_LABELS = {
    COVERAGE_COMPLETE: "completa",
    COVERAGE_PARTIAL: "parcial",
    COVERAGE_NONE: "ausente",
    COVERAGE_UNKNOWN: "não verificada",
}
COMPLETE_TOLERANCE = 0.999
MIN_PIXELS_IN_FIELD = 100
PLAUSIBLE_ELEVATION_M = (-500.0, 9000.0)

NOT_ELEVATION_CANDIDATE = "NOT_ELEVATION_CANDIDATE"
RASTER_WITHOUT_CRS = "RASTER_WITHOUT_CRS"
HORIZONTAL_IN_DEGREES = "HORIZONTAL_IN_DEGREES"
HORIZONTAL_UNIT_UNKNOWN = "HORIZONTAL_UNIT_UNKNOWN"
VERTICAL_UNIT_UNCONFIRMED = "VERTICAL_UNIT_UNCONFIRMED"
VERTICAL_UNIT_CONFLICT = "VERTICAL_UNIT_CONFLICT"
NO_NODATA_VALUE = "NO_NODATA_VALUE"
CRS_DIFFERS_FROM_FIELD = "CRS_DIFFERS_FROM_FIELD"
FIELD_NOT_SELECTED = "FIELD_NOT_SELECTED"
FIELD_BOUNDARY_MISSING = "FIELD_BOUNDARY_MISSING"
FIELD_BOUNDARY_AMBIGUOUS = "FIELD_BOUNDARY_AMBIGUOUS"
FIELD_GEOMETRY_INVALID = "FIELD_GEOMETRY_INVALID"
COVERAGE_RESULT = "COVERAGE_RESULT"
NODATA_IN_FIELD = "NODATA_IN_FIELD"
COARSE_RESOLUTION = "COARSE_RESOLUTION"
VALUES_OUT_OF_RANGE = "VALUES_OUT_OF_RANGE"
NO_VALID_VALUES = "NO_VALID_VALUES"
TRANSFORM_FAILED = "TRANSFORM_FAILED"
CHECK_FAILED = "CHECK_FAILED"


@dataclass(frozen=True)
class RasterSuitability:
    candidate: bool
    reasons: tuple = ()

    @property
    def text(self) -> str:
        if self.candidate:
            return ("Candidato a DEM: banda única numérica. O conteúdo de elevação não é comprovado pelo nome "
                    "nem pelo formato.")
        return "Não recomendado como DEM: " + "; ".join(self.reasons) + "."


@dataclass(frozen=True)
class VerticalUnit:
    unit: str | None = None
    source: str = ""
    conflict: tuple = ()

    @property
    def confirmed(self) -> bool:
        return self.unit is not None

    @property
    def text(self) -> str:
        if not self.confirmed:
            return VERTICAL_UNCONFIRMED
        return f"{UNIT_LABELS.get(self.unit, self.unit)} ({self.source})"


@dataclass(frozen=True)
class DemMetadata:
    layer_id: str
    name: str
    source: str
    provider: str
    crs: object
    horizontal_unit: str | None
    res_x: float
    res_y: float
    extent: tuple
    width: int
    height: int
    band_count: int
    data_type: str
    nodata: tuple
    vertical: VerticalUnit
    suitability: RasterSuitability

    @property
    def has_nodata(self) -> bool:
        return bool(self.nodata)


@dataclass(frozen=True)
class CoverageResult:
    status: str
    field_area: float = 0.0
    covered_fraction: float = 0.0
    nodata_fraction: float | None = None
    sampled_pixels: int = 0
    pixels_in_field: float = 0.0
    elevation: tuple | None = None
    diagnostics: tuple = field(default_factory=tuple)

    @property
    def text(self) -> str:
        label = COVERAGE_LABELS[self.status]
        if self.status in (COVERAGE_UNKNOWN, COVERAGE_NONE):
            return label.capitalize()
        parts = [f"{label.capitalize()} ({self.covered_fraction * 100:.1f}% da área dentro do raster)"]
        if self.nodata_fraction:
            parts.append(f"NoData em {self.nodata_fraction * 100:.1f}% da área amostrada")
        return "; ".join(parts)


# ------------------------------------------------------------- descoberta --
def classify_raster(*, band_count: int, data_type: str, provider: str) -> RasterSuitability:
    """Candidato so com banda unica numerica de arquivo; nunca 'DEM confirmado'."""
    reasons = []
    if band_count != 1:
        reasons.append(f"{band_count} bandas (típico de imagem ou multiespectral)")
    if data_type in IMAGE_TYPES:
        reasons.append(f"tipo {data_type} (típico de imagem ou classificação)")
    elif data_type not in ELEVATION_TYPES:
        reasons.append(f"tipo {data_type or 'desconhecido'} não representa elevação")
    if provider not in FILE_PROVIDERS:
        reasons.append(f"provedor '{provider}' (serviço ou tiles, sem valores de elevação confiáveis)")
    return RasterSuitability(not reasons, tuple(reasons))


# --------------------------------------------------------------- unidades --
def normalize_unit(text) -> str | None:
    value = str(text or "").strip().casefold().replace("_", " ")
    if value in ("m", "metre", "metres", "meter", "meters", "metro", "metros"):
        return UNIT_METERS
    if value in ("ft", "foot", "feet", "us-ft", "us survey foot", "pé", "pés", "pes"):
        return UNIT_FEET
    if value in ("deg", "degree", "degrees", "grau", "graus"):
        return UNIT_DEGREES
    return None


def resolve_vertical_unit(*, declared=None, band_unit=None, vertical_crs_unit=None) -> VerticalUnit:
    """Declaracao do usuario > metadado da banda > CRS vertical; sem nada, nao confirmada."""
    found = [
        (unit, source)
        for unit, source in (
            (normalize_unit(band_unit), VERTICAL_BAND),
            (normalize_unit(vertical_crs_unit), VERTICAL_CRS),
        )
        if unit in (UNIT_METERS, UNIT_FEET)
    ]
    conflict = tuple(sorted({f"{UNIT_LABELS[unit]} ({source})" for unit, source in found})) \
        if len({unit for unit, _ in found}) > 1 else ()
    declared_unit = normalize_unit(declared)
    if declared_unit in (UNIT_METERS, UNIT_FEET):
        return VerticalUnit(declared_unit, VERTICAL_DECLARED, conflict)
    if conflict:
        return VerticalUnit(None, "", conflict)
    if found:
        return VerticalUnit(found[0][0], found[0][1])
    return VerticalUnit()


def approx_meters(degrees: float, latitude: float, *, axis: str = "x") -> float:
    """Tamanho aproximado de um passo em graus, so para exibicao."""
    meters = abs(degrees) * 111_320.0
    return meters * math.cos(math.radians(latitude)) if axis == "x" else meters


def resolution_text(meta: DemMetadata, *, latitude: float | None = None) -> str:
    if meta.horizontal_unit == UNIT_DEGREES:
        text = f"{meta.res_x:.6g}° × {meta.res_y:.6g}°"
        if latitude is not None:
            text += (f" (aprox. {approx_meters(meta.res_x, latitude):.1f} m × "
                     f"{approx_meters(meta.res_y, latitude, axis='y'):.1f} m)")
        return text
    unit = UNIT_LABELS.get(meta.horizontal_unit, "unidades do CRS")
    return f"{meta.res_x:.4g} × {meta.res_y:.4g} {unit}"


# --------------------------------------------------------------- cobertura --
def classify_coverage(covered_fraction: float, nodata_fraction: float | None = None) -> str:
    if covered_fraction <= 0.0:
        return COVERAGE_NONE
    if covered_fraction >= COMPLETE_TOLERANCE and not (nodata_fraction or 0.0) > 1.0 - COMPLETE_TOLERANCE:
        return COVERAGE_COMPLETE
    if nodata_fraction is not None and nodata_fraction >= COMPLETE_TOLERANCE:
        return COVERAGE_NONE
    return COVERAGE_PARTIAL


def coverage_diagnostics(result: CoverageResult, *, vertical_unit: str | None = None, layer_id: str = "") -> tuple:
    found = []
    severity = {
        COVERAGE_COMPLETE: SEVERITY_INFO,
        COVERAGE_PARTIAL: SEVERITY_WARNING,
        COVERAGE_NONE: SEVERITY_ERROR,
    }.get(result.status)
    if severity is not None:
        found.append(Diagnostic(COVERAGE_RESULT, severity, f"Cobertura do talhão: {result.text}.", layer_id))
    if result.nodata_fraction:
        found.append(Diagnostic(
            NODATA_IN_FIELD, SEVERITY_WARNING,
            f"{result.nodata_fraction * 100:.1f}% da área amostrada do talhão é NoData.", layer_id))
    if result.status != COVERAGE_NONE and 0 < result.pixels_in_field < MIN_PIXELS_IN_FIELD:
        found.append(Diagnostic(
            COARSE_RESOLUTION, SEVERITY_WARNING,
            f"Só cerca de {result.pixels_in_field:.0f} pixels cobrem o talhão: resolução grosseira para "
            "análises de terreno.", layer_id))
    if result.status != COVERAGE_NONE and result.sampled_pixels and result.elevation is None:
        found.append(Diagnostic(NO_VALID_VALUES, SEVERITY_ERROR,
                                "Nenhum valor válido do raster dentro do talhão.", layer_id))
    if result.elevation is not None and not values_plausible(*result.elevation[:2], unit=vertical_unit):
        low, high = result.elevation[:2]
        found.append(Diagnostic(
            VALUES_OUT_OF_RANGE, SEVERITY_WARNING,
            f"Valores entre {low:.2f} e {high:.2f} fora da faixa típica de elevação; confirme se o raster é um DEM "
            "e qual a unidade vertical.", layer_id))
    return tuple(found)


def values_plausible(low: float, high: float, *, unit: str | None = None) -> bool:
    factor = 3.28084 if unit == UNIT_FEET else 1.0
    minimum, maximum = PLAUSIBLE_ELEVATION_M
    return minimum * factor <= low and high <= maximum * factor


# -------------------------------------------------------------- metadados --
def metadata_diagnostics(meta: DemMetadata, *, field_crs_authid: str | None = None) -> tuple:
    found = []
    layer_id = meta.layer_id
    if not meta.suitability.candidate:
        found.append(Diagnostic(NOT_ELEVATION_CANDIDATE, SEVERITY_WARNING, meta.suitability.text, layer_id))
    crs = meta.crs
    if crs is None or not crs.is_valid:
        found.append(Diagnostic(
            RASTER_WITHOUT_CRS, SEVERITY_ERROR,
            "Raster sem CRS: a cobertura do talhão não pode ser verificada. Defina o CRS na origem; o inspetor "
            "não altera o arquivo.", layer_id))
    elif meta.horizontal_unit == UNIT_DEGREES:
        found.append(Diagnostic(
            HORIZONTAL_IN_DEGREES, SEVERITY_WARNING,
            f"Unidade horizontal em graus ({crs.authid}): declividade e distâncias exigirão reprojeção para um CRS "
            "métrico (SIRGAS 2000 / UTM) numa etapa futura.", layer_id))
    elif meta.horizontal_unit is None:
        found.append(Diagnostic(HORIZONTAL_UNIT_UNKNOWN, SEVERITY_WARNING,
                                f"Unidade horizontal de {crs.authid} não identificada.", layer_id))
    if meta.vertical.conflict:
        found.append(Diagnostic(
            VERTICAL_UNIT_CONFLICT, SEVERITY_WARNING,
            "Fontes de unidade vertical divergentes: " + ", ".join(meta.vertical.conflict) + ".", layer_id))
    if not meta.vertical.confirmed:
        found.append(Diagnostic(
            VERTICAL_UNIT_UNCONFIRMED, SEVERITY_WARNING,
            f"{VERTICAL_UNCONFIRMED}: não será assumido metro. Declare a unidade se ela for conhecida.", layer_id))
    if not meta.has_nodata:
        found.append(Diagnostic(
            NO_NODATA_VALUE, SEVERITY_INFO,
            "Banda sem valor NoData: pixels vazios não podem ser distinguidos de elevação real.", layer_id))
    if (crs is not None and crs.is_valid and field_crs_authid
            and crs.authid and crs.authid != field_crs_authid):
        found.append(Diagnostic(
            CRS_DIFFERS_FROM_FIELD, SEVERITY_INFO,
            f"CRS do raster ({crs.authid}) diferente do talhão ({field_crs_authid}): a verificação transforma o "
            "limite só em memória.", layer_id))
    return tuple(found)
