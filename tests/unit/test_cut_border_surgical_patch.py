"""Patch cirurgico: corte + bordadura pela ultima linha ativa (12 testes do patch)."""

import unittest

from shapely.geometry import LineString, Point, box

from plugin.fortsmart_precision.core.longitudinal_cut_engine import (
    ObstacleInput,
    build_obstacle_zones,
    compute_longitudinal_cut,
    fill_closed_rings,
)
from plugin.fortsmart_precision.core.obstacle_border_pass_engine import (
    cut_work_line_records,
    preview_footer_lines,
    preview_footer_status,
    simulate_obstacle_cut,
)
from plugin.fortsmart_precision.core.planting_line_cut_engine import (
    BOUNDARY_AS_OBSTACLE_MESSAGE,
    GEOMETRY_INCOMPLETE,
    OFFSET_MISSING_MESSAGE,
    READY,
    SAME_LAYER_MESSAGE,
    PlantingLineCutError,
    classify_transversal_clearance,
    cut_preview_readiness,
    is_field_boundary_layer_name,
    machine_schematic_layout,
    obstacle_layer_priority,
    validate_obstacle_layer_choice,
)
from plugin.fortsmart_precision.core.operation_simulator import SimulationStatus
from plugin.fortsmart_precision.domain.operation_simulation import (
    MachineReferenceType,
    MachineWorkGeometry,
    ObstacleBorderMode,
    ObstacleStrategy,
    WorkState,
)

CRS = "EPSG:31981"


def machine(width=20.0, offset=-18.0, mode=ObstacleBorderMode.ONE_IMPLEMENT_PASS, **kwargs):
    return MachineWorkGeometry(
        work_width_m=width,
        reference_type=MachineReferenceType.GNSS_ANTENNA,
        reference_to_working_line_longitudinal_m=offset,
        border_mode=mode,
        **kwargs,
    )


class BorderWidthTest(unittest.TestCase):
    def test_01_width_20_offset_minus_18_one_pass_border_20(self):
        self.assertEqual(machine(20.0, -18.0).desired_border_width_m(), 20.0)

    def test_02_width_15_border_15(self):
        self.assertEqual(machine(15.0, -18.0).desired_border_width_m(), 15.0)

    def test_custom_border_uses_its_own_field(self):
        geometry = machine(mode=ObstacleBorderMode.CUSTOM, obstacle_border_width_m=7.5)
        self.assertEqual(geometry.desired_border_width_m(), 7.5)


class PreviewReadinessTest(unittest.TestCase):
    def test_03_missing_offset_blocks_longitudinal_preview(self):
        status, message = cut_preview_readiness(longitudinal=True, working_offset_m=None)
        self.assertEqual(status, GEOMETRY_INCOMPLETE)
        self.assertEqual(message, OFFSET_MISSING_MESSAGE)

    def test_valid_offset_clears_status(self):
        self.assertEqual(cut_preview_readiness(longitudinal=True, working_offset_m=-18.0), (READY, ""))

    def test_radial_strategy_does_not_require_offset(self):
        self.assertEqual(cut_preview_readiness(longitudinal=False, working_offset_m=None), (READY, ""))

    def test_missing_offset_engine_refuses_simulation(self):
        with self.assertRaises(ValueError):
            simulate_obstacle_cut(
                [("L1", [(0, 0), (300, 0)])], [ObstacleInput("P1", Point(150, 0), 0.5)],
                MachineWorkGeometry(work_width_m=20.0), crs_authid=CRS,
            )


class SchematicTest(unittest.TestCase):
    def layout(self, offset):
        return machine_schematic_layout(
            working_offset_m=offset, work_width_m=20.0, width_px=400.0, height_px=160.0
        )

    def test_04_negative_offset_draws_bar_behind(self):
        data = self.layout(-18.0)
        self.assertEqual(data["position"], "behind")
        self.assertGreater(data["bar"][1], data["gnss"][1])  # sentido para cima: atras = abaixo

    def test_05_positive_offset_draws_bar_ahead(self):
        data = self.layout(18.0)
        self.assertEqual(data["position"], "ahead")
        self.assertLess(data["bar"][1], data["gnss"][1])

    def test_missing_offset_has_no_bar(self):
        data = self.layout(None)
        self.assertFalse(data["complete"])
        self.assertIsNone(data["bar"])


