# -*- coding: utf-8 -*-
"""Desvio manual de obstaculo (V1): LATERAL_LEFT, LATERAL_RIGHT e CUT_RESUME."""

from __future__ import annotations

import logging
import math
import unittest
from dataclasses import replace

from shapely.affinity import scale
from shapely.geometry import LineString, MultiLineString, Point, box

from plugin.fortsmart_precision.core.lateral_detour.engine import (
    DETOURED,
    create_lateral_detour,
    crosses_to_other_side,
)
from plugin.fortsmart_precision.core.obstacle_detour import (
    V1_DETOUR_TYPES,
    DetourParameters,
    DetourStatus,
    DetourType,
    LineDirection,
    NearbyObstacle,
    build_manual_detour,
    detour_debug_text,
    safety_zone,
    selection_error,
    suggest_lateral_distances,
)
from plugin.fortsmart_precision.core.obstacle_detour.geometry import lateral_config
from plugin.fortsmart_precision.core.obstacle_detour.models import (
    MSG_ENDPOINT_INSIDE,
    MSG_FIELD_NOT_CHECKED,
    MSG_INVADES_ZONE,
    MSG_SWATH_OUTSIDE_FIELD,
    other_obstacle_warning,
    MSG_NO_CONFLICT,
    MSG_NO_TRANSITION,
    MSG_SELECT_LINE,
    MSG_SELECT_OBSTACLE,
    MSG_SELECT_ONE_EACH,
)
from plugin.fortsmart_precision.core.obstacle_detour.validation import (
    MAX_VERTEX_TURN_DEG,
    has_duplicate_segment,
    side_consistent,
    signed_offset,
    surroundings_warnings,
    validate_cut,
    vertex_turns_deg,
)
from plugin.fortsmart_precision.domain.obstacle_strategy import DetourSide

LINE = LineString([(0.0, 0.0), (100.0, 0.0)])
POST = Point(50.0, 0.0)
TOLERANCE = 0.03


def params(detour_type=DetourType.LATERAL_LEFT, **overrides) -> DetourParameters:
    values = dict(implement_width_m=2.0, obstacle_radius_m=1.0, safety_margin_m=0.5)
    values.update(overrides)
    return DetourParameters(detour_type, **values)


def detour(detour_type=DetourType.LATERAL_LEFT, line=LINE, obstacle=POST, **overrides):
    return build_manual_detour(
        line, obstacle, params(detour_type, **overrides), line_id="L0024", obstacle_id="OB-7"
    )


class SafetyZoneTest(unittest.TestCase):
    def test_obstacle_2m_with_half_meter_margin_gives_1_5m_zone_and_path_stays_outside(self):
        p = params(obstacle_radius_m=1.0, safety_margin_m=0.5)
        self.assertAlmostEqual(p.safety_radius_m, 1.5)
        zone = safety_zone(POST, p)
        self.assertAlmostEqual(zone.bounds[2] - POST.x, 1.5, places=3)
        for detour_type in (DetourType.LATERAL_LEFT, DetourType.LATERAL_RIGHT):
            result = detour(detour_type)
            self.assertTrue(result.ok, result.messages)
            self.assertGreaterEqual(result.result_geometry.distance(POST), 1.5 + 1.0 - TOLERANCE)
            self.assertGreaterEqual(result.result_geometry.distance(zone), p.half_width_m - TOLERANCE)

    def test_zone_never_uses_width_or_spacing(self):
        for width in (1.0, 6.0, 12.0):
            p = params(implement_width_m=width)
            self.assertAlmostEqual(p.safety_radius_m, 1.5)
            self.assertAlmostEqual(safety_zone(POST, p).area, safety_zone(POST, params()).area)

    def test_margins_0_025_05_1_keep_planter_outside_zone(self):
        distances = []
        for margin in (0.0, 0.25, 0.5, 1.0):
            result = detour(DetourType.LATERAL_RIGHT, safety_margin_m=margin, longitudinal_anticipation_m=5,
                            longitudinal_return_m=5)
            self.assertTrue(result.ok, result.messages)
            minimum = 1.0 + margin + 1.0
            distance = result.result_geometry.distance(POST)
            self.assertGreaterEqual(distance, minimum - TOLERANCE)
            distances.append(distance)
        self.assertEqual(distances, sorted(distances))
        self.assertGreater(distances[-1], distances[0])


