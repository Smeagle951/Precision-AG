import math
import unittest

from shapely.geometry import GeometryCollection, LineString, Point, Polygon, box

from plugin.fortsmart_precision.core.longitudinal_cut_engine import (
    WORK_OFF,
    WORK_ON,
    LongitudinalCutError,
    ObstacleInput,
    _ReferencePath,
    build_obstacle_zones,
    compute_longitudinal_cut,
    working_bar,
    working_element_pose,
)
from plugin.fortsmart_precision.core.obstacle_border_pass_engine import (
    cluster_zones,
    machine_schematic_text,
    polygonal_mask,
    polygonal_part,
    simulate_obstacle_cut,
    work_event_records,
)
from plugin.fortsmart_precision.core.operation_simulator import SimulationStatus
from plugin.fortsmart_precision.domain.operation_simulation import (
    MachineReferenceType,
    MachineWorkGeometry,
    ObstacleBorderMode,
    ObstacleStrategy,
    WorkGeometryStatus,
    WorkState,
)

CRS = "EPSG:31981"
TOL = 0.05


def machine(width=20.0, offset=-18.0, mode=ObstacleBorderMode.ONE_IMPLEMENT_PASS, **kwargs):
    return MachineWorkGeometry(
        work_width_m=width,
        reference_type=kwargs.pop("reference_type", MachineReferenceType.HITCH_PIN),
        reference_to_working_line_longitudinal_m=offset,
        border_mode=mode,
        **kwargs,
    )


def post(x=150.0, y=0.0, oid="P1", radius=0.5):
    return ObstacleInput(oid, Point(x, y), physical_radius_m=radius)


def cut(points, obstacles, geometry, margin=0.5, pass_id="L1"):
    zones = build_obstacle_zones(obstacles, margin)
    return compute_longitudinal_cut(pass_id, points, zones, geometry, tolerance_m=TOL)


def event(result, kind):
    return next(item for item in result.events if item.event_type == kind)


class MachineWorkGeometryTest(unittest.TestCase):
    def test_one_implement_pass_uses_effective_width(self):
        self.assertEqual(machine(width=15.0).desired_border_width_m(), 15.0)  # TEST 04

    def test_custom_border_is_not_width(self):
        geometry = machine(mode=ObstacleBorderMode.CUSTOM, obstacle_border_width_m=10.0)
        self.assertEqual(geometry.desired_border_width_m(), 10.0)  # TEST 06

    def test_cut_distance_is_only_the_longitudinal_margin(self):
        for mode in ObstacleBorderMode:
            geometry = machine(mode=mode, obstacle_border_width_m=10.0, safety_margin_longitudinal_m=1.5)
            self.assertEqual(geometry.required_cut_distance_m(), 1.5)
        self.assertEqual(machine().required_cut_distance_m(), 0.0)

    def test_negative_anticipation_is_rejected(self):
        with self.assertRaises(ValueError):
            machine(longitudinal_anticipation_m=-1.0).validate()

    def test_missing_working_offset_is_geometry_incomplete(self):
        geometry = MachineWorkGeometry(work_width_m=20.0)
        self.assertIs(geometry.status, WorkGeometryStatus.GEOMETRY_INCOMPLETE)
        with self.assertRaises(LongitudinalCutError):
            cut([(0, 0), (300, 0)], [post()], geometry)

    def test_custom_border_without_width_is_rejected(self):
        with self.assertRaises(ValueError):
            machine(mode=ObstacleBorderMode.CUSTOM).validate()

    def test_lateral_offset_is_relative_to_reference(self):
        geometry = machine(reference_lateral_offset_m=0.5, implement_lateral_offset_m=0.2)
        self.assertAlmostEqual(geometry.working_lateral_offset_m, -0.3)


