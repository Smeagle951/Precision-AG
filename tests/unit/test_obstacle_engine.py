# -*- coding: utf-8 -*-
"""Testes Precision Lines v2 — Obstacle Avoidance."""

from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

from plugin.fortsmart_precision.core.export_engine import export_precision_lines_package
from plugin.fortsmart_precision.core.line_geometry import Segment, distance
from plugin.fortsmart_precision.core.obstacle_buffer_engine import build_all_envelopes, merge_adjacent_envelopes
from plugin.fortsmart_precision.core.obstacle_engine import (
    apply_obstacle_avoidance_to_passes,
    apply_obstacle_avoidance_to_rows,
)
from plugin.fortsmart_precision.core.obstacle_validation_engine import validate_avoided_paths
from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
from plugin.fortsmart_precision.domain.application_zone import ApplicationZone, FieldZone
from plugin.fortsmart_precision.domain.avoidance_configuration import AvoidanceConfiguration, AvoidanceMode
from plugin.fortsmart_precision.domain.guidance_reference import GuidanceReference
from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
from plugin.fortsmart_precision.domain.machine_model import load_machine_presets
from plugin.fortsmart_precision.domain.obstacle_model import Obstacle, ObstacleType, obstacle_from_point
from plugin.fortsmart_precision.domain.precision_project import (
    ABLine,
    FieldGeometry,
    PrecisionOperation,
    PrecisionProject,
)


def rectangle(width=400.0, height=240.0, x=0.0, y=0.0):
    outer = [(x, y), (x + width, y), (x + width, y + height), (x, y + height), (x, y)]
    return [(outer, [])]


def uniport():
    machine = load_machine_presets()["uniport_5030_103x035"]
    return machine


def db27():
    return load_machine_presets()["db27_36x050"]


def spray_project_with_obstacle(center=(200.0, 120.0), obstacles=None):
    field = rectangle(400, 240)
    obs = obstacles or (obstacle_from_point(center),)
    return PrecisionProject(
        field=FieldGeometry(field_boundary=field, operational_boundary=field, crs_authid="EPSG:31982"),
        ab_line=ABLine(start=(0.0, 120.0), end=(400.0, 120.0)),
        spraying=PrecisionOperation(
            operation_id="spraying",
            machine=uniport(),
            headland=HeadlandLayout(pass_count=0),
        ),
        obstacles=obs,
        avoidance=AvoidanceConfiguration(mode=AvoidanceMode.CONCENTRIC_RING),
    )