class AnticipationAndReturnTest(unittest.TestCase):
    def test_anticipation_moves_maneuver_start_but_not_the_radius(self):
        entries = set()
        for anticipation in (1.0, 2.0, 3.0, 5.0):
            result = detour(implement_width_m=1.0, longitudinal_anticipation_m=anticipation)
            self.assertTrue(result.ok, (anticipation, result.messages))
            self.assertAlmostEqual(
                result.conflict_entry_station_m - result.maneuver_start_station_m, anticipation, places=6
            )
            self.assertAlmostEqual(result.parameters.safety_radius_m, 1.5)
            entries.add(round(result.conflict_entry_station_m, 6))
        self.assertEqual(len(entries), 1)

    def test_return_moves_maneuver_end(self):
        for ret in (2.0, 4.0):
            result = detour(longitudinal_return_m=ret)
            self.assertTrue(result.ok, result.messages)
            self.assertAlmostEqual(result.maneuver_end_station_m - result.conflict_exit_station_m, ret, places=6)

    def test_exact_anticipation_is_never_scaled_silently(self):
        result = detour(implement_width_m=12.0, longitudinal_anticipation_m=3.0, longitudinal_return_m=3.0)
        self.assertIs(result.status, DetourStatus.FAILED)
        self.assertIn(MSG_NO_TRANSITION, result.messages)
        suggestion = suggest_lateral_distances(LINE, POST, params(implement_width_m=12.0))
        self.assertIsNotNone(suggestion)
        self.assertGreater(suggestion[0], 3.0)
        accepted = detour(implement_width_m=12.0, longitudinal_anticipation_m=suggestion[0],
                          longitudinal_return_m=suggestion[1])
        self.assertTrue(accepted.ok, accepted.messages)
        self.assertAlmostEqual(
            accepted.conflict_entry_station_m - accepted.maneuver_start_station_m, suggestion[0], places=6
        )

    def test_engine_default_still_scales_and_exact_mode_does_not(self):
        p = params(implement_width_m=12.0)
        config = lateral_config(p, DetourSide.LEFT, 3.0, 3.0)
        default = create_lateral_detour(LINE, [("OB", POST)], config)
        self.assertEqual(default.status, DETOURED)
        self.assertGreater(default.sections[0].approach_used, 3.0)
        exact = create_lateral_detour(LINE, [("OB", POST)], config, distance_factors=(1.0,))
        self.assertNotEqual(exact.status, DETOURED)


class TractorOffsetTest(unittest.TestCase):
    def test_tractor_offset_moves_tractor_events_and_keeps_implement_path(self):
        base = detour(tractor_to_implement_m=0.0)
        self.assertTrue(base.ok)
        for distance in (2.0, 5.0, 8.0, 10.0):
            result = detour(tractor_to_implement_m=distance)
            self.assertTrue(result.ok, result.messages)
            self.assertAlmostEqual(result.parameters.reference_to_operation_m, -distance)
            self.assertLess(result.result_geometry.hausdorff_distance(base.result_geometry), 1e-9)
            final = result.result_geometry
            implement_s = final.project(Point(result.implement_start_xy))
            tractor_s = final.project(Point(result.tractor_start_xy))
            self.assertAlmostEqual(tractor_s - implement_s, distance, places=6)

    def test_cut_resume_tractor_offset_does_not_move_ground_gap(self):
        base = detour(DetourType.CUT_RESUME)
        for distance in (2.0, 5.0, 8.0, 10.0):
            result = detour(DetourType.CUT_RESUME, tractor_to_implement_m=distance)
            self.assertAlmostEqual(result.maneuver_start_station_m, base.maneuver_start_station_m, places=6)
            self.assertAlmostEqual(result.tractor_start_xy[0] - result.implement_start_xy[0], distance, places=6)


