# -*- coding: utf-8 -*-
"""Metas de tempo do pipeline: nunca pode ficar 'carregando eternamente'.

O objetivo destes testes nao e cronometrar a maquina do usuario, e sim travar
regressoes algoritmicas: se alguem reintroduzir a varredura
`N passadas x M obstaculos` ou densificacao fixa, o tempo estoura.
"""

from __future__ import annotations

import time
import unittest

from plugin.fortsmart_precision.core.boundary_engine import build_boundary_plan
from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
from plugin.fortsmart_precision.domain.avoidance_configuration import (
    AvoidanceConfiguration,
    AvoidanceMode,
)
from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, SprayerMachine
from plugin.fortsmart_precision.domain.obstacle_model import obstacle_from_point
from plugin.fortsmart_precision.domain.path_smoothing_configuration import (
    PathSmoothingConfiguration,
    SmoothingLevel,
)
from plugin.fortsmart_precision.domain.precision_project import (
    ABLine,
    FieldGeometry,
    PrecisionOperation,
    PrecisionProject,
)
from plugin.fortsmart_precision.domain.processing_profile import (
    final_profile,
    preview_profile,
)


def _field(width=1200.0, height=900.0):
    outer = [(0.0, 0.0), (width, 0.0), (width, height), (0.0, height), (0.0, 0.0)]
    return [(outer, [])]


def _sprayer():
    return SprayerMachine(
        machine_id="s36",
        name="Barra 36",
        nozzle_count=72,
        nozzle_spacing_m=0.5,
        boom_width_m=36.0,
        track=MachineTrack(track_width_m=3.0, tire_width_m=0.37),
    )


def _spray_operation():
    return PrecisionOperation(
        operation_id="spraying",
        machine=_sprayer(),
        extension_m=10.0,
        headland=HeadlandLayout(
            pass_count=1,
            width_m=36.0,
            effective_spacing_m=36.0,
            mode="follow_boundary",
        ),
    )


def _scattered_obstacles(count: int):
    """Obstaculos espalhados: a maioria longe de qualquer passada especifica."""
    out = []
    for i in range(count):
        x = 60.0 + (i * 137) % 1080
        y = 60.0 + (i * 271) % 780
        out.append(
            obstacle_from_point(
                (float(x), float(y)),
                obstacle_radius_m=1.0,
                safety_margin_m=0.5,
                obstacle_id=f"obs{i}",
            )
        )
    return tuple(out)


def _project(obstacles=(), profile=None):
    return PrecisionProject(
        field=FieldGeometry(
            field_boundary=_field(),
            operational_boundary=_field(),
            crs_authid="EPSG:31982",
        ),
        ab_line=ABLine(start=(0.0, 450.0), end=(1200.0, 450.0)),
        spraying=_spray_operation(),
        obstacles=obstacles,
        avoidance=AvoidanceConfiguration(mode=AvoidanceMode.CONCENTRIC_RING),
        line_smoothing=PathSmoothingConfiguration(level=SmoothingLevel.LOW),
        processing=profile or final_profile(),
    )


class BoundaryTargetTest(unittest.TestCase):
    def test_headland_under_one_second(self):
        started = time.perf_counter()
        plan = build_boundary_plan(
            _field(), _spray_operation(), (0.0, 450.0), (1200.0, 450.0)
        )
        elapsed = time.perf_counter() - started
        self.assertTrue(plan.headland_centerlines)
        self.assertLess(elapsed, 1.5, f"bordadura levou {elapsed:.2f}s")


class ObstacleScalingTargetTest(unittest.TestCase):
    def test_many_obstacles_do_not_multiply_by_passes(self):
        """60 obstaculos x ~25 passadas: com indice espacial isso nao explode."""
        obstacles = _scattered_obstacles(60)
        started = time.perf_counter()
        result = run_precision_lines(_project(obstacles))
        elapsed = time.perf_counter() - started
        self.assertGreater(len(result.spraying_passes), 10)
        self.assertLess(
            elapsed,
            25.0,
            f"pulverizacao com {len(obstacles)} obstaculos levou {elapsed:.2f}s",
        )

    def test_obstacles_far_from_field_cost_almost_nothing(self):
        """Obstaculos fora do talhao nao podem pesar no calculo."""
        far = tuple(
            obstacle_from_point(
                (50000.0 + i * 40.0, 50000.0),
                obstacle_radius_m=1.0,
                safety_margin_m=0.5,
                obstacle_id=f"far{i}",
            )
            for i in range(120)
        )
        baseline_start = time.perf_counter()
        run_precision_lines(_project())
        baseline = time.perf_counter() - baseline_start

        with_far_start = time.perf_counter()
        result = run_precision_lines(_project(far))
        with_far = time.perf_counter() - with_far_start

        self.assertEqual(len(result.avoided_paths), 0)
        # Tolerancia generosa: o ponto e nao escalar com o numero de obstaculos.
        self.assertLess(with_far, max(baseline * 3.0, baseline + 5.0))


class ProcessingModeTargetTest(unittest.TestCase):
    def test_preview_is_not_slower_than_final(self):
        obstacles = _scattered_obstacles(24)
        final_start = time.perf_counter()
        final = run_precision_lines(_project(obstacles, final_profile()))
        final_elapsed = time.perf_counter() - final_start

        preview_start = time.perf_counter()
        preview = run_precision_lines(_project(obstacles, preview_profile()))
        preview_elapsed = time.perf_counter() - preview_start

        self.assertEqual(
            len(preview.spraying_passes),
            len(final.spraying_passes),
            "modo Rapido nao pode perder passadas",
        )
        self.assertLessEqual(preview_elapsed, final_elapsed + 2.0)


if __name__ == "__main__":
    unittest.main()
