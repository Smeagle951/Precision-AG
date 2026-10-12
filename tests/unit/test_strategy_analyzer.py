# -*- coding: utf-8 -*-
"""Analisador de estrategias de linhas (motor puro, sem QGIS)."""

from __future__ import annotations

import dataclasses
import json
import math
import tempfile
import unittest
from pathlib import Path

from shapely.geometry import LineString, Point as ShapelyPoint, Polygon

from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
from plugin.fortsmart_precision.domain.machine_model import PlanterMachine, load_machine_presets
from plugin.fortsmart_precision.domain.precision_project import (
    ABLine,
    FieldGeometry,
    PrecisionOperation,
    PrecisionProject,
)
from plugin.fortsmart_precision.strategy_analyzer.curve_strategy import (
    CURVE_SOURCE_AB,
    CURVE_SOURCE_AUTO,
    CURVE_SOURCE_BOUNDARY,
    CURVE_SOURCE_LAYER,
    boundary_reference_curve,
    choose_curve_reference,
    generate_curve_candidate,
    with_curve_reference,
)
from plugin.fortsmart_precision.strategy_analyzer.field_context import FieldContext, build_field_context
from plugin.fortsmart_precision.strategy_analyzer.models import (
    CRITERION_LINE_COUNT,
    CRITERION_TOTAL_LENGTH,
    CURVE_REFERENCE_REQUIRED,
    CURVE_STRATEGY_INVALID,
    STRATEGY_ANALYSIS_NO_BOUNDARY,
    STRATEGY_ANALYSIS_NO_OPERATION,
    STRATEGY_ANALYSIS_NO_VALID_STRAIGHT,
    StrategyAnalysisConfig,
    StrategyAnalysisError,
    StrategyCandidate,
    StrategyLine,
    StrategyTolerances,
    StrategyType,
)
from plugin.fortsmart_precision.strategy_analyzer.strategy_analyzer import (
    LineStrategyAnalyzer,
    analysis_report,
    log_summary,
    write_analysis_report,
)
from plugin.fortsmart_precision.strategy_analyzer.strategy_metrics import (
    apply_line_metrics,
    crossing_count,
    minimum_curve_radius,
)
from plugin.fortsmart_precision.strategy_analyzer.strategy_ranker import (
    angle_distance,
    best_by,
    comparison_rows,
    format_km,
    summary_rows,
    rank_candidates,
    select_preview_candidates,
)
from plugin.fortsmart_precision.strategy_analyzer.strategy_validator import (
    reference_curve_problems,
    validate_candidate,
)
from plugin.fortsmart_precision.strategy_analyzer.straight_strategy import (
    coarse_angles,
    generate_straight_candidate,
    normalize_angle,
    refine_angles,
)

SPACING = 18.0


def rectangle(width, height, x=0.0, y=0.0):
    outer = [(x, y), (x + width, y), (x + width, y + height), (x, y + height), (x, y)]
    return [(outer, [])]


def rotated(polygons, angle_deg, center):
    cos_a, sin_a = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))

    def rot(point):
        dx, dy = point[0] - center[0], point[1] - center[1]
        return (center[0] + dx * cos_a - dy * sin_a, center[1] + dx * sin_a + dy * cos_a)

    return [([rot(p) for p in outer], [[rot(p) for p in hole] for hole in holes]) for outer, holes in polygons]


def context_for(polygons, *, field_id="TL-01", reference=(), anchor=None, extension=0.0):
    return FieldContext(
        field_id=field_id,
        work_area=polygons,
        allowed_area=polygons,
        operational_boundary=polygons,
        pass_spacing_m=SPACING,
        operation_width_m=SPACING,
        extension_m=extension,
        anchor=anchor,
        reference_curve=tuple(reference),
        reference_id="ref-1" if reference else "",
    )


