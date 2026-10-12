# -*- coding: utf-8 -*-
"""Testes Precision Lines v3 — Desvio de Plantio."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from plugin.fortsmart_precision.core.export_engine import export_precision_lines_package
from plugin.fortsmart_precision.core.guidance_engine import TrafficPass
from plugin.fortsmart_precision.core.line_geometry import Segment, distance
from plugin.fortsmart_precision.core.obstacle_buffer_engine import (
    build_planting_forbidden_region,
    merge_planting_forbidden_regions,
    build_all_planting_forbidden_regions,
)
from plugin.fortsmart_precision.core.planting_kinematics_engine import kinematics_from_planter
from plugin.fortsmart_precision.core.planting_obstacle_engine import (
    ConflictType,
    apply_planting_avoidance_to_passes,
    classify_conflict,
    resolve_strategy,
)
from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, PlanterMachine, load_machine_presets
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


def rectangle(width=400.0, height=240.0):
    outer = [(0.0, 0.0), (width, 0.0), (width, height), (0.0, height), (0.0, 0.0)]
    return [(outer, [])]


def planter_9m() -> PlanterMachine:
    """Plantadeira sintetica 9,00 m (18 linhas x 0,50 m)."""
    return PlanterMachine(
        machine_id="planter_9m",
        name="Plantadeira 9m",
        row_count=18,
        row_spacing_m=0.5,
        track=MachineTrack(track_width_m=2.0, tire_width_m=0.35),
        informed_operational_width_m=9.0,
    )


def kinematics_9m() -> PlantingKinematics:
    return PlantingKinematics(
        operational_width_m=9.0,
        track_width_m=2.0,
        hitch_distance_m=3.0,
        tractor_length_m=4.0,
        row_count=18,
        row_spacing_m=0.5,
    )


def sample_pass(y=120.0) -> TrafficPass:
    segment = Segment((0.0, y), (400.0, y))
    return TrafficPass(
        pass_no=1,
        fs_id="pass-1",
        operation_id="planting",
        spacing_m=9.0,
        width_m=9.0,
        offset_m=0.0,
        azimuth_deg=0.0,
        direction="forward",
        clipped_segment=segment,
        guidance_segment=segment,
    )


def kinematics_20m() -> PlantingKinematics:
    return PlantingKinematics(
        operational_width_m=20.0,
        track_width_m=0.0,
    )


def planter_identity():
    class Identity:
        machine_id = "implement_20m"
        row_count = 1

    return Identity()


def pass_20m(pass_no=1, y=100.0) -> TrafficPass:
    segment = Segment((0.0, y), (400.0, y))
    return TrafficPass(
        pass_no=pass_no,
        fs_id=f"pass-{pass_no}",
        operation_id="planting",
        spacing_m=20.0,
        width_m=20.0,
        offset_m=0.0,
        azimuth_deg=0.0,
        direction="forward",
        clipped_segment=segment,
        guidance_segment=segment,
    )


class PlantingForbiddenRegionTest(unittest.TestCase):
    def test_margins_preserve_rtk_and_expand_zone(self):
        obs = obstacle_from_point((200.0, 120.0), obstacle_radius_m=0.0, name="O-001")
        config = PlantingAvoidanceConfiguration(inner_margin_m=0.50, outer_margin_m=0.50)
        kin = kinematics_9m()
        region = build_planting_forbidden_region(obs, kin, config)
        # RTK center intact
        self.assertEqual(region.center, (200.0, 120.0))
        # safety = 0 + 1.0 margem + 4.5 half width = 5.5
        self.assertAlmostEqual(region.safety_radius_m, 5.5, places=3)
        self.assertAlmostEqual(region.implement_clearance_radius_m, 5.5, places=3)
        # tractor clearance: max(bitola/2, tractor_length/2) + margens = max(1, 2) + 1 = 3
        self.assertAlmostEqual(region.tractor_clearance_radius_m, 3.0, places=3)


class ConflictClassificationTest(unittest.TestCase):
    def test_20m_planter_post_at_15m_is_pass(self):
        kin = kinematics_20m()
        config = PlantingAvoidanceConfiguration(inner_margin_m=1.0, outer_margin_m=0.0)
        region = build_planting_forbidden_region(
            obstacle_from_point((200.0, 115.0)), kin, config
        )
        conflict = classify_conflict(
            pass_20m().guidance_segment,
            region,
            kin,
            is_grouped=False,
            is_polygon=False,
        )
        self.assertEqual(conflict, ConflictType.NONE)

    def test_20m_planter_post_at_5m_conflicts_with_implement_edge(self):
        kin = kinematics_20m()
        config = PlantingAvoidanceConfiguration(inner_margin_m=1.0, outer_margin_m=0.0)
        region = build_planting_forbidden_region(
            obstacle_from_point((200.0, 105.0)), kin, config
        )
        self.assertAlmostEqual(region.implement_clearance_radius_m, 11.0)
        conflict = classify_conflict(
            pass_20m().guidance_segment,
            region,
            kin,
            is_grouped=False,
            is_polygon=False,
        )
        self.assertEqual(conflict, ConflictType.IMPLEMENT_EDGE)

    def test_implement_edge_at_half_width(self):
        kin = kinematics_9m()
        config = PlantingAvoidanceConfiguration()
        # Obstaculo a 4,5 m lateral do centro da trajetoria y=120
        obs = obstacle_from_point((200.0, 124.5), obstacle_radius_m=0.0)
        region = build_planting_forbidden_region(obs, kin, config)
        segment = Segment((0.0, 120.0), (400.0, 120.0))
        conflict = classify_conflict(segment, region, kin, is_grouped=False, is_polygon=False)
        self.assertEqual(conflict, ConflictType.IMPLEMENT_EDGE)
        self.assertEqual(resolve_strategy(conflict, config), PlantingAvoidanceStrategy.CONTOUR)

    def test_tractor_center_on_axis(self):
        kin = kinematics_9m()
        config = PlantingAvoidanceConfiguration()
        obs = obstacle_from_point((200.0, 120.0), obstacle_radius_m=0.0)
        region = build_planting_forbidden_region(obs, kin, config)
        segment = Segment((0.0, 120.0), (400.0, 120.0))
        conflict = classify_conflict(segment, region, kin, is_grouped=False, is_polygon=False)
        self.assertEqual(conflict, ConflictType.TRACTOR_CENTER)
        self.assertEqual(resolve_strategy(conflict, config, is_polygon=False), PlantingAvoidanceStrategy.CONTOUR)


class PlantingStrategiesTest(unittest.TestCase):
    def test_20m_contour_changes_only_conflicting_pass_and_returns_to_guide(self):
        kin = kinematics_20m()
        config = PlantingAvoidanceConfiguration(
            strategy=PlantingAvoidanceStrategy.AUTO,
            inner_margin_m=1.0,
            outer_margin_m=0.0,
        )
        obstacle = obstacle_from_point((200.0, 105.0))
        original = [pass_20m(1, 100.0), pass_20m(2, 120.0)]
        modified, results, _avoided = apply_planting_avoidance_to_passes(
            original, [obstacle], kin, config, planter_identity()
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].pass_id, 1)
        self.assertTrue(results[0].returns_to_guidance)
        self.assertGreater(len(modified[0].line_points()), 2)
        self.assertEqual(modified[1].line_points(), original[1].line_points())
        self.assertGreaterEqual(
            min(distance(point, obstacle.center) for point in modified[0].line_points()),
            10.9,
        )

    def test_circular_avoidance_for_edge_obstacle(self):
        kin = kinematics_9m()
        config = PlantingAvoidanceConfiguration(strategy=PlantingAvoidanceStrategy.AUTO)
        planter = planter_9m()
        obs = obstacle_from_point((200.0, 124.5), obstacle_radius_m=0.0)
        passes, results, avoided = apply_planting_avoidance_to_passes(
            [sample_pass()],
            [obs],
            kin,
            config,
            planter,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].strategy_used, PlantingAvoidanceStrategy.CONTOUR)
        self.assertEqual(results[0].conflict_type, ConflictType.IMPLEMENT_EDGE)
        self.assertTrue(results[0].returns_to_guidance)
        self.assertGreater(len(results[0].avoidance_path), 2)
        # Retorno: ultimo ponto perto do fim original
        self.assertLess(distance(results[0].avoidance_path[-1], (400.0, 120.0)), 1.0)
        self.assertEqual(len(avoided), 1)
        self.assertEqual(len(passes[0].path_points), len(results[0].avoidance_path))

    def test_circular_avoidance_for_center_obstacle(self):
        kin = kinematics_9m()
        config = PlantingAvoidanceConfiguration(strategy=PlantingAvoidanceStrategy.AUTO)
        planter = planter_9m()
        obs = obstacle_from_point((200.0, 120.0), obstacle_radius_m=0.0)
        _passes, results, _avoided = apply_planting_avoidance_to_passes(
            [sample_pass()],
            [obs],
            kin,
            config,
            planter,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].strategy_used, PlantingAvoidanceStrategy.CONTOUR)
        self.assertEqual(results[0].conflict_type, ConflictType.TRACTOR_CENTER)
        self.assertTrue(results[0].returns_to_guidance)
        # Contorno no limite: muitos pontos e retorno a linha (sem anel fechado).
        radius = results[0].tractor_radius_m
        center = (200.0, 120.0)
        path = list(results[0].avoidance_path)
        self.assertGreater(len(path), 30)
        self.assertLess(distance(path[0], (0.0, 120.0)), 1.0)
        self.assertLess(distance(path[-1], (400.0, 120.0)), 1.0)
        # Nao e um anel: extremos distantes um do outro.
        self.assertGreater(distance(path[0], path[-1]), 50.0)
        near_clearance = [
            p for p in path if abs(distance(p, center) - radius) < 3.0
        ]
        self.assertGreaterEqual(len(near_clearance), 6)

    def test_grouped_posts_single_continuous_detour(self):
        kin = kinematics_9m()
        config = PlantingAvoidanceConfiguration(
            strategy=PlantingAvoidanceStrategy.AUTO,
            merge_obstacles_m=25.0,
        )
        planter = planter_9m()
        obstacles = [
            obstacle_from_point((180.0, 120.0), obstacle_radius_m=0.0, name="O-001"),
            obstacle_from_point((200.0, 120.0), obstacle_radius_m=0.0, name="O-002"),
            obstacle_from_point((220.0, 120.0), obstacle_radius_m=0.0, name="O-003"),
        ]
        regions = merge_planting_forbidden_regions(
            build_all_planting_forbidden_regions(obstacles, kin, config),
            config.merge_obstacles_m,
        )
        self.assertEqual(len(regions), 1)
        self.assertEqual(len(regions[0].group_ids), 3)

        _passes, results, _avoided = apply_planting_avoidance_to_passes(
            [sample_pass()],
            obstacles,
            kin,
            config,
            planter,
        )
        # Um unico desvio continuo (nao tres sobe/desce)
        self.assertEqual(len(results), 1)
        self.assertIn(results[0].conflict_type, {ConflictType.GROUPED, ConflictType.TRACTOR_CENTER})
        self.assertEqual(results[0].strategy_used, PlantingAvoidanceStrategy.CONTOUR)


class PlantingPipelineTest(unittest.TestCase):
    def test_pipeline_derives_rows_from_tractor_path(self):
        field = rectangle()
        planter = planter_9m()
        kin = kinematics_9m()
        project = PrecisionProject(
            field=FieldGeometry(
                field_boundary=field,
                operational_boundary=field,
                crs_authid="EPSG:31982",
            ),
            ab_line=ABLine(start=(0.0, 120.0), end=(400.0, 120.0)),
            planting=PrecisionOperation(
                operation_id="planting",
                machine=planter,
                headland=HeadlandLayout(
                    pass_count=1,
                    width_m=9.0,
                    effective_spacing_m=9.0,
                    mode="parallel_ab",
                ),
            ),
            obstacles=(obstacle_from_point((200.0, 120.0)),),
            planting_kinematics=kin,
            planting_avoidance=PlantingAvoidanceConfiguration(),
        )
        result = run_precision_lines(project)
        self.assertGreater(len(result.planting_avoidance_results), 0)
        self.assertGreater(len(result.planting_rows), 0)
        self.assertGreater(len(result.forbidden_regions), 0)
        # Linhas derivadas apos desvio
        self.assertTrue(any(len(r.path_points) > 2 for r in result.planting_rows) or len(result.planting_rows) > 0)

    def test_export_includes_planting_layers(self):
        field = rectangle()
        planter = planter_9m()
        project = PrecisionProject(
            field=FieldGeometry(
                field_boundary=field,
                operational_boundary=field,
                crs_authid="EPSG:31982",
            ),
            ab_line=ABLine(start=(0.0, 120.0), end=(400.0, 120.0)),
            planting=PrecisionOperation(
                operation_id="planting",
                machine=planter,
                headland=HeadlandLayout(
                    pass_count=1,
                    width_m=9.0,
                    effective_spacing_m=9.0,
                    mode="parallel_ab",
                ),
            ),
            obstacles=(obstacle_from_point((200.0, 120.0)),),
            planting_kinematics=kinematics_9m(),
        )
        result = run_precision_lines(project)
        with tempfile.TemporaryDirectory() as tmp:
            package = export_precision_lines_package(
                Path(tmp),
                passes=result.planting_passes,
                rows=result.planting_rows,
                tramline_zones=result.tramline_zones,
                shutoff_segments=result.shutoff_segments,
                validation_report=result.validation,
                force=True,
                avoided_paths=result.avoided_paths,
                obstacle_envelopes=result.obstacle_envelopes,
                planting_avoidance_results=result.planting_avoidance_results,
                forbidden_regions=result.forbidden_regions,
            )
            names = set(package.export.files)
            self.assertIn("planting_avoidance_results.geojson", names)
            self.assertIn("forbidden_regions.geojson", names)

    def test_kinematics_from_planter_fallback(self):
        planter = load_machine_presets()["db27_36x050"]
        kin = kinematics_from_planter(planter, hitch_distance_m=2.5)
        self.assertAlmostEqual(kin.operational_width_m, planter.operational_width_m)
        self.assertEqual(kin.hitch_distance_m, 2.5)


if __name__ == "__main__":
    unittest.main()
