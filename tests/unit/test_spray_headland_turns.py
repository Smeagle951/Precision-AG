# -*- coding: utf-8 -*-
"""SKILL 3 — cabeceira da pulverizacao: Extensao reta / operador x Manobra automatica.

Talhao 600 x 400 m (EPSG:31982), barra 36 m, bordadura de 1 passada, extensao
10 m. A manobra automatica reutiliza o headland_turn_engine; as passadas,
a bordadura e os rastros de pneus nunca mudam.
"""

from __future__ import annotations

import math
import unittest
from dataclasses import replace

from shapely.geometry import LineString, Polygon
from shapely.geometry import Point as ShapelyPoint

from plugin.fortsmart_precision.core.headland_turn_engine import (
    STATUS_INFEASIBLE_RADIUS,
    STATUS_OBSTACLE_CONFLICT,
    STATUS_OK,
)
from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
from plugin.fortsmart_precision.core.spray_headland_turns import (
    RADIUS_MISSING_MESSAGE,
    SPRAY_HEADLAND_RADIUS_MISSING,
    SPRAY_HEADLAND_SOURCE_LAYER,
    machine_half_outer_width_m,
    plan_spray_headland_turns,
    spray_headland_turn_summary,
    trim_to_area,
)
from plugin.fortsmart_precision.domain.headland_layout import HEADLAND_MODE_FIDELITY, HeadlandLayout
from plugin.fortsmart_precision.domain.machine_model import MachineTrack
from plugin.fortsmart_precision.domain.obstacle_model import obstacle_from_point
from plugin.fortsmart_precision.domain.planting_kinematics import PlantingKinematics
from plugin.fortsmart_precision.domain.precision_project import (
    SPRAY_HEADLAND_TURN_AUTOMATIC,
    SPRAY_HEADLAND_TURN_MANUAL,
    PrecisionProjectError,
)
from tests.unit.test_spray_headland_regression_baseline import (
    FIELD,
    build_project,
    sprayer,
    spraying_op,
    summary,
)

RADIUS = 8.0
NO_HEADLAND = HeadlandLayout(pass_count=0, width_m=0.0, mode="none")


def _project(*, radius=RADIUS, headland=None, extension=10.0, mode=SPRAY_HEADLAND_TURN_AUTOMATIC, **kw):
    op = spraying_op(sprayer(sprayer_minimum_turn_radius_m=radius))
    if headland is not None:
        op = replace(op, headland=headland)
    op = replace(op, extension_m=extension)
    return build_project("spray_default", spraying=op, spray_headland_turn_mode=mode, **kw)


def _headings(points):
    return [
        math.atan2(b[1] - a[1], b[0] - a[0]) for a, b in zip(points, points[1:]) if math.dist(a, b) > 1e-9
    ]


def _heading_change_deg(h1, h2) -> float:
    return math.degrees(abs((h2 - h1 + math.pi) % (2.0 * math.pi) - math.pi))


def _pass_ends(result):
    """(inicio, fim) de cada passada numerada, como geradas."""
    return {p.pass_no: p.line_points() for p in result.spraying_passes}


class SprayHeadlandModeModelTest(unittest.TestCase):
    def test_default_is_manual_and_independent_of_planting_mode(self):
        project = build_project("spray_default")
        self.assertEqual(project.spray_headland_turn_mode, SPRAY_HEADLAND_TURN_MANUAL)
        self.assertEqual(project.headland_turn_mode, "extend")
        auto = replace(project, spray_headland_turn_mode=SPRAY_HEADLAND_TURN_AUTOMATIC)
        auto.validate()
        self.assertEqual(auto.headland_turn_mode, "extend")
        planting_offset = replace(project, headland_turn_mode="offset_turn")
        planting_offset.validate()
        self.assertEqual(planting_offset.spray_headland_turn_mode, SPRAY_HEADLAND_TURN_MANUAL)

    def test_invalid_mode_rejected(self):
        with self.assertRaises(PrecisionProjectError):
            replace(build_project("spray_default"), spray_headland_turn_mode="offset_turn").validate()


