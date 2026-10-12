# -*- coding: utf-8 -*-
"""Testes da Etapa 3: volta fora do limite e area externa autorizada."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.parallel_pass_engine import ParallelPassParams, generate_parallel_passes
from plugin.fortsmart_precision.core.turn_path_engine import TurnPathError, generate_turn_paths
from plugin.fortsmart_precision.domain.boundary_areas import build_inner_and_headland
from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
from plugin.fortsmart_precision.domain.turn_configuration import (
    SafetyMargins,
    TurnConfiguration,
    TurnConfigurationError,
    TurnFinishMode,
    TurnStatus,
    TurnType,
)
from plugin.fortsmart_precision.validators.turn_validator import validate_turn_configuration


def rectangle(width=300.0, height=200.0, x=0.0, y=0.0):
    outer = [
        (x, y),
        (x + width, y),
        (x + width, y + height),
        (x, y + height),
        (x, y),
    ]
    return [(outer, [])]


def external_strip(field_width=300.0, height=40.0, y=-40.0):
    """Faixa externa abaixo do talhao (manobra autorizada)."""
    return rectangle(field_width, height, x=0.0, y=y)


def _passes_and_areas(*, reserved_passes=0, with_external=True, field=None):
    field = field or rectangle(300, 200)
    layout = HeadlandLayout(
        pass_count=reserved_passes,
        width_m=18.0,
        effective_spacing_m=18.0,
        mode="parallel_ab" if reserved_passes else "none",
    )
    external = external_strip() if with_external else None
    # Para volta externa, trabalhar sobre o limte operacional completo.
    areas = build_inner_and_headland(field, layout.reserved_width_m, external_turn_area=external)
    work = areas.inner_work_area or field
    passes = generate_parallel_passes(
        ParallelPassParams(
            polygons=work,
            ab_start=(0, 100),
            ab_end=(300, 100),
            pass_spacing_m=18.0,
            operation_width_m=18.0,
            extension_m=0.0,
        )
    )
    return passes, areas, layout


class TurnPathsEtapa3Test(unittest.TestCase):
    def test_outside_without_authorization_blocked(self):
        with self.assertRaises(TurnConfigurationError):
            TurnConfiguration(
                generate_turns=True,
                finish_mode=TurnFinishMode.OUTSIDE_BOUNDARY,
                allow_outside_boundary=False,
                min_turn_radius_m=8.0,
            ).validate()

    def test_outside_without_external_area_raises(self):
        passes, areas, _ = _passes_and_areas(with_external=False)
        config = TurnConfiguration(
            generate_turns=True,
            finish_mode=TurnFinishMode.OUTSIDE_BOUNDARY,
            allow_outside_boundary=True,
            turn_type=TurnType.U,
            min_turn_radius_m=8.0,
            external_extension_m=30.0,
            tractor_length_m=6.0,
        )
        with self.assertRaises(TurnPathError):
            generate_turn_paths(passes, config, areas)

    def test_authorized_external_area_generates_outside_turns(self):
        passes, areas, _ = _passes_and_areas(with_external=True)
        config = TurnConfiguration(
            generate_turns=True,
            finish_mode=TurnFinishMode.OUTSIDE_BOUNDARY,
            allow_outside_boundary=True,
            turn_type=TurnType.U,
            min_turn_radius_m=8.0,
            external_extension_m=30.0,
            extension_before_m=30.0,
            extension_after_m=30.0,
            tractor_length_m=6.0,
            safety=SafetyMargins(recommended_clearance_m=2.0, outer_boundary_m=0.0),
        )
        result = generate_turn_paths(passes, config, areas)
        self.assertGreater(len(result.turns), 0)
        self.assertTrue(all(turn.outside_boundary for turn in result.turns))
        self.assertTrue(all(turn.turn_location == "external" for turn in result.turns))

    def test_extension_20m_insufficient(self):
        passes, areas, _ = _passes_and_areas(with_external=True)
        config = TurnConfiguration(
            generate_turns=True,
            finish_mode=TurnFinishMode.OUTSIDE_BOUNDARY,
            allow_outside_boundary=True,
            turn_type=TurnType.U,
            min_turn_radius_m=15.0,
            external_extension_m=20.0,
            extension_before_m=20.0,
            extension_after_m=20.0,
            tractor_length_m=10.0,
            implement_length_m=12.0,
            safety=SafetyMargins(outer_boundary_m=2.0),
        )
        status = config.extension_status()
        self.assertEqual(status["status"], "insufficient")
        self.assertGreater(status["minimum_m"], 20.0)

        result = generate_turn_paths(passes, config, areas)
        self.assertTrue(any(turn.status == TurnStatus.IMPOSSIBLE.value for turn in result.turns))

        report = validate_turn_configuration(config, areas)
        self.assertFalse(report.ok)
        self.assertTrue(any("insuficiente" in err.lower() for err in report.errors))

    def test_extension_default_is_configurable_warning(self):
        passes, areas, _ = _passes_and_areas(with_external=True)
        config = TurnConfiguration(
            generate_turns=True,
            finish_mode=TurnFinishMode.OUTSIDE_BOUNDARY,
            allow_outside_boundary=True,
            min_turn_radius_m=5.0,
            external_extension_m=20.0,
            extension_before_m=20.0,
            extension_after_m=20.0,
            tractor_length_m=4.0,
        )
        # Com raio 5 e trator 4, minima ~5+2.5=7.5 < 20 -> ok, mas aviso do padrao.
        report = validate_turn_configuration(config, areas)
        self.assertTrue(any("padrao" in warn.lower() or "20" in warn for warn in report.warnings))

    def test_maneuver_area_mode_requires_flag_and_polygon(self):
        passes, areas, _ = _passes_and_areas(with_external=True)
        with self.assertRaises(TurnConfigurationError):
            TurnConfiguration(
                generate_turns=True,
                finish_mode=TurnFinishMode.MANEUVER_AREA,
                use_maneuver_area=False,
                min_turn_radius_m=8.0,
            ).validate()

        config = TurnConfiguration(
            generate_turns=True,
            finish_mode=TurnFinishMode.MANEUVER_AREA,
            use_maneuver_area=True,
            allow_outside_boundary=True,
            turn_type=TurnType.U,
            min_turn_radius_m=8.0,
            external_extension_m=30.0,
            tractor_length_m=5.0,
        )
        result = generate_turn_paths(passes, config, areas)
        self.assertGreater(len(result.turns), 0)

    def test_minimum_extension_formula(self):
        config = TurnConfiguration(
            generate_turns=True,
            finish_mode=TurnFinishMode.OUTSIDE_BOUNDARY,
            allow_outside_boundary=True,
            min_turn_radius_m=10.0,
            tractor_length_m=6.0,
            implement_length_m=8.0,
            safety=SafetyMargins(outer_boundary_m=1.0),
        )
        # 10 + max(7, 5) + 1 = 18
        self.assertAlmostEqual(config.minimum_extension_m(), 18.0)

    def test_outside_drop_turn(self):
        passes, areas, _ = _passes_and_areas(with_external=True)
        config = TurnConfiguration(
            generate_turns=True,
            finish_mode=TurnFinishMode.OUTSIDE_BOUNDARY,
            allow_outside_boundary=True,
            turn_type=TurnType.DROP,
            min_turn_radius_m=8.0,
            external_extension_m=35.0,
            tractor_length_m=5.0,
        )
        result = generate_turn_paths(passes, config, areas)
        self.assertGreater(len(result.turns), 0)
        self.assertTrue(all(turn.label == "GOTA" for turn in result.turns))
        self.assertTrue(all(turn.outside_boundary for turn in result.turns))


if __name__ == "__main__":
    unittest.main()
