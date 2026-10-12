# -*- coding: utf-8 -*-
"""Importacao nao destrutiva de arquivos vetoriais."""

from __future__ import annotations

import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ..core.crs import require_projected_metric
from ..core.project_manager import build_project_paths, read_project_config
from ..database.schema import connect
from ..models.input_report import INVALID, ImportResult
from ..validators.input_validator import InputValidator
from .input_inspector import InputInspector


ALGORITHM_ID = "fortsmart.import_service"
ALGORITHM_VERSION = "0.1.0"


class ImportServiceError(RuntimeError):
    pass


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def unique_storage_name(dest_dir, source_path):
    source = Path(source_path)
    token = uuid4().hex[:12]
    if source.suffix.lower() == ".shp":
        return f"{source.stem}_{token}"
    return f"{source.stem}_{token}{source.suffix}"


def copy_original_non_destructive(source_path, originals_dir):
    source = Path(source_path)
    originals_dir = Path(originals_dir)
    originals_dir.mkdir(parents=True, exist_ok=True)
    stored_name = unique_storage_name(originals_dir, source)

    if source.suffix.lower() == ".shp":
        dest_dir = originals_dir / stored_name
        dest_dir.mkdir(parents=False, exist_ok=False)
        stem = source.with_suffix("")
        copied = []
        for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
            component = stem.with_suffix(ext)
            if component.exists():
                dest = dest_dir / component.name
                shutil.copy2(component, dest)
                copied.append(dest)
        return stored_name, dest_dir, copied

    dest = originals_dir / stored_name
    shutil.copy2(source, dest)
    return stored_name, dest, [dest]


def relative_to_project(path, project_root):
    return str(Path(path).resolve().relative_to(Path(project_root).resolve()))


def signed_area_ring(coords):
    if len(coords) < 4:
        return 0.0
    total = 0.0
    for idx, (x1, y1) in enumerate(coords):
        x2, y2 = coords[(idx + 1) % len(coords)]
        total += (x1 * y2) - (x2 * y1)
    return total / 2.0


def polygon_area_m2(polygon):
    if not polygon:
        return 0.0
    outer = signed_area_ring([(float(x), float(y)) for x, y, *_ in polygon[0]])
    holes = sum(abs(signed_area_ring([(float(x), float(y)) for x, y, *_ in ring])) for ring in polygon[1:])
    return abs(outer) - holes


def geometry_area_m2(geometry, crs_authid):
    require_projected_metric(crs_authid, "calculo de area importada")
    if not geometry:
        return 0.0
    geom_type = geometry.get("type")
    coords = geometry.get("coordinates")
    if geom_type == "Polygon":
        return polygon_area_m2(coords)
    if geom_type == "MultiPolygon":
        return sum(polygon_area_m2(poly) for poly in coords)
    return 0.0


def normalize_geojson_features(raw_data, source_crs, target_crs):
    """Normaliza GeoJSON sem reprojetar coordenadas fora do runtime GIS."""
    features = raw_data.get("features", []) if raw_data.get("type") == "FeatureCollection" else []
    normalized = []
    empty_removed = 0
    polygon_to_multi = 0
    area_before = None
    area_after = None

    can_measure = source_crs == target_crs
    if can_measure:
        area_before = 0.0
        area_after = 0.0

    for idx, feature in enumerate(features):
        geom = feature.get("geometry")
        if not geom or not geom.get("coordinates"):
            empty_removed += 1
            continue
        if can_measure:
            area_before += geometry_area_m2(geom, source_crs)
        if geom.get("type") == "Polygon":
            geom = {"type": "MultiPolygon", "coordinates": [geom["coordinates"]]}
            polygon_to_multi += 1
        out_feature = {
            "id": str(feature.get("id", idx)),
            "properties": feature.get("properties") or {},
            "geometry": geom,
        }
        if can_measure:
            area_after += geometry_area_m2(geom, target_crs)
        normalized.append(out_feature)

    return {
        "features": normalized,
        "original_count": len(features),
        "imported_count": len(normalized),
        "empty_removed": empty_removed,
        "polygon_to_multi": polygon_to_multi,
        "area_before": area_before,
        "area_after": area_after,
        "reprojected": source_crs != target_crs,
    }


