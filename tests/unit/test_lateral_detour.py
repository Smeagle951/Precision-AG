"""Estrategia LATERAL_DETOUR isolada + regressao do corte existente (STOP_CUT_RESUME)."""

import ast
import math
import unittest
from pathlib import Path
from unittest import mock

from shapely.geometry import LineString, Point, box

from plugin.fortsmart_precision.core import obstacle_strategy_controller as controller
from plugin.fortsmart_precision.core.lateral_detour import (
    DETOURED,
    NO_CONFLICT,
    WORK_OFF,
    WORK_ON,
    DetourValidation,
    calculate_machine_envelope,
    create_lateral_detour,
    generate_planter_rows,
    generate_row_offsets,
    minimum_radius,
    required_turn_radius,
)
from plugin.fortsmart_precision.core.line_geometry import circle_ring_polygon
from plugin.fortsmart_precision.core.planting_line_cut_engine import cut_polyline_by_zones
from plugin.fortsmart_precision.domain import obstacle_strategy as strategy_module
from plugin.fortsmart_precision.domain.obstacle_strategy import (
    DETOUR_NOT_FEASIBLE,
    ContourStrategy,
    DetourSide,
    ObstacleConfig,
    ObstacleConfigError,
    ObstacleHandlingStrategy,
    obstacle_config_from_dict,
    resolve_strategy,
)

PLUGIN = Path(__file__).resolve().parents[2] / "plugin" / "fortsmart_precision"
STRAIGHT = LineString([(0.0, 0.0), (200.0, 0.0)])


def lateral(rows=27, spacing=0.45, **kwargs) -> ObstacleConfig:
    kwargs.setdefault("obstacle_radius", 0.5)
    return ObstacleConfig(
        strategy=ObstacleHandlingStrategy.LATERAL_DETOUR,
        row_count=rows,
        row_spacing=spacing,
        **kwargs,
    )


class StrategyConfigTest(unittest.TestCase):
    def test_default_strategy_is_stop_cut_resume(self):
        self.assertEqual(ObstacleConfig().strategy, ObstacleHandlingStrategy.STOP_CUT_RESUME)

    def test_old_project_without_strategy_stays_stop_cut_resume(self):
        self.assertEqual(obstacle_config_from_dict({}).strategy, ObstacleHandlingStrategy.STOP_CUT_RESUME)
        self.assertEqual(obstacle_config_from_dict(None).strategy, ObstacleHandlingStrategy.STOP_CUT_RESUME)
        self.assertEqual(resolve_strategy(""), ObstacleHandlingStrategy.STOP_CUT_RESUME)

    def test_saved_lateral_config_round_trip(self):
        config = lateral(detour_side=DetourSide.RIGHT, planting_during_detour=False)
        loaded = obstacle_config_from_dict(config.to_dict())
        self.assertEqual(loaded, config)

    def test_unknown_strategy_is_rejected(self):
        with self.assertRaises(ObstacleConfigError):
            resolve_strategy("teleport")

    def test_feature_flag_off_keeps_existing_strategy(self):
        with mock.patch.object(strategy_module, "ENABLE_LATERAL_DETOUR", False):
            self.assertEqual(resolve_strategy("lateral_detour"), ObstacleHandlingStrategy.STOP_CUT_RESUME)

    def test_lateral_config_requires_machine_parameters(self):
        with self.assertRaises(ObstacleConfigError):
            lateral(rows=0).validate()
        with self.assertRaises(ObstacleConfigError):
            lateral(spacing=0.0).validate()
        with self.assertRaises(ObstacleConfigError):
            lateral(minimum_turn_radius=0.0).validate()

    def test_machine_width_from_rows(self):
        self.assertAlmostEqual(lateral(27, 0.45).machine_width, 12.15)
        self.assertAlmostEqual(lateral(40, 0.50).machine_width, 20.0)
        self.assertAlmostEqual(lateral(24, 0.50).machine_width, 12.0)
        envelope = calculate_machine_envelope(40, 0.5, 0.5)
        self.assertAlmostEqual(envelope.clearance, 10.5)


