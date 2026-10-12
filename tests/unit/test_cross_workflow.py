# -*- coding: utf-8 -*-
"""Fluxo de cruzamento e contorno de desvio de plantio."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.cross_workflow import (
    ensure_tire_tracks,
    ensure_virtual_planting_rows,
    passes_to_planting_rows,
    resolve_planting_rows_for_cross,
    run_cross_shutoff,
    session_ready_for_cross,
)
from plugin.fortsmart_precision.core.guidance_engine import TrafficPass
from plugin.fortsmart_precision.core.line_geometry import Segment, distance, polyline_length
from plugin.fortsmart_precision.core.planting_obstacle_engine import apply_planting_avoidance_to_passes
from plugin.fortsmart_precision.core.precision_lines_engine import PrecisionLinesResult
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, PlanterMachine, SprayerMachine
from plugin.fortsmart_precision.domain.obstacle_model import obstacle_from_polygon
from plugin.fortsmart_precision.domain.planting_avoidance_configuration import (
    PlantingAvoidanceConfiguration,
    PlantingAvoidanceStrategy,
)
from plugin.fortsmart_precision.domain.planting_kinematics import PlantingKinematics
from plugin.fortsmart_precision.domain.sprayer_traffic_configuration import (
    SprayerTrafficConfiguration,
    TrafficMeasureResolution,
)
from plugin.fortsmart_precision.domain.precision_project import FieldGeometry, PrecisionProject


def _planter():
    return PlanterMachine(
        machine_id="p",
        name="18m",
        row_count=36,
        row_spacing_m=0.5,
        track=MachineTrack(track_width_m=1.8, tire_width_m=0.3),
    )


def _sprayer():
    return SprayerMachine(
        machine_id="s",
        name="36m",
        nozzle_count=72,
        nozzle_spacing_m=0.5,
        boom_width_m=36.0,
        track=MachineTrack(track_width_m=3.0, tire_width_m=0.37),
    )


def _pass_line(y=120.0):
    return TrafficPass(
        pass_no=0,
        fs_id="p1",
        operation_id="planting",
        spacing_m=18.0,
        width_m=18.0,
        offset_m=0.0,
        azimuth_deg=0.0,
        direction="forward",
        clipped_segment=Segment((0.0, y), (400.0, y)),
        guidance_segment=Segment((0.0, y), (400.0, y)),
    )


class CrossWorkflowTest(unittest.TestCase):
    def test_session_ready_needs_both_operations(self):
        planter = _planter()
        spray = _sprayer()
        stub = PrecisionLinesResult(
            project=PrecisionProject(
                field=FieldGeometry(field_boundary=[], operational_boundary=[], crs_authid="EPSG:31981"),
                ab_line=__import__(
                    "plugin.fortsmart_precision.domain.precision_project", fromlist=["ABLine"]
                ).ABLine(start=(0, 0), end=(1, 0)),
            ),
            boundary=None,
            planting_passes=[_pass_line()],
            planting_rows=[],
            spraying_passes=[],
            tramline_zones=[],
            shutoff_segments=[],
            shutoff_table=[],
        )
        self.assertFalse(session_ready_for_cross(stub))
        stub2 = PrecisionLinesResult(
            project=stub.project,
            boundary=None,
            planting_passes=[_pass_line()],
            planting_rows=passes_to_planting_rows([_pass_line()], planter),
            spraying_passes=[
                TrafficPass(
                    pass_no=0,
                    fs_id="s1",
                    operation_id="spraying",
                    spacing_m=36.0,
                    width_m=36.0,
                    offset_m=0.0,
                    azimuth_deg=0.0,
                    direction="forward",
                    clipped_segment=Segment((0, 0), (400, 0)),
                    guidance_segment=Segment((0, 0), (400, 0)),
                )
            ],
            tramline_zones=[],
            shutoff_segments=[],
            shutoff_table=[],
        )
        self.assertTrue(session_ready_for_cross(stub2))

    def test_ensure_tire_tracks_from_spray_passes(self):
        spray_pass = TrafficPass(
            pass_no=0,
            fs_id="s1",
            operation_id="spraying",
            spacing_m=36.0,
            width_m=36.0,
            offset_m=0.0,
            azimuth_deg=0.0,
            direction="forward",
            clipped_segment=Segment((0, 0), (400, 0)),
            guidance_segment=Segment((0, 0), (400, 0)),
        )
        tracks = ensure_tire_tracks([spray_pass], _sprayer())
        self.assertEqual(len(tracks), 2)

    def test_resolve_prefers_session_virtual_rows(self):
        planter = _planter()
        kin = PlantingKinematics(
            operational_width_m=18.0,
            track_width_m=1.8,
            hitch_distance_m=1.0,
            minimum_turn_radius_m=5.0,
            row_count=36,
            row_spacing_m=0.5,
        )
        ring = [
            (-50.0, 100.0),
            (450.0, 100.0),
            (450.0, 140.0),
            (-50.0, 140.0),
            (-50.0, 100.0),
        ]
        rows = ensure_virtual_planting_rows([_pass_line()], planter, kin, work_area=[(ring, [])])
        self.assertGreaterEqual(len(rows), planter.row_count)
        out, src = resolve_planting_rows_for_cross(
            session_rows=rows,
            session_passes=None,
            imported_rows=[],
            planter=planter,
        )
        self.assertGreaterEqual(len(out), planter.row_count)
        self.assertIn("sessao", src)

    def test_resolve_generates_virtual_from_passes_only(self):
        planter = _planter()
        kin = PlantingKinematics(
            operational_width_m=18.0,
            track_width_m=1.8,
            hitch_distance_m=1.0,
            minimum_turn_radius_m=5.0,
            row_count=36,
            row_spacing_m=0.5,
        )
        ring = [
            (-50.0, 100.0),
            (450.0, 100.0),
            (450.0, 140.0),
            (-50.0, 140.0),
            (-50.0, 100.0),
        ]
        out, src = resolve_planting_rows_for_cross(
            session_rows=None,
            session_passes=[_pass_line()],
            imported_rows=[],
            planter=planter,
            kinematics=kin,
            work_area=[(ring, [])],
        )
        self.assertGreaterEqual(len(out), planter.row_count)
        self.assertIn("virtuais geradas", src)

    def test_run_cross_shutoff_off_on_tire_tracks(self):
        planter = _planter()
        traffic = SprayerTrafficConfiguration(
            boom_width_m=36.0,
            tire_width_m=0.37,
            inner_clearance_m=2.70,
            outer_width_m=3.43,
            resolution=TrafficMeasureResolution.USE_OUTER,
        )
        sprayer = SprayerMachine(
            machine_id="s",
            name="36m",
            nozzle_count=72,
            nozzle_spacing_m=0.5,
            boom_width_m=36.0,
            track=MachineTrack(track_width_m=3.0, tire_width_m=0.37),
            traffic=traffic,
        )
        kin = PlantingKinematics(
            operational_width_m=18.0,
            track_width_m=1.8,
            hitch_distance_m=1.0,
            minimum_turn_radius_m=5.0,
            row_count=36,
            row_spacing_m=0.5,
        )
        ring = [
            (-50.0, -10.0),
            (450.0, -10.0),
            (450.0, 10.0),
            (-50.0, 10.0),
            (-50.0, -10.0),
        ]
        plant_rows = ensure_virtual_planting_rows(
            [_pass_line(y=0.0)], planter, kin, work_area=[(ring, [])]
        )
        spray_pass = TrafficPass(
            pass_no=0,
            fs_id="s1",
            operation_id="spraying",
            spacing_m=36.0,
            width_m=36.0,
            offset_m=0.0,
            azimuth_deg=0.0,
            direction="forward",
            clipped_segment=Segment((0, 0), (400, 0)),
            guidance_segment=Segment((0, 0), (400, 0)),
            path_points=((0.0, 0.0), (400.0, 0.0)),
        )
        cross = run_cross_shutoff(
            planting_rows=plant_rows,
            spraying_passes=[spray_pass],
            planter=planter,
            sprayer=sprayer,
            plant_source="teste",
            shutoff_on_tramlines=True,
            clip_area=[(ring, [])],
        )
        self.assertGreater(len(cross.shutoff_segments), 0)
        self.assertEqual(len(cross.tire_tracks), 2)
        self.assertGreaterEqual(len(plant_rows), planter.row_count)


class ContourAvoidanceTest(unittest.TestCase):
    def test_contour_produces_continuous_tractor_polyline(self):
        kin = PlantingKinematics(
            operational_width_m=18.0,
            track_width_m=1.8,
            hitch_distance_m=1.0,
            minimum_turn_radius_m=5.0,
            row_count=36,
            row_spacing_m=0.5,
        )
        planter = _planter()
        # Poligono no meio da passada.
        poly = (
            [
                (190.0, 115.0),
                (210.0, 115.0),
                (210.0, 125.0),
                (190.0, 125.0),
                (190.0, 115.0),
            ],
            [],
        )
        obs = obstacle_from_polygon(poly, name="area")
        config = PlantingAvoidanceConfiguration(
            strategy=PlantingAvoidanceStrategy.CONTOUR,
            inner_margin_m=0.5,
            outer_margin_m=0.5,
        )
        passes, results, _avoided = apply_planting_avoidance_to_passes(
            [_pass_line()],
            [obs],
            kin,
            config,
            planter,
        )
        self.assertEqual(len(results), 1)
        path = list(results[0].avoidance_path)
        self.assertGreaterEqual(len(path), 8)
        self.assertGreater(polyline_length(path), 400.0)
        self.assertLess(distance(path[-1], (400.0, 120.0)), 2.0)
        self.assertGreater(len(passes[0].path_points), 5)


if __name__ == "__main__":
    unittest.main()
