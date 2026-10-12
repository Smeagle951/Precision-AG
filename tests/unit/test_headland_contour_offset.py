# -*- coding: utf-8 -*-
"""Bordadura: trator no meio da faixa e distancia travada tambem nas curvas."""

from __future__ import annotations

import math
import unittest

from plugin.fortsmart_precision.core.boundary_engine import build_boundary_plan
from plugin.fortsmart_precision.core.line_geometry import (
    line_line_intersection,
    offset_closed_ring,
)
from plugin.fortsmart_precision.core.path_smoothing_engine import smooth_boundary_plan
from plugin.fortsmart_precision.domain.headland_layout import (
    HEADLAND_CORNER_AUTO,
    HEADLAND_CORNER_FOLLOW_BOUNDARY,
    HeadlandLayout,
    passes_for_total_width,
)
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, PlanterMachine
from plugin.fortsmart_precision.domain.path_smoothing_configuration import (
    PathSmoothingConfiguration,
    SmoothingLevel,
)
from plugin.fortsmart_precision.domain.precision_project import PrecisionOperation


def _planter_18m():
    """Plantadeira de 18 m (36 linhas x 0,5 m) = bordadura de 18 m por passada."""
    return PlanterMachine(
        machine_id="p18",
        name="36x0.5",
        row_count=36,
        row_spacing_m=0.5,
        track=MachineTrack(track_width_m=1.8, tire_width_m=0.3),
    )


class SprayerHeadlandWidthTest(unittest.TestCase):
    """Bordadura de pulverizacao informada em metros, como a da plantadeira.

    Antes o pulverizador so aceitava 1 passada de barra. Com a metragem, uma
    barra de 36 m atende 36 m com uma passada e 72 m com duas, e a linha do
    trator continua a meia barra do limite.
    """

    def test_one_boom_when_band_equals_boom(self):
        self.assertEqual(passes_for_total_width(36.0, 36.0), 1)

    def test_band_wider_than_boom_rounds_up(self):
        self.assertEqual(passes_for_total_width(50.0, 36.0), 2)
        self.assertEqual(passes_for_total_width(72.0, 36.0), 2)

    def test_tractor_line_stays_at_half_boom_from_boundary(self):
        layout = HeadlandLayout(
            pass_count=passes_for_total_width(72.0, 36.0),
            width_m=36.0,
            effective_spacing_m=36.0,
            mode="follow_boundary",
        )
        self.assertEqual(layout.center_offsets_m(), [18.0, 54.0])
        self.assertAlmostEqual(layout.reserved_width_m, 72.0, places=6)

    def test_fractional_boom_is_not_rounded_to_a_fixed_machine(self):
        layout = HeadlandLayout(
            pass_count=1,
            width_m=36.05,
            effective_spacing_m=36.05,
            mode="follow_boundary",
        )
        self.assertAlmostEqual(layout.center_offsets_m()[0], 18.025, places=6)


def _pivot_field(radius=300.0, segments=180):
    outer = [
        (radius * math.cos(2 * math.pi * i / segments), radius * math.sin(2 * math.pi * i / segments))
        for i in range(segments)
    ]
    outer.append(outer[0])
    return [(outer, [])]


def _sparse_curved_field():
    """Talhao curvo com poucos vertices na curva (comum em shapefile/QGIS)."""
    outer = [(0.0, 0.0), (400.0, 0.0)]
    for i in range(1, 9):
        ang = math.pi * i / 8.0
        outer.append((400.0 + 150.0 * math.sin(ang), 150.0 - 150.0 * math.cos(ang)))
    outer.extend([(400.0, 300.0), (0.0, 300.0), (0.0, 0.0)])
    return [(outer, [])]


def _max_edge_length(points):
    pts = list(points)
    if len(pts) < 2:
        return 0.0
    return max(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))