def irregular_field():
    """Talhao em forma de feijao: borda sul curva, norte reta."""
    south = [(x, 60.0 * math.sin(math.pi * x / 600.0) * -1.0) for x in range(0, 601, 25)]
    north = [(600.0, 260.0), (0.0, 260.0)]
    outer = south + north + [south[0]]
    return [(outer, [])]


def arc_reference():
    return tuple((float(x), 130.0 - 60.0 * math.sin(math.pi * x / 600.0)) for x in range(0, 601, 20))


def db27() -> PlanterMachine:
    machine = load_machine_presets()["db27_36x050"]
    assert isinstance(machine, PlanterMachine)
    return machine


def project_for(polygons, *, field_id, ab, headland_passes=1):
    return PrecisionProject(
        field=FieldGeometry(
            field_id=field_id,
            field_boundary=polygons,
            operational_boundary=polygons,
            crs_authid="EPSG:31982",
        ),
        ab_line=ABLine(start=ab[0], end=ab[1]),
        planting=PrecisionOperation(
            operation_id="planting",
            machine=db27(),
            headland=HeadlandLayout(
                pass_count=headland_passes,
                width_m=18.0,
                effective_spacing_m=18.0,
                mode="parallel_ab",
            ),
        ),
    )


def fast_config(**overrides):
    values = dict(test_curve=False, compare_overlap=False, compare_gap=False)
    values.update(overrides)
    return StrategyAnalysisConfig(**values)


class AngleSearchTest(unittest.TestCase):
    def test_coarse_angles_never_include_180(self):
        angles = coarse_angles(StrategyAnalysisConfig())
        self.assertEqual(len(angles), 36)
        self.assertEqual(angles[0], 0.0)
        self.assertEqual(angles[-1], 175.0)
        self.assertNotIn(180.0, angles)

    def test_normalize_and_refine_wrap_around_zero(self):
        self.assertEqual(normalize_angle(180.0), 0.0)
        self.assertEqual(normalize_angle(-2.0), 178.0)
        self.assertEqual(refine_angles([0.0], 2.0, 1.0), [178.0, 179.0, 0.0, 1.0, 2.0])

    def test_invalid_config_rejected(self):
        with self.assertRaises(ValueError):
            StrategyAnalysisConfig(test_straight=False, test_curve=False).validate()
        with self.assertRaises(ValueError):
            StrategyAnalysisConfig(straight_angle_step=0).validate()
        with self.assertRaises(ValueError):
            StrategyAnalysisConfig(ranking_criterion="melhor").validate()


class StraightStrategyTest(unittest.TestCase):
    def test_rectangle_best_straight_follows_long_axis(self):
        context = context_for(rectangle(400, 240))
        result = LineStrategyAnalyzer().analyze(context, fast_config())
        best = result.best_by_line_count
        self.assertIsNotNone(best)
        self.assertEqual(best.strategy_type, StrategyType.STRAIGHT)
        self.assertAlmostEqual(best.angle_deg, 90.0, delta=1.0)
        across = generate_straight_candidate(context, 0.0)
        self.assertLess(best.line_count, len(across.lines))
        self.assertTrue(all(item.valid for item in result.straight_candidates()))
        self.assertEqual(best.turn_count, best.line_count - 1)

    def test_rotated_elongated_field_matches_dominant_axis(self):
        field = rotated(rectangle(1000, 200), 30.0, (500.0, 100.0))
        result = LineStrategyAnalyzer().analyze(context_for(field), fast_config())
        dominant_azimuth = math.degrees(math.atan2(math.cos(math.radians(30)), math.sin(math.radians(30))))
        self.assertAlmostEqual(dominant_azimuth, 60.0)
        best = result.best_by_line_count
        self.assertLessEqual(abs(best.angle_deg - dominant_azimuth), 2.0)
        self.assertGreater(result.straight_tested, 36)
        self.assertTrue(any(item.angle_deg % 1 for item in result.straight_candidates()))

    def test_straight_candidate_matches_generator_numbering_from_anchor(self):
        context = context_for(rectangle(400, 240), anchor=(0.0, 120.0))
        candidate = generate_straight_candidate(context, 90.0)
        numbers = [line.pass_no for line in candidate.lines]
        self.assertIn(0, numbers)
        zero = next(line for line in candidate.lines if line.pass_no == 0)
        self.assertAlmostEqual(zero.points[0][1], 120.0, places=6)
        self.assertEqual(numbers, sorted(numbers, reverse=numbers[0] > numbers[-1]))

    def test_no_valid_straight_reported_when_field_too_small(self):
        tiny = rectangle(5, 5)
        config = fast_config(straight_angle_step=45.0, fine_step_deg=0, refine_step_deg=45.0)
        result = LineStrategyAnalyzer().analyze(context_for(tiny), config)
        if not result.straight_valid:
            self.assertIn(STRATEGY_ANALYSIS_NO_VALID_STRAIGHT, result.issue_codes)
        self.assertTrue(all(line.length_m <= 10 for item in result.candidates for line in item.lines))


