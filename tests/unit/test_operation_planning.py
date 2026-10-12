import unittest

from plugin.fortsmart_precision.core.coverage_strip_engine import build_coverage_strips
from plugin.fortsmart_precision.core.crs import CrsValidationError, require_projected_metric
from plugin.fortsmart_precision.core.parallel_pass_engine import ParallelPassParams, generate_parallel_passes
from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
from plugin.fortsmart_precision.domain.operation_width import OperationWidth, half_width
from plugin.fortsmart_precision.domain.planting_configuration import PlantingConfiguration
from plugin.fortsmart_precision.domain.seed_corn_planning import (
    SeedCornParams,
    SeedCornPattern,
    generate_seed_corn_plan,
)
from plugin.fortsmart_precision.domain.spraying_configuration import SprayingConfiguration


def rectangle(width=100.0, height=60.0, x=0.0, y=0.0):
    outer = [
        (x, y),
        (x + width, y),
        (x + width, y + height),
        (x, y + height),
        (x, y),
    ]
    return [(outer, [])]


class OperationPlanningTest(unittest.TestCase):
    def test_planting_width_18_center_9(self):
        config = PlantingConfiguration(row_count=40, row_spacing_m=0.45)
        self.assertAlmostEqual(config.calculated_width_m, 18.0)
        self.assertAlmostEqual(config.half_width_m, 9.0)
        self.assertAlmostEqual(config.row_offset_from_center(20), -0.225)
        self.assertAlmostEqual(config.row_offset_from_center(21), 0.225)

    def test_headland_one_two_three_passes(self):
        layout = HeadlandLayout(pass_count=3, width_m=18.0, effective_spacing_m=18.0, mode="parallel_ab")
        self.assertEqual(layout.center_offsets_m(), [9.0, 27.0, 45.0])
        self.assertEqual(layout.reserved_width_m, 54.0)

    def test_planting_40_rows_045_and_36_rows_050(self):
        self.assertAlmostEqual(PlantingConfiguration(40, 0.45).calculated_width_m, 18.0)
        self.assertAlmostEqual(PlantingConfiguration(36, 0.50).calculated_width_m, 18.0)

    def test_meeting_between_passes_is_correct(self):
        status = PlantingConfiguration(40, 0.45).meeting_status()
        self.assertEqual(status["status"], "correct")
        self.assertAlmostEqual(status["meeting_spacing_m"], 0.45)

    def test_sprayer_36_center_18_and_overlap(self):
        config = SprayingConfiguration(
            boom_width_m=36.0,
            nozzle_count=72,
            nozzle_spacing_m=0.5,
            overlap_value=0.40,
            overlap_unit="m",
            overlap_basis="total",
        )
        self.assertAlmostEqual(config.half_boom_width_m, 18.0)
        self.assertAlmostEqual(config.width_by_nozzle_count_m, 36.0)
        self.assertAlmostEqual(config.effective_spacing_m, 35.60)

    def test_overlap_in_centimeters_and_percent(self):
        cm = SprayingConfiguration(36.0, 72, 0.5, overlap_value=40.0, overlap_unit="cm")
        pct = SprayingConfiguration(36.0, 72, 0.5, overlap_value=10.0, overlap_unit="percent")
        self.assertAlmostEqual(cm.overlap_total_m, 0.40)
        self.assertAlmostEqual(pct.overlap_total_m, 3.60)
        self.assertAlmostEqual(pct.effective_spacing_m, 32.40)

    def test_nozzle_width_methods_and_divergence(self):
        by_count = OperationWidth(36.0, method="count_spacing", count=108, spacing_m=0.3333333333).compare()
        by_interval = OperationWidth(36.0, method="interval_spacing", count=108, spacing_m=0.35).compare()
        incompatible = OperationWidth(36.0, method="count_spacing", count=108, spacing_m=0.5).compare()
        self.assertAlmostEqual(by_count.calculated_width_m, 36.0, places=4)
        self.assertAlmostEqual(by_interval.calculated_width_m, 37.45)
        self.assertEqual(incompatible.status, "review")

    def test_parallel_passes_and_coverage_strips(self):
        passes = generate_parallel_passes(
            ParallelPassParams(
                polygons=rectangle(100, 60),
                ab_start=(0, 0),
                ab_end=(100, 0),
                pass_spacing_m=18.0,
                operation_width_m=18.0,
                extension_m=20.0,
            )
        )
        self.assertGreaterEqual(len(passes), 4)
        self.assertTrue(all(pass_line.length_m >= 100 for pass_line in passes))
        strips = build_coverage_strips(passes, *half_width(18.0))
        self.assertEqual(len(strips), len(passes))
        self.assertEqual(len(strips[0].ring), 5)

    def test_irregular_field_and_hole_generate_passes(self):
        outer = [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]
        hole = [(40, 40), (60, 40), (60, 60), (40, 60), (40, 40)]
        irregular = [(outer, [hole])]
        passes = generate_parallel_passes(
            ParallelPassParams(irregular, (0, 0), (100, 10), 20, 20)
        )
        self.assertGreater(len(passes), 4)

    def test_seed_corn_pattern_49_rows_has_42_female_7_male(self):
        plan = generate_seed_corn_plan(
            SeedCornParams(
                polygons=rectangle(100, 24),
                ab_start=(0, 0),
                ab_end=(100, 0),
                planter=PlantingConfiguration(7, 0.5),
                pattern=SeedCornPattern(("F", "F", "F", "F", "F", "F", "M1")),
                ab_reference="first_physical_row",
                extension_m=0,
            )
        )
        rows = [row for row in plan.rows if 0 <= -row.offset_from_ab_m <= 24]
        self.assertEqual(len(rows), 49)
        self.assertEqual(len([row for row in rows if row.sex == "F"]), 42)
        self.assertEqual(len([row for row in rows if row.male_operation == "M1"]), 7)

    def test_seed_corn_12_row_planter_does_not_reset_pattern(self):
        pattern = SeedCornPattern(("F", "F", "F", "F", "F", "F", "M1"))
        self.assertEqual([pattern.role_for_global_no(i) for i in range(1, 15)], list("FFFFFF") + ["M1"] + list("FFFFFF") + ["M1"])
        self.assertEqual(pattern.role_for_global_no(13), "F")
        self.assertEqual(pattern.role_for_global_no(14), "M1")

    def test_seed_corn_14_row_planter_has_two_cycles_per_pass(self):
        pattern = SeedCornPattern(("F", "F", "F", "F", "F", "F", "M1"))
        roles = [pattern.role_for_global_no(i) for i in range(1, 15)]
        self.assertEqual(roles.count("M1"), 2)

    def test_seed_corn_initial_cycle_position_and_m2(self):
        pattern = SeedCornPattern(("F", "F", "F", "F", "F", "M1", "M2"), initial_cycle_position=7)
        self.assertEqual(pattern.role_for_global_no(1), "M2")
        self.assertEqual(pattern.role_for_global_no(7), "M1")

    def test_variable_spacing_matrix(self):
        pattern = SeedCornPattern(
            ("F", "F", "F", "F", "F", "F", "M1"),
            spacing_after_position_m=(0.5, 0.5, 0.5, 0.5, 0.5, 0.6, 0.6),
        )
        self.assertAlmostEqual(pattern.spacing_after_global_no(6, 0.5), 0.6)
        self.assertAlmostEqual(pattern.spacing_after_global_no(7, 0.5), 0.6)

    def test_geographic_crs_blocked(self):
        with self.assertRaises(CrsValidationError):
            require_projected_metric("EPSG:4326", "motor de operacao agricola")


if __name__ == "__main__":
    unittest.main()