class ReversedPassTest(unittest.TestCase):
    def test_06_reversed_pass_keeps_physical_gap(self):
        zones = build_obstacle_zones([ObstacleInput("P1", Point(150, 0), 0.5)], 0.5)
        geometry = machine(20.0, -18.0)
        forward = compute_longitudinal_cut("F", [(0, 0), (300, 0)], zones, geometry)
        backward = compute_longitudinal_cut("B", [(300, 0), (0, 0)], zones, geometry)
        for result in (forward, backward):
            raised = [i for i in result.intervals if i.state is WorkState.RAISED]
            self.assertEqual(len(raised), 1)
            xs = [p[0] for p in raised[0].working_points]
            # fisico: a barra levanta so enquanto encosta na zona (raio 0,5 + margem 0,5)
            self.assertAlmostEqual(min(xs), 150 - 1, delta=0.06)
            self.assertAlmostEqual(max(xs), 150 + 1, delta=0.06)
            for item in result.events:
                self.assertAlmostEqual(item.measured_distance_m, 0.0, delta=0.05)


class ObstacleLayerChoiceTest(unittest.TestCase):
    def test_07_boundary_as_obstacle_is_rejected(self):
        self.assertIsNone(obstacle_layer_priority("Boundary - talhao_11"))
        self.assertTrue(is_field_boundary_layer_name("Boundary"))
        self.assertEqual(
            validate_obstacle_layer_choice(
                obstacle_layer_id="b2", obstacle_layer_name="Boundary - talhao_11",
                field_layer_id="f1", geometry_kind="polygon",
            ),
            BOUNDARY_AS_OBSTACLE_MESSAGE,
        )

    def test_same_layer_as_field_is_rejected(self):
        self.assertEqual(
            validate_obstacle_layer_choice(
                obstacle_layer_id="f1", obstacle_layer_name="qualquer", field_layer_id="f1",
                geometry_kind="polygon",
            ),
            SAME_LAYER_MESSAGE,
        )

    def test_08_flag_uuid_is_recognized_with_top_priority(self):
        name = "Flag{3f2a9c1e-77b4-4d1e-9a0b-6f5e4d3c2b1a}"
        self.assertEqual(obstacle_layer_priority(name), 0)
        self.assertEqual(obstacle_layer_priority("Flag"), 1)
        self.assertEqual(obstacle_layer_priority("Poste"), 2)
        for other in ("Obstacle", "Obstaculo", "Obstáculo"):
            self.assertEqual(obstacle_layer_priority(other), 3)
        self.assertIsNone(obstacle_layer_priority("06_Passadas_Plantio"))
        self.assertIsNone(
            validate_obstacle_layer_choice(
                obstacle_layer_id="o1", obstacle_layer_name=name, field_layer_id="f1",
                geometry_kind="point",
            )
        )


class TransversalTest(unittest.TestCase):
    def test_09_centerline_misses_post_but_half_width_touches(self):
        self.assertEqual(
            classify_transversal_clearance(lateral_distance_m=8.0, implement_width_m=20.0),
            "CONFLICT",
        )
        self.assertEqual(
            classify_transversal_clearance(lateral_distance_m=12.0, implement_width_m=20.0),
            "CLEAR",
        )
        zones = build_obstacle_zones([ObstacleInput("P1", Point(150, 8), 0.5)], 0.5)
        result = compute_longitudinal_cut("L1", [(0, 0), (300, 0)], zones, machine())
        self.assertTrue(result.affected)

    def test_transversal_rejects_invalid_width(self):
        with self.assertRaises(PlantingLineCutError):
            classify_transversal_clearance(lateral_distance_m=1.0, implement_width_m=0.0)