class ManualHeadlandTest(unittest.TestCase):
    """Extensao reta / operador manobra: passadas retas, independentes, sem curva."""

    @classmethod
    def setUpClass(cls):
        cls.result = run_precision_lines(build_project("spray_default"))

    def test_no_turns_generated(self):
        self.assertIsNone(self.result.spray_headland_turns)
        self.assertEqual(self.result.turn_paths, [])

    def test_each_pass_straight_beyond_limit_by_extension(self):
        for pass_no, points in _pass_ends(self.result).items():
            with self.subTest(pass_no=pass_no):
                ys = {round(y, 6) for _x, y in points}
                self.assertEqual(len(ys), 1)  # reta, sem curva nas pontas
                xs = sorted((points[0][0], points[-1][0]))
                self.assertAlmostEqual(xs[0], -10.0, places=6)
                self.assertAlmostEqual(xs[1], 610.0, places=6)

    def test_passes_are_independent(self):
        lines = [LineString(p.line_points()) for p in self.result.spraying_passes]
        for i, a in enumerate(lines):
            for b in lines[i + 1:]:
                self.assertGreater(a.distance(b), 30.0)

    def test_manual_matches_pre_skill_baseline(self):
        explicit = replace(build_project("spray_default"), spray_headland_turn_mode=SPRAY_HEADLAND_TURN_MANUAL)
        self.assertEqual(summary(run_precision_lines(explicit)), summary(self.result))


class AutomaticHeadlandTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_precision_lines(_project())
        cls.turns = cls.result.spray_headland_turns

    def test_one_turn_per_consecutive_pair(self):
        self.assertEqual(len(self.result.spraying_passes), 9)
        self.assertEqual(len(self.turns.turns), 8)
        self.assertEqual(self.turns.rejected, ())
        self.assertTrue(all(turn.status == STATUS_OK for turn in self.turns.turns))
        self.assertEqual(self.turns.report["direction_source"], "attribute")
        self.assertFalse(self.turns.report["passes_modified"])

    def test_minimum_radius_respected(self):
        for turn in self.turns.turns:
            self.assertGreaterEqual(turn.radius_m, RADIUS - 1e-9)
            self.assertLessEqual(turn.radius_m, 36.0 / 2.0 + 1e-9)
        self.assertEqual(self.turns.report["radii_m"], [18.0])

    def test_smooth_aligned_entry_without_v_or_loop(self):
        ends = _pass_ends(self.result)
        for turn in self.turns.turns:
            with self.subTest(turn=turn.turn_id):
                headings = _headings(turn.points)
                changes = [_heading_change_deg(a, b) for a, b in zip(headings, headings[1:])]
                self.assertLessEqual(max(changes), 2.5)  # arco de 2 graus, sem quina (V)
                total = sum(changes)
                self.assertAlmostEqual(total, 180.0, delta=3.0)  # meia volta, sem laco
                pass_axis = math.atan2(0.0, 1.0)
                self.assertLessEqual(min(_heading_change_deg(headings[0], pass_axis),
                                         _heading_change_deg(headings[0], pass_axis + math.pi)), 2.0)
                self.assertLessEqual(min(_heading_change_deg(headings[-1], pass_axis),
                                         _heading_change_deg(headings[-1], pass_axis + math.pi)), 2.0)
                # Entrada alinhada na proxima passada: o ultimo ponto esta sobre ela.
                self.assertLess(LineString(ends[turn.to_pass]).distance(ShapelyPoint(turn.points[-1])), 0.06)
                self.assertLess(LineString(ends[turn.from_pass]).distance(ShapelyPoint(turn.points[0])), 0.06)

    def test_turns_stay_in_headland_and_operational_limit(self):
        clearance = machine_half_outer_width_m(sprayer())
        limit = Polygon(FIELD[0][0]).buffer(10.0 - clearance, join_style=2)
        inner = Polygon([(36.0, 36.0), (564.0, 36.0), (564.0, 364.0), (36.0, 364.0)])
        for turn in self.turns.turns:
            line = LineString(turn.points)
            self.assertTrue(limit.buffer(0.06).covers(line))
            self.assertLessEqual(line.intersection(inner).length, 0.06)

    def test_passes_border_and_tire_tracks_unchanged(self):
        baseline = summary(run_precision_lines(build_project("spray_default")))
        self.assertEqual(summary(self.result), baseline)

    def test_turn_features_use_headland_turn_schema(self):
        features = self.turns.features()
        self.assertEqual(len(features), 8)
        points, attrs = features[0]
        self.assertGreaterEqual(len(points), 3)
        self.assertEqual(attrs["source_layer"], SPRAY_HEADLAND_SOURCE_LAYER)
        self.assertEqual(attrs["status"], STATUS_OK)
        self.assertTrue(attrs["from_line_id"].startswith("L"))

    def test_summary_and_validation(self):
        self.assertEqual(spray_headland_turn_summary(self.turns), "Cabeceira automatica: 8 curva(s) (raio 18.00 m)")
        self.assertIn("Cabeceira automatica: 8 curva(s) aceita(s), 0 recusada(s)", self.result.validation.checks)
        self.assertEqual(spray_headland_turn_summary(None), "")

    def test_headland_mode_independent_from_turn_mode(self):
        fidelity = replace(
            spraying_op(sprayer(sprayer_minimum_turn_radius_m=RADIUS)),
            headland=replace(spraying_op().headland, headland_mode=HEADLAND_MODE_FIDELITY),
        )
        manual = run_precision_lines(build_project("spray_default", spraying=fidelity))
        auto = run_precision_lines(
            build_project("spray_default", spraying=fidelity, spray_headland_turn_mode=SPRAY_HEADLAND_TURN_AUTOMATIC)
        )
        self.assertEqual(summary(manual)["headland"], summary(auto)["headland"])
        self.assertEqual(auto.project.spraying.headland.headland_mode, HEADLAND_MODE_FIDELITY)
        self.assertIsNotNone(auto.spray_headland_turns)


