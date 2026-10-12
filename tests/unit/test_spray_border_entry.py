# -*- coding: utf-8 -*-
"""Fase 2 — entra e sai pela linha real da bordadura (em memoria)."""

from __future__ import annotations

import math
import unittest

from shapely.geometry import LineString, Polygon
from shapely.geometry import Point as ShapelyPoint

from plugin.fortsmart_precision.core.spray_border_entry import (
    ENTRY_ANTICIPATION_M,
    EXIT_LEAD_M,
    INFEASIBLE_MESSAGE,
    STATUS_BLOCKED_U_TURN,
    STATUS_INFEASIBLE,
    STATUS_NOT_VALIDATED,
    TURN_TYPE,
    BorderEntrySettings,
    HeadlandRingInput,
    SprayPassInput,
    border_entry_summary,
    border_entry_connection_summary,
    outermost_headland_ring,
    plan_spray_border_entries,
)
from plugin.fortsmart_precision.core.spray_headland_turns import plan_spray_headland_turns
from plugin.fortsmart_precision.domain.precision_project import SPRAY_HEADLAND_TURN_MANUAL
from tests.unit.test_spray_headland_regression_baseline import build_project, summary
from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines


def _rect_ring(x0, y0, x1, y1, n_curve=0):
    pts = [(x0, y0), (x1, y0), (x1, y1)]
    if n_curve > 0:
        for i in range(1, n_curve):
            t = i / n_curve
            x = x1 + (x0 - x1) * t
            pts.append((x, y1 + 12.0 * math.sin(math.pi * t)))
    pts.extend([(x0, y1), (x0, y0)])
    return tuple(pts)


def _pair(x_a=20.0, x_b=40.0, y0=-10.0, y1=90.0, ring=None):
    ring = ring or _rect_ring(0.0, 0.0, 100.0, 80.0)
    return (
        SprayPassInput(1, ((x_a, y0), (x_a, y1)), "forward", "L0001"),
        SprayPassInput(2, ((x_b, y0), (x_b, y1)), "reverse", "L0002"),
        HeadlandRingInput(0, 10.0, ring, "B1"),
    )


def _first_ok(plan):
    accepted = plan.accepted
    assert accepted, plan.report | {"warnings": plan.warnings}
    return accepted[0]


class OutermostRingTest(unittest.TestCase):
    def test_picks_smallest_offset(self):
        rings = (
            HeadlandRingInput(1, 45.0, ((0, 0), (1, 0))),
            HeadlandRingInput(0, 10.0, ((0, 0), (2, 0))),
            HeadlandRingInput(2, 80.0, ((0, 0), (3, 0))),
        )
        ring = outermost_headland_ring(rings)
        self.assertEqual(ring.pass_no, 0)
        self.assertEqual(ring.offset_m, 10.0)


