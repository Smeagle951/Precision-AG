# -*- coding: utf-8 -*-
"""Validador automatico da rota: detecta, classifica e localiza; nunca corrige."""

from __future__ import annotations

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

from shapely.geometry import LineString, Point, Polygon, box

from plugin.fortsmart_precision.core.route_simulation_engine import RouteSimulationEngine
from plugin.fortsmart_precision.core.simulation_route import RoutePassInput, build_ordered_route
from plugin.fortsmart_precision.domain.machine_profile import MachineProfile
from plugin.fortsmart_precision.validator.obstacle_validator import ObstacleInput
from plugin.fortsmart_precision.validator.route_validator_engine import RouteValidatorEngine
from plugin.fortsmart_precision.validator.validation_config import ValidationConfig
from plugin.fortsmart_precision.validator.warning_model import Severity, WarningStatus, WarningType


def straight(pass_id, sequence, y=0.0, x0=0.0, x1=100.0, route_type=None):
    return RoutePassInput(pass_id, (((x0, y), (x1, y)),), sequence, route_type=route_type)


def parallel(count, spacing=10.0, length=100.0):
    return [straight(f"P{i + 1:02d}", i + 1, y=i * spacing, x1=length) for i in range(count)]


def of_type(result, warning_type):
    return [w for w in result.warnings if w.warning_type is warning_type]


def arc(pass_id, radius=100.0, degrees=90.0, step_deg=1.0):
    count = int(degrees / step_deg)
    points = tuple(
        (radius * math.cos(math.radians(i * step_deg)), radius * math.sin(math.radians(i * step_deg)))
        for i in range(count + 1)
    )
    return RoutePassInput(pass_id, (points,), 1)


class CleanRouteTest(unittest.TestCase):
    def test_regular_parallel_route_has_no_warnings(self):
        result = RouteValidatorEngine().validate(
            parallel(5), allowed_area=box(-1, -5, 101, 45), expected_spacing_m=10.0
        )

        self.assertEqual(result.warnings, [])
        self.assertEqual(result.route_count, 5)


class BoundaryValidatorTest(unittest.TestCase):
    def test_41_route_90_percent_inside_flags_only_the_outside_10_percent(self):
        route = [straight("P01", 1, y=5.0, x0=0.0, x1=100.0)]
        area = box(-10, 0, 90, 10)
        config = ValidationConfig(allow_headland_overrun=False)

        result = RouteValidatorEngine(config).validate(route, allowed_area=area)

        warnings = of_type(result, WarningType.OUTSIDE_ALLOWED_AREA)
        self.assertEqual(len(warnings), 1)
        self.assertIs(warnings[0].severity, Severity.CRITICAL)
        self.assertAlmostEqual(warnings[0].geometry.length, 10.0, places=6)
        self.assertAlmostEqual(warnings[0].geometry.bounds[0], 90.0, places=6)
        self.assertAlmostEqual(warnings[0].distance_m, 90.0, places=6)
        self.assertAlmostEqual(warnings[0].end_distance_m, 100.0, places=6)
        self.assertIn("fora da area permitida", warnings[0].message)

    def test_headland_overrun_at_route_end_is_info_when_allowed(self):
        route = [straight("P01", 1, y=5.0, x0=0.0, x1=100.0)]
        config = ValidationConfig(allow_headland_overrun=True, max_headland_overrun_m=12.0)

        result = RouteValidatorEngine(config).validate(route, allowed_area=box(-10, 0, 90, 10))

        self.assertIs(of_type(result, WarningType.OUTSIDE_ALLOWED_AREA)[0].severity, Severity.INFO)

    def test_outside_stretch_in_the_middle_is_critical_even_with_overrun_allowed(self):
        route = [straight("P01", 1, y=5.0, x0=0.0, x1=100.0)]
        notch = box(-10, 0, 110, 10).difference(box(40, 0, 60, 10))

        result = RouteValidatorEngine().validate(route, allowed_area=notch)

        warnings = of_type(result, WarningType.OUTSIDE_ALLOWED_AREA)
        self.assertEqual(len(warnings), 1)
        self.assertIs(warnings[0].severity, Severity.CRITICAL)
        self.assertAlmostEqual(warnings[0].geometry.length, 20.0, places=6)


