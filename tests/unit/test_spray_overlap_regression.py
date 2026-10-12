# -*- coding: utf-8 -*-
"""Regressao da pulverizacao: baseline capturado ANTES do transpasse por bicos.

Talhao retangular 600 x 400 m em CRS metrico, barra 36 m (72 x 0,50 m),
transpasse 0, sem desvio de obstaculos, bordadura LEGACY. Os numeros abaixo
foram medidos no motor antes da SKILL 1 e devem permanecer identicos com os
valores padrao (faixa para fora = 0).
"""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
from plugin.fortsmart_precision.domain.machine_model import SprayerMachine
from plugin.fortsmart_precision.domain.precision_project import (
    ABLine,
    FieldGeometry,
    PrecisionOperation,
    PrecisionProject,
)
from plugin.fortsmart_precision.domain.sprayer_traffic_configuration import (
    SprayerTrafficConfiguration,
)

FIELD = [([(0.0, 0.0), (600.0, 0.0), (600.0, 400.0), (0.0, 400.0), (0.0, 0.0)], [])]


def _length(points) -> float:
    return sum(
        ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 for a, b in zip(points, points[1:])
    )


def spray_result(*, overlap_m: float, headland_passes: int, **headland_kwargs):
    boom = 36.0
    traffic = SprayerTrafficConfiguration(
        boom_width_m=boom, tire_width_m=0.37, inner_clearance_m=2.70, outer_width_m=3.43
    )
    machine = SprayerMachine(
        machine_id="s36",
        name="Barra 36 m",
        nozzle_count=72,
        nozzle_spacing_m=0.5,
        boom_width_m=boom,
        track=traffic.to_machine_track(),
        overlap_m=overlap_m,
        traffic=traffic,
    )
    headland = HeadlandLayout(
        pass_count=headland_passes,
        width_m=boom if headland_passes else 0.0,
        effective_spacing_m=headland_kwargs.pop("effective_spacing_m", boom) if headland_passes else None,
        mode="follow_boundary" if headland_passes else "none",
        **headland_kwargs,
    )
    project = PrecisionProject(
        field=FieldGeometry(field_boundary=FIELD, operational_boundary=FIELD, crs_authid="EPSG:31982"),
        ab_line=ABLine(start=(0.0, 200.0), end=(600.0, 200.0)),
        spraying=PrecisionOperation(
            operation_id="spraying", machine=machine, headland=headland, extension_m=10.0
        ),
    )
    return run_precision_lines(project)


def summary(result) -> dict[str, object]:
    lines = result.boundary.headland_centerlines if result.boundary else ()
    return {
        "pass_count": len(result.spraying_passes),
        "pass_total_m": round(sum(_length(p.line_points()) for p in result.spraying_passes), 3),
        "pass_offsets": sorted(round(p.offset_m, 3) + 0.0 for p in result.spraying_passes),
        "headland_offsets": [round(line.offset_from_outer_m, 3) for line in lines],
        "headland_lengths": [round(line.length_m(), 3) for line in lines],
        "reserved": round(result.boundary.reserved_width_m, 3) if result.boundary else None,
        "tire_tracks": len(result.tire_tracks),
    }


BASELINE = {
    (0.0, 1): {
        "pass_count": 9,
        "pass_total_m": 5580.0,
        "pass_offsets": [-144.0, -108.0, -72.0, -36.0, 0.0, 36.0, 72.0, 108.0, 144.0],
        "headland_offsets": [18.0],
        "headland_lengths": [1856.0],
        "reserved": 36.0,
        "tire_tracks": 20,
    },
    (0.0, 2): {
        "pass_count": 7,
        "pass_total_m": 4340.0,
        "pass_offsets": [-108.0, -72.0, -36.0, 0.0, 36.0, 72.0, 108.0],
        "headland_offsets": [18.0, 54.0],
        "headland_lengths": [1856.0, 1568.0],
        "reserved": 72.0,
        "tire_tracks": 18,
    },
    (0.0, 0): {
        "pass_count": 11,
        "pass_total_m": 6820.0,
        "pass_offsets": [
            -180.0, -144.0, -108.0, -72.0, -36.0, 0.0, 36.0, 72.0, 108.0, 144.0, 180.0
        ],
        "headland_offsets": [],
        "headland_lengths": [],
        "reserved": None,
        "tire_tracks": 22,
    },
    (1.0, 1): {
        "pass_count": 9,
        "pass_total_m": 5580.0,
        "pass_offsets": [-140.0, -105.0, -70.0, -35.0, 0.0, 35.0, 70.0, 105.0, 140.0],
        "headland_offsets": [18.0],
        "headland_lengths": [1856.0],
        "reserved": 36.0,
        "tire_tracks": 20,
    },
}


class SprayRegressionBaselineTest(unittest.TestCase):
    def test_default_settings_match_pre_skill_baseline(self):
        for (overlap, passes), expected in BASELINE.items():
            with self.subTest(overlap=overlap, passes=passes):
                self.assertEqual(
                    summary(spray_result(overlap_m=overlap, headland_passes=passes)), expected
                )


if __name__ == "__main__":
    unittest.main()
