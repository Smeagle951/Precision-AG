# -*- coding: utf-8 -*-
"""SKILL 2 — desvio minimo da pulverizacao (barra fisica x zona de seguranca)."""

from __future__ import annotations

import math
import unittest
from dataclasses import replace

from plugin.fortsmart_precision.core.application_obstacle_engine import (
    SPRAY_TURN_RADIUS_MISSING,
    SprayAvoidanceType,
    analyze_spray_pass_conflict,
    apply_application_obstacle_avoidance,
    build_spray_safety_zones,
    classify_spray_conflict,
    lateral_ramp_length_m,
    lateral_ramp_offset_m,
    min_turning_radius_m,
    resolve_sprayer_turn_radius_m,
    spray_boom_clearance_violations,
    spray_boom_width_m,
    spray_conflict_counts,
    spray_corridor_half_width_m,
    spray_pass_avoidance_types,
    tangent_contour_profile,
)
from plugin.fortsmart_precision.core.guidance_engine import TrafficPass
from plugin.fortsmart_precision.core.line_geometry import Segment
from plugin.fortsmart_precision.domain.avoidance_configuration import (
    AvoidanceConfiguration,
    AvoidanceConfigurationError,
)
from plugin.fortsmart_precision.domain.machine_model import (
    MachineModelError,
    MachineTrack,
    SprayerMachine,
)
from plugin.fortsmart_precision.domain.obstacle_model import obstacle_from_point

FIELD = [([(0.0, 0.0), (600.0, 0.0), (600.0, 400.0), (0.0, 400.0), (0.0, 0.0)], [])]
TURN_RADIUS = 8.0
HALF_BOOM = 18.0


def _sprayer(turn_radius: float | None = TURN_RADIUS) -> SprayerMachine:
    return SprayerMachine(
        machine_id="s36",
        name="Barra 36 m",
        nozzle_count=72,
        nozzle_spacing_m=0.5,
        boom_width_m=36.0,
        track=MachineTrack(track_width_m=3.0, tire_width_m=0.5),
        sprayer_minimum_turn_radius_m=turn_radius,
    )


def _config(**kwargs) -> AvoidanceConfiguration:
    return AvoidanceConfiguration(minimum_deviation=True, **kwargs)


def _pass(y: float, pass_no: int = 1, x0: float = 0.0, x1: float = 600.0) -> TrafficPass:
    a, b = (x0, y), (x1, y)
    return TrafficPass(
        pass_no=pass_no,
        fs_id=f"p{pass_no}",
        operation_id="spraying",
        spacing_m=36.0,
        width_m=36.0,
        offset_m=0.0,
        azimuth_deg=90.0,
        direction="forward",
        clipped_segment=Segment(a, b),
        guidance_segment=Segment(a, b),
        path_points=(a, b),
    )


def _obstacle(x: float, y: float, oid: str = "poste"):
    return obstacle_from_point((x, y), obstacle_radius_m=0.5, safety_margin_m=1.0, obstacle_id=oid)


def _run(passes, obstacles, machine=None, config=None, allowed_area=FIELD):
    records: list = []
    out, avoided = apply_application_obstacle_avoidance(
        passes,
        list(obstacles),
        machine or _sprayer(),
        config or _config(),
        allowed_area=allowed_area,
        report=records,
    )
    return out, avoided, records


def _lateral(point, y_pass: float) -> float:
    """Pass na direcao +x: lateral positiva = esquerda = +y."""
    return point[1] - y_pass