class StraightHeadlandPairTest(unittest.TestCase):
    def test_t01_t03_t04_t05_continuous_with_measured_leads(self):
        a, b, ring = _pair()
        plan = plan_spray_border_entries((a, b), (ring,))
        conn = _first_ok(plan)
        self.assertEqual(conn.status, STATUS_NOT_VALIDATED)
        self.assertAlmostEqual(conn.exit_lead_m, EXIT_LEAD_M, places=2)
        self.assertAlmostEqual(conn.entry_lead_m, ENTRY_ANTICIPATION_M, places=2)
        self.assertGreater(conn.align_m, 0.0)
        self.assertGreaterEqual(len(conn.exit_points), 2)
        self.assertGreaterEqual(len(conn.transit_points), 2)
        self.assertGreaterEqual(len(conn.entry_points), 2)
        self.assertGreater(conn.transit_length_m, 0.0)
        self.assertGreaterEqual(len(conn.points), 4)
        path = LineString(conn.points)
        self.assertTrue(path.is_simple)
        ring_line = LineString(ring.points)
        self.assertIsNotNone(conn.b)
        self.assertLess(ring_line.distance(ShapelyPoint(*conn.b)), 0.05)
        self.assertLess(ring_line.distance(ShapelyPoint(*conn.d)), 0.05)
        self.assertLess(path.distance(ShapelyPoint(*conn.a)), 0.05)
        self.assertLess(path.distance(ShapelyPoint(*conn.e)), 0.05)

    def test_t03_exit_is_exactly_7m_along_pass(self):
        a, b, ring = _pair()
        conn = _first_ok(plan_spray_border_entries((a, b), (ring,)))
        pass_line = LineString(a.points)
        crossing = pass_line.project(ShapelyPoint(*conn.b))
        self.assertAlmostEqual(pass_line.project(ShapelyPoint(*conn.a)), crossing - EXIT_LEAD_M, places=2)

    def test_t06_does_not_cross_outside_the_ring(self):
        a, b, ring = _pair()
        conn = _first_ok(plan_spray_border_entries((a, b), (ring,)))
        interior = Polygon(_rect_ring(0.0, 0.0, 100.0, 80.0))
        self.assertTrue(interior.buffer(0.05).covers(LineString(conn.points)))

    def test_g1_at_a_b_d_e(self):
        a, b, ring = _pair()
        conn = _first_ok(plan_spray_border_entries((a, b), (ring,)))
        heads = [
            math.atan2(q[1] - p[1], q[0] - p[0])
            for p, q in zip(conn.points, conn.points[1:])
            if math.dist(p, q) > 1e-9
        ]
        jumps = [
            abs((h2 - h1 + math.pi) % (2 * math.pi) - math.pi)
            for h1, h2 in zip(heads, heads[1:])
        ]
        self.assertLess(max(math.degrees(j) for j in jumps), 25.0)

    def test_t08_registered_radius_does_not_force_curve(self):
        a, b, ring = _pair()
        plan = plan_spray_border_entries(
            (a, b), (ring,), settings=BorderEntrySettings(min_turn_radius_m=8.0)
        )
        self.assertEqual(plan.report["accepted_count"], 0)
        self.assertEqual(plan.rejected[0].status, STATUS_INFEASIBLE)
        self.assertIn(INFEASIBLE_MESSAGE, plan.rejected[0].message)
        self.assertEqual(plan.rejected[0].points, ())

    def test_blocked_when_u_turns_active(self):
        a, b, ring = _pair()
        plan = plan_spray_border_entries((a, b), (ring,), u_turns_active=True)
        self.assertEqual(plan.report["status"], STATUS_BLOCKED_U_TURN)
        self.assertEqual(plan.accepted, ())
        self.assertIn("manobra automatica", border_entry_summary(plan).lower())

    def test_t09_non_adjacent_and_missing_crossing(self):
        a, _b, ring = _pair()
        c = SprayPassInput(3, ((80.0, -10.0), (80.0, 90.0)), "forward", "L0003")
        plan = plan_spray_border_entries((a, c), (ring,))
        self.assertEqual(plan.rejected[0].status, STATUS_INFEASIBLE)
        self.assertIn("nao adjacentes", plan.rejected[0].message)

        short = SprayPassInput(1, ((20.0, 20.0), (20.0, 40.0)), "forward", "L0001")
        other = SprayPassInput(2, ((40.0, 20.0), (40.0, 40.0)), "reverse", "L0002")
        plan = plan_spray_border_entries((short, other), (ring,))
        self.assertEqual(plan.rejected[0].status, STATUS_INFEASIBLE)
        self.assertIn(INFEASIBLE_MESSAGE, plan.rejected[0].message)

    def test_does_not_call_u_turn_engine(self):
        a, b, ring = _pair()
        plan = plan_spray_border_entries((a, b), (ring,))
        self.assertFalse(plan.report["generator_called"])
        self.assertFalse(plan.report["passes_modified"])
        self.assertFalse(plan.report["persisted"])
        self.assertEqual(plan.accepted[0].attributes()["turn_type"], TURN_TYPE)


