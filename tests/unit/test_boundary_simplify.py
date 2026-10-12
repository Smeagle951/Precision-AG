# -*- coding: utf-8 -*-
"""Limite superamostrado (vertice a cada poucos mm) nao pode travar a bordadura."""

from __future__ import annotations

import math
import time
import unittest

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon

from plugin.fortsmart_precision.core.boundary_engine import build_boundary_plan
from plugin.fortsmart_precision.core.boundary_simplify import (
    BOUNDARY_SIMPLIFY_TOLERANCE_M,
    simplify_dense_boundary,
)
from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, PlanterMachine
from plugin.fortsmart_precision.domain.precision_project import (
    ABLine,
    FieldGeometry,
    PrecisionOperation,
    PrecisionProject,
)

E0, N0 = 650000.0, 8500000.0


def dense_rectangle(width=600.0, height=400.0, step=0.005):
    """Retangulo com um vertice a cada `step` metros (como o limite do GS3)."""
    corners = [(E0, N0), (E0 + width, N0), (E0 + width, N0 + height), (E0, N0 + height)]
    ring = []
    for (x0, y0), (x1, y1) in zip(corners, corners[1:] + corners[:1]):
        count = int(math.hypot(x1 - x0, y1 - y0) / step)
        ring.extend((x0 + (x1 - x0) * i / count, y0 + (y1 - y0) * i / count) for i in range(count))
    ring.append(ring[0])
    return ring


def dense_circle(radius=300.0, count=150_000):
    ring = [(E0 + radius * math.cos(2 * math.pi * i / count), N0 + radius * math.sin(2 * math.pi * i / count)) for i in range(count)]
    return ring + [ring[0]]


def planter_operation(width=12.15, headland_passes=1):
    machine = PlanterMachine(
        machine_id="p", name="p", row_count=27, row_spacing_m=0.45,
        track=MachineTrack(track_width_m=3.0, tire_width_m=0.4), informed_operational_width_m=width,
    )
    return PrecisionOperation(
        operation_id="planting", machine=machine, extension_m=0.0,
        headland=HeadlandLayout(pass_count=headland_passes, width_m=width, effective_spacing_m=width, mode="follow_boundary"),
    )


def max_deviation(original_ring, simplified_ring) -> float:
    points = shapely.points(np.asarray(original_ring))
    return float(shapely.distance(points, LineString(simplified_ring)).max())


class SimplifyDenseBoundaryTest(unittest.TestCase):
    def test_oversampled_curve_is_reduced_within_2_mm(self):
        ring = dense_circle()

        (polygon,), summary = simplify_dense_boundary([(ring, [])])

        self.assertTrue(summary.applied)
        self.assertLess(summary.simplified_vertices, 3000)
        self.assertLessEqual(max_deviation(ring, polygon[0]), BOUNDARY_SIMPLIFY_TOLERANCE_M + 1e-9)
        self.assertAlmostEqual(Polygon(polygon[0]).area, Polygon(ring).area, delta=2.0)

    def test_collinear_oversampling_collapses_to_the_real_corners(self):
        (polygon,), _summary = simplify_dense_boundary([(dense_rectangle(), [])])

        self.assertEqual(len(polygon[0]), 5)
        self.assertEqual(sorted(set(polygon[0])), sorted({(E0, N0), (E0 + 600.0, N0), (E0 + 600.0, N0 + 400.0), (E0, N0 + 400.0)}))

    def test_normal_boundary_is_returned_untouched(self):
        polygons = [([(E0, N0), (E0 + 100, N0), (E0 + 100, N0 + 50), (E0, N0 + 50), (E0, N0)], [])]

        result, summary = simplify_dense_boundary(polygons)

        self.assertIs(result, polygons)
        self.assertFalse(summary.applied)

    def test_holes_are_kept(self):
        hole = [(E0 + 200, N0 + 100), (E0 + 250, N0 + 100), (E0 + 250, N0 + 150), (E0 + 200, N0 + 150), (E0 + 200, N0 + 100)]

        (polygon,), _summary = simplify_dense_boundary([(dense_rectangle(), [hole])])

        self.assertEqual(len(polygon[1]), 1)
        self.assertAlmostEqual(Polygon(polygon[1][0]).area, 2500.0)


class DenseBoundaryPipelineTest(unittest.TestCase):
    def test_headland_on_oversampled_boundary_finishes_and_keeps_offset(self):
        ring = dense_rectangle()  # ~400 mil vertices
        start = time.perf_counter()

        plan = build_boundary_plan([(ring, [])], planter_operation(), (E0, N0 + 200), (E0 + 600, N0 + 200))

        self.assertLess(time.perf_counter() - start, 20.0)
        centerline = LineString(plan.headland_centerlines[0].line_points())
        distances = shapely.distance(shapely.points(np.asarray(centerline.coords)), Polygon(ring).exterior)
        self.assertLess(abs(float(distances.min()) - 6.075), 0.01)
        self.assertLess(abs(float(distances.max()) - 6.075), 0.01)

    def test_generator_runs_with_simplified_boundary_in_the_result(self):
        ring = dense_rectangle()
        project = PrecisionProject(
            field=FieldGeometry([(ring, [])], [(ring, [])], "EPSG:31982"),
            ab_line=ABLine((E0, N0 + 200), (E0 + 600, N0 + 200)),
            planting=planter_operation(),
        )

        with self.assertLogs("fortsmart_precision.boundary", level="INFO") as logs:
            result = run_precision_lines(project)

        self.assertIn("BOUNDARY SIMPLIFIED", "\n".join(logs.output))
        self.assertTrue(result.validation.ok, result.validation)
        self.assertGreater(len(result.planting_passes), 20)
        self.assertEqual(len(ring), len(project.field.operational_boundary[0][0]))  # entrada nao e alterada


if __name__ == "__main__":
    unittest.main()