class CurveStrategyTest(unittest.TestCase):
    def test_irregular_field_straight_and_curve_stay_inside_allowed_area(self):
        field = irregular_field()
        context = context_for(field, reference=arc_reference())
        result = LineStrategyAnalyzer().analyze(
            context, StrategyAnalysisConfig(straight_angle_step=15.0, compare_gap=True)
        )
        curve = result.curve_candidate()
        self.assertIsNotNone(curve)
        self.assertTrue(curve.valid, curve.warnings)
        self.assertGreater(curve.line_count, 3)
        allowed = Polygon(field[0][0]).buffer(0.05)
        for candidate in result.preview_candidates:
            self.assertLessEqual(candidate.boundary_exit_length_m, 0.05 * candidate.line_count)
            for line in candidate.lines:
                self.assertTrue(LineString(line.points).within(allowed))
        self.assertIn(curve, result.preview_candidates)
        self.assertIsNotNone(curve.coverage_ha)
        self.assertIsNotNone(curve.gap_ha)
        self.assertEqual(curve.crossing_count, 0)
        self.assertIsNotNone(curve.minimum_curve_radius_m)

    def test_curve_without_reference_reports_required_code(self):
        result = LineStrategyAnalyzer().analyze(
            context_for(rectangle(400, 240)), fast_config(test_curve=True)
        )
        self.assertIn(CURVE_REFERENCE_REQUIRED, result.issue_codes)
        self.assertIsNone(result.curve_candidate())
        self.assertIsNotNone(result.best_by_line_count)
        with self.assertRaises(StrategyAnalysisError) as raised:
            generate_curve_candidate(context_for(rectangle(400, 240)), StrategyTolerances())
        self.assertEqual(raised.exception.code, CURVE_REFERENCE_REQUIRED)

    def test_invalid_curve_marked_invalid_and_analysis_continues(self):
        figure_eight = ((0.0, 0.0), (300.0, 200.0), (300.0, 0.0), (0.0, 200.0))
        context = context_for(rectangle(400, 240), reference=figure_eight)
        result = LineStrategyAnalyzer().analyze(context, fast_config(test_curve=True, straight_angle_step=30.0))
        curve = result.curve_candidate()
        self.assertIsNotNone(curve)
        self.assertFalse(curve.valid)
        self.assertIn(CURVE_STRATEGY_INVALID, result.issue_codes)
        self.assertNotIn(curve, result.preview_candidates)
        self.assertIsNotNone(result.best_by_line_count)
        self.assertEqual(result.best_by_line_count.strategy_type, StrategyType.STRAIGHT)

    def test_reference_curve_problems(self):
        self.assertTrue(reference_curve_problems([(0.0, 0.0)], 0.05))
        loop = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 0.0)]
        self.assertTrue(any("loop" in item for item in reference_curve_problems(loop, 0.05)))
        self.assertTrue(reference_curve_problems([(0.0, 0.0), (100.0, 0.0)], 0.05))
        self.assertEqual(reference_curve_problems(list(arc_reference()), 0.05), [])

    def test_reference_curve_is_not_modified(self):
        reference = [(float(x), 130.0 - 0.001 * (x - 300) ** 2) for x in range(0, 601, 30)]
        snapshot = list(reference)
        context = context_for(irregular_field(), reference=reference)
        generate_curve_candidate(context, StrategyTolerances())
        self.assertEqual(reference, snapshot)
        self.assertIsInstance(context.reference_curve, tuple)


