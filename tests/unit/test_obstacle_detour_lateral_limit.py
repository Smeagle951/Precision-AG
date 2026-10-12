# -*- coding: utf-8 -*-
"""Desvio de obstaculo nao pode invadir a passada vizinha."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.application_obstacle_engine import (
    apply_application_obstacle_avoidance,
)
from plugin.fortsmart_precision.core.guidance_engine import TrafficPass
from plugin.fortsmart_precision.core.line_geometry import Segment
from plugin.fortsmart_precision.core.obstacle_contour_path import (
    detour_side_toward_pass,
    polyline_max_lateral_offset_m,
)
from plugin.fortsmart_precision.core.planting_kinematics_engine import kinematics_from_planter
from plugin.fortsmart_precision.core.planting_obstacle_engine import (
    apply_planting_avoidance_to_passes,
    lateral_limit_for_pass,
)
from plugin.fortsmart_precision.core.row_engine import PlantingRow
from plugin.fortsmart_precision.core.shutoff_engine import apply_row_shutoff
from plugin.fortsmart_precision.domain.avoidance_configuration import (
    AvoidanceConfiguration,
    AvoidanceMode,
)
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


def traffic_pass(spacing_m: float, y: float = 100.0) -> TrafficPass:
    segment = Segment((0.0, y), (400.0, y))
    return TrafficPass(
        pass_no=1,
        fs_id="pass-1",
        operation_id="op",
        spacing_m=spacing_m,
        width_m=spacing_m,
        offset_m=0.0,
        azimuth_deg=0.0,
        direction="forward",
        clipped_segment=segment,
        guidance_segment=segment,
    )


class DetourSideSelectionTest(unittest.TestCase):
    def test_passes_on_opposite_sides_pick_opposite_arcs(self):
        obstacle = (200.0, 100.0)
        above = Segment((0.0, 110.0), (400.0, 110.0))
        below = Segment((0.0, 90.0), (400.0, 90.0))
        side_above = detour_side_toward_pass(above, obstacle)
        side_below = detour_side_toward_pass(below, obstacle)
        dot = side_above[0] * side_below[0] + side_above[1] * side_below[1]
        self.assertLess(dot, 0.0, "passadas opostas devem abrir para lados opostos")


class LateralOffsetMeasureTest(unittest.TestCase):
    def test_measures_perpendicular_distance_from_guidance(self):
        segment = Segment((0.0, 0.0), (100.0, 0.0))
        points = [(0.0, 0.0), (40.0, -6.5), (60.0, 3.0), (100.0, 0.0)]
        self.assertAlmostEqual(
            polyline_max_lateral_offset_m(points, segment), 6.5, places=6
        )

    def test_measure_is_independent_of_line_direction(self):
        segment = Segment((0.0, 0.0), (70.71067812, 70.71067812))
        points = [(0.0, 0.0), (35.35533906, 35.35533906 + 4.0 * 2**0.5 / 2 * 2)]
        self.assertGreater(polyline_max_lateral_offset_m(points, segment), 0.0)

    def test_limit_is_half_spacing(self):
        self.assertAlmostEqual(lateral_limit_for_pass(traffic_pass(18.0)), 9.0)
        self.assertEqual(lateral_limit_for_pass(traffic_pass(0.0)), float("inf"))


class PlantingDetourStaysInsideSwathTest(unittest.TestCase):
    """Plantadeira de 18 m: o desvio nao pode passar de 9 m do eixo."""

    def setUp(self):
        self.kinematics = PlantingKinematics(
            operational_width_m=18.0,
            track_width_m=1.8,
            hitch_distance_m=3.0,
            tractor_length_m=4.5,
            minimum_turn_radius_m=6.0,
            row_count=36,
            row_spacing_m=0.5,
        )
        self.planter = PlanterMachine(
            machine_id="p18",
            name="Plantadeira 18m",
            row_count=36,
            row_spacing_m=0.5,
            track=MachineTrack(track_width_m=1.8, tire_width_m=0.3),
        )
        self.config = PlantingAvoidanceConfiguration(
            strategy=PlantingAvoidanceStrategy.AUTO,
            enabled=True,
            minimum_turn_radius_m=6.0,
        )

    def test_detour_stays_at_the_nominal_clearance(self):
        """Folga da plantadeira (W/2 + margem) nao e encolhida para a bitola."""
        item = traffic_pass(18.0)
        obstacle = obstacle_from_point(
            (200.0, 100.0), obstacle_radius_m=0.5, safety_margin_m=0.5
        )
        modified, _results, _avoided = apply_planting_avoidance_to_passes(
            [item],
            [obstacle],
            self.kinematics,
            self.config,
            self.planter,
        )
        points = list(modified[0].line_points())
        offset = polyline_max_lateral_offset_m(points, item.guidance_segment)
        # Nominal = 0,5 obst + 9 meia plantadeira + 1,0 margens config ≈ 10,5 m.
        half_w = self.kinematics.half_operational_width_m
        closest = min(
            ((px - 200.0) ** 2 + (py - 100.0) ** 2) ** 0.5 for px, py in points
        )
        self.assertGreaterEqual(closest, half_w - 1e-3)
        # Rmin pode abrir um pouco alem do raio nominal; o teto e meio espacamento
        # da passada vizinha (9 m) elevado pela folga — nunca abaixo de W/2.
        self.assertLessEqual(offset, lateral_limit_for_pass(item) + half_w)

    def test_wide_margin_detour_is_capped_at_half_spacing(self):
        """Margem exagerada nao pode empurrar o trator para a passada vizinha."""
        item = traffic_pass(40.0)
        obstacle = obstacle_from_point(
            (200.0, 100.0), obstacle_radius_m=0.5, safety_margin_m=0.5
        )
        modified, _results, _avoided = apply_planting_avoidance_to_passes(
            [item],
            [obstacle],
            self.kinematics,
            self.config,
            self.planter,
        )
        points = list(modified[0].line_points())
        offset = polyline_max_lateral_offset_m(points, item.guidance_segment)
        self.assertLessEqual(offset, 20.0 + 1e-6)

    def test_detour_still_clears_the_tractor_track(self):
        item = traffic_pass(18.0)
        obstacle = obstacle_from_point(
            (200.0, 100.0), obstacle_radius_m=0.5, safety_margin_m=0.5
        )
        modified, _results, _avoided = apply_planting_avoidance_to_passes(
            [item],
            [obstacle],
            self.kinematics,
            self.config,
            self.planter,
        )
        points = list(modified[0].line_points())
        closest = min(
            ((px - 200.0) ** 2 + (py - 100.0) ** 2) ** 0.5 for px, py in points
        )
        # Plantadeira 18 m: linha do trator a >= 9 m (meia largura), nunca so a bitola.
        self.assertGreaterEqual(closest, self.kinematics.half_operational_width_m - 1e-3)


class PlanterHalfWidthPolygonClearanceTest(unittest.TestCase):
    """Plantadeira 20 m: contorno de poligono/linha a 10 m, nao 3–7 m."""

    def test_polygon_obstacle_keeps_half_implement_width(self):
        from plugin.fortsmart_precision.core.planting_obstacle_engine import _build_contour
        from plugin.fortsmart_precision.core.obstacle_buffer_engine import (
            build_planting_forbidden_region,
        )
        from plugin.fortsmart_precision.domain.obstacle_model import Obstacle, ObstacleType

        kin = PlantingKinematics(
            operational_width_m=20.0,
            track_width_m=2.0,
            hitch_distance_m=0.0,
            row_count=40,
            row_spacing_m=0.5,
        )
        cfg = PlantingAvoidanceConfiguration(enabled=True)
        poly = (
            [(50.0, -1.0), (150.0, -1.0), (150.0, 1.0), (50.0, 1.0), (50.0, -1.0)],
            [],
        )
        obs = Obstacle(
            obstacle_id="fence",
            obstacle_type=ObstacleType.POLYGON,
            center=(100.0, 0.0),
            obstacle_radius_m=0.0,
            polygon=poly,
        )
        reg = build_planting_forbidden_region(obs, kin, cfg)
        built = _build_contour(
            Segment((0.0, 0.0), (200.0, 0.0)),
            reg,
            kin,
            obstacle=obs,
            finalize=True,
        )
        self.assertIsNotNone(built)
        path = built[0]
        # Distancia do trator a borda do poligono (y=±1).
        gaps = [abs(p[1]) - 1.0 for p in path if 50.0 <= p[0] <= 150.0]
        self.assertTrue(gaps)
        self.assertGreaterEqual(min(gaps), 9.5, "20 m -> folga >= 10 m na ponta, nao 3–7 m")
        self.assertGreaterEqual(built[5], kin.half_operational_width_m)

    def test_point_obstacle_stays_at_half_width_not_full(self):
        """Plantadeira 20 m + poste: trator a ~10 m + margem, nunca ~20 m (2x W/2)."""
        from plugin.fortsmart_precision.core.planting_obstacle_engine import (
            _build_contour,
            apply_planting_avoidance_to_passes,
        )
        from plugin.fortsmart_precision.core.obstacle_buffer_engine import (
            build_planting_forbidden_region,
        )
        from plugin.fortsmart_precision.domain.machine_model import MachineTrack, PlanterMachine

        kin = PlantingKinematics(
            operational_width_m=20.0,
            track_width_m=3.0,
            hitch_distance_m=3.0,
            row_count=40,
            row_spacing_m=0.5,
            minimum_turn_radius_m=12.0,
        )
        cfg = PlantingAvoidanceConfiguration(
            inner_margin_m=0.25,
            outer_margin_m=0.25,
            enabled=True,
        )
        obs = obstacle_from_point(
            (200.0, 100.0), obstacle_radius_m=0.5, safety_margin_m=0.5
        )
        reg = build_planting_forbidden_region(obs, kin, cfg)
        built = _build_contour(
            Segment((0.0, 100.0), (400.0, 100.0)),
            reg,
            kin,
            obstacle=obs,
            finalize=True,
        )
        self.assertIsNotNone(built)
        path = built[0]
        center = obs.center
        min_center = min(
            ((px - center[0]) ** 2 + (py - center[1]) ** 2) ** 0.5 for px, py in path
        )
        nominal = reg.implement_clearance_radius_m
        self.assertLessEqual(
            min_center,
            nominal + 5.0,
            "centro do trator nao pode ir a ~2x meia barra (~20 m em 20 m)",
        )
        self.assertGreaterEqual(min_center, nominal - 0.5)
        self.assertLess(
            min_center,
            kin.operational_width_m + 1.0,
            "nao usar largura inteira (20 m) como folga do trator",
        )

        planter = PlanterMachine(
            machine_id="p20",
            name="20m",
            row_count=40,
            row_spacing_m=0.5,
            track=MachineTrack(track_width_m=3.0, tire_width_m=0.4),
        )
        item = traffic_pass(20.0, y=100.0)
        modified, _, _ = apply_planting_avoidance_to_passes(
            [item], [obs], kin, cfg, planter
        )
        pts = list(modified[0].line_points())
        min_pipe = min(
            ((px - center[0]) ** 2 + (py - center[1]) ** 2) ** 0.5 for px, py in pts
        )
        self.assertLessEqual(min_pipe, nominal + 5.0)


class SprayGroupedEnvelopeUsesGroupCenterTest(unittest.TestCase):
    """Grupo fundido: anel no centro do envelope, nao no 1o poste."""

    def test_merged_posts_clear_each_member(self):
        from plugin.fortsmart_precision.core.obstacle_buffer_engine import (
            build_all_envelopes,
            merge_adjacent_envelopes,
        )

        sprayer = SprayerMachine(
            machine_id="s36",
            name="36m",
            nozzle_count=72,
            nozzle_spacing_m=0.5,
            boom_width_m=36.0,
            track=MachineTrack(track_width_m=3.0, tire_width_m=0.4),
        )
        # Tres postes alinhados na passada — devem fundir.
        centers = [(180.0, 100.0), (200.0, 100.0), (220.0, 100.0)]
        obstacles = [
            obstacle_from_point(c, obstacle_radius_m=0.5, safety_margin_m=0.5)
            for c in centers
        ]
        envelopes = merge_adjacent_envelopes(
            build_all_envelopes(obstacles, sprayer),
            2.0,
        )
        self.assertEqual(len(envelopes), 1)
        group = envelopes[0]
        self.assertIn("+", group.obstacle_id)

        item = traffic_pass(36.0)
        modified, avoided = apply_application_obstacle_avoidance(
            [item],
            obstacles,
            sprayer,
            AvoidanceConfiguration(
                mode=AvoidanceMode.CONCENTRIC_RING,
                minimum_turn_radius_m=8.0,
                merge_adjacent_envelopes_m=2.0,
            ),
        )
        self.assertGreater(len(avoided), 0)
        path = list(modified[0].line_points())
        half = sprayer.half_operational_width_m
        for center in centers:
            closest = min(
                ((px - center[0]) ** 2 + (py - center[1]) ** 2) ** 0.5 for px, py in path
            )
            self.assertGreaterEqual(
                closest,
                half - 1.0,
                f"poste {center} ainda dentro da barra (dist={closest:.2f})",
            )


class SprayDetourStaysInsideSwathTest(unittest.TestCase):
    """Barra de 36 m: folga nominal de 19 m e nada alem disso."""

    def test_boom_detour_stays_at_the_nominal_clearance(self):
        item = traffic_pass(36.0)
        sprayer = SprayerMachine(
            machine_id="s36",
            name="Pulverizador 36m",
            nozzle_count=72,
            nozzle_spacing_m=0.5,
            boom_width_m=36.0,
            track=MachineTrack(track_width_m=3.0, tire_width_m=0.37),
        )
        obstacle = obstacle_from_point(
            (200.0, 100.0), obstacle_radius_m=0.5, safety_margin_m=0.5
        )
        modified, _avoided = apply_application_obstacle_avoidance(
            [item],
            [obstacle],
            sprayer,
            AvoidanceConfiguration(
                mode=AvoidanceMode.CONCENTRIC_RING, minimum_turn_radius_m=6.0
            ),
        )
        points = list(modified[0].line_points())
        offset = polyline_max_lateral_offset_m(points, item.guidance_segment)
        # Nominal = 0,5 obstaculo + 18 meia barra + 0,5 margem.
        self.assertLessEqual(offset, 19.0 + 1e-6)


class SprayMultiObstaclePerformanceTest(unittest.TestCase):
    def test_two_obstacles_yield_two_detours_not_a_loop(self):
        item = traffic_pass(36.0)
        sprayer = SprayerMachine(
            machine_id="s36",
            name="Pulverizador 36m",
            nozzle_count=72,
            nozzle_spacing_m=0.5,
            boom_width_m=36.0,
            track=MachineTrack(track_width_m=3.0, tire_width_m=0.37),
        )
        obstacles = [
            obstacle_from_point((150.0, 100.0), obstacle_radius_m=0.5, safety_margin_m=0.5),
            obstacle_from_point((250.0, 100.0), obstacle_radius_m=0.5, safety_margin_m=0.5),
        ]
        _modified, avoided = apply_application_obstacle_avoidance(
            [item],
            obstacles,
            sprayer,
            AvoidanceConfiguration(
                mode=AvoidanceMode.CONCENTRIC_RING, minimum_turn_radius_m=6.0
            ),
        )
        self.assertEqual(len(avoided), 1)
        self.assertGreater(len(_modified[0].line_points()), 2)

    def test_merged_envelope_is_not_reprocessed(self):
        item = traffic_pass(36.0)
        sprayer = SprayerMachine(
            machine_id="s36",
            name="Pulverizador 36m",
            nozzle_count=72,
            nozzle_spacing_m=0.5,
            boom_width_m=36.0,
            track=MachineTrack(track_width_m=3.0, tire_width_m=0.37),
        )
        obstacles = [
            obstacle_from_point((200.0, 100.0), obstacle_radius_m=0.5, safety_margin_m=0.5),
            obstacle_from_point((201.5, 100.0), obstacle_radius_m=0.5, safety_margin_m=0.5),
        ]
        _modified, avoided = apply_application_obstacle_avoidance(
            [item],
            obstacles,
            sprayer,
            AvoidanceConfiguration(
                mode=AvoidanceMode.CONCENTRIC_RING,
                minimum_turn_radius_m=6.0,
                merge_adjacent_envelopes_m=2.0,
            ),
        )
        self.assertEqual(len(avoided), 1)


class PlanterPassSpacingTest(unittest.TestCase):
    def test_effective_spacing_is_operational_width(self):
        planter = PlanterMachine(
            machine_id="p40",
            name="40x0.5",
            row_count=40,
            row_spacing_m=0.5,
            track=MachineTrack(track_width_m=1.8, tire_width_m=0.3),
        )
        self.assertAlmostEqual(planter.operational_width_m, 20.0)
        self.assertAlmostEqual(planter.meeting_half_gap_m, 0.25)
        self.assertAlmostEqual(planter.meeting_spacing_m(), 0.5)
        self.assertAlmostEqual(planter.effective_pass_spacing_m, 20.0)


class SwathObstacleDetectionTest(unittest.TestCase):
    def test_edge_obstacle_triggers_contour_without_axis_crossing(self):
        """Obstaculo na ponta da plantadeira: eixo passa reto mas a barra bate."""
        kinematics = PlantingKinematics(
            operational_width_m=20.0,
            track_width_m=1.8,
            hitch_distance_m=3.0,
            tractor_length_m=4.5,
            minimum_turn_radius_m=6.0,
            row_count=40,
            row_spacing_m=0.5,
        )
        planter = PlanterMachine(
            machine_id="p40",
            name="40x0.5",
            row_count=40,
            row_spacing_m=0.5,
            track=MachineTrack(track_width_m=1.8, tire_width_m=0.3),
        )
        config = PlantingAvoidanceConfiguration(
            strategy=PlantingAvoidanceStrategy.AUTO,
            enabled=True,
            minimum_turn_radius_m=6.0,
        )
        # Centro do obstaculo a 8 m do eixo: dentro da meia barra (10 m).
        obstacle = obstacle_from_point((200.0, 108.0), obstacle_radius_m=0.5, safety_margin_m=0.5)
        item = traffic_pass(20.0, y=100.0)
        modified, results, _avoided = apply_planting_avoidance_to_passes(
            [item],
            [obstacle],
            kinematics,
            config,
            planter,
        )
        self.assertEqual(len(results), 1)
        self.assertGreater(len(modified[0].line_points()), 2)


class CurvedPassSwathDetectionTest(unittest.TestCase):
    def test_polyline_detects_obstacle_on_implement_edge(self):
        """Curva AB: obstaculo na ponta da barra num trecho curto."""
        from plugin.fortsmart_precision.core.obstacle_buffer_engine import (
            build_planting_forbidden_region,
        )
        from plugin.fortsmart_precision.core.obstacle_contour_path import (
            polyline_forbidden_hit_range,
        )
        from plugin.fortsmart_precision.domain.planting_avoidance_configuration import (
            PlantingAvoidanceConfiguration,
        )

        kinematics = PlantingKinematics(
            operational_width_m=20.0,
            track_width_m=1.8,
            row_count=40,
            row_spacing_m=0.5,
        )
        config = PlantingAvoidanceConfiguration(enabled=True)
        obstacle = obstacle_from_point((150.0, 108.0), obstacle_radius_m=0.5, safety_margin_m=0.5)
        region = build_planting_forbidden_region(obstacle, kinematics, config)
        # Polilinha levemente curva; eixo passa a 8 m do obstaculo (dentro da meia barra).
        # A zona ja embute W/2 — half_width_m=0 evita contar 2x a meia largura.
        polyline = [(0.0, 100.0), (75.0, 101.0), (150.0, 102.0), (225.0, 101.0), (300.0, 100.0)]
        hit = polyline_forbidden_hit_range(polyline, region, half_width_m=0.0)
        self.assertIsNotNone(hit)


class DetourSmoothingTest(unittest.TestCase):
    def test_finalize_path_adds_smooth_vertices(self):
        from plugin.fortsmart_precision.core.planting_obstacle_engine import (
            _finalize_avoidance_path,
        )

        jagged = [(0.0, 0.0), (40.0, 0.0), (50.0, 5.0), (60.0, 0.0), (100.0, 0.0)]
        smooth = _finalize_avoidance_path(jagged)
        self.assertGreater(len(smooth), len(jagged))


class MultiObstaclePassTest(unittest.TestCase):
    """Passada reta com varios obstaculos deve contornar todos."""

    def test_straight_pass_avoids_three_obstacles(self):
        import math

        planter = PlanterMachine(
            machine_id="p",
            name="40x0.5",
            row_count=40,
            row_spacing_m=0.5,
            track=MachineTrack(track_width_m=1.8, tire_width_m=0.3),
        )
        kin = kinematics_from_planter(planter)
        config = PlantingAvoidanceConfiguration(
            strategy=PlantingAvoidanceStrategy.AUTO,
            enabled=True,
            minimum_turn_radius_m=6.0,
        )
        centers = [(100.0, 100.0), (200.0, 100.0), (300.0, 100.0)]
        obstacles = [
            obstacle_from_point(center, obstacle_radius_m=0.5, safety_margin_m=0.5)
            for center in centers
        ]
        seg = Segment((0.0, 100.0), (400.0, 100.0))
        item = TrafficPass(
            pass_no=0,
            fs_id="p0",
            operation_id="planting",
            spacing_m=20.0,
            width_m=20.0,
            offset_m=0.0,
            azimuth_deg=0.0,
            direction="forward",
            clipped_segment=seg,
            guidance_segment=seg,
        )
        modified, results, avoided = apply_planting_avoidance_to_passes(
            [item], obstacles, kin, config, planter
        )
        pts = list(modified[0].line_points())
        self.assertEqual(len(results), 3, "deveria gerar um desvio por obstaculo")
        self.assertEqual(len(avoided), 1, "um AvoidedPath final por passada")
        clearance = kin.half_operational_width_m + config.total_margin_m() + 0.5
        for center in centers:
            dist_min = min(math.hypot(p[0] - center[0], p[1] - center[1]) for p in pts)
            self.assertGreater(
                dist_min,
                clearance - 0.5,
                f"passada ainda invade zona do obstaculo em {center}",
            )


class PlantingManyObstaclesPerformanceTest(unittest.TestCase):
    def test_forty_obstacles_one_pass_completes_quickly(self):
        import time

        planter = PlanterMachine(
            machine_id="p",
            name="40x0.5",
            row_count=40,
            row_spacing_m=0.5,
            track=MachineTrack(track_width_m=1.8, tire_width_m=0.3),
        )
        kin = kinematics_from_planter(planter)
        config = PlantingAvoidanceConfiguration(
            strategy=PlantingAvoidanceStrategy.AUTO,
            enabled=True,
            minimum_turn_radius_m=6.0,
        )
        obstacles = [
            obstacle_from_point((50.0 + i * 10.0, 100.0), obstacle_radius_m=0.5, safety_margin_m=0.5)
            for i in range(40)
        ]
        item = TrafficPass(
            pass_no=0,
            fs_id="p0",
            operation_id="planting",
            spacing_m=20.0,
            width_m=20.0,
            offset_m=0.0,
            azimuth_deg=0.0,
            direction="forward",
            clipped_segment=Segment((0.0, 100.0), (800.0, 100.0)),
            guidance_segment=Segment((0.0, 100.0), (800.0, 100.0)),
        )
        t0 = time.perf_counter()
        _modified, results, _avoided = apply_planting_avoidance_to_passes(
            [item], obstacles, kin, config, planter
        )
        elapsed = time.perf_counter() - t0
        # Fileira continua de postes vira corredores, nao 40 sobe-e-desce.
        self.assertGreater(len(results), 0)
        self.assertLess(len(results), 40)
        grouped_ids = {oid for r in results for oid in r.obstacle_ids}
        self.assertEqual(len(grouped_ids), 40, "nenhum obstaculo pode ficar sem cobertura")
        self.assertLess(elapsed, 20.0, "deteccao circular deve evitar travamento")


class ObstacleZoneTurnsSeedingOffTest(unittest.TestCase):
    """Linha que passa sobre o obstaculo sai de operacao, mesmo dentro do miolo."""

    def _row(self, row_id: int, y: float) -> PlantingRow:
        segment = Segment((0.0, y), (400.0, y))
        return PlantingRow(
            fs_id=f"row-{row_id}",
            row_id=row_id,
            pass_id=1,
            machine_id="p18",
            spacing_m=0.5,
            direction="forward",
            offset_m=0.0,
            azimuth_deg=0.0,
            segment=segment,
            path_points=((0.0, y), (400.0, y)),
        )

    def test_off_area_wins_over_on_area(self):
        inner = [
            ([(-10.0, -10.0), (410.0, -10.0), (410.0, 210.0), (-10.0, 210.0), (-10.0, -10.0)], [])
        ]
        obstacle_zone = [
            ([(195.0, 95.0), (205.0, 95.0), (205.0, 105.0), (195.0, 105.0), (195.0, 95.0)], [])
        ]
        segments = apply_row_shutoff(
            [self._row(1, 100.0), self._row(2, 150.0)],
            [],
            off_areas=obstacle_zone,
            on_areas=inner,
            shutoff_on_tramlines=False,
        )
        off_on_row1 = [
            item for item in segments if item.row_id == 1 and item.shutoff_state == "off"
        ]
        off_on_row2 = [
            item for item in segments if item.row_id == 2 and item.shutoff_state == "off"
        ]
        self.assertTrue(off_on_row1, "linha sobre o obstaculo deveria desligar")
        self.assertFalse(off_on_row2, "linha longe do obstaculo deveria continuar ligada")


if __name__ == "__main__":
    unittest.main()