class StopCutResumeRegressionTest(unittest.TestCase):
    def test_controller_matches_existing_cut_exactly(self):
        config = ObstacleConfig(row_count=27, row_spacing=0.45, safety_margin=1.0, obstacle_radius=0.5)
        result = controller.apply_obstacle_strategy(STRAIGHT, [("P1", Point(100, 0))], config, source_id="7")
        self.assertEqual(result.strategy_used, ObstacleHandlingStrategy.STOP_CUT_RESUME)
        self.assertFalse(result.fallback_used)
        self.assertIsNone(result.detour)
        segments = result.existing_result
        self.assertEqual(len(segments), 2)
        self.assertTrue(all(segment.obstacle_cut for segment in segments))
        radius = 12.15 / 2 + 0.5 + 1.0
        self.assertAlmostEqual(segments[0].path_points[-1][0], 100 - radius, delta=0.05)
        self.assertAlmostEqual(segments[1].path_points[0][0], 100 + radius, delta=0.05)

    def test_existing_function_result_unchanged_without_obstacles(self):
        points = tuple(STRAIGHT.coords)
        direct = cut_polyline_by_zones(points, [], source_id="1")
        via_controller = controller.apply_obstacle_strategy(STRAIGHT, [], ObstacleConfig()).existing_result
        self.assertEqual(direct, via_controller)

    def test_existing_function_same_zones_same_result(self):
        config = ObstacleConfig(row_count=24, row_spacing=0.5, safety_margin=0.5)
        zones = [circle_ring_polygon((100.0, 0.0), 6.5, segments=96)]
        direct = cut_polyline_by_zones(tuple(STRAIGHT.coords), zones, source_id="1", obstacle_count=1)
        via = controller.call_existing_strategy(STRAIGHT, [("P", Point(100, 0))], config)
        self.assertEqual(len(direct), len(via))
        for a, b in zip(direct, via):
            self.assertEqual(a.segment_id, b.segment_id)
            self.assertEqual(a.obstacle_cut, b.obstacle_cut)
            self.assertAlmostEqual(a.path_points[0][0], b.path_points[0][0], delta=0.02)
            self.assertAlmostEqual(a.path_points[-1][0], b.path_points[-1][0], delta=0.02)

    def test_injected_existing_strategy_is_called_untouched(self):
        calls = []

        def existing(path, obstacles, config):
            calls.append((path, obstacles, config))
            return "resultado-original"

        config = ObstacleConfig()
        result = controller.apply_obstacle_strategy(STRAIGHT, [("P", Point(1, 1))], config, existing_strategy=existing)
        self.assertEqual(result.existing_result, "resultado-original")
        self.assertEqual(len(calls), 1)