class CutAndBorderTest(unittest.TestCase):
    def test_10_machine_path_continuous_work_layer_cut(self):
        sim = simulate_obstacle_cut(
            [("L1", [(0, 0), (300, 0)])], [ObstacleInput("P1", Point(150, 0), 0.5)],
            machine(), crs_authid=CRS, safety_margin_m=0.5,
        )
        item = sim.passes[0]
        self.assertEqual(item.reference_path, ((0.0, 0.0), (300.0, 0.0)))
        self.assertEqual([e.event_type for e in item.events], ["WORK_OFF", "WORK_ON"])
        (record,) = cut_work_line_records(sim)
        self.assertTrue(record["affected"])
        first, second = record["segments"]
        self.assertEqual(first[0], (0.0, 0.0))
        self.assertEqual(second[-1], (300.0, 0.0))
        gap_start = max(p[0] for p in first)
        gap_end = min(p[0] for p in second)
        self.assertAlmostEqual(gap_start, 149.0, delta=0.06)
        self.assertAlmostEqual(gap_end, 151.0, delta=0.06)

    def test_11_border_gap_is_warning(self):
        sim = simulate_obstacle_cut(
            [("L1", [(0, 0), (300, 0)])], [ObstacleInput("P1", Point(150, 0), 0.5)],
            machine(longitudinal_anticipation_m=25.0), crs_authid=CRS, safety_margin_m=0.5,
        )
        self.assertIn("BORDER_GAP", sim.border_passes[0].issues)
        self.assertIn(preview_footer_status(sim.report), ("WARNING", "INVALID"))
        self.assertLess(sim.report["border_coverage_pct"], 100.0)

    def test_12_border_around_large_obstacle_has_no_gap_and_measures_overlap(self):
        obstacle = ObstacleInput("P1", box(140, -10, 160, 10), 0.0)
        sim = simulate_obstacle_cut(
            [("L1", [(0, 0), (300, 0)])], [obstacle], machine(), crs_authid=CRS,
            safety_margin_m=0.0,
        )
        # a linha trabalha ate encostar no obstaculo; a faixa de contorno sobrepoe esse trecho
        self.assertEqual(sim.report["warnings"], ["FINAL_OVERLAP"])
        self.assertEqual(preview_footer_status(sim.report), "WARNING")
        self.assertLess(sim.final_gap.area, 0.01)
        self.assertNotIn("BORDER_GAP", sim.border_passes[0].issues)
        (record,) = cut_work_line_records(sim)
        self.assertAlmostEqual(record["gaps"][0][0], 140.0, delta=0.06)
        self.assertAlmostEqual(record["gaps"][0][1], 160.0, delta=0.06)


class FooterAndRingsTest(unittest.TestCase):
    def test_footer_lists_required_items(self):
        sim = simulate_obstacle_cut(
            [("L1", [(0, 0), (300, 0)])], [ObstacleInput("P1", Point(150, 0), 0.5)],
            machine(), crs_authid=CRS, safety_margin_m=0.5,
        )
        text = " | ".join(preview_footer_lines(sim.report))
        for label in ("Implemento: 20,00 m", "Offset ultima linha: -18,00 m", "Bordadura: 20,00 m",
                      "Seguranca obstaculo: 1,00 m", "Antecipacao: 0,00 m", "Corte longitudinal: ate 2,0",
                      "WORK_OFF: OK", "WORK_ON: OK",
                      "Cobertura da bordadura:", "Falha:", "Sobreposicao:", "Status:"):
            self.assertIn(label, text)

    def test_closed_ring_obstacle_is_filled(self):
        ring = Point(0, 0).buffer(1.0).exterior
        filled = fill_closed_rings(LineString(ring.coords))
        self.assertEqual(filled.geom_type, "Polygon")
        self.assertGreater(filled.area, 3.0)
        open_line = LineString([(0, 0), (1, 0)])
        self.assertIs(fill_closed_rings(open_line), open_line)

    def test_strategy_cut_only_skips_border(self):
        sim = simulate_obstacle_cut(
            [("L1", [(0, 0), (300, 0)])], [ObstacleInput("P1", Point(150, 0), 0.5)],
            machine(), crs_authid=CRS, safety_margin_m=0.5, strategy=ObstacleStrategy.CUT_ONLY,
        )
        self.assertEqual(sim.border_passes, ())
        self.assertIsNone(sim.report["border_coverage_pct"])


if __name__ == "__main__":
    unittest.main()
