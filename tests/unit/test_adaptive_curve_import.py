# -*- coding: utf-8 -*-
"""Import AdaptiveCurve: corta U-turns, mantem desvio antigo, desvia obstaculo novo."""

from __future__ import annotations

import math
import unittest

from plugin.fortsmart_precision.core.adaptive_curve_import_engine import (
    import_adaptive_curve_passes,
    polyline_intersects_circle,
    polyline_min_distance_to_point,
    split_serpentine_strip_uturns,
)
from plugin.fortsmart_precision.core.application_obstacle_engine import (
    apply_application_obstacle_avoidance,
)
from plugin.fortsmart_precision.core.guidance_engine import TrafficPass
from plugin.fortsmart_precision.core.line_geometry import Segment, circle_arc_polyline
from plugin.fortsmart_precision.domain.avoidance_configuration import (
    AvoidanceConfiguration,
    AvoidanceMode,
)
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, SprayerMachine
from plugin.fortsmart_precision.domain.obstacle_model import obstacle_from_point


def _rect(width=200.0, height=120.0):
    outer = [(0.0, 0.0), (width, 0.0), (width, height), (0.0, height), (0.0, 0.0)]
    return [(outer, [])]


def _sprayer_36():
    return SprayerMachine(
        machine_id="s36",
        name="36.05",
        nozzle_count=103,
        nozzle_spacing_m=0.35,
        boom_width_m=36.05,
        track=MachineTrack(track_width_m=3.0, tire_width_m=0.37),
    )


def _serpentine_with_uturns_and_mid_detour():
    """Duas passadas horizontais ligadas por U agudo na direita + arco de desvio no miolo.

    O U usa vertices agudos (nao arco denso): o classificador olha angulo de viragem,
    e um semicirculo suave tem viragens ~15° por vertice.
    """
    left0 = [(10.0, 40.0), (80.0, 40.0)]
    # Meia-volta no miolo (desvio antigo) — longe da borda.
    detour = circle_arc_polyline((100.0, 40.0), 12.0, math.pi, -math.pi, segments=20)
    right0 = [(120.0, 40.0), (190.0, 40.0)]
    # U-turn agudo na cabeceira direita (perto de x=200): ~180° em (198, 50).
    uturn = [(190.0, 40.0), (198.0, 40.0), (198.0, 50.0), (198.0, 60.0), (190.0, 60.0)]
    pass1 = [(190.0, 60.0), (10.0, 60.0)]
    pts = left0 + detour[1:] + right0[1:] + uturn[1:] + pass1[1:]
    return pts


class SplitUturnTest(unittest.TestCase):
    def test_strips_headland_uturn_keeps_midfield_detour(self):
        field = _rect(200, 120)
        pts = _serpentine_with_uturns_and_mid_detour()
        parts, n_cut = split_serpentine_strip_uturns(
            pts, field, headland_band_m=35.0, min_turn_deg=90.0
        )
        self.assertGreaterEqual(n_cut, 1)
        self.assertGreaterEqual(len(parts), 2)
        # Desvio no miolo permanece (pontos fora da reta y=40 perto de x=100).
        flat = [p for part in parts for p in part]
        near_detour = [
            p for p in flat if abs(p[0] - 100.0) < 15.0 and abs(p[1] - 40.0) > 4.0
        ]
        self.assertTrue(near_detour)
        self.assertTrue(all(polyline_length_ok(part) for part in parts))
        # U cortado: nenhuma parte deve ir de y~40 ate y~60 na borda direita.
        for part in parts:
            ys = [p[1] for p in part if p[0] > 185.0]
            if len(ys) >= 2:
                self.assertLess(max(ys) - min(ys), 15.0)


def polyline_length_ok(part):
    from plugin.fortsmart_precision.core.line_geometry import polyline_length

    return polyline_length(part) > 30.0


class ImportExtendTest(unittest.TestCase):
    def test_import_extends_past_boundary(self):
        field = _rect(200, 120)
        # Duas passadas ja separadas (sem U).
        polylines = [
            [(20.0, 40.0), (180.0, 40.0)],
            [(20.0, 70.0), (180.0, 70.0)],
        ]
        result = import_adaptive_curve_passes(
            polylines,
            field,
            extension_m=10.0,
            pass_spacing_m=30.0,
            width_m=30.0,
        )
        self.assertEqual(len(result.passes), 2)
        self.assertIn(0, [p.pass_no for p in result.passes])
        for traffic in result.passes:
            xs = [p[0] for p in traffic.line_points()]
            self.assertLess(min(xs), 20.0)
            self.assertGreater(max(xs), 180.0)


