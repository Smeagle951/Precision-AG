# -*- coding: utf-8 -*-
"""Testes da Etapa 2: gota, pula-faixa e sequencias alternadas."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.line_geometry import distance, drop_polyline
from plugin.fortsmart_precision.core.parallel_pass_engine import ParallelPassParams, generate_parallel_passes
from plugin.fortsmart_precision.core.pass_sequence_engine import build_pass_sequence, order_passes_for_mode
from plugin.fortsmart_precision.core.turn_path_engine import generate_turn_paths
from plugin.fortsmart_precision.domain.boundary_areas import build_inner_and_headland
from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
from plugin.fortsmart_precision.domain.turn_configuration import (
    PassSequenceMode,
    SafetyMargins,
    TurnConfiguration,
    TurnConfigurationError,
    TurnFinishMode,
    TurnStatus,
    TurnType,
)


def rectangle(width=300.0, height=200.0, x=0.0, y=0.0):
    outer = [
        (x, y),
        (x + width, y),
        (x + width, y + height),
        (x, y + height),
        (x, y),
    ]
    return [(outer, [])]


def _passes_and_areas(*, width=18.0, spacing=18.0, headland_passes=3, field=None):
    field = field or rectangle(400, 240)
    layout = HeadlandLayout(
        pass_count=headland_passes,
        width_m=width,
        effective_spacing_m=spacing,
        mode="parallel_ab",
    )
    areas = build_inner_and_headland(field, layout.reserved_width_m)
    passes = generate_parallel_passes(
        ParallelPassParams(
            polygons=areas.inner_work_area,
            ab_start=(0, 120),
            ab_end=(400, 120),
            pass_spacing_m=spacing,
            operation_width_m=width,
            extension_m=0.0,
        )
    )
    return passes, areas, layout


class TurnPathsEtapa2Test(unittest.TestCase):
    def test_alternating_order_is_odd_then_even(self):
        passes, _, _ = _passes_and_areas()
        ordered = order_passes_for_mode(passes, PassSequenceMode.ALTERNATING)
        nos = [item.pass_no for item in ordered]
        self.assertEqual(sorted(nos), sorted(p.pass_no for p in passes))
        if len(nos) >= 4:
            # Primeiros itens saltam pelo menos uma faixa na numeracao original.
            self.assertGreaterEqual(abs(nos[1] - nos[0]), 2)

    def test_skip_one_sequence_connections(self):
        passes, _, _ = _passes_and_areas()
        connections = build_pass_sequence(passes, PassSequenceMode.SKIP_ONE, skip_passes=1)
        self.assertEqual(len(connections), max(0, len(passes) - 1))
        if connections:
            first = connections[0]
            self.assertNotEqual(first.to_pass.pass_no, first.from_pass.pass_no + 1)

    def test_skip_two_sequence_order(self):
        passes, _, _ = _passes_and_areas()
        ordered = order_passes_for_mode(passes, PassSequenceMode.SKIP_TWO)
        nos = [item.pass_no for item in ordered]
        self.assertEqual(sorted(nos), sorted(p.pass_no for p in passes))
        if len(nos) >= 3:
            self.assertGreaterEqual(abs(nos[1] - nos[0]), 2)

    def test_skip_pass_turn_type_uses_skip_sequence(self):
        passes, areas, _ = _passes_and_areas(headland_passes=3)
        config = TurnConfiguration(
            generate_turns=True,
            finish_mode=TurnFinishMode.INSIDE_HEADLAND,
            turn_type=TurnType.SKIP_PASS,
            sequence_mode=PassSequenceMode.SEQUENTIAL,
            skip_passes=1,
            min_turn_radius_m=8.0,
            safety=SafetyMargins(recommended_clearance_m=2.0),
        )
        result = generate_turn_paths(passes, config, areas)
        self.assertGreater(len(result.turns), 0)
        self.assertEqual(result.report["sequence_mode"], PassSequenceMode.SKIP_ONE.value)
        self.assertTrue(all(turn.turn_type == TurnType.SKIP_PASS.value for turn in result.turns))
        self.assertTrue(all(turn.label == "PULA" for turn in result.turns))

    def test_drop_turn_generates_gota_label(self):
        passes, areas, _ = _passes_and_areas(headland_passes=3)
        config = TurnConfiguration(
            generate_turns=True,
            finish_mode=TurnFinishMode.INSIDE_HEADLAND,
            turn_type=TurnType.DROP,
            min_turn_radius_m=8.0,
            safety=SafetyMargins(recommended_clearance_m=2.0),
        )
        result = generate_turn_paths(passes, config, areas)
        self.assertGreater(len(result.turns), 0)
        self.assertTrue(all(turn.turn_type == TurnType.DROP.value for turn in result.turns))
        self.assertTrue(all(turn.label == "GOTA" for turn in result.turns))
        self.assertTrue(all(len(turn.points) >= 5 for turn in result.turns))

    def test_drop_width_independent_of_pass_spacing(self):
        u_cfg = TurnConfiguration(
            generate_turns=True,
            finish_mode=TurnFinishMode.INSIDE_HEADLAND,
            turn_type=TurnType.U,
            min_turn_radius_m=12.0,
        )
        drop_cfg = TurnConfiguration(
            generate_turns=True,
            finish_mode=TurnFinishMode.INSIDE_HEADLAND,
            turn_type=TurnType.DROP,
            min_turn_radius_m=12.0,
        )
        # Gota: profundidade ~2R, independente do espacamento lateral.
        self.assertAlmostEqual(drop_cfg.required_turn_width_m(10.0), drop_cfg.required_turn_width_m(40.0))
        # U: aumenta quando o espacamento lateral cresce alem do diametro.
        self.assertLess(u_cfg.required_turn_width_m(10.0), u_cfg.required_turn_width_m(40.0))
        self.assertLess(drop_cfg.required_turn_width_m(40.0), u_cfg.required_turn_width_m(40.0))

    def test_drop_polyline_advances_beyond_chord(self):
        start = (0.0, 0.0)
        end = (10.0, 0.0)
        points = drop_polyline(start, end, forward=(0.0, 1.0), radius_m=8.0, segments=20)
        self.assertEqual(points[0], start)
        self.assertEqual(points[-1], end)
        mid = points[len(points) // 2]
        # Apex da gota deve avancar em Y.
        self.assertGreater(mid[1], 5.0)
        self.assertGreater(polyline_length_approx(points), distance(start, end))

    def test_alternating_turns_increase_lateral_spacing(self):
        passes, areas, _ = _passes_and_areas(headland_passes=3)
        seq = generate_turn_paths(
            passes,
            TurnConfiguration(
                generate_turns=True,
                finish_mode=TurnFinishMode.INSIDE_HEADLAND,
                turn_type=TurnType.U,
                sequence_mode=PassSequenceMode.SEQUENTIAL,
                min_turn_radius_m=8.0,
            ),
            areas,
        )
        alt = generate_turn_paths(
            passes,
            TurnConfiguration(
                generate_turns=True,
                finish_mode=TurnFinishMode.INSIDE_HEADLAND,
                turn_type=TurnType.U,
                sequence_mode=PassSequenceMode.ALTERNATING,
                min_turn_radius_m=8.0,
            ),
            areas,
        )
        self.assertGreater(len(seq.turns), 0)
        self.assertGreater(len(alt.turns), 0)
        # Na alternada, a primeira conexao cobre mais de uma faixa.
        first_alt_spacing = abs(alt.connections[0].from_pass.offset_m - alt.connections[0].to_pass.offset_m)
        first_seq_spacing = abs(seq.connections[0].from_pass.offset_m - seq.connections[0].to_pass.offset_m)
        self.assertGreaterEqual(first_alt_spacing, first_seq_spacing)


def polyline_length_approx(points):
    total = 0.0
    for a, b in zip(points, points[1:]):
        total += distance(a, b)
    return total


if __name__ == "__main__":
    unittest.main()
