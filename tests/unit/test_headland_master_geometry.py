# -*- coding: utf-8 -*-
"""Bordadura = transformacao geometrica do limite real (W/2), nunca retangulo."""

from __future__ import annotations

import math
import unittest

from plugin.fortsmart_precision.core.boundary_engine import (
    BoundaryEngineError,
    build_boundary_plan,
    headland_traffic_offset_m,
    master_boundary_geometry,
)
from plugin.fortsmart_precision.core.line_geometry import (
    distance,
    multipolygon_area,
    multipolygon_bbox,
    point_in_multipolygon,
)
from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, SprayerMachine
from plugin.fortsmart_precision.domain.precision_project import ABLine, PrecisionOperation


def _sprayer(boom: float) -> SprayerMachine:
    return SprayerMachine(
        machine_id="s",
        name=f"barra {boom}",
        nozzle_count=72,
        nozzle_spacing_m=0.5,
        boom_width_m=boom,
        track=MachineTrack(track_width_m=3.0, tire_width_m=0.37),
    )


def _spray_operation(boom: float, *, pass_count: int = 1) -> PrecisionOperation:
    return PrecisionOperation(
        operation_id="spraying",
        machine=_sprayer(boom),
        headland=HeadlandLayout(
            pass_count=pass_count,
            width_m=boom,
            effective_spacing_m=boom,
            mode="follow_boundary",
        ),
        extension_m=10.0,
    )


def _circle(center=(0.0, 0.0), radius=300.0, segments=72):
    ring = [
        (
            center[0] + radius * math.cos(2 * math.pi * i / segments),
            center[1] + radius * math.sin(2 * math.pi * i / segments),
        )
        for i in range(segments)
    ]
    ring.append(ring[0])
    return [(ring, [])]


def _concave_field():
    """Talhao em L (concavidade real)."""
    ring = [
        (0.0, 0.0),
        (600.0, 0.0),
        (600.0, 300.0),
        (300.0, 300.0),
        (300.0, 600.0),
        (0.0, 600.0),
        (0.0, 0.0),
    ]
    return [(ring, [])]


class TrafficOffsetRuleTest(unittest.TestCase):
    def test_offset_is_half_boom_for_any_width(self):
        for boom, expected in ((24.0, 12.0), (30.0, 15.0), (36.0, 18.0), (36.05, 18.025)):
            with self.subTest(boom=boom):
                self.assertAlmostEqual(headland_traffic_offset_m(boom), expected, places=4)

    def test_zero_width_is_rejected(self):
        with self.assertRaises(BoundaryEngineError):
            headland_traffic_offset_m(0.0)

    def test_plan_centerline_offset_matches_half_boom(self):
        field = _circle(radius=300.0)
        plan = build_boundary_plan(
            field,
            _spray_operation(36.0),
            (-300.0, 0.0),
            (300.0, 0.0),
        )
        self.assertEqual(len(plan.headland_centerlines), 1)
        self.assertAlmostEqual(plan.headland_centerlines[0].offset_from_outer_m, 18.0, places=4)
        self.assertAlmostEqual(plan.reserved_width_m, 36.0, places=4)


class ShapePreservationTest(unittest.TestCase):
    def test_circular_field_gives_circular_traffic_line(self):
        radius = 300.0
        field = _circle(radius=radius)
        plan = build_boundary_plan(
            field,
            _spray_operation(36.0),
            (-radius, 0.0),
            (radius, 0.0),
        )
        line = plan.headland_centerlines[0]
        points = line.line_points()
        self.assertGreater(len(points), 20)
        # Todo ponto da linha do trator fica a ~ (raio - 18) do centro do pivo.
        dists = [distance(pt, (0.0, 0.0)) for pt in points]
        for value in dists:
            self.assertAlmostEqual(value, radius - 18.0, delta=1.5)

    def test_traffic_line_is_not_a_rectangle(self):
        """Contorno circular nao pode degenerar em bbox."""
        field = _circle(radius=300.0)
        plan = build_boundary_plan(
            field,
            _spray_operation(36.0),
            (-300.0, 0.0),
            (300.0, 0.0),
        )
        points = list(plan.headland_centerlines[0].line_points())
        ring_area = abs(
            0.5
            * sum(
                a[0] * b[1] - b[0] * a[1]
                for a, b in zip(points, points[1:] + points[:1])
            )
        )
        xmin, ymin, xmax, ymax = multipolygon_bbox([(points, [])])
        bbox_area = (xmax - xmin) * (ymax - ymin)
        # Circulo ocupa ~78,5% da bbox; retangulo ocuparia ~100%.
        self.assertLess(ring_area / bbox_area, 0.85)
        self.assertGreater(ring_area / bbox_area, 0.70)

    def test_concave_field_keeps_concavity(self):
        field = _concave_field()
        plan = build_boundary_plan(
            field,
            _spray_operation(18.0),
            (0.0, 0.0),
            (600.0, 0.0),
        )
        inner = plan.inner_boundary
        self.assertTrue(inner)
        # O canto reentrante (450, 450) esta FORA do talhao em L.
        self.assertFalse(point_in_multipolygon((450.0, 450.0), field))
        self.assertFalse(point_in_multipolygon((450.0, 450.0), inner))
        # O miolo continua dentro do talhao original.
        self.assertTrue(point_in_multipolygon((150.0, 150.0), inner))


class MasterGeometryTest(unittest.TestCase):
    def test_master_preserves_area_and_only_adds_vertices(self):
        field = _circle(radius=300.0, segments=24)
        master = master_boundary_geometry(field, width_m=36.0)
        self.assertGreater(len(master[0][0]), len(field[0][0]))
        self.assertAlmostEqual(
            multipolygon_area(master),
            multipolygon_area(field),
            delta=multipolygon_area(field) * 0.01,
        )

    def test_inner_limit_and_traffic_line_share_geometry(self):
        """Limite interno e linha do trator saem da mesma referencia."""
        field = _circle(radius=300.0, segments=24)
        plan = build_boundary_plan(
            field,
            _spray_operation(36.0),
            (-300.0, 0.0),
            (300.0, 0.0),
        )
        traffic = plan.headland_centerlines[0].line_points()
        inner = plan.inner_boundary
        self.assertTrue(inner)
        # Linha do trator a 18 m; miolo comeca a 36 m: todo ponto de trafego
        # esta fora do miolo, mas dentro do talhao.
        outside_inner = sum(1 for pt in traffic if not point_in_multipolygon(pt, inner))
        self.assertEqual(outside_inner, len(traffic))
        inside_field = sum(1 for pt in traffic if point_in_multipolygon(pt, field))
        self.assertEqual(inside_field, len(traffic))


class HeadlandTooLargeTest(unittest.TestCase):
    def test_headland_that_eats_the_field_raises_clear_error(self):
        field = _circle(radius=20.0)
        with self.assertRaises(BoundaryEngineError) as ctx:
            build_boundary_plan(
                field,
                _spray_operation(36.0),
                (-20.0, 0.0),
                (20.0, 0.0),
            )
        self.assertIn("bordadura", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
