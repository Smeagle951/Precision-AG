# -*- coding: utf-8 -*-
"""WORK_OFF por intersecao exata linha x faixa do pneu (independente da amostragem)."""

from __future__ import annotations

import math
import unittest
from types import SimpleNamespace
from unittest import mock

from plugin.fortsmart_precision.core import shutoff_engine
from plugin.fortsmart_precision.core.line_geometry import Segment
from plugin.fortsmart_precision.core.operational_generation import build_operational_generation
from plugin.fortsmart_precision.core.row_engine import PlantingRow
from plugin.fortsmart_precision.core.shutoff_engine import apply_row_shutoff
from plugin.fortsmart_precision.core.tire_track_engine import TireTrack
from plugin.fortsmart_precision.domain.operational_contract import CrossSourceMode

WIDTH = 0.60  # pneu 0,40 + margem 0,10 por lado
TOLERANCE = 0.01


def row(points, fs_id="ROW_1", row_id=1) -> PlantingRow:
    points = tuple((float(x), float(y)) for x, y in points)
    return PlantingRow(
        fs_id=fs_id, row_id=row_id, pass_id=1, machine_id="PLANTADEIRA", spacing_m=0.5,
        direction="N", offset_m=0.0, azimuth_deg=0.0,
        segment=Segment(points[0], points[-1]), path_points=points if len(points) > 2 else (),
    )


def tire(points, side="left", track_id=None, width=WIDTH) -> TireTrack:
    return TireTrack(
        pass_id=1, side=side, offset_m=-1.0 if side == "left" else 1.0, tire_width_m=width,
        track_width_m=2.0, points=tuple((float(x), float(y)) for x, y in points),
        track_id=track_id or f"TT_1_{side.upper()}", source_feature_id="SP1",
        physical_tire_width_m=0.40, safety_margin_m=0.10,
    )


def off_intervals(segments, fs_id="ROW_1"):
    return sorted(
        (item.station_start_m, item.station_end_m)
        for item in segments
        if item.shutoff_state == "off" and item.source_row_id == fs_id
    )


def oracle(row_points, tracks, step=0.001):
    """Referencia por forca bruta: distancia ao eixo <= meia largura, a cada 1 mm."""
    from shapely.geometry import LineString, Point

    line = LineString(row_points)
    axes = [(LineString(t.points), t.tire_width_m / 2.0) for t in tracks]
    count = int(line.length / step)
    intervals, start = [], None
    for index in range(count + 1):
        s = min(line.length, index * step)
        p = line.interpolate(s)
        inside = any(axis.distance(Point(p)) <= half for axis, half in axes)
        if inside and start is None:
            start = s
        if not inside and start is not None:
            intervals.append((start, s - step))
            start = None
    if start is not None:
        intervals.append((start, line.length))
    return [item for item in intervals if item[1] - item[0] > 2 * step]


def arc(cx, cy, radius, a0, a1, step=2):
    return [(cx + radius * math.cos(math.radians(a)), cy + radius * math.sin(math.radians(a)))
            for a in range(a0, a1 + 1, step)]