class LateralDetourGeometryTest(unittest.TestCase):
    def assert_unchanged_outside(self, result, original):
        final = result.final_path
        for section in result.sections:
            before = original.interpolate(max(0.0, section.s_start - 1.0))
            after = original.interpolate(min(original.length, section.s_end + 1.0))
            self.assertLess(final.distance(before), 1e-6)
            self.assertLess(final.distance(after), 1e-6)

    def test_no_obstacle_returns_identical_path(self):
        result = create_lateral_detour(STRAIGHT, [], lateral())
        self.assertEqual(result.status, NO_CONFLICT)
        self.assertTrue(result.final_path.equals(STRAIGHT))
        self.assertEqual(list(result.final_path.coords), list(STRAIGHT.coords))

    def test_lateral_obstacle_outside_envelope_is_not_detoured(self):
        result = create_lateral_detour(STRAIGHT, [("L", Point(100, 9.0))], lateral())
        self.assertEqual(result.status, NO_CONFLICT)
        self.assertEqual(list(result.final_path.coords), list(STRAIGHT.coords))

    def test_central_obstacle_is_detoured_safely(self):
        config = lateral()
        result = create_lateral_detour(STRAIGHT, [("P1", Point(100, 0))], config)
        self.assertEqual(result.status, DETOURED, result.reason)
        validation = result.validation
        self.assertIsInstance(validation, DetourValidation)
        self.assertTrue(validation.valid, validation.errors)
        self.assertGreaterEqual(validation.minimum_clearance, config.safety_margin - 0.01)
        self.assertGreaterEqual(validation.minimum_radius, required_turn_radius(config) * 0.98)
        self.assertTrue(validation.inside_allowed_area)
        self.assertFalse(validation.self_intersection)
        self.assertTrue(result.final_path.is_simple)
        self.assertEqual(result.final_path.coords[0], STRAIGHT.coords[0])
        self.assertEqual(result.final_path.coords[-1], STRAIGHT.coords[-1])
        self.assert_unchanged_outside(result, STRAIGHT)

    def test_detour_uses_only_needed_arc_and_no_corners(self):
        result = create_lateral_detour(STRAIGHT, [("P1", Point(100, 0))], lateral())
        section = result.sections[0]
        perimeter = 2 * math.pi * result.contour_radius
        self.assertLess(LineString(section.contour).length, perimeter / 2)
        self.assertAlmostEqual(section.s_start, section.s_entry - 12.0, delta=1e-6)
        self.assertAlmostEqual(section.s_end, section.s_exit + 12.0, delta=1e-6)
        self.assertGreaterEqual(minimum_radius(section.coords), result.required_radius * 0.98)

    def test_fixed_side_is_respected(self):
        left = create_lateral_detour(STRAIGHT, [("P", Point(100, 0))], lateral(detour_side=DetourSide.LEFT))
        right = create_lateral_detour(STRAIGHT, [("P", Point(100, 0))], lateral(detour_side=DetourSide.RIGHT))
        self.assertGreater(max(y for _x, y in left.final_path.coords), 5.0)
        self.assertLess(min(y for _x, y in right.final_path.coords), -5.0)

    def test_boundary_rejects_one_side_and_auto_uses_other(self):
        allowed = box(-1.0, -60.0, 201.0, 5.0)
        result = create_lateral_detour(STRAIGHT, [("P", Point(100, 0))], lateral(), allowed_area=allowed)
        self.assertEqual(result.status, DETOURED, result.reason)
        self.assertEqual(result.sections[0].side, DetourSide.RIGHT)
        self.assertTrue(result.validation.inside_allowed_area)

    def test_both_sides_blocked_is_not_feasible(self):
        allowed = box(-1.0, -5.0, 201.0, 5.0)
        result = create_lateral_detour(STRAIGHT, [("P", Point(100, 0))], lateral(), allowed_area=allowed)
        self.assertEqual(result.status, DETOUR_NOT_FEASIBLE)
        self.assertIsNone(result.final_path)
        self.assertTrue(result.log)
        self.assertEqual(result.log[-1]["status"], DETOUR_NOT_FEASIBLE)

    def test_two_obstacles_processed_in_path_order(self):
        path = LineString([(0, 0), (220, 0)])
        result = create_lateral_detour(path, [("B", Point(150, 0)), ("A", Point(60, 0))], lateral())
        self.assertEqual(result.status, DETOURED, result.reason)
        self.assertEqual([section.obstacle_ids for section in result.sections], [("A",), ("B",)])
        self.assertLess(result.sections[0].s_end, result.sections[1].s_start)
        self.assert_unchanged_outside(result, path)

    def test_overlapping_obstacles_become_single_detour(self):
        result = create_lateral_detour(STRAIGHT, [("A", Point(100, 0)), ("B", Point(105, 2))], lateral())
        self.assertEqual(result.status, DETOURED, result.reason)
        self.assertEqual(len(result.sections), 1)
        self.assertEqual(set(result.sections[0].obstacle_ids), {"A", "B"})
        self.assertTrue(result.validation.valid)

    def test_close_detours_are_merged(self):
        result = create_lateral_detour(STRAIGHT, [("A", Point(100, 0)), ("B", Point(125, 0))], lateral())
        self.assertEqual(result.status, DETOURED, result.reason)
        self.assertEqual(len(result.sections), 1)
        self.assertEqual(set(result.sections[0].obstacle_ids), {"A", "B"})

    def test_polygon_obstacle(self):
        result = create_lateral_detour(STRAIGHT, [("Q", box(95, -3, 105, 3))], lateral(obstacle_radius=0.0))
        self.assertEqual(result.status, DETOURED, result.reason)
        self.assertTrue(result.validation.valid, result.validation.errors)

    def test_curved_master_path(self):
        arc = LineString([(100 * math.cos(math.radians(a)), 100 * math.sin(math.radians(a))) for a in range(0, 91)])
        center = (100 * math.cos(math.pi / 4), 100 * math.sin(math.pi / 4))
        result = create_lateral_detour(arc, [("C", Point(center))], lateral())
        self.assertEqual(result.status, DETOURED, result.reason)
        self.assertTrue(result.validation.valid, result.validation.errors)
        rows = generate_planter_rows(result.final_path, 27, 0.45)
        self.assertTrue(rows.spacing_ok, rows.errors)

    def test_tight_contour_keeps_minimum_radius(self):
        config = lateral(contour_strategy=ContourStrategy.CONVEX_TIGHT, minimum_turn_radius=6.0)
        result = create_lateral_detour(STRAIGHT, [("P", Point(100, 0))], config)
        if result.status == DETOURED:
            self.assertGreaterEqual(result.validation.minimum_radius, result.required_radius * 0.98)
        else:
            self.assertEqual(result.status, DETOUR_NOT_FEASIBLE)

    def test_work_off_during_detour(self):
        result = create_lateral_detour(STRAIGHT, [("P", Point(100, 0))], lateral(planting_during_detour=False))
        states = [state for state, _line in result.work_segments]
        self.assertEqual(states, [WORK_ON, WORK_OFF, WORK_ON])
        events = result.events()
        self.assertEqual([event["event"] for event in events], [WORK_OFF, WORK_ON])

    def test_work_on_during_detour_by_default(self):
        result = create_lateral_detour(STRAIGHT, [("P", Point(100, 0))], lateral())
        self.assertEqual([state for state, _line in result.work_segments], [WORK_ON])
        self.assertEqual(result.events(), [])


