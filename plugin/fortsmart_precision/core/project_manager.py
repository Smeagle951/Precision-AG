# -*- coding: utf-8 -*-
"""Gerenciamento de projetos locais FortSmart Precision."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ..database.schema import DEFAULT_GPKG_NAME, SCHEMA_VERSION, connect, get_schema_version
from ..database.migrations.migration_001_initial import migrate
from .crs import normalize_authid, require_projected_metric


PROJECT_DIRS = (
    "00_ORIGINAIS",
    "01_BANCO",
    "02_RASTERS",
    "03_EXPORTACOES",
    "04_RELATORIOS",
    "05_BACKUPS",
    "06_LOGS",
)

PROJECT_CONFIG_FILE = "fortsmart_project.json"


class ProjectManagerError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    config_path: Path
    geopackage_path: Path
    originals_dir: Path
    database_dir: Path
    rasters_dir: Path
    exports_dir: Path
    reports_dir: Path
    backups_dir: Path
    logs_dir: Path


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_project_paths(project_root):
    root = Path(project_root)
    return ProjectPaths(
        root=root,
        config_path=root / PROJECT_CONFIG_FILE,
        geopackage_path=root / "01_BANCO" / DEFAULT_GPKG_NAME,
        originals_dir=root / "00_ORIGINAIS",
        database_dir=root / "01_BANCO",
        rasters_dir=root / "02_RASTERS",
        exports_dir=root / "03_EXPORTACOES",
        reports_dir=root / "04_RELATORIOS",
        backups_dir=root / "05_BACKUPS",
        logs_dir=root / "06_LOGS",
    )


def create_standard_dirs(paths):
    for name in PROJECT_DIRS:
        (paths.root / name).mkdir(parents=True, exist_ok=True)


def write_project_config(paths, config):
    paths.config_path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def read_project_config(project_root):
    paths = build_project_paths(project_root)
    if not paths.config_path.exists():
        raise ProjectManagerError(f"Projeto sem {PROJECT_CONFIG_FILE}: {paths.root}")
    return json.loads(paths.config_path.read_text(encoding="utf-8"))


def insert_initial_records(paths, config, created_by):
    now = utc_now()
    project_id = config["project_id"]
    property_id = str(uuid4())
    season_id = str(uuid4())

    conn = connect(paths.geopackage_path)
    try:
        with conn:
            existing = conn.execute("SELECT id FROM fs_project WHERE id = ?", (project_id,)).fetchone()
            if existing:
                return
            audit = (now, now, created_by, None, "fortsmart.project_manager", "0.1.0", "pending")
            conn.execute(
                """
                INSERT INTO fs_project (
                    id, created_at, updated_at, created_by, source_id,
                    algorithm_id, algorithm_version, validation_status,
                    project_name, property_name, season_name, master_crs,
                    project_config_path, geopackage_path
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    *audit,
                    config["project_name"],
                    config["property_name"],
                    config["season_name"],
                    config["master_crs"],
                    str(paths.config_path),
                    str(paths.geopackage_path),
                ),
            )
            conn.execute(
                """
                INSERT INTO fs_properties (
                    id, created_at, updated_at, created_by, source_id,
                    algorithm_id, algorithm_version, validation_status,
                    project_id, name
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (property_id, *audit, project_id, config["property_name"]),
            )
            conn.execute(
                """
                INSERT INTO fs_seasons (
                    id, created_at, updated_at, created_by, source_id,
                    algorithm_id, algorithm_version, validation_status,
                    project_id, name
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (season_id, *audit, project_id, config["season_name"]),
            )
    finally:
        conn.close()


def create_project(
    project_root,
    project_name,
    property_name,
    season_name,
    master_crs,
    created_by="local",
    overwrite=False,
):
    """Cria projeto FortSmart, GeoPackage e configuracao local."""
    paths = build_project_paths(project_root)
    master_crs = normalize_authid(master_crs)
    require_projected_metric(master_crs, "criacao de projeto")

    if paths.root.exists() and any(paths.root.iterdir()) and not overwrite:
        raise ProjectManagerError(
            f"A pasta do projeto ja existe e nao esta vazia: {paths.root}. "
            "Use overwrite=True somente com confirmacao explicita."
        )

    paths.root.mkdir(parents=True, exist_ok=True)
    create_standard_dirs(paths)

    migration_result = migrate(
        paths.geopackage_path,
        master_crs,
        backup_dir=paths.backups_dir,
        log_dir=paths.logs_dir,
    )

    config = {
        "project_id": str(uuid4()),
        "project_name": project_name,
        "property_name": property_name,
        "season_name": season_name,
        "master_crs": master_crs,
        "schema_version": SCHEMA_VERSION,
        "geopackage": str(paths.geopackage_path.relative_to(paths.root)),
        "created_at": utc_now(),
        "created_by": created_by,
    }
    write_project_config(paths, config)
    insert_initial_records(paths, config, created_by)

    return {
        "paths": paths,
        "config": config,
        "migration": migration_result,
    }


def validate_project(project_root):
    """Valida se um projeto local possui estrutura minima completa."""
    paths = build_project_paths(project_root)
    errors = []
    warnings = []

    if not paths.root.exists():
        errors.append("Pasta raiz do projeto nao existe.")

    for name in PROJECT_DIRS:
        if not (paths.root / name).is_dir():
            errors.append(f"Subpasta ausente: {name}")

    config = None
    if not paths.config_path.exists():
        errors.append(f"Arquivo ausente: {PROJECT_CONFIG_FILE}")
    else:
        try:
            config = read_project_config(paths.root)
        except json.JSONDecodeError as exc:
            errors.append(f"JSON de projeto invalido: {exc}")

    if not paths.geopackage_path.exists():
        errors.append("GeoPackage mestre ausente.")
    else:
        try:
            conn = connect(paths.geopackage_path)
            try:
                version = get_schema_version(conn)
                if version < SCHEMA_VERSION:
                    errors.append(f"Versao do esquema desatualizada: {version}")
            finally:
                conn.close()
        except sqlite3.Error as exc:
            errors.append(f"GeoPackage invalido ou inacessivel: {exc}")

    if config:
        try:
            require_projected_metric(config.get("master_crs"), "validacao do projeto")
        except Exception as exc:
            errors.append(str(exc))
        if config.get("schema_version") != SCHEMA_VERSION:
            warnings.append("Versao declarada no JSON difere da versao esperada.")

    return {
        "status": "ok" if not errors else "error",
        "errors": errors,
        "warnings": warnings,
        "paths": paths,
        "config": config,
    }