class ExactTireIntervalTests(unittest.TestCase):
    def assert_intervals(self, actual, expected, tolerance=TOLERANCE):
        self.assertEqual(len(actual), len(expected), f"{actual} != {expected}")
        for (a0, a1), (e0, e1) in zip(actual, expected):
            self.assertAlmostEqual(a0, e0, delta=tolerance)
            self.assertAlmostEqual(a1, e1, delta=tolerance)

    def test_straight_tires_2m_both_detected(self):
        tracks = [tire([(20, 40), (180, 40)], "left"), tire([(20, 42), (180, 42)], "right")]
        segments = apply_row_shutoff([row([(50, 5), (50, 95)])], [], tire_tracks=tracks)
        self.assert_intervals(off_intervals(segments), [(34.7, 35.3), (36.7, 37.3)])

    def test_straight_tires_4m_both_detected(self):
        tracks = [tire([(20, 40), (180, 40)], "left"), tire([(20, 44), (180, 44)], "right")]
        segments = apply_row_shutoff([row([(50, 5), (50, 95)])], [], tire_tracks=tracks)
        self.assert_intervals(off_intervals(segments), [(34.7, 35.3), (38.7, 39.3)])

    def test_curved_tires_match_oracle(self):
        for spacing in (2.0, 4.0):
            tracks = [
                tire(arc(100, -20, 70, 50, 130), "left"),
                tire(arc(100, -20, 70 + spacing, 50, 130), "right"),
            ]
            for x in (60.0, 85.0, 100.0, 123.0):
                with self.subTest(spacing=spacing, x=x):
                    points = [(x, 5), (x, 95)]
                    segments = apply_row_shutoff([row(points)], [], tire_tracks=tracks)
                    expected = oracle(points, tracks)
                    self.assertEqual(len(expected), 2)
                    self.assert_intervals(off_intervals(segments), expected)

    def test_short_intersection_below_sample_step(self):
        track = tire([(50, 60), (50, 61.2)], "left")
        segments = apply_row_shutoff([row([(50, 5), (50, 95)])], [], tire_tracks=[track])
        self.assert_intervals(off_intervals(segments), [(54.7, 56.5)])
        narrow = tire([(20, 41.3), (180, 41.3)], "right", width=0.10)
        segments = apply_row_shutoff([row([(50, 5), (50, 95)])], [], tire_tracks=[narrow])
        self.assert_intervals(off_intervals(segments), [(36.25, 36.35)])

    def test_row_tangent_to_envelope_has_no_off(self):
        track = tire([(20, 40), (49.7, 40)], "left")
        segments = apply_row_shutoff([row([(50, 5), (50, 95)])], [], tire_tracks=[track])
        self.assertEqual(off_intervals(segments), [])
        inside = apply_row_shutoff([row([(49.99, 5), (49.99, 95)])], [], tire_tracks=[track])
        self.assertEqual(len(off_intervals(inside)), 1)

    def test_row_without_crossing_stays_on(self):
        track = tire([(20, 40), (180, 40)], "left")
        segments = apply_row_shutoff([row([(10, 50), (10, 95)])], [], tire_tracks=[track])
        self.assertEqual(off_intervals(segments), [])
        self.assertEqual([item.shutoff_state for item in segments], ["on"])

    def test_row_crossing_only_left_or_only_right(self):
        tracks = [tire([(20, 40), (180, 40)], "left"), tire([(20, 42), (180, 42)], "right")]
        only_left = apply_row_shutoff([row([(50, 5), (50, 41)])], [], tire_tracks=tracks)
        self.assert_intervals(off_intervals(only_left), [(34.7, 35.3)])
        only_right = apply_row_shutoff([row([(50, 41), (50, 95)])], [], tire_tracks=tracks)
        self.assert_intervals(off_intervals(only_right), [(0.7, 1.3)])

    def test_same_tire_crossed_twice_by_curve(self):
        track = tire(arc(50, 60, 15, 180, 360), "left")
        points = [(10, 55), (90, 55)]
        segments = apply_row_shutoff([row(points)], [], tire_tracks=[track])
        expected = oracle(points, [track])
        self.assertEqual(len(expected), 2)
        self.assert_intervals(off_intervals(segments), expected)

    def test_multisegment_row(self):
        tracks = [tire([(20, 40), (180, 40)], "left"), tire([(20, 42), (180, 42)], "right")]
        points = [(30, 5), (40, 60), (55, 20), (70, 90)]
        segments = apply_row_shutoff([row(points)], [], tire_tracks=tracks)
        expected = oracle(points, tracks)
        self.assertEqual(len(expected), 6)
        self.assert_intervals(off_intervals(segments), expected)

    def test_stations_ordered_and_source_row_preserved(self):
        tracks = [tire([(20, 40), (180, 40)], "left"), tire([(20, 42), (180, 42)], "right")]
        rows = [row([(x, 5), (x, 95)], fs_id=f"ROW_{x}", row_id=x) for x in (30, 60, 90)]
        segments = apply_row_shutoff(rows, [], tire_tracks=tracks)
        off = [item for item in segments if item.shutoff_state == "off"]
        self.assertEqual(len(off), 6)
        for item in off:
            self.assertLess(item.station_start_m, item.station_end_m)
            self.assertEqual(item.source_row_id, f"ROW_{item.row_id}")
            length = sum(math.dist(a, b) for a, b in zip(item.line_points(), item.line_points()[1:]))
            self.assertAlmostEqual(length, item.station_end_m - item.station_start_m, places=6)
            self.assertEqual(len(set(item.line_points())), len(item.line_points()))

    def test_tire_track_id_preserved_in_generation(self):
        tracks = [tire([(20, 40), (180, 40)], "left"), tire([(20, 42), (180, 42)], "right")]
        rows = [row([(x, 5), (x, 95)], fs_id=f"ROW_{x}", row_id=x) for x in (30, 60)]
        off = [item for item in apply_row_shutoff(rows, [], tire_tracks=tracks) if item.shutoff_state == "off"]
        cross = SimpleNamespace(
            planting_rows=rows,
            spraying_passes=[SimpleNamespace(pass_no=1, fs_id="SP1", line_points=lambda: ((20, 41), (180, 41)))],
            tire_tracks=tracks,
            tire_shutoff_segments=off,
        )
        sprayer = SimpleNamespace(name="PULVERIZADOR TESTE", to_dict=lambda: {"name": "PULVERIZADOR TESTE"})
        generation = build_operational_generation(
            cross=cross, field_id="TL-01", field_name="TL-01", source_crs="EPSG:32721",
            working_crs="EPSG:32721", source_mode=CrossSourceMode.EXISTING_PASSES, sprayer=sprayer,
            planting_layer="linhas", spray_layer="pulverizacao",
        )
        by_station = {}
        for segment in generation.segments:
            by_station.setdefault(segment.source_row_id, []).append(
                (round(segment.station_start_m, 2), segment.tire_track_id, segment.tire_side)
            )
        for fs_id in ("ROW_30", "ROW_60"):
            self.assertEqual(
                sorted(by_station[fs_id]),
                [(34.7, "TT_1_LEFT", "LEFT"), (36.7, "TT_1_RIGHT", "RIGHT")],
            )

    def test_result_independent_of_sample_step(self):
        scenarios = [
            ([tire([(20, 40), (180, 40)], "left"), tire([(20, 42), (180, 42)], "right")],
             [(50, 5), (50, 95)]),
            ([tire(arc(100, -20, 70, 50, 130), "left"), tire(arc(100, -20, 72, 50, 130), "right")],
             [(30, 5), (40, 60), (55, 20), (70, 90)]),
        ]
        for tracks, points in scenarios:
            results = []
            for step in (0.5, 2.5, 10.0, 50.0):
                with mock.patch.object(shutoff_engine, "_TRACK_ROW_SAMPLE_M", step):
                    segments = apply_row_shutoff([row(points)], [], tire_tracks=tracks)
                results.append([(round(a, 6), round(b, 6)) for a, b in off_intervals(segments)])
            self.assertTrue(results[0])
            for other in results[1:]:
                self.assertEqual(results[0], other)

    def test_on_areas_path_uses_exact_intervals(self):
        tracks = [tire([(20, 40), (180, 40)], "left"), tire([(20, 42), (180, 42)], "right")]
        field = [([(0, 0), (200, 0), (200, 100), (0, 100), (0, 0)], [])]
        segments = apply_row_shutoff(
            [row([(50, 5), (50, 95)])], [], on_areas=field, tire_tracks=tracks
        )
        self.assert_intervals(off_intervals(segments), [(34.7, 35.3), (36.7, 37.3)])

    def test_off_areas_combined_with_exact_tracks(self):
        tracks = [tire([(20, 40), (180, 40)], "left"), tire([(20, 42), (180, 42)], "right")]
        zone = [([(40, 70), (60, 70), (60, 80), (40, 80), (40, 70)], [])]
        segments = apply_row_shutoff(
            [row([(50, 5), (50, 95)])], [], off_areas=zone, tire_tracks=tracks
        )
        intervals = off_intervals(segments)
        self.assert_intervals(intervals[:2], [(34.7, 35.3), (36.7, 37.3)])
        self.assertEqual(len(intervals), 3)
        # Area poligonal segue amostrada (2,5 m); so o rastro e exato.
        self.assertAlmostEqual(intervals[2][0], 65.0, delta=2.5)
        self.assertAlmostEqual(intervals[2][1], 75.0, delta=2.5)


if __name__ == "__main__":
    unittest.main()
