import json
import tempfile
import unittest
from pathlib import Path

from plugin.fortsmart_precision.core.project_manager import (
    PROJECT_DIRS,
    ProjectManagerError,
    create_project,
    validate_project,
)
from plugin.fortsmart_precision.database.schema import SCHEMA_VERSION, connect, get_schema_version


class ProjectManagerTest(unittest.TestCase):
    def test_create_project_writes_standard_structure_and_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "Projeto_FortSmart"
            result = create_project(
                project_root,
                project_name="Projeto Teste",
                property_name="Fazenda Teste",
                season_name="2026/27",
                master_crs="EPSG:31981",
                created_by="tests",
            )

            self.assertTrue(result["paths"].config_path.exists())
            self.assertTrue(result["paths"].geopackage_path.exists())
            for dirname in PROJECT_DIRS:
                self.assertTrue((project_root / dirname).is_dir())

            config = json.loads(result["paths"].config_path.read_text(encoding="utf-8"))
            self.assertEqual(config["master_crs"], "EPSG:31981")
            self.assertEqual(config["schema_version"], SCHEMA_VERSION)
            self.assertTrue(config["project_id"])

    def test_existing_non_empty_project_requires_overwrite_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "Projeto_FortSmart"
            project_root.mkdir()
            (project_root / "arquivo_existente.txt").write_text("x", encoding="utf-8")

            with self.assertRaises(ProjectManagerError):
                create_project(
                    project_root,
                    project_name="Projeto Teste",
                    property_name="Fazenda Teste",
                    season_name="2026/27",
                    master_crs="EPSG:31981",
                )

    def test_validate_project_reports_ok_after_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "Projeto_FortSmart"
            create_project(
                project_root,
                project_name="Projeto Teste",
                property_name="Fazenda Teste",
                season_name="2026/27",
                master_crs="EPSG:31981",
            )

            validation = validate_project(project_root)
            self.assertEqual(validation["status"], "ok")
            self.assertEqual(validation["errors"], [])

    def test_schema_version_is_stored_in_geopackage(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "Projeto_FortSmart"
            result = create_project(
                project_root,
                project_name="Projeto Teste",
                property_name="Fazenda Teste",
                season_name="2026/27",
                master_crs="EPSG:31981",
            )

            conn = connect(result["paths"].geopackage_path)
            try:
                self.assertEqual(get_schema_version(conn), SCHEMA_VERSION)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()

