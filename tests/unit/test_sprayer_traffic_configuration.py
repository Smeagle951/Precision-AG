# -*- coding: utf-8 -*-
"""Testes: trafego generico do pulverizador e shutoff por zonas de pneu."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.sprayer_traffic_engine import calculate_planting_shutoff
from plugin.fortsmart_precision.core.guidance_engine import TrafficPass
from plugin.fortsmart_precision.core.line_geometry import Segment
from plugin.fortsmart_precision.core.tire_track_engine import generate_tire_tracks_from_traffic
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, PlanterMachine, SprayerMachine
from plugin.fortsmart_precision.domain.sprayer_traffic_configuration import (
    SprayerTrafficConfiguration,
    TrafficMeasureResolution,
)


def _jacto_like_traffic(
    *,
    resolution: TrafficMeasureResolution = TrafficMeasureResolution.USE_OUTER,
) -> SprayerTrafficConfiguration:
    return SprayerTrafficConfiguration(
        boom_width_m=36.0,
        tire_width_m=0.37,
        inner_clearance_m=2.70,
        outer_width_m=3.43,
        resolution=resolution,
    )


def _planter_36x045() -> PlanterMachine:
    return PlanterMachine(
        machine_id="planter_36",
        name="Plantadeira 36x0,45",
        row_count=36,
        row_spacing_m=0.45,
        track=MachineTrack(track_width_m=1.8, tire_width_m=0.3),
    )


class SprayerTrafficConfigurationTest(unittest.TestCase):
    def test_detects_one_centimeter_inconsistency(self):
        traffic = _jacto_like_traffic()
        check = traffic.measure_check(tolerance_m=0.005)
        self.assertFalse(check.is_consistent)
        self.assertAlmostEqual(check.computed_outer_m, 3.44, places=2)
        self.assertAlmostEqual(check.difference_m, 0.01, places=2)

    def test_use_outer_derives_zones_from_external_width(self):
        traffic = _jacto_like_traffic(resolution=TrafficMeasureResolution.USE_OUTER)
        left, right = traffic.calculate_tire_zones()
        self.assertAlmostEqual(left.min_m, -1.715, places=3)
        self.assertAlmostEqual(left.max_m, -1.350, places=3)
        self.assertAlmostEqual(right.min_m, 1.350, places=3)
        self.assertAlmostEqual(right.max_m, 1.715, places=3)
        self.assertAlmostEqual(left.width_m, 0.365, places=3)

    def test_use_inner_and_tires_uses_declared_tire_width(self):
        traffic = _jacto_like_traffic(resolution=TrafficMeasureResolution.USE_INNER_AND_TIRES)
        left, right = traffic.calculate_tire_zones()
        self.assertAlmostEqual(left.width_m, 0.37, places=3)
        self.assertAlmostEqual(traffic.resolved_outer_width_m(), 3.44, places=2)

    def test_boom_separate_from_track(self):
        traffic = _jacto_like_traffic()
        machine = SprayerMachine(
            machine_id="spr",
            name="Generico",
            nozzle_count=72,
            nozzle_spacing_m=0.5,
            boom_width_m=36.0,
            track=traffic.to_machine_track(),
            traffic=traffic,
        )
        machine.validate()
        self.assertAlmostEqual(machine.boom_width_m, 36.0)
        self.assertNotAlmostEqual(machine.boom_width_m, machine.effective_track.track_width_m)


class PlantingShutoffByOffsetTest(unittest.TestCase):
    def test_row_in_right_tire_zone_desliga(self):
        traffic = _jacto_like_traffic()
        planter = _planter_36x045()
        rows = calculate_planting_shutoff(planter, traffic)
        by_offset = {round(r.offset_m, 3): r for r in rows}

        self.assertEqual(by_offset[1.575].action, "DESLIGA")
        self.assertEqual(by_offset[1.575].zone_side, "right")
        self.assertEqual(by_offset[-1.575].action, "DESLIGA")
        self.assertEqual(by_offset[-1.575].zone_side, "left")

    def test_row_in_clear_gap_liga(self):
        traffic = _jacto_like_traffic()
        planter = _planter_36x045()
        rows = calculate_planting_shutoff(planter, traffic)
        by_offset = {round(r.offset_m, 3): r for r in rows}

        self.assertEqual(by_offset[1.125].action, "LIGA")
        self.assertEqual(by_offset[-1.125].action, "LIGA")
        self.assertIsNone(by_offset[1.125].zone_side)

    def test_machine_track_from_traffic_for_legacy_engines(self):
        traffic = _jacto_like_traffic()
        track = traffic.to_machine_track()
        self.assertAlmostEqual(track.track_width_m, 3.065, places=3)
        self.assertAlmostEqual(track.tire_width_m, 0.365, places=3)

    def test_margin_expands_exclusion_without_moving_track_centers(self):
        traffic = SprayerTrafficConfiguration(
            boom_width_m=36.0,
            tire_width_m=0.38,
            inner_clearance_m=2.70,
            outer_width_m=3.46,
            safety_margin_m=0.10,
        )
        self.assertAlmostEqual(traffic.exclusion_width_m, 0.58, places=3)
        physical_left, physical_right = traffic.calculate_tire_zones()
        exclusion_left, exclusion_right = traffic.calculate_exclusion_zones()
        self.assertAlmostEqual(
            exclusion_left.center_m, physical_left.center_m, places=9
        )
        self.assertAlmostEqual(
            exclusion_right.center_m, physical_right.center_m, places=9
        )
        self.assertAlmostEqual(exclusion_left.min_m, physical_left.min_m - 0.10)
        self.assertAlmostEqual(exclusion_right.max_m, physical_right.max_m + 0.10)
        traffic_pass = TrafficPass(
            pass_no=1,
            fs_id="spray-1",
            operation_id="spraying",
            spacing_m=36.0,
            width_m=36.0,
            offset_m=0.0,
            azimuth_deg=90.0,
            direction="forward",
            clipped_segment=Segment((0.0, 0.0), (100.0, 0.0)),
            guidance_segment=Segment((0.0, 0.0), (100.0, 0.0)),
        )
        tracks = generate_tire_tracks_from_traffic([traffic_pass], traffic)
        self.assertEqual(len(tracks), 2)
        self.assertTrue(all(abs(item.tire_width_m - 0.58) < 1e-9 for item in tracks))
        self.assertAlmostEqual(abs(tracks[0].offset_m), traffic.track_width_m / 2.0, places=6)

    def test_margin_is_used_by_static_row_classification(self):
        traffic = SprayerTrafficConfiguration(
            boom_width_m=36.0,
            tire_width_m=0.40,
            inner_clearance_m=2.60,
            outer_width_m=3.40,
            safety_margin_m=0.10,
        )
        planter = PlanterMachine(
            machine_id="margin-planter",
            name="Linhas para margem",
            row_count=9,
            row_spacing_m=0.40,
            track=MachineTrack(track_width_m=1.8, tire_width_m=0.30),
        )
        rows = calculate_planting_shutoff(planter, traffic)
        by_offset = {round(item.offset_m, 1): item for item in rows}
        self.assertEqual(by_offset[1.2].action, "DESLIGA")
        self.assertEqual(by_offset[1.2].zone_side, "right")


if __name__ == "__main__":
    unittest.main()