class SprayGeometryAssertions(unittest.TestCase):
    def assert_smooth_detour(self, original: TrafficPass, modified: TrafficPass, obstacles) -> None:
        pts = list(modified.line_points())
        start, end = original.line_points()[0], original.line_points()[-1]
        self.assertEqual(pts[0], start)
        self.assertEqual(pts[-1], end)
        headings = [
            math.atan2(b[1] - a[1], b[0] - a[0])
            for a, b in zip(pts, pts[1:])
            if math.dist(a, b) > 1e-6
        ]
        for heading in headings:
            # Nunca reverte o rumo da passada (sem U/V).
            self.assertGreater(math.cos(heading), -1e-9)
        changes = [
            abs((h2 - h1 + math.pi) % (2.0 * math.pi) - math.pi)
            for h1, h2 in zip(headings, headings[1:])
        ]
        self.assertLessEqual(math.degrees(max(changes)), 10.0)
        self.assertGreaterEqual(min_turning_radius_m(pts), TURN_RADIUS * 0.98)
        violations = spray_boom_clearance_violations(
            pts, build_spray_safety_zones(list(obstacles)), HALF_BOOM, tolerance_m=0.02
        )
        self.assertEqual(violations, [])

    def assert_exact_return(self, modified: TrafficPass, y_pass: float, entry: float, exit_: float):
        for point in modified.line_points():
            if point[0] <= entry - 1e-6 or point[0] >= exit_ + 1e-6:
                self.assertAlmostEqual(_lateral(point, y_pass), 0.0, places=6)


class ClassificationTests(unittest.TestCase):
    def test_example_from_spec_lateral_left_6_5(self):
        kind, side, required = classify_spray_conflict(-13.0, 1.5, 36.0, corridor_half_width_m=1.75)
        self.assertEqual(kind, SprayAvoidanceType.LATERAL)
        self.assertEqual(side, "left")
        self.assertAlmostEqual(required, 6.5)

    def test_outside_boom_is_none(self):
        kind, side, required = classify_spray_conflict(25.0, 1.5, 36.0, corridor_half_width_m=1.75)
        self.assertEqual((kind, side, required), (SprayAvoidanceType.NONE, "", 0.0))

    def test_zone_touching_boom_tip_exactly_is_none(self):
        kind, _side, _required = classify_spray_conflict(19.5, 1.5, 36.0)
        self.assertEqual(kind, SprayAvoidanceType.NONE)

    def test_center_corridor_is_full_contour(self):
        kind, _side, _required = classify_spray_conflict(-0.5, 1.5, 36.0, corridor_half_width_m=1.75)
        self.assertEqual(kind, SprayAvoidanceType.FULL_CONTOUR)

    def test_uses_physical_boom_not_effective_spacing(self):
        machine = replace(_sprayer(), overlap_m=2.0)
        self.assertAlmostEqual(spray_boom_width_m(machine), 36.0)
        self.assertAlmostEqual(spray_corridor_half_width_m(machine), 1.75)

    def test_analyze_pass_conflict_reports_both_sides(self):
        zone = build_spray_safety_zones([_obstacle(300.0, 185.0)])[0]
        result = analyze_spray_pass_conflict(
            [(0.0, 200.0), (600.0, 200.0)], zone, half_boom_m=18.0, corridor_half_width_m=1.75
        )
        self.assertEqual(result.avoidance_type, SprayAvoidanceType.LATERAL)
        self.assertAlmostEqual(result.left_required_m, 4.5)
        self.assertAlmostEqual(result.right_required_m, 34.5)
        self.assertAlmostEqual(result.s_min, 298.5)
        self.assertAlmostEqual(result.s_max, 301.5)


class SafetyZoneTests(unittest.TestCase):
    def test_safe_radius_is_obstacle_radius_plus_margin(self):
        zone = build_spray_safety_zones([_obstacle(10.0, 10.0, "p1")])[0]
        self.assertAlmostEqual(zone.safe_radius_m, 1.5)
        attrs = zone.attributes()
        self.assertEqual(attrs["operation"], "spraying")
        self.assertEqual(attrs["obstacle_id"], "p1")
        self.assertAlmostEqual(attrs["safe_radius_m"], 1.5)
        self.assertTrue(zone.circular)