class ObstacleValidatorTest(unittest.TestCase):
    def test_42_route_crossing_obstacle_flags_route_inside_obstacle(self):
        obstacle = ObstacleInput("OBS-1", Point(50.0, 0.0).buffer(5.0, 64))

        result = RouteValidatorEngine().validate([straight("P01", 1)], obstacles=[obstacle])

        warnings = of_type(result, WarningType.OBSTACLE_INTERSECTION)
        self.assertEqual(len(warnings), 1)
        self.assertIs(warnings[0].severity, Severity.CRITICAL)
        self.assertEqual(warnings[0].obstacle_id, "OBS-1")
        self.assertAlmostEqual(warnings[0].geometry.length, 10.0, places=2)
        self.assertAlmostEqual(warnings[0].distance_m, 45.0, places=2)

    def test_route_inside_safety_buffer_only_is_warning_with_distance(self):
        obstacle = ObstacleInput("OBS-1", Point(50.0, 3.0).buffer(2.0, 64))
        config = ValidationConfig(obstacle_safety_buffer_m=2.0)

        result = RouteValidatorEngine(config).validate([straight("P01", 1)], obstacles=[obstacle])

        warning = of_type(result, WarningType.OBSTACLE_INTERSECTION)[0]
        self.assertIs(warning.severity, Severity.WARNING)
        self.assertAlmostEqual(warning.actual_value, 1.0, places=2)

    def test_route_far_from_obstacle_has_no_warning(self):
        obstacle = ObstacleInput("OBS-1", Point(50.0, 30.0).buffer(5.0))

        result = RouteValidatorEngine().validate([straight("P01", 1)], obstacles=[obstacle])

        self.assertEqual(of_type(result, WarningType.OBSTACLE_INTERSECTION), [])


class SpacingValidatorTest(unittest.TestCase):
    def test_43_spacing_10_50_against_10_00_with_tolerance_0_10_is_flagged(self):
        routes = [straight("P01", 1, y=0.0), straight("P02", 2, y=10.5)]

        result = RouteValidatorEngine(ValidationConfig(spacing_tolerance_m=0.10)).validate(
            routes, expected_spacing_m=10.0
        )

        warnings = of_type(result, WarningType.SPACING_OUT_OF_TOLERANCE)
        self.assertEqual(len(warnings), 1)
        warning = warnings[0]
        self.assertEqual((warning.pass_id, warning.related_pass_id), ("P02", "P01"))
        self.assertAlmostEqual(warning.expected_value, 10.0)
        self.assertAlmostEqual(warning.actual_value, 10.5, places=6)
        self.assertAlmostEqual(warning.difference, 0.5, places=6)
        self.assertIn("Esperado: 10.00 m", warning.message)
        self.assertIn("Medido: 10.50 m", warning.message)
        self.assertIn("Desvio: +0.50 m", warning.message)

    def test_spacing_within_tolerance_is_clean(self):
        routes = [straight("P01", 1, y=0.0), straight("P02", 2, y=10.08)]

        result = RouteValidatorEngine().validate(routes, expected_spacing_m=10.0)

        self.assertEqual(of_type(result, WarningType.SPACING_OUT_OF_TOLERANCE), [])

    def test_spacing_warning_covers_only_the_deviating_stretch(self):
        bent = RoutePassInput("P02", (((0.0, 10.0), (60.0, 10.0), (61.0, 10.6), (100.0, 10.6)),), 2)
        routes = [straight("P01", 1), bent]

        result = RouteValidatorEngine().validate(routes, expected_spacing_m=10.0)

        warning = of_type(result, WarningType.SPACING_OUT_OF_TOLERANCE)[0]
        self.assertGreaterEqual(warning.distance_m, 55.0)
        self.assertLess(warning.geometry.length, 50.0)
        self.assertAlmostEqual(warning.actual_value, 10.6, places=6)

    def test_spacing_is_skipped_without_expected_spacing(self):
        routes = [straight("P01", 1, y=0.0), straight("P02", 2, y=12.0)]

        result = RouteValidatorEngine().validate(routes)

        self.assertEqual(of_type(result, WarningType.SPACING_OUT_OF_TOLERANCE), [])

    def test_shorter_neighbour_does_not_create_false_spacing_warning_past_its_end(self):
        routes = [straight("P01", 1, y=0.0, x1=100.0), straight("P02", 2, y=10.0, x1=50.0)]

        result = RouteValidatorEngine().validate(routes, expected_spacing_m=10.0)

        self.assertEqual(of_type(result, WarningType.SPACING_OUT_OF_TOLERANCE), [])


