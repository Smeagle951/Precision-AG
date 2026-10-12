# -*- coding: utf-8 -*-
"""Faixa de cobertura progressiva: so o trecho ja percorrido, largura real, transpasse visivel."""

from __future__ import annotations

import math
import unittest

from shapely.geometry import box

from plugin.fortsmart_precision.core.coverage_engine import (
    CoverageEngine,
    CoverageSettings,
    get_travelled_segment,
)
from plugin.fortsmart_precision.core.route_simulation_engine import RouteSimulationEngine
from plugin.fortsmart_precision.core.simulation_route import RouteMode, RoutePassInput, build_ordered_route
from plugin.fortsmart_precision.domain.machine_profile import MachineProfile

SPEED = 10.0  # m/s -> advance(1.0) = 10 m


def straight(pass_id, sequence, y=0.0, length=100.0):
    return RoutePassInput(pass_id, (((0.0, y), (length, y)),), sequence)


def simulation(passes, width, mode=RouteMode.SERPENTINE, step=0.5):
    engine = RouteSimulationEngine(
        build_ordered_route(passes, mode), MachineProfile(id="m", name="M", width_m=width), SPEED
    )
    coverage = CoverageEngine(CoverageSettings(working_width_m=width, update_step_m=step))
    return engine, coverage


def run(engine, coverage, seconds):
    engine.advance(seconds)
    coverage.update(engine)


class SettingsTest(unittest.TestCase):
    def test_width_must_be_informed(self):
        for bad in (0.0, -1.0, float("nan")):
            with self.assertRaises(ValueError):
                CoverageEngine(CoverageSettings(working_width_m=bad))

    def test_half_width_comes_from_the_informed_width(self):
        self.assertAlmostEqual(CoverageSettings(12.15).half_width_m, 6.075)


class ProgressiveCoverageTest(unittest.TestCase):
    def test_35_coverage_grows_with_the_machine_on_a_100_m_pass(self):
        engine, coverage = simulation([straight("P01", 1)], 12.15)
        engine.start()
        coverage.update(engine)
        self.assertEqual(coverage.state.passes(), [])

        for seconds, expected in ((2.5, 25.0), (2.5, 50.0)):
            run(engine, coverage, seconds)
            geometry = coverage.state.current.geometry
            minx, miny, maxx, maxy = geometry.bounds
            self.assertAlmostEqual(maxx - minx, expected, places=6)
            self.assertAlmostEqual(maxy - miny, 12.15, places=6)
            self.assertAlmostEqual(geometry.area, expected * 12.15, places=6)
            self.assertLessEqual(maxx, engine.state.current_position[0] + 1e-9)

        run(engine, coverage, 10.0)
        self.assertIsNone(coverage.state.current)
        self.assertAlmostEqual(coverage.state.completed[0].geometry.area, 100.0 * 12.15, places=6)

    def test_36_strip_width_follows_the_informed_width(self):
        for width in (5.0, 10.0, 12.15, 15.0, 30.0, 40.0):
            engine, coverage = simulation([straight("P01", 1)], width)
            engine.start()
            run(engine, coverage, 4.0)
            minx, miny, maxx, maxy = coverage.state.current.geometry.bounds
            self.assertAlmostEqual(maxy - miny, width, places=6, msg=width)
            self.assertAlmostEqual(miny, -width / 2.0, places=6)

    def test_never_paints_ahead_of_the_machine_and_lag_is_below_update_step(self):
        engine, coverage = simulation([straight("P01", 1)], 10.0, step=1.0)
        engine.start()
        for _ in range(37):
            run(engine, coverage, 0.03)  # 0,3 m por quadro
            x = engine.state.current_position[0]
            maxx = coverage.state.current.geometry.bounds[2] if coverage.state.current else 0.0
            self.assertLessEqual(maxx, x + 1e-9)
            self.assertLess(x - maxx, 1.0 + 1e-9)

    def test_previous_pass_stays_and_serpentine_paints_in_travel_direction(self):
        engine, coverage = simulation([straight("P01", 1), straight("P02", 2, y=10.0)], 10.0)
        engine.start()
        run(engine, coverage, 12.5)  # P01 inteira + 25 m da P02 (volta)

        self.assertEqual(sorted(coverage.state.coverage_by_pass), ["P01", "P02"])
        self.assertAlmostEqual(coverage.state.completed[0].geometry.area, 1000.0, places=6)
        minx, _miny, maxx, _maxy = coverage.state.current.geometry.bounds
        self.assertAlmostEqual((minx, maxx), (75.0, 100.0))

    def test_several_passes_finished_in_one_frame_are_all_consolidated(self):
        engine, coverage = simulation([straight(f"P{i}", i, y=10.0 * i) for i in range(1, 6)], 10.0)
        engine.start()
        run(engine, coverage, 100.0)

        self.assertEqual(len(coverage.state.completed), 5)
        self.assertIsNone(coverage.state.current)
        self.assertAlmostEqual(coverage.state.gross_area_m2, 5000.0, places=6)

    def test_gap_between_parts_of_the_same_pass_is_not_covered(self):
        cut = RoutePassInput("P01", (((0.0, 0.0), (40.0, 0.0)), ((60.0, 0.0), (100.0, 0.0))), 1)
        engine, coverage = simulation([cut], 10.0)
        engine.start()
        run(engine, coverage, 100.0)

        geometry = coverage.state.completed[0].geometry
        self.assertAlmostEqual(geometry.area, 800.0, places=6)
        self.assertAlmostEqual(geometry.intersection(box(41, -5, 59, 5)).area, 0.0)