class ObstacleZoneTest(unittest.TestCase):
    def test_zones_add_radius_then_margin(self):
        zone = build_obstacle_zones([post(radius=0.5)], 0.5)[0]
        self.assertAlmostEqual(zone.safety_zone.distance(Point(151.0, 0)), 0.0, places=3)
        self.assertGreater(zone.safety_zone.distance(Point(151.05, 0)), 0.0)

    def test_point_without_radius_or_margin_is_rejected(self):
        with self.assertRaises(LongitudinalCutError):
            build_obstacle_zones([post(radius=0.0)], 0.0)

    def test_point_without_radius_is_allowed_by_explicit_machine_lateral_margin(self):
        simulation = simulate_obstacle_cut(
            [("P1", [(0.0, 0.0), (300.0, 0.0)])],
            [post(radius=0.0)],
            machine(
                width=10.0,
                offset=0.0,
                mode=ObstacleBorderMode.NONE,
                safety_margin_lateral_m=0.5,
            ),
            crs_authid=CRS,
            field_polygon=box(-50, -100, 350, 100),
            safety_margin_m=0.0,
            strategy=ObstacleStrategy.CUT_ONLY,
        )

        self.assertEqual(simulation.zones[0].safety_zone.geom_type, "Point")
        self.assertTrue(simulation.passes[0].affected)
        self.assertEqual(simulation.report["machine_geometry"]["safety_margin_lateral_m"], 0.5)
        self.assertEqual(simulation.report["obstacle_safety_m"], 0.0)

    def test_zero_area_obstacles_never_enter_area_overlay_mask(self):
        mask = polygonal_mask(GeometryCollection([Point(0, 0), LineString([(0, 0), (1, 0)])]))
        self.assertTrue(mask.is_empty)
        self.assertEqual(mask.geom_type, "Polygon")

        simulation = simulate_obstacle_cut(
            [("P1", [(0.0, 0.0), (300.0, 0.0)])],
            [
                post(x=140.0, radius=0.0, oid="P1"),
                ObstacleInput("L1", LineString([(160.0, -1.0), (160.0, 1.0)])),
            ],
            machine(
                width=10.0,
                offset=0.0,
                mode=ObstacleBorderMode.NONE,
                safety_margin_lateral_m=0.5,
            ),
            crs_authid=CRS,
            field_polygon=box(-50, -100, 350, 100),
            safety_margin_m=0.0,
            strategy=ObstacleStrategy.CUT_ONLY,
        )
        self.assertTrue(simulation.passes[0].affected)
        self.assertEqual(simulation.report["obstacle_count"], 2)

    def test_negative_values_are_rejected(self):
        with self.assertRaises(LongitudinalCutError):
            build_obstacle_zones([post()], -1)
        with self.assertRaises(LongitudinalCutError):
            build_obstacle_zones([post(radius=-1)], 0.5)


class WorkingElementPoseTest(unittest.TestCase):
    def test_rear_bar_is_behind_reference_along_local_tangent(self):
        path = _ReferencePath([(0, 0), (100, 0)])
        reference, center, tangent = working_element_pose(path, 50, machine())
        self.assertEqual(reference, (50.0, 0.0))
        self.assertAlmostEqual(center[0], 32.0)
        self.assertEqual(tangent, (1.0, 0.0))
        bar = working_bar(path, 50, machine())
        self.assertAlmostEqual(bar.length, 20.0)

    def test_curved_path_follows_local_tangent_not_global_axis(self):  # TEST 09
        arc = [(100 * math.sin(a / 100), 100 - 100 * math.cos(a / 100)) for a in range(0, 158)]
        path = _ReferencePath(arc)
        station = 120.0
        reference, center, (tx, ty) = working_element_pose(path, station, machine())
        self.assertAlmostEqual(center[0], reference[0] - 18 * tx, places=6)
        self.assertAlmostEqual(center[1], reference[1] - 18 * ty, places=6)
        self.assertGreater(abs(center[1] - reference[1]), 10.0)