class CrossingValidatorTest(unittest.TestCase):
    def test_44_x_crossing_is_flagged_at_the_intersection_point(self):
        routes = [
            RoutePassInput("P14", (((0.0, 0.0), (100.0, 100.0)),), 14),
            RoutePassInput("P18", (((0.0, 100.0), (100.0, 0.0)),), 18),
        ]

        result = RouteValidatorEngine().validate(routes)

        warnings = of_type(result, WarningType.UNEXPECTED_ROUTE_CROSSING)
        self.assertEqual(len(warnings), 1)
        self.assertEqual((warnings[0].pass_id, warnings[0].related_pass_id), ("P14", "P18"))
        self.assertEqual(warnings[0].geometry.geom_type, "Point")
        self.assertAlmostEqual(warnings[0].geometry.x, 50.0)
        self.assertAlmostEqual(warnings[0].geometry.y, 50.0)
        self.assertEqual(warnings[0].message, "Passada P14 cruza P18 em ponto nao planejado.")

    def test_border_route_crossing_is_allowed(self):
        routes = [straight("P01", 1, y=50.0), RoutePassInput("B1", (((50.0, 0.0), (50.0, 100.0)),), 2, route_type="BORDER")]

        result = RouteValidatorEngine().validate(routes)

        self.assertEqual(of_type(result, WarningType.UNEXPECTED_ROUTE_CROSSING), [])

    def test_end_to_end_connection_is_not_a_crossing(self):
        routes = [
            RoutePassInput("P01", (((0.0, 0.0), (100.0, 0.0)),), 1),
            RoutePassInput("P02", (((100.0, 0.0), (100.0, 10.0)),), 2),
        ]

        result = RouteValidatorEngine().validate(routes)

        self.assertEqual(of_type(result, WarningType.UNEXPECTED_ROUTE_CROSSING), [])


