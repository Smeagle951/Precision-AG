# -*- coding: utf-8 -*-
"""Testes de cadastro livre de maquinas (largura / transpasse)."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.domain.machine_model import MachineTrack, PlanterMachine, SprayerMachine


def resolve_sprayer_overlap(
    *,
    nozzle_count: int,
    nozzle_spacing_m: float,
    boom_width_m: float | None,
    overlap_manual_m: float = 0.0,
) -> tuple[float, float]:
    calculated = nozzle_count * nozzle_spacing_m
    boom = calculated if boom_width_m is None or boom_width_m <= 0 else boom_width_m
    if overlap_manual_m > 0:
        return boom, overlap_manual_m
    if boom < calculated - 0.001:
        return boom, round(calculated - boom, 3)
    return boom, 0.0


class FreeMachineConfigTest(unittest.TestCase):
    def test_planter_auto_width_sum(self):
        machine = PlanterMachine(
            machine_id="custom",
            name="Plantadeira 18x0,50",
            row_count=18,
            row_spacing_m=0.5,
            track=MachineTrack(track_width_m=1.8, tire_width_m=0.3),
        )
        self.assertAlmostEqual(machine.operational_width_m, 9.0)

    def test_sprayer_manual_overlap_applied(self):
        boom, overlap = resolve_sprayer_overlap(
            nozzle_count=40,
            nozzle_spacing_m=0.5,
            boom_width_m=20.0,
            overlap_manual_m=0.75,
        )
        self.assertEqual(overlap, 0.75)
        machine = SprayerMachine(
            machine_id="custom",
            name="Barra",
            nozzle_count=40,
            nozzle_spacing_m=0.5,
            boom_width_m=boom,
            track=MachineTrack(track_width_m=3.0, tire_width_m=0.35),
            overlap_m=overlap,
        )
        self.assertAlmostEqual(machine.effective_pass_spacing_m, 19.25, places=3)

    def test_sprayer_auto_overlap_when_boom_below_calculated(self):
        boom, overlap = resolve_sprayer_overlap(
            nozzle_count=103,
            nozzle_spacing_m=0.35,
            boom_width_m=36.0,
            overlap_manual_m=0.0,
        )
        self.assertAlmostEqual(overlap, 103 * 0.35 - 36.0, places=3)
        self.assertAlmostEqual(boom, 36.0)


if __name__ == "__main__":
    unittest.main()
