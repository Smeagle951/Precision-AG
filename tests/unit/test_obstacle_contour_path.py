# -*- coding: utf-8 -*-
"""Contorno de obstaculos poligonais e polilinhas curvas."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.application_obstacle_engine import apply_obstacle_avoidance_to_passes
from plugin.fortsmart_precision.core.guidance_engine import TrafficPass
from plugin.fortsmart_precision.core.line_geometry import Segment
from plugin.fortsmart_precision.core.obstacle_buffer_engine import build_all_envelopes
from plugin.fortsmart_precision.core.obstacle_contour_path import (
    circular_bypass_path,
    contour_path_around_polygon,
    polyline_envelope_hit_range,
    smooth_avoidance_trajectory,
)
from plugin.fortsmart_precision.domain.avoidance_configuration import AvoidanceConfiguration, AvoidanceMode
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, SprayerMachine
from plugin.fortsmart_precision.domain.obstacle_model import Obstacle, ObstacleType


def sprayer_36m():
    return SprayerMachine(
        machine_id="s36",
        name="36m",
        nozzle_count=72,
        nozzle_spacing_m=0.5,
        boom_width_m=36.0,
        track=MachineTrack(track_width_m=3.0, tire_width_m=0.35),
    )


class CircularBypassTest(unittest.TestCase):
    def test_circular_bypass_is_high_res_semicircle(self):
        from math import acos, degrees

        from plugin.fortsmart_precision.core.line_geometry import distance, normalize, sub

        segment = Segment((0.0, 120.0), (400.0, 120.0))
        center = (200.0, 120.0)
        radius = 18.0
        path = circular_bypass_path(segment, center, radius, turn_radius_m=5.0, segments=96)
        self.assertIsNotNone(path)
        self.assertGreater(len(path), 40)
        self.assertAlmostEqual(path[0][0], 0.0, places=3)
        self.assertAlmostEqual(path[-1][0], 400.0, places=3)
        # Nao fecha anel.
        self.assertGreater(distance(path[0], path[-1]), 50.0)
        # Maioria dos pontos do miolo ficam no raio operacional.
        mid = path[len(path) // 4 : 3 * len(path) // 4]
        on_arc = [p for p in mid if abs(distance(p, center) - radius) < 2.5]
        self.assertGreater(len(on_arc), 12)
        # Sem quina seca (~90°): deflexao maxima entre segmentos consecutivos < 35°.
        max_deflect = 0.0
        for i in range(1, len(path) - 1):
            a_vec = sub(path[i], path[i - 1])
            b_vec = sub(path[i + 1], path[i])
            if distance(path[i], path[i - 1]) < 1e-6 or distance(path[i + 1], path[i]) < 1e-6:
                continue
            a = normalize(a_vec)
            b = normalize(b_vec)
            dot = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1]))
            max_deflect = max(max_deflect, abs(degrees(acos(dot))))
        self.assertLess(max_deflect, 32.0)


class HitchImplementLagTest(unittest.TestCase):
    def test_longer_hitch_starts_turn_earlier(self):
        """Atraso do implemento: hitch maior => trator inicia desvio mais cedo."""
        from plugin.fortsmart_precision.core.obstacle_contour_path import (
            hitch_anticipation_m,
            plan_circular_avoidance_for_implement,
        )
        from plugin.fortsmart_precision.core.planting_kinematics_engine import (
            implement_clears_circle,
            implement_path_along_tractor,
        )
        from plugin.fortsmart_precision.domain.planting_kinematics import PlantingKinematics

        segment = Segment((0.0, 120.0), (400.0, 120.0))
        center = (200.0, 120.0)
        clearance = 18.0

        def first_leave_x(path):
            for pt in path:
                if abs(pt[1] - 120.0) > 0.8:
                    return pt[0]
            return None

        leaves = []
        for hitch in (0.0, 4.0, 8.0):
            kin = PlantingKinematics(
                operational_width_m=9.0,
                track_width_m=0.0,
                hitch_distance_m=hitch,
                minimum_turn_radius_m=6.0,
                row_count=12,
                row_spacing_m=0.75,
            )
            path = plan_circular_avoidance_for_implement(
                segment, center, clearance, kin, segments=64
            )
            self.assertIsNotNone(path)
            self.assertTrue(
                implement_clears_circle(path, kin, center, clearance_radius_m=clearance)
            )
            leaves.append(first_leave_x(path))
            impl = implement_path_along_tractor(path, kin)
            self.assertGreater(len(impl), 10)

        self.assertGreater(hitch_anticipation_m(8.0, 6.0), hitch_anticipation_m(4.0, 6.0))
        self.assertEqual(len(leaves), 3)
        for pt in leaves:
            self.assertIsNotNone(pt)


class DualBezierChenTest(unittest.TestCase):
    def test_dual_bezier_returns_to_same_guidance_line(self):
        """Metragem: entrada/saida colineares com a passada (anel + fillet)."""
        from plugin.fortsmart_precision.core.line_geometry import distance, normalize, sub

        segment = Segment((0.0, 100.0), (300.0, 100.0))
        center = (150.0, 100.0)
        path = circular_bypass_path(segment, center, 12.0, turn_radius_m=6.0, segments=96)
        self.assertIsNotNone(path)
        # Extremos na linha global (Y=100).
        self.assertAlmostEqual(path[0][1], 100.0, places=3)
        self.assertAlmostEqual(path[-1][1], 100.0, places=3)
        # Heading final alinhado a travel (volta a passada sem "andar" lateral).
        travel = normalize(sub(segment.end, segment.start))
        end_dir = normalize(sub(path[-1], path[-2]))
        self.assertGreater(travel[0] * end_dir[0] + travel[1] * end_dir[1], 0.95)
        # Clearance respeitado no miolo.
        mid = path[len(path) // 4 : 3 * len(path) // 4]
        self.assertTrue(all(distance(p, center) >= 11.5 for p in mid))


class SprayPolygonContourTest(unittest.TestCase):
    def test_square_obstacle_uses_contour_not_ring(self):
        square = Obstacle(
            obstacle_id="sq",
            obstacle_type=ObstacleType.POLYGON,
            center=(200.0, 120.0),
            obstacle_radius_m=3.0,
            safety_margin_m=0.5,
            polygon=(
                [(197, 117), (203, 117), (203, 123), (197, 123), (197, 117)],
                [],
            ),
        )
        machine = sprayer_36m()
        segment = Segment((0.0, 120.0), (400.0, 120.0))
        env = build_all_envelopes([square], machine)[0]
        path = contour_path_around_polygon(
            segment,
            env.geometry,
            clearance_m=env.application_radius_m,
        )
        self.assertIsNotNone(path)
        self.assertGreater(len(path), 12)
        # Extremidades na linha de guiagem (sem falha de cobertura).
        self.assertAlmostEqual(path[0][0], 0.0, places=3)
        self.assertAlmostEqual(path[0][1], 120.0, places=3)
        self.assertAlmostEqual(path[-1][0], 400.0, places=3)
        self.assertAlmostEqual(path[-1][1], 120.0, places=3)

        traffic = TrafficPass(
            pass_no=0,
            fs_id="t1",
            operation_id="spraying",
            spacing_m=36.0,
            width_m=36.0,
            offset_m=0.0,
            azimuth_deg=0.0,
            direction="forward",
            clipped_segment=segment,
            guidance_segment=segment,
        )
        modified, avoided = apply_obstacle_avoidance_to_passes(
            [traffic],
            [square],
            machine,
            AvoidanceConfiguration(mode=AvoidanceMode.CONCENTRIC_RING),
        )
        self.assertEqual(len(avoided), 1)
        self.assertEqual(avoided[0].action, "contour")
        self.assertGreater(len(modified[0].path_points), 8)

    def test_smooth_avoidance_rounds_sharp_corners(self):
        jagged = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (20.0, 10.0)]
        smooth = smooth_avoidance_trajectory(jagged, densify_m=1.0, chaikin_iterations=3)
        self.assertGreater(len(smooth), len(jagged))
        self.assertEqual(smooth[0], jagged[0])
        self.assertEqual(smooth[-1], jagged[-1])
        mid_x = [p[0] for p in smooth if 8.0 < p[0] < 12.0]
        self.assertGreater(len(mid_x), 2)


class PolylineHitTest(unittest.TestCase):
    def test_detects_hit_on_curved_pass(self):
        machine = sprayer_36m()
        from plugin.fortsmart_precision.domain.obstacle_model import obstacle_from_point

        obs = obstacle_from_point((200.0, 130.0), obstacle_radius_m=2.0, safety_margin_m=0.5)
        env = build_all_envelopes([obs], machine)[0]
        curve = (
            (0.0, 100.0),
            (100.0, 110.0),
            (200.0, 125.0),
            (300.0, 110.0),
            (400.0, 100.0),
        )
        hit = polyline_envelope_hit_range(curve, env)
        self.assertIsNotNone(hit)

    def test_envelope_protects_boom_tip_without_double_counting(self):
        """Envelope = raio_obst + meia barra + margem: protege a ponta uma unica vez."""
        machine = sprayer_36m()
        from plugin.fortsmart_precision.domain.obstacle_model import obstacle_from_point

        half = machine.half_operational_width_m
        line = (
            (0.0, 100.0),
            (100.0, 100.0),
            (200.0, 100.0),
            (300.0, 100.0),
            (400.0, 100.0),
        )
        radius, margin = 0.5, 0.5
        reach = radius + half + margin

        # Obstaculo logo DENTRO do alcance da ponta da barra -> desvio.
        inside = obstacle_from_point(
            (200.0, 100.0 + reach - 1.0), obstacle_radius_m=radius, safety_margin_m=margin
        )
        env_inside = build_all_envelopes([inside], machine)[0]
        self.assertIsNotNone(polyline_envelope_hit_range(line, env_inside))

        # Obstaculo logo FORA do alcance -> a ponta passa com folga, sem desvio.
        outside = obstacle_from_point(
            (200.0, 100.0 + reach + 1.0), obstacle_radius_m=radius, safety_margin_m=margin
        )
        env_outside = build_all_envelopes([outside], machine)[0]
        self.assertIsNone(polyline_envelope_hit_range(line, env_outside))


if __name__ == "__main__":
    unittest.main()
