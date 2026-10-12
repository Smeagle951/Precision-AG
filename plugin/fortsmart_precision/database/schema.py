# -*- coding: utf-8 -*-
"""Esquema inicial do GeoPackage FortSmart Precision."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


SCHEMA_VERSION = 1
DEFAULT_GPKG_NAME = "fortsmart.gpkg"

ATTRIBUTE_TABLES = (
    "fs_project",
    "fs_properties",
    "fs_farms",
    "fs_seasons",
    "fs_fields",
    "fs_source_files",
    "fs_operations",
    "fs_validations",
    "fs_exports",
)

GEOMETRY_LAYERS = {
    "field_boundaries": "POLYGON",
    "operational_boundaries": "POLYGON",
    "obstacles": "POLYGON",
    "access_roads": "LINESTRING",
    "exclusion_areas": "POLYGON",
}


@dataclass(frozen=True)
class SchemaTable:
    name: str
    kind: str


def connect(gpkg_path):
    conn = sqlite3.connect(str(gpkg_path))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_geopackage_base(conn):
    """Cria metadados minimos exigidos pelo padrao GeoPackage."""
    conn.executescript(
        """
        PRAGMA application_id = 1196437808;
        PRAGMA user_version = 10400;

        CREATE TABLE IF NOT EXISTS gpkg_spatial_ref_sys (
            srs_name TEXT NOT NULL,
            srs_id INTEGER NOT NULL PRIMARY KEY,
            organization TEXT NOT NULL,
            organization_coordsys_id INTEGER NOT NULL,
            definition TEXT NOT NULL,
            description TEXT
        );

        CREATE TABLE IF NOT EXISTS gpkg_contents (
            table_name TEXT NOT NULL PRIMARY KEY,
            data_type TEXT NOT NULL,
            identifier TEXT UNIQUE,
            description TEXT DEFAULT '',
            last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            min_x DOUBLE,
            min_y DOUBLE,
            max_x DOUBLE,
            max_y DOUBLE,
            srs_id INTEGER,
            CONSTRAINT fk_gc_r_srs_id FOREIGN KEY (srs_id)
                REFERENCES gpkg_spatial_ref_sys(srs_id)
        );

        CREATE TABLE IF NOT EXISTS gpkg_geometry_columns (
            table_name TEXT NOT NULL,
            column_name TEXT NOT NULL,
            geometry_type_name TEXT NOT NULL,
            srs_id INTEGER NOT NULL,
            z TINYINT NOT NULL,
            m TINYINT NOT NULL,
            CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name),
            CONSTRAINT fk_gc_tn FOREIGN KEY (table_name)
                REFERENCES gpkg_contents(table_name),
            CONSTRAINT fk_gc_srs FOREIGN KEY (srs_id)
                REFERENCES gpkg_spatial_ref_sys(srs_id)
        );
        """
    )
    conn.executemany(
        """
        INSERT OR IGNORE INTO gpkg_spatial_ref_sys
            (srs_name, srs_id, organization, organization_coordsys_id, definition, description)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            ("Undefined cartesian SRS", -1, "NONE", -1, "undefined", "undefined cartesian coordinate reference system"),
            ("Undefined geographic SRS", 0, "NONE", 0, "undefined", "undefined geographic coordinate reference system"),
            ("WGS 84 geodetic", 4326, "EPSG", 4326, "EPSG:4326", "longitude/latitude coordinates in decimal degrees"),
            ("SIRGAS 2000 / UTM zone 20S", 31980, "EPSG", 31980, "EPSG:31980", "SIRGAS 2000 / UTM zone 20S"),
            ("SIRGAS 2000 / UTM zone 21S", 31981, "EPSG", 31981, "EPSG:31981", "SIRGAS 2000 / UTM zone 21S"),
            ("SIRGAS 2000 / UTM zone 22S", 31982, "EPSG", 31982, "EPSG:31982", "SIRGAS 2000 / UTM zone 22S"),
            ("SIRGAS 2000 / UTM zone 23S", 31983, "EPSG", 31983, "EPSG:31983", "SIRGAS 2000 / UTM zone 23S"),
        ],
    )


def audit_columns_sql():
    return """
        id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        source_id TEXT,
        algorithm_id TEXT,
        algorithm_version TEXT,
        validation_status TEXT NOT NULL DEFAULT 'pending'
    """


