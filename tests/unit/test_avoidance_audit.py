# -*- coding: utf-8 -*-
"""Auditoria do desvio: raio operacional e clearance da ponta do implemento."""

from __future__ import annotations

import math
import unittest

from plugin.fortsmart_precision.core.avoidance_audit_engine import (
    audit_table,
    build_avoidance_audit,
)
from plugin.fortsmart_precision.core.line_geometry import Segment, circle_arc_polyline
from plugin.fortsmart_precision.core.obstacle_engine import AvoidedPath
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, SprayerMachine
from plugin.fortsmart_precision.domain.obstacle_model import obstacle_from_point


def _sprayer_36() -> SprayerMachine:
    return SprayerMachine(
        machine_id="s36",
        name="Barra 36",
        nozzle_count=72,
        nozzle_spacing_m=0.5,
        boom_width_m=36.0,
        track=MachineTrack(track_width_m=3.0, tire_width_m=0.37),
    )


def _avoided(points, obstacle_id: str) -> AvoidedPath:
    return AvoidedPath(
        fs_id="a1",
        source_id="p1",
        pass_id=3,
        row_id=None,
        operation_id="spraying",
        machine_id="s36",
        original_segment=Segment(points[0], points[-1]),
        modified_points=tuple(points),
        entry_point=points[0],
        exit_point=points[-1],
        obstacle_id=obstacle_id,
        application_radius_m=18.5,
        action="ring",
        returns_to_guidance=True,
    )


class OperationalRadiusTest(unittest.TestCase):
    def test_radius_follows_boom_width_not_hardcoded(self):
        sprayer = _sprayer_36()
        obstacle = obstacle_from_point((50.0, 0.0), obstacle_radius_m=1.0, safety_margin_m=0.5)
        audit = build_avoidance_audit(
            operation_id="spraying",
            machine=sprayer,
            obstacles=[obstacle],
            avoided_paths=[],
            safety_margin_m=0.5,
        )
        self.assertAlmostEqual(audit.half_width_m, 18.0, places=3)
        self.assertAlmostEqual(audit.operational_radius_m, 1.0 + 18.0 + 0.5, places=3)

    def test_half_width_tracks_machine(self):
        for boom, expected in ((24.0, 12.0), (30.0, 15.0), (36.05, 18.025)):
            with self.subTest(boom=boom):
                machine = SprayerMachine(
                    machine_id="s",
                    name=f"barra {boom}",
                    nozzle_count=60,
                    nozzle_spacing_m=0.5,
                    boom_width_m=boom,
                    track=MachineTrack(track_width_m=3.0, tire_width_m=0.37),
                )
                audit = build_avoidance_audit(
                    operation_id="spraying",
                    machine=machine,
                    obstacles=[],
                    avoided_paths=[],
                    safety_margin_m=0.0,
                )
                self.assertAlmostEqual(audit.half_width_m, expected, places=3)


class ClearanceTest(unittest.TestCase):
    def test_safe_arc_reports_positive_clearance(self):
        sprayer = _sprayer_36()
        obstacle = obstacle_from_point((50.0, 0.0), obstacle_radius_m=1.0, safety_margin_m=0.5)
        radius = sprayer.half_operational_width_m + 1.0 + 2.0
        arc = circle_arc_polyline((50.0, 0.0), radius, math.pi, -math.pi, segments=48)
        points = [(0.0, 0.0)] + list(arc) + [(100.0, 0.0)]
        audit = build_avoidance_audit(
            operation_id="spraying",
            machine=sprayer,
            obstacles=[obstacle],
            avoided_paths=[_avoided(points, obstacle.obstacle_id)],
            safety_margin_m=0.5,
        )
        self.assertEqual(audit.deviation_count, 1)
        self.assertEqual(audit.affected_pass_count, 1)
        self.assertIsNotNone(audit.min_clearance_m)
        self.assertGreater(audit.min_clearance_m, 0.0)
        self.assertTrue(audit.ok)

    def test_path_through_obstacle_flags_negative_clearance(self):
        sprayer = _sprayer_36()
        obstacle = obstacle_from_point((50.0, 0.0), obstacle_radius_m=1.0, safety_margin_m=0.5)
        points = [(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)]
        audit = build_avoidance_audit(
            operation_id="spraying",
            machine=sprayer,
            obstacles=[obstacle],
            avoided_paths=[_avoided(points, obstacle.obstacle_id)],
            safety_margin_m=0.5,
        )
        self.assertFalse(audit.ok)
        self.assertLess(audit.min_clearance_m, 0.0)
        table = audit_table(audit)
        self.assertEqual(table[0]["status"], "SEM FOLGA")

    def test_rows_are_renderable(self):
        sprayer = _sprayer_36()
        audit = build_avoidance_audit(
            operation_id="spraying",
            machine=sprayer,
            obstacles=[],
            avoided_paths=[],
            safety_margin_m=0.5,
            minimum_turn_radius_m=12.0,
            extension_m=10.0,
        )
        labels = [label for label, _ in audit.rows()]
        self.assertIn("Raio operacional", labels)
        self.assertIn("Clearance minimo", labels)
        self.assertIn("Passadas afetadas", labels)
        self.assertIn("Situacao", audit.summary_text())


if __name__ == "__main__":
    unittest.main()
