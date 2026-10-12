# -*- coding: utf-8 -*-
"""Desvio de plantio em passada curva com corda curta (pivo / AB adaptativa)."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.guidance_engine import TrafficPass
from plugin.fortsmart_precision.core.line_geometry import Segment
from plugin.fortsmart_precision.core.planting_kinematics_engine import kinematics_from_planter
from plugin.fortsmart_precision.core.planting_obstacle_engine import apply_planting_avoidance_to_passes
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, PlanterMachine
from plugin.fortsmart_precision.domain.obstacle_model import obstacle_from_polygon
from plugin.fortsmart_precision.domain.planting_avoidance_configuration import (
    PlantingAvoidanceConfiguration,
    PlantingAvoidanceStrategy,
)


class PlantingObstacleShortChordTest(unittest.TestCase):
    def test_curved_pass_with_short_chord_and_obstacle(self):
        """Corda inicio-fim ~0 m mas polilinha longa: nao pode travar no desvio."""
        planter = PlanterMachine(
            machine_id="p40",
            name="40x0.5",
            row_count=40,
            row_spacing_m=0.5,
            track=MachineTrack(track_width_m=1.8, tire_width_m=0.3),
        )
        kin = kinematics_from_planter(planter)
        config = PlantingAvoidanceConfiguration(
            strategy=PlantingAvoidanceStrategy.AUTO,
            enabled=True,
            minimum_turn_radius_m=6.0,
        )
        # Arco em U: inicio e fim proximos (como passada curta no pivo).
        path = [
            (100.0, 100.0),
            (120.0, 100.0),
            (140.0, 110.0),
            (140.0, 130.0),
            (120.0, 140.0),
            (100.0, 140.0),
            (100.05, 100.05),
        ]
        chord = Segment(path[0], path[-1])
        self.assertLess(chord.length, 1.0)
        obstacle = obstacle_from_polygon(
            [
                (
                    (130.0, 120.0),
                    (140.0, 120.0),
                    (140.0, 130.0),
                    (130.0, 130.0),
                    (130.0, 120.0),
                ),
                [],
            ],
            obstacle_radius_m=0.0,
            safety_margin_m=0.35,
            name="obst",
            obstacle_id="obst1",
        )
        item = TrafficPass(
            pass_no=1,
            fs_id="p1",
            operation_id="planting",
            spacing_m=20.0,
            width_m=20.0,
            offset_m=0.0,
            azimuth_deg=0.0,
            direction="forward",
            clipped_segment=chord,
            guidance_segment=chord,
            path_points=tuple(path),
        )
        modified, results, avoided = apply_planting_avoidance_to_passes(
            [item],
            [obstacle],
            kin,
            config,
            planter,
        )
        self.assertEqual(len(modified), 1)
        self.assertGreater(len(modified[0].line_points()), 2)
        self.assertGreater(len(results), 0)
        self.assertGreater(len(avoided), 0)


if __name__ == "__main__":
    unittest.main()