class TurnRadiusTests(unittest.TestCase):
    def test_sprayer_radius_has_priority(self):
        self.assertEqual(
            resolve_sprayer_turn_radius_m(_sprayer(9.0), _config(minimum_turn_radius_m=6.0)), 9.0
        )

    def test_falls_back_to_config_and_never_invents(self):
        self.assertEqual(resolve_sprayer_turn_radius_m(_sprayer(None), _config(minimum_turn_radius_m=7.0)), 7.0)
        self.assertIsNone(resolve_sprayer_turn_radius_m(_sprayer(None), _config(minimum_turn_radius_m=None)))

    def test_sprayer_model_validates_radius(self):
        _sprayer(8.0).validate()
        _sprayer(None).validate()
        with self.assertRaises(MachineModelError):
            _sprayer(0.0).validate()
        self.assertEqual(_sprayer(8.0).to_dict()["sprayer_minimum_turn_radius_m"], 8.0)
        self.assertEqual(_sprayer(8.0).minimum_turn_radius_m, 8.0)

    def test_missing_radius_is_unresolved_and_keeps_original(self):
        original = _pass(208.0)
        out, avoided, records = _run(
            [original], [_obstacle(300.0, 200.0)], _sprayer(None), _config(minimum_turn_radius_m=None)
        )
        self.assertEqual(out[0].line_points(), original.line_points())
        self.assertEqual(avoided, [])
        self.assertEqual(records[0].avoidance_type, SprayAvoidanceType.UNRESOLVED.value)
        self.assertEqual(records[0].reason, SPRAY_TURN_RADIUS_MISSING)


class AvoidanceConfigurationTests(unittest.TestCase):
    def test_defaults_keep_legacy(self):
        config = AvoidanceConfiguration()
        self.assertFalse(config.minimum_deviation)
        self.assertEqual(config.side_preference, "auto")
        config.validate()

    def test_rejects_invalid_side_and_negative_distances(self):
        with self.assertRaises(AvoidanceConfigurationError):
            _config(side_preference="frente").validate()
        with self.assertRaises(AvoidanceConfigurationError):
            _config(preparation_distance_m=-1.0).validate()
        with self.assertRaises(AvoidanceConfigurationError):
            _config(return_distance_m=-0.5).validate()


class RampAndContourProfileTests(unittest.TestCase):
    def test_lateral_ramp_is_tangent_and_reaches_offset(self):
        total = lateral_ramp_length_m(4.5, TURN_RADIUS)
        self.assertGreater(total, 0.0)
        self.assertAlmostEqual(lateral_ramp_offset_m(0.0, 4.5, TURN_RADIUS), 0.0)
        self.assertAlmostEqual(lateral_ramp_offset_m(total, 4.5, TURN_RADIUS), 4.5)
        self.assertAlmostEqual(lateral_ramp_offset_m(0.01, 4.5, TURN_RADIUS), 0.0, places=4)
        values = [lateral_ramp_offset_m(total * k / 50, 4.5, TURN_RADIUS) for k in range(51)]
        self.assertEqual(values, sorted(values))
        self.assertAlmostEqual(lateral_ramp_offset_m(total / 2, -4.5, TURN_RADIUS), -2.25)

    def test_tangent_contour_profile_is_tangent_and_concentric(self):
        profile = tangent_contour_profile(300.0, -0.5, 19.6, TURN_RADIUS, 1.0)
        self.assertIsNotNone(profile)
        self.assertEqual(profile[0][1], 0.0)
        self.assertEqual(profile[-1][1], 0.0)
        self.assertAlmostEqual(max(d for _s, d in profile), 19.1, places=2)
        self.assertGreaterEqual(min_turning_radius_m(profile), TURN_RADIUS * 0.999)
        right = tangent_contour_profile(300.0, 0.5, 19.6, TURN_RADIUS, -1.0)
        self.assertAlmostEqual(min(d for _s, d in right), -19.1, places=2)

    def test_tangent_contour_refuses_reversal(self):
        self.assertIsNone(tangent_contour_profile(300.0, 10.0, 19.6, TURN_RADIUS, 1.0))