class SimplifiedFlowEngineTest(unittest.TestCase):
    def test_fixed_ab_angle_tests_single_direction(self):
        result = LineStrategyAnalyzer().analyze(
            context_for(rectangle(400, 240)), fast_config(straight_fixed_angle=217.0)
        )
        self.assertEqual(result.straight_tested, 1)
        self.assertEqual(result.candidates[0].angle_deg, 37.0)
        self.assertEqual(len(result.preview_candidates), 1)

    def test_refine_can_be_disabled(self):
        result = LineStrategyAnalyzer().analyze(
            context_for(rectangle(400, 240)), fast_config(refine=False, straight_angle_end=175.0)
        )
        self.assertEqual(result.straight_tested, 36)
        self.assertTrue(all(item.angle_deg % 5 == 0 for item in result.candidates))

    def test_boundary_reference_follows_longest_curved_edge(self):
        field = irregular_field()
        points = boundary_reference_curve(field)
        self.assertGreaterEqual(len(points), 3)
        self.assertTrue(all(y <= 1e-6 for _x, y in points))
        self.assertGreater(LineString(points).length, 550.0)
        ring = Polygon(field[0][0]).exterior
        self.assertTrue(all(ring.distance(ShapelyPoint(p)) < 1e-6 for p in points))
        self.assertEqual(reference_curve_problems(points, 0.05), [])

    def test_boundary_reference_of_rectangle_is_straight_side(self):
        points = boundary_reference_curve(rectangle(400, 240))
        self.assertEqual(len(points), 2)
        self.assertAlmostEqual(LineString(points).length, 400.0)
        self.assertTrue(reference_curve_problems(points, 0.05))
        self.assertEqual(boundary_reference_curve([]), ())

    def test_choose_curve_reference_sources(self):
        arc = arc_reference()
        straight_ab = ((0.0, 0.0), (100.0, 0.0))
        auto_ab = choose_curve_reference(CURVE_SOURCE_AUTO, ab_points=arc, boundary_polygons=irregular_field())
        self.assertEqual(auto_ab.source, CURVE_SOURCE_AB)
        self.assertEqual(auto_ab.points, arc)
        auto_border = choose_curve_reference(
            CURVE_SOURCE_AUTO, ab_points=straight_ab, boundary_polygons=irregular_field()
        )
        self.assertEqual(auto_border.source, CURVE_SOURCE_BOUNDARY)
        self.assertEqual(auto_border.description, "borda do talhão")
        self.assertGreaterEqual(len(auto_border.points), 3)
        self.assertEqual(choose_curve_reference(CURVE_SOURCE_AB, ab_points=straight_ab).points, ())
        layer = choose_curve_reference(CURVE_SOURCE_LAYER, layer_points=arc, layer_id="lyr")
        self.assertEqual((layer.points, layer.reference_id), (arc, "lyr"))
        with self.assertRaises(ValueError):
            choose_curve_reference("melhor")

    def test_with_curve_reference_keeps_original_context(self):
        context = context_for(irregular_field())
        reference = choose_curve_reference(CURVE_SOURCE_BOUNDARY, boundary_polygons=context.work_area)
        updated = with_curve_reference(context, reference)
        self.assertEqual(context.reference_curve, ())
        self.assertEqual(updated.reference_curve, reference.points)
        self.assertEqual(updated.reference_id, "BOUNDARY")
        result = LineStrategyAnalyzer().analyze(updated, StrategyAnalysisConfig(test_straight=False))
        self.assertTrue(result.curve_candidate().valid, result.curve_candidate().warnings)

    def test_summary_rows_show_winner_and_difference(self):
        straight = StrategyCandidate(candidate_id="S", strategy_type=StrategyType.STRAIGHT, lines=(), angle_deg=37.0)
        curve = StrategyCandidate(candidate_id="C", strategy_type=StrategyType.CURVE, lines=())
        straight.line_count, straight.total_length_m, straight.turn_count = 78, 18240.0, 77
        curve.line_count, curve.total_length_m, curve.turn_count = 74, 18920.0, 73
        self.assertEqual(
            summary_rows([straight, curve]),
            ["Menos passadas: CURVA  -4", "Menor percurso: RETA 37°  -0,7 km", "Menos manobras: CURVA  -4"],
        )
        curve.line_count, curve.turn_count = 78, 77
        self.assertEqual(summary_rows([straight, curve])[0], "Menos passadas: empate")
        self.assertEqual(summary_rows([straight]), [])
        self.assertEqual(format_km(18240.0), "18,2 km")


