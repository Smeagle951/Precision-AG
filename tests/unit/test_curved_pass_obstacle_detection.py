# -*- coding: utf-8 -*-
"""Obstaculos em passada CURVA nao podem ser filtrados pela corda start→end."""

from __future__ import annotations

import math
import unittest

from plugin.fortsmart_precision.core.application_obstacle_engine import (
    _envelopes_near_pass,
    apply_application_obstacle_avoidance,
)
from plugin.fortsmart_precision.core.guidance_engine import TrafficPass
from plugin.fortsmart_precision.core.line_geometry import Segment, distance
from plugin.fortsmart_precision.core.obstacle_buffer_engine import build_all_envelopes
from plugin.fortsmart_precision.core.tire_track_engine import generate_tire_tracks
from plugin.fortsmart_precision.domain.avoidance_configuration import (
    AvoidanceConfiguration,
    AvoidanceMode,
)
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, SprayerMachine
from plugin.fortsmart_precision.domain.obstacle_model import obstacle_from_point


def _quarter_circle_pass(radius: float = 120.0, n: int = 25) -> list[tuple[float, float]]:
    return [
        (radius * math.cos(math.pi * i / (2 * (n - 1))), radius * math.sin(math.pi * i / (2 * (n - 1))))
        for i in range(n)
    ]


class CurvedPassEnvelopeFilterTest(unittest.TestCase):
    def test_obstacle_on_arc_is_not_filtered_by_chord(self):
        pts = _quarter_circle_pass()
        mid = pts[len(pts) // 2]
        # Distancia a corda e grande; a polilinha passa em cima do ponto.
        chord = Segment(pts[0], pts[-1])
        ax, ay = chord.start
        bx, by = chord.end
        dx, dy = bx - ax, by - ay
        t = ((mid[0] - ax) * dx + (mid[1] - ay) * dy) / (dx * dx + dy * dy)
        proj = (ax + t * dx, ay + t * dy)
        self.assertGreater(distance(mid, proj), 25.0)

        sprayer = SprayerMachine(
            machine_id="s36",
            name="36m",
            nozzle_count=72,
            nozzle_spacing_m=0.5,
            boom_width_m=36.0,
            track=MachineTrack(track_width_m=3.0, tire_width_m=0.4),
        )
        obs = obstacle_from_point(mid, obstacle_radius_m=0.5, safety_margin_m=0.5)
        envelopes = build_all_envelopes([obs], sprayer)
        near = _envelopes_near_pass(
            chord,
            envelopes,
            sprayer,
            path_points=pts,
        )
        self.assertEqual(len(near), 1, "obstaculo no arco deve ser candidato")

    def test_spray_avoidance_on_curved_pass_creates_detour(self):
        pts = _quarter_circle_pass()
        mid = pts[len(pts) // 2]
        sprayer = SprayerMachine(
            machine_id="s36",
            name="36m",
            nozzle_count=72,
            nozzle_spacing_m=0.5,
            boom_width_m=36.0,
            track=MachineTrack(track_width_m=3.0, tire_width_m=0.4),
        )
        obs = obstacle_from_point(mid, obstacle_radius_m=0.5, safety_margin_m=0.5)
        item = TrafficPass(
            pass_no=0,
            fs_id="c0",
            operation_id="spraying",
            spacing_m=36.0,
            width_m=36.0,
            offset_m=0.0,
            azimuth_deg=0.0,
            direction="forward",
            clipped_segment=Segment(pts[0], pts[-1]),
            guidance_segment=Segment(pts[0], pts[-1]),
            path_points=tuple(pts),
        )
        modified, avoided = apply_application_obstacle_avoidance(
            [item],
            [obs],
            sprayer,
            AvoidanceConfiguration(mode=AvoidanceMode.CONCENTRIC_RING, minimum_turn_radius_m=8.0),
        )
        self.assertGreater(len(avoided), 0, "desvio nao pode ser ignorado na curva")
        path = list(modified[0].line_points())
        closest = min(distance(p, mid) for p in path)
        self.assertGreaterEqual(closest, sprayer.half_operational_width_m - 0.5)


class TireTrackFollowsDetourTest(unittest.TestCase):
    def test_tire_tracks_preserve_circular_detour_vertices(self):
        # Passada com arco denso: decimacao antiga (4 m) destruia a curva.
        center = (50.0, 0.0)
        radius = 12.0
        arc = [
            (center[0] + radius * math.cos(math.pi * i / 24), center[1] + radius * math.sin(math.pi * i / 24))
            for i in range(25)
        ]
        pts = [(0.0, 0.0)] + arc + [(100.0, 0.0)]
        item = TrafficPass(
            pass_no=1,
            fs_id="t1",
            operation_id="spraying",
            spacing_m=36.0,
            width_m=36.0,
            offset_m=0.0,
            azimuth_deg=0.0,
            direction="forward",
            clipped_segment=Segment(pts[0], pts[-1]),
            guidance_segment=Segment(pts[0], pts[-1]),
            path_points=tuple(pts),
        )
        tracks = generate_tire_tracks([item], track_width_m=3.0, tire_width_m=0.4)
        self.assertEqual(len(tracks), 2)
        left = tracks[0].points
        # Arco deve sobreviver: muitos pontos com |y| relevante.
        arched = [p for p in left if abs(p[1]) > 3.0]
        self.assertGreater(len(arched), 8, "rastro nao pode virar corda reta")


if __name__ == "__main__":
    unittest.main()
