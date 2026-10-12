import unittest

from plugin.fortsmart_precision.core.line_geometry import circle_ring_polygon
from plugin.fortsmart_precision.core.planting_line_cut_engine import (
    PlantingLineCutError,
    calculate_safety_radius,
    cut_polyline_by_zones,
    derived_cut_layer_names,
    is_obstacle_layer_name,
    is_safety_zone_layer_name,
)


class PlantingLineCutEngineTest(unittest.TestCase):
    def test_output_names_are_derived_without_repeated_suffix(self):
        self.assertEqual(
            derived_cut_layer_names("Plantio 18 m", "Postes"),
            ("Plantio 18 m - corte", "Postes - zona de corte"),
        )
        self.assertEqual(
            derived_cut_layer_names("Plantio 18 m - corte", "Postes - zona de corte"),
            ("Plantio 18 m - corte", "Postes - zona de corte"),
        )

    def test_flag_uuid_layer_is_detected(self):
        self.assertTrue(is_obstacle_layer_name("Flag{8f47-1234}"))
        self.assertTrue(is_obstacle_layer_name("Obstáculo_postes"))
        self.assertFalse(is_obstacle_layer_name("Boundary — talhao_11"))

    def test_expanded_safety_zones_are_not_accepted_as_obstacles(self):
        self.assertTrue(is_safety_zone_layer_name("_fortsmart_workspace_10_Zonas_Seguranca (4)"))
        self.assertTrue(is_safety_zone_layer_name("_fortsmart_workspace_11_Desvios_Obstaculos"))
        self.assertTrue(is_safety_zone_layer_name("Postes - zona de corte"))
        self.assertFalse(is_safety_zone_layer_name("_fortsmart_workspace_09_Obstaculos_RTK (4)"))
        self.assertFalse(is_safety_zone_layer_name("Flag{8f47-1234}"))

    def test_manual_radius_is_used_as_informed(self):
        self.assertEqual(calculate_safety_radius(method="manual", manual_radius_m=10), 10)

    def test_half_width_plus_margin(self):
        self.assertEqual(
            calculate_safety_radius(
                method="half_width_margin", implement_width_m=10, safety_margin_m=1
            ),
            6,
        )

    def test_half_width_plus_obstacle_radius_plus_margin(self):
        self.assertEqual(
            calculate_safety_radius(
                method="half_width_margin",
                implement_width_m=20,
                safety_margin_m=1,
                obstacle_radius_m=0.5,
            ),
            11.5,
        )

    def test_manual_radius_ignores_width_and_obstacle_radius(self):
        self.assertEqual(
            calculate_safety_radius(
                method="manual",
                manual_radius_m=7,
                implement_width_m=20,
                obstacle_radius_m=3,
            ),
            7,
        )

    def test_negative_obstacle_radius_is_rejected(self):
        with self.assertRaises(PlantingLineCutError):
            calculate_safety_radius(
                method="half_width_margin", implement_width_m=20, obstacle_radius_m=-1
            )

    def test_invalid_width_is_rejected(self):
        with self.assertRaises(PlantingLineCutError):
            calculate_safety_radius(method="half_width_margin", implement_width_m=0)

    def test_one_post_splits_line_in_two_aligned_segments(self):
        zone = circle_ring_polygon((50, 0), 10, segments=64)
        result = cut_polyline_by_zones(
            [(0, 0), (100, 0)], [zone], source_id="L001", densify_m=0.05
        )
        self.assertEqual(len(result), 2)
        self.assertTrue(all(item.obstacle_cut for item in result))
        self.assertTrue(all(all(abs(p[1]) < 1e-9 for p in item.path_points) for item in result))
        self.assertLessEqual(result[0].path_points[-1][0], 40.1)
        self.assertGreaterEqual(result[1].path_points[0][0], 59.9)

    def test_line_without_hit_remains_identical(self):
        zone = circle_ring_polygon((50, 20), 5, segments=48)
        result = cut_polyline_by_zones([(0, 0), (100, 0)], [zone], source_id="L002")
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0].obstacle_cut)
        self.assertEqual(result[0].path_points, ((0, 0), (100, 0)))

    def test_three_posts_create_multiple_safe_segments(self):
        zones = [circle_ring_polygon((x, 0), 3, segments=48) for x in (20, 50, 80)]
        result = cut_polyline_by_zones(
            [(0, 0), (100, 0)], zones, source_id="L003", obstacle_count=3
        )
        self.assertEqual(len(result), 4)
        self.assertTrue(all(item.obstacle_count == 3 for item in result))

    def test_overlapping_zones_do_not_duplicate_segments(self):
        zones = [
            circle_ring_polygon((48, 0), 6, segments=48),
            circle_ring_polygon((52, 0), 6, segments=48),
        ]
        result = cut_polyline_by_zones([(0, 0), (100, 0)], zones, source_id="L004")
        self.assertEqual(len(result), 2)

    def test_cut_preserves_curved_source_vertices(self):
        source = [(0, 0), (20, 3), (40, 9), (60, 18), (80, 30), (100, 45)]
        zone = circle_ring_polygon((50, 13.5), 7, segments=64)
        result = cut_polyline_by_zones(source, [zone], source_id="CURVA")
        self.assertEqual(len(result), 2)
        retained = {point for segment in result for point in segment.path_points}
        self.assertIn(source[1], retained)
        self.assertIn(source[-2], retained)
        source_edges = list(zip(source, source[1:]))
        for segment in result:
            for point in segment.path_points:
                self.assertTrue(
                    point in source
                    or any(self._point_on_segment(point, a, b) for a, b in source_edges)
                )

    def test_field_of_parallel_passes_is_cut_only_where_posts_are(self):
        radius = calculate_safety_radius(
            method="half_width_margin",
            implement_width_m=20,
            safety_margin_m=0.5,
            obstacle_radius_m=1.0,
        )
        posts = [(300.0, 100.0), (700.0, 240.0), (500.0, 400.0)]
        zones = [circle_ring_polygon(post, radius, segments=96) for post in posts]
        passes = [[(0.0, 20.0 * k), (1000.0, 20.0 * k)] for k in range(1, 24)]
        for index, line in enumerate(passes, start=1):
            y = line[0][1]
            hits = [post for post in posts if abs(post[1] - y) < radius]
            result = cut_polyline_by_zones(
                line, zones, source_id=f"P{index}", densify_m=0.2,
                obstacle_count=len(hits),
            )
            if not hits:
                self.assertEqual(len(result), 1)
                self.assertFalse(result[0].obstacle_cut)
                continue
            self.assertEqual(len(result), len(hits) + 1, f"P{index}")
            for segment in result:
                self.assertTrue(segment.obstacle_cut)
                for x, py in segment.path_points:
                    self.assertAlmostEqual(py, y, places=9)
                    for cx, cy in posts:
                        distance = ((x - cx) ** 2 + (py - cy) ** 2) ** 0.5
                        self.assertGreaterEqual(distance, radius - 0.01)

    @staticmethod
    def _point_on_segment(point, a, b, tolerance=1e-7):
        cross = (point[0] - a[0]) * (b[1] - a[1]) - (point[1] - a[1]) * (
            b[0] - a[0]
        )
        if abs(cross) > tolerance:
            return False
        return (
            min(a[0], b[0]) - tolerance <= point[0] <= max(a[0], b[0]) + tolerance
            and min(a[1], b[1]) - tolerance <= point[1] <= max(a[1], b[1]) + tolerance
        )


if __name__ == "__main__":
    unittest.main()