class MetricsAndValidatorTest(unittest.TestCase):
    def _candidate(self, lines):
        return StrategyCandidate(
            candidate_id="X",
            strategy_type=StrategyType.CURVE,
            lines=tuple(
                StrategyLine(points=tuple(points), pass_no=i, length_m=0.0, spacing_m=18, width_m=18)
                for i, points in enumerate(lines)
            ),
        )

    def test_line_metrics_count_short_segments_and_exits(self):
        allowed = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
        candidate = self._candidate([[(10, 10), (90, 10)], [(10, 30), (25, 30)], [(50, 50), (150, 50)]])
        apply_line_metrics(candidate, allowed, StrategyTolerances(), check_crossings=True)
        self.assertEqual(candidate.line_count, 3)
        self.assertEqual(candidate.turn_count, 2)
        self.assertEqual(candidate.short_segment_count, 1)
        self.assertAlmostEqual(candidate.boundary_exit_length_m, 50.0, delta=0.1)
        validate_candidate(candidate, StrategyAnalysisConfig())
        self.assertFalse(candidate.valid)

    def test_self_intersection_and_crossings_invalidate(self):
        allowed = Polygon([(-10, -10), (110, -10), (110, 110), (-10, 110)])
        candidate = self._candidate(
            [[(0, 0), (100, 100), (100, 0), (0, 100)], [(0, 50), (100, 50)]]
        )
        apply_line_metrics(candidate, allowed, StrategyTolerances(), check_crossings=True)
        self.assertEqual(candidate.self_intersection_count, 1)
        self.assertGreaterEqual(candidate.crossing_count, 1)
        validate_candidate(candidate, StrategyAnalysisConfig())
        self.assertFalse(candidate.valid)

    def test_crossing_count_parallel_lines_zero(self):
        lines = [LineString([(0, y), (100, y)]) for y in (0, 18, 36)]
        self.assertEqual(crossing_count(lines, 0.05), 0)

    def test_minimum_curve_radius_of_circle_arc(self):
        arc = [(50 * math.cos(t / 20), 50 * math.sin(t / 20)) for t in range(0, 30)]
        line = StrategyLine(points=tuple(arc), pass_no=0, length_m=0, spacing_m=1, width_m=1)
        self.assertAlmostEqual(minimum_curve_radius([line], min_chord_m=1.0), 50.0, delta=0.5)
        straight = StrategyLine(points=((0, 0), (10, 0), (20, 0)), pass_no=0, length_m=0, spacing_m=1, width_m=1)
        self.assertIsNone(minimum_curve_radius([straight], min_chord_m=1.0))

    def test_min_radius_limit_invalidates_curve(self):
        candidate = self._candidate([[(0, 0), (100, 0)]])
        apply_line_metrics(candidate, Polygon([(-1, -1), (101, -1), (101, 1), (-1, 1)]), StrategyTolerances(), check_crossings=True)
        candidate.minimum_curve_radius_m = 12.0
        validate_candidate(candidate, StrategyAnalysisConfig(min_curve_radius_m=20.0))
        self.assertFalse(candidate.valid)


