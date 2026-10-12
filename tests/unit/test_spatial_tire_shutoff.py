# -*- coding: utf-8 -*-
"""Testes: faixa de rastro ao longo do path e shutoff espacial ROW × pneu."""

from __future__ import annotations

import math
import unittest

from plugin.fortsmart_precision.core.guidance_engine import TrafficPass
from plugin.fortsmart_precision.core.line_geometry import (
    Segment,
    build_polyline_strip_polygon,
    circle_arc_polyline,
    point_in_multipolygon,
    polyline_length,
)
from plugin.fortsmart_precision.core.row_engine import PlantingRow
from plugin.fortsmart_precision.core.shutoff_engine import apply_row_shutoff
from plugin.fortsmart_precision.core.sprayer_traffic_engine import calculate_planting_shutoff
from plugin.fortsmart_precision.core.tire_track_engine import (
    generate_tire_track_polygons,
    generate_tire_tracks,
    generate_tire_tracks_from_traffic,
    tire_tracks_multipolygon,
)
from plugin.fortsmart_precision.core.tramline_engine import generate_tramline_zones_from_tire_tracks
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, PlanterMachine
from plugin.fortsmart_precision.domain.sprayer_traffic_configuration import (
    SprayerTrafficConfiguration,
    TrafficMeasureResolution,
)


def _jacto_traffic(
    *,
    resolution: TrafficMeasureResolution = TrafficMeasureResolution.USE_OUTER,
) -> SprayerTrafficConfiguration:
    return SprayerTrafficConfiguration(
        boom_width_m=36.0,
        tire_width_m=0.37,
        inner_clearance_m=2.70,
        outer_width_m=3.43,
        resolution=resolution,
    )


def _pass_with_arc() -> TrafficPass:
    """Passada reta + arco semicircular (desvio) + reta."""
    straight1 = [(0.0, 0.0), (50.0, 0.0)]
    arc = circle_arc_polyline(
        (50.0, 20.0),
        20.0,
        start_angle_rad=-math.pi / 2,
        sweep_rad=math.pi,
        segments=24,
    )
    # arc goes from (50,0) around to (50,40) via (70,20)
    straight2 = [(50.0, 40.0), (100.0, 40.0)]
    points = tuple(straight1 + arc[1:] + straight2[1:])
    return TrafficPass(
        pass_no=1,
        fs_id="arc1",
        operation_id="spraying",
        spacing_m=36.0,
        width_m=36.0,
        offset_m=0.0,
        azimuth_deg=0.0,
        direction="forward",
        clipped_segment=Segment(points[0], points[-1]),
        guidance_segment=Segment(points[0], points[-1]),
        path_points=points,
    )


