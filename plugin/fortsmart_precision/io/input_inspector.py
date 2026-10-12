# -*- coding: utf-8 -*-
"""Inspecao nao destrutiva de arquivos vetoriais de entrada."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import struct
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from ..models.input_report import InputInspectionReport
from ..core.crs import normalize_authid


SHAPE_TYPES = {
    0: "Null",
    1: "Point",
    3: "LineString",
    5: "Polygon",
    8: "MultiPoint",
    11: "PointZ",
    13: "LineStringZ",
    15: "PolygonZ",
    18: "MultiPointZ",
    21: "PointM",
    23: "LineStringM",
    25: "PolygonM",
    28: "MultiPointM",
}

SUPPORTED_EXTENSIONS = {
    ".shp": ("ESRI Shapefile", "ESRI Shapefile"),
    ".gpkg": ("GeoPackage", "GPKG"),
    ".geojson": ("GeoJSON", "GeoJSON"),
    ".json": ("GeoJSON", "GeoJSON"),
    ".kml": ("KML", "LIBKML"),
    ".kmz": ("KMZ", "LIBKML/ZIP"),
    ".csv": ("CSV", "CSV"),
}

INTERNAL_GPKG_TABLES = {
    "gpkg_contents",
    "gpkg_geometry_columns",
    "gpkg_spatial_ref_sys",
    "gpkg_extensions",
    "gpkg_tile_matrix",
    "gpkg_tile_matrix_set",
}


def checksum_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checksum_files(paths):
    digest = hashlib.sha256()
    for path in sorted(Path(p) for p in paths):
        digest.update(path.name.encode("utf-8"))
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def detect_prj_authid(prj_path):
    if not prj_path or not Path(prj_path).exists():
        return None
    text = Path(prj_path).read_text(encoding="utf-8", errors="ignore").upper()
    if "31980" in text or ("SIRGAS" in text and "UTM" in text and "20S" in text):
        return "EPSG:31980"
    if "31981" in text or ("SIRGAS" in text and "UTM" in text and "21S" in text):
        return "EPSG:31981"
    if "31982" in text or ("SIRGAS" in text and "UTM" in text and "22S" in text):
        return "EPSG:31982"
    if "31983" in text or ("SIRGAS" in text and "UTM" in text and "23S" in text):
        return "EPSG:31983"
    if "4674" in text or "SIRGAS" in text:
        return "EPSG:4674"
    if "4326" in text or "WGS_1984" in text or "WGS 84" in text:
        return "EPSG:4326"
    return None


def read_dbf_fields(dbf_path):
    path = Path(dbf_path)
    if not path.exists():
        return []
    data = path.read_bytes()
    if len(data) < 32:
        return []
    header_len = struct.unpack("<H", data[8:10])[0]
    fields = []
    offset = 32
    while offset + 32 <= min(header_len, len(data)):
        if data[offset] == 0x0D:
            break
        raw = data[offset : offset + 11].split(b"\x00", 1)[0]
        name = raw.decode("latin-1", errors="ignore").strip()
        if name:
            fields.append(name)
        offset += 32
    return fields


def inspect_shapefile(path):
    shp_path = Path(path)
    stem = shp_path.with_suffix("")
    components = [stem.with_suffix(ext) for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg")]
    existing = [p for p in components if p.exists()]
    report = InputInspectionReport(
        source_path=str(shp_path),
        format="ESRI Shapefile",
        driver="ESRI Shapefile",
        components=[str(p) for p in existing],
        checksum_sha256=checksum_files(existing) if existing else None,
        file_size_bytes=sum(p.stat().st_size for p in existing),
    )

    missing_required = [str(p.name) for p in components[:3] if not p.exists()]
    if missing_required:
        report.errors.extend(f"Componente obrigatorio ausente: {name}" for name in missing_required)
    if not stem.with_suffix(".prj").exists():
        report.warnings.append("Arquivo .prj ausente; CRS nao pode ser confirmado automaticamente.")
    else:
        report.crs_authid = detect_prj_authid(stem.with_suffix(".prj"))
        if not report.crs_authid:
            report.warnings.append("Arquivo .prj encontrado, mas EPSG nao foi identificado.")

    if shp_path.exists() and shp_path.stat().st_size >= 100:
        header = shp_path.read_bytes()[:100]
        try:
            shape_type = struct.unpack("<i", header[32:36])[0]
            report.geometry_type = SHAPE_TYPES.get(shape_type, f"Unknown({shape_type})")
            xmin, ymin, xmax, ymax = struct.unpack("<4d", header[36:68])
            report.extent = {"min_x": xmin, "min_y": ymin, "max_x": xmax, "max_y": ymax}
        except struct.error as exc:
            report.errors.append(f"Cabecalho SHP invalido: {exc}")

    shx_path = stem.with_suffix(".shx")
    if shx_path.exists() and shx_path.stat().st_size >= 100:
        report.feature_count = max(0, int((shx_path.stat().st_size - 100) / 8))

    report.fields = read_dbf_fields(stem.with_suffix(".dbf"))
    cpg_path = stem.with_suffix(".cpg")
    report.encoding = cpg_path.read_text(errors="ignore").strip() if cpg_path.exists() else None
    return report


def inspect_geojson(path):
    src = Path(path)
    report = InputInspectionReport(
        source_path=str(src),
        format="GeoJSON",
        driver="GeoJSON",
        components=[str(src)],
        checksum_sha256=checksum_file(src),
        file_size_bytes=src.stat().st_size,
        crs_authid=None,
        encoding="UTF-8",
    )
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except Exception as exc:
        report.errors.append(f"GeoJSON invalido: {exc}")
        return report

    crs = data.get("crs")
    if isinstance(crs, dict):
        name = crs.get("properties", {}).get("name")
        report.crs_authid = normalize_authid(name) if name else None
    if not report.crs_authid:
        report.crs_authid = "EPSG:4326"
        report.warnings.append("GeoJSON sem CRS explicito; RFC 7946 assume WGS84/EPSG:4326.")

    features = data.get("features", []) if data.get("type") == "FeatureCollection" else []
    report.feature_count = len(features)
    field_names = set()
    geom_types = set()
    xs = []
    ys = []
    empty_count = 0
    for idx, feature in enumerate(features):
        props = feature.get("properties") or {}
        field_names.update(props.keys())
        geom = feature.get("geometry")
        if not geom or not geom.get("coordinates"):
            empty_count += 1
            continue
        geom_types.add(geom.get("type", "Unknown"))
        for x, y in iter_coordinates(geom.get("coordinates")):
            xs.append(x)
            ys.append(y)
    report.fields = sorted(field_names)
    report.geometry_type = "Mixed" if len(geom_types) > 1 else (next(iter(geom_types)) if geom_types else None)
    if xs and ys:
        report.extent = {"min_x": min(xs), "min_y": min(ys), "max_x": max(xs), "max_y": max(ys)}
    if empty_count:
        report.warnings.append(f"{empty_count} feicao(oes) com geometria vazia.")
    report.metadata["empty_geometry_count"] = empty_count
    report.metadata["raw_feature_collection"] = data
    return report


def iter_coordinates(coords):
    if not isinstance(coords, list):
        return
    if len(coords) >= 2 and all(isinstance(v, (int, float)) for v in coords[:2]):
        yield float(coords[0]), float(coords[1])
        return
    for item in coords:
        yield from iter_coordinates(item)


def inspect_kml(path):
    src = Path(path)
    report = InputInspectionReport(
        source_path=str(src),
        format="KML",
        driver="LIBKML",
        components=[str(src)],
        checksum_sha256=checksum_file(src),
        file_size_bytes=src.stat().st_size,
        crs_authid="EPSG:4326",
        encoding="UTF-8",
    )
    try:
        root = ET.parse(src).getroot()
    except Exception as exc:
        report.errors.append(f"KML invalido: {exc}")
        return report
    ns = {"k": "http://www.opengis.net/kml/2.2"}
    placemarks = root.findall(".//k:Placemark", ns) or root.findall(".//Placemark")
    report.feature_count = len(placemarks)
    geom_types = set()
    for placemark in placemarks:
        for geom_name in ("Point", "LineString", "Polygon", "MultiGeometry"):
            if placemark.find(f".//k:{geom_name}", ns) is not None or placemark.find(f".//{geom_name}") is not None:
                geom_types.add(geom_name)
    report.geometry_type = "Mixed" if len(geom_types) > 1 else (next(iter(geom_types)) if geom_types else None)
    return report


def inspect_kmz(path):
    src = Path(path)
    report = InputInspectionReport(
        source_path=str(src),
        format="KMZ",
        driver="LIBKML/ZIP",
        components=[str(src)],
        checksum_sha256=checksum_file(src),
        file_size_bytes=src.stat().st_size,
        crs_authid="EPSG:4326",
    )
    try:
        with zipfile.ZipFile(src) as zf:
            names = zf.namelist()
            kml_names = [name for name in names if name.lower().endswith(".kml")]
            report.layers = [{"name": name, "format": "KML"} for name in kml_names]
            report.metadata["zip_members"] = names
            report.metadata["resources"] = [name for name in names if not name.lower().endswith(".kml")]
            if not kml_names:
                report.errors.append("KMZ sem arquivo KML interno.")
            elif len(kml_names) > 1:
                report.warnings.append("KMZ contem multiplos KML; selecione explicitamente a camada.")
    except zipfile.BadZipFile as exc:
        report.errors.append(f"KMZ invalido: {exc}")
    return report


def inspect_gpkg(path):
    src = Path(path)
    report = InputInspectionReport(
        source_path=str(src),
        format="GeoPackage",
        driver="GPKG",
        components=[str(src)],
        checksum_sha256=checksum_file(src),
        file_size_bytes=src.stat().st_size,
    )
    try:
        conn = sqlite3.connect(str(src))
        rows = conn.execute(
            """
            SELECT table_name, data_type, identifier, srs_id
            FROM gpkg_contents
            WHERE table_name NOT LIKE 'gpkg_%'
            ORDER BY table_name
            """
        ).fetchall()
        geom = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT table_name, geometry_type_name FROM gpkg_geometry_columns"
            ).fetchall()
        }
        report.layers = [
            {
                "name": table_name,
                "data_type": data_type,
                "identifier": identifier,
                "srs_id": srs_id,
                "geometry_type": geom.get(table_name),
            }
            for table_name, data_type, identifier, srs_id in rows
            if table_name not in INTERNAL_GPKG_TABLES
        ]
        feature_layers = [layer for layer in report.layers if layer.get("data_type") == "features"]
        if len(feature_layers) == 1:
            layer = feature_layers[0]
            report.geometry_type = layer.get("geometry_type")
            report.crs_authid = f"EPSG:{layer.get('srs_id')}" if layer.get("srs_id") else None
            report.feature_count = conn.execute(f"SELECT COUNT(*) FROM {layer['name']}").fetchone()[0]
        elif len(feature_layers) > 1:
            report.warnings.append("GeoPackage contem multiplas camadas espaciais; selecione uma para importar.")
    except Exception as exc:
        report.errors.append(f"GeoPackage invalido: {exc}")
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return report


def inspect_csv(path, delimiter=None, encoding="utf-8"):
    src = Path(path)
    report = InputInspectionReport(
        source_path=str(src),
        format="CSV",
        driver="CSV",
        components=[str(src)],
        checksum_sha256=checksum_file(src),
        file_size_bytes=src.stat().st_size,
        encoding=encoding,
    )
    if delimiter is None:
        report.warnings.append("Separador CSV nao informado explicitamente.")
        sample = src.read_text(encoding=encoding, errors="ignore")[:2048]
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
        report.metadata["detected_delimiter"] = delimiter
    try:
        with src.open("r", encoding=encoding, newline="") as fh:
            reader = csv.DictReader(fh, delimiter=delimiter)
            report.fields = reader.fieldnames or []
            report.feature_count = sum(1 for _ in reader)
    except Exception as exc:
        report.errors.append(f"CSV invalido: {exc}")
    return report


class InputInspector:
    """Examina arquivos sem alterar nem importar."""

    def inspect(self, source_path, **options):
        path = Path(source_path)
        if not path.exists():
            return InputInspectionReport(source_path=str(path), errors=["Arquivo nao encontrado."])
        ext = path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            return InputInspectionReport(
                source_path=str(path),
                format="Unknown",
                driver="Unknown",
                checksum_sha256=checksum_file(path) if path.is_file() else None,
                errors=[f"Formato nao suportado nesta fase: {ext}"],
            )
        if ext == ".shp":
            return inspect_shapefile(path)
        if ext == ".gpkg":
            return inspect_gpkg(path)
        if ext in (".geojson", ".json"):
            return inspect_geojson(path)
        if ext == ".kml":
            return inspect_kml(path)
        if ext == ".kmz":
            return inspect_kmz(path)
        if ext == ".csv":
            return inspect_csv(path, delimiter=options.get("delimiter"), encoding=options.get("encoding", "utf-8"))
        return InputInspectionReport(source_path=str(path), errors=["Formato nao tratado."])

