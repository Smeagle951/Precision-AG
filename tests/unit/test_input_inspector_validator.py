import json
import sqlite3
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from plugin.fortsmart_precision.io.input_inspector import InputInspector
from plugin.fortsmart_precision.models.input_report import INVALID, VALID_WITH_WARNINGS
from plugin.fortsmart_precision.validators.input_validator import InputValidator


def write_minimal_shapefile(base, with_prj=True, with_shx=True, with_empty_geometry=False):
    shp = base.with_suffix(".shp")
    shx = base.with_suffix(".shx")
    dbf = base.with_suffix(".dbf")
    header = bytearray(100)
    struct.pack_into(">i", header, 0, 9994)
    struct.pack_into("<i", header, 28, 1000)
    struct.pack_into("<i", header, 32, 5)
    struct.pack_into("<4d", header, 36, -56.1, -15.7, -56.0, -15.6)
    shp.write_bytes(header)
    if with_shx:
        shx.write_bytes(header + b"\x00" * 8)
    # DBF header with two fields.
    dbf_header = bytearray(32 + 32 * 2 + 1)
    dbf_header[0] = 3
    struct.pack_into("<I", dbf_header, 4, 1)
    struct.pack_into("<H", dbf_header, 8, len(dbf_header))
    dbf_header[32:43] = b"NOME\x00\x00\x00\x00\x00\x00\x00"
    dbf_header[43] = ord("C")
    dbf_header[64:75] = b"AREA_HA\x00\x00\x00\x00"
    dbf_header[75] = ord("N")
    dbf_header[-1] = 0x0D
    dbf.write_bytes(dbf_header)
    if with_prj:
        base.with_suffix(".prj").write_text('GEOGCS["SIRGAS 2000",AUTHORITY["EPSG","4674"]]', encoding="utf-8")
    base.with_suffix(".cpg").write_text("UTF-8", encoding="utf-8")
    return shp


def write_gpkg_with_layers(path):
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE gpkg_contents (
                table_name TEXT PRIMARY KEY,
                data_type TEXT NOT NULL,
                identifier TEXT,
                description TEXT,
                last_change TEXT,
                min_x DOUBLE,
                min_y DOUBLE,
                max_x DOUBLE,
                max_y DOUBLE,
                srs_id INTEGER
            );
            CREATE TABLE gpkg_geometry_columns (
                table_name TEXT,
                column_name TEXT,
                geometry_type_name TEXT,
                srs_id INTEGER,
                z INTEGER,
                m INTEGER
            );
            CREATE TABLE layer_a (id INTEGER PRIMARY KEY, geom BLOB);
            CREATE TABLE layer_b (id INTEGER PRIMARY KEY, geom BLOB);
            CREATE TABLE gpkg_spatial_ref_sys (srs_id INTEGER PRIMARY KEY);
            INSERT INTO gpkg_contents(table_name, data_type, identifier, srs_id) VALUES
                ('layer_a', 'features', 'layer_a', 31981),
                ('layer_b', 'features', 'layer_b', 31981),
                ('gpkg_contents', 'attributes', 'gpkg_contents', NULL);
            INSERT INTO gpkg_geometry_columns(table_name, column_name, geometry_type_name, srs_id, z, m) VALUES
                ('layer_a', 'geom', 'POLYGON', 31981, 0, 0),
                ('layer_b', 'geom', 'MULTIPOLYGON', 31981, 0, 0);
            INSERT INTO layer_a(id, geom) VALUES (1, x'00');
            """
        )
        conn.commit()
    finally:
        conn.close()


class InputInspectorValidatorTest(unittest.TestCase):
    def test_shapefile_complete_with_geographic_crs_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            shp = write_minimal_shapefile(Path(tmp) / "talhao")
            inspection = InputInspector().inspect(shp)
            validation = InputValidator().validate(inspection)

            self.assertEqual(inspection.format, "ESRI Shapefile")
            self.assertEqual(inspection.crs_authid, "EPSG:4674")
            self.assertEqual(inspection.geometry_type, "Polygon")
            self.assertEqual(inspection.feature_count, 1)
            self.assertEqual(validation.status, VALID_WITH_WARNINGS)
            self.assertTrue(any(msg.code == "CRS_GEOGRAPHIC" for msg in validation.messages))

    def test_shapefile_without_prj_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            shp = write_minimal_shapefile(Path(tmp) / "talhao", with_prj=False)
            validation = InputValidator().validate(InputInspector().inspect(shp))

            self.assertEqual(validation.status, INVALID)
            self.assertTrue(any(msg.code == "SHP_PRJ_MISSING" for msg in validation.messages))

    def test_shapefile_without_shx_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            shp = write_minimal_shapefile(Path(tmp) / "talhao", with_shx=False)
            validation = InputValidator().validate(InputInspector().inspect(shp))

            self.assertEqual(validation.status, INVALID)
            self.assertTrue(any(msg.code == "SHP_COMPONENT_MISSING" for msg in validation.messages))

    def test_geojson_with_empty_geometry_reports_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            geojson = Path(tmp) / "talhao.geojson"
            geojson.write_text(
                json.dumps(
                    {
                        "type": "FeatureCollection",
                        "crs": {"type": "name", "properties": {"name": "EPSG:31981"}},
                        "features": [
                            {"type": "Feature", "properties": {"name": "ok"}, "geometry": {"type": "Polygon", "coordinates": [[[-1, -1], [1, -1], [1, 1], [-1, -1]]]}},
                            {"type": "Feature", "properties": {"name": "empty"}, "geometry": None},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            validation = InputValidator().validate(InputInspector().inspect(geojson))
            self.assertEqual(validation.status, VALID_WITH_WARNINGS)
            self.assertTrue(any(msg.code == "EMPTY_GEOMETRY" for msg in validation.messages))

    def test_gpkg_with_multiple_layers_warns_and_ignores_internal_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            gpkg = Path(tmp) / "multi.gpkg"
            write_gpkg_with_layers(gpkg)
            inspection = InputInspector().inspect(gpkg)
            validation = InputValidator().validate(inspection)

            self.assertEqual(len(inspection.layers), 2)
            self.assertEqual(validation.status, VALID_WITH_WARNINGS)
            self.assertTrue(any(msg.code == "GPKG_MULTIPLE_LAYERS" for msg in validation.messages))

    def test_kmz_with_multiple_kml_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            kmz = Path(tmp) / "multi.kmz"
            with zipfile.ZipFile(kmz, "w") as zf:
                zf.writestr("a.kml", "<kml/>")
                zf.writestr("b.kml", "<kml/>")
                zf.writestr("files/icon.png", b"png")
            validation = InputValidator().validate(InputInspector().inspect(kmz))

            self.assertEqual(validation.status, VALID_WITH_WARNINGS)
            self.assertTrue(any(msg.code == "KMZ_MULTIPLE_KML" for msg in validation.messages))

    def test_csv_requires_explicit_xy_crs_and_delimiter(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "pontos.csv"
            csv_path.write_text("lon;lat\n-56.0;-15.0\n", encoding="utf-8")
            validation = InputValidator().validate(InputInspector().inspect(csv_path), csv_options={})

            self.assertEqual(validation.status, INVALID)
            self.assertTrue(any(msg.code == "CSV_XY_REQUIRED" for msg in validation.messages))
            self.assertTrue(any(msg.code == "CSV_CRS_REQUIRED" for msg in validation.messages))


if __name__ == "__main__":
    unittest.main()
