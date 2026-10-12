# -*- coding: utf-8 -*-
"""Testes do modelo de shutoff pneu × linha de semente."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.domain.machine_model import MachineTrack, PlanterMachine
from plugin.fortsmart_precision.domain.sprayer_traffic_configuration import (
    SprayerTrafficConfiguration,
    TrafficMeasureResolution,
)
from plugin.fortsmart_precision.domain.tire_shutoff_model import tire_shutoff_from_machines


class TireShutoffModelTest(unittest.TestCase):
    def test_classifies_rows_on_corridor_and_tires(self):
        planter = PlanterMachine(
            machine_id="p",
            name="18m",
            row_count=40,
            row_spacing_m=0.45,
            track=MachineTrack(track_width_m=1.8, tire_width_m=0.3),
        )
        traffic = SprayerTrafficConfiguration(
            boom_width_m=36.0,
            tire_width_m=0.37,
            inner_clearance_m=2.70,
            outer_width_m=3.43,
            resolution=TrafficMeasureResolution.USE_OUTER,
        )
        zones, rows = tire_shutoff_from_machines(planter, traffic)
        off_rows = [item for item in rows if item[2] == "DESLIGA"]
        on_rows = [item for item in rows if item[2] == "LIGA"]
        self.assertGreater(len(off_rows), 0)
        self.assertGreater(len(on_rows), 0)
        right_center = traffic.calculate_tire_zones()[1].center_m
        self.assertFalse(zones.row_is_on_corridor(right_center))


if __name__ == "__main__":
    unittest.main()