class LongitudinalCutStraightTest(unittest.TestCase):
    LINE = [(0.0, 0.0), (300.0, 0.0)]

    def test_01_work_off_when_active_line_reaches_safety_zone(self):
        result = cut(self.LINE, [post()], machine())
        off = event(result, WORK_OFF)
        self.assertAlmostEqual(off.measured_distance_m, 0.0, delta=TOL)
        self.assertAlmostEqual(off.working_xy[0], 150 - 1, delta=TOL)
        # sanity check analitico (linha reta): s = x0 - zona - offset
        self.assertAlmostEqual(off.station_m, 150 - 1 - (-18), delta=TOL)

    def test_02_work_on_when_active_line_leaves_safety_zone(self):
        result = cut(self.LINE, [post()], machine())
        on = event(result, WORK_ON)
        self.assertAlmostEqual(on.measured_distance_m, 0.0, delta=TOL)
        self.assertAlmostEqual(on.working_xy[0], 150 + 1, delta=TOL)
        self.assertAlmostEqual(on.station_m, 150 + 1 + 18, delta=TOL)

    def test_03_reverse_direction_leaves_same_physical_gap(self):
        forward = cut(self.LINE, [post()], machine())
        backward = cut(list(reversed(self.LINE)), [post()], machine())
        f_bounds = forward.unworked_area.bounds
        b_bounds = backward.unworked_area.bounds
        for a, b in zip(f_bounds, b_bounds):
            self.assertAlmostEqual(a, b, delta=TOL)
        self.assertAlmostEqual(event(backward, WORK_OFF).working_xy[0], 151.0, delta=TOL)
        self.assertAlmostEqual(event(backward, WORK_ON).working_xy[0], 149.0, delta=TOL)

    def test_05_other_width_and_offset_keep_ground_cut(self):
        result = cut(self.LINE, [post()], machine(width=18.0, offset=-12.0))
        off = event(result, WORK_OFF)
        self.assertAlmostEqual(off.measured_distance_m, 0.0, delta=TOL)
        self.assertAlmostEqual(off.working_xy[0], 149.0, delta=TOL)
        self.assertAlmostEqual(off.station_m, 150 - 1 + 12, delta=TOL)

    def test_06_custom_border_does_not_change_cut(self):
        geometry = machine(mode=ObstacleBorderMode.CUSTOM, obstacle_border_width_m=10.0)
        off = event(cut(self.LINE, [post()], geometry), WORK_OFF)
        self.assertAlmostEqual(off.measured_distance_m, 0.0, delta=TOL)
        self.assertAlmostEqual(off.working_xy[0], 149.0, delta=TOL)

    def test_07_displaced_gnss_is_corrected_by_offset(self):
        hitch = cut(self.LINE, [post()], machine(offset=-18.0))
        gnss_geometry = machine(
            offset=-21.0,
            reference_type=MachineReferenceType.GNSS_ANTENNA,
            reference_lateral_offset_m=0.5,
        )
        gnss_line = [(0.0, -0.5), (300.0, -0.5)]
        gnss = cut(gnss_line, [post()], gnss_geometry)
        h_off, g_off = event(hitch, WORK_OFF), event(gnss, WORK_OFF)
        self.assertAlmostEqual(g_off.working_xy[0], h_off.working_xy[0], delta=TOL)
        self.assertAlmostEqual(g_off.working_xy[1], 0.0, delta=1e-6)
        self.assertAlmostEqual(g_off.station_m - h_off.station_m, 3.0, delta=TOL)

    def test_08_front_implement_positive_offset(self):
        result = cut(self.LINE, [post()], machine(offset=3.0))
        off = event(result, WORK_OFF)
        self.assertAlmostEqual(off.measured_distance_m, 0.0, delta=TOL)
        self.assertAlmostEqual(off.station_m, 150 - 1 - 3, delta=TOL)
        self.assertGreater(off.working_xy[0], off.reference_xy[0])

    def test_10_polygon_distance_uses_zone_not_centroid(self):
        square = ObstacleInput("Q", box(148, -2, 152, 2), physical_radius_m=0.0)
        off = event(cut(self.LINE, [square], machine()), WORK_OFF)
        self.assertAlmostEqual(off.working_xy[0], 148 - 0.5, delta=TOL)

    def test_lateral_obstacle_outside_pass_strip_does_not_cut(self):
        result = cut(self.LINE, [post(y=12.0)], machine())
        self.assertFalse(result.affected)
        self.assertEqual(result.events, ())

    def test_lateral_safety_margin_widens_corridor(self):
        result = cut(self.LINE, [post(y=11.5)], machine(safety_margin_lateral_m=1.0))
        self.assertTrue(result.affected)

    def test_trajectory_stays_continuous(self):
        result = cut(self.LINE, [post()], machine())
        states = [item.state for item in result.intervals]
        self.assertEqual(states, [WorkState.WORKING, WorkState.RAISED, WorkState.WORKING])
        self.assertAlmostEqual(result.intervals[0].end_station_m, result.intervals[1].start_station_m)
        self.assertAlmostEqual(result.intervals[-1].end_station_m, 300.0)
        self.assertEqual(result.reference_path, ((0.0, 0.0), (300.0, 0.0)))


