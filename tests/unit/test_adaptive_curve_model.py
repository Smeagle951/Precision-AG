# -*- coding: utf-8 -*-
"""Modelo AdaptiveCurve: corta U, preserva miolo, desvio so onde necessario, idempotente."""

from __future__ import annotations

import math
import unittest

from plugin.fortsmart_precision.core.adaptive_curve_import_engine import (
    import_adaptive_curve_passes,
    polyline_min_distance_to_point,
    split_serpentine_strip_uturns,
)
from plugin.fortsmart_precision.core.application_obstacle_engine import (
    apply_application_obstacle_avoidance,
)
from plugin.fortsmart_precision.core.line_geometry import Segment, circle_arc_polyline
from plugin.fortsmart_precision.domain.avoidance_configuration import (
    AvoidanceConfiguration,
    AvoidanceMode,
)
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, SprayerMachine
from plugin.fortsmart_precision.domain.obstacle_model import obstacle_from_point


def _rect(w=200.0, h=120.0):
    return [([(0.0, 0.0), (w, 0.0), (w, h), (0.0, h), (0.0, 0.0)], [])]


def _sprayer_36():
    return SprayerMachine(
        machine_id="s36",
        name="36.05",
        nozzle_count=103,
        nozzle_spacing_m=0.35,
        boom_width_m=36.05,
        track=MachineTrack(track_width_m=3.0, tire_width_m=0.37),
    )


def _gold_serpentine():
    """2 U na cabeceira + 1 arco antigo no miolo."""
    left = [(10.0, 40.0), (80.0, 40.0)]
    detour = circle_arc_polyline((100.0, 40.0), 12.0, math.pi, -math.pi, segments=20)
    right = [(120.0, 40.0), (190.0, 40.0)]
    uturn = [(190.0, 40.0), (198.0, 40.0), (198.0, 50.0), (198.0, 60.0), (190.0, 60.0)]
    back = [(190.0, 60.0), (10.0, 60.0)]
    return left + detour[1:] + right[1:] + uturn[1:] + back[1:]


class AdaptiveCurveModelTest(unittest.TestCase):
    def test_strips_uturn_keeps_midfield_curve_and_path_points(self):
        field = _rect()
        pts = _gold_serpentine()
        parts, n_cut = split_serpentine_strip_uturns(
            pts, field, headland_band_m=35.0, min_turn_deg=90.0
        )
        self.assertGreaterEqual(n_cut, 1)
        self.assertGreaterEqual(len(parts), 2)
        flat = [p for part in parts for p in part]
        mid = [p for p in flat if abs(p[0] - 100.0) < 15.0 and abs(p[1] - 40.0) > 4.0]
        self.assertTrue(mid, "arco do miolo deve permanecer")

        result = import_adaptive_curve_passes(
            [pts],
            field,
            extension_m=10.0,
            pass_spacing_m=20.0,
            width_m=20.0,
            headland_band_m=35.0,
            min_turn_deg=90.0,
        )
        self.assertGreaterEqual(result.stripped_uturn_count, 1)
        self.assertGreaterEqual(len(result.passes), 2)
        # Passadas continuam curvas (path_points densos), nao so start/end.
        curved = [
            p
            for p in result.passes
            if any(abs(pt[0] - 100.0) < 15.0 and abs(pt[1] - 40.0) > 4.0 for pt in p.line_points())
        ]
        self.assertTrue(curved)
        self.assertGreater(len(curved[0].path_points), 8)

    def test_smooth_headland_uturn_is_stripped(self):
        field = _rect()
        left = [(10.0, 40.0), (170.0, 40.0)]
        # U suave (semicirculo) — angulos locais ~15°, so acumulado detecta.
        uturn = circle_arc_polyline((170.0, 50.0), 10.0, -math.pi / 2, math.pi, segments=24)
        back = [(170.0, 60.0), (10.0, 60.0)]
        pts = left + uturn[1:] + back[1:]
        parts, n_cut = split_serpentine_strip_uturns(
            pts, field, headland_band_m=35.0, min_turn_deg=100.0
        )
        self.assertGreaterEqual(n_cut, 1)
        self.assertGreaterEqual(len(parts), 2)

    def test_new_pole_gets_half_boom_detour_and_returns(self):
        sprayer = _sprayer_36()
        half = sprayer.half_operational_width_m
        from plugin.fortsmart_precision.core.guidance_engine import TrafficPass

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
        pole = obstacle_from_point(
            (50.0, 0.0), obstacle_radius_m=0.5, safety_margin_m=0.5, name="poste"
        )
        # Raio nao fixo: obst + meia barra + margem.
        expected = pole.application_radius_m(sprayer)
        self.assertAlmostEqual(expected, 0.5 + half + 0.5, places=3)

        config = AvoidanceConfiguration(mode=AvoidanceMode.CONCENTRIC_RING)
        modified, avoided = apply_application_obstacle_avoidance(
            [traffic], [pole], sprayer, config
        )
        self.assertEqual(len(avoided), 1)
        path = list(modified[0].line_points())
        self.assertGreaterEqual(
            polyline_min_distance_to_point(path, pole.center), expected - 0.05
        )
        self.assertEqual(path[0], (0.0, 0.0))
        self.assertEqual(path[-1], (100.0, 0.0))
        self.assertGreater(len(path), 8)

    def test_already_clear_path_skips_and_is_idempotent(self):
        sprayer = _sprayer_36()
        half = sprayer.half_operational_width_m
        radius = half + 0.5 + 0.5
        arc = circle_arc_polyline((50.0, 0.0), radius + 1.0, math.pi, -math.pi, segments=24)
        path = [(0.0, 0.0)] + list(arc) + [(100.0, 0.0)]
        from plugin.fortsmart_precision.core.guidance_engine import TrafficPass

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
        pole = obstacle_from_point(
            (50.0, 0.0), obstacle_radius_m=0.5, safety_margin_m=0.5
        )
        config = AvoidanceConfiguration(mode=AvoidanceMode.CONCENTRIC_RING)
        m1, a1 = apply_application_obstacle_avoidance([traffic], [pole], sprayer, config)
        self.assertEqual(len(a1), 0)
        m2, a2 = apply_application_obstacle_avoidance(m1, [pole], sprayer, config)
        self.assertEqual(len(a2), 0)
        self.assertEqual(list(m1[0].line_points()), list(m2[0].line_points()))

    def test_closed_contour_ring_is_removed_straight_edge_pass_kept(self):
        field = _rect(200, 120)
        # Anel de cabeceira (quase fechado, perto da borda).
        ring = [
            (5.0, 5.0),
            (195.0, 5.0),
            (195.0, 115.0),
            (5.0, 115.0),
            (5.0, 5.0),
        ]
        # Passada reta perto da borda inferior — NAO e contorno.
        edge_pass = [(20.0, 15.0), (180.0, 15.0)]
        result = import_adaptive_curve_passes(
            [ring, edge_pass],
            field,
            extension_m=5.0,
            pass_spacing_m=20.0,
            width_m=20.0,
            headland_band_m=25.0,
        )
        self.assertGreaterEqual(result.removed_contour_count, 1)
        self.assertGreaterEqual(len(result.passes), 1)
        # Passada reta sobrevive.
        self.assertTrue(
            any(abs(p.line_points()[0][1] - 15.0) < 5.0 for p in result.passes)
        )


if __name__ == "__main__":
    unittest.main()
