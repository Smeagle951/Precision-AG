# -*- coding: utf-8 -*-
"""Simulador de rota: maquina percorre as passadas existentes, uma por vez."""

from __future__ import annotations

import math
import unittest
from unittest.mock import PropertyMock, patch

from shapely.geometry import LineString, Point as ShapelyPoint

from plugin.fortsmart_precision.core.route_simulation_engine import (
    SIMULATION_PREMATURE_COMPLETION,
    PassVisualState,
    RouteSimulationEngine,
    SimulationError,
)
from plugin.fortsmart_precision.core.simulation_marker import (
    VISUAL_DEFAULT_LENGTH_M,
    machine_marker_outline,
)
from plugin.fortsmart_precision.core.simulation_route import (
    SIMULATION_ROUTE_INVALID,
    RouteMode,
    RoutePassInput,
    RouteValidationError,
    bearing_deg,
    build_ordered_route,
    validate_route_input,
)
from plugin.fortsmart_precision.domain.machine_profile import MachineProfile, MachineType

PROFILE = MachineProfile(id="m", name="Trator", machine_type=MachineType.TRACTOR_PLANTER, width_m=20.0, length_m=8.0)


def straight(pass_id, sequence, y=0.0, length=100.0, reverse=False):
    points = ((0.0, y), (length, y))
    return RoutePassInput(pass_id, (points[::-1] if reverse else points,), sequence)


def engine_for(passes, speed=10.0, mode=RouteMode.SERPENTINE, **kwargs):
    return RouteSimulationEngine(build_ordered_route(passes, mode, **kwargs), PROFILE, speed)


def run(engine, seconds, tick=0.05):
    steps = int(round(seconds / tick))
    for _ in range(steps):
        engine.advance(tick)
    return engine.state


def executed_length(engine):
    return sum(LineString(p).length for p in engine.executed_active_parts())


class StraightLineTest(unittest.TestCase):
    def test_1_straight_100m_at_10ms(self):
        engine = engine_for([straight("P01", 1)])
        engine.start()
        state = run(engine, 1.0)
        self.assertAlmostEqual(state.current_distance_m, 10.0, places=6)
        self.assertAlmostEqual(executed_length(engine), 10.0, places=6)
        self.assertEqual(engine.pass_visual_state(0), PassVisualState.ACTIVE)
        state = run(engine, 4.0)
        self.assertAlmostEqual(state.current_distance_m, 50.0, places=6)
        self.assertAlmostEqual(state.current_position[0], 50.0, places=6)
        self.assertAlmostEqual(state.progress_percent, 50.0, places=6)
        self.assertAlmostEqual(sum(LineString(p).length for p in engine.remaining_active_parts()), 50.0, places=6)
        state = run(engine, 5.0)
        self.assertTrue(state.is_finished)
        self.assertFalse(state.is_running)
        self.assertAlmostEqual(state.progress_percent, 100.0)
        self.assertAlmostEqual(state.elapsed_time_s, 10.0, places=6)
        self.assertEqual(state.current_position, (100.0, 0.0))
        self.assertEqual(engine.pass_visual_state(0), PassVisualState.COMPLETED)

    def test_motion_uses_real_delta_not_ticks(self):
        coarse = engine_for([straight("P01", 1)])
        fine = engine_for([straight("P01", 1)])
        coarse.start()
        fine.start()
        coarse.advance(3.0)
        run(fine, 3.0, tick=0.01)
        self.assertAlmostEqual(coarse.state.current_distance_m, fine.state.current_distance_m, places=6)

    def test_heading_east(self):
        engine = engine_for([straight("P01", 1)])
        engine.start()
        self.assertAlmostEqual(run(engine, 2.0).current_heading_deg, 90.0)