class SideAndDirectionTest(unittest.TestCase):
    def test_left_and_right_are_mirror_equivalent(self):
        left = detour(DetourType.LATERAL_LEFT)
        right = detour(DetourType.LATERAL_RIGHT)
        self.assertTrue(left.ok and right.ok)
        self.assertEqual((left.side, right.side), ("LEFT", "RIGHT"))
        mirrored = scale(right.result_geometry, xfact=1.0, yfact=-1.0, origin=(0, 0))
        self.assertLess(mirrored.hausdorff_distance(left.result_geometry), 1e-6)
        self.assertGreater(max(y for _x, y in left.result_geometry.coords), 0)
        self.assertLess(min(y for _x, y in right.result_geometry.coords), 0)

    def test_a_to_b_and_b_to_a_are_equivalent_without_whiskers(self):
        forward = detour(DetourType.LATERAL_LEFT)
        reversed_line = LineString(list(LINE.coords)[::-1])
        backward = detour(DetourType.LATERAL_RIGHT, line=reversed_line)
        self.assertTrue(forward.ok and backward.ok)
        self.assertLess(forward.result_geometry.hausdorff_distance(backward.result_geometry), 0.05)
        travelled = detour(DetourType.LATERAL_LEFT, line=reversed_line, direction=LineDirection.B_TO_A)
        self.assertTrue(travelled.ok, travelled.messages)
        self.assertEqual(travelled.result_geometry.coords[0], reversed_line.coords[0])
        self.assertLess(travelled.result_geometry.hausdorff_distance(forward.result_geometry), 1e-6)
        for result in (forward, backward, travelled):
            geometry = result.result_geometry
            self.assertTrue(geometry.is_valid and geometry.is_simple)
            self.assertFalse(has_duplicate_segment(geometry.coords))
            self.assertLessEqual(max(vertex_turns_deg(geometry.coords)), MAX_VERTEX_TURN_DEG)

    def test_detour_never_crosses_original_line(self):
        for detour_type, side in ((DetourType.LATERAL_LEFT, "LEFT"), (DetourType.LATERAL_RIGHT, "RIGHT")):
            for anticipation in (2.0, 3.0, 5.0, 8.0):
                result = detour(detour_type, longitudinal_anticipation_m=anticipation,
                                longitudinal_return_m=anticipation)
                self.assertTrue(result.ok, result.messages)
                self.assertTrue(side_consistent(LINE, result.result_geometry.coords, side))

    def test_start_and_end_are_preserved_and_outside_is_untouched(self):
        result = detour()
        geometry = result.result_geometry
        self.assertEqual(geometry.coords[0], LINE.coords[0])
        self.assertEqual(geometry.coords[-1], LINE.coords[-1])
        before = LineString([(0, 0), (result.maneuver_start_station_m - 0.01, 0)])
        self.assertTrue(geometry.buffer(1e-6).covers(before))


