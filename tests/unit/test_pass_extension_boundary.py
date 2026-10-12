# -*- coding: utf-8 -*-
"""Extensao externa: clip no limite operacional expandido (nao no original)."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.boundary_engine import build_boundary_plan
from plugin.fortsmart_precision.core.guidance_engine import generate_traffic_passes
from plugin.fortsmart_precision.core.line_geometry import (
    build_processing_boundary,
    multipolygon_bbox,
)
from plugin.fortsmart_precision.core.parallel_pass_engine import (
    ParallelPassParams,
    generate_parallel_passes,
)
from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, SprayerMachine
from plugin.fortsmart_precision.domain.precision_project import (
    ABLine,
    PrecisionOperation,
)


def rectangle(width=100.0, height=100.0, x=0.0, y=0.0):
    outer = [
        (x, y),
        (x + width, y),
        (x + width, y + height),
        (x, y + height),
        (x, y),
    ]
    return [(outer, [])]


def sprayer_36() -> SprayerMachine:
    return SprayerMachine(
        machine_id="spr36",
        name="Spray 36",
        nozzle_count=103,
        nozzle_spacing_m=0.35,
        boom_width_m=36.0,
        track=MachineTrack(track_width_m=3.0, tire_width_m=0.5),
    )


class ProcessingBoundaryTest(unittest.TestCase):
    def test_buffer_preserves_shape_not_bbox_only(self):
        field = rectangle(100, 100)
        proc = build_processing_boundary(field, 10.0)
        xmin, ymin, xmax, ymax = multipolygon_bbox(proc)
        self.assertAlmostEqual(xmin, -10.0, places=5)
        self.assertAlmostEqual(ymin, -10.0, places=5)
        self.assertAlmostEqual(xmax, 110.0, places=5)
        self.assertAlmostEqual(ymax, 110.0, places=5)

    def test_zero_extension_returns_original(self):
        field = rectangle(50, 40)
        proc = build_processing_boundary(field, 0.0)
        self.assertEqual(multipolygon_bbox(proc), multipolygon_bbox(field))


class ExtensionClipTest(unittest.TestCase):
    def test_extension_10_20_50_lengths(self):
        field = rectangle(100, 100)
        for ext in (10.0, 20.0, 50.0):
            with self.subTest(ext=ext):
                params = ParallelPassParams(
                    polygons=field,
                    ab_start=(0.0, 50.0),
                    ab_end=(100.0, 50.0),
                    pass_spacing_m=50.0,
                    operation_width_m=36.0,
                    extension_m=ext,
                    clip_boundary=field,
                )
                passes = generate_parallel_passes(params)
                mid = next(p for p in passes if abs(p.guidance_segment.start[1] - 50.0) < 1e-6)
                xs = (mid.guidance_segment.start[0], mid.guidance_segment.end[0])
                self.assertAlmostEqual(min(xs), -ext, places=5)
                self.assertAlmostEqual(max(xs), 100.0 + ext, places=5)
                self.assertAlmostEqual(mid.length_m, 100.0 + 2.0 * ext, places=5)

    def test_no_second_clip_to_original(self):
        """Passada final deve ultrapassar o limite original em +extensao."""
        field = rectangle(100, 100)
        params = ParallelPassParams(
            polygons=field,
            ab_start=(0.0, 50.0),
            ab_end=(100.0, 50.0),
            pass_spacing_m=100.0,
            operation_width_m=36.0,
            extension_m=10.0,
            clip_boundary=field,
        )
        passes = generate_parallel_passes(params)
        self.assertGreater(len(passes), 0)
        for item in passes:
            xs = (item.guidance_segment.start[0], item.guidance_segment.end[0])
            self.assertLess(min(xs), 0.0)
            self.assertGreater(max(xs), 100.0)


class HeadlandIndependentOfExtensionTest(unittest.TestCase):
    def test_headland_width_unchanged_by_extension(self):
        field = rectangle(400, 240)
        ab = ABLine(start=(0.0, 120.0), end=(400.0, 120.0))
        op = PrecisionOperation(
            operation_id="spraying",
            machine=sprayer_36(),
            extension_m=50.0,
            headland=HeadlandLayout(
                pass_count=1,
                width_m=36.0,
                effective_spacing_m=36.0,
                mode="follow_boundary",
            ),
        )
        boundary = build_boundary_plan(field, op, ab.start, ab.end)
        self.assertAlmostEqual(boundary.reserved_width_m, 36.0)
        # Passadas no miolo ainda saem +50 m alem do operacional.
        passes = generate_traffic_passes(
            boundary.inner_boundary or field,
            ab,
            op,
            clip_boundary=field,
        )
        self.assertGreater(len(passes), 0)
        lengths = [p.guidance_segment.length for p in passes]
        # Miolo ~ 400-72 = 328 m de largura util no eixo X se AB horizontal...
        # Comprimento da passada no eixo X: deve ser > 400 (ultrapassa externos).
        self.assertGreater(max(lengths), 400.0 + 50.0)


class PipelineExtensionTest(unittest.TestCase):
    def test_guidance_uses_processing_boundary(self):
        field = rectangle(100, 100)
        ab = ABLine(start=(0.0, 50.0), end=(100.0, 50.0))
        op = PrecisionOperation(
            operation_id="spraying",
            machine=sprayer_36(),
            extension_m=20.0,
        )
        passes = generate_traffic_passes(field, ab, op, clip_boundary=field)
        mid = next(p for p in passes if abs(p.guidance_segment.start[1] - 50.0) < 1.0)
        xs = (mid.guidance_segment.start[0], mid.guidance_segment.end[0])
        self.assertAlmostEqual(min(xs), -20.0, places=4)
        self.assertAlmostEqual(max(xs), 120.0, places=4)


class ShortCurvedAbFillsFieldTest(unittest.TestCase):
    """A-B curva curta no miolo deve ainda assim alcancar processing (±ext)."""

    def test_short_curve_reaches_processing_boundary(self):
        field = rectangle(400.0, 300.0)
        master = ((150.0, 150.0), (200.0, 160.0), (250.0, 150.0))
        for ext in (0.0, 20.0, 50.0):
            params = ParallelPassParams(
                polygons=field,
                ab_start=master[0],
                ab_end=master[-1],
                master_path=master,
                operation_id="spray",
                operation_width_m=36.0,
                pass_spacing_m=36.0,
                extension_m=ext,
                clip_boundary=field,
            )
            passes = generate_parallel_passes(params)
            self.assertGreater(len(passes), 0)
            xs: list[float] = []
            for item in passes:
                xs.extend(pt[0] for pt in item.line_points())
            # Processing = field.buffer(+ext): x in [-ext, 400+ext]
            self.assertLess(min(xs), 5.0 - ext + 15.0, f"ext={ext} min={min(xs)}")
            self.assertGreater(max(xs), 395.0 + ext - 15.0, f"ext={ext} max={max(xs)}")


if __name__ == "__main__":
    unittest.main()