def create_attribute_tables(conn):
    audit = audit_columns_sql()
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS fs_project (
            {audit},
            project_name TEXT NOT NULL,
            property_name TEXT NOT NULL,
            season_name TEXT NOT NULL,
            master_crs TEXT NOT NULL,
            project_config_path TEXT NOT NULL,
            geopackage_path TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fs_properties (
            {audit},
            project_id TEXT NOT NULL,
            name TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES fs_project(id)
        );

        CREATE TABLE IF NOT EXISTS fs_farms (
            {audit},
            property_id TEXT,
            name TEXT NOT NULL,
            FOREIGN KEY (property_id) REFERENCES fs_properties(id)
        );

        CREATE TABLE IF NOT EXISTS fs_seasons (
            {audit},
            project_id TEXT NOT NULL,
            name TEXT NOT NULL,
            start_date TEXT,
            end_date TEXT,
            FOREIGN KEY (project_id) REFERENCES fs_project(id)
        );

        CREATE TABLE IF NOT EXISTS fs_fields (
            {audit},
            project_id TEXT NOT NULL,
            name TEXT NOT NULL,
            boundary_id TEXT,
            FOREIGN KEY (project_id) REFERENCES fs_project(id)
        );

        CREATE TABLE IF NOT EXISTS fs_source_files (
            {audit},
            project_id TEXT NOT NULL,
            original_name TEXT NOT NULL,
            stored_name TEXT,
            source_path TEXT,
            stored_path TEXT NOT NULL,
            stored_relative_path TEXT,
            checksum_sha256 TEXT NOT NULL,
            file_format TEXT,
            driver_name TEXT,
            file_size_bytes INTEGER,
            crs_authid TEXT,
            geometry_type TEXT,
            feature_count INTEGER,
            import_status TEXT,
            FOREIGN KEY (project_id) REFERENCES fs_project(id)
        );

        CREATE TABLE IF NOT EXISTS fs_operations (
            {audit},
            project_id TEXT NOT NULL,
            operation_type TEXT NOT NULL,
            input_source_id TEXT,
            output_layer TEXT,
            parameters_json TEXT NOT NULL DEFAULT '{{}}',
            status TEXT,
            started_at TEXT,
            finished_at TEXT,
            error_message TEXT,
            result_summary TEXT,
            FOREIGN KEY (project_id) REFERENCES fs_project(id),
            FOREIGN KEY (input_source_id) REFERENCES fs_source_files(id)
        );

        CREATE TABLE IF NOT EXISTS fs_validations (
            {audit},
            project_id TEXT NOT NULL,
            operation_id TEXT,
            severity TEXT,
            validation_code TEXT,
            message TEXT,
            feature_id TEXT,
            details_json TEXT,
            target_table TEXT,
            target_id TEXT,
            status TEXT NOT NULL,
            messages_json TEXT NOT NULL DEFAULT '[]',
            FOREIGN KEY (project_id) REFERENCES fs_project(id),
            FOREIGN KEY (operation_id) REFERENCES fs_operations(id)
        );

        CREATE TABLE IF NOT EXISTS fs_exports (
            {audit},
            project_id TEXT NOT NULL,
            profile_id TEXT,
            format TEXT NOT NULL,
            output_path TEXT NOT NULL,
            checksum_sha256 TEXT,
            validation_id TEXT,
            FOREIGN KEY (project_id) REFERENCES fs_project(id)
        );

        CREATE TABLE IF NOT EXISTS fs_schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL,
            description TEXT NOT NULL
        );
        """
    )

    for table in ATTRIBUTE_TABLES:
        conn.execute(
            """
            INSERT OR IGNORE INTO gpkg_contents
                (table_name, data_type, identifier, description, srs_id)
            VALUES (?, 'attributes', ?, ?, NULL)
            """,
            (table, table, "FortSmart attribute table"),
        )


def create_geometry_layers(conn, srs_id):
    audit = audit_columns_sql()
    for layer_name, geometry_type in GEOMETRY_LAYERS.items():
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {layer_name} (
                {audit},
                name TEXT NOT NULL,
                area_m2 REAL,
                source_feature_count INTEGER,
                imported_feature_count INTEGER,
                geom BLOB
            )
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO gpkg_contents
                (table_name, data_type, identifier, description, srs_id)
            VALUES (?, 'features', ?, ?, ?)
            """,
            (layer_name, layer_name, "FortSmart geometry layer", srs_id),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO gpkg_geometry_columns
                (table_name, column_name, geometry_type_name, srs_id, z, m)
            VALUES (?, 'geom', ?, ?, 0, 0)
            """,
            (layer_name, geometry_type, srs_id),
        )


def get_schema_version(conn):
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='fs_schema_version'"
    ).fetchone()
    if not table_exists:
        return 0
    row = conn.execute("SELECT MAX(version) FROM fs_schema_version").fetchone()
    return int(row[0] or 0)


def list_expected_tables():
    return [SchemaTable(name, "attribute") for name in ATTRIBUTE_TABLES] + [
        SchemaTable(name, "feature") for name in GEOMETRY_LAYERS
    ]
