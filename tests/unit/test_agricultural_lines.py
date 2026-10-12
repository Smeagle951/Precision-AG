import unittest

from plugin.fortsmart_precision.core.crs import CrsValidationError, require_projected_metric
from plugin.fortsmart_precision.core.line_geometry import shrink_axis_aligned_polygon
from plugin.fortsmart_precision.domain.agricultural_lines import (
    AgriculturalLineParams,
    MaleFemaleSetup,
    PlantingSetup,
    SprayingSetup,
    generate_parallel_agricultural_lines,
    spacing_for_operation,
)


def rectangle(width=100.0, height=60.0, x=0.0, y=0.0):
    outer = [
        (x, y),
        (x + width, y),
        (x + width, y + height),
        (x, y + height),
        (x, y),
    ]
    return [(outer, [])]


class AgriculturalLinesTest(unittest.TestCase):
    def test_rectangular_field_spacing_18_with_extension_20(self):
        lines = generate_parallel_agricultural_lines(
            AgriculturalLineParams(
                polygons=rectangle(100, 60),
                ab_start=(0, 0),
                ab_end=(100, 0),
                spacing_m=18,
                extension_m=20,
            )
        )

        self.assertEqual(len(lines), 4)
        self.assertEqual([line.line_no for line in lines], [1, 2, 3, 4])
        self.assertTrue(all(abs(line.length_m - 140.0) < 1e-6 for line in lines))
        self.assertTrue(all(abs(line.azimuth_deg - 90.0) < 1e-6 for line in lines))

    def test_spacing_6_7_18_20_36_generate_ordered_lines(self):
        expected_minimums = {6: 10, 7: 9, 18: 4, 20: 4, 36: 2}
        for spacing, minimum in expected_minimums.items():
            with self.subTest(spacing=spacing):
                lines = generate_parallel_agricultural_lines(
                    AgriculturalLineParams(
                        polygons=rectangle(100, 60),
                        ab_start=(0, 0),
                        ab_end=(100, 0),
                        spacing_m=spacing,
                    )
                )
                self.assertGreaterEqual(len(lines), minimum)
                self.assertEqual([line.line_no for line in lines], list(range(1, len(lines) + 1)))

    def test_irregular_field_generates_lines(self):
        polygon = [
            (
                [(0, 0), (120, 0), (80, 50), (110, 90), (0, 70), (0, 0)],
                [],
            )
        ]
        lines = generate_parallel_agricultural_lines(
            AgriculturalLineParams(
                polygons=polygon,
                ab_start=(0, 0),
                ab_end=(100, 10),
                spacing_m=20,
                extension_m=20,
            )
        )
        self.assertGreaterEqual(len(lines), 4)

    def test_multipart_field_preserves_parts_as_segments(self):
        multi = rectangle(50, 50, 0, 0) + rectangle(50, 50, 100, 0)
        lines = generate_parallel_agricultural_lines(
            AgriculturalLineParams(
                polygons=multi,
                ab_start=(0, 0),
                ab_end=(150, 0),
                spacing_m=25,
            )
        )
        self.assertGreaterEqual(len(lines), 4)
        self.assertTrue(any(line.segment.start[0] < 75 for line in lines))
        self.assertTrue(any(line.segment.start[0] > 75 for line in lines))

    def test_field_with_hole_splits_or_removes_segments(self):
        outer = [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]
        hole = [(40, 40), (60, 40), (60, 60), (40, 60), (40, 40)]
        lines = generate_parallel_agricultural_lines(
            AgriculturalLineParams(
                polygons=[(outer, [hole])],
                ab_start=(0, 0),
                ab_end=(100, 0),
                spacing_m=20,
                extension_m=0,
            )
        )
        self.assertGreater(len(lines), 5)
        self.assertTrue(any(line.length_m < 100 for line in lines))

    def test_short_ab_line_is_rejected(self):
        with self.assertRaises(ValueError):
            generate_parallel_agricultural_lines(
                AgriculturalLineParams(
                    polygons=rectangle(),
                    ab_start=(0, 0),
                    ab_end=(0, 0),
                    spacing_m=18,
                )
            )

    def test_ab_line_outside_field_still_covers_polygon(self):
        lines = generate_parallel_agricultural_lines(
            AgriculturalLineParams(
                polygons=rectangle(100, 60),
                ab_start=(0, 200),
                ab_end=(100, 200),
                spacing_m=20,
            )
        )
        self.assertGreaterEqual(len(lines), 3)

    def test_headland_that_eliminates_field_returns_none_in_pure_helper(self):
        polygon = rectangle(20, 20)[0]
        self.assertIsNone(shrink_axis_aligned_polygon(polygon, 11))

    def test_spraying_72_nozzles_at_half_meter(self):
        setup = SprayingSetup(boom_width_m=36.0, nozzle_count=72, nozzle_spacing_m=0.5)
        self.assertEqual(setup.calculated_width_m, 36.0)
        self.assertEqual(setup.width_divergence_m, 0.0)
        self.assertEqual(spacing_for_operation("spraying", 18, spraying=setup), 36.0)

    def test_planting_12_rows_uses_operational_width(self):
        setup = PlantingSetup(row_count=12, row_spacing_m=0.5)
        self.assertEqual(setup.working_width_m, 6.0)
        self.assertEqual(spacing_for_operation("planting", 18, planting=setup), 6.0)

    def test_male_female_pattern_classifies_lines(self):
        setup = MaleFemaleSetup(
            planter_total_rows=7,
            female_rows=6,
            male_rows=1,
            female_spacing_m=0.5,
            male_spacing_m=0.5,
            pattern=tuple("FFFFFFM"),
        )
        lines = generate_parallel_agricultural_lines(
            AgriculturalLineParams(
                polygons=rectangle(100, 60),
                ab_start=(0, 0),
                ab_end=(100, 0),
                spacing_m=10,
                operation="male_female",
                male_female=setup,
            )
        )
        self.assertEqual([line.sex for line in lines[:7]], list("FFFFFFM"))

    def test_two_configured_male_positions(self):
        setup = MaleFemaleSetup(
            planter_total_rows=7,
            female_rows=5,
            male_rows=2,
            female_spacing_m=0.5,
            male_spacing_m=0.5,
            pattern=tuple("MFFFFFM"),
        )
        lines = generate_parallel_agricultural_lines(
            AgriculturalLineParams(
                polygons=rectangle(100, 60),
                ab_start=(0, 0),
                ab_end=(100, 0),
                spacing_m=10,
                operation="male_female",
                male_female=setup,
            )
        )
        self.assertEqual(lines[0].sex, "M")
        self.assertEqual(lines[6].sex, "M")

    def test_geographic_crs_is_blocked_for_agricultural_lines(self):
        with self.assertRaises(CrsValidationError):
            require_projected_metric("EPSG:4674", "geracao de linhas agricolas")


if __name__ == "__main__":
    unittest.main()