class Step14ConflictTableTests(SprayGeometryAssertions):
    """Passo 14: barra 36 m, poste em (300, 200), zona 1,50 m."""

    def setUp(self):
        self.obstacle = _obstacle(300.0, 200.0, "poste_1")
        self.ys = [225.0, 215.0, 208.0, 200.5, 175.0]
        self.passes = [_pass(y, pass_no=i) for i, y in enumerate(self.ys, start=1)]
        self.out, self.avoided, records = _run(self.passes, [self.obstacle])
        self.by_pass = {rec.pass_id: rec for rec in records}

    def test_each_pass_analyzed_separately(self):
        expected = {
            1: ("NONE", "", 0.0),
            2: ("LATERAL", "left", 4.5),
            3: ("LATERAL", "left", 11.5),
            4: ("FULL_CONTOUR", "left", 19.0),
            5: ("NONE", "", 0.0),
        }
        for pass_id, (kind, side, required) in expected.items():
            rec = self.by_pass[pass_id]
            self.assertEqual(rec.avoidance_type, kind, pass_id)
            self.assertEqual(rec.side, side, pass_id)
            self.assertAlmostEqual(rec.required_offset_m, required, places=6, msg=pass_id)
            self.assertEqual(rec.operation, "spraying")
            self.assertAlmostEqual(rec.boom_width_m, 36.0)
            self.assertAlmostEqual(rec.safe_radius_m, 1.5)
            self.assertEqual(rec.minimum_turn_radius_m, TURN_RADIUS)

    def test_none_passes_unchanged_and_next_pass_recalculated(self):
        self.assertEqual(self.out[0].line_points(), self.passes[0].line_points())
        self.assertEqual(self.out[4].line_points(), self.passes[4].line_points())
        self.assertLess(self.by_pass[2].applied_offset_m, self.by_pass[3].applied_offset_m)

    def test_lateral_passes_are_smooth_and_return_exactly(self):
        for index in (1, 2):
            rec = self.by_pass[index + 1]
            self.assert_smooth_detour(self.passes[index], self.out[index], [self.obstacle])
            self.assert_exact_return(self.out[index], self.ys[index], rec.entry_station_m, rec.exit_station_m)
            peak = max(_lateral(p, self.ys[index]) for p in self.out[index].line_points())
            self.assertAlmostEqual(peak, rec.required_offset_m + 0.05, places=6)

    def test_central_pass_contours_without_full_orbit(self):
        rec = self.by_pass[4]
        modified = self.out[3]
        self.assert_smooth_detour(self.passes[3], modified, [self.obstacle])
        self.assert_exact_return(modified, 200.5, rec.entry_station_m, rec.exit_station_m)
        headings = [
            math.atan2(b[1] - a[1], b[0] - a[0])
            for a, b in zip(modified.line_points(), modified.line_points()[1:])
            if math.dist(a, b) > 1e-6
        ]
        self.assertLess(max(abs(h) for h in headings), math.pi / 2.0)

    def test_avoided_paths_only_for_conflicts(self):
        self.assertEqual(sorted(path.pass_id for path in self.avoided), [2, 3, 4])
        self.assertTrue(all(path.returns_to_guidance for path in self.avoided))

    def test_pass_attributes_and_counts(self):
        records = list(self.by_pass.values())
        counts = spray_conflict_counts(records)
        self.assertEqual(counts, {"NONE": 2, "LATERAL": 2, "FULL_CONTOUR": 1, "UNRESOLVED": 0})
        per_pass = spray_pass_avoidance_types(records)
        self.assertEqual(per_pass[4]["avoidance_type"], "FULL_CONTOUR")
        self.assertEqual(per_pass[2]["obstacle_ids"], "poste_1")
        self.assertEqual(per_pass[1]["obstacle_ids"], "")

    def test_record_attributes_and_corridor(self):
        rec = self.by_pass[2]
        attrs = rec.attributes()
        for key in (
            "operation",
            "pass_id",
            "obstacle_id",
            "avoidance_type",
            "side",
            "boom_width_m",
            "safe_radius_m",
            "required_offset_m",
            "entry_station_m",
            "exit_station_m",
            "minimum_turn_radius_m",
        ):
            self.assertIn(key, attrs)
        self.assertIsNotNone(rec.corridor_polygon())
        self.assertIsNone(self.by_pass[1].corridor_polygon())


