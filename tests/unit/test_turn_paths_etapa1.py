# -*- coding: utf-8 -*-
"""Testes da Etapa 1: limites, bordadura e voltas em U."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.line_geometry import arc_polyline, distance
from plugin.fortsmart_precision.core.parallel_pass_engine import ParallelPassParams, generate_parallel_passes
from plugin.fortsmart_precision.core.pass_sequence_engine import build_pass_sequence
from plugin.fortsmart_precision.core.turn_path_engine import TurnPathError, generate_turn_paths
from plugin.fortsmart_precision.domain.boundary_areas import build_inner_and_headland
from plugin.fortsmart_precision.domain.headland_configuration import (
    HeadlandConfiguration,
    HeadlandCreationMode,
    HeadlandGeometryType,
)
from plugin.fortsmart_precision.domain.headland_layout import HeadlandConfigurationError, HeadlandLayout
from plugin.fortsmart_precision.domain.planting_configuration import PlantingConfiguration
from plugin.fortsmart_precision.domain.spraying_configuration import SprayingConfiguration
from plugin.fortsmart_precision.domain.turn_configuration import (
    PassSequenceMode,
    SafetyMargins,
    TurnConfiguration,
    TurnConfigurationError,
    TurnFinishMode,
    TurnStatus,
    TurnType,
)
from plugin.fortsmart_precision.validators.turn_validator import validate_turn_configuration, validate_turn_paths


def rectangle(width=300.0, height=200.0, x=0.0, y=0.0):
    outer = [
        (x, y),
        (x + width, y),
        (x + width, y + height),
        (x, y + height),
        (x, y),
    ]
    return [(outer, [])]


def _passes_and_areas(*, width=18.0, spacing=18.0, headland_passes=2, field=None):
    field = field or rectangle(300, 200)
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
            ab_start=(0, 100),
            ab_end=(300, 100),
            pass_spacing_m=spacing,
            operation_width_m=width,
            extension_m=0.0,
        )
    )
    return passes, areas, layout


class TurnPathsEtapa1Test(unittest.TestCase):
    def test_no_automatic_turn(self):
        passes, areas, _ = _passes_and_areas()
        result = generate_turn_paths(
            passes,
            TurnConfiguration(generate_turns=False, finish_mode=TurnFinishMode.NONE),
            areas,
        )
        self.assertEqual(result.turns, [])
        self.assertEqual(result.report["mode"], "none")

    def test_u_turn_valid_with_wide_headland(self):
        passes, areas, layout = _passes_and_areas(headland_passes=2)
        self.assertGreaterEqual(layout.reserved_width_m, 36.0)
        config = TurnConfiguration(
            generate_turns=True,
            finish_mode=TurnFinishMode.INSIDE_HEADLAND,
            turn_type=TurnType.U,
            min_turn_radius_m=8.0,
            safety=SafetyMargins(recommended_clearance_m=2.0),
        )
        result = generate_turn_paths(passes, config, areas)
        self.assertGreater(len(result.turns), 0)
        self.assertTrue(any(turn.status == TurnStatus.VALID.value for turn in result.turns))
        self.assertFalse(any(turn.is_estimated for turn in result.turns if turn.status == TurnStatus.VALID.value))

    def test_u_turn_impossible_without_space(self):
        passes, areas, layout = _passes_and_areas(headland_passes=1)
        self.assertAlmostEqual(layout.reserved_width_m, 18.0)
        config = TurnConfiguration(
            generate_turns=True,
            finish_mode=TurnFinishMode.INSIDE_HEADLAND,
            turn_type=TurnType.U,
            min_turn_radius_m=15.0,
            safety=SafetyMargins(recommended_clearance_m=2.0, planted_area_m=0.5),
        )
        result = generate_turn_paths(passes, config, areas)
        self.assertGreater(len(result.turns), 0)
        # Largura necessaria ~30.5 m > 18 m disponiveis.
        required = config.required_turn_width_m(18.0)
        self.assertIsNotNone(required)
        self.assertGreater(required, areas.reserved_width_m)
        self.assertTrue(any(turn.status == TurnStatus.IMPOSSIBLE.value for turn in result.turns))

    def test_headland_one_two_three_passes_offsets(self):
        one = HeadlandConfiguration(
            creation_mode=HeadlandCreationMode.PASSES_1,
            width_m=18.0,
            effective_spacing_m=18.0,
        )
        two = HeadlandConfiguration(
            creation_mode=HeadlandCreationMode.PASSES_2,
            width_m=18.0,
            effective_spacing_m=18.0,
        )
        three = HeadlandConfiguration(
            creation_mode=HeadlandCreationMode.PASSES_3,
            width_m=18.0,
            effective_spacing_m=18.0,
        )
        self.assertEqual(one.center_offsets_m(), [9.0])
        self.assertEqual(two.center_offsets_m(), [9.0, 27.0])
        self.assertEqual(three.center_offsets_m(), [9.0, 27.0, 45.0])
        self.assertAlmostEqual(three.reserved_width_m, 54.0)

    def test_sequential_sequence(self):
        passes, areas, _ = _passes_and_areas()
        connections = build_pass_sequence(passes, PassSequenceMode.SEQUENTIAL)
        self.assertEqual(len(connections), max(0, len(passes) - 1))
        if connections:
            self.assertEqual(connections[0].from_pass.pass_no, passes[0].pass_no)
            self.assertEqual(connections[0].to_pass.pass_no, passes[1].pass_no)

    def test_alternating_sequence_orders_odd_then_even(self):
        passes, _, _ = _passes_and_areas()
        connections = build_pass_sequence(passes, PassSequenceMode.ALTERNATING)
        self.assertEqual(len(connections), max(0, len(passes) - 1))
        if len(passes) >= 4:
            ordered_nos = [connections[0].from_pass.pass_no] + [c.to_pass.pass_no for c in connections]
            # Padrao tipico: impares primeiro.
            self.assertEqual(ordered_nos[0], passes[0].pass_no)
            self.assertNotEqual(ordered_nos[1], ordered_nos[0] + 1)

    def test_obstacle_on_curve_marks_impossible(self):
        passes, areas, _ = _passes_and_areas(headland_passes=2)
        config = TurnConfiguration(
            generate_turns=True,
            finish_mode=TurnFinishMode.INSIDE_HEADLAND,
            turn_type=TurnType.U,
            min_turn_radius_m=8.0,
            avoid_obstacles=True,
        )
        # Gera uma volta e coloca obstaculo no meio do arco.
        preliminary = generate_turn_paths(passes, config, areas)
        self.assertGreater(len(preliminary.turns), 0)
        mid = preliminary.turns[0].points[len(preliminary.turns[0].points) // 2]
        obstacle = [
            (
                [
                    (mid[0] - 5, mid[1] - 5),
                    (mid[0] + 5, mid[1] - 5),
                    (mid[0] + 5, mid[1] + 5),
                    (mid[0] - 5, mid[1] + 5),
                    (mid[0] - 5, mid[1] - 5),
                ],
                [],
            )
        ]
        blocked = generate_turn_paths(passes, config, areas, obstacles=obstacle)
        self.assertTrue(any(turn.status == TurnStatus.IMPOSSIBLE.value for turn in blocked.turns))

    def test_outside_boundary_requires_explicit_authorization(self):
        with self.assertRaises(TurnConfigurationError):
            TurnConfiguration(
                generate_turns=True,
                finish_mode=TurnFinishMode.OUTSIDE_BOUNDARY,
                allow_outside_boundary=False,
                turn_type=TurnType.U,
                min_turn_radius_m=8.0,
            ).validate()

    def test_outside_boundary_authorized_config_ok(self):
        TurnConfiguration(
            generate_turns=True,
            finish_mode=TurnFinishMode.OUTSIDE_BOUNDARY,
            allow_outside_boundary=True,
            turn_type=TurnType.U,
            min_turn_radius_m=8.0,
            external_extension_m=30.0,
        ).validate()

    def test_missing_radius_marks_estimated(self):
        passes, areas, _ = _passes_and_areas(headland_passes=2)
        config = TurnConfiguration(
            generate_turns=True,
            finish_mode=TurnFinishMode.INSIDE_HEADLAND,
            turn_type=TurnType.U,
            min_turn_radius_m=None,
        )
        result = generate_turn_paths(passes, config, areas)
        self.assertGreater(len(result.turns), 0)
        self.assertTrue(all(turn.is_estimated for turn in result.turns))
        self.assertTrue(
            all(turn.status == TurnStatus.INSUFFICIENT_DATA.value for turn in result.turns)
        )

    def test_planting_18m_headland_offsets(self):
        planting = PlantingConfiguration(row_count=40, row_spacing_m=0.45)
        cfg = HeadlandConfiguration(
            creation_mode=HeadlandCreationMode.PASSES_3,
            width_m=planting.working_width_m,
            effective_spacing_m=planting.working_width_m,
        )
        self.assertEqual(cfg.center_offsets_m(), [9.0, 27.0, 45.0])

    def test_spraying_36m_with_overlap_offsets(self):
        spraying = SprayingConfiguration(
            boom_width_m=36.0,
            nozzle_count=72,
            nozzle_spacing_m=0.5,
            overlap_value=0.40,
            overlap_unit="m",
            overlap_basis="total",
        )
        cfg = HeadlandConfiguration(
            creation_mode=HeadlandCreationMode.PASSES_3,
            width_m=spraying.boom_width_m,
            effective_spacing_m=spraying.effective_spacing_m,
        )
        offsets = cfg.center_offsets_m()
        self.assertAlmostEqual(offsets[0], 18.0)
        self.assertAlmostEqual(offsets[1], 53.6)
        self.assertAlmostEqual(offsets[2], 89.2)

    def test_irregular_field_and_hole(self):
        outer = [(0, 0), (300, 0), (300, 200), (0, 200), (0, 0)]
        hole = [(120, 80), (180, 80), (180, 120), (120, 120), (120, 80)]
        field = [(outer, [hole])]
        passes, areas, _ = _passes_and_areas(headland_passes=1, field=field)
        self.assertGreater(len(passes), 0)
        config = TurnConfiguration(
            generate_turns=True,
            finish_mode=TurnFinishMode.INSIDE_HEADLAND,
            min_turn_radius_m=6.0,
        )
        result = generate_turn_paths(passes, config, areas)
        self.assertGreaterEqual(len(result.turns), 0)

    def test_missing_headland_raises(self):
        passes, areas, _ = _passes_and_areas(headland_passes=0)
        config = TurnConfiguration(
            generate_turns=True,
            finish_mode=TurnFinishMode.INSIDE_HEADLAND,
            min_turn_radius_m=8.0,
        )
        with self.assertRaises(TurnPathError):
            generate_turn_paths(passes, config, areas)

    def test_follow_boundary_geometry_not_in_etapa1(self):
        with self.assertRaises(HeadlandConfigurationError):
            HeadlandConfiguration(
                creation_mode=HeadlandCreationMode.PASSES_1,
                geometry_type=HeadlandGeometryType.FOLLOW_BOUNDARY,
                width_m=18.0,
            ).validate()

    def test_arc_polyline_semicircle(self):
        points = arc_polyline((0.0, 0.0), (10.0, 0.0), bulge_left=True, segments=8)
        self.assertEqual(points[0], (0.0, 0.0))
        self.assertEqual(points[-1], (10.0, 0.0))
        mid = points[len(points) // 2]
        self.assertAlmostEqual(mid[0], 5.0, places=5)
        self.assertAlmostEqual(mid[1], 5.0, places=5)
        self.assertAlmostEqual(distance(points[0], points[-1]), 10.0)

    def test_validator_report_and_outside_without_auth(self):
        report = validate_turn_configuration(
            TurnConfiguration(generate_turns=False, finish_mode=TurnFinishMode.NONE)
        )
        self.assertTrue(report.ok)
        blocked = validate_turn_configuration(
            TurnConfiguration(
                generate_turns=True,
                finish_mode=TurnFinishMode.OUTSIDE_BOUNDARY,
                allow_outside_boundary=False,
                turn_type=TurnType.U,
            )
        )
        # validate() ja falha no dominio; o wrapper captura.
        self.assertFalse(blocked.ok)

    def test_validator_on_generated_turns(self):
        passes, areas, _ = _passes_and_areas(headland_passes=2)
        config = TurnConfiguration(
            generate_turns=True,
            finish_mode=TurnFinishMode.INSIDE_HEADLAND,
            min_turn_radius_m=8.0,
        )
        result = generate_turn_paths(passes, config, areas)
        report = validate_turn_paths(result, config, areas, allow_save_invalid=True)
        self.assertIn("savable_count", report.as_dict())

    def test_boundary_areas_point_in_headland(self):
        areas = build_inner_and_headland(rectangle(100, 60), 10.0)
        self.assertTrue(areas.point_in_headland((5.0, 30.0)))
        self.assertTrue(areas.point_in_inner((50.0, 30.0)))
        self.assertFalse(areas.point_in_headland((50.0, 30.0)))


if __name__ == "__main__":
    unittest.main()
