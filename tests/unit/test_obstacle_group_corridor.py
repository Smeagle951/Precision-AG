# -*- coding: utf-8 -*-
"""Envelopes que se sobrepoem viram UM corredor, nao desvia-volta-desvia-volta."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.line_geometry import distance
from plugin.fortsmart_precision.core.obstacle_buffer_engine import (
    build_all_envelopes,
    build_all_planting_forbidden_regions,
    merge_planting_forbidden_regions,
)
from plugin.fortsmart_precision.core.obstacle_grouping_engine import (
    merge_adjacent_envelopes,
)
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, SprayerMachine
from plugin.fortsmart_precision.domain.obstacle_model import obstacle_from_point
from plugin.fortsmart_precision.domain.planting_avoidance_configuration import (
    PlantingAvoidanceConfiguration,
)
from plugin.fortsmart_precision.domain.planting_kinematics import PlantingKinematics


def _sprayer(boom: float = 36.0) -> SprayerMachine:
    return SprayerMachine(
        machine_id="s",
        name=f"barra {boom}",
        nozzle_count=72,
        nozzle_spacing_m=0.5,
        boom_width_m=boom,
        track=MachineTrack(track_width_m=3.0, tire_width_m=0.37),
    )


def _poles(xs, y=100.0):
    return [
        obstacle_from_point(
            (float(x), y), obstacle_radius_m=0.5, safety_margin_m=0.5, obstacle_id=f"p{i}"
        )
        for i, x in enumerate(xs)
    ]


class OverlapGroupingTest(unittest.TestCase):
    def test_poles_closer_than_two_envelopes_become_one_corridor(self):
        """Postes a 10 m com envelope de 19 m formam barreira continua."""
        machine = _sprayer(36.0)
        envelopes = build_all_envelopes(_poles([100.0, 110.0, 120.0]), machine)
        merged = merge_adjacent_envelopes(envelopes, 2.0)
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(merged[0].obstacle_id.split("+")), 3)

    def test_distant_poles_stay_separate(self):
        machine = _sprayer(36.0)
        envelopes = build_all_envelopes(_poles([100.0, 400.0, 700.0]), machine)
        merged = merge_adjacent_envelopes(envelopes, 2.0)
        self.assertEqual(len(merged), 3)

    def test_merged_circle_actually_covers_every_member(self):
        """O arco unico precisa limpar TODOS os obstaculos, nao so o do meio."""
        machine = _sprayer(36.0)
        obstacles = _poles([100.0, 110.0, 120.0, 130.0])
        envelopes = build_all_envelopes(obstacles, machine)
        merged = merge_adjacent_envelopes(envelopes, 2.0)
        self.assertEqual(len(merged), 1)
        group = merged[0]
        for env in envelopes:
            reach = distance(group.center, env.center) + env.application_radius_m
            self.assertLessEqual(
                reach,
                group.application_radius_m + 1e-6,
                f"envelope {env.obstacle_id} ficou fora do corredor",
            )

    def test_merge_disabled_keeps_every_envelope(self):
        machine = _sprayer(36.0)
        envelopes = build_all_envelopes(_poles([100.0, 110.0, 120.0]), machine)
        self.assertEqual(len(merge_adjacent_envelopes(envelopes, 0.0)), 3)

    def test_long_row_is_split_into_viable_corridors(self):
        """Fileira de 1 km nao pode virar um circulo de centenas de metros."""
        machine = _sprayer(36.0)
        xs = [100.0 + i * 10.0 for i in range(40)]
        envelopes = build_all_envelopes(_poles(xs), machine)
        merged = merge_adjacent_envelopes(envelopes, 2.0)
        self.assertGreater(len(merged), 1)
        self.assertLess(len(merged), 40)
        biggest = max(item.application_radius_m for item in merged)
        self.assertLess(biggest, 5.0 * envelopes[0].application_radius_m + 1e-6)
        # Nenhum obstaculo pode desaparecer no agrupamento.
        covered = {oid for item in merged for oid in item.obstacle_id.split("+")}
        self.assertEqual(len(covered), 40)


class PlantingRegionGroupingTest(unittest.TestCase):
    def _kinematics(self) -> PlantingKinematics:
        return PlantingKinematics(
            operational_width_m=9.0,
            track_width_m=2.0,
            hitch_distance_m=3.0,
            tractor_length_m=4.0,
            row_count=18,
            row_spacing_m=0.5,
        )

    def test_overlapping_regions_merge_and_cover_members(self):
        kin = self._kinematics()
        config = PlantingAvoidanceConfiguration()
        obstacles = _poles([180.0, 190.0, 200.0])
        regions = build_all_planting_forbidden_regions(obstacles, kin, config)
        merged = merge_planting_forbidden_regions(regions, config.merge_obstacles_m)
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(merged[0].group_ids), 3)
        for region in regions:
            reach = (
                distance(merged[0].center, region.center)
                + region.implement_clearance_radius_m
            )
            self.assertLessEqual(reach, merged[0].implement_clearance_radius_m + 1e-6)


if __name__ == "__main__":
    unittest.main()