class PlanterRowsTest(unittest.TestCase):
    def test_27_rows_045(self):
        offsets = generate_row_offsets(27, 0.45)
        self.assertEqual(len(offsets), 27)
        self.assertIn(0.0, offsets)
        self.assertAlmostEqual(offsets[-1] - offsets[0], 26 * 0.45)
        self.assertAlmostEqual(lateral(27, 0.45).machine_width, 12.15)

    def test_40_rows_050_has_no_zero_offset(self):
        offsets = generate_row_offsets(40, 0.50)
        self.assertEqual(len(offsets), 40)
        self.assertNotIn(0.0, offsets)
        self.assertIn(-0.25, offsets)
        self.assertIn(0.25, offsets)
        self.assertAlmostEqual(offsets[0], -9.75)
        self.assertAlmostEqual(offsets[-1], 9.75)

    def test_24_rows_050(self):
        offsets = generate_row_offsets(24, 0.50)
        self.assertEqual(len(offsets), 24)
        self.assertNotIn(0.0, offsets)
        self.assertAlmostEqual(lateral(24, 0.50).machine_width, 12.0)

    def test_rows_follow_detour_with_valid_spacing(self):
        for rows, spacing in ((27, 0.45), (40, 0.50), (24, 0.50)):
            with self.subTest(rows=rows, spacing=spacing):
                config = lateral(rows, spacing)
                result = create_lateral_detour(STRAIGHT, [("P", Point(100, 0))], config)
                self.assertEqual(result.status, DETOURED, result.reason)
                generated = generate_planter_rows(result.final_path, rows, spacing)
                self.assertEqual(len(generated.rows), rows)
                self.assertTrue(generated.spacing_ok, generated.errors)
                for row in generated.rows:
                    self.assertTrue(row.geometry.is_simple)
                    self.assertEqual(row.geometry.coords[0][0], 0.0)

    def test_positive_offset_is_right_side(self):
        generated = generate_planter_rows(STRAIGHT, 2, 1.0)
        left, right = generated.rows
        self.assertAlmostEqual(left.geometry.coords[0][1], 0.5)
        self.assertAlmostEqual(right.geometry.coords[0][1], -0.5)

    def test_rows_clipped_last(self):
        generated = generate_planter_rows(STRAIGHT, 3, 0.5, allowed_area=box(10, -5, 50, 5))
        self.assertTrue(generated.spacing_ok)
        for row in generated.rows:
            self.assertAlmostEqual(row.geometry.length, 200.0, places=6)
            self.assertAlmostEqual(sum(part.length for part in row.clipped_parts), 40.0, places=6)


