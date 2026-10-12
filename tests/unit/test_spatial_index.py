# -*- coding: utf-8 -*-
"""Indice espacial: descarta obstaculos distantes sem perder candidatos reais."""

from __future__ import annotations

import time
import unittest

from plugin.fortsmart_precision.core.obstacle_buffer_engine import build_all_envelopes
from plugin.fortsmart_precision.core.spatial_index import (
    build_envelope_index,
    build_region_index,
)
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, SprayerMachine
from plugin.fortsmart_precision.domain.obstacle_model import obstacle_from_point


def _sprayer() -> SprayerMachine:
    return SprayerMachine(
        machine_id="s36",
        name="Barra 36",
        nozzle_count=72,
        nozzle_spacing_m=0.5,
        boom_width_m=36.0,
        track=MachineTrack(track_width_m=3.0, tire_width_m=0.37),
    )


def _grid_obstacles(count_x: int, count_y: int, step: float = 120.0):
    return [
        obstacle_from_point(
            (i * step, j * step), obstacle_radius_m=1.0, safety_margin_m=0.5
        )
        for i in range(count_x)
        for j in range(count_y)
    ]


class IndexCorrectnessTest(unittest.TestCase):
    def test_query_returns_superset_of_linear_filter(self):
        machine = _sprayer()
        obstacles = _grid_obstacles(8, 8)
        envelopes = build_all_envelopes(obstacles, machine)
        index = build_envelope_index(envelopes)
        self.assertEqual(len(index), len(envelopes))

        reach = machine.half_operational_width_m + 30.0
        path = [(0.0, 240.0), (400.0, 240.0), (840.0, 240.0)]
        found = index.query_polyline(path, reach)
        found_ids = {env.obstacle_id for env in found}

        # Referencia: filtro linear ingenuo pelo mesmo alcance.
        expected = set()
        for env in envelopes:
            cx, cy = env.center
            if not (-reach <= cx <= 840.0 + reach):
                continue
            if abs(cy - 240.0) <= reach + env.application_radius_m:
                expected.add(env.obstacle_id)
        self.assertTrue(expected.issubset(found_ids))

    def test_far_query_returns_nothing(self):
        machine = _sprayer()
        envelopes = build_all_envelopes(_grid_obstacles(5, 5), machine)
        index = build_envelope_index(envelopes)
        far = index.query_polyline([(50000.0, 50000.0), (50400.0, 50000.0)], 20.0)
        self.assertEqual(far, [])

    def test_empty_index_is_safe(self):
        index = build_envelope_index([])
        self.assertEqual(len(index), 0)
        self.assertEqual(index.query_polyline([(0.0, 0.0), (10.0, 0.0)], 5.0), [])
        self.assertEqual(index.query_point((0.0, 0.0), 5.0), [])

    def test_region_index_uses_implement_clearance(self):
        from plugin.fortsmart_precision.core.obstacle_buffer_engine import (
            build_all_planting_forbidden_regions,
        )
        from plugin.fortsmart_precision.domain.planting_avoidance_configuration import (
            PlantingAvoidanceConfiguration,
        )
        from plugin.fortsmart_precision.domain.planting_kinematics import PlantingKinematics

        kin = PlantingKinematics(
            operational_width_m=9.0,
            track_width_m=2.0,
            hitch_distance_m=3.0,
            tractor_length_m=4.0,
            row_count=18,
            row_spacing_m=0.5,
        )
        regions = build_all_planting_forbidden_regions(
            _grid_obstacles(4, 4), kin, PlantingAvoidanceConfiguration()
        )
        index = build_region_index(regions)
        self.assertEqual(len(index), len(regions))
        near = index.query_point((0.0, 0.0), 5.0)
        self.assertTrue(near)


class IndexScalingTest(unittest.TestCase):
    def test_many_obstacles_query_stays_cheap(self):
        """400 obstaculos x 100 passadas nao pode virar 40.000 varreduras."""
        machine = _sprayer()
        envelopes = build_all_envelopes(_grid_obstacles(20, 20, step=60.0), machine)
        index = build_envelope_index(envelopes)
        reach = machine.half_operational_width_m + 30.0

        started = time.perf_counter()
        total = 0
        for i in range(100):
            y = i * 12.0
            total += len(index.query_polyline([(0.0, y), (1140.0, y)], reach))
        elapsed = time.perf_counter() - started

        self.assertGreater(total, 0)
        # Cada passada so ve a sua faixa, nao os 400 obstaculos.
        self.assertLess(total / 100.0, len(envelopes) * 0.5)
        self.assertLess(elapsed, 2.0)


if __name__ == "__main__":
    unittest.main()
