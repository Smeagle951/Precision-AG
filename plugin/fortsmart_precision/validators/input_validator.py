# -*- coding: utf-8 -*-
"""Validacao estruturada de arquivos de entrada."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from ..core.crs import inspect_authid
from ..models.input_report import (
    INVALID,
    VALID,
    VALID_WITH_WARNINGS,
    InputInspectionReport,
    InputValidationReport,
    ValidationMessage,
)


BRAZIL_APPROX_EXTENT = {
    "min_x": -74.5,
    "max_x": -34.0,
    "min_y": -34.5,
    "max_y": 6.0,
}


def message(severity, code, text, **details):
    return ValidationMessage(severity=severity, code=code, message=text, details=details)


def extent_looks_like_lonlat(extent):
    if not extent:
        return False
    return (
        -180 <= extent.get("min_x", 999) <= 180
        and -180 <= extent.get("max_x", 999) <= 180
        and -90 <= extent.get("min_y", 999) <= 90
        and -90 <= extent.get("max_y", 999) <= 90
    )


def extent_intersects_brazil(extent):
    if not extent:
        return None
    return not (
        extent.get("max_x", 0) < BRAZIL_APPROX_EXTENT["min_x"]
        or extent.get("min_x", 0) > BRAZIL_APPROX_EXTENT["max_x"]
        or extent.get("max_y", 0) < BRAZIL_APPROX_EXTENT["min_y"]
        or extent.get("min_y", 0) > BRAZIL_APPROX_EXTENT["max_y"]
    )


class InputValidator:
    """Valida o resultado de uma inspecao sem importar dados."""

    def validate(self, inspection: InputInspectionReport, csv_options=None):
        messages = []

        for error in inspection.errors:
            messages.append(message("error", "INSPECTION_ERROR", error))
        for warning in inspection.warnings:
            messages.append(message("warning", "INSPECTION_WARNING", warning))

        fmt = inspection.format
        source = Path(inspection.source_path)

        if fmt == "ESRI Shapefile":
            self._validate_shapefile(source, inspection, messages)
        elif fmt == "GeoPackage":
            self._validate_gpkg(inspection, messages)
        elif fmt == "KMZ":
            self._validate_kmz(inspection, messages)
        elif fmt == "CSV":
            self._validate_csv(inspection, messages, csv_options or {})

        self._validate_crs(inspection, messages)
        self._validate_fields(inspection, messages)
        self._validate_extent(inspection, messages)
        self._validate_geometry(inspection, messages)

        if any(msg.severity == "error" for msg in messages):
            status = INVALID
        elif any(msg.severity == "warning" for msg in messages):
            status = VALID_WITH_WARNINGS
        else:
            status = VALID

        return InputValidationReport(status=status, inspection=inspection, messages=messages)

    def _validate_shapefile(self, source, inspection, messages):
        stem = source.with_suffix("")
        required = [stem.with_suffix(ext) for ext in (".shp", ".shx", ".dbf")]
        for component in required:
            if not component.exists():
                messages.append(message("error", "SHP_COMPONENT_MISSING", f"Componente obrigatorio ausente: {component.name}"))
        if not stem.with_suffix(".prj").exists():
            messages.append(message("error", "SHP_PRJ_MISSING", "Shapefile sem .prj; defina CRS explicitamente antes de importar."))

    def _validate_gpkg(self, inspection, messages):
        layers = [layer for layer in inspection.layers if layer.get("data_type") == "features"]
        if not layers:
            messages.append(message("error", "GPKG_NO_FEATURE_LAYER", "GeoPackage sem camada espacial importavel."))
        if len(layers) > 1:
            messages.append(message("warning", "GPKG_MULTIPLE_LAYERS", "GeoPackage contem multiplas camadas; selecao explicita e obrigatoria."))
        for layer in inspection.layers:
            if str(layer.get("name", "")).startswith("gpkg_"):
                messages.append(message("error", "GPKG_INTERNAL_LAYER", "Tabela interna GeoPackage nao pode ser importada.", layer=layer.get("name")))

    def _validate_kmz(self, inspection, messages):
        kml_layers = [layer for layer in inspection.layers if str(layer.get("name", "")).lower().endswith(".kml")]
        if not kml_layers:
            messages.append(message("error", "KMZ_NO_KML", "KMZ sem KML interno."))
        if len(kml_layers) > 1:
            messages.append(message("warning", "KMZ_MULTIPLE_KML", "KMZ contem mais de um KML; selecao explicita e obrigatoria."))

    def _validate_csv(self, inspection, messages, options):
        if not options.get("x_field") or not options.get("y_field"):
            messages.append(message("error", "CSV_XY_REQUIRED", "CSV exige selecao explicita dos campos X/Y."))
        if not options.get("crs_authid"):
            messages.append(message("error", "CSV_CRS_REQUIRED", "CSV exige CRS informado explicitamente."))
        if not options.get("delimiter"):
            messages.append(message("error", "CSV_DELIMITER_REQUIRED", "CSV exige separador informado explicitamente."))

    def _validate_crs(self, inspection, messages):
        if inspection.format == "GeoPackage" and inspection.layers and not inspection.crs_authid:
            # Em GPKG multi-camada, o CRS pertence a cada camada. A selecao explicita
            # da camada e validada antes da importacao espacial.
            return
        if not inspection.crs_authid:
            messages.append(message("error", "CRS_MISSING", "CRS ausente ou nao identificado."))
            return
        info = inspect_authid(inspection.crs_authid)
        if info.is_geographic:
            messages.append(
                message(
                    "warning",
                    "CRS_GEOGRAPHIC",
                    f"CRS {info.authid} e geografico; nao use para calculos metricos antes de reprojetar.",
                )
            )

    def _validate_fields(self, inspection, messages):
        counts = Counter(name.lower() for name in inspection.fields)
        duplicates = [name for name, count in counts.items() if count > 1]
        if duplicates:
            messages.append(message("error", "DUPLICATE_FIELDS", "Campos duplicados encontrados.", fields=duplicates))

    def _validate_extent(self, inspection, messages):
        if not inspection.extent:
            return
        if extent_looks_like_lonlat(inspection.extent):
            in_brazil = extent_intersects_brazil(inspection.extent)
            if in_brazil is False:
                messages.append(message("warning", "EXTENT_OUTSIDE_BRAZIL", "Extensao geografica parece estar fora do Brasil."))
        else:
            # Coordenadas projetadas sao validadas em etapa GIS/QGIS posterior.
            return

    def _validate_geometry(self, inspection, messages):
        if inspection.feature_count == 0:
            messages.append(message("warning", "NO_FEATURES", "Arquivo sem feicoes."))
        empty_count = int(inspection.metadata.get("empty_geometry_count", 0) or 0)
        if empty_count:
            messages.append(message("warning", "EMPTY_GEOMETRY", f"{empty_count} geometria(s) vazia(s) encontradas."))
