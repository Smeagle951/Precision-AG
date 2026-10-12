# -*- coding: utf-8 -*-
"""Transpasse do pulverizador: sem / metros / numero de bicos (regra unica)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from plugin.fortsmart_precision.domain.machine_model import (
    MachineModelError,
    MachineTrack,
    SprayerMachine,
)
from plugin.fortsmart_precision.domain.sprayer_overlap import (
    OVERLAP_MODE_METERS,
    OVERLAP_MODE_NONE,
    OVERLAP_MODE_NOZZLES,
    OVERLAP_SIDE_LEFT,
    OVERLAP_SIDE_NONE,
    OVERLAP_SIDE_RIGHT,
    SprayerOverlapError,
    effective_pass_spacing_m,
    machine_pass_overlap_attributes,
    overlap_nozzle_equivalent,
    overlap_side_for_pass,
    pass_overlap_attributes,
    resolve_sprayer_overlap_m,
)

BOOM = dict(nozzle_count=72, nozzle_spacing_m=0.5, boom_width_m=36.0)


def sprayer_36(**kwargs) -> SprayerMachine:
    return SprayerMachine(
        machine_id="s36",
        name="Barra 36 m",
        nozzle_count=72,
        nozzle_spacing_m=0.5,
        boom_width_m=kwargs.pop("boom_width_m", 36.0),
        track=MachineTrack(track_width_m=3.0, tire_width_m=0.37),
        **kwargs,
    )


class ResolverModesTest(unittest.TestCase):
    def test_none_mode_is_zero_even_with_values(self):
        self.assertEqual(
            resolve_sprayer_overlap_m(
                OVERLAP_MODE_NONE, overlap_m=2.0, overlap_nozzle_count=3, **BOOM
            ),
            0.0,
        )

    def test_meters_mode_returns_informed_value(self):
        self.assertAlmostEqual(
            resolve_sprayer_overlap_m(OVERLAP_MODE_METERS, overlap_m=0.75, **BOOM), 0.75
        )

    def test_meters_zero_keeps_legacy_auto_only_when_requested(self):
        kwargs = dict(nozzle_count=72, nozzle_spacing_m=0.5, boom_width_m=35.0)
        self.assertAlmostEqual(
            resolve_sprayer_overlap_m(
                OVERLAP_MODE_METERS, legacy_auto_from_boom=True, **kwargs
            ),
            1.0,
        )
        self.assertEqual(resolve_sprayer_overlap_m(OVERLAP_MODE_METERS, **kwargs), 0.0)

    def test_meters_zero_with_boom_equal_calculated_is_zero(self):
        self.assertEqual(
            resolve_sprayer_overlap_m(OVERLAP_MODE_METERS, legacy_auto_from_boom=True, **BOOM),
            0.0,
        )

    def test_nozzle_mode_example_36m_72_nozzles(self):
        expected = {0: 36.00, 1: 35.50, 2: 35.00, 3: 34.50, 4: 34.00}
        for nozzles, spacing in expected.items():
            with self.subTest(nozzles=nozzles):
                overlap = resolve_sprayer_overlap_m(
                    OVERLAP_MODE_NOZZLES, overlap_nozzle_count=nozzles, **BOOM
                )
                self.assertAlmostEqual(overlap, nozzles * 0.5)
                self.assertAlmostEqual(effective_pass_spacing_m(36.0, overlap), spacing)

    def test_two_nozzles_give_one_meter(self):
        overlap = resolve_sprayer_overlap_m(OVERLAP_MODE_NOZZLES, overlap_nozzle_count=2, **BOOM)
        self.assertAlmostEqual(overlap, 1.00)
        self.assertAlmostEqual(effective_pass_spacing_m(36.0, overlap), 35.00)


class ResolverValidationTest(unittest.TestCase):
    def test_nozzles_must_be_below_nozzle_count(self):
        for nozzles in (72, 73):
            with self.subTest(nozzles=nozzles):
                with self.assertRaises(SprayerOverlapError):
                    resolve_sprayer_overlap_m(
                        OVERLAP_MODE_NOZZLES, overlap_nozzle_count=nozzles, **BOOM
                    )
        self.assertAlmostEqual(
            resolve_sprayer_overlap_m(OVERLAP_MODE_NOZZLES, overlap_nozzle_count=71, **BOOM),
            35.5,
        )

    def test_negative_values_and_unknown_mode(self):
        with self.assertRaises(SprayerOverlapError):
            resolve_sprayer_overlap_m(OVERLAP_MODE_NOZZLES, overlap_nozzle_count=-1, **BOOM)
        with self.assertRaises(SprayerOverlapError):
            resolve_sprayer_overlap_m(OVERLAP_MODE_METERS, overlap_m=-0.1, **BOOM)
        with self.assertRaises(SprayerOverlapError):
            resolve_sprayer_overlap_m("auto", **BOOM)

    def test_overlap_must_be_below_boom(self):
        with self.assertRaises(SprayerOverlapError):
            effective_pass_spacing_m(36.0, 36.0)


class SprayerMachineOverlapTest(unittest.TestCase):
    def test_default_meters_mode_is_backward_compatible(self):
        machine = sprayer_36(overlap_m=0.75)
        self.assertEqual(machine.overlap_mode, OVERLAP_MODE_METERS)
        self.assertAlmostEqual(machine.resolved_overlap_m, 0.75)
        self.assertAlmostEqual(machine.effective_pass_spacing_m, 35.25)

    def test_machine_does_not_apply_legacy_auto(self):
        machine = sprayer_36(boom_width_m=24.0)
        self.assertEqual(machine.resolved_overlap_m, 0.0)
        self.assertAlmostEqual(machine.effective_pass_spacing_m, 24.0)

    def test_nozzle_mode_keeps_physical_boom(self):
        machine = sprayer_36(overlap_mode=OVERLAP_MODE_NOZZLES, overlap_nozzle_count=2)
        machine.validate()
        self.assertAlmostEqual(machine.resolved_overlap_m, 1.0)
        self.assertAlmostEqual(machine.effective_pass_spacing_m, 35.0)
        self.assertAlmostEqual(machine.boom_width_m, 36.0)
        self.assertAlmostEqual(machine.operational_width_m, 36.0)
        report = machine.to_dict()
        self.assertEqual(report["overlap_mode"], OVERLAP_MODE_NOZZLES)
        self.assertEqual(report["overlap_nozzle_count"], 2)
        self.assertAlmostEqual(report["effective_pass_spacing_m"], 35.0)

    def test_machine_rejects_invalid_nozzle_overlap(self):
        machine = sprayer_36(overlap_mode=OVERLAP_MODE_NOZZLES, overlap_nozzle_count=72)
        with self.assertRaises(MachineModelError):
            machine.validate()

    def test_none_mode_ignores_overlap_m(self):
        machine = sprayer_36(overlap_m=1.0, overlap_mode=OVERLAP_MODE_NONE)
        self.assertAlmostEqual(machine.effective_pass_spacing_m, 36.0)


class OverlapSideTest(unittest.TestCase):
    def test_first_pass_has_no_overlap_side(self):
        self.assertEqual(
            overlap_side_for_pass(previous_offset_m=None, offset_m=0.0, direction="forward"),
            OVERLAP_SIDE_NONE,
        )

    def test_side_alternates_with_direction(self):
        # Passadas avancando para a esquerda da A-B: anterior fica a direita.
        attrs = pass_overlap_attributes(
            [(0, 0.0, "forward"), (1, -35.0, "reverse"), (2, -70.0, "forward"), (3, -105.0, "reverse")],
            overlap_m=1.0,
            overlap_nozzles=2,
        )
        self.assertEqual(
            [attrs[no]["overlap_side"] for no in range(4)],
            [OVERLAP_SIDE_NONE, OVERLAP_SIDE_LEFT, OVERLAP_SIDE_RIGHT, OVERLAP_SIDE_LEFT],
        )
        self.assertEqual(attrs[0]["overlap_m"], 0.0)
        self.assertEqual(attrs[0]["overlap_nozzles"], 0)
        self.assertEqual(attrs[1]["overlap_m"], 1.0)
        self.assertEqual(attrs[1]["overlap_nozzles"], 2)
        self.assertEqual(attrs[2]["direction"], "forward")

    def test_previous_on_the_right_while_forward_is_right(self):
        self.assertEqual(
            overlap_side_for_pass(previous_offset_m=35.0, offset_m=0.0, direction="forward"),
            OVERLAP_SIDE_RIGHT,
        )

    def test_zero_overlap_marks_all_passes_none(self):
        attrs = pass_overlap_attributes(
            [(-1, 36.0, "forward"), (0, 0.0, "reverse")], overlap_m=0.0, overlap_nozzles=0
        )
        self.assertTrue(all(item["overlap_side"] == OVERLAP_SIDE_NONE for item in attrs.values()))

    def test_segments_of_same_pass_share_attributes(self):
        attrs = pass_overlap_attributes(
            [(0, 0.0, "forward"), (1, -35.0, "reverse"), (1, -35.0, "reverse")],
            overlap_m=1.0,
            overlap_nozzles=2,
        )
        self.assertEqual(sorted(attrs), [0, 1])

    def test_nozzle_equivalent(self):
        self.assertEqual(overlap_nozzle_equivalent(1.0, 0.5), 2)
        self.assertIsNone(overlap_nozzle_equivalent(0.7, 0.5))
        self.assertIsNone(overlap_nozzle_equivalent(1.0, 0.0))

    def test_machine_pass_attributes(self):
        passes = [
            SimpleNamespace(pass_no=0, offset_m=0.0, direction="forward"),
            SimpleNamespace(pass_no=1, offset_m=-35.0, direction="reverse"),
        ]
        machine = sprayer_36(overlap_mode=OVERLAP_MODE_NOZZLES, overlap_nozzle_count=2)
        attrs = machine_pass_overlap_attributes(passes, machine)
        self.assertEqual(attrs[1]["overlap_nozzles"], 2)
        self.assertAlmostEqual(attrs[1]["overlap_m"], 1.0)
        meters = machine_pass_overlap_attributes(passes, sprayer_36(overlap_m=1.0))
        self.assertEqual(meters[1]["overlap_nozzles"], 2)
        self.assertEqual(machine_pass_overlap_attributes(passes, None), {})


if __name__ == "__main__":
    unittest.main()
