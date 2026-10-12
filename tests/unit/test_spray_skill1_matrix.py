# -*- coding: utf-8 -*-
"""Regressao SKILL 1 no motor completo: transpasse por bicos x faixa externa x bordadura.

Complementa os testes de resolver/layout: aqui as combinacoes passam pelo
gerador (``run_precision_lines`` / ``build_boundary_plan``) com a barra de
36 m (72 bicos x 0,50 m) no talhao 600 x 400 m (EPSG:31982).
"""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.boundary_engine import build_boundary_plan
from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
from plugin.fortsmart_precision.domain.precision_project import (
    ABLine,
    FieldGeometry,
    PrecisionOperation,
    PrecisionProject,
)
from plugin.fortsmart_precision.domain.sprayer_overlap import OVERLAP_MODE_NOZZLES
from tests.unit.test_spray_headland_outside_overlap import FIELD, distances_to_field_boundary
from tests.unit.test_sprayer_overlap import sprayer_36


def _operation(nozzles: int, passes: int, outside: float) -> PrecisionOperation:
    machine = sprayer_36(overlap_mode=OVERLAP_MODE_NOZZLES, overlap_nozzle_count=nozzles)
    return PrecisionOperation(
        operation_id="spraying",
        machine=machine,
        headland=HeadlandLayout(
            pass_count=passes,
            width_m=36.0,
            effective_spacing_m=machine.effective_pass_spacing_m,
            mode="follow_boundary",
            outside_overlap_m=outside,
        ),
    )


class NozzleOverlapPipelineTest(unittest.TestCase):
    def test_zero_to_four_nozzles_set_pass_spacing(self):
        for nozzles in range(5):
            with self.subTest(nozzles=nozzles):
                op = _operation(nozzles, 1, 0.0)
                result = run_precision_lines(PrecisionProject(
                    field=FieldGeometry(field_boundary=FIELD, operational_boundary=FIELD, crs_authid="EPSG:31982"),
                    ab_line=ABLine(start=(0.0, 200.0), end=(600.0, 200.0)),
                    spraying=op,
                ))
                spacing = 36.0 - 0.5 * nozzles
                offsets = sorted({round(p.offset_m, 6) for p in result.spraying_passes})
                self.assertGreater(len(offsets), 2)
                for a, b in zip(offsets, offsets[1:]):
                    self.assertAlmostEqual(b - a, spacing, places=6)
                # A barra fisica continua 36 m; so o passo muda.
                self.assertAlmostEqual(op.machine.boom_width_m, 36.0)
                self.assertTrue(result.tire_tracks)


class OutsideBandHeadlandPassesTest(unittest.TestCase):
    def test_outside_band_times_headland_passes(self):
        for outside in (0.0, 0.5, 1.0):
            for passes in (1, 2, 3):
                with self.subTest(outside=outside, passes=passes):
                    plan = build_boundary_plan(FIELD, _operation(2, passes, outside), (0.0, 200.0), (600.0, 200.0))
                    lines = sorted(plan.headland_centerlines, key=lambda line: line.pass_no)
                    self.assertEqual(len(lines), passes)
                    expected = [18.0 - outside + k * 35.0 for k in range(passes)]
                    for line, value in zip(lines, expected):
                        low, high = distances_to_field_boundary(line.line_points())
                        self.assertAlmostEqual(low, value, places=6)
                        self.assertAlmostEqual(high, value, places=6)
                    self.assertAlmostEqual(plan.reserved_width_m, expected[-1] + 18.0)


if __name__ == "__main__":
    unittest.main()
