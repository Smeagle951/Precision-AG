# -*- coding: utf-8 -*-
"""Pulverizacao: orbita 360° em obstaculo circular + folga = W/2 + margem."""

from __future__ import annotations

import math
import unittest

from plugin.fortsmart_precision.core.application_obstacle_engine import (
    apply_application_obstacle_avoidance,
)
from plugin.fortsmart_precision.core.guidance_engine import TrafficPass
from plugin.fortsmart_precision.core.line_geometry import Segment, distance, polyline_length
from plugin.fortsmart_precision.core.obstacle_buffer_engine import build_application_envelope
from plugin.fortsmart_precision.core.obstacle_contour_path import circular_orbit_360_path
from plugin.fortsmart_precision.core.tire_track_engine import generate_tire_tracks
from plugin.fortsmart_precision.domain.avoidance_configuration import (
    AvoidanceConfiguration,
    AvoidanceMode,
)
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, SprayerMachine
from plugin.fortsmart_precision.domain.obstacle_model import obstacle_from_point


def _sprayer_20m() -> SprayerMachine:
    return SprayerMachine(
        machine_id="s20",
        name="20m",
        nozzle_count=40,
        nozzle_spacing_m=0.5,
        boom_width_m=20.0,
        track=MachineTrack(track_width_m=3.0, tire_width_m=0.4),
    )


def _pass_through(y: float = 100.0) -> TrafficPass:
    segment = Segment((0.0, y), (400.0, y))
    return TrafficPass(
        pass_no=0,
        fs_id="s0",
        operation_id="spraying",
        spacing_m=20.0,
        width_m=20.0,
        offset_m=0.0,
        azimuth_deg=0.0,
        direction="forward",
        clipped_segment=segment,
        guidance_segment=segment,
    )


def _winding_turns(path, center) -> float:
    """Voltas acumuladas em torno do centro (1.0 ~= 360°)."""
    if len(path) < 3:
        return 0.0
    total = 0.0
    prev = math.atan2(path[0][1] - center[1], path[0][0] - center[0])
    for pt in path[1:]:
        ang = math.atan2(pt[1] - center[1], pt[0] - center[0])
        delta = ang - prev
        while delta > math.pi:
            delta -= 2.0 * math.pi
        while delta < -math.pi:
            delta += 2.0 * math.pi
        total += delta
        prev = ang
    return abs(total) / (2.0 * math.pi)


class SprayClearanceHalfWidthTest(unittest.TestCase):
    def test_center_stays_at_half_boom_plus_margin(self):
        sprayer = _sprayer_20m()
        obs = obstacle_from_point(
            (200.0, 100.0), obstacle_radius_m=0.5, safety_margin_m=0.5
        )
        envelope = build_application_envelope(obs, sprayer)
        nominal = envelope.application_radius_m
        self.assertAlmostEqual(nominal, 11.0, places=3)

        modified, avoided = apply_application_obstacle_avoidance(
            [_pass_through()],
            [obs],
            sprayer,
            AvoidanceConfiguration(
                mode=AvoidanceMode.CONCENTRIC_RING,
                minimum_turn_radius_m=8.0,
                orbit_360=True,
            ),
        )
        self.assertGreater(len(avoided), 0)
        path = list(modified[0].line_points())
        min_center = min(distance(p, obs.center) for p in path)
        self.assertGreaterEqual(min_center, nominal - 0.75)
        self.assertLess(
            min_center,
            sprayer.operational_width_m + 1.0,
            "nao usar largura inteira (20 m) como folga do centro",
        )


class SprayOrbit360Test(unittest.TestCase):
    def test_orbit_completes_nearly_full_turn(self):
        segment = Segment((0.0, 100.0), (400.0, 100.0))
        center = (200.0, 100.0)
        radius = 11.0
        path = circular_orbit_360_path(
            segment, center, radius, turn_radius_m=8.0, segments=96
        )
        self.assertIsNotNone(path)
        turns = _winding_turns(path, center)
        self.assertGreaterEqual(turns, 0.95, "deve completar ~360° ao redor do obstaculo")
        self.assertLess(distance(path[0], segment.start), 1.0)
        self.assertLess(distance(path[-1], segment.end), 1.0)
        # Comprimento do miolo deve cobrir pelo menos uma circunferencia.
        self.assertGreater(polyline_length(path), 2.0 * math.pi * radius * 0.85)

    def test_pipeline_orbit_and_tire_tracks_follow(self):
        sprayer = _sprayer_20m()
        obs = obstacle_from_point(
            (200.0, 100.0), obstacle_radius_m=0.5, safety_margin_m=0.5
        )
        modified, avoided = apply_application_obstacle_avoidance(
            [_pass_through()],
            [obs],
            sprayer,
            AvoidanceConfiguration(
                mode=AvoidanceMode.CONCENTRIC_RING,
                minimum_turn_radius_m=8.0,
                orbit_360=True,
            ),
        )
        self.assertEqual(len(avoided), 1)
        path = list(modified[0].line_points())
        turns = _winding_turns(path, obs.center)
        self.assertGreaterEqual(turns, 0.95)

        tracks = generate_tire_tracks(
            modified, track_width_m=3.0, tire_width_m=0.4
        )
        self.assertGreater(len(tracks), 0)
        # Rastro acompanha a orbita (nao corda reta).
        track_pts = list(tracks[0].points)
        track_turns = _winding_turns(track_pts, obs.center)
        self.assertGreaterEqual(
            track_turns, 0.7, "rastro de pneu deve seguir a volta do pulverizador"
        )


class SprayOrbitPreservesPassLengthTest(unittest.TestCase):
    def test_orbit_near_edge_does_not_erase_pass(self):
        """Clip da orbita nao pode reduzir a passada a um arco curto."""
        from plugin.fortsmart_precision.core.line_geometry import polyline_length

        sprayer = _sprayer_20m()
        # Poste perto da borda sul: metade da orbita sai do talhao.
        field = [([(0.0, 0.0), (400.0, 0.0), (400.0, 200.0), (0.0, 200.0), (0.0, 0.0)], [])]
        obs = obstacle_from_point(
            (200.0, 5.0), obstacle_radius_m=0.5, safety_margin_m=0.5
        )
        item = _pass_through(y=5.0)
        original_len = polyline_length(item.line_points())
        modified, avoided = apply_application_obstacle_avoidance(
            [item],
            [obs],
            sprayer,
            AvoidanceConfiguration(
                mode=AvoidanceMode.CONCENTRIC_RING,
                minimum_turn_radius_m=8.0,
                orbit_360=True,
            ),
            allowed_area=field,
        )
        self.assertEqual(len(modified), 1)
        new_len = polyline_length(modified[0].line_points())
        self.assertGreaterEqual(
            new_len,
            0.55 * original_len,
            "passada nao pode virar so o arco do obstaculo",
        )
        self.assertLess(distance(modified[0].line_points()[0], item.line_points()[0]), 5.0)
        self.assertLess(distance(modified[0].line_points()[-1], item.line_points()[-1]), 5.0)


if __name__ == "__main__":
    unittest.main()