class RankerTest(unittest.TestCase):
    def _make(self, cid, kind, angle, lines, length):
        candidate = StrategyCandidate(candidate_id=cid, strategy_type=kind, lines=(), angle_deg=angle)
        candidate.line_count = lines
        candidate.turn_count = max(0, lines - 1)
        candidate.total_length_m = length
        return candidate

    def test_rankings_by_criterion_and_factual_rows(self):
        straight = self._make("S37", StrategyType.STRAIGHT, 37.0, 78, 18240.0)
        straight2 = self._make("S40", StrategyType.STRAIGHT, 40.0, 80, 18300.0)
        curve = self._make("C", StrategyType.CURVE, None, 74, 18920.0)
        invalid = self._make("BAD", StrategyType.STRAIGHT, 10.0, 10, 100.0)
        invalid.valid = False
        candidates = [straight, straight2, curve, invalid]
        self.assertIs(best_by(candidates, CRITERION_LINE_COUNT), curve)
        self.assertIs(best_by(candidates, CRITERION_TOTAL_LENGTH), straight)
        self.assertNotIn(invalid, rank_candidates(candidates, CRITERION_LINE_COUNT))
        rows = comparison_rows([straight, curve])
        self.assertIn("Menor número de passadas: CURVA (74)", rows)
        self.assertIn("Menor comprimento total: RETA 37° (18240.0 m)", rows)
        self.assertIn("Menos manobras: CURVA (73)", rows)
        self.assertFalse(any("MELHOR" in row.upper() for row in rows))

    def test_preview_selection_limits_to_best_straight_curve_second(self):
        s1 = self._make("S1", StrategyType.STRAIGHT, 37.0, 78, 1.0)
        s2 = self._make("S2", StrategyType.STRAIGHT, 38.0, 79, 1.0)
        s3 = self._make("S3", StrategyType.STRAIGHT, 39.0, 80, 1.0)
        curve = self._make("C", StrategyType.CURVE, None, 74, 1.0)
        selected = select_preview_candidates([s1, s2, s3, curve], CRITERION_LINE_COUNT, 3)
        self.assertEqual([item.candidate_id for item in selected], ["S1", "C", "S2"])
        self.assertEqual(len(select_preview_candidates([s1, s2, s3, curve], CRITERION_LINE_COUNT, 2)), 2)
        far = self._make("S4", StrategyType.STRAIGHT, 120.0, 90, 1.0)
        separated = select_preview_candidates(
            [s1, s2, s3, far, curve], CRITERION_LINE_COUNT, 3, min_angle_separation=5.0
        )
        self.assertEqual([item.candidate_id for item in separated], ["S1", "C", "S4"])
        wrap = self._make("S5", StrategyType.STRAIGHT, 178.0, 79, 1.0)
        best_zero = self._make("S0", StrategyType.STRAIGHT, 1.0, 70, 1.0)
        self.assertEqual(
            [c.candidate_id for c in select_preview_candidates([best_zero, wrap, far], CRITERION_LINE_COUNT, 3, min_angle_separation=5.0)],
            ["S0", "S4"],
        )

    def test_angle_distance_wraps_at_180(self):
        self.assertAlmostEqual(angle_distance(1.0, 178.0), 3.0)
        self.assertAlmostEqual(angle_distance(30.0, 120.0), 90.0)
        self.assertAlmostEqual(angle_distance(0.0, 0.0), 0.0)