class FallbackTest(unittest.TestCase):
    def test_infeasible_detour_falls_back_to_cut_with_log(self):
        config = lateral()
        with self.assertLogs("fortsmart_precision.obstacles", level="WARNING"):
            result = controller.apply_obstacle_strategy(STRAIGHT, [("P", Point(3, 0))], config)
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.status, controller.FALLBACK_TO_CUT)
        self.assertEqual(result.strategy_requested, ObstacleHandlingStrategy.LATERAL_DETOUR)
        self.assertEqual(result.strategy_used, ObstacleHandlingStrategy.STOP_CUT_RESUME)
        self.assertTrue(result.fallback_reason)
        self.assertTrue(all(entry["fallback_used"] for entry in result.log))
        self.assertTrue(result.existing_result)

    def test_fallback_disabled_reports_not_feasible(self):
        config = lateral(allow_fallback=False)
        result = controller.apply_obstacle_strategy(STRAIGHT, [("P", Point(3, 0))], config)
        self.assertFalse(result.fallback_used)
        self.assertEqual(result.status, DETOUR_NOT_FEASIBLE)
        self.assertIsNone(result.existing_result)

    def test_successful_detour_log_fields(self):
        result = controller.apply_obstacle_strategy(STRAIGHT, [("P", Point(100, 0))], lateral())
        self.assertEqual(result.strategy_used, ObstacleHandlingStrategy.LATERAL_DETOUR)
        entry = result.log[0]
        for key in ("obstacle_id", "strategy", "machine_width", "safety_margin", "entry_point", "exit_point", "side", "minimum_radius", "status", "fallback_used"):
            self.assertIn(key, entry)
        self.assertEqual(entry["obstacle_id"], "P")
        self.assertIsNotNone(result.final_path)


class IsolationTest(unittest.TestCase):
    FORBIDDEN = ("parallel_pass_engine", "precision_lines_engine", "agricultural_lines_engine")

    def test_lateral_gui_modules_have_no_undefined_names(self):
        from tests.unit.test_cut_gui_undefined_names import undefined_names_in_functions

        for module in ("gui/lateral_detour_widget.py", "gui/lateral_detour_preview.py"):
            source = (PLUGIN / module).read_text(encoding="utf-8")
            with self.subTest(module=module):
                self.assertEqual(undefined_names_in_functions(source), [])

    def test_cut_dialog_defaults_to_existing_behavior(self):
        source = (PLUGIN / "gui" / "lateral_detour_widget.py").read_text(encoding="utf-8")
        self.assertIn("self.cut_radio.setChecked(True)", source)
        self.assertNotIn("self.detour_radio.setChecked(True)", source)
        dialog = (PLUGIN / "gui" / "planting_line_cut_dialog.py").read_text(encoding="utf-8")
        self.assertLess(dialog.index("if self._lateral_mode():\n            self._preview_lateral_detour()"),
                        dialog.index("if self.work_geometry_box.is_longitudinal():\n            self._preview_longitudinal()"))

    def test_new_modules_do_not_import_generators_or_qgis(self):
        files = list((PLUGIN / "core" / "lateral_detour").glob("*.py"))
        files += [PLUGIN / "core" / "obstacle_strategy_controller.py", PLUGIN / "domain" / "obstacle_strategy.py"]
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    self.assertFalse(module.startswith("qgis"), path.name)
                    for name in self.FORBIDDEN:
                        self.assertNotIn(name, module, path.name)


if __name__ == "__main__":
    unittest.main()