class AutomaticHeadlandLimitsTest(unittest.TestCase):
    def test_without_border_uses_extension_with_minimum_radius(self):
        result = run_precision_lines(_project(headland=NO_HEADLAND))
        turns = result.spray_headland_turns
        self.assertEqual(len(turns.turns), len(result.spraying_passes) - 1)
        self.assertEqual(turns.report["radii_m"], [8.0])
        clearance = machine_half_outer_width_m(sprayer())
        for turn in turns.turns:
            for x, _y in turn.points:
                # Fora do talhao e dentro da extensao menos meia largura externa.
                self.assertTrue(x <= 0.06 or x >= 600.0 - 0.06)
                self.assertTrue(-10.0 + clearance - 0.06 <= x <= 610.0 - clearance + 0.06)

    def test_no_space_returns_warning_without_forced_curve(self):
        result = run_precision_lines(_project(headland=NO_HEADLAND, extension=5.0))
        turns = result.spray_headland_turns
        self.assertEqual(turns.turns, ())
        self.assertEqual(turns.features(), [])
        self.assertTrue(turns.rejected)
        self.assertTrue(all(turn.status == STATUS_INFEASIBLE_RADIUS for turn in turns.rejected))
        self.assertTrue(all(turn.points == () for turn in turns.rejected))
        self.assertEqual(len(turns.warnings), len(turns.rejected))
        self.assertIn("nenhum raio", turns.warnings[0])
        self.assertTrue(any("Cabeceira" in w.message for w in result.validation.warnings))
        self.assertTrue(result.validation.ok)
        self.assertIn("sem espaco", spray_headland_turn_summary(turns))

    def test_radius_larger_than_half_spacing_is_infeasible(self):
        turns = run_precision_lines(_project(radius=20.0)).spray_headland_turns
        self.assertEqual(turns.turns, ())
        self.assertIn("raio até 18.00 m", turns.warnings[0])

    def test_missing_sprayer_radius_never_uses_planter_radius(self):
        project = _project(
            radius=None,
            planting_kinematics=PlantingKinematics(
                operational_width_m=9.0, track_width_m=0.0, hitch_distance_m=0.0,
                minimum_turn_radius_m=6.0, row_count=18, row_spacing_m=0.5,
            ),
        )
        turns = run_precision_lines(project).spray_headland_turns
        self.assertEqual(turns.turns, ())
        self.assertEqual(turns.report["status"], SPRAY_HEADLAND_RADIUS_MISSING)
        self.assertEqual(turns.warnings, (RADIUS_MISSING_MESSAGE,))
        self.assertEqual(spray_headland_turn_summary(turns), "Cabeceira automatica: nao gerada")

    def test_obstacle_near_turn_is_not_forced(self):
        # Zona de 8,5 m entre as passadas de y=56 e y=92, na cabeceira leste.
        post = obstacle_from_point((575.0, 74.0), obstacle_radius_m=0.5, safety_margin_m=8.0, obstacle_id="poste")
        result = run_precision_lines(_project(obstacles=(post,)))
        turns = result.spray_headland_turns
        blocked = [turn for turn in turns.rejected if turn.status == STATUS_OBSTACLE_CONFLICT]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(len(turns.turns), 7)
        self.assertIn("obstáculo", turns.warnings[0])
        zone = ShapelyPoint(575.0, 74.0).buffer(8.5)
        for turn in turns.turns:
            self.assertFalse(LineString(turn.points).intersects(zone))
        self.assertNotIn(blocked[0].turn_id, {attrs["turn_id"] for _p, attrs in turns.features()})

    def test_detoured_passes_keep_tracks_and_still_turn(self):
        baseline = summary(run_precision_lines(build_project("spray_minimum")))
        result = run_precision_lines(
            build_project("spray_minimum", spray_headland_turn_mode=SPRAY_HEADLAND_TURN_AUTOMATIC)
        )
        self.assertEqual(summary(result), baseline)
        self.assertEqual(len(result.spray_headland_turns.turns), 8)