class NewObstacleAvoidanceTest(unittest.TestCase):
    def test_new_pole_on_centerline_gets_half_boom_detour(self):
        sprayer = _sprayer_36()
        half = sprayer.half_operational_width_m
        self.assertAlmostEqual(half, 18.025, places=3)
        # Passada reta cruzando o poste.
        traffic = TrafficPass(
            pass_no=0,
            fs_id="a0",
            operation_id="spraying",
            spacing_m=36.05,
            width_m=36.05,
            offset_m=0.0,
            azimuth_deg=0.0,
            direction="forward",
            clipped_segment=Segment((0.0, 0.0), (100.0, 0.0)),
            guidance_segment=Segment((0.0, 0.0), (100.0, 0.0)),
            path_points=((0.0, 0.0), (100.0, 0.0)),
        )
        pole = obstacle_from_point((50.0, 0.0), obstacle_radius_m=0.5, safety_margin_m=0.0, name="poste")
        config = AvoidanceConfiguration(mode=AvoidanceMode.CONCENTRIC_RING)
        modified, avoided = apply_application_obstacle_avoidance(
            [traffic], [pole], sprayer, config
        )
        self.assertEqual(len(avoided), 1)
        path = list(modified[0].line_points())
        min_d = polyline_min_distance_to_point(path, pole.center)
        self.assertGreaterEqual(min_d, half + pole.obstacle_radius_m - 0.05)
        self.assertEqual(path[0], (0.0, 0.0))
        self.assertEqual(path[-1], (100.0, 0.0))

    def test_already_clear_path_skips_new_detour(self):
        sprayer = _sprayer_36()
        half = sprayer.half_operational_width_m
        # Path ja contorna o poste (arco fora do raio).
        radius = half + 0.5
        arc = circle_arc_polyline((50.0, 0.0), radius + 1.0, math.pi, -math.pi, segments=24)
        path = [(0.0, 0.0)] + list(arc) + [(100.0, 0.0)]
        # Garantir que nao penetra.
        self.assertFalse(polyline_intersects_circle(path, (50.0, 0.0), radius - 0.01))
        traffic = TrafficPass(
            pass_no=0,
            fs_id="a0",
            operation_id="spraying",
            spacing_m=36.05,
            width_m=36.05,
            offset_m=0.0,
            azimuth_deg=0.0,
            direction="forward",
            clipped_segment=Segment((0.0, 0.0), (100.0, 0.0)),
            guidance_segment=Segment((0.0, 0.0), (100.0, 0.0)),
            path_points=tuple(path),
        )
        pole = obstacle_from_point((50.0, 0.0), obstacle_radius_m=0.5, safety_margin_m=0.0)
        config = AvoidanceConfiguration(mode=AvoidanceMode.CONCENTRIC_RING)
        _modified, avoided = apply_application_obstacle_avoidance(
            [traffic], [pole], sprayer, config
        )
        self.assertEqual(len(avoided), 0)


class ABRegressionTest(unittest.TestCase):
    def test_parallel_ab_generation_unchanged(self):
        """Caminho A-B (gerar aplicacao) permanece independente da importacao."""
        from plugin.fortsmart_precision.core.parallel_pass_engine import (
            ParallelPassParams,
            generate_parallel_passes,
        )

        field = _rect(200, 120)
        passes = generate_parallel_passes(
            ParallelPassParams(
                polygons=field,
                ab_start=(0.0, 60.0),
                ab_end=(200.0, 60.0),
                pass_spacing_m=36.05,
                operation_width_m=36.05,
                extension_m=10.0,
                operation_id="spraying",
            )
        )
        self.assertGreaterEqual(len(passes), 2)
        self.assertIn(0, [p.pass_no for p in passes])


class BuildPlanFromAdaptiveCurveTest(unittest.TestCase):
    def test_serpentine_not_discarded_as_contour_and_builds_headland(self):
        """Regressao: serpentina com pontas na mesma cabeceira nao e 'anel'."""
        from plugin.fortsmart_precision.core.adaptive_curve_import_engine import (
            build_plan_from_adaptive_curve,
        )
        from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
        from plugin.fortsmart_precision.domain.machine_model import PlanterMachine

        field = _rect(200, 120)
        pts = _serpentine_with_uturns_and_mid_detour()
        sprayer = _sprayer_36()
        planter = PlanterMachine(
            machine_id="p",
            name="p",
            row_count=12,
            row_spacing_m=0.5,
            track=MachineTrack(track_width_m=3.0, tire_width_m=0.37),
        )
        plan = build_plan_from_adaptive_curve(
            [pts],
            field,
            sprayer=sprayer,
            planter=planter,
            spray_headland=HeadlandLayout(pass_count=0),
            plant_headland=HeadlandLayout(pass_count=0),
        )
        self.assertGreaterEqual(len(plan.spraying_passes), 2)
        self.assertGreaterEqual(plan.stripped_uturn_count, 1)
        self.assertIsNotNone(plan.spraying_boundary)
        self.assertTrue(plan.spraying_boundary.areas.headland_area)
        flat = [p for t in plan.spraying_passes for p in t.line_points()]
        mid = [p for p in flat if abs(p[0] - 100.0) < 15.0 and abs(p[1] - 40.0) > 4.0]
        self.assertTrue(mid, "desvio do miolo deve permanecer nas passadas")


if __name__ == "__main__":
    unittest.main()