class TwoPassesTest(unittest.TestCase):
    def test_2_one_pass_at_a_time(self):
        engine = engine_for([straight("P01", 1), straight("P02", 2, y=20.0)])
        engine.start()
        state = run(engine, 5.0)
        self.assertEqual((state.current_pass_id, state.completed_pass_count), ("P01", 0))
        self.assertEqual(engine.pass_visual_state(1), PassVisualState.PLANNED)
        state = run(engine, 6.0)
        self.assertEqual(state.current_pass_id, "P02")
        self.assertEqual(state.completed_pass_count, 1)
        self.assertAlmostEqual(state.current_distance_m, 10.0, places=6)
        self.assertEqual([p.id for p in engine.completed_passes()], ["P01"])
        state = run(engine, 9.0)
        self.assertTrue(state.is_finished)
        self.assertAlmostEqual(state.elapsed_time_s, 20.0, places=6)

    def test_3_serpentine_reverses_heading(self):
        engine = engine_for([straight("P01", 1), straight("P02", 2, y=20.0)])
        engine.start()
        self.assertAlmostEqual(run(engine, 2.0).current_heading_deg, 90.0)
        state = run(engine, 10.0)
        self.assertEqual(state.current_pass_id, "P02")
        self.assertAlmostEqual(state.current_heading_deg, 270.0)
        self.assertAlmostEqual(state.current_position[0], 80.0, places=6)
        self.assertTrue(engine.current_pass.reversed)

    def test_serpentine_respects_already_alternated_geometry(self):
        passes = [straight("P01", 1), straight("P02", 2, y=20.0, reverse=True), straight("P03", 3, y=40.0)]
        route = build_ordered_route(passes)
        self.assertEqual([p.reversed for p in route.passes], [False, False, False])
        self.assertEqual(route.passes[1].start, (100.0, 20.0))

    def test_same_direction_and_custom_sequence(self):
        passes = [straight("P01", 1), straight("P02", 2, y=20.0, reverse=True)]
        same = build_ordered_route(passes, RouteMode.SAME_DIRECTION)
        self.assertEqual(same.passes[1].start, (0.0, 20.0))
        custom = build_ordered_route(passes, RouteMode.CUSTOM_SEQUENCE, custom_order=["P02", "P01"])
        self.assertEqual([p.id for p in custom.passes], ["P02", "P01"])
        self.assertEqual(custom.passes[0].start, (100.0, 20.0))


class CurveTest(unittest.TestCase):
    def test_4_machine_stays_on_curve_and_turns_progressively(self):
        arc = tuple((100.0 * math.sin(a / 40.0 * math.pi / 2), 100.0 * math.cos(a / 40.0 * math.pi / 2)) for a in range(41))
        engine = engine_for([RoutePassInput("P01", (arc,), 1)], speed=5.0)
        engine.start()
        line = LineString(arc)
        headings = []
        while not engine.state.is_finished:
            state = engine.advance(1.0)
            self.assertLess(line.distance(ShapelyPoint(state.current_position)), 1e-6)
            headings.append(state.current_heading_deg)
        self.assertGreater(len(headings), 20)
        self.assertTrue(all(b >= a - 1e-6 for a, b in zip(headings, headings[1:])))
        # Quarto de circulo de (0, 100) a (100, 0): rumo vai de leste (90) para sul (180).
        self.assertLess(abs(headings[0] - 93.4), 1.0)
        self.assertGreater(headings[-2], 175.0)
        self.assertLess(headings[-1], 180.0 + 1e-6)
        # Executado no meio da curva segue os vertices reais (nao corta por dentro).
        engine.restart()
        engine.advance(15.0)
        parts = engine.executed_active_parts()
        self.assertGreater(len(parts[0]), 3)
        self.assertAlmostEqual(LineString(parts[0]).length, 75.0, places=6)

    def test_multipart_pass_jumps_without_counting_gap(self):
        parts = (((0.0, 0.0), (40.0, 0.0)), ((60.0, 0.0), (100.0, 0.0)))
        engine = engine_for([RoutePassInput("P01", parts, 1)])
        engine.start()
        state = run(engine, 5.0)
        self.assertAlmostEqual(state.current_position[0], 70.0, places=6)
        self.assertEqual(len(engine.executed_active_parts()), 2)
        self.assertAlmostEqual(engine.route.total_length_m, 80.0)