def _curved_field():
    """Talhao com um lado reto e um lado curvo (raio pequeno)."""
    outer = [(0.0, 0.0), (400.0, 0.0)]
    for i in range(1, 90):
        ang = math.pi * i / 90.0
        outer.append((400.0 + 150.0 * math.sin(ang), 150.0 - 150.0 * math.cos(ang)))
    outer.extend([(400.0, 300.0), (0.0, 300.0), (0.0, 0.0)])
    return [(outer, [])]


def _sharp_v_field():
    return [
        (
            [
                (0.0, 0.0),
                (200.0, 0.0),
                (200.0, 80.0),
                (300.0, 100.0),
                (200.0, 120.0),
                (200.0, 200.0),
                (0.0, 200.0),
                (0.0, 0.0),
            ],
            [],
        )
    ]


def _narrow_u_field():
    cap = [
        (
            300.0 + 5.0 * math.cos(-math.pi / 2.0 + index * math.pi / 12.0),
            100.0 + 5.0 * math.sin(-math.pi / 2.0 + index * math.pi / 12.0),
        )
        for index in range(13)
    ]
    return [
        (
            [
                (0.0, 0.0),
                (200.0, 0.0),
                (200.0, 95.0),
                *cap,
                (200.0, 105.0),
                (200.0, 200.0),
                (0.0, 200.0),
                (0.0, 0.0),
            ],
            [],
        )
    ]


def _min_distance_to_ring(point, ring):
    best = float("inf")
    pts = list(ring)
    for a, b in zip(pts, pts[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        seg2 = dx * dx + dy * dy
        if seg2 <= 1e-12:
            continue
        t = ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / seg2
        t = max(0.0, min(1.0, t))
        px, py = a[0] + t * dx, a[1] + t * dy
        best = min(best, math.hypot(point[0] - px, point[1] - py))
    return best


def _operation(pass_count=1):
    machine = _planter_18m()
    width = machine.operational_width_m
    return PrecisionOperation(
        operation_id="planting",
        machine=machine,
        headland=HeadlandLayout(
            pass_count=pass_count,
            width_m=width,
            effective_spacing_m=width,
            mode="follow_boundary",
        ),
        extension_m=0.0,
    )


def _operation_for_width(width_m, pass_count=1, corner_mode=HEADLAND_CORNER_AUTO):
    machine = PlanterMachine(
        machine_id="test",
        name="test",
        row_count=max(1, int(round(width_m / 0.5))),
        row_spacing_m=0.5,
        track=MachineTrack(track_width_m=1.8, tire_width_m=0.3),
    )
    return PrecisionOperation(
        operation_id="planting",
        machine=machine,
        headland=HeadlandLayout(
            pass_count=pass_count,
            width_m=width_m,
            effective_spacing_m=width_m,
            mode="follow_boundary",
            corner_mode=corner_mode,
        ),
        extension_m=0.0,
    )


class HeadlandOffsetDistanceTest(unittest.TestCase):
    def test_offset_keeps_constant_distance_on_concave_curve(self):
        """Offset de 9 m nao pode variar em curva (nem gerar laco)."""
        ring = []
        for i in range(180):
            ang = 2 * math.pi * i / 180
            delta = ((ang - math.pi) % (2 * math.pi))
            radius = 100.0 - 25.0 * math.exp(-(delta ** 2) / 0.02)
            ring.append((radius * math.cos(ang), radius * math.sin(ang)))

        offset = offset_closed_ring(ring, 9.0)
        self.assertIsNotNone(offset)
        closed_source = list(ring) + [ring[0]]
        distances = [_min_distance_to_ring(p, closed_source) for p in offset]
        self.assertAlmostEqual(min(distances), 9.0, delta=0.15)
        self.assertAlmostEqual(max(distances), 9.0, delta=0.15)


class DensifyRingTest(unittest.TestCase):
    def test_long_edges_are_subdivided(self):
        from plugin.fortsmart_precision.core.line_geometry import (
            densify_closed_ring,
            distance,
            ring_without_duplicate_close,
        )

        ring = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0), (0.0, 0.0)]
        dense = densify_closed_ring(ring, max_edge_m=5.0)
        pts = ring_without_duplicate_close(dense)
        max_edge = max(distance(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts)))
        self.assertLessEqual(max_edge, 5.01)