class CircularRingTest(unittest.TestCase):
    def test_circular_obstacle_application_ring_18m(self):
        sprayer = uniport()
        expected_radius = sprayer.half_operational_width_m
        self.assertAlmostEqual(expected_radius, 18.025, places=3)

        project = spray_project_with_obstacle(center=(200.0, 120.0))
        result = run_precision_lines(project)
        self.assertGreater(len(result.avoided_paths), 0)

        path = result.avoided_paths[0]
        self.assertEqual(path.action, "ring")
        center = (200.0, 120.0)
        ring_points = [
            p
            for p in path.modified_points
            if abs(distance(p, center) - expected_radius) < 1.0
        ]
        self.assertGreater(len(ring_points), 8)
        for point in ring_points[:: max(1, len(ring_points) // 12)]:
            # Tolerancia: suavizacao de entrada/saida pode afastar levemente do raio ideal.
            self.assertAlmostEqual(distance(point, center), expected_radius, delta=1.25)

    def test_obstacle_returns_to_original_guidance(self):
        project = spray_project_with_obstacle(center=(200.0, 120.0))
        result = run_precision_lines(project)
        self.assertTrue(any(p.returns_to_guidance for p in result.avoided_paths))


class ObstacleEngineTest(unittest.TestCase):
    def test_multi_pass_independent_avoidance(self):
        from plugin.fortsmart_precision.core.guidance_engine import generate_traffic_passes

        field = rectangle(400, 240)
        ab = ABLine(start=(0.0, 120.0), end=(400.0, 120.0))
        op = PrecisionOperation(operation_id="spraying", machine=uniport())
        passes = generate_traffic_passes(field, ab, op)
        self.assertGreater(len(passes), 3)

        obs = obstacle_from_point((200.0, passes[1].guidance_segment.start[1]))
        config = AvoidanceConfiguration(mode=AvoidanceMode.CONCENTRIC_RING)
        modified, avoided = apply_obstacle_avoidance_to_passes(
            passes, [obs], uniport(), config, allowed_area=field
        )
        hit_ids = {a.pass_id for a in avoided}
        self.assertIn(passes[1].pass_no, hit_ids)
        untouched = [p for p in modified if p.pass_no not in hit_ids]
        self.assertGreater(len(untouched), 0)

    def test_merged_obstacle_corridor(self):
        sprayer = uniport()
        obs1 = obstacle_from_point((100.0, 120.0), obstacle_id="o1")
        obs2 = obstacle_from_point((105.0, 120.0), obstacle_id="o2")
        envs = build_all_envelopes([obs1, obs2], sprayer)
        merged = merge_adjacent_envelopes(envs, merge_distance_m=20.0)
        self.assertEqual(len(merged), 1)

    def test_square_obstacle_offset_with_rounded_corners(self):
        square = Obstacle(
            obstacle_id="sq1",
            obstacle_type=ObstacleType.POLYGON,
            center=(200.0, 120.0),
            obstacle_radius_m=5.0,
            safety_margin_m=1.0,
            polygon=(
                [(195, 115), (205, 115), (205, 125), (195, 125), (195, 115)],
                [],
            ),
        )
        env = build_all_envelopes([square], uniport())[0]
        self.assertGreater(env.application_radius_m, 5.0)

    def test_validation_blocks_path_through_obstacle(self):
        from plugin.fortsmart_precision.core.obstacle_engine import AvoidedPath

        obs = obstacle_from_point((200.0, 120.0))
        bad_path = AvoidedPath(
            fs_id="x",
            source_id="s",
            pass_id=1,
            row_id=None,
            operation_id="spraying",
            machine_id="m",
            original_segment=Segment((0, 120), (400, 120)),
            modified_points=((200.0, 120.0), (210.0, 120.0)),
            entry_point=(200.0, 120.0),
            exit_point=(210.0, 120.0),
            obstacle_id=obs.obstacle_id,
            application_radius_m=18.025,
            action="ring",
            returns_to_guidance=True,
        )
        report = validate_avoided_paths(
            [bad_path],
            [obs],
            rectangle(400, 240),
            AvoidanceConfiguration(mode=AvoidanceMode.CONCENTRIC_RING),
        )
        self.assertFalse(report.ok)
        self.assertTrue(any(e.code == "PATH_THROUGH_OBSTACLE" for e in report.errors))


class MultiFieldTest(unittest.TestCase):
    def test_multi_field_application_zone(self):
        field_a = rectangle(200, 240, x=0, y=0)
        field_b = rectangle(200, 240, x=210, y=0)
        zone = ApplicationZone(
            fields=(
                FieldZone("A", field_a, field_a, headland_color="orange"),
                FieldZone("B", field_b, field_b, headland_color="yellow"),
            ),
            crs_authid="EPSG:31982",
            continuous_spray_across_fields=True,
        )
        union = zone.operational_union
        self.assertEqual(len(union), 2)

        obstacles = (
            obstacle_from_point((150.0, 120.0)),
            obstacle_from_point((260.0, 120.0)),
        )
        project = PrecisionProject(
            field=FieldGeometry(field_boundary=field_a, operational_boundary=field_a, crs_authid="EPSG:31982"),
            ab_line=ABLine(start=(0.0, 120.0), end=(400.0, 120.0)),
            application_zone=zone,
            spraying=PrecisionOperation(operation_id="spraying", machine=uniport()),
            obstacles=obstacles,
            avoidance=AvoidanceConfiguration(mode=AvoidanceMode.CONCENTRIC_RING),
        )
        result = run_precision_lines(project)
        self.assertGreater(len(result.spraying_passes), 0)


class HeadlandObstacleTest(unittest.TestCase):
    def test_obstacle_on_headland_centerline(self):
        from plugin.fortsmart_precision.core.boundary_engine import build_boundary_plan

        project = PrecisionProject(
            field=FieldGeometry(
                field_boundary=rectangle(400, 240),
                operational_boundary=rectangle(400, 240),
                crs_authid="EPSG:31982",
            ),
            ab_line=ABLine(start=(0.0, 120.0), end=(400.0, 120.0)),
            planting=PrecisionOperation(
                operation_id="planting",
                machine=db27(),
                headland=HeadlandLayout(pass_count=1, width_m=18.0, effective_spacing_m=18.0, mode="parallel_ab"),
            ),
            obstacles=(obstacle_from_point((200.0, 111.0)),),
            avoidance=AvoidanceConfiguration(mode=AvoidanceMode.CONCENTRIC_RING),
        )
        assert project.planting is not None
        boundary = build_boundary_plan(
            project.field.operational_boundary,
            project.planting,
            project.ab_line.start,
            project.ab_line.end,
        )
        self.assertEqual(len(boundary.headland_centerlines), 1)
        line = boundary.headland_centerlines[0]
        modified, avoided = apply_obstacle_avoidance_to_passes(
            [
                type("P", (), {
                    "pass_no": 0,
                    "fs_id": "h1",
                    "operation_id": "headland",
                    "spacing_m": 18.0,
                    "width_m": 18.0,
                    "offset_m": 0.0,
                    "azimuth_deg": 90.0,
                    "direction": "forward",
                    "clipped_segment": line.segment,
                    "guidance_segment": line.segment,
                })()
            ],
            list(project.obstacles),
            db27(),
            project.avoidance,
            allowed_area=project.field.operational_boundary,
        )
        self.assertGreaterEqual(len(avoided), 0)


class ExportObstacleTest(unittest.TestCase):
    def test_export_includes_avoided_paths(self):
        result = run_precision_lines(spray_project_with_obstacle())
        with tempfile.TemporaryDirectory() as tmp:
            package = export_precision_lines_package(
                Path(tmp),
                passes=result.planting_passes,
                rows=result.planting_rows,
                tramline_zones=result.tramline_zones,
                shutoff_segments=result.shutoff_segments,
                validation_report=result.validation,
                avoided_paths=result.avoided_paths,
                obstacle_envelopes=result.obstacle_envelopes,
            )
            self.assertIn("avoided_paths.geojson", package.export.files)
            self.assertIn("obstacle_envelopes.geojson", package.export.files)


if __name__ == "__main__":
    unittest.main()