class SixRequiredCasesTests(SprayGeometryAssertions):
    def test_case1_obstacle_outside_boom(self):
        original = _pass(200.0)
        out, avoided, records = _run([original], [_obstacle(300.0, 175.0)])
        self.assertEqual(out[0].line_points(), original.line_points())
        self.assertEqual(avoided, [])
        self.assertEqual(records[0].avoidance_type, "NONE")

    def test_case2_obstacle_at_boom_tip_small_lateral(self):
        original = _pass(200.0)
        obstacle = _obstacle(300.0, 183.0)
        out, _avoided, records = _run([original], [obstacle])
        rec = records[0]
        self.assertEqual((rec.avoidance_type, rec.side), ("LATERAL", "left"))
        self.assertAlmostEqual(rec.required_offset_m, 2.5)
        self.assert_smooth_detour(original, out[0], [obstacle])
        self.assert_exact_return(out[0], 200.0, rec.entry_station_m, rec.exit_station_m)
        self.assertLess(rec.exit_station_m - rec.entry_station_m, 30.0)

    def test_case3_intermediate_obstacle(self):
        original = _pass(200.0)
        obstacle = _obstacle(300.0, 192.0)
        out, _avoided, records = _run([original], [obstacle])
        rec = records[0]
        self.assertEqual((rec.avoidance_type, rec.side), ("LATERAL", "left"))
        self.assertAlmostEqual(rec.required_offset_m, 11.5)
        self.assert_smooth_detour(original, out[0], [obstacle])
        self.assert_exact_return(out[0], 200.0, rec.entry_station_m, rec.exit_station_m)

    def test_case4_central_obstacle(self):
        original = _pass(200.0)
        obstacle = _obstacle(300.0, 199.5)
        out, _avoided, records = _run([original], [obstacle])
        rec = records[0]
        self.assertEqual(rec.avoidance_type, "FULL_CONTOUR")
        self.assertGreaterEqual(rec.applied_offset_m, rec.required_offset_m)
        self.assert_smooth_detour(original, out[0], [obstacle])
        self.assert_exact_return(out[0], 200.0, rec.entry_station_m, rec.exit_station_m)

    def test_case5_two_close_obstacles_single_detour(self):
        original = _pass(200.0)
        obstacles = [_obstacle(300.0, 188.0, "a"), _obstacle(306.0, 190.0, "b")]
        out, avoided, records = _run([original], obstacles)
        self.assertEqual(len(records), 2)
        self.assertEqual({rec.avoidance_type for rec in records}, {"LATERAL"})
        self.assertEqual({rec.side for rec in records}, {"left"})
        self.assertEqual(len({(rec.entry_station_m, rec.exit_station_m) for rec in records}), 1)
        self.assertEqual(len(avoided), 1)
        self.assertEqual(avoided[0].obstacle_id, "a+b")
        peak = max(_lateral(p, 200.0) for p in out[0].line_points())
        self.assertAlmostEqual(peak, 9.5 + 0.05, places=6)
        self.assert_smooth_detour(original, out[0], obstacles)
        rec = records[0]
        self.assert_exact_return(out[0], 200.0, rec.entry_station_m, rec.exit_station_m)

    def test_case6_near_field_boundary_switches_side(self):
        original = _pass(10.0)
        obstacle = _obstacle(300.0, 14.0)
        out, _avoided, records = _run([original], [obstacle])
        rec = records[0]
        # Direita (15,5 m) sairia do talhao (y < 0): escolhe a esquerda (23,5 m).
        self.assertEqual((rec.avoidance_type, rec.side), ("LATERAL", "left"))
        self.assertAlmostEqual(rec.required_offset_m, 23.5)
        self.assertTrue(all(0.0 <= p[1] <= 400.0 for p in out[0].line_points()))
        self.assert_smooth_detour(original, out[0], [obstacle])
        self.assert_exact_return(out[0], 10.0, rec.entry_station_m, rec.exit_station_m)

    def test_case6_without_boundary_prefers_cheaper_right(self):
        original = _pass(10.0)
        _out, _avoided, records = _run([original], [_obstacle(300.0, 14.0)], allowed_area=None)
        self.assertEqual((records[0].side, records[0].required_offset_m), ("right", 15.5))


