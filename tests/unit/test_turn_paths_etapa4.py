# -*- coding: utf-8 -*-
"""Testes da Etapa 4: omega, tres pontos, rebocado e milho semente por grupo."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.line_geometry import distance, omega_polyline, three_point_polyline
from plugin.fortsmart_precision.core.parallel_pass_engine import ParallelPassParams, generate_parallel_passes
from plugin.fortsmart_precision.core.pass_sequence_engine import build_pass_sequence, order_passes_for_mode
from plugin.fortsmart_precision.core.seed_corn_turn_engine import (
    generate_seed_corn_group_turns,
    passes_for_seed_group,
)
from plugin.fortsmart_precision.core.turn_path_engine import generate_turn_paths
from plugin.fortsmart_precision.domain.boundary_areas import build_inner_and_headland
from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
from plugin.fortsmart_precision.domain.planting_configuration import PlantingConfiguration
from plugin.fortsmart_precision.domain.seed_corn_planning import (
    SeedCornParams,
    SeedCornPattern,
    generate_seed_corn_plan,
)
from plugin.fortsmart_precision.domain.turn_configuration import (
    PassSequenceMode,
    SafetyMargins,
    TurnConfiguration,
    TurnConfigurationError,
    TurnFinishMode,
    TurnType,
)
from plugin.fortsmart_precision.validators.turn_validator import validate_turn_configuration


def rectangle(width=400.0, height=240.0, x=0.0, y=0.0):
    outer = [
        (x, y),
        (x + width, y),
        (x + width, y + height),
        (x, y + height),
        (x, y),
    ]
    return [(outer, [])]


def _passes_and_areas(*, headland_passes=3):
    field = rectangle(400, 240)
    layout = HeadlandLayout(
        pass_count=headland_passes,
        width_m=18.0,
        effective_spacing_m=18.0,
        mode="parallel_ab",
    )
    areas = build_inner_and_headland(field, layout.reserved_width_m)
    passes = generate_parallel_passes(
        ParallelPassParams(
            polygons=areas.inner_work_area,
            ab_start=(0, 120),
            ab_end=(400, 120),
            pass_spacing_m=18.0,
            operation_width_m=18.0,
            extension_m=0.0,
        )
    )
    return passes, areas


class TurnPathsEtapa4Test(unittest.TestCase):
    def test_omega_turn_label_and_path(self):
        passes, areas = _passes_and_areas()
        config = TurnConfiguration(
            generate_turns=True,
            finish_mode=TurnFinishMode.INSIDE_HEADLAND,
            turn_type=TurnType.OMEGA,
            min_turn_radius_m=8.0,
            safety=SafetyMargins(recommended_clearance_m=2.0),
        )
        result = generate_turn_paths(passes, config, areas)
        self.assertGreater(len(result.turns), 0)
        self.assertTrue(all(turn.label == "OMEGA" for turn in result.turns))
        self.assertTrue(all(len(turn.points) >= 5 for turn in result.turns))

    def test_three_point_is_special_maneuver(self):
        passes, areas = _passes_and_areas()
        config = TurnConfiguration(
            generate_turns=True,
            finish_mode=TurnFinishMode.INSIDE_HEADLAND,
            turn_type=TurnType.THREE_POINT,
            min_turn_radius_m=8.0,
        )
        self.assertTrue(config.is_special_maneuver())
        result = generate_turn_paths(passes, config, areas)
        self.assertGreater(len(result.turns), 0)
        self.assertTrue(all(turn.label == "3P" for turn in result.turns))
        self.assertTrue(all(turn.is_special_maneuver for turn in result.turns))
        report = validate_turn_configuration(config, areas)
        self.assertTrue(any("manobra especial" in warn.lower() for warn in report.warnings))

    def test_towed_implement_increases_required_width(self):
        mounted = TurnConfiguration(
            generate_turns=True,
            finish_mode=TurnFinishMode.INSIDE_HEADLAND,
            turn_type=TurnType.OMEGA,
            min_turn_radius_m=10.0,
            implement_length_m=12.0,
            implement_mounted=True,
        )
        towed = TurnConfiguration(
            generate_turns=True,
            finish_mode=TurnFinishMode.INSIDE_HEADLAND,
            turn_type=TurnType.OMEGA,
            min_turn_radius_m=10.0,
            implement_length_m=12.0,
            implement_mounted=False,
        )
        self.assertGreater(towed.required_turn_width_m(18.0), mounted.required_turn_width_m(18.0))
        self.assertGreater(towed.minimum_extension_m(), mounted.minimum_extension_m())

    def test_blocks_sequence_orders_in_chunks(self):
        passes, _ = _passes_and_areas()
        ordered = order_passes_for_mode(passes, PassSequenceMode.BLOCKS, block_size=3)
        self.assertEqual([p.pass_no for p in ordered], [p.pass_no for p in sorted(passes, key=lambda x: x.pass_no)])
        connections = build_pass_sequence(passes, PassSequenceMode.BLOCKS, block_size=3)
        self.assertTrue(all(conn.block_no >= 1 for conn in connections))

    def test_custom_sequence(self):
        passes, areas = _passes_and_areas()
        nos = [p.pass_no for p in sorted(passes, key=lambda x: x.pass_no)]
        if len(nos) < 3:
            self.skipTest("Poucas passadas")
        custom = (nos[0], nos[2], nos[1])
        config = TurnConfiguration(
            generate_turns=True,
            finish_mode=TurnFinishMode.INSIDE_HEADLAND,
            turn_type=TurnType.U,
            sequence_mode=PassSequenceMode.CUSTOM,
            custom_sequence=custom,
            min_turn_radius_m=6.0,
        )
        result = generate_turn_paths(passes, config, areas)
        self.assertEqual(result.connections[0].from_pass.pass_no, custom[0])
        self.assertEqual(result.connections[0].to_pass.pass_no, custom[1])

    def test_custom_sequence_requires_order(self):
        with self.assertRaises(TurnConfigurationError):
            TurnConfiguration(
                generate_turns=True,
                finish_mode=TurnFinishMode.INSIDE_HEADLAND,
                sequence_mode=PassSequenceMode.CUSTOM,
                custom_sequence=(),
                min_turn_radius_m=8.0,
            ).validate()

    def test_omega_and_three_point_polylines(self):
        start = (0.0, 0.0)
        end = (20.0, 0.0)
        omega = omega_polyline(start, end, forward=(0.0, 1.0), radius_m=8.0)
        three = three_point_polyline(start, end, forward=(0.0, 1.0), radius_m=8.0)
        self.assertEqual(omega[0], start)
        self.assertEqual(omega[-1], end)
        self.assertEqual(three[0], start)
        self.assertEqual(three[-1], end)
        self.assertEqual(len(three), 5)
        self.assertGreater(distance(three[1], three[2]), 0)

    def test_seed_corn_separate_group_turns(self):
        field = rectangle(120, 40)
        plan = generate_seed_corn_plan(
            SeedCornParams(
                polygons=field,
                ab_start=(0, 20),
                ab_end=(120, 20),
                planter=PlantingConfiguration(7, 0.5),
                pattern=SeedCornPattern(("F", "F", "F", "F", "F", "F", "M1")),
                ab_reference="center_planter",
                extension_m=0,
            )
        )
        areas = build_inner_and_headland(field, 18.0)
        female_passes = passes_for_seed_group(plan, "F")
        male_passes = passes_for_seed_group(plan, "M1")
        self.assertGreater(len(female_passes), 0)

        group_configs = {
            "F": TurnConfiguration(
                generate_turns=True,
                finish_mode=TurnFinishMode.INSIDE_HEADLAND,
                turn_type=TurnType.U,
                min_turn_radius_m=6.0,
            ),
            "M1": TurnConfiguration(
                generate_turns=False,
                finish_mode=TurnFinishMode.NONE,
            ),
            "M2": TurnConfiguration(
                generate_turns=True,
                finish_mode=TurnFinishMode.INSIDE_HEADLAND,
                turn_type=TurnType.DROP,
                min_turn_radius_m=6.0,
            ),
        }
        turn_plan = generate_seed_corn_group_turns(plan, areas, group_configs)
        by_group = {item.group: item for item in turn_plan.groups}
        self.assertIn("F", by_group)
        self.assertIn("M1", by_group)
        self.assertGreater(len(by_group["F"].turns), 0)
        self.assertEqual(len(by_group["M1"].turns), 0)
        self.assertEqual(by_group["M1"].result.report.get("message"), "Sem volta automatica.")


if __name__ == "__main__":
    unittest.main()
