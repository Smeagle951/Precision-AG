# -*- coding: utf-8 -*-
"""Cruzar plantio × rastros densos nao pode travar o QGIS."""

from __future__ import annotations

import time
import unittest

from plugin.fortsmart_precision.core.line_geometry import Segment
from plugin.fortsmart_precision.core.row_engine import PlantingRow
from plugin.fortsmart_precision.core.shutoff_engine import (
    _build_tire_strips,
    _decimate_polyline,
    apply_row_shutoff,
)
from plugin.fortsmart_precision.core.tire_track_engine import TireTrack


def _dense_track(pass_id: int, side: str, y: float, length_m: float = 800.0) -> TireTrack:
    """Rastro suavizado (~0,5 m) como no preview real — milhares de verts."""
    n = int(length_m / 0.5) + 1
    points = tuple((float(i) * 0.5, y) for i in range(n))
    return TireTrack(
        pass_id=pass_id,
        side=side,
        offset_m=1.53 if side == "right" else -1.53,
        tire_width_m=0.37,
        track_width_m=3.06,
        points=points,
    )


class ShutoffTireCrossPerfTest(unittest.TestCase):
    def test_decimate_polyline_removes_dense_vertices(self):
        pts = [(float(i) * 0.5, 0.0) for i in range(2001)]
        out = _decimate_polyline(pts, min_step_m=4.0, max_points=100)
        self.assertLessEqual(len(out), 100)
        self.assertEqual(out[0], pts[0])
        self.assertEqual(out[-1], pts[-1])

    def test_build_tire_strips_caps_axis_points(self):
        tracks = [_dense_track(1, "left", -1.53), _dense_track(1, "right", 1.53)]
        strips = _build_tire_strips(tracks)
        self.assertEqual(len(strips), 2)
        for strip in strips:
            self.assertLessEqual(len(strip.points), 100)
            self.assertGreaterEqual(len(strip.points), 2)

    def test_cross_many_parallel_rows_against_dense_tracks_finishes_fast(self):
        """Regressao do freeze no botao Cruzar (geometria real: rows // rastros)."""
        tracks: list[TireTrack] = []
        for pass_id in range(27):
            y = float(pass_id) * 36.0
            tracks.append(_dense_track(pass_id, "left", y - 1.53))
            tracks.append(_dense_track(pass_id, "right", y + 1.53))
        self.assertEqual(len(tracks), 54)
        self.assertGreater(sum(len(t.points) for t in tracks), 15000)

        # ~1980 linhas paralelas aos rastros (como plantio real); inclui eixos de pneu.
        rows: list[PlantingRow] = []
        for pass_id in range(55):
            base_y = float(pass_id) * 18.0
            for row_id in range(36):
                offset = (row_id - 17.5) * 0.5
                y = base_y + offset
                rows.append(
                    PlantingRow(
                        fs_id=f"r-{pass_id}-{row_id}",
                        row_id=row_id + 1,
                        pass_id=pass_id,
                        machine_id="p",
                        spacing_m=0.5,
                        direction="forward",
                        offset_m=offset,
                        azimuth_deg=0.0,
                        segment=Segment((0.0, y), (800.0, y)),
                    )
                )
        # Garante linhas exatamente no eixo do pneu (DESLIGA).
        for pass_id in range(27):
            y = float(pass_id) * 36.0
            for side, yy in (("L", y - 1.53), ("R", y + 1.53)):
                rows.append(
                    PlantingRow(
                        fs_id=f"tire-{pass_id}-{side}",
                        row_id=100 + pass_id,
                        pass_id=pass_id,
                        machine_id="p",
                        spacing_m=0.5,
                        direction="forward",
                        offset_m=yy - y,
                        azimuth_deg=0.0,
                        segment=Segment((0.0, yy), (800.0, yy)),
                    )
                )
        self.assertGreaterEqual(len(rows), 1980)

        t0 = time.perf_counter()
        segments = apply_row_shutoff(rows, tire_tracks=tracks)
        elapsed = time.perf_counter() - t0
        self.assertGreater(len(segments), 0)
        off = [s for s in segments if s.shutoff_state == "off"]
        self.assertGreater(len(off), 0, "esperado DESLIGA onde row cai no rastro")
        self.assertLess(
            elapsed,
            8.0,
            f"cruzar demorou {elapsed:.2f}s — ainda ha risco de travar o QGIS",
        )

    def test_perpendicular_crossing_still_detects_off(self):
        """Cruzamento perpendicular fino (regressao da distancia segmento×eixo)."""
        tracks = [_dense_track(0, "right", 1.53, length_m=100.0)]
        # Track denso mas curto; row perpendicular.
        row = PlantingRow(
            fs_id="cross",
            row_id=1,
            pass_id=0,
            machine_id="p",
            spacing_m=0.5,
            direction="forward",
            offset_m=1.53,
            azimuth_deg=90.0,
            segment=Segment((50.0, -10.0), (50.0, 10.0)),
        )
        segments = apply_row_shutoff([row], tire_tracks=tracks)
        off = [s for s in segments if s.shutoff_state == "off"]
        self.assertGreaterEqual(len(off), 1)
        self.assertGreater(sum(s.segment.length for s in off), 0.2)


if __name__ == "__main__":
    unittest.main()