class LongitudinalCutCurveTest(unittest.TestCase):
    def test_09_curve_event_respects_physical_border(self):
        arc = [(200 * math.sin(a / 200), 200 - 200 * math.cos(a / 200)) for a in range(0, 401)]
        mid = arc[200]
        result = cut(arc, [post(x=mid[0], y=mid[1])], machine())
        for kind in (WORK_OFF, WORK_ON):
            self.assertAlmostEqual(event(result, kind).measured_distance_m, 0.0, delta=TOL)

    def test_curve_anticipation_moves_work_off_along_the_pass(self):
        arc = [(200 * math.sin(a / 200), 200 - 200 * math.cos(a / 200)) for a in range(0, 401)]
        mid = arc[200]
        base = cut(arc, [post(x=mid[0], y=mid[1])], machine())
        early = cut(arc, [post(x=mid[0], y=mid[1])], machine(longitudinal_anticipation_m=2.0))
        self.assertAlmostEqual(event(base, WORK_OFF).station_m - event(early, WORK_OFF).station_m, 2.0, delta=1e-6)
        self.assertAlmostEqual(event(early, WORK_OFF).measured_distance_m, 2.0, delta=TOL)
        self.assertAlmostEqual(event(base, WORK_ON).station_m, event(early, WORK_ON).station_m, delta=1e-6)


def _golden(**kwargs):
    return simulate_obstacle_cut(
        [("P1", [(0.0, 0.0), (300.0, 0.0)])],
        kwargs.pop("obstacles", [post()]),
        kwargs.pop("geometry", machine()),
        crs_authid=CRS,
        field_polygon=kwargs.pop("field", box(-50, -100, 350, 100)),
        safety_margin_m=0.5,
        **kwargs,
    )


class BorderPassTest(unittest.TestCase):
    def test_11_single_border_pass_covers_small_border(self):
        geometry = machine(mode=ObstacleBorderMode.CUSTOM, obstacle_border_width_m=10.0)
        sim = _golden(geometry=geometry)
        border = sim.border_passes[0]
        self.assertLess(border.gap_area.area, 0.01)
        self.assertNotIn("BORDER_GAP", border.issues)
        self.assertLess(sim.final_gap.area, 0.01)

    def test_12_insufficient_single_pass_is_warning_not_perfect(self):
        sim = _golden(geometry=machine(longitudinal_anticipation_m=25.0))
        border = sim.border_passes[0]
        self.assertIn("BORDER_GAP", border.issues)
        self.assertGreater(border.gap_area.area, 1.0)
        self.assertIsNot(sim.status, SimulationStatus.VALID)
        self.assertIn("FINAL_GAP", sim.warnings)

    def test_13_border_colliding_with_post_is_invalid(self):
        sim = _golden(obstacles=[post(), post(x=165.0, oid="P2")], group_obstacles=False)
        self.assertIs(sim.status, SimulationStatus.INVALID)
        self.assertTrue(any("BORDER_COLLISION" in item for item in sim.errors))

    def test_14_border_leaving_field_is_invalid(self):
        sim = _golden(field=box(-50, -15, 350, 100))
        self.assertIs(sim.status, SimulationStatus.INVALID)
        self.assertIn("BORDER_OUTSIDE_FIELD", sim.border_passes[0].issues)

    def test_15_close_posts_are_grouped_before_border(self):
        sim = _golden(obstacles=[post(), post(x=165.0, oid="P2")])
        self.assertEqual(len(sim.border_passes), 1)
        self.assertEqual(set(sim.border_passes[0].obstacle_ids), {"P1", "P2"})
        self.assertNotIn("BORDER_COLLISION", sim.border_passes[0].issues)

    def test_cluster_link_distance(self):
        zones = build_obstacle_zones([post(), post(x=190.0, oid="P2")], 0.5)
        self.assertEqual(len(cluster_zones(zones, 20.0)), 2)
        self.assertEqual(len(cluster_zones(zones, 40.0)), 1)

    def test_turn_radius_warning(self):
        sim = _golden(geometry=machine(min_turn_radius_m=15.0))
        self.assertIn("BORDER_TURN_RADIUS", sim.border_passes[0].issues)


