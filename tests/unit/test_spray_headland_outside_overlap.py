# -*- coding: utf-8 -*-
"""Bordadura da aplicacao: meia barra fisica, faixa para fora e passo efetivo."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.boundary_engine import build_boundary_plan
from plugin.fortsmart_precision.core.spray_headland_preview import (
    format_m,
    spray_headland_schematic_layout,
    spray_headland_summary,
)
from plugin.fortsmart_precision.domain.headland_layout import (
    HeadlandConfigurationError,
    HeadlandLayout,
)
from plugin.fortsmart_precision.domain.precision_project import PrecisionOperation
from plugin.fortsmart_precision.domain.sprayer_overlap import OVERLAP_MODE_NOZZLES

from tests.unit.test_spray_overlap_regression import FIELD, spray_result
from tests.unit.test_sprayer_overlap import sprayer_36


def layout(passes: int, outside: float, spacing: float = 35.0) -> HeadlandLayout:
    return HeadlandLayout(
        pass_count=passes,
        width_m=36.0,
        effective_spacing_m=spacing,
        mode="follow_boundary",
        outside_overlap_m=outside,
    )


def _point_segment_distance(point, start, end) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 <= 0 else max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length2))
    px, py = start[0] + t * dx, start[1] + t * dy
    return ((point[0] - px) ** 2 + (point[1] - py) ** 2) ** 0.5


def distances_to_field_boundary(points) -> tuple[float, float]:
    """Min/max da distancia (CRS metrico) entre vertices e o limite do talhao."""
    ring = FIELD[0][0]
    edges = list(zip(ring, ring[1:]))
    values = [min(_point_segment_distance(p, a, b) for a, b in edges) for p in points]
    return min(values), max(values)


class HeadlandOutsideOverlapLayoutTest(unittest.TestCase):
    def test_first_center_offset_for_outside_values(self):
        for outside, expected in ((0.0, 18.0), (0.5, 17.5), (1.0, 17.0)):
            with self.subTest(outside=outside):
                item = layout(1, outside)
                self.assertAlmostEqual(item.first_center_offset_m, expected)
                self.assertEqual(item.center_offsets_m(), [expected])

    def test_offsets_for_one_two_three_passes(self):
        expected = [17.5, 52.5, 87.5]
        for passes in (1, 2, 3):
            with self.subTest(passes=passes):
                item = layout(passes, 0.5)
                self.assertEqual(item.center_offsets_m(), expected[:passes])
                # Borda interna fisica da ultima passada = centro + meia barra.
                self.assertAlmostEqual(item.reserved_width_m, expected[passes - 1] + 18.0)

    def test_default_is_bitwise_legacy(self):
        legacy = HeadlandLayout(pass_count=3, width_m=36.0, effective_spacing_m=36.0, mode="follow_boundary")
        self.assertEqual(legacy.outside_overlap_m, 0.0)
        self.assertEqual(legacy.center_offsets_m(), [18.0, 54.0, 90.0])
        self.assertEqual(legacy.reserved_width_m, 36.0 + 2 * 36.0)

    def test_outside_must_be_below_half_boom(self):
        for outside in (18.0, 20.0):
            with self.subTest(outside=outside):
                with self.assertRaises(HeadlandConfigurationError):
                    layout(1, outside).validate()
        layout(1, 17.99).validate()
        with self.assertRaises(HeadlandConfigurationError):
            layout(1, -0.1).validate()
        HeadlandLayout(pass_count=0, outside_overlap_m=5.0).validate()

    def test_report_exposes_outside_and_first_center(self):
        report = layout(2, 0.5).report()
        self.assertEqual(report["outside_overlap_m"], 0.5)
        self.assertEqual(report["first_center_offset_m"], 17.5)
        self.assertEqual(report["center_offsets_m"], [17.5, 52.5])
        self.assertEqual(report["effective_spacing_m"], 35.0)


class SprayHeadlandPreviewTest(unittest.TestCase):
    def test_summary_text(self):
        self.assertEqual(
            spray_headland_summary(layout(1, 0.5)),
            "Barra fisica: 36,00 m / Meia barra: 18,00 m / Faixa fora: 0,50 m / "
            "Linha central: 17,50 m do limite / Passo efetivo: 35,00 m",
        )
        self.assertEqual(format_m(17.5), "17,50 m")

    def test_schematic_layout_positions(self):
        data = spray_headland_schematic_layout(
            boom_width_m=36.0, outside_overlap_m=0.5, width_px=400.0, height_px=110.0
        )
        self.assertTrue(data["valid"])
        self.assertTrue(data["has_outside"])
        scale = data["scale_px_per_m"]
        self.assertLess(data["boom_left_x"], data["boundary_x"])
        self.assertAlmostEqual(data["center_x"] - data["boundary_x"], 17.5 * scale)
        self.assertAlmostEqual(data["boom_right_x"] - data["boundary_x"], 35.5 * scale)
        self.assertGreaterEqual(data["boundary_x"] - data["boom_left_x"], 3.0)

    def test_schematic_without_outside_and_invalid_boom(self):
        data = spray_headland_schematic_layout(
            boom_width_m=36.0, outside_overlap_m=0.0, width_px=400.0, height_px=110.0
        )
        self.assertFalse(data["has_outside"])
        self.assertAlmostEqual(data["boom_left_x"], data["boundary_x"])
        self.assertFalse(
            spray_headland_schematic_layout(
                boom_width_m=0.0, outside_overlap_m=0.0, width_px=400.0, height_px=110.0
            )["valid"]
        )


class AcceptanceEngineTest(unittest.TestCase):
    """Barra 36 m, 72 bicos x 0,50, 2 bicos de transpasse, 0,50 m para fora."""

    def _machine(self):
        return sprayer_36(overlap_mode=OVERLAP_MODE_NOZZLES, overlap_nozzle_count=2)

    def test_boundary_plan_centerlines_measured_from_boundary(self):
        machine = self._machine()
        op = PrecisionOperation(
            operation_id="spraying",
            machine=machine,
            headland=layout(3, 0.5, spacing=machine.effective_pass_spacing_m),
        )
        plan = build_boundary_plan(FIELD, op, (0.0, 200.0), (600.0, 200.0))
        by_pass = {line.pass_no: line for line in plan.headland_centerlines}
        for pass_no, expected in ((0, 17.5), (1, 52.5), (2, 87.5)):
            with self.subTest(pass_no=pass_no):
                low, high = distances_to_field_boundary(by_pass[pass_no].line_points())
                self.assertAlmostEqual(low, expected, places=6)
                self.assertAlmostEqual(high, expected, places=6)
        self.assertAlmostEqual(plan.reserved_width_m, 87.5 + 18.0)
        self.assertAlmostEqual(machine.boom_width_m, 36.0)

    def test_run_precision_lines_acceptance(self):
        result = spray_result(
            overlap_m=0.0,
            headland_passes=2,
            effective_spacing_m=35.0,
            outside_overlap_m=0.5,
        )
        lines = sorted(result.boundary.headland_centerlines, key=lambda line: line.pass_no)
        self.assertEqual([round(line.offset_from_outer_m, 3) for line in lines], [17.5, 52.5])
        for line, expected in zip(lines, (17.5, 52.5)):
            low, high = distances_to_field_boundary(line.line_points())
            self.assertAlmostEqual(low, expected, places=6)
            self.assertAlmostEqual(high, expected, places=6)
        # Parte fisica da barra fora do limite na 1a passada = meia barra - centro.
        self.assertAlmostEqual(18.0 - lines[0].offset_from_outer_m, 0.5)
        self.assertAlmostEqual(result.boundary.reserved_width_m, 52.5 + 18.0)

    def test_run_precision_lines_nozzle_overlap_inner_spacing(self):
        from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
        from plugin.fortsmart_precision.domain.precision_project import (
            ABLine,
            FieldGeometry,
            PrecisionProject,
        )

        machine = self._machine()
        project = PrecisionProject(
            field=FieldGeometry(field_boundary=FIELD, operational_boundary=FIELD, crs_authid="EPSG:31982"),
            ab_line=ABLine(start=(0.0, 200.0), end=(600.0, 200.0)),
            spraying=PrecisionOperation(
                operation_id="spraying",
                machine=machine,
                headland=layout(1, 0.5, spacing=machine.effective_pass_spacing_m),
            ),
        )
        result = run_precision_lines(project)
        offsets = sorted({round(p.offset_m, 6) for p in result.spraying_passes})
        gaps = {round(b - a, 6) for a, b in zip(offsets, offsets[1:])}
        self.assertEqual(gaps, {35.0})
        self.assertTrue(all(abs(p.width_m - 36.0) < 1e-9 for p in result.spraying_passes))
        line = result.boundary.headland_centerlines[0]
        low, high = distances_to_field_boundary(line.line_points())
        self.assertAlmostEqual(low, 17.5, places=6)
        self.assertAlmostEqual(high, 17.5, places=6)


if __name__ == "__main__":
    unittest.main()