class AnalyzerFlowTest(unittest.TestCase):
    def test_cancel_returns_without_error(self):
        calls = {"n": 0}

        def cancelled():
            calls["n"] += 1
            return calls["n"] > 3

        result = LineStrategyAnalyzer(is_cancelled=cancelled).analyze(
            context_for(rectangle(400, 240)), fast_config(test_curve=True)
        )
        self.assertTrue(result.cancelled)
        self.assertLess(result.straight_tested, 36)
        self.assertEqual(result.preview_candidates, [])

    def test_progress_messages(self):
        messages = []
        LineStrategyAnalyzer(progress=messages.append).analyze(
            context_for(rectangle(400, 240), reference=arc_reference()),
            StrategyAnalysisConfig(compare_overlap=False, compare_gap=False),
        )
        self.assertIn("Analisando retas... 18 / 36", messages)
        self.assertIn("Analisando curva...", messages)

    def test_log_summary_and_report(self):
        config = fast_config(test_curve=True)
        result = LineStrategyAnalyzer().analyze(context_for(rectangle(400, 240), field_id="TL-13"), config)
        summary = log_summary(result)
        self.assertTrue(summary.startswith("Field: TL-13 / STRAIGHT tested="))
        self.assertIn("best_angle=90", summary)
        self.assertIn(f"CURVE {CURVE_REFERENCE_REQUIRED}", summary)
        report = analysis_report(result, config)
        self.assertEqual(report["analysis_version"], 1)
        self.assertEqual(report["field_id"], "TL-13")
        with tempfile.TemporaryDirectory() as tmp:
            path = write_analysis_report(Path(tmp) / "STRATEGY_ANALYSIS_REPORT.json", result, config)
            data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["summary"], summary)
        self.assertEqual(data["straight_tested"], result.straight_tested)


class FieldContextTest(unittest.TestCase):
    def test_build_field_context_uses_headland_inner_area(self):
        field = rectangle(400, 240)
        project = project_for(field, field_id="TL-13", ab=((0.0, 120.0), (400.0, 120.0)))
        context = build_field_context(project)
        self.assertEqual(context.field_id, "TL-13")
        self.assertAlmostEqual(context.pass_spacing_m, project.planting.pass_spacing_m)
        self.assertLess(context.work_shape.area, Polygon(field[0][0]).area)
        self.assertEqual(context.anchor, (0.0, 120.0))
        self.assertAlmostEqual(context.ab_azimuth_deg, 90.0)
        self.assertEqual(context.ab_path, ((0.0, 120.0), (400.0, 120.0)))

    def test_build_field_context_errors(self):
        field = rectangle(400, 240)
        project = project_for(field, field_id="TL-13", ab=((0.0, 120.0), (400.0, 120.0)))
        with self.assertRaises(StrategyAnalysisError) as raised:
            build_field_context(dataclasses.replace(project, planting=None))
        self.assertEqual(raised.exception.code, STRATEGY_ANALYSIS_NO_OPERATION)
        empty = context_for([])
        with self.assertRaises(StrategyAnalysisError) as raised:
            empty.validate()
        self.assertEqual(raised.exception.code, STRATEGY_ANALYSIS_NO_BOUNDARY)

    def test_multi_field_analysis_uses_only_selected_field(self):
        tl12 = rectangle(300, 300, x=0.0, y=0.0)
        tl13 = rectangle(500, 200, x=5000.0, y=5000.0)
        project_13 = project_for(tl13, field_id="TL-13", ab=((5000.0, 5100.0), (5500.0, 5100.0)))
        context = build_field_context(project_13)
        result = LineStrategyAnalyzer().analyze(context, fast_config())
        tl12_shape = Polygon(tl12[0][0]).buffer(100.0)
        self.assertGreater(len(result.candidates), 0)
        for candidate in result.candidates:
            for line in candidate.lines:
                self.assertFalse(LineString(line.points).intersects(tl12_shape))
                self.assertTrue(all(x >= 4900.0 and y >= 4900.0 for x, y in line.points))


if __name__ == "__main__":
    unittest.main()