class PolylineStripPolygonTest(unittest.TestCase):
    def test_straight_strip_covers_tire_width(self):
        poly = build_polyline_strip_polygon([(0.0, 0.0), (100.0, 0.0)], half_width_m=0.185)
        self.assertIsNotNone(poly)
        mp = [poly]
        self.assertTrue(point_in_multipolygon((50.0, 0.0), mp))
        self.assertTrue(point_in_multipolygon((50.0, 0.18), mp))
        self.assertFalse(point_in_multipolygon((50.0, 0.5), mp))

    def test_arc_strip_is_not_chord_bbox(self):
        arc = circle_arc_polyline((0.0, 0.0), 30.0, 0.0, math.pi / 2, segments=20)
        poly = build_polyline_strip_polygon(arc, half_width_m=0.2)
        self.assertIsNotNone(poly)
        # Ponto no meio do arco (~45°) deve estar na faixa.
        mid = arc[len(arc) // 2]
        self.assertTrue(point_in_multipolygon(mid, [poly]))
        # Centro do arco (corda) nao deve confundir: (30,0) esta no inicio, ok;
        # ponto dentro do setor mas longe do arco nao deve estar na faixa.
        self.assertFalse(point_in_multipolygon((10.0, 10.0), [poly]))


class TireTrackPolygonTest(unittest.TestCase):
    def test_tracks_from_traffic_produce_polygons(self):
        traffic = _jacto_traffic()
        tracks = generate_tire_tracks_from_traffic([_pass_with_arc()], traffic)
        self.assertEqual(len(tracks), 2)
        polys = generate_tire_track_polygons(tracks)
        self.assertEqual(len(polys), 2)
        for track, poly in polys:
            self.assertGreaterEqual(len(track.points), 10)
            self.assertIsNotNone(poly)

    def test_tramlines_from_tire_tracks(self):
        traffic = _jacto_traffic()
        tracks = generate_tire_tracks_from_traffic([_pass_with_arc()], traffic)
        zones = generate_tramline_zones_from_tire_tracks(
            tracks,
            machine_id="spr",
            operation_id="spraying",
        )
        self.assertEqual(len(zones), 2)
        sides = {z.side for z in zones}
        self.assertEqual(sides, {"left", "right"})
        self.assertEqual(zones[0].source, "tire_track")


class SpatialShutoffArcTest(unittest.TestCase):
    def test_crossing_angle_is_derived_from_geometry(self):
        traffic = SprayerTrafficConfiguration(
            boom_width_m=36.0,
            tire_width_m=0.38,
            inner_clearance_m=2.70,
            outer_width_m=3.46,
        )
        spray_pass = TrafficPass(
            pass_no=1,
            fs_id="spray-angle",
            operation_id="spraying",
            spacing_m=36.0,
            width_m=36.0,
            offset_m=0.0,
            azimuth_deg=90.0,
            direction="forward",
            clipped_segment=Segment((0.0, 0.0), (200.0, 0.0)),
            guidance_segment=Segment((0.0, 0.0), (200.0, 0.0)),
        )
        tracks = generate_tire_tracks_from_traffic([spray_pass], traffic)
        right_track = next(item for item in tracks if item.side == "right")
        crossing_center = (100.0, right_track.points[0][1])

        for angle_deg in (5.0, 10.0, 15.0):
            with self.subTest(angle_deg=angle_deg):
                angle = math.radians(angle_deg)
                direction = (math.cos(angle), math.sin(angle))
                start = (
                    crossing_center[0] - 100.0 * direction[0],
                    crossing_center[1] - 100.0 * direction[1],
                )
                end = (
                    crossing_center[0] + 100.0 * direction[0],
                    crossing_center[1] + 100.0 * direction[1],
                )
                row = PlantingRow(
                    fs_id=f"row-{int(angle_deg)}",
                    row_id=int(angle_deg),
                    pass_id=1,
                    machine_id="planter",
                    spacing_m=0.45,
                    direction="forward",
                    offset_m=0.0,
                    azimuth_deg=angle_deg,
                    segment=Segment(start, end),
                    path_points=(start, end),
                )
                segments = apply_row_shutoff([row], tire_tracks=[right_track])
                off = [item for item in segments if item.shutoff_state == "off"]
                measured = sum(polyline_length(list(item.line_points())) for item in off)
                expected = traffic.exclusion_width_m / math.sin(angle)
                self.assertAlmostEqual(measured, expected, delta=0.08)
                self.assertTrue(all(item.source_row_id == row.fs_id for item in segments))
                self.assertTrue(
                    all(item.station_end_m >= item.station_start_m for item in segments)
                )

    def test_planting_row_crossing_tire_strip_creates_off_segment(self):
        """Linha de plantio cruza o rastro direito → pelo menos um OFF com comprimento > 0."""
        traffic = _jacto_traffic()
        # Trajetoria do pulverizador ao longo de Y=0 (eixo X).
        spray_pass = TrafficPass(
            pass_no=1,
            fs_id="s1",
            operation_id="spraying",
            spacing_m=36.0,
            width_m=36.0,
            offset_m=0.0,
            azimuth_deg=0.0,
            direction="forward",
            clipped_segment=Segment((0.0, 0.0), (100.0, 0.0)),
            guidance_segment=Segment((0.0, 0.0), (100.0, 0.0)),
            path_points=((0.0, 0.0), (100.0, 0.0)),
        )
        tracks = generate_tire_tracks_from_traffic([spray_pass], traffic)
        # Linha de plantio perpendicular cruzando o pneu direito (~+1.53 m).
        right_center = traffic.calculate_tire_zones()[1].center_m
        row = PlantingRow(
            fs_id="r1",
            row_id=21,
            pass_id=1,
            machine_id="planter",
            spacing_m=0.45,
            direction="forward",
            offset_m=right_center,
            azimuth_deg=90.0,
            segment=Segment((50.0, -20.0), (50.0, 20.0)),
            path_points=((50.0, -20.0), (50.0, 20.0)),
        )
        segments = apply_row_shutoff([row], tire_tracks=tracks)
        off = [s for s in segments if s.shutoff_state == "off"]
        self.assertGreaterEqual(len(off), 1)
        self.assertGreater(sum(s.segment.length for s in off), 0.2)
        # Trechos fora do pneu permanecem ON.
        on = [s for s in segments if s.shutoff_state == "on"]
        self.assertGreaterEqual(len(on), 1)

    def test_row_in_center_gap_stays_on(self):
        traffic = _jacto_traffic()
        spray_pass = TrafficPass(
            pass_no=1,
            fs_id="s1",
            operation_id="spraying",
            spacing_m=36.0,
            width_m=36.0,
            offset_m=0.0,
            azimuth_deg=0.0,
            direction="forward",
            clipped_segment=Segment((0.0, 0.0), (100.0, 0.0)),
            guidance_segment=Segment((0.0, 0.0), (100.0, 0.0)),
            path_points=((0.0, 0.0), (100.0, 0.0)),
        )
        tracks = generate_tire_tracks_from_traffic([spray_pass], traffic)
        # Linha no eixo central (Y=0), paralela ao pulverizador — so no vao livre.
        row = PlantingRow(
            fs_id="r0",
            row_id=18,
            pass_id=1,
            machine_id="planter",
            spacing_m=0.45,
            direction="forward",
            offset_m=0.0,
            azimuth_deg=0.0,
            segment=Segment((10.0, 0.0), (90.0, 0.0)),
            path_points=((10.0, 0.0), (90.0, 0.0)),
        )
        segments = apply_row_shutoff([row], tire_tracks=tracks)
        off = [s for s in segments if s.shutoff_state == "off"]
        self.assertEqual(len(off), 0)
        self.assertTrue(all(s.shutoff_state == "on" for s in segments))

    def test_arc_path_shutoff_has_positive_off_length(self):
        traffic = _jacto_traffic()
        spray = _pass_with_arc()
        tracks = generate_tire_tracks_from_traffic([spray], traffic)
        # Linha vertical cruzando o arco no X=70 (ponto mais a direita do arco).
        row = PlantingRow(
            fs_id="rcross",
            row_id=1,
            pass_id=1,
            machine_id="planter",
            spacing_m=0.45,
            direction="forward",
            offset_m=0.0,
            azimuth_deg=90.0,
            segment=Segment((70.0, 0.0), (70.0, 40.0)),
            path_points=((70.0, 0.0), (70.0, 40.0)),
        )
        segments = apply_row_shutoff([row], tire_tracks=tracks)
        off = [s for s in segments if s.shutoff_state == "off"]
        self.assertGreaterEqual(len(off), 1)
        self.assertGreater(sum(polyline_length(list(s.line_points())) for s in off), 0.1)


class OffsetClassificationRegressionTest(unittest.TestCase):
    def test_planter_36x045_desliga_at_1575(self):
        traffic = _jacto_traffic()
        planter = PlanterMachine(
            machine_id="p36",
            name="36x0,45",
            row_count=36,
            row_spacing_m=0.45,
            track=MachineTrack(track_width_m=1.8, tire_width_m=0.3),
        )
        rows = calculate_planting_shutoff(planter, traffic)
        by_off = {round(r.offset_m, 3): r for r in rows}
        self.assertEqual(by_off[1.575].action, "DESLIGA")
        self.assertEqual(by_off[-1.575].action, "DESLIGA")
        self.assertEqual(by_off[1.125].action, "LIGA")


if __name__ == "__main__":
    unittest.main()