class GoldenScenarioTest(unittest.TestCase):
    """20 m, ultima linha 18 m atras, bordadura de 1 passada (faixa lateral), poste r=0,5 + 0,5."""

    def test_golden_example(self):
        sim = _golden()
        item = sim.passes[0]
        off, on = event(item, WORK_OFF), event(item, WORK_ON)
        self.assertAlmostEqual(off.station_m, 167.0, delta=TOL)
        self.assertAlmostEqual(on.station_m, 169.0, delta=TOL)
        self.assertAlmostEqual(off.working_xy[0], 149.0, delta=TOL)
        self.assertAlmostEqual(on.working_xy[0], 151.0, delta=TOL)
        zone_area = sim.zones[0].safety_zone.area
        self.assertAlmostEqual(sim.unworked_area.area, 20 * 2 - zone_area, delta=0.5)
        border = sim.border_passes[0]
        self.assertAlmostEqual(border.trajectory.length, 2 * math.pi * 11, delta=0.1)
        self.assertLess(sim.final_gap.area, 0.01)
        self.assertLess(border.gap_area.area, 0.01)
        report = sim.report
        self.assertEqual(report["passes"][0]["work_off_station"], [round(off.station_m, 4)])
        self.assertEqual(report["passes"][0]["cut_distance_m"], [round(on.station_m - off.station_m, 4)])
        self.assertFalse(report["original_layers_modified"])
        self.assertEqual(report["target_distance_m"], 0.0)
        self.assertAlmostEqual(report["max_cut_distance_m"], 2.0, delta=TOL)
        (detail,) = report["longitudinal_cuts"]
        self.assertEqual(detail["safety_zone_m"], 1.0)
        self.assertEqual(detail["working_width_m"], 20.0)
        self.assertEqual(detail["reference_to_operation_m"], -18.0)

    def test_cut_only_skips_border_and_reports_intentional_unworked(self):
        sim = _golden(strategy=ObstacleStrategy.CUT_ONLY)
        self.assertEqual(sim.border_passes, ())
        self.assertIn("UNWORKED_INTENTIONAL", sim.warnings)

    def test_contour_strategies_are_not_handled_here(self):
        for strategy in (ObstacleStrategy.AUTO, ObstacleStrategy.DIRECT_CONTOUR):
            with self.assertRaises(LongitudinalCutError):
                _golden(strategy=strategy)

    def test_cut_for_border_requires_border(self):
        with self.assertRaises(LongitudinalCutError):
            _golden(geometry=machine(mode=ObstacleBorderMode.NONE))

    def test_geographic_crs_is_rejected(self):
        with self.assertRaises(Exception):
            simulate_obstacle_cut(
                [("P1", [(0, 0), (1, 0)])], [post()], machine(), crs_authid="EPSG:4326"
            )

    def test_polygonal_part_drops_lines_and_points(self):
        mixed = GeometryCollection([box(0, 0, 1, 1), LineString([(5, 5), (6, 6)]), Point(9, 9)])
        self.assertAlmostEqual(polygonal_part(mixed).area, 1.0)
        self.assertIsNone(polygonal_part(LineString([(0, 0), (1, 1)])))
        self.assertIsNone(polygonal_part(Polygon()))

    def test_event_records_expose_inspection_data(self):
        sim = _golden()
        records = work_event_records(sim, TOL)
        self.assertEqual([r["event"] for r in records], [WORK_OFF, WORK_ON])
        for record in records:
            self.assertEqual(record["reference"], "HITCH_PIN")
            self.assertEqual(record["offset_long_m"], -18.0)
            self.assertEqual(record["border_target_m"], 0.0)
            self.assertTrue(record["within_tol"])
            self.assertEqual(record["obstacle_ids"], "P1")

    def test_schematic_shows_rear_bar_and_incomplete_profile(self):
        text = machine_schematic_text(machine())
        self.assertIn("18.00 m atras", text)
        self.assertIn("20.00 m", text)
        self.assertLess(text.index("REFERENCIA"), text.index("BARRA"))
        front = machine_schematic_text(machine(offset=3.0))
        self.assertLess(front.index("BARRA"), front.index("REFERENCIA"))
        incomplete = machine_schematic_text(MachineWorkGeometry(work_width_m=20.0))
        self.assertIn("GEOMETRY_INCOMPLETE", incomplete)

    def test_neighbour_pass_overlap_is_measured(self):
        sim = simulate_obstacle_cut(
            [("P1", [(0.0, 0.0), (300.0, 0.0)]), ("P2", [(300.0, 20.0), (0.0, 20.0)])],
            [post()],
            machine(),
            crs_authid=CRS,
            field_polygon=box(-50, -100, 350, 100),
            safety_margin_m=0.5,
        )
        self.assertFalse(sim.passes[1].affected)
        self.assertGreater(sim.border_passes[0].overlap_area.area, 1.0)
        self.assertIn("FINAL_OVERLAP", sim.warnings)


if __name__ == "__main__":
    unittest.main()