class ControlsTest(unittest.TestCase):
    def test_5_pause_freezes_and_resumes_same_point(self):
        engine = engine_for([straight("P01", 1)])
        engine.start()
        run(engine, 4.0)
        paused = engine.pause()
        self.assertTrue(paused.is_paused)
        frozen = run(engine, 3.0)
        self.assertEqual(frozen.current_distance_m, paused.current_distance_m)
        self.assertEqual(frozen.current_position, paused.current_position)
        self.assertEqual(frozen.elapsed_time_s, paused.elapsed_time_s)
        engine.resume()
        self.assertAlmostEqual(run(engine, 1.0).current_distance_m, 50.0, places=6)

    def test_6_restart_goes_back_to_p01(self):
        engine = engine_for([straight("P01", 1), straight("P02", 2, y=20.0)])
        engine.start()
        run(engine, 12.0)
        state = engine.restart()
        self.assertEqual((state.current_pass_index, state.current_pass_id), (0, "P01"))
        self.assertEqual((state.current_distance_m, state.progress_percent, state.completed_distance_m), (0.0, 0.0, 0.0))
        self.assertFalse(state.is_finished)
        self.assertTrue(state.is_running)

    def test_stop_keeps_point_and_start_begins_again(self):
        engine = engine_for([straight("P01", 1)])
        engine.start()
        run(engine, 3.0)
        stopped = engine.stop()
        self.assertFalse(stopped.is_running)
        self.assertAlmostEqual(run(engine, 2.0).current_distance_m, 30.0, places=6)
        self.assertEqual(engine.start().current_distance_m, 0.0)

    def test_speed_multiplier_scales_animation(self):
        engine = engine_for([straight("P01", 1, length=1000.0)])
        engine.set_speed_multiplier(10.0)
        engine.start()
        state = run(engine, 1.0)
        self.assertAlmostEqual(state.current_distance_m, 100.0, places=6)
        self.assertAlmostEqual(state.elapsed_time_s, 10.0, places=6)
        with self.assertRaises(ValueError):
            engine.set_speed_multiplier(0.0)


class RegressionTest(unittest.TestCase):
    def test_50_passes_never_complete_at_start(self):
        passes = [straight(f"P{i:02d}", i, y=20.0 * i) for i in range(1, 51)]
        engine = engine_for(passes)
        self.assertEqual({engine.pass_visual_state(i) for i in range(50)}, {PassVisualState.PLANNED})
        state = engine.start()
        self.assertEqual((state.completed_pass_count, state.active_pass_count, state.planned_pass_count), (0, 1, 49))
        self.assertEqual(engine.executed_active_parts(), [])
        state = run(engine, 10.0)
        self.assertEqual((state.completed_pass_count, state.active_pass_count, state.planned_pass_count), (1, 1, 48))
        self.assertEqual(state.route_count, 50)
        while not engine.state.is_finished:
            engine.advance(7.3)
            self.assertEqual(engine.state.route_count, 50)
        self.assertEqual(engine.state.completed_pass_count, 50)

    def test_premature_completion_guard(self):
        engine = engine_for([straight("P01", 1), straight("P02", 2, y=20.0)])
        engine.start()
        # Simula um bug que marcaria todas as passadas como concluidas no inicio.
        with patch.object(RouteSimulationEngine, "completed_pass_count", new_callable=PropertyMock, return_value=2):
            with self.assertRaises(SimulationError) as ctx:
                engine.state
        self.assertEqual(ctx.exception.code, SIMULATION_PREMATURE_COMPLETION)

    def test_input_geometry_is_not_changed(self):
        passes = [straight("P01", 1), straight("P02", 2, y=20.0)]
        snapshot = [p.segments for p in passes]
        engine = engine_for(passes)
        engine.start()
        run(engine, 25.0)
        self.assertEqual([p.segments for p in passes], snapshot)
        self.assertEqual(sorted(engine.route.passes[1].segments[0]), sorted(snapshot[1][0]))

    def test_logs(self):
        engine = engine_for([straight("P01", 1, length=10.0), straight("P02", 2, y=20.0, length=10.0)])
        with self.assertLogs("fortsmart_precision.simulation", level="INFO") as logs:
            engine.start()
            engine.advance(5.0)
        text = "\n".join(logs.output)
        for expected in ("SIMULATION START route_count=2", "mode=SERPENTINE", "PASS COMPLETED pass_id=P01",
                         "NEXT PASS pass_id=P02", "SIMULATION FINISHED"):
            self.assertIn(expected, text)

    def test_state_as_dict(self):
        engine = engine_for([straight("P01", 1)])
        engine.start()
        data = run(engine, 2.0).as_dict()
        for key in ("current_pass_id", "current_distance_m", "current_position", "current_heading_deg",
                    "progress_percent", "elapsed_time_s", "remaining_distance_m"):
            self.assertIn(key, data)


