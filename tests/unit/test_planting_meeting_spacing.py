# -*- coding: utf-8 -*-
"""Encontro de passadas ida/volta: nao pode remontar nem deixar falha."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.domain.machine_model import MachineTrack, PlanterMachine


def _planter(row_count=36, row_spacing_m=0.5, informed=None):
    return PlanterMachine(
        machine_id="p",
        name="teste",
        row_count=row_count,
        row_spacing_m=row_spacing_m,
        track=MachineTrack(track_width_m=1.8, tire_width_m=0.3),
        informed_operational_width_m=informed,
    )


class PlanterMeetingSpacingTest(unittest.TestCase):
    def test_calculated_width_gives_exact_internal_spacing(self):
        """36 x 0,50 m: barra fisica 17,5 m, faixa 18,0 m, encontro 0,50 m."""
        machine = _planter()
        self.assertAlmostEqual(machine.physical_span_m, 17.5, places=6)
        self.assertAlmostEqual(machine.operational_width_m, 18.0, places=6)
        self.assertAlmostEqual(machine.meeting_spacing_m(), 0.5, places=6)
        self.assertEqual(machine.meeting_status()["status"], "correct")

    def test_narrow_informed_width_is_flagged_as_overlap(self):
        """Largura informada menor que a faixa das linhas: linha da volta remonta a da ida."""
        machine = _planter(informed=17.5)
        self.assertAlmostEqual(machine.operational_width_m, 17.5, places=9)
        self.assertAlmostEqual(machine.meeting_spacing_m(), 0.0, places=6)
        status = machine.meeting_status()
        self.assertEqual(status["status"], "overlap")
        self.assertAlmostEqual(float(status["difference_m"]), -0.5, places=6)

    def test_wide_informed_width_is_flagged_as_gap(self):
        machine = _planter(informed=18.4)
        self.assertAlmostEqual(machine.operational_width_m, 18.4, places=9)
        status = machine.meeting_status()
        self.assertEqual(status["status"], "gap")
        self.assertAlmostEqual(float(status["difference_m"]), 0.4, places=6)

    def test_meeting_spacing_follows_planter_spacing(self):
        """40 x 0,45 m tem encontro de 0,45 m (nao 0,50 m)."""
        machine = _planter(row_count=40, row_spacing_m=0.45)
        self.assertAlmostEqual(machine.operational_width_m, 18.0, places=6)
        self.assertAlmostEqual(machine.meeting_spacing_m(), 0.45, places=6)
        self.assertEqual(machine.meeting_status()["status"], "correct")


class RowLayoutMeetingTest(unittest.TestCase):
    def test_adjacent_passes_meet_at_one_spacing(self):
        """Distancia entre a ultima linha da ida e a primeira da volta."""
        machine = _planter()
        offsets = machine.all_row_offsets()
        width = machine.operational_width_m
        neighbour_first = offsets[0] + width
        self.assertAlmostEqual(neighbour_first - offsets[-1], machine.row_spacing_m, places=6)


if __name__ == "__main__":
    unittest.main()
