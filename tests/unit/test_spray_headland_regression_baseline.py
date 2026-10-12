# -*- coding: utf-8 -*-
"""Regressao da aplicacao (SKILL 3): baseline capturado ANTES da cabeceira.

Talhao 600 x 400 m (EPSG:31982), barra 36 m (72 x 0,50 m), bordadura de 1
passada, extensao 10 m. ``tests/fixtures/spray_headland_baseline.json`` foi
gravado com o motor anterior a SKILL 3
(``python -m tests.unit.test_spray_headland_regression_baseline --capture``).

Contrato: transpasse antigo, faixa externa = 0, desvio spray desligado e
cabeceira manual (padrao) reproduzem exatamente o resultado anterior —
passadas, bordadura, rastros de pneus (geometria) e tramlines/shutoff.
Com o desvio minimo ligado, as passadas desviadas continuam gerando os
mesmos rastros de pneus.
"""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
from plugin.fortsmart_precision.domain.avoidance_configuration import (
    AvoidanceConfiguration,
    AvoidanceMode,
)
from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
from plugin.fortsmart_precision.domain.machine_model import (
    MachineTrack,
    PlanterMachine,
    SprayerMachine,
)
from plugin.fortsmart_precision.domain.obstacle_model import obstacle_from_point
from plugin.fortsmart_precision.domain.precision_project import (
    ABLine,
    FieldGeometry,
    PrecisionOperation,
    PrecisionProject,
)
from plugin.fortsmart_precision.domain.processing_profile import preview_profile
from plugin.fortsmart_precision.domain.sprayer_traffic_configuration import (
    SprayerTrafficConfiguration,
)

BASELINE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "spray_headland_baseline.json"
FIELD = [([(0.0, 0.0), (600.0, 0.0), (600.0, 400.0), (0.0, 400.0), (0.0, 0.0)], [])]


def sprayer(**kwargs) -> SprayerMachine:
    traffic = SprayerTrafficConfiguration(
        boom_width_m=36.0, tire_width_m=0.37, inner_clearance_m=2.70, outer_width_m=3.43
    )
    values = dict(
        machine_id="s36",
        name="Barra 36 m",
        nozzle_count=72,
        nozzle_spacing_m=0.5,
        boom_width_m=36.0,
        track=traffic.to_machine_track(),
        overlap_m=0.0,
        traffic=traffic,
    )
    values.update(kwargs)
    return SprayerMachine(**values)


def spraying_op(machine: SprayerMachine | None = None) -> PrecisionOperation:
    return PrecisionOperation(
        operation_id="spraying",
        machine=machine or sprayer(),
        headland=HeadlandLayout(
            pass_count=1, width_m=36.0, effective_spacing_m=36.0, mode="follow_boundary"
        ),
        extension_m=10.0,
    )


def planting_op() -> PrecisionOperation:
    return PrecisionOperation(
        operation_id="planting",
        machine=PlanterMachine(
            machine_id="p9",
            name="Plantadeira 9 m",
            row_count=18,
            row_spacing_m=0.5,
            track=MachineTrack(track_width_m=2.0, tire_width_m=0.35),
            informed_operational_width_m=9.0,
        ),
        headland=HeadlandLayout(
            pass_count=1, width_m=9.0, effective_spacing_m=9.0, mode="follow_boundary"
        ),
        extension_m=5.0,
    )


def obstacles():
    return tuple(
        obstacle_from_point(
            center, obstacle_radius_m=0.5, safety_margin_m=1.0, obstacle_id=f"poste_{index}"
        )
        for index, center in enumerate(((300.0, 200.0), (150.0, 125.0), (450.0, 290.0)), start=1)
    )


SPRAY_OFF = AvoidanceConfiguration(mode=AvoidanceMode.NONE)
SPRAY_MINIMUM = AvoidanceConfiguration(
    mode=AvoidanceMode.CONCENTRIC_RING, minimum_turn_radius_m=8.0, minimum_deviation=True
)


def build_project(name: str, **overrides) -> PrecisionProject:
    machine = sprayer(sprayer_minimum_turn_radius_m=8.0) if name == "spray_minimum" else sprayer()
    values = dict(
        field=FieldGeometry(field_boundary=FIELD, operational_boundary=FIELD, crs_authid="EPSG:31982"),
        ab_line=ABLine(start=(0.0, 200.0), end=(600.0, 200.0)),
        spraying=spraying_op(machine),
        avoidance=SPRAY_OFF,
    )
    if name == "spray_minimum":
        values.update(obstacles=obstacles(), avoidance=SPRAY_MINIMUM)
    if name == "combined":
        values.update(planting=planting_op(), processing=preview_profile())
    values.update(overrides)
    return PrecisionProject(**values)


SCENARIOS = ("spray_default", "spray_minimum", "combined")


def _length(points) -> float:
    return sum(
        ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 for a, b in zip(points, points[1:])
    )


def _digest(polylines) -> str:
    hasher = hashlib.sha1()
    for pts in polylines:
        for x, y in pts:
            hasher.update(f"{x:.3f},{y:.3f};".encode("ascii"))
        hasher.update(b"|")
    return hasher.hexdigest()


def _lines(polylines) -> dict[str, object]:
    polylines = [tuple(p) for p in polylines]
    return {
        "count": len(polylines),
        "total_m": round(sum(_length(p) for p in polylines), 3),
        "digest": _digest(polylines),
    }


def summary(result) -> dict[str, object]:
    plan = result.spraying_boundary
    tracks = sorted(result.tire_tracks, key=lambda t: (str(t.pass_id), str(t.side)))
    return {
        "passes": _lines(p.line_points() for p in result.spraying_passes),
        "headland": _lines(
            line.line_points() for line in (plan.headland_centerlines if plan else ())
        ),
        "tire_tracks": _lines(t.points for t in tracks),
        "tire_track_sides": sorted({str(t.side) for t in tracks}),
        "spray_avoided": len([a for a in result.avoided_paths if a.operation_id == "spraying"]),
        "tramlines": len(result.tramline_zones),
        "shutoff": len(result.shutoff_segments),
    }


def capture() -> dict[str, dict[str, object]]:
    return {name: summary(run_precision_lines(build_project(name))) for name in SCENARIOS}


class SprayHeadlandRegressionBaselineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))

    def test_default_application_is_identical(self):
        result = run_precision_lines(build_project("spray_default"))
        self.assertEqual(summary(result), self.baseline["spray_default"])

    def test_detoured_passes_keep_tire_tracks(self):
        result = run_precision_lines(build_project("spray_minimum"))
        self.assertEqual(summary(result), self.baseline["spray_minimum"])
        self.assertGreater(self.baseline["spray_minimum"]["spray_avoided"], 0)

    def test_planting_plus_spraying_tracks_and_tramlines_are_identical(self):
        result = run_precision_lines(build_project("combined"))
        self.assertEqual(summary(result), self.baseline["combined"])


if __name__ == "__main__":
    if "--capture" in sys.argv:
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(json.dumps(capture(), indent=2, sort_keys=True), encoding="utf-8")
        print(f"baseline gravado em {BASELINE_PATH}")
    else:
        unittest.main()