class GeometryValidatorTest(unittest.TestCase):
    def test_45_duplicated_route_is_flagged(self):
        routes = [straight("P01", 1), straight("P02", 2, y=0.02)]

        result = RouteValidatorEngine().validate(routes)

        warnings = of_type(result, WarningType.DUPLICATED_ROUTE)
        self.assertEqual(len(warnings), 1)
        self.assertEqual((warnings[0].pass_id, warnings[0].related_pass_id), ("P02", "P01"))
        self.assertAlmostEqual(warnings[0].actual_value, 100.0, places=3)

    def test_46_smooth_curve_has_no_sharp_direction_warning(self):
        result = RouteValidatorEngine().validate([arc("P01", radius=100.0, degrees=120.0, step_deg=0.5)])

        self.assertEqual(of_type(result, WarningType.SHARP_DIRECTION_CHANGE), [])

    def test_47_v_shape_is_flagged_once_at_the_apex(self):
        route = RoutePassInput("P01", (((0.0, 100.0), (50.0, 0.0), (100.0, 100.0)),), 1)

        result = RouteValidatorEngine().validate([route])

        warnings = of_type(result, WarningType.SHARP_DIRECTION_CHANGE)
        self.assertEqual(len(warnings), 1)
        self.assertAlmostEqual(warnings[0].geometry.x, 50.0)
        self.assertAlmostEqual(warnings[0].geometry.y, 0.0)
        self.assertGreater(warnings[0].actual_value, 120.0)

    def test_densified_corner_is_flagged_once(self):
        points = tuple((float(x), 0.0) for x in range(0, 51)) + tuple((50.0, float(y)) for y in range(1, 51))
        result = RouteValidatorEngine().validate([RoutePassInput("P01", (points,), 1)])

        self.assertEqual(len(of_type(result, WarningType.SHARP_DIRECTION_CHANGE)), 1)

    def test_route_too_short(self):
        result = RouteValidatorEngine().validate([straight("P01", 1, x1=3.0)])

        warning = of_type(result, WarningType.ROUTE_TOO_SHORT)[0]
        self.assertAlmostEqual(warning.actual_value, 3.0)

    def test_structural_problems_are_critical_and_block_simulation(self):
        routes = [
            RoutePassInput("P01", (), 1),
            RoutePassInput("P02", (((0.0, 0.0),),), 2),
            RoutePassInput("P03", (((5.0, 5.0), (5.0, 5.0)),), 3),
            RoutePassInput("P04", (((0.0, float("nan")), (1.0, 1.0)),), 4),
        ]

        result = RouteValidatorEngine().validate(routes)

        types = {w.pass_id: w.warning_type for w in result.warnings}
        self.assertEqual(types["P01"], WarningType.EMPTY_ROUTE)
        self.assertEqual(types["P02"], WarningType.INVALID_GEOMETRY)
        self.assertEqual(types["P03"], WarningType.ZERO_LENGTH_ROUTE)
        self.assertEqual(types["P04"], WarningType.INVALID_GEOMETRY)
        self.assertTrue(all(w.severity is Severity.CRITICAL for w in result.warnings))
        self.assertEqual(result.blocked_pass_ids(), ["P01", "P02", "P03", "P04"])


class TransitionValidatorTest(unittest.TestCase):
    def test_sequence_jump_is_suspect_without_reordering(self):
        routes = [straight("P01", 1, y=0.0), straight("P02", 2, y=10.0), straight("P03", 3, y=50.0), straight("P04", 4, y=20.0)]

        result = RouteValidatorEngine().validate(routes, expected_spacing_m=10.0)

        suspects = of_type(result, WarningType.ROUTE_SEQUENCE_SUSPECT)
        self.assertEqual([(w.related_pass_id, w.pass_id) for w in suspects], [("P02", "P03"), ("P03", "P04")])
        self.assertEqual([r.id for r in routes], ["P01", "P02", "P03", "P04"])

    def test_next_route_too_far(self):
        routes = [straight("P01", 1, y=0.0, x0=0.0, x1=100.0), straight("P02", 2, y=10.0, x0=200.0, x1=300.0)]

        result = RouteValidatorEngine(ValidationConfig(max_transition_distance_m=50.0)).validate(routes)

        warning = of_type(result, WarningType.NEXT_ROUTE_TOO_FAR)[0]
        self.assertEqual((warning.related_pass_id, warning.pass_id), ("P01", "P02"))
        self.assertAlmostEqual(warning.actual_value, math.hypot(100.0, 10.0))