class CutResumeTest(unittest.TestCase):
    def test_cut_resume_gap_is_zone_plus_anticipation_and_return(self):
        result = detour(DetourType.CUT_RESUME, longitudinal_anticipation_m=3.0, longitudinal_return_m=2.0)
        self.assertTrue(result.ok, result.messages)
        parts = result.result_parts
        self.assertEqual(len(parts), 2)
        self.assertAlmostEqual(result.conflict_entry_station_m, 48.5, places=2)
        self.assertAlmostEqual(result.maneuver_start_station_m, 45.5, places=2)
        self.assertAlmostEqual(result.maneuver_end_station_m, 51.5 + 2.0, places=2)
        self.assertAlmostEqual(parts[0].length, result.maneuver_start_station_m, places=6)
        self.assertEqual(validate_cut(parts, safety_zone(POST, result.parameters), 1.0), [])

    def test_cut_resume_is_width_independent_for_centered_obstacle(self):
        stations = {
            round(detour(DetourType.CUT_RESUME, implement_width_m=width).maneuver_start_station_m, 2)
            for width in (3.0, 6.0, 12.0)
        }
        self.assertEqual(stations, {45.5})

    def test_cut_resume_respects_direction(self):
        # Digitalizada 0 -> 100, percorrida 100 -> 0: a antecipacao fica do lado leste.
        result = detour(DetourType.CUT_RESUME, direction=LineDirection.B_TO_A,
                        longitudinal_anticipation_m=3.0, longitudinal_return_m=0.0)
        self.assertTrue(result.ok, result.messages)
        planted_x = sorted(x for part in result.result_parts for x, _y in part.coords)
        gap_start = max(x for x in planted_x if x < 50)
        gap_end = min(x for x in planted_x if x > 50)
        self.assertAlmostEqual(gap_start, 48.5, places=2)
        self.assertAlmostEqual(gap_end, 51.5 + 3.0, places=2)
        self.assertLess(result.result_parts[0].coords[0][0], result.result_parts[1].coords[0][0])
        for part in result.result_parts:
            self.assertLess(part.coords[0][0], part.coords[-1][0])


class SelectionAndValidationTest(unittest.TestCase):
    def test_selection_messages(self):
        self.assertEqual(selection_error(0, 1), MSG_SELECT_LINE)
        self.assertEqual(selection_error(1, 0), MSG_SELECT_OBSTACLE)
        self.assertEqual(selection_error(2, 1), MSG_SELECT_ONE_EACH)
        self.assertEqual(selection_error(1, 3), MSG_SELECT_ONE_EACH)
        self.assertIsNone(selection_error(1, 1))

    def test_v1_types_and_planned_types(self):
        self.assertEqual(
            [t.value for t in V1_DETOUR_TYPES], ["LATERAL_LEFT", "LATERAL_RIGHT", "CUT_RESUME"]
        )
        result = detour(DetourType.ARC_360)
        self.assertIs(result.status, DetourStatus.FAILED)
        self.assertTrue(any("planejado" in message for message in result.messages))

    def test_invalid_parameters_are_reported(self):
        result = detour(implement_width_m=0.0, safety_margin_m=-1.0)
        self.assertIs(result.status, DetourStatus.FAILED)
        self.assertIn("Informe a largura do implemento (m).", result.messages)
        self.assertIn("Margem de segurança não pode ser negativo.", result.messages)

    def test_obstacle_far_from_line_needs_no_detour(self):
        result = detour(obstacle=Point(50.0, 10.0))
        self.assertIs(result.status, DetourStatus.NO_CONFLICT)
        self.assertEqual(result.messages, (MSG_NO_CONFLICT,))

    def test_line_starting_inside_zone_is_rejected(self):
        result = detour(obstacle=Point(0.5, 0.0))
        self.assertIs(result.status, DetourStatus.FAILED)
        self.assertIn(MSG_ENDPOINT_INSIDE, result.messages)

    def test_validation_helpers(self):
        self.assertTrue(has_duplicate_segment([(0, 0), (1, 0), (0, 0)]))
        self.assertTrue(has_duplicate_segment([(0, 0), (0, 0), (1, 0)]))
        self.assertFalse(has_duplicate_segment([(0, 0), (1, 0), (2, 1)]))
        self.assertAlmostEqual(vertex_turns_deg([(0, 0), (1, 0), (1, 1)])[0], 90.0)
        self.assertGreater(signed_offset(LINE, (10, 2)), 0)
        self.assertLess(signed_offset(LINE, (10, -2)), 0)
        self.assertFalse(side_consistent(LINE, [(10, 1), (11, -0.5)], "LEFT"))
        self.assertTrue(crosses_to_other_side(LINE, [(10, 1), (11, -0.5)], DetourSide.LEFT))
        self.assertFalse(crosses_to_other_side(LINE, [(10, 1), (11, 0.0)], DetourSide.LEFT))
        invading = [LineString([(0, 0), (49.9, 0)])]
        self.assertIn(MSG_INVADES_ZONE, validate_cut(invading, POST.buffer(1.5), 1.0))


