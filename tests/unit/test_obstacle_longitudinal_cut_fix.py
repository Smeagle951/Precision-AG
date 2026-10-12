# -*- coding: utf-8 -*-
"""Corte longitudinal de obstaculo: largura/espacamento/bordadura nunca viram distancia de corte."""

from __future__ import annotations

import unittest

from shapely.geometry import Point

from plugin.fortsmart_precision.core.longitudinal_cut_engine import (
    WORK_OFF,
    WORK_ON,
    LongitudinalCutBreakdown,
    ObstacleInput,
    _anticipate,
    build_obstacle_zones,
    calculate_longitudinal_cut_distance,
    compute_longitudinal_cut,
    cut_debug_text,
)
from plugin.fortsmart_precision.core.obstacle_border_pass_engine import (
    cut_work_line_records,
    simulate_obstacle_cut,
)
from plugin.fortsmart_precision.domain.operation_simulation import (
    MachineReferenceType,
    MachineWorkGeometry,
    ObstacleBorderMode,
    ObstacleStrategy,
)

CRS = "EPSG:31981"
TOL = 0.06
LINE = [(0.0, 0.0), (300.0, 0.0)]


def machine(width=20.0, anticipation=0.0, offset=-8.0, mode=ObstacleBorderMode.ONE_IMPLEMENT_PASS, **kwargs):
    """Frente do trator como referencia; ultima linha ativa 8 m atras."""
    return MachineWorkGeometry(
        work_width_m=width,
        reference_type=MachineReferenceType.TRACTOR_FRONT,
        reference_to_working_line_longitudinal_m=offset,
        border_mode=mode,
        longitudinal_anticipation_m=anticipation,
        **kwargs,
    )


def cut_of(geometry, *, radius=1.0, margin=0.0, route=LINE, y=0.0) -> LongitudinalCutBreakdown:
    return calculate_longitudinal_cut_distance(
        route, ObstacleInput("P1", Point(150.0, y), radius), geometry, safety_margin_m=margin
    )


def ground_gap(geometry, *, radius=1.0, margin=2.0, route=LINE):
    sim = simulate_obstacle_cut(
        [("L1", route)], [ObstacleInput("P1", Point(150.0, 0.0), radius)], geometry,
        crs_authid=CRS, safety_margin_m=margin, strategy=ObstacleStrategy.CUT_ONLY,
    )
    (record,) = cut_work_line_records(sim)
    return record["gaps"][0]


class MandatoryTests(unittest.TestCase):
    def test_1_width_20_is_not_a_20_m_cut(self):
        item = cut_of(machine(width=20.0), radius=1.0, margin=0.0)
        self.assertAlmostEqual(item.cut_distance_m, 2.0, delta=TOL)  # so o diametro da zona
        self.assertAlmostEqual(item.anticipated_m, 0.0, delta=1e-9)
        self.assertLess(item.cut_distance_m, 20.0)

    def test_2_zone_plus_anticipation(self):
        item = cut_of(machine(width=20.0, anticipation=2.0), radius=1.0, margin=2.0)
        self.assertEqual(item.safety_zone_m, 3.0)
        self.assertAlmostEqual(item.anticipated_m, 2.0, delta=1e-6)
        self.assertAlmostEqual(item.cut_distance_m, 2 * 3.0 + 2.0, delta=TOL)
        offset = -8.0
        self.assertAlmostEqual(item.work_off_station_m + offset, 150 - 3 - 2, delta=TOL)
        self.assertAlmostEqual(item.work_on_station_m + offset, 150 + 3, delta=TOL)

    def test_3_changing_only_width_keeps_longitudinal_cut(self):
        wide = cut_of(machine(width=20.0, anticipation=2.0), margin=2.0)
        narrow = cut_of(machine(width=10.0, anticipation=2.0), margin=2.0)
        self.assertAlmostEqual(wide.cut_distance_m, narrow.cut_distance_m, delta=1e-3)
        self.assertAlmostEqual(wide.work_off_station_m, narrow.work_off_station_m, delta=1e-3)
        self.assertAlmostEqual(wide.work_on_station_m, narrow.work_on_station_m, delta=1e-3)

    def test_4_margin_grows_the_cut(self):
        small = cut_of(machine(anticipation=2.0), margin=2.0)
        large = cut_of(machine(anticipation=2.0), margin=5.0)
        self.assertAlmostEqual(large.cut_distance_m - small.cut_distance_m, 2 * 3.0, delta=TOL)
        self.assertAlmostEqual(large.cut_distance_m, 2 * 6.0 + 2.0, delta=TOL)

    def test_5_anticipation_stays_2_m_with_width_20(self):
        for width in (10.0, 20.0):
            item = cut_of(machine(width=width, anticipation=2.0), margin=2.0)
            self.assertAlmostEqual(item.anticipated_m, 2.0, delta=1e-6)
            self.assertAlmostEqual(item.cut_distance_m, 8.0, delta=TOL)


