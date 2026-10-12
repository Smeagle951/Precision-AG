# -*- coding: utf-8 -*-
"""Caso de ouro: raio operacional, arco que nao apaga a passada, agrupamento e rastros."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.line_geometry import distance
from plugin.fortsmart_precision.core.obstacle_buffer_engine import (
    build_all_envelopes,
    build_planting_forbidden_region,
    merge_adjacent_envelopes,
)
from plugin.fortsmart_precision.core.planting_kinematics_engine import kinematics_from_planter
from plugin.fortsmart_precision.core.planting_obstacle_engine import ConflictType
from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
from plugin.fortsmart_precision.core.preview_layer_names import NAMED_PREVIEW_LAYERS, PREVIEW_PREFIX
from plugin.fortsmart_precision.core.tire_track_engine import generate_tire_tracks, offset_polyline
from plugin.fortsmart_precision.domain.avoidance_configuration import AvoidanceConfiguration, AvoidanceMode
from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, PlanterMachine, SprayerMachine
from plugin.fortsmart_precision.domain.obstacle_model import obstacle_from_point
from plugin.fortsmart_precision.domain.path_smoothing_configuration import (
    PathSmoothingConfiguration,
    SmoothingLevel,
)
from plugin.fortsmart_precision.domain.planting_avoidance_configuration import PlantingAvoidanceConfiguration
from plugin.fortsmart_precision.domain.precision_project import (
    ABLine,
    FieldGeometry,
    PrecisionOperation,
    PrecisionProject,
)


def rectangle(width=400.0, height=240.0):
    outer = [(0.0, 0.0), (width, 0.0), (width, height), (0.0, height), (0.0, 0.0)]
    return [(outer, [])]


def sprayer_boom(width_m: float) -> SprayerMachine:
    return SprayerMachine(
        machine_id=f"boom_{int(width_m)}",
        name=f"Barra {width_m:.0f}m",
        nozzle_count=max(1, int(round(width_m / 0.5))),
        nozzle_spacing_m=0.5,
        boom_width_m=width_m,
        track=MachineTrack(track_width_m=3.10, tire_width_m=0.35),
        overlap_m=0.0,
    )


def planter_18m() -> PlanterMachine:
    return PlanterMachine(
        machine_id="p18",
        name="Plantadeira 18m",
        row_count=36,
        row_spacing_m=0.50,
        track=MachineTrack(track_width_m=1.8, tire_width_m=0.3),
    )


def field_project(**kwargs) -> PrecisionProject:
    field = rectangle()
    defaults = dict(
        field=FieldGeometry(
            field_boundary=field,
            operational_boundary=field,
            crs_authid="EPSG:31982",
        ),
        ab_line=ABLine(start=(0.0, 120.0), end=(400.0, 120.0)),
        line_smoothing=PathSmoothingConfiguration(level=SmoothingLevel.OFF),
        avoidance=AvoidanceConfiguration(mode=AvoidanceMode.CONCENTRIC_RING),
    )
    defaults.update(kwargs)
    return PrecisionProject(**defaults)


class NamedPreviewLayersTest(unittest.TestCase):
    def test_named_layers_include_field_headland_passes(self):
        self.assertEqual(len(NAMED_PREVIEW_LAYERS), 15)
        self.assertEqual(len(set(NAMED_PREVIEW_LAYERS)), 15)
        self.assertEqual(NAMED_PREVIEW_LAYERS[0], "01_Limite_Externo")
        self.assertEqual(NAMED_PREVIEW_LAYERS[7], "08_Rastros_Pneus")
        self.assertEqual(NAMED_PREVIEW_LAYERS[-3], "13_Shutoff")
        self.assertEqual(NAMED_PREVIEW_LAYERS[-2], "14_Limite_Operacional")
        self.assertEqual(NAMED_PREVIEW_LAYERS[-1], "15_Passadas_Bordadura")
        # Prefixo antigo so e reconhecido para limpeza; nao entra mais no nome.
        self.assertTrue(PREVIEW_PREFIX.startswith("_fortsmart_workspace_"))


class ApplicationRadiusTest(unittest.TestCase):
    def _assert_boom_radius(self, width_m: float, obstacle_radius=0.0, margin=0.50) -> None:
        machine = sprayer_boom(width_m)
        expected = obstacle_radius + width_m / 2.0 + margin
        obs = obstacle_from_point(
            (200.0, 120.0),
            obstacle_radius_m=obstacle_radius,
            safety_margin_m=margin,
            obstacle_id="rtk",
        )
        self.assertAlmostEqual(obs.safety_zone_radius_m(), obstacle_radius + margin, places=3)
        self.assertAlmostEqual(obs.application_radius_m(machine), expected, places=3)
        self.assertAlmostEqual(machine.half_operational_width_m, width_m / 2.0, places=3)

        project = field_project(
            spraying=PrecisionOperation(operation_id="spraying", machine=machine),
            obstacles=(obs,),
        )
        result = run_precision_lines(project)
        self.assertGreater(len(result.avoided_paths), 0)
        path = result.avoided_paths[0]
        self.assertAlmostEqual(path.application_radius_m, expected, places=3)
        ring_points = [
            p for p in path.modified_points if abs(distance(p, obs.center) - expected) < 1.0
        ]
        self.assertGreater(len(ring_points), 6)

    def test_boom_36_obstacle_3m_radius_golden(self):
        self._assert_boom_radius(36.0, obstacle_radius=3.0, margin=0.50)

    def test_boom_36_center_at_18_plus_margin(self):
        self._assert_boom_radius(36.0)

    def test_boom_24_center_at_12_plus_margin(self):
        self._assert_boom_radius(24.0)

    def test_boom_30_center_at_15_plus_margin(self):
        self._assert_boom_radius(30.0)


class PassContinuesAfterArcTest(unittest.TestCase):
    def test_arc_does_not_delete_pass(self):
        machine = sprayer_boom(24.0)
        obs = obstacle_from_point(
            (200.0, 120.0),
            obstacle_radius_m=0.0,
            safety_margin_m=0.50,
            obstacle_id="rtk",
        )
        project = field_project(
            spraying=PrecisionOperation(operation_id="spraying", machine=machine),
            obstacles=(obs,),
        )
        result = run_precision_lines(project)
        self.assertGreater(len(result.spraying_passes), 0)
        self.assertGreater(len(result.avoided_paths), 0)
        for traffic_pass in result.spraying_passes:
            pts = traffic_pass.line_points()
            self.assertGreaterEqual(len(pts), 2)
            xs = [p[0] for p in pts]
            self.assertLess(min(xs), 30.0)
            self.assertGreater(max(xs), 370.0)
        path = result.avoided_paths[0]
        self.assertGreater(len(path.modified_points), 4)
        self.assertTrue(path.returns_to_guidance)
        self.assertLess(distance(path.modified_points[0], path.original_segment.start), 1.0)
        self.assertLess(distance(path.modified_points[-1], path.original_segment.end), 1.0)


class ObstacleGroupingTest(unittest.TestCase):
    def test_nearby_obstacles_become_one_corridor(self):
        machine = sprayer_boom(24.0)
        obs1 = obstacle_from_point((200.0, 120.0), obstacle_id="o1", safety_margin_m=0.50)
        obs2 = obstacle_from_point((201.5, 120.0), obstacle_id="o2", safety_margin_m=0.50)
        envelopes = merge_adjacent_envelopes(build_all_envelopes([obs1, obs2], machine), 2.0)
        self.assertEqual(len(envelopes), 1)

        project = field_project(
            spraying=PrecisionOperation(operation_id="spraying", machine=machine),
            obstacles=(obs1, obs2),
            avoidance=AvoidanceConfiguration(
                mode=AvoidanceMode.CONCENTRIC_RING,
                merge_adjacent_envelopes_m=2.0,
            ),
        )
        result = run_precision_lines(project)
        self.assertEqual(len(result.obstacle_envelopes), 1)
        self.assertGreater(len(result.avoided_paths), 0)
        for traffic_pass in result.spraying_passes:
            xs = [p[0] for p in traffic_pass.line_points()]
            self.assertLess(min(xs), 30.0)
            self.assertGreater(max(xs), 370.0)


class PlanterTipEnvelopeTest(unittest.TestCase):
    def test_planter_18m_tip_is_9m(self):
        planter = planter_18m()
        self.assertAlmostEqual(planter.operational_width_m, 18.0)
        self.assertAlmostEqual(planter.half_operational_width_m, 9.0)

        config = PlantingAvoidanceConfiguration()
        kin = kinematics_from_planter(planter)
        obs = obstacle_from_point(
            (200.0, 129.0),
            obstacle_radius_m=0.0,
            safety_margin_m=0.0,
            obstacle_id="tip",
        )
        region = build_planting_forbidden_region(obs, kin, config)
        self.assertAlmostEqual(
            region.implement_clearance_radius_m,
            9.0 + config.total_margin_m(),
            places=3,
        )

        project = field_project(
            planting=PrecisionOperation(operation_id="planting", machine=planter),
            obstacles=(obs,),
            planting_avoidance=config,
        )
        result = run_precision_lines(project)
        self.assertGreater(len(result.planting_passes), 0)
        if result.planting_rows:
            row_ids = [(row.pass_id, row.row_id) for row in result.planting_rows]
            self.assertEqual(len(row_ids), len(set(row_ids)))
            self.assertTrue(any(row.row_id >= 0 for row in result.planting_rows))
        self.assertGreater(len(result.planting_avoidance_results), 0)
        self.assertTrue(
            any(
                item.conflict_type == ConflictType.IMPLEMENT_EDGE
                for item in result.planting_avoidance_results
            )
        )


class TireTrackTest(unittest.TestCase):
    def test_offset_is_half_track_width(self):
        pts = ((0.0, 120.0), (100.0, 120.0))
        left = offset_polyline(pts, 1.55)
        right = offset_polyline(pts, -1.55)
        self.assertAlmostEqual(left[0][1], 121.55, places=2)
        self.assertAlmostEqual(right[0][1], 118.45, places=2)

    def test_two_tracks_per_pass_after_avoidance(self):
        machine = sprayer_boom(24.0)
        obs = obstacle_from_point((200.0, 120.0), safety_margin_m=0.50, obstacle_id="rtk")
        project = field_project(
            spraying=PrecisionOperation(operation_id="spraying", machine=machine),
            obstacles=(obs,),
        )
        result = run_precision_lines(project)
        self.assertGreater(len(result.spraying_passes), 0)
        self.assertGreaterEqual(len(result.tire_tracks), 2 * len(result.spraying_passes))
        sides = {track.side for track in result.tire_tracks}
        self.assertEqual(sides, {"left", "right"})
        hit_pass = next(
            p for p in result.spraying_passes if len(p.line_points()) > 2
        )
        tracks = generate_tire_tracks(
            [hit_pass],
            track_width_m=machine.track.track_width_m,
            tire_width_m=machine.track.tire_width_m,
        )
        self.assertEqual(len(tracks), 2)
        self.assertGreater(len(tracks[0].points), 2)


class HeadlandAvoidanceTest(unittest.TestCase):
    def test_spray_headland_centerline_is_deviated(self):
        machine = sprayer_boom(24.0)
        obs = obstacle_from_point((200.0, 108.0), safety_margin_m=0.50, obstacle_id="hl")
        project = field_project(
            spraying=PrecisionOperation(
                operation_id="spraying",
                machine=machine,
                headland=HeadlandLayout(pass_count=1, width_m=24.0, mode="parallel_ab"),
            ),
            obstacles=(obs,),
        )
        result = run_precision_lines(project)
        self.assertIsNotNone(result.boundary)
        self.assertGreater(len(result.boundary.headland_centerlines), 0)
        self.assertGreater(len(result.avoided_paths), 0)
        self.assertTrue(
            any(len(line.line_points()) > 2 for line in result.boundary.headland_centerlines)
            or any(path.operation_id == "spraying" for path in result.avoided_paths)
        )

    def test_planting_headland_centerline_is_deviated(self):
        planter = planter_18m()
        obs = obstacle_from_point((200.0, 111.0), safety_margin_m=0.0, obstacle_id="hlp")
        project = field_project(
            planting=PrecisionOperation(
                operation_id="planting",
                machine=planter,
                headland=HeadlandLayout(pass_count=1, width_m=18.0, mode="parallel_ab"),
            ),
            obstacles=(obs,),
        )
        result = run_precision_lines(project)
        self.assertIsNotNone(result.boundary)
        self.assertGreater(len(result.boundary.headland_centerlines), 0)
        self.assertGreater(
            len(result.avoided_paths) + len(result.planting_avoidance_results),
            0,
        )


if __name__ == "__main__":
    unittest.main()