class SideAndFailureTests(SprayGeometryAssertions):
    def test_forced_side_is_respected(self):
        original = _pass(200.0)
        obstacle = _obstacle(300.0, 185.0)
        out, _avoided, records = _run([original], [obstacle], config=_config(side_preference="right"))
        rec = records[0]
        self.assertEqual((rec.avoidance_type, rec.side), ("LATERAL", "right"))
        self.assertAlmostEqual(rec.required_offset_m, 34.5)
        self.assert_smooth_detour(original, out[0], [obstacle])

    def test_preparation_and_return_distances_extend_safe_stretch(self):
        base = _run([_pass(200.0)], [_obstacle(300.0, 185.0)])[2][0]
        longer = _run(
            [_pass(200.0)],
            [_obstacle(300.0, 185.0)],
            config=_config(preparation_distance_m=5.0, return_distance_m=7.0),
        )[2][0]
        ramp = lateral_ramp_length_m(4.55, TURN_RADIUS)
        self.assertAlmostEqual(longer.entry_station_m, 298.5 - 5.0 - ramp, places=6)
        self.assertAlmostEqual(longer.exit_station_m, 301.5 + 7.0 + ramp, places=6)
        self.assertLess(longer.entry_station_m, base.entry_station_m)
        self.assertGreater(longer.exit_station_m, base.exit_station_m)

    def test_no_room_for_transition_is_unresolved(self):
        original = _pass(200.0, x0=295.0, x1=305.0)
        out, avoided, records = _run([original], [_obstacle(300.0, 192.0)])
        self.assertEqual(records[0].avoidance_type, "UNRESOLVED")
        self.assertTrue(records[0].reason)
        self.assertEqual(out[0].line_points(), original.line_points())
        self.assertEqual(avoided, [])
        self.assertGreaterEqual(len(records[0].detour_points), 2)

    def test_reverse_direction_pass_mirrors_side(self):
        a, b = (600.0, 200.0), (0.0, 200.0)
        original = replace(_pass(200.0), clipped_segment=Segment(a, b), guidance_segment=Segment(a, b), path_points=(a, b))
        _out, _avoided, records = _run([original], [_obstacle(300.0, 185.0)])
        self.assertEqual((records[0].side, records[0].required_offset_m), ("right", 4.5))


class PipelineIntegrationTests(unittest.TestCase):
    def _result(self, turn_radius):
        from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
        from tests.unit.test_spray_obstacle_regression_baseline import (
            SPRAY_DEFAULT_ON,
            build_project,
        )

        config = replace(SPRAY_DEFAULT_ON, minimum_deviation=True, minimum_turn_radius_m=turn_radius)
        return run_precision_lines(
            build_project(spraying=True, planting=False, avoidance=config, planting_enabled=False)
        )

    def test_records_and_summary_with_radius(self):
        result = self._result(TURN_RADIUS)
        self.assertTrue(result.validation.ok, [e.message for e in result.validation.errors])
        counts = spray_conflict_counts(result.spray_avoidance_records)
        self.assertEqual(counts["UNRESOLVED"], 0)
        self.assertGreater(counts["LATERAL"] + counts["FULL_CONTOUR"], 0)
        self.assertTrue(any("Desvio pulverizacao" in check for check in result.validation.checks))

    def test_missing_radius_is_reported_and_blocks(self):
        result = self._result(None)
        codes = {issue.code for issue in result.validation.errors}
        warnings = {issue.code for issue in result.validation.warnings}
        self.assertIn("SPRAY_AVOIDANCE_UNRESOLVED", codes)
        self.assertIn("SPRAYER_TURN_RADIUS_MISSING", warnings)
        self.assertFalse(result.validation.ok)


if __name__ == "__main__":
    unittest.main()
