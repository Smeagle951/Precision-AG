# -*- coding: utf-8 -*-
"""Migracao 001: esquema inicial FortSmart."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
import sqlite3
from pathlib import Path

from ..schema import (
    SCHEMA_VERSION,
    connect,
    create_attribute_tables,
    create_geopackage_base,
    create_geometry_layers,
    get_schema_version,
)
from ...core.crs import normalize_authid, require_projected_metric


class MigrationError(RuntimeError):
    pass


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def epsg_srs_id(authid):
    normalized = normalize_authid(authid)
    if not normalized.startswith("EPSG:"):
        raise MigrationError(f"CRS mestre sem EPSG reconhecido: {authid}")
    return int(normalized.split(":", 1)[1])


def backup_geopackage(gpkg_path, backup_dir):
    gpkg_path = Path(gpkg_path)
    if not gpkg_path.exists():
        return None

    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"{gpkg_path.stem}_before_migration_{stamp}{gpkg_path.suffix}"
    shutil.copy2(gpkg_path, backup_path)
    return backup_path


def append_log(log_dir, message):
    if log_dir is None:
        return
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "migrations.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{utc_now()} {message}\n")


def migrate(gpkg_path, master_crs, backup_dir=None, log_dir=None):
    """Aplica a migracao inicial em transacao, com backup quando o banco existir."""
    require_projected_metric(master_crs, "criacao do GeoPackage mestre")
    gpkg_path = Path(gpkg_path)
    gpkg_path.parent.mkdir(parents=True, exist_ok=True)

    conn = connect(gpkg_path)
    try:
        backup_path = None
        try:
            current_version = get_schema_version(conn)
        except sqlite3.DatabaseError:
            conn.close()
            backup_path = backup_geopackage(gpkg_path, backup_dir)
            append_log(log_dir, "migration_001 failed before version check invalid_database")
            raise

        if current_version >= SCHEMA_VERSION:
            append_log(log_dir, f"migration_001 skipped current_version={current_version}")
            return {"applied": False, "version": current_version, "backup": None}

        backup_path = backup_geopackage(gpkg_path, backup_dir)
        append_log(log_dir, "migration_001 started")

        with conn:
            create_geopackage_base(conn)
            create_attribute_tables(conn)
            create_geometry_layers(conn, epsg_srs_id(master_crs))
            conn.execute(
                """
                INSERT INTO fs_schema_version (version, applied_at, description)
                VALUES (?, ?, ?)
                """,
                (SCHEMA_VERSION, utc_now(), "Initial FortSmart Precision schema"),
            )

        append_log(log_dir, "migration_001 completed version=1")
        return {
            "applied": True,
            "version": SCHEMA_VERSION,
            "backup": str(backup_path) if backup_path else None,
        }
    except Exception as exc:
        conn.rollback()
        append_log(log_dir, f"migration_001 failed error={exc}")
        raise
    finally:
        conn.close()
