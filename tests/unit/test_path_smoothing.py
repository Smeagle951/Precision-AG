# -*- coding: utf-8 -*-
"""Testes de suavizacao global de linhas Precision Lines."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.guidance_engine import TrafficPass
from plugin.fortsmart_precision.core.line_geometry import Segment
from plugin.fortsmart_precision.core.path_smoothing_engine import (
    smooth_polyline,
    smooth_traffic_passes,
)
from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
from plugin.fortsmart_precision.domain.machine_model import load_machine_presets
from plugin.fortsmart_precision.domain.path_smoothing_configuration import (
    PathSmoothingConfiguration,
    SmoothingLevel,
)
from plugin.fortsmart_precision.domain.precision_project import (
    ABLine,
    FieldGeometry,
    PrecisionOperation,
    PrecisionProject,
)


def rectangle(width=400.0, height=240.0):
    outer = [(0.0, 0.0), (width, 0.0), (width, height), (0.0, height), (0.0, 0.0)]
    return [(outer, [])]


def sample_pass() -> TrafficPass:
    segment = Segment((0.0, 120.0), (400.0, 120.0))
    return TrafficPass(
        pass_no=1,
        fs_id="pass-1",
        operation_id="spraying",
        spacing_m=36.05,
        width_m=36.05,
        offset_m=0.0,
        azimuth_deg=0.0,
        direction="forward",
        clipped_segment=segment,
        guidance_segment=segment,
    )


class PathSmoothingTest(unittest.TestCase):
    def test_smooth_polyline_preserves_endpoints(self):
        points = [(0.0, 0.0), (100.0, 0.0)]
        config = PathSmoothingConfiguration(level=SmoothingLevel.MED)
        smoothed = smooth_polyline(points, config)
        self.assertGreater(len(smoothed), 2)
        self.assertEqual(smoothed[0], points[0])
        self.assertEqual(smoothed[-1], points[-1])

    def test_smooth_polyline_off_returns_original(self):
        points = [(0.0, 0.0), (100.0, 0.0)]
        config = PathSmoothingConfiguration(level=SmoothingLevel.OFF)
        smoothed = smooth_polyline(points, config)
        self.assertEqual(smoothed, tuple(points))

    def test_smooth_traffic_passes_populates_path_points(self):
        config = PathSmoothingConfiguration(level=SmoothingLevel.MED)
        result = smooth_traffic_passes([sample_pass()], config)
        self.assertEqual(len(result), 1)
        self.assertGreater(len(result[0].path_points), 2)
        self.assertEqual(result[0].path_points[0], sample_pass().guidance_segment.start)
        self.assertEqual(result[0].path_points[-1], sample_pass().guidance_segment.end)

    def test_pipeline_applies_smoothing_to_all_layers(self):
        field = rectangle()
        planter = load_machine_presets()["db27_36x050"]
        sprayer = load_machine_presets()["uniport_5030_103x035"]
        project = PrecisionProject(
            field=FieldGeometry(field_boundary=field, operational_boundary=field, crs_authid="EPSG:31982"),
            ab_line=ABLine(start=(0.0, 120.0), end=(400.0, 120.0)),
            planting=PrecisionOperation(
                operation_id="planting",
                machine=planter,
                headland=HeadlandLayout(pass_count=1, width_m=18.0, effective_spacing_m=18.0, mode="parallel_ab"),
            ),
            spraying=PrecisionOperation(
                operation_id="spraying",
                machine=sprayer,
                headland=HeadlandLayout(pass_count=0),
            ),
            line_smoothing=PathSmoothingConfiguration(level=SmoothingLevel.MED),
        )
        result = run_precision_lines(project)
        self.assertGreater(len(result.planting_passes), 0)
        self.assertTrue(all(len(p.path_points) > 2 for p in result.planting_passes))
        # Linhas virtuais nao sao densificadas (performance).
        self.assertTrue(all(len(r.line_points()) >= 2 for r in result.planting_rows))
        self.assertTrue(all(len(p.path_points) > 2 for p in result.spraying_passes))
        self.assertGreater(len(result.shutoff_segments), 0)
        self.assertIsNotNone(result.boundary)
        assert result.boundary is not None
        self.assertTrue(all(len(h.path_points) > 2 for h in result.boundary.headland_centerlines))


if __name__ == "__main__":
    unittest.main()