class CurvedHeadlandTest(unittest.TestCase):
    def test_t02_transit_follows_real_geometry_not_chord(self):
        ring_pts = _rect_ring(0.0, 0.0, 100.0, 80.0, n_curve=16)
        a, b, ring = _pair(y0=-10.0, y1=110.0, ring=ring_pts)
        conn = _first_ok(plan_spray_border_entries((a, b), (ring,)))
        ring_line = LineString(ring.points)
        chord = LineString([conn.b, conn.d])
        samples = [
            ring_line.interpolate(ring_line.project(ShapelyPoint(*pt)))
            for pt in conn.points
            if ring_line.distance(ShapelyPoint(*pt)) < 0.2
        ]
        self.assertGreater(len(samples), 3)
        path_on_ring = LineString([(p.x, p.y) for p in samples])
        self.assertGreater(path_on_ring.length, chord.length + 0.3)
        transit = LineString(conn.transit_points)
        self.assertTrue(ring_line.buffer(0.05).covers(transit))
        self.assertAlmostEqual(transit.length, conn.transit_length_m, places=3)
        self.assertGreater(len(conn.transit_points), 3)
        self.assertFalse(transit.equals(chord))

    def test_t09_diagnostic_records_source_stations_and_real_substring(self):
        ring_pts = _rect_ring(0.0, 0.0, 100.0, 80.0, n_curve=16)
        a, b, ring = _pair(y0=-10.0, y1=110.0, ring=ring_pts)
        plan = plan_spray_border_entries((a, b), (ring,))
        conn = _first_ok(plan)
        diagnostic = conn.diagnostic()
        self.assertEqual(diagnostic["turn_type"], TURN_TYPE)
        self.assertEqual(diagnostic["headland_line_id"], "B1")
        self.assertTrue(diagnostic["uses_real_headland_substring"])
        self.assertGreater(diagnostic["transit_length_m"], 0.0)
        for station in ("a_station_m", "b_station_m", "d_station_m", "e_station_m"):
            self.assertIsNotNone(diagnostic[station])
        self.assertEqual(plan.report["connections"][0], diagnostic)
        self.assertLessEqual(diagnostic["max_transit_distance_m"], 0.05)
        self.assertLessEqual(max(diagnostic["tangent_error_deg"].values()), 2.0)
        text = border_entry_connection_summary(conn)
        for token in ("L0001", "L0002", "B1", "A=(", "B=(", "D=(", "E=(", "B-D="):
            self.assertIn(token, text)

    def test_closed_irregular_headland_with_incompatible_angles_is_not_forced(self):
        ring = HeadlandRingInput(
            0,
            10.0,
            ((0, 0), (105, 0), (112, 45), (96, 86), (48, 94), (0, 80), (0, 0)),
            "B_IRREGULAR",
        )
        first = SprayPassInput(1, ((18, -8), (31, 105)), "forward", "SPRAY_01")
        second = SprayPassInput(2, ((44, -8), (63, 105)), "reverse", "SPRAY_02")
        plan = plan_spray_border_entries((first, second), (ring,))
        self.assertEqual(plan.accepted, ())
        self.assertEqual(plan.rejected[0].headland_line_id, "B_IRREGULAR")
        self.assertEqual(plan.rejected[0].status, STATUS_INFEASIBLE)
        self.assertEqual(plan.rejected[0].points, ())
        self.assertIn("Manobra inviavel", plan.rejected[0].message)

    def test_oblique_a7_a8_use_exact_7m_references(self):
        ring = HeadlandRingInput(
            0, 10.0, ((0, 0), (100, 0), (100, 80), (0, 80), (0, 0)), "B1"
        )
        a7 = SprayPassInput(7, ((20, -10), (10, 100)), "forward", "A7")
        a8 = SprayPassInput(8, ((40, -10), (35, 100)), "reverse", "A8")
        conn = _first_ok(plan_spray_border_entries((a7, a8), (ring,)))
        self.assertEqual((conn.from_line_id, conn.headland_line_id, conn.to_line_id), ("A7", "B1", "A8"))
        self.assertAlmostEqual(conn.exit_lead_m, 7.0, places=3)
        self.assertAlmostEqual(conn.entry_lead_m, 7.0, places=3)
        self.assertGreater(conn.align_m, 0.0)
        self.assertLessEqual(conn.max_transit_distance_m, 0.05)


class GeneratorRegressionTest(unittest.TestCase):
    def test_t12_default_generation_unchanged_and_manual_headland(self):
        project = build_project("spray_default")
        self.assertEqual(project.spray_headland_turn_mode, SPRAY_HEADLAND_TURN_MANUAL)
        result = run_precision_lines(project)
        self.assertIsNone(result.spray_headland_turns)
        snap = summary(result)
        self.assertGreater(snap["passes"]["count"], 2)
        ring = outermost_headland_ring(
            HeadlandRingInput(line.pass_no, line.offset_from_outer_m, line.line_points())
            for line in result.spraying_boundary.headland_centerlines
        )
        self.assertIsNotNone(ring)
        passes = [
            SprayPassInput(p.pass_no, p.line_points(), p.direction, p.fs_id)
            for p in result.spraying_passes
        ]
        plan = plan_spray_border_entries(passes, (ring,))
        self.assertGreaterEqual(plan.report["possible_count"], 1)
        self.assertEqual(len(result.spraying_passes), snap["passes"]["count"])
        u = plan_spray_headland_turns(
            result.spraying_passes,
            work_area=None,
            operational_area=project.field.operational_boundary,
            radius_m=8.0,
            clearance_m=1.0,
        )
        self.assertTrue(u.turns or u.warnings)
        blocked = plan_spray_border_entries(passes, (ring,), u_turns_active=True)
        self.assertEqual(blocked.report["status"], STATUS_BLOCKED_U_TURN)


if __name__ == "__main__":
    unittest.main()
