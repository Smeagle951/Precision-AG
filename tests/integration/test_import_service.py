import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from plugin.fortsmart_precision.core.project_manager import create_project
from plugin.fortsmart_precision.io.import_service import ImportService, ImportServiceError


def write_projected_geojson(path, include_empty=False):
    features = [
        {
            "type": "Feature",
            "id": "talhao-1",
            "properties": {"name": "Talhao 1"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0, 0], [100, 0], [100, 100], [0, 0]]],
            },
        }
    ]
    if include_empty:
        features.append({"type": "Feature", "id": "empty", "properties": {}, "geometry": None})
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": "EPSG:31981"}},
                "features": features,
            }
        ),
        encoding="utf-8",
    )
    return path


class ImportServiceIntegrationTest(unittest.TestCase):
    def test_import_geojson_copies_original_registers_rows_and_normalizes_polygon(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Projeto_FortSmart"
            create_project(root, "Projeto", "Fazenda", "2026/27", "EPSG:31981")
            source = write_projected_geojson(Path(tmp) / "talhao.geojson", include_empty=True)

            result = ImportService().import_field_boundary(root, source)

            self.assertEqual(result.status, "imported")
            self.assertEqual(result.report["original_count"], 2)
            self.assertEqual(result.report["imported_count"], 1)
            self.assertEqual(result.report["empty_removed"], 1)
            self.assertEqual(result.report["polygon_to_multi"], 1)
            self.assertEqual(result.report["area_before"], result.report["area_after"])
            self.assertTrue(list((root / "00_ORIGINAIS").glob("talhao_*.geojson")))
            self.assertTrue(list((root / "04_RELATORIOS").glob("import_*.html")))

            conn = sqlite3.connect(root / "01_BANCO" / "fortsmart.gpkg")
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM fs_source_files").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM fs_operations WHERE operation_type='import_field_boundary'").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM field_boundaries").fetchone()[0], 1)
                row = conn.execute("SELECT stored_relative_path, import_status FROM fs_source_files").fetchone()
                self.assertTrue(row[0].startswith("00_ORIGINAIS"))
                self.assertEqual(row[1], "imported")
            finally:
                conn.close()

    def test_duplicate_checksum_is_rejected_without_partial_second_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Projeto_FortSmart"
            create_project(root, "Projeto", "Fazenda", "2026/27", "EPSG:31981")
            source = write_projected_geojson(Path(tmp) / "talhao.geojson")

            ImportService().import_field_boundary(root, source)
            with self.assertRaises(ImportServiceError):
                ImportService().import_field_boundary(root, source)

            conn = sqlite3.connect(root / "01_BANCO" / "fortsmart.gpkg")
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM fs_source_files").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM fs_operations").fetchone()[0], 1)
            finally:
                conn.close()

    def test_import_failure_does_not_leave_partial_database_rows(self):
        class FailingService(ImportService):
            def _write_spatial_rows(self, conn, output_layer, import_report, audit, source_id):
                raise RuntimeError("forced failure")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Projeto_FortSmart"
            create_project(root, "Projeto", "Fazenda", "2026/27", "EPSG:31981")
            source = write_projected_geojson(Path(tmp) / "talhao.geojson")

            with self.assertRaises(RuntimeError):
                FailingService().import_field_boundary(root, source)

            conn = sqlite3.connect(root / "01_BANCO" / "fortsmart.gpkg")
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM fs_source_files").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM fs_operations").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM field_boundaries").fetchone()[0], 0)
            finally:
                conn.close()
            self.assertEqual(list((root / "00_ORIGINAIS").iterdir()), [])

    def test_project_can_be_moved_and_relative_original_path_still_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Projeto_FortSmart"
            create_project(root, "Projeto", "Fazenda", "2026/27", "EPSG:31981")
            source = write_projected_geojson(Path(tmp) / "talhao.geojson")
            ImportService().import_field_boundary(root, source)

            moved = Path(tmp) / "Projeto_Movido"
            root.rename(moved)
            conn = sqlite3.connect(moved / "01_BANCO" / "fortsmart.gpkg")
            try:
                rel = conn.execute("SELECT stored_relative_path FROM fs_source_files").fetchone()[0]
                self.assertTrue((moved / rel).exists())
            finally:
                conn.close()

    def test_import_respects_requested_target_layer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Projeto_FortSmart"
            create_project(root, "Projeto", "Fazenda", "2026/27", "EPSG:31981")
            source = write_projected_geojson(Path(tmp) / "obstaculo.geojson")

            result = ImportService().import_field_boundary(
                root,
                source,
                target_layer="obstacles",
                data_type="obstáculo",
            )

            self.assertEqual(result.output_layer, "obstacles")
            conn = sqlite3.connect(root / "01_BANCO" / "fortsmart.gpkg")
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM obstacles").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM field_boundaries").fetchone()[0], 0)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