class OverlapTest(unittest.TestCase):
    def areas(self, spacing):
        engine, coverage = simulation([straight("P01", 1), straight("P02", 2, y=spacing)], 10.0)
        engine.start()
        run(engine, coverage, 100.0)
        return coverage.state

    def test_37_width_10_spacing_9_has_1_m_overlap_kept_per_pass(self):
        state = self.areas(9.0)

        self.assertEqual(len(state.coverage_by_pass), 2)  # nao dissolvido: transpasse visivel
        self.assertAlmostEqual(state.gross_area_m2, 2000.0, places=6)
        self.assertAlmostEqual(state.unique_area_m2, 1900.0, places=6)
        self.assertAlmostEqual(state.overlap_area_m2, 100.0, places=6)

    def test_38_width_10_spacing_10_touches_without_overlap(self):
        state = self.areas(10.0)

        self.assertAlmostEqual(state.unique_area_m2, 2000.0, places=6)
        self.assertAlmostEqual(state.overlap_area_m2, 0.0, places=6)

    def test_39_width_10_spacing_11_leaves_1_m_uncovered(self):
        state = self.areas(11.0)
        gap = box(0.0, 5.0, 100.0, 6.0)

        self.assertAlmostEqual(state.overlap_area_m2, 0.0, places=6)
        self.assertAlmostEqual(sum(g.intersection(gap).area for g in state.coverage_by_pass.values()), 0.0)

    def test_unique_area_while_the_active_pass_overlaps_the_previous(self):
        engine, coverage = simulation([straight("P01", 1), straight("P02", 2, y=9.0)], 10.0)
        engine.start()
        run(engine, coverage, 15.0)  # 50 m da P02

        self.assertAlmostEqual(coverage.state.gross_area_m2, 1500.0, places=6)
        self.assertAlmostEqual(coverage.state.unique_area_m2, 1450.0, places=6)


class CurveTest(unittest.TestCase):
    def test_40_strip_follows_a_curve_as_one_smooth_polygon(self):
        radius, width = 100.0, 10.0
        points = tuple(
            (radius * math.cos(math.radians(a / 2)), radius * math.sin(math.radians(a / 2))) for a in range(0, 181)
        )
        engine, coverage = simulation([RoutePassInput("P01", (points,), 1)], width)
        engine.start()
        run(engine, coverage, 100.0)

        geometry = coverage.state.completed[0].geometry
        length = engine.route.total_length_m
        self.assertEqual(geometry.geom_type, "Polygon")
        self.assertTrue(geometry.is_valid)
        self.assertAlmostEqual(geometry.area, length * width, delta=length * width * 0.002)


class ControlsTest(unittest.TestCase):
    def test_41_pause_freezes_coverage_exactly_where_the_machine_stopped(self):
        engine, coverage = simulation([straight("P01", 1, length=200.0)], 10.0, step=1.0)
        engine.start()
        for _ in range(266):
            run(engine, coverage, 0.03)  # 79,8 m
        engine.advance(0.002)  # 79,82 m (ainda sem refazer: passo de 1 m)
        engine.pause()
        coverage.update(engine)
        frozen = coverage.state.current.geometry

        self.assertAlmostEqual(frozen.bounds[2], engine.state.current_distance_m, places=9)
        for _ in range(50):
            engine.advance(1.0)
            self.assertFalse(coverage.update(engine))
        self.assertIs(coverage.state.current.geometry, frozen)

        engine.resume()
        run(engine, coverage, 1.0)
        self.assertAlmostEqual(coverage.state.current.geometry.bounds[2], engine.state.current_distance_m, places=9)

    def test_stop_keeps_coverage(self):
        engine, coverage = simulation([straight("P01", 1), straight("P02", 2, y=10.0)], 10.0)
        engine.start()
        run(engine, coverage, 13.0)
        engine.stop()
        coverage.update(engine)

        self.assertEqual(len(coverage.state.passes()), 2)
        self.assertAlmostEqual(coverage.state.gross_area_m2, 1300.0, places=6)

    def test_42_restart_clears_all_coverage(self):
        engine, coverage = simulation([straight(f"P{i}", i, y=10.0 * i) for i in range(1, 4)], 10.0)
        engine.start()
        run(engine, coverage, 25.0)
        engine.restart()

        self.assertTrue(coverage.update(engine))
        self.assertEqual(coverage.state.passes(), [])
        self.assertEqual(coverage.state.gross_area_m2, 0.0)
        self.assertEqual(engine.state.completed_distance_m, 0.0)

    def test_start_again_after_finish_does_not_mix_simulations(self):
        engine, coverage = simulation([straight("P01", 1)], 10.0)
        engine.start()
        run(engine, coverage, 100.0)
        engine.start()
        run(engine, coverage, 1.0)

        self.assertEqual(coverage.state.completed, {})
        self.assertAlmostEqual(coverage.state.gross_area_m2, 100.0, places=6)


class TravelledSegmentTest(unittest.TestCase):
    def test_travelled_segment_is_only_the_part_between_distances(self):
        route = build_ordered_route([straight("P01", 1)])
        segment = get_travelled_segment(route.passes[0], 0.0, 30.0)

        self.assertAlmostEqual(segment.length, 30.0)
        self.assertIsNone(get_travelled_segment(route.passes[0], 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