class HeadlandCenterlineTest(unittest.TestCase):
    def test_tractor_runs_at_half_width_around_pivot(self):
        """Bordadura de 18 m: trator a 9 m do limite em TODO o contorno curvo."""
        field = _pivot_field()
        plan = build_boundary_plan(field, _operation(), (0.0, 0.0), (100.0, 0.0))
        self.assertEqual(len(plan.headland_centerlines), 1)
        line = plan.headland_centerlines[0]
        self.assertAlmostEqual(line.offset_from_outer_m, 9.0, places=6)

        points = line.line_points()
        self.assertGreater(len(points), 50)
        radii = [math.hypot(p[0], p[1]) for p in points]
        # Pivo de raio 300 (poligono inscrito): centro da faixa em ~291 m.
        self.assertAlmostEqual(min(radii), 291.0, delta=0.6)
        self.assertAlmostEqual(max(radii), 291.0, delta=0.6)

    def test_sparse_curved_headland_keeps_offset_band(self):
        """Poucos vertices na curva: densifica e mantem trator na faixa de 9 m."""
        field = _sparse_curved_field()
        plan = build_boundary_plan(field, _operation(), (0.0, 0.0), (100.0, 0.0))
        line = plan.headland_centerlines[0]
        points = list(line.line_points())
        source = list(field[0][0])
        self.assertGreater(len(points), 60)
        distances = [_min_distance_to_ring(p, source) for p in points]
        self.assertGreaterEqual(min(distances), 8.5)
        self.assertLessEqual(max(distances), 9.5)

    def test_curved_side_is_not_straightened_by_smoothing(self):
        """Suavizacao nao pode retificar a curva (trator sairia da faixa)."""
        field = _curved_field()
        plan = build_boundary_plan(field, _operation(), (0.0, 0.0), (100.0, 0.0))
        smoothed = smooth_boundary_plan(
            plan, PathSmoothingConfiguration(level=SmoothingLevel.LOW)
        )
        line = smoothed.headland_centerlines[0]
        points = list(line.line_points())
        source = list(field[0][0])
        distances = [_min_distance_to_ring(p, source) for p in points]
        self.assertGreaterEqual(min(distances), 8.5)
        self.assertLessEqual(max(distances), 9.5)
        # Contorno continua fechado.
        self.assertAlmostEqual(points[0][0], points[-1][0], places=3)
        self.assertAlmostEqual(points[0][1], points[-1][1], places=3)

    def test_reported_length_is_the_real_perimeter(self):
        """Metragem da bordadura = perimetro percorrido, nao start->end."""
        field = _pivot_field()
        plan = build_boundary_plan(field, _operation(), (0.0, 0.0), (100.0, 0.0))
        line = plan.headland_centerlines[0]
        expected = 2 * math.pi * 291.0
        self.assertAlmostEqual(line.length_m(), expected, delta=expected * 0.01)
        self.assertAlmostEqual(
            float(line.attributes()["length_m"]), line.length_m(), places=6
        )

        smoothed = smooth_boundary_plan(
            plan, PathSmoothingConfiguration(level=SmoothingLevel.LOW)
        )
        self.assertAlmostEqual(
            smoothed.headland_centerlines[0].length_m(), expected, delta=expected * 0.01
        )

    def test_second_pass_sits_one_width_further_in(self):
        field = _pivot_field()
        plan = build_boundary_plan(field, _operation(pass_count=2), (0.0, 0.0), (100.0, 0.0))
        offsets = sorted(line.offset_from_outer_m for line in plan.headland_centerlines)
        self.assertEqual(offsets, [9.0, 27.0])


