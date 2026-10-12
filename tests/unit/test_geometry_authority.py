# -*- coding: utf-8 -*-
"""Regressao: limite real e linha mestra (sem bbox/reta inventados)."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.boundary_engine import build_boundary_plan
from plugin.fortsmart_precision.core.guidance_engine import generate_traffic_passes
from plugin.fortsmart_precision.core.line_geometry import (
    point_in_multipolygon,
    ring_bbox,
    shrink_axis_aligned_polygon,
    shrink_polygon,
)
from plugin.fortsmart_precision.core.parallel_pass_engine import ParallelPassParams, generate_parallel_passes
from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
from plugin.fortsmart_precision.domain.boundary_areas import build_inner_and_headland
from plugin.fortsmart_precision.domain.guidance_reference import GuidanceMode, GuidanceReference
from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, SprayerMachine
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


def irregular_field():
    """Talhao em L — bbox seria um retangulo que nao e o limite."""
    outer = [
        (0.0, 0.0),
        (300.0, 0.0),
        (300.0, 100.0),
        (120.0, 100.0),
        (120.0, 240.0),
        (0.0, 240.0),
        (0.0, 0.0),
    ]
    return [(outer, [])]


def sprayer_36() -> SprayerMachine:
    return SprayerMachine(
        machine_id="s36",
        name="Barra 36m",
        nozzle_count=72,
        nozzle_spacing_m=0.5,
        boom_width_m=36.0,
        track=MachineTrack(track_width_m=3.10, tire_width_m=0.35),
        overlap_m=0.0,
    )


class RealBoundaryShrinkTest(unittest.TestCase):
    def test_irregular_inner_is_not_bbox(self):
        field = irregular_field()
        areas = build_inner_and_headland(field, 36.0)
        self.assertIsNotNone(areas.inner_work_area)
        inner_outer = areas.inner_work_area[0][0]
        # Outer do projeto permanece o L original.
        self.assertEqual(areas.operational_boundary, field)
        # Inner preserva o L (mais de 4 vertices tipicos de bbox).
        unique = {(round(p[0], 1), round(p[1], 1)) for p in inner_outer[:-1]}
        self.assertGreaterEqual(len(unique), 6)
        # Degrau do L sobrevive: o ponto deslocado para dentro pertence ao miolo
        # (a reentrancia vira arco de 36 m, entao nao ha vertice exato ali).
        self.assertTrue(point_in_multipolygon((84.0, 64.0), areas.inner_work_area))
        # Ponto no canto do bbox que esta FORA do L nao pode estar no miolo.
        outside_l = (250.0, 200.0)
        self.assertFalse(point_in_multipolygon(outside_l, field))
        self.assertFalse(point_in_multipolygon(outside_l, areas.inner_work_area))
        # Retangulo do bbox encolhido conteria (250,200); o L encolhido nao.
        bbox_inner = shrink_axis_aligned_polygon(
            (
                [
                    (0.0, 0.0),
                    (300.0, 0.0),
                    (300.0, 240.0),
                    (0.0, 240.0),
                    (0.0, 0.0),
                ],
                [],
            ),
            36.0,
        )
        self.assertIsNotNone(bbox_inner)
        self.assertTrue(point_in_multipolygon(outside_l, [bbox_inner]))
        self.assertFalse(point_in_multipolygon(outside_l, areas.inner_work_area))

    def test_boom_36_outer_traffic_inner_are_distinct(self):
        field = rectangle(400, 240)
        op = PrecisionOperation(
            operation_id="spraying",
            machine=sprayer_36(),
            headland=HeadlandLayout(pass_count=1, width_m=36.0, mode="follow_boundary"),
        )
        plan = build_boundary_plan(field, op, (0.0, 120.0), (400.0, 120.0))
        self.assertAlmostEqual(plan.reserved_width_m, 36.0)
        self.assertEqual(len(plan.headland_centerlines), 1)
        self.assertAlmostEqual(plan.headland_centerlines[0].offset_from_outer_m, 18.0)
        traffic = plan.headland_centerlines[0].line_points()
        self.assertGreater(len(traffic), 4)
        inner = plan.headland_inner_limits[0].points
        # Outer bbox 400x240; inner ~328x168; traffic ring ~364x204 — formas diferentes.
        ox0, oy0, ox1, oy1 = ring_bbox(field[0][0])
        ix0, iy0, ix1, iy1 = ring_bbox(list(inner))
        self.assertAlmostEqual((ox1 - ox0) - (ix1 - ix0), 72.0, delta=2.0)
        self.assertAlmostEqual((oy1 - oy0) - (iy1 - iy0), 72.0, delta=2.0)
        tx0, ty0, tx1, ty1 = ring_bbox(list(traffic))
        self.assertAlmostEqual((ox1 - ox0) - (tx1 - tx0), 36.0, delta=2.0)
        # Tres geometrias distintas.
        self.assertNotEqual(round(ox1 - ox0, 1), round(tx1 - tx0, 1))
        self.assertNotEqual(round(tx1 - tx0, 1), round(ix1 - ix0, 1))


class MasterCurvePreservedTest(unittest.TestCase):
    def test_curved_ab_not_collapsed_to_chord(self):
        field = rectangle(400, 240)
        curve = (
            (0.0, 80.0),
            (100.0, 100.0),
            (200.0, 140.0),
            (300.0, 160.0),
            (400.0, 140.0),
        )
        ab = ABLine(start=curve[0], end=curve[-1], path_points=curve)
        params = ParallelPassParams(
            polygons=field,
            ab_start=ab.start,
            ab_end=ab.end,
            pass_spacing_m=36.0,
            operation_width_m=36.0,
            extension_m=10.0,
            master_path=curve,
        )
        passes = generate_parallel_passes(params)
        self.assertGreater(len(passes), 0)
        # Pelo menos uma passada com polilinha (nao so 2 pontos da corda).
        curved = [p for p in passes if len(p.line_points()) > 2]
        self.assertGreater(len(curved), 0)
        sample = curved[0].line_points()
        # Nao pode ser a reta start-end: ponto medio deve desviar da corda.
        mid = sample[len(sample) // 2]
        chord_y_at_x = 80.0 + (140.0 - 80.0) * ((mid[0] - 0.0) / 400.0)
        # Se colapsasse em reta, y estaria na corda; curva original sobe ate 160.
        self.assertGreater(abs(mid[1] - chord_y_at_x), 1.0)

    def test_pipeline_keeps_guidance_curve(self):
        field = rectangle(400, 240)
        curve = (
            (0.0, 100.0),
            (80.0, 110.0),
            (160.0, 130.0),
            (240.0, 150.0),
            (320.0, 140.0),
            (400.0, 120.0),
        )
        project = PrecisionProject(
            field=FieldGeometry(
                field_boundary=field,
                operational_boundary=field,
                crs_authid="EPSG:31982",
            ),
            ab_line=ABLine(start=curve[0], end=curve[-1], path_points=curve),
            spraying=PrecisionOperation(operation_id="spraying", machine=sprayer_36()),
            guidance_reference=GuidanceReference(
                mode=GuidanceMode.CURVED,
                start=curve[0],
                end=curve[-1],
                control_points=curve,
            ),
            line_smoothing=PathSmoothingConfiguration(level=SmoothingLevel.OFF),
        )
        result = run_precision_lines(project)
        self.assertGreater(len(result.spraying_passes), 0)
        effective = result.project.effective_ab_line().line_points()
        self.assertEqual(len(effective), len(curve))
        self.assertGreater(
            sum(1 for p in result.spraying_passes if len(p.line_points()) > 2),
            0,
        )


class PassesCoverFieldTest(unittest.TestCase):
    def test_passes_cover_full_width(self):
        field = rectangle(400, 240)
        ab = ABLine(start=(0.0, 120.0), end=(400.0, 120.0))
        op = PrecisionOperation(operation_id="spraying", machine=sprayer_36(), extension_m=10.0)
        passes = generate_traffic_passes(field, ab, op)
        ys = [p.guidance_segment.start[1] for p in passes]
        self.assertLess(min(ys), 40.0)
        self.assertGreater(max(ys), 200.0)
        # Extensao 10 m: comprimento > largura do talhao.
        self.assertGreater(passes[0].guidance_segment.length, 400.0)


class ShrinkPolygonShapeTest(unittest.TestCase):
    def test_rectangle_shrink_matches_expected(self):
        poly = rectangle(100, 60)[0]
        shrunk = shrink_polygon(poly, 10.0)
        self.assertIsNotNone(shrunk)
        xmin, ymin, xmax, ymax = ring_bbox(shrunk[0])
        self.assertAlmostEqual(xmin, 10.0, delta=0.5)
        self.assertAlmostEqual(ymin, 10.0, delta=0.5)
        self.assertAlmostEqual(xmax, 90.0, delta=0.5)
        self.assertAlmostEqual(ymax, 50.0, delta=0.5)


if __name__ == "__main__":
    unittest.main()
