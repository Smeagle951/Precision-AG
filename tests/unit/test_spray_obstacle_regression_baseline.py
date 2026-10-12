# -*- coding: utf-8 -*-
"""Regressao do desvio de pulverizacao (SKILL 2): baseline capturado ANTES.

Talhao 600 x 400 m em CRS metrico (EPSG:31982), barra 36 m, plantadeira 9 m,
tres postes RTK (raio 0,50 m + margem 1,00 m). O arquivo
``tests/fixtures/spray_obstacle_baseline.json`` foi gravado com o motor
anterior a SKILL 2 (``python -m tests.unit.test_spray_obstacle_regression_baseline``).

Contrato:
- desvio de pulverizacao DESLIGADO: saida identica ao baseline;
- modos legados ligados (anel curto / giro 360°): identicos ao baseline;
- plantio: identico em todos os casos, inclusive com o novo desvio minimo da
  pulverizacao ligado no mesmo projeto.
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
from plugin.fortsmart_precision.domain.planting_avoidance_configuration import (
    PlantingAvoidanceConfiguration,
    PlantingAvoidanceStrategy,
)
from plugin.fortsmart_precision.domain.planting_kinematics import PlantingKinematics
from plugin.fortsmart_precision.domain.precision_project import (
    ABLine,
    FieldGeometry,
    PrecisionOperation,
    PrecisionProject,
)
from plugin.fortsmart_precision.domain.processing_profile import final_profile, preview_profile

BASELINE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "spray_obstacle_baseline.json"
FIELD = [([(0.0, 0.0), (600.0, 0.0), (600.0, 400.0), (0.0, 400.0), (0.0, 0.0)], [])]


def _obstacles():
    return tuple(
        obstacle_from_point(
            center,
            obstacle_radius_m=0.5,
            safety_margin_m=1.0,
            obstacle_id=f"poste_{index}",
        )
        for index, center in enumerate(((300.0, 200.0), (150.0, 125.0), (450.0, 290.0)), start=1)
    )


def _sprayer() -> SprayerMachine:
    return SprayerMachine(
        machine_id="s36",
        name="Barra 36 m",
        nozzle_count=72,
        nozzle_spacing_m=0.5,
        boom_width_m=36.0,
        track=MachineTrack(track_width_m=3.0, tire_width_m=0.5),
    )


def _planter() -> PlanterMachine:
    return PlanterMachine(
        machine_id="p9",
        name="Plantadeira 9 m",
        row_count=18,
        row_spacing_m=0.5,
        track=MachineTrack(track_width_m=2.0, tire_width_m=0.35),
        informed_operational_width_m=9.0,
    )


def _spraying_op() -> PrecisionOperation:
    return PrecisionOperation(
        operation_id="spraying",
        machine=_sprayer(),
        headland=HeadlandLayout(
            pass_count=1, width_m=36.0, effective_spacing_m=36.0, mode="follow_boundary"
        ),
        extension_m=10.0,
    )


def _planting_op() -> PrecisionOperation:
    return PrecisionOperation(
        operation_id="planting",
        machine=_planter(),
        headland=HeadlandLayout(
            pass_count=1, width_m=9.0, effective_spacing_m=9.0, mode="follow_boundary"
        ),
        extension_m=5.0,
    )


def _planting_config(enabled: bool) -> PlantingAvoidanceConfiguration:
    return PlantingAvoidanceConfiguration(
        strategy=PlantingAvoidanceStrategy.AUTO,
        inner_margin_m=0.5,
        outer_margin_m=0.5,
        merge_obstacles_m=2.0,
        minimum_turn_radius_m=6.0,
        enabled=enabled,
    )


def _kinematics() -> PlantingKinematics:
    return PlantingKinematics(
        operational_width_m=9.0,
        track_width_m=0.0,
        hitch_distance_m=0.0,
        minimum_turn_radius_m=6.0,
        row_count=18,
        row_spacing_m=0.5,
    )


SPRAY_OFF = AvoidanceConfiguration(mode=AvoidanceMode.NONE, minimum_turn_radius_m=6.0)
SPRAY_DEFAULT_ON = AvoidanceConfiguration()
SPRAY_ORBIT_ON = AvoidanceConfiguration(
    mode=AvoidanceMode.CONCENTRIC_RING, minimum_turn_radius_m=6.0, orbit_360=True
)


def build_project(
    *, spraying: bool, planting: bool, avoidance, planting_enabled: bool, fast: bool = False
):
    # Plantio + pulverizacao no perfil Final materializa o shutoff completo (~80 s).
    processing = preview_profile() if fast else final_profile()
    return PrecisionProject(
        processing=processing,
        field=FieldGeometry(field_boundary=FIELD, operational_boundary=FIELD, crs_authid="EPSG:31982"),
        ab_line=ABLine(start=(0.0, 200.0), end=(600.0, 200.0)),
        spraying=_spraying_op() if spraying else None,
        planting=_planting_op() if planting else None,
        obstacles=_obstacles(),
        avoidance=avoidance,
        planting_avoidance=_planting_config(planting_enabled),
        planting_kinematics=_kinematics() if planting else None,
    )


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


def _lines_summary(polylines) -> dict[str, object]:
    polylines = [tuple(p) for p in polylines]
    return {
        "count": len(polylines),
        "total_m": round(sum(_length(p) for p in polylines), 3),
        "digest": _digest(polylines),
    }


def spraying_summary(result) -> dict[str, object]:
    plan = result.spraying_boundary
    return {
        "passes": _lines_summary(p.line_points() for p in result.spraying_passes),
        "headland": _lines_summary(
            line.line_points() for line in (plan.headland_centerlines if plan else ())
        ),
        "tire_tracks": len(result.tire_tracks),
        "spray_avoided": len([a for a in result.avoided_paths if a.operation_id == "spraying"]),
    }


def planting_summary(result) -> dict[str, object]:
    plan = result.boundary if result.project.planting is not None else None
    return {
        "passes": _lines_summary(p.line_points() for p in result.planting_passes),
        "headland": _lines_summary(
            line.line_points() for line in (plan.headland_centerlines if plan else ())
        ),
        "rows": len(result.planting_rows),
        "tractor_axes": _lines_summary(a.path_points for a in result.tractor_axes),
        "planting_results": len(result.planting_avoidance_results),
        "plant_avoided": len([a for a in result.avoided_paths if a.operation_id != "spraying"]),
        "shutoff": len(result.shutoff_segments),
    }


SCENARIOS = {
    "spray_off": dict(spraying=True, planting=False, avoidance=SPRAY_OFF, planting_enabled=False),
    "spray_default_on": dict(
        spraying=True, planting=False, avoidance=SPRAY_DEFAULT_ON, planting_enabled=False
    ),
    "spray_orbit_on": dict(
        spraying=True, planting=False, avoidance=SPRAY_ORBIT_ON, planting_enabled=False
    ),
    "planting_off": dict(spraying=False, planting=True, avoidance=SPRAY_OFF, planting_enabled=False),
    "planting_on": dict(spraying=False, planting=True, avoidance=SPRAY_OFF, planting_enabled=True),
    "combined_on": dict(
        spraying=True, planting=True, avoidance=SPRAY_DEFAULT_ON, planting_enabled=True, fast=True
    ),
}


def capture() -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    for name, kwargs in SCENARIOS.items():
        result = run_precision_lines(build_project(**kwargs))
        entry: dict[str, object] = {}
        if kwargs["spraying"]:
            entry["spraying"] = spraying_summary(result)
        if kwargs["planting"]:
            entry["planting"] = planting_summary(result)
        out[name] = entry
    return out


def _load_baseline() -> dict[str, dict[str, object]]:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


class SprayObstacleRegressionBaselineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = _load_baseline()

    def _run(self, name: str):
        return run_precision_lines(build_project(**SCENARIOS[name]))

    def test_spray_avoidance_off_is_identical(self):
        result = self._run("spray_off")
        self.assertEqual(spraying_summary(result), self.baseline["spray_off"]["spraying"])

    def test_legacy_spray_modes_are_identical(self):
        for name in ("spray_default_on", "spray_orbit_on"):
            with self.subTest(scenario=name):
                result = self._run(name)
                self.assertEqual(spraying_summary(result), self.baseline[name]["spraying"])

    def test_planting_is_identical(self):
        for name in ("planting_off", "planting_on", "combined_on"):
            with self.subTest(scenario=name):
                result = self._run(name)
                self.assertEqual(planting_summary(result), self.baseline[name]["planting"])

    def test_planting_identical_with_new_spray_minimum_deviation(self):
        try:
            smart = replace(
                SPRAY_DEFAULT_ON, minimum_deviation=True, minimum_turn_radius_m=6.0
            )
        except TypeError:  # pragma: no cover - motor anterior a SKILL 2
            self.skipTest("desvio minimo indisponivel")
        kwargs = dict(SCENARIOS["combined_on"], avoidance=smart)
        result = run_precision_lines(build_project(**kwargs))
        self.assertEqual(planting_summary(result), self.baseline["combined_on"]["planting"])


if __name__ == "__main__":
    if "--capture" in sys.argv:
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(json.dumps(capture(), indent=2, sort_keys=True), encoding="utf-8")
        print(f"baseline gravado em {BASELINE_PATH}")
    else:
        unittest.main()