class ScopeTest(unittest.TestCase):
    def test_only_the_detoured_part_of_a_multipart_line_changes(self):
        far_part = LineString([(0, 30), (100, 30)])
        line = MultiLineString([list(far_part.coords), list(LINE.coords)])
        result = detour(line=line)
        self.assertTrue(result.ok, result.messages)
        parts = result.result_parts
        self.assertEqual(len(parts), 2)
        self.assertTrue(parts[0].equals_exact(far_part, 0.0))
        self.assertGreater(parts[1].length, LINE.length)

    def test_many_obstacles_and_lines_only_selected_pair_is_used(self):
        obstacles = [Point(10 + 5 * (i % 20), 3 * (i // 20) + 1.5) for i in range(100)]
        lines = [LineString([(0, 3 * k), (200, 3 * k)]) for k in range(500)]
        selected_line, selected_obstacle = lines[24], Point(120, 72)
        result = build_manual_detour(
            selected_line, selected_obstacle, params(), line_id="L0024", obstacle_id="OB-SEL"
        )
        self.assertTrue(result.ok, result.messages)
        self.assertEqual(result.obstacle_id, "OB-SEL")
        changed = box(*result.result_geometry.bounds)
        self.assertLess(changed.bounds[3], 72 + 1.5 + 1.0 + 0.5)
        self.assertEqual(len(lines), 500)
        self.assertEqual(len(obstacles), 100)
        self.assertTrue(lines[23].equals(LineString([(0, 69), (200, 69)])))
        self.assertTrue(lines[25].equals(LineString([(0, 75), (200, 75)])))


class SurroundingsWarningTest(unittest.TestCase):
    def _run(self, detour_type=DetourType.LATERAL_LEFT, nearby=(), field_area=None, **overrides):
        return build_manual_detour(
            LINE, POST, params(detour_type, **overrides), line_id="L0024", obstacle_id="OB-7",
            nearby_obstacles=nearby, field_area=field_area,
        )

    def test_other_obstacle_on_detour_side_is_warned_but_not_used(self):
        neighbour = NearbyObstacle("OB-9", Point(50.0, 4.0))
        left = self._run(nearby=[neighbour])
        self.assertTrue(left.ok, left.messages)
        self.assertEqual(left.warnings, (other_obstacle_warning(["OB-9"]),))
        alone = self._run()
        self.assertLess(left.result_geometry.hausdorff_distance(alone.result_geometry), 1e-9)
        right = self._run(DetourType.LATERAL_RIGHT, nearby=[neighbour])
        self.assertEqual(right.warnings, ())

    def test_far_obstacles_and_selected_obstacle_are_not_warned(self):
        nearby = [NearbyObstacle("OB-7", POST)] + [
            NearbyObstacle(f"OB-{i}", Point(10.0 * i, 40.0)) for i in range(10, 20)
        ]
        self.assertEqual(self._run(nearby=nearby).warnings, ())

    def test_other_obstacle_radius_attribute_is_used(self):
        small = NearbyObstacle("OB-9", Point(50.0, 6.5), radius_m=0.1)
        big = NearbyObstacle("OB-9", Point(50.0, 6.5), radius_m=3.0)
        self.assertEqual(self._run(nearby=[small]).warnings, ())
        self.assertEqual(self._run(nearby=[big]).warnings, (other_obstacle_warning(["OB-9"]),))

    def test_detour_leaving_field_is_warned(self):
        field = box(-10.0, -1.5, 110.0, 50.0)
        right = self._run(DetourType.LATERAL_RIGHT, field_area=field)
        self.assertTrue(right.ok)
        self.assertEqual(len(right.warnings), 1)
        self.assertTrue(right.warnings[0].startswith("⚠ O desvio sai do talhão ("))
        left = self._run(field_area=field)
        self.assertEqual(left.warnings, ())
        self.assertNotIn(MSG_FIELD_NOT_CHECKED, left.messages)

    def test_swath_leaving_field_is_warned_only_when_detour_adds_it(self):
        edge_field = box(-10.0, -1.0, 110.0, 50.0)
        self.assertEqual(self._run(field_area=edge_field).warnings, ())
        tight = box(-10.0, -1.0, 110.0, 2.0)
        result = self._run(field_area=tight)
        self.assertTrue(any("talhão" in warning for warning in result.warnings))
        swath_only = box(-10.0, -1.0, 110.0, 3.4)
        self.assertEqual(self._run(field_area=swath_only).warnings, (MSG_SWATH_OUTSIDE_FIELD,))

    def test_missing_field_is_reported_and_cut_resume_has_no_surroundings(self):
        self.assertIn(MSG_FIELD_NOT_CHECKED, self._run().messages)
        cut = self._run(DetourType.CUT_RESUME, nearby=[NearbyObstacle("OB-9", Point(50.0, 4.0))],
                        field_area=box(40, -0.5, 60, 0.5))
        self.assertTrue(cut.ok)
        self.assertEqual(cut.warnings, ())
        self.assertIsNone(cut.changed_geometry)

    def test_helper_and_debug_line(self):
        changed = LineString([(0, 2), (10, 2)])
        self.assertEqual(surroundings_warnings(changed, 1.0, [("A", Point(5, 2.5).buffer(0.5))]),
                         [other_obstacle_warning(["A"])])
        self.assertEqual(surroundings_warnings(None, 1.0, [("A", Point(5, 2).buffer(1))]), [])
        result = self._run(nearby=[NearbyObstacle("OB-9", Point(50.0, 4.0))])
        self.assertIn("WARNINGS: ⚠ O desvio passa pela zona de outro obstáculo: OB-9.", detour_debug_text(result))


class DebugLogTest(unittest.TestCase):
    def test_debug_block_has_required_fields(self):
        result = detour(tractor_to_implement_m=8.0)
        text = detour_debug_text(result)
        for token in (
            "=== FORTSMART OBSTACLE DETOUR ===", "LINE: L0024", "OBSTACLE: OB-7", "TYPE: LATERAL_LEFT",
            "OBSTACLE RADIUS: 1.00 m", "SAFETY MARGIN: 0.50 m", "SAFETY RADIUS: 1.50 m", "ANTICIPATION: 3.00 m",
            "RETURN: 3.00 m", "REFERENCE → OPERATION: -8.00 m", "LINE DIRECTION: A_TO_B", "RESULT: OK",
        ):
            self.assertIn(token, text)

    def test_debug_block_is_logged(self):
        with self.assertLogs("fortsmart_precision.obstacle_detour", level=logging.INFO) as captured:
            detour()
        self.assertTrue(any("=== FORTSMART OBSTACLE DETOUR ===" in line for line in captured.output))

    def test_record_attributes_have_required_fields(self):
        result = detour(tractor_to_implement_m=8.0)
        attributes = result.record_attributes("2026-10-04T10:00:00")
        self.assertEqual(
            set(attributes),
            {
                "detour_id", "line_id", "obstacle_id", "detour_type", "side", "obstacle_radius_m",
                "safety_margin_m", "anticipation_m", "return_m", "reference_to_operation_m", "created_at",
            },
        )
        self.assertEqual(attributes["reference_to_operation_m"], -8.0)
        self.assertTrue(attributes["detour_id"].startswith("DV-"))
        self.assertTrue(math.isclose(attributes["safety_margin_m"], 0.5))
        self.assertEqual(replace(result.parameters, safety_margin_m=1.0).safety_radius_m, 2.0)


if __name__ == "__main__":
    unittest.main()
