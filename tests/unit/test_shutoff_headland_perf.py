# -*- coding: utf-8 -*-
"""Shutoff em pivo denso nao pode travar (bordadura com milhares de vertices)."""

from __future__ import annotations

import time
import unittest
from math import cos, pi, sin

from plugin.fortsmart_precision.core.line_geometry import (
    Segment,
    resample_closed_ring,
    simplify_multipolygon_for_pip,
)
from plugin.fortsmart_precision.core.row_engine import PlantingRow
from plugin.fortsmart_precision.core.shutoff_engine import apply_row_shutoff
from plugin.fortsmart_precision.domain.boundary_areas import build_inner_and_headland


def _dense_circle(radius_m: float = 500.0, step_m: float = 2.0):
    n = max(32, int(2.0 * pi * radius_m / step_m))
    ring = [
        (radius_m * cos(2.0 * pi * i / n), radius_m * sin(2.0 * pi * i / n))
        for i in range(n)
    ]
    ring.append(ring[0])
    return [(ring, [])]


class ShutoffHeadlandPerfTest(unittest.TestCase):
    def test_resample_closed_ring_caps_vertices(self):
        field = _dense_circle()
        outer = field[0][0]
        self.assertGreater(len(outer), 1000)
        simplified = resample_closed_ring(outer, max_vertices=180, min_edge_m=2.0)
        # +1 pelo fechamento
        self.assertLessEqual(len(simplified), 182)
        self.assertGreaterEqual(len(simplified), 4)

    def test_shutoff_against_dense_headland_finishes_fast(self):
        """Regressao do freeze: 1980 linhas × bordadura 1500 verts ~20 min."""
        field = _dense_circle()
        areas = build_inner_and_headland(field, 18.0)
        self.assertTrue(areas.headland_area)
        raw_verts = len(areas.headland_area[0][0])
        self.assertGreater(raw_verts, 1000)

        simplified = simplify_multipolygon_for_pip(areas.headland_area, max_vertices=180)
        self.assertLessEqual(len(simplified[0][0]), 182)

        rows = [
            PlantingRow(
                fs_id=f"r-{i}",
                row_id=(i % 36) + 1,
                pass_id=i // 36,
                machine_id="p",
                spacing_m=0.5,
                direction="forward",
                offset_m=0.0,
                azimuth_deg=90.0,
                segment=Segment((-400.0, float(i % 50)), (400.0, float(i % 50))),
            )
            for i in range(500)
        ]
        t0 = time.perf_counter()
        segments = apply_row_shutoff(
            rows,
            [],
            off_areas=areas.headland_area,
            shutoff_on_tramlines=False,
        )
        elapsed = time.perf_counter() - t0
        self.assertGreater(len(segments), 0)
        # Antes: ~5 min para 500 linhas. Meta: < 5 s em CPU comum.
        self.assertLess(
            elapsed,
            5.0,
            f"shutoff demorou {elapsed:.2f}s — ainda ha risco de travar o QGIS",
        )


if __name__ == "__main__":
    unittest.main()