class TrimAndPlanHelpersTest(unittest.TestCase):
    def test_trim_to_area_keeps_first_entry_to_last_exit(self):
        area = Polygon([(0, -5), (100, -5), (100, 5), (0, 5)]).difference(
            Polygon([(40, -5), (60, -5), (60, 5), (40, 5)])
        )
        self.assertEqual(trim_to_area([(-10.0, 0.0), (110.0, 0.0)], area), ((0.0, 0.0), (100.0, 0.0)))
        self.assertEqual(trim_to_area([(-10.0, 50.0), (110.0, 50.0)], area), ())
        self.assertEqual(trim_to_area([(-10.0, 0.0), (110.0, 0.0)], None), ((-10.0, 0.0), (110.0, 0.0)))

    def test_plan_without_limit_or_radius_only_warns(self):
        passes = run_precision_lines(build_project("spray_default")).spraying_passes
        no_limit = plan_spray_headland_turns(
            passes, work_area=FIELD, operational_area=[], radius_m=8.0, clearance_m=1.0
        )
        self.assertEqual(no_limit.turns, ())
        self.assertTrue(no_limit.warnings)
        no_radius = plan_spray_headland_turns(
            passes, work_area=FIELD, operational_area=FIELD, radius_m=0.0, clearance_m=1.0
        )
        self.assertEqual(no_radius.report["status"], SPRAY_HEADLAND_RADIUS_MISSING)

    def test_half_outer_width_from_machine_track(self):
        self.assertAlmostEqual(machine_half_outer_width_m(sprayer()), 3.43 / 2.0)
        bare = replace(sprayer(), traffic=None, track=MachineTrack(track_width_m=3.0, tire_width_m=0.5))
        self.assertAlmostEqual(machine_half_outer_width_m(bare), 1.75)


if __name__ == "__main__":
    unittest.main()
