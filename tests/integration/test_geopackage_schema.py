import tempfile
import unittest
from pathlib import Path

from plugin.fortsmart_precision.core.project_manager import create_project
from plugin.fortsmart_precision.database.schema import (
    ATTRIBUTE_TABLES,
    GEOMETRY_LAYERS,
    SCHEMA_VERSION,
    connect,
    get_schema_version,
)
from plugin.fortsmart_precision.database.migrations.migration_001_initial import migrate


class GeoPackageSchemaIntegrationTest(unittest.TestCase):
    def test_created_geopackage_contains_expected_tables_layers_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = create_project(
                Path(tmp) / "Projeto_FortSmart",
                project_name="Projeto Teste",
                property_name="Fazenda Teste",
                season_name="2026/27",
                master_crs="EPSG:31981",
            )

            conn = connect(result["paths"].geopackage_path)
            try:
                sqlite_tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                for table in ATTRIBUTE_TABLES:
                    self.assertIn(table, sqlite_tables)
                for layer in GEOMETRY_LAYERS:
                    self.assertIn(layer, sqlite_tables)

                contents = {
                    row[0]: row[1]
                    for row in conn.execute(
                        "SELECT table_name, data_type FROM gpkg_contents"
                    ).fetchall()
                }
                for table in ATTRIBUTE_TABLES:
                    self.assertEqual(contents[table], "attributes")
                for layer in GEOMETRY_LAYERS:
                    self.assertEqual(contents[layer], "features")

                geom_columns = {
                    row[0]: (row[1], row[2])
                    for row in conn.execute(
                        "SELECT table_name, geometry_type_name, srs_id FROM gpkg_geometry_columns"
                    ).fetchall()
                }
                for layer, geometry_type in GEOMETRY_LAYERS.items():
                    self.assertEqual(geom_columns[layer], (geometry_type, 31981))

                self.assertEqual(get_schema_version(conn), SCHEMA_VERSION)
            finally:
                conn.close()

    def test_migration_is_idempotent_when_schema_is_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = create_project(
                Path(tmp) / "Projeto_FortSmart",
                project_name="Projeto Teste",
                property_name="Fazenda Teste",
                season_name="2026/27",
                master_crs="EPSG:31981",
            )

            second = migrate(
                result["paths"].geopackage_path,
                "EPSG:31981",
                backup_dir=result["paths"].backups_dir,
                log_dir=result["paths"].logs_dir,
            )
            self.assertFalse(second["applied"])
            self.assertEqual(second["version"], SCHEMA_VERSION)

    def test_migration_creates_backup_when_existing_database_needs_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Projeto_FortSmart"
            backup_dir = root / "05_BACKUPS"
            log_dir = root / "06_LOGS"
            gpkg_path = root / "01_BANCO" / "fortsmart.gpkg"
            gpkg_path.parent.mkdir(parents=True)
            gpkg_path.write_bytes(b"placeholder")

            with self.assertRaises(Exception):
                migrate(gpkg_path, "EPSG:31981", backup_dir=backup_dir, log_dir=log_dir)

            backups = list(backup_dir.glob("fortsmart_before_migration_*.gpkg"))
            self.assertGreaterEqual(len(backups), 1)


if __name__ == "__main__":
    unittest.main()