class HeadlandSharpTipTest(unittest.TestCase):
    def test_auto_extends_both_v_legs_without_splitting_passes(self):
        plan = build_boundary_plan(
            _sharp_v_field(),
            _operation_for_width(10.0, pass_count=2),
            (0.0, 0.0),
            (100.0, 0.0),
        )

        self.assertEqual(len(plan.headland_centerlines), 2)
        self.assertEqual(
            [line.offset_from_outer_m for line in plan.headland_centerlines],
            [5.0, 15.0],
        )
        self.assertEqual(
            len({line.fs_id for line in plan.headland_centerlines}), 2
        )
        for line in plan.headland_centerlines:
            points = line.line_points()
            self.assertNotEqual(points[0], points[-1])
            crossing = line_line_intersection(
                points[0], points[1], points[-2], points[-1]
            )
            self.assertIsNotNone(crossing)
            self.assertGreater(crossing[0], 200.0)

    def test_auto_extends_narrow_u_as_two_parallel_legs(self):
        plan = build_boundary_plan(
            _narrow_u_field(),
            _operation_for_width(4.0),
            (0.0, 0.0),
            (100.0, 0.0),
        )

        points = plan.headland_centerlines[0].line_points()
        self.assertNotEqual(points[0], points[-1])
        self.assertGreater(points[0][0], 305.0)
        self.assertGreater(points[-1][0], 305.0)
        self.assertAlmostEqual(points[0][1], 103.0, delta=0.25)
        self.assertAlmostEqual(points[-1][1], 97.0, delta=0.25)

    def test_auto_keeps_wide_curve_closed(self):
        plan = build_boundary_plan(
            _pivot_field(),
            _operation_for_width(18.0),
            (0.0, 0.0),
            (100.0, 0.0),
        )
        points = plan.headland_centerlines[0].line_points()
        self.assertEqual(points[0], points[-1])

    def test_follow_boundary_keeps_sharp_v_closed(self):
        plan = build_boundary_plan(
            _sharp_v_field(),
            _operation_for_width(
                10.0, corner_mode=HEADLAND_CORNER_FOLLOW_BOUNDARY
            ),
            (0.0, 0.0),
            (100.0, 0.0),
        )
        points = plan.headland_centerlines[0].line_points()
        self.assertEqual(points[0], points[-1])

    def test_smoothing_does_not_distort_straight_through_headland(self):
        plan = build_boundary_plan(
            _sharp_v_field(),
            _operation_for_width(10.0),
            (0.0, 0.0),
            (100.0, 0.0),
        )
        original = plan.headland_centerlines[0].line_points()

        smoothed = smooth_boundary_plan(
            plan, PathSmoothingConfiguration(level=SmoothingLevel.HIGH)
        )

        self.assertEqual(smoothed.headland_centerlines[0].line_points(), original)


class HeadlandWidthToPassesTest(unittest.TestCase):
    def test_exact_multiple(self):
        self.assertEqual(passes_for_total_width(18.0, 9.0), 2)
        self.assertEqual(passes_for_total_width(18.0, 18.0), 1)

    def test_rounds_up_so_headland_is_never_short(self):
        # 20 m com maquina de 9 m: 2 passadas dariam 18 m (falta), entao 3.
        self.assertEqual(passes_for_total_width(20.0, 9.0), 3)
        self.assertEqual(passes_for_total_width(5.0, 12.0), 1)

    def test_zero_width_means_no_headland(self):
        self.assertEqual(passes_for_total_width(0.0, 9.0), 0)

    def test_informed_width_drives_reserved_band(self):
        machine = _planter_18m()
        count = passes_for_total_width(36.0, machine.operational_width_m)
        layout = HeadlandLayout(
            pass_count=count,
            width_m=machine.operational_width_m,
            effective_spacing_m=machine.operational_width_m,
            mode="follow_boundary",
        )
        self.assertEqual(count, 2)
        self.assertAlmostEqual(layout.reserved_width_m, 36.0, places=6)
        self.assertEqual(layout.center_offsets_m(), [9.0, 27.0])


if __name__ == "__main__":
    unittest.main()