class ResultAndEngineTest(unittest.TestCase):
    def test_validator_never_changes_input_routes(self):
        routes = parallel(4) + [RoutePassInput("P09", (((0.0, 0.0), (100.0, 30.0)),), 9)]
        before = copy.deepcopy(routes)
        area = box(10, -5, 90, 40)

        RouteValidatorEngine().validate(routes, allowed_area=area, expected_spacing_m=10.0)

        self.assertEqual(routes, before)
        self.assertEqual(area.bounds, (10.0, -5.0, 90.0, 40.0))

    def test_warnings_for_pass_include_related_pass(self):
        routes = [
            RoutePassInput("P14", (((0.0, 0.0), (100.0, 100.0)),), 1),
            RoutePassInput("P18", (((0.0, 100.0), (100.0, 0.0)),), 2),
        ]
        result = RouteValidatorEngine().validate(routes)

        self.assertEqual(len(result.warnings_for_pass("P18")), 1)
        self.assertEqual(result.warnings_for_pass("P99"), [])

    def test_ids_filters_status_and_json_report(self):
        routes = [straight("P01", 1, y=0.0), straight("P02", 2, y=10.5)]
        result = RouteValidatorEngine().validate(
            routes, allowed_area=box(-1, -5, 90, 20), expected_spacing_m=10.0
        )
        result.set_status(result.warnings[0].id, WarningStatus.REVIEWED)

        self.assertEqual([w.id for w in result.warnings], [f"W{i:04d}" for i in range(1, len(result.warnings) + 1)])
        self.assertEqual(len(result.filtered("SPACING")), 1)
        self.assertEqual(result.filtered("CRITICAL"), [w for w in result.warnings if w.severity is Severity.CRITICAL])
        with tempfile.TemporaryDirectory() as tmp:
            data = json.loads(result.write_json(Path(tmp) / "r.json").read_text(encoding="utf-8"))
        self.assertEqual(data["route_count"], 2)
        self.assertEqual(data["critical"] + data["warning"] + data["info"], len(data["warnings"]))
        self.assertEqual(data["warnings"][0]["status"], "REVIEWED")
        self.assertTrue(data["warnings"][0]["geometry_wkt"].startswith("LINESTRING"))

    def test_open_warnings_block_only_when_configured(self):
        result = RouteValidatorEngine().validate(
            [straight("P01", 1, y=0.0), straight("P02", 2, y=10.5)], expected_spacing_m=10.0
        )

        self.assertFalse(result.blocks_simulation(allow_with_warnings=True))
        self.assertTrue(result.blocks_simulation(allow_with_warnings=False))
        for warning in result.warnings:
            result.set_status(warning.id, WarningStatus.IGNORED)
        self.assertFalse(result.blocks_simulation(allow_with_warnings=False))

    def test_nearest_warning_to_map_click(self):
        routes = [
            RoutePassInput("P14", (((0.0, 0.0), (100.0, 100.0)),), 1),
            RoutePassInput("P18", (((0.0, 100.0), (100.0, 0.0)),), 2),
        ]
        result = RouteValidatorEngine().validate(routes)

        self.assertEqual(result.nearest_warning(51.0, 50.0, 2.0).pass_id, "P14")
        self.assertIsNone(result.nearest_warning(80.0, 50.0, 2.0))

    def test_logs_start_each_validator_and_finish(self):
        with self.assertLogs("fortsmart_precision.validation", level="INFO") as logs:
            RouteValidatorEngine().validate(parallel(2), expected_spacing_m=10.0)

        text = "\n".join(logs.output)
        self.assertIn("VALIDATION START route_count=2 obstacle_count=0 expected_spacing=10.00 tolerance=0.10", text)
        self.assertIn("VALIDATOR: SPACING warnings=0", text)
        self.assertIn("VALIDATION FINISHED critical=0 warning=0 info=0", text)

    def test_same_input_is_served_from_cache(self):
        engine = RouteValidatorEngine()
        routes = parallel(3)

        first = engine.validate(routes, expected_spacing_m=10.0)

        self.assertIs(engine.validate(routes, expected_spacing_m=10.0), first)
        self.assertIsNot(engine.validate(routes, expected_spacing_m=9.0), first)

    def test_48_validate_then_simulate_normally_with_open_warnings(self):
        routes = [straight("P01", 1, y=0.0), straight("P02", 2, y=10.5), straight("P03", 3, y=20.0)]
        result = RouteValidatorEngine().validate(routes, expected_spacing_m=10.0)
        self.assertGreater(result.warning_count, 0)
        self.assertEqual(result.blocked_pass_ids(), [])

        engine = RouteSimulationEngine(build_ordered_route(routes), MachineProfile(id="m", name="M"), 10.0)
        engine.start()
        seen = set()
        while not engine.state.is_finished:
            engine.advance(1.0)
            seen.add(engine.state.current_pass_id)
            result.warnings_for_pass(engine.state.current_pass_id)

        self.assertTrue(engine.state.is_finished)
        self.assertEqual(seen, {"P01", "P02", "P03"})
        self.assertAlmostEqual(engine.state.completed_distance_m, 300.0)


if __name__ == "__main__":
    unittest.main()