class GeometryRulesTest(unittest.TestCase):
    def test_sprayer_15_m_is_not_a_15_m_cut(self):
        item = cut_of(machine(width=15.0), radius=1.0, margin=0.0)
        self.assertAlmostEqual(item.cut_distance_m, 2.0, delta=TOL)

    def test_border_mode_never_changes_the_cut(self):
        cuts = {
            mode: cut_of(machine(mode=mode, obstacle_border_width_m=12.0, anticipation=2.0), margin=2.0).cut_distance_m
            for mode in ObstacleBorderMode
        }
        self.assertAlmostEqual(max(cuts.values()) - min(cuts.values()), 0.0, delta=1e-6)

    def test_pass_spacing_does_not_change_the_cut(self):
        def cut_on_post_line(spacing):
            passes = [(f"L{n}", [(0.0, n * spacing), (300.0, n * spacing)]) for n in range(-2, 3)]
            sim = simulate_obstacle_cut(
                passes, [ObstacleInput("P1", Point(150.0, 0.0), 1.0)], machine(anticipation=2.0),
                crs_authid=CRS, safety_margin_m=2.0, strategy=ObstacleStrategy.CUT_ONLY,
            )
            return {record["pass_id"]: record for record in cut_work_line_records(sim)}["L0"]["gaps"]

        self.assertEqual(cut_on_post_line(20.0), cut_on_post_line(10.0))

    def test_direction_of_travel_is_respected(self):
        forward = ground_gap(machine(anticipation=2.0))
        backward = ground_gap(machine(anticipation=2.0), route=list(reversed(LINE)))
        self.assertAlmostEqual(forward[0], 145.0, delta=TOL)  # ->  desliga 2 m antes de x=147
        self.assertAlmostEqual(forward[1], 153.0, delta=TOL)
        # <-  em estacao: entra na zona em x=153, desliga em x=155, religa em x=147
        self.assertAlmostEqual(300.0 - backward[0], 155.0, delta=TOL)
        self.assertAlmostEqual(300.0 - backward[1], 147.0, delta=TOL)

    def test_tractor_to_implement_distance_only_moves_the_reference_event(self):
        gaps = {offset: ground_gap(machine(anticipation=2.0, offset=offset)) for offset in (-18.0, -8.0, 0.0, 2.0)}
        for gap in gaps.values():
            self.assertAlmostEqual(gap[0], gaps[-8.0][0], delta=1e-3)
            self.assertAlmostEqual(gap[1], gaps[-8.0][1], delta=1e-3)
        rear = cut_of(machine(anticipation=2.0, offset=-8.0), margin=2.0)
        front = cut_of(machine(anticipation=2.0, offset=2.0), margin=2.0)
        self.assertAlmostEqual(rear.work_off_station_m - front.work_off_station_m, 10.0, delta=1e-3)
        self.assertAlmostEqual(rear.cut_distance_m, front.cut_distance_m, delta=1e-3)

    def test_lateral_behaviour_still_uses_half_width(self):
        # zona 3 m, poste a 12 m da passada: meia largura 10 + 3 = 13 > 12 encosta; com 5 m nao
        self.assertIsNotNone(cut_of(machine(width=20.0), margin=2.0, y=12.0))
        self.assertIsNone(cut_of(machine(width=10.0), margin=2.0, y=12.0))

    def test_anticipation_merges_close_obstacles_and_clamps_at_start(self):
        self.assertEqual(_anticipate([(10.0, 12.0), (13.0, 15.0)], 2.0), [(8.0, 15.0, 10.0, True)])
        self.assertEqual(_anticipate([(1.0, 3.0)], 2.0), [(0.0, 3.0, 1.0, False)])
        zones = build_obstacle_zones([ObstacleInput("P1", Point(150, 0), 1.0)], 2.0)
        result = compute_longitudinal_cut("L1", LINE, zones, machine(anticipation=2.0, offset=0.0))
        off = next(e for e in result.events if e.event_type == WORK_OFF)
        on = next(e for e in result.events if e.event_type == WORK_ON)
        self.assertAlmostEqual(off.measured_distance_m, off.target_distance_m, delta=TOL)
        self.assertAlmostEqual(on.measured_distance_m, on.target_distance_m, delta=TOL)


class DebugLogTest(unittest.TestCase):
    def test_log_shows_the_source_of_every_value(self):
        with self.assertLogs("fortsmart_precision.obstacle_cut", level="INFO") as logs:
            cut_of(machine(width=20.0, anticipation=2.0), radius=1.0, margin=2.0)
        text = "\n".join(logs.output)
        for expected in (
            "=== FORTSMART OBSTACLE CUT DEBUG ===",
            "WORKING WIDTH: 20.00 m",
            "SPACING: nao usado no corte longitudinal",
            "OBSTACLE RADIUS: 1.00 m",
            "SAFETY MARGIN: 2.00 m",
            "LONGITUDINAL ANTICIPATION: 2.00 m",
            "REFERENCE POINT: TRACTOR_FRONT",
            "REFERENCE -> OPERATION: -8.00 m (atras",
            "CALCULATED SAFETY ZONE: 3.00 m",
            "CALCULATED CUT DISTANCE: 8.00 m",
        ):
            self.assertIn(expected, text)

    def test_debug_text_is_built_from_breakdown(self):
        item = cut_of(machine(anticipation=2.0), margin=2.0)
        self.assertIn(f"WORK_OFF STATION: {item.work_off_station_m:.2f} m (antecipado 2.00 m)", cut_debug_text(item))

    def test_report_lists_each_cut(self):
        sim = simulate_obstacle_cut(
            [("L1", LINE)], [ObstacleInput("P1", Point(150.0, 0.0), 1.0)], machine(anticipation=2.0),
            crs_authid=CRS, safety_margin_m=2.0, strategy=ObstacleStrategy.CUT_ONLY,
        )
        (detail,) = sim.report["longitudinal_cuts"]
        self.assertEqual(detail["anticipation_m"], 2.0)
        self.assertEqual(detail["safety_zone_m"], 3.0)
        self.assertAlmostEqual(detail["cut_distance_m"], 8.0, delta=TOL)
        self.assertEqual(sim.report["machine_geometry"]["longitudinal_anticipation_m"], 2.0)


if __name__ == "__main__":
    unittest.main()