def load_geojson_for_import(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_csv_points(path, x_field, y_field, delimiter, encoding="utf-8"):
    features = []
    with Path(path).open("r", encoding=encoding, newline="") as fh:
        reader = csv.DictReader(fh, delimiter=delimiter)
        for idx, row in enumerate(reader):
            if row.get(x_field) in (None, "") or row.get(y_field) in (None, ""):
                continue
            x = float(str(row[x_field]).replace(",", "."))
            y = float(str(row[y_field]).replace(",", "."))
            props = dict(row)
            features.append(
                {
                    "id": str(idx),
                    "properties": props,
                    "geometry": {"type": "Point", "coordinates": [x, y]},
                }
            )
    return {
        "type": "FeatureCollection",
        "features": features,
    }


class ImportService:
    """Orquestra inspecao, validacao, copia e registro da importacao."""

    def __init__(self, inspector=None, validator=None):
        self.inspector = inspector or InputInspector()
        self.validator = validator or InputValidator()

    def import_field_boundary(self, project_root, source_path, **options):
        paths = build_project_paths(project_root)
        config = read_project_config(project_root)
        master_crs = config["master_crs"]
        require_projected_metric(master_crs, "importacao para GeoPackage mestre")

        inspection = self.inspector.inspect(source_path, **options)
        if inspection.format == "CSV" and options.get("crs_authid"):
            inspection.crs_authid = options["crs_authid"]
            inspection.geometry_type = "Point"
        validation = self.validator.validate(inspection, csv_options=options)
        if validation.status == INVALID:
            return ImportResult(
                status=INVALID,
                source_id=None,
                operation_id=None,
                output_layer=None,
                report={"reason": "validation_failed"},
                validation=validation,
            )

        source_id = str(uuid4())
        operation_id = str(uuid4())
        now = utc_now()
        copied_storage = None
        copied_files = []
        output_layer = options.get("target_layer", "field_boundaries")
        import_report = {}

        try:
            archive_source_path = options.get("archive_source_path") or source_path
            archive_inspection = self.inspector.inspect(archive_source_path)
            stored_name, stored_path, copied_files = copy_original_non_destructive(archive_source_path, paths.originals_dir)
            copied_storage = stored_path
            stored_relative = relative_to_project(stored_path, paths.root)

            import_report = self._normalize_for_field_boundary(inspection, master_crs, options)
            status = "imported" if import_report.get("spatial_rows_written") else "registered_only"

            conn = connect(paths.geopackage_path)
            try:
                with conn:
                    duplicate_checksum = archive_inspection.checksum_sha256 or inspection.checksum_sha256
                    existing = conn.execute(
                        "SELECT id FROM fs_source_files WHERE project_id = ? AND checksum_sha256 = ?",
                        (config["project_id"], duplicate_checksum),
                    ).fetchone()
                    if existing:
                        raise ImportServiceError("Arquivo duplicado: checksum ja registrado neste projeto.")

                    audit = (now, now, config.get("created_by", "local"), None, ALGORITHM_ID, ALGORITHM_VERSION, validation.status)
                    conn.execute(
                        """
                        INSERT INTO fs_source_files (
                            id, created_at, updated_at, created_by, source_id,
                            algorithm_id, algorithm_version, validation_status,
                            project_id, original_name, stored_name, source_path,
                            stored_path, stored_relative_path, checksum_sha256,
                            file_format, driver_name, file_size_bytes, crs_authid,
                            geometry_type, feature_count, import_status
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            source_id,
                            *audit,
                            config["project_id"],
                            Path(archive_source_path).name,
                            stored_name,
                            str(Path(archive_source_path)),
                            str(stored_path),
                            stored_relative,
                            archive_inspection.checksum_sha256 or inspection.checksum_sha256,
                            archive_inspection.format or inspection.format,
                            archive_inspection.driver or inspection.driver,
                            archive_inspection.file_size_bytes or inspection.file_size_bytes,
                            archive_inspection.crs_authid or inspection.crs_authid,
                            archive_inspection.geometry_type or inspection.geometry_type,
                            archive_inspection.feature_count or inspection.feature_count,
                            status,
                        ),
                    )
                    conn.execute(
                        """
                        INSERT INTO fs_operations (
                            id, created_at, updated_at, created_by, source_id,
                            algorithm_id, algorithm_version, validation_status,
                            project_id, operation_type, input_source_id, output_layer,
                            parameters_json, status, started_at, finished_at, error_message, result_summary
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            operation_id,
                            *audit,
                            config["project_id"],
                            "import_field_boundary",
                            source_id,
                            output_layer,
                            json.dumps(options, ensure_ascii=False),
                            status,
                            now,
                            utc_now(),
                            None,
                            json.dumps(import_report, ensure_ascii=False),
                        ),
                    )
                    self._insert_validation_rows(conn, config["project_id"], operation_id, validation)
                    self._write_spatial_rows(conn, output_layer, import_report, audit, source_id)
            finally:
                conn.close()

            self._write_html_report(paths.reports_dir, operation_id, archive_source_path, import_report, validation)

            return ImportResult(
                status=status,
                source_id=source_id,
                operation_id=operation_id,
                output_layer=output_layer,
                report=import_report,
                validation=validation,
            )
        except Exception:
            # Banco fica protegido por transacao. A copia em 00_ORIGINAIS e removida para nao deixar lixo de falha.
            if copied_storage and Path(copied_storage).exists():
                if Path(copied_storage).is_dir():
                    shutil.rmtree(copied_storage)
                else:
                    Path(copied_storage).unlink()
            raise

    def _normalize_for_field_boundary(self, inspection, master_crs, options):
        if inspection.format == "GeoJSON":
            raw = load_geojson_for_import(inspection.source_path)
            normalized = normalize_geojson_features(raw, inspection.crs_authid, master_crs)
            normalized["target_crs"] = master_crs
            normalized["source_crs"] = inspection.crs_authid
            normalized["spatial_rows_written"] = normalized["imported_count"]
            normalized["changes"] = [
                f"{normalized['empty_removed']} geometria(s) vazia(s) removida(s)",
                f"{normalized['polygon_to_multi']} Polygon convertido(s) para MultiPolygon",
            ]
            return normalized

        if inspection.format == "CSV":
            raw = load_csv_points(
                inspection.source_path,
                options["x_field"],
                options["y_field"],
                options["delimiter"],
                options.get("encoding", "utf-8"),
            )
            return {
                "features": raw["features"],
                "original_count": inspection.feature_count,
                "imported_count": len(raw["features"]),
                "empty_removed": 0,
                "polygon_to_multi": 0,
                "area_before": None,
                "area_after": None,
                "source_crs": inspection.crs_authid,
                "target_crs": master_crs,
                "reprojected": inspection.crs_authid != master_crs,
                "spatial_rows_written": len(raw["features"]),
                "changes": ["CSV convertido para feicoes de ponto em camada derivada"],
            }

        return {
            "features": [],
            "original_count": inspection.feature_count,
            "imported_count": 0,
            "area_before": None,
            "area_after": None,
            "source_crs": inspection.crs_authid,
            "target_crs": master_crs,
            "reprojected": inspection.crs_authid != master_crs,
            "spatial_rows_written": 0,
            "changes": ["Formato inspecionado e registrado; importacao espacial depende de runtime GIS/selecao de camada."],
        }

    def _insert_validation_rows(self, conn, project_id, operation_id, validation):
        now = utc_now()
        for msg in validation.messages:
            conn.execute(
                """
                INSERT INTO fs_validations (
                    id, created_at, updated_at, created_by, source_id,
                    algorithm_id, algorithm_version, validation_status,
                    project_id, operation_id, severity, validation_code, message,
                    feature_id, details_json, target_table, target_id, status, messages_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    now,
                    now,
                    "local",
                    None,
                    ALGORITHM_ID,
                    ALGORITHM_VERSION,
                    validation.status,
                    project_id,
                    operation_id,
                    msg.severity,
                    msg.code,
                    msg.message,
                    msg.feature_id,
                    json.dumps(msg.details, ensure_ascii=False),
                    None,
                    None,
                    validation.status,
                    json.dumps([m.to_dict() for m in validation.messages], ensure_ascii=False),
                ),
            )

    def _write_spatial_rows(self, conn, output_layer, import_report, audit, source_id):
        features = import_report.get("features") or []
        polygon_layers = {"field_boundaries", "operational_boundaries", "obstacles", "exclusion_areas"}
        line_layers = {"access_roads"}
        for feature in features:
            geom = feature.get("geometry")
            geom_type = geom.get("type") if geom else None
            if output_layer in polygon_layers and geom_type not in ("MultiPolygon", "Polygon"):
                continue
            if output_layer in line_layers and geom_type not in ("LineString", "MultiLineString"):
                continue
            conn.execute(
                f"""
                INSERT INTO {output_layer} (
                    id, created_at, updated_at, created_by, source_id,
                    algorithm_id, algorithm_version, validation_status,
                    name, area_m2, source_feature_count, imported_feature_count, geom
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    *audit[0:3],
                    source_id,
                    audit[4],
                    audit[5],
                    audit[6],
                    str(feature.get("properties", {}).get("name") or feature.get("id") or "feature"),
                    import_report.get("area_after"),
                    import_report.get("original_count"),
                    import_report.get("imported_count"),
                    json.dumps(geom, ensure_ascii=False).encode("utf-8") if geom else None,
                ),
            )

    def _write_html_report(self, reports_dir, operation_id, source_path, import_report, validation):
        reports_dir = Path(reports_dir)
        reports_dir.mkdir(parents=True, exist_ok=True)
        status_class = "ok" if validation.status == "VALID" else "warn" if validation.status == "VALID_WITH_WARNINGS" else "err"
        rows = "\n".join(
            f"<tr><td>{msg.severity}</td><td>{msg.code}</td><td>{msg.message}</td></tr>"
            for msg in validation.messages
        ) or "<tr><td colspan='3'>Sem mensagens</td></tr>"
        changes = "\n".join(f"<li>{item}</li>" for item in import_report.get("changes", [])) or "<li>Sem alteracoes registradas</li>"
        html = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <title>Relatorio de importacao FortSmart</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 32px; color: #1f2933; }}
    h1 {{ margin-bottom: 4px; }}
    .meta {{ color: #52606d; margin-bottom: 24px; }}
    .status {{ display: inline-block; padding: 4px 8px; border-radius: 4px; color: white; }}
    .ok {{ background: #2f855a; }}
    .warn {{ background: #b7791f; }}
    .err {{ background: #c53030; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 12px; }}
    th, td {{ border: 1px solid #cbd5e1; padding: 8px; text-align: left; }}
    th {{ background: #edf2f7; }}
  </style>
</head>
<body>
  <h1>Relatorio de importacao FortSmart</h1>
  <div class="meta">Operacao: {operation_id}<br>Arquivo: {source_path}</div>
  <p>Status: <span class="status {status_class}">{validation.status}</span></p>
  <h2>Resumo</h2>
  <table>
    <tr><th>Feicoes originais</th><td>{import_report.get("original_count")}</td></tr>
    <tr><th>Feicoes importadas</th><td>{import_report.get("imported_count")}</td></tr>
    <tr><th>CRS origem</th><td>{import_report.get("source_crs")}</td></tr>
    <tr><th>CRS destino</th><td>{import_report.get("target_crs")}</td></tr>
    <tr><th>Area antes (m2)</th><td>{import_report.get("area_before")}</td></tr>
    <tr><th>Area depois (m2)</th><td>{import_report.get("area_after")}</td></tr>
  </table>
  <h2>Alteracoes</h2>
  <ul>{changes}</ul>
  <h2>Validacoes</h2>
  <table>
    <tr><th>Gravidade</th><th>Codigo</th><th>Mensagem</th></tr>
    {rows}
  </table>
</body>
</html>
"""
        (reports_dir / f"import_{operation_id}.html").write_text(html, encoding="utf-8")