class ValidationTest(unittest.TestCase):
    def assert_invalid(self, passes, fragment, **kwargs):
        with self.assertRaises(RouteValidationError) as ctx:
            build_ordered_route(passes, **kwargs)
        self.assertEqual(ctx.exception.code, SIMULATION_ROUTE_INVALID)
        self.assertTrue(any(fragment in p for p in ctx.exception.problems), ctx.exception.problems)

    def test_invalid_inputs(self):
        self.assert_invalid([], "Nenhuma passada")
        self.assert_invalid([RoutePassInput("P01", (), 1)], "geometria vazia")
        self.assert_invalid([RoutePassInput("P01", (((0.0, 0.0), (0.0, 0.0)),), 1)], "comprimento zero")
        self.assert_invalid([RoutePassInput("P01", (((0.0, 0.0),),), 1)], "menos de 2 vertices")
        self.assert_invalid([straight("P01", None)], "sem sequencia")
        self.assert_invalid([straight("P01", 1), straight("P02", 1, y=20.0)], "repetida")
        self.assert_invalid([straight("P01", 1), straight("P01", 2, y=20.0)], "duplicada")
        self.assert_invalid([straight("P01", 1)], "personalizada", mode=RouteMode.CUSTOM_SEQUENCE, custom_order=[])
        self.assert_invalid([RoutePassInput("P01", (((0.0, 0.0), (float("nan"), 1.0)),), 1)], "coordenada invalida")

    def test_geographic_crs_is_rejected(self):
        problems = validate_route_input([straight("P01", 1)], crs_authid="EPSG:4326")
        self.assertTrue(problems)
        self.assertEqual(validate_route_input([straight("P01", 1)], crs_authid="EPSG:31982"), [])


class MarkerAndProfileTest(unittest.TestCase):
    def test_marker_points_to_heading(self):
        ring = machine_marker_outline((0.0, 0.0), 90.0, 4.0, 10.0)
        nose = max(ring, key=lambda p: p[0])
        self.assertAlmostEqual(nose[0], 5.0)
        self.assertAlmostEqual(nose[1], 0.0)
        self.assertEqual(ring[0], ring[-1])
        default = machine_marker_outline((0.0, 0.0), 0.0)
        self.assertAlmostEqual(max(p[1] for p in default), VISUAL_DEFAULT_LENGTH_M / 2)

    def test_bearing_and_profile_validation(self):
        self.assertAlmostEqual(bearing_deg((0, 0), (0, 1)), 0.0)
        self.assertAlmostEqual(bearing_deg((0, 0), (-1, 0)), 270.0)
        with self.assertRaises(ValueError):
            MachineProfile("m", "x", width_m=0.0).validate()


if __name__ == "__main__":
    unittest.main()
