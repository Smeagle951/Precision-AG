# -*- coding: utf-8 -*-
"""Etapa 0F: regras do Inspetor DEM (sem QGIS)."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core import dem_inspector as dem
from plugin.fortsmart_precision.core.dem_inspector import (
    CoverageResult,
    DemMetadata,
    classify_coverage,
    classify_raster,
    resolve_vertical_unit,
)
from plugin.fortsmart_precision.core.project_context import CrsSummary

UTM = CrsSummary("EPSG:31981", True, False, True, True)
WGS84 = CrsSummary("EPSG:4326", True, True, False, False)


def _meta(**changes):
    values = dict(
        layer_id="R1", name="dem", source="dem.tif", provider="gdal", crs=UTM, horizontal_unit=dem.UNIT_METERS,
        res_x=10.0, res_y=10.0, extent=(0, 0, 100, 100), width=10, height=10, band_count=1,
        data_type="Float32", nodata=("-9999",), vertical=resolve_vertical_unit(band_unit="m"),
        suitability=classify_raster(band_count=1, data_type="Float32", provider="gdal"),
    )
    values.update(changes)
    return DemMetadata(**values)


def _codes(items):
    return {item.code for item in items}


class SuitabilityTest(unittest.TestCase):
    def test_single_numeric_band_is_only_a_candidate(self):
        result = classify_raster(band_count=1, data_type="Float32", provider="gdal")
        self.assertTrue(result.candidate)
        self.assertIn("não é comprovado", result.text)
        self.assertNotIn("confirmado", result.text.replace("não é comprovado", ""))

    def test_images_and_services_are_explained(self):
        rgb = classify_raster(band_count=3, data_type="Byte", provider="gdal")
        self.assertFalse(rgb.candidate)
        self.assertEqual(len(rgb.reasons), 2)
        self.assertFalse(classify_raster(band_count=1, data_type="Byte", provider="gdal").candidate)
        self.assertFalse(classify_raster(band_count=1, data_type="CFloat32", provider="gdal").candidate)
        service = classify_raster(band_count=1, data_type="Float32", provider="wms")
        self.assertFalse(service.candidate)
        self.assertIn("wms", service.text)


class VerticalUnitTest(unittest.TestCase):
    def test_unknown_is_never_assumed_as_meters(self):
        unit = resolve_vertical_unit()
        self.assertFalse(unit.confirmed)
        self.assertEqual(unit.text, "Unidade vertical não confirmada")
        self.assertFalse(resolve_vertical_unit(band_unit="").confirmed)
        self.assertFalse(resolve_vertical_unit(band_unit="deg").confirmed)

    def test_sources_and_precedence(self):
        self.assertEqual(resolve_vertical_unit(band_unit="metre").unit, dem.UNIT_METERS)
        self.assertEqual(resolve_vertical_unit(vertical_crs_unit="ft").source, dem.VERTICAL_CRS)
        declared = resolve_vertical_unit(declared="ft", band_unit="m")
        self.assertEqual((declared.unit, declared.source), (dem.UNIT_FEET, dem.VERTICAL_DECLARED))

    def test_conflicting_sources_stay_unconfirmed(self):
        unit = resolve_vertical_unit(band_unit="m", vertical_crs_unit="ft")
        self.assertFalse(unit.confirmed)
        self.assertEqual(len(unit.conflict), 2)


class CoverageTest(unittest.TestCase):
    def test_classification(self):
        self.assertEqual(classify_coverage(1.0, 0.0), dem.COVERAGE_COMPLETE)
        self.assertEqual(classify_coverage(0.0), dem.COVERAGE_NONE)
        self.assertEqual(classify_coverage(0.4, 0.0), dem.COVERAGE_PARTIAL)
        self.assertEqual(classify_coverage(1.0, 0.25), dem.COVERAGE_PARTIAL)
        self.assertEqual(classify_coverage(1.0, 1.0), dem.COVERAGE_NONE)

    def test_diagnostics(self):
        partial = CoverageResult(dem.COVERAGE_PARTIAL, 1.0, 0.5, 0.1, 400, 50.0, (500.0, 510.0, 505.0))
        self.assertEqual(
            _codes(dem.coverage_diagnostics(partial)),
            {dem.COVERAGE_RESULT, dem.NODATA_IN_FIELD, dem.COARSE_RESOLUTION},
        )
        odd = CoverageResult(dem.COVERAGE_COMPLETE, 1.0, 1.0, 0.0, 4000, 4000.0, (0.0, 65000.0, 10.0))
        self.assertIn(dem.VALUES_OUT_OF_RANGE, _codes(dem.coverage_diagnostics(odd)))
        empty = CoverageResult(dem.COVERAGE_PARTIAL, 1.0, 1.0, 0.5, 100, 400.0, None)
        self.assertIn(dem.NO_VALID_VALUES, _codes(dem.coverage_diagnostics(empty)))

    def test_feet_widen_the_plausible_range(self):
        self.assertFalse(dem.values_plausible(100.0, 12000.0, unit=dem.UNIT_METERS))
        self.assertTrue(dem.values_plausible(100.0, 12000.0, unit=dem.UNIT_FEET))


class MetadataDiagnosticsTest(unittest.TestCase):
    def test_valid_dem_only_has_no_blocking_notes(self):
        self.assertEqual(_codes(dem.metadata_diagnostics(_meta())), set())

    def test_missing_crs_and_degrees(self):
        self.assertIn(dem.RASTER_WITHOUT_CRS, _codes(dem.metadata_diagnostics(_meta(crs=None, horizontal_unit=None))))
        geographic = _meta(crs=WGS84, horizontal_unit=dem.UNIT_DEGREES)
        codes = _codes(dem.metadata_diagnostics(geographic, field_crs_authid="EPSG:31981"))
        self.assertEqual(codes, {dem.HORIZONTAL_IN_DEGREES, dem.CRS_DIFFERS_FROM_FIELD})

    def test_units_nodata_and_suitability(self):
        meta = _meta(
            vertical=resolve_vertical_unit(), nodata=(),
            suitability=classify_raster(band_count=3, data_type="Byte", provider="gdal"),
        )
        self.assertEqual(
            _codes(dem.metadata_diagnostics(meta)),
            {dem.VERTICAL_UNIT_UNCONFIRMED, dem.NO_NODATA_VALUE, dem.NOT_ELEVATION_CANDIDATE},
        )

    def test_resolution_text(self):
        self.assertEqual(dem.resolution_text(_meta()), "10 × 10 metros")
        geographic = _meta(crs=WGS84, horizontal_unit=dem.UNIT_DEGREES, res_x=0.0001, res_y=0.0001)
        text = dem.resolution_text(geographic, latitude=-20.0)
        self.assertIn("aprox. 10.5 m × 11.1 m", text)


if __name__ == "__main__":
    unittest.main()
