# -*- coding: utf-8 -*-
"""Clip de linhas de plantio no limite operacional+extensao e shutoff no miolo."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.guidance_engine import TrafficPass
from plugin.fortsmart_precision.core.line_geometry import (
    Segment,
    build_processing_boundary,
    multipolygon_bbox,
    point_in_multipolygon,
)
from plugin.fortsmart_precision.core.planting_kinematics_engine import (
    generate_rows_from_tractor_paths,
    kinematics_from_planter,
)
from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
from plugin.fortsmart_precision.core.shutoff_engine import apply_row_shutoff
from plugin.fortsmart_precision.domain.avoidance_configuration import AvoidanceConfiguration, AvoidanceMode
from plugin.fortsmart_precision.domain.boundary_areas import build_inner_and_headland
from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, PlanterMachine, SprayerMachine
from plugin.fortsmart_precision.domain.planting_avoidance_configuration import (
    PlantingAvoidanceConfiguration,
)
from plugin.fortsmart_precision.domain.precision_project import (
    ABLine,
    FieldGeometry,
    PrecisionOperation,
    PrecisionProject,
)


def rectangle(width=200.0, height=120.0):
    outer = [(0.0, 0.0), (width, 0.0), (width, height), (0.0, height), (0.0, 0.0)]
    return [(outer, [])]


def planter() -> PlanterMachine:
    return PlanterMachine(
        machine_id="p18",
        name="P18",
        row_count=6,
        row_spacing_m=0.5,
        track=MachineTrack(track_width_m=2.0, tire_width_m=0.4),
        informed_operational_width_m=3.0,
    )


class PlantingClipExtensionTest(unittest.TestCase):
    def test_polyline_rows_clip_to_processing_boundary(self):
        """Linhas com path_points (curva) nao ultrapassam limite+extensao."""
        field = rectangle(100, 100)
        proc = build_processing_boundary(field, 10.0)
        # Polilinha que sai do processing.
        pts = [(-30.0, 50.0), (50.0, 50.0), (130.0, 50.0)]
        traffic = TrafficPass(
            pass_no=1,
            fs_id="p1",
            operation_id="planting",
            spacing_m=3.0,
            width_m=3.0,
            offset_m=0.0,
            azimuth_deg=90.0,
            direction="forward",
            clipped_segment=Segment(pts[0], pts[-1]),
            guidance_segment=Segment(pts[0], pts[-1]),
            path_points=tuple(pts),
        )
        rows = generate_rows_from_tractor_paths(
            [traffic],
            planter(),
            kinematics_from_planter(planter()),
            work_area=proc,
        )
        self.assertGreater(len(rows), 0)
        xmin, ymin, xmax, ymax = multipolygon_bbox(proc)
        for row in rows:
            for x, y in row.line_points():
                self.assertGreaterEqual(x, xmin - 1e-6)
                self.assertLessEqual(x, xmax + 1e-6)
                self.assertGreaterEqual(y, ymin - 1e-6)
                self.assertLessEqual(y, ymax + 1e-6)

    def test_curved_planting_passes_reach_external_margin_after_smoothing(self):
        field = rectangle(200, 120)
        curve = (
            (0.0, 60.0),
            (50.0, 63.0),
            (100.0, 70.0),
            (150.0, 66.0),
            (200.0, 60.0),
        )
        project = PrecisionProject(
            field=FieldGeometry(
                field_boundary=field,
                operational_boundary=field,
                crs_authid="EPSG:31981",
            ),
            ab_line=ABLine(start=curve[0], end=curve[-1], path_points=curve),
            planting=PrecisionOperation(
                operation_id="planting",
                machine=planter(),
                extension_m=20.0,
                headland=HeadlandLayout(
                    pass_count=2,
                    width_m=3.0,
                    effective_spacing_m=3.0,
                    mode="follow_boundary",
                ),
            ),
            planting_kinematics=kinematics_from_planter(planter()),
        )
        result = run_precision_lines(project)
        center = min(result.planting_passes, key=lambda item: abs(item.offset_m))
        xs = [point[0] for point in center.line_points()]
        self.assertLessEqual(min(xs), -19.5)
        self.assertGreaterEqual(max(xs), 219.5)


class HeadlandSeedShutoffTest(unittest.TestCase):
    def test_main_rows_off_outside_inner_work_area(self):
        """Miolo: semente LIGA so no inner; bordadura e fora = DESLIGA."""
        field = rectangle(200, 120)
        areas = build_inner_and_headland(field, 18.0)
        # Linha atravessa todo o talhao (passa pela bordadura).
        from plugin.fortsmart_precision.core.row_engine import PlantingRow

        row = PlantingRow(
            fs_id="r1",
            row_id=1,
            pass_id=1,
            machine_id="p",
            spacing_m=0.5,
            direction="forward",
            offset_m=0.0,
            azimuth_deg=90.0,
            segment=Segment((0.0, 60.0), (200.0, 60.0)),
        )
        segs = apply_row_shutoff(
            [row],
            [],
            on_areas=areas.inner_work_area,
            shutoff_on_tramlines=False,
        )
        off = [s for s in segs if s.shutoff_state == "off"]
        on = [s for s in segs if s.shutoff_state == "on"]
        self.assertTrue(off, "deve desligar na bordadura / pontas")
        self.assertTrue(on, "deve ligar no miolo")
        # Ponto no miolo deve estar em trecho ON.
        mid = (100.0, 60.0)
        self.assertTrue(point_in_multipolygon(mid, areas.inner_work_area))

    def test_pipeline_plants_with_extension_and_headland_shutoff(self):
        field = rectangle(200, 120)
        p = planter()
        sprayer = SprayerMachine(
            machine_id="s",
            name="spray",
            nozzle_count=24,
            nozzle_spacing_m=0.5,
            boom_width_m=12.0,
            track=MachineTrack(track_width_m=1.8, tire_width_m=0.3),
        )
        project = PrecisionProject(
            field=FieldGeometry(
                field_boundary=field,
                operational_boundary=field,
                crs_authid="EPSG:31981",
            ),
            ab_line=ABLine(start=(0.0, 60.0), end=(200.0, 60.0)),
            planting=PrecisionOperation(
                operation_id="planting",
                machine=p,
                extension_m=20.0,
                headland=HeadlandLayout(
                    pass_count=1,
                    width_m=3.0,
                    effective_spacing_m=3.0,
                    mode="follow_boundary",
                ),
            ),
            spraying=PrecisionOperation(
                operation_id="spraying",
                machine=sprayer,
                headland=HeadlandLayout(pass_count=0),
            ),
            planting_kinematics=kinematics_from_planter(p),
            planting_avoidance=PlantingAvoidanceConfiguration(enabled=False),
            avoidance=AvoidanceConfiguration(mode=AvoidanceMode.NONE),
            shutoff_on_headland_inner=True,
            shutoff_on_tramlines=False,
        )
        result = run_precision_lines(project)
        self.assertGreater(len(result.planting_passes), 0)
        self.assertGreater(len(result.planting_rows), 0)
        # Passadas estendem alem do talhao.
        xs = []
        for item in result.planting_passes:
            xs.extend([item.guidance_segment.start[0], item.guidance_segment.end[0]])
        self.assertLess(min(xs), 0.0)
        self.assertGreater(max(xs), 200.0)
        # Ha trechos DESLIGA (bordadura) — shutoff so com plantio+spray no projeto.
        actions = {item["action"] for item in result.shutoff_table}
        self.assertIn("DESLIGA", actions)

    def test_planting_only_defers_shutoff_to_cross(self):
        field = rectangle(200, 120)
        p = planter()
        project = PrecisionProject(
            field=FieldGeometry(
                field_boundary=field,
                operational_boundary=field,
                crs_authid="EPSG:31981",
            ),
            ab_line=ABLine(start=(0.0, 60.0), end=(200.0, 60.0)),
            planting=PrecisionOperation(
                operation_id="planting",
                machine=p,
                extension_m=10.0,
                headland=HeadlandLayout(
                    pass_count=1,
                    width_m=3.0,
                    effective_spacing_m=3.0,
                    mode="follow_boundary",
                ),
            ),
            planting_kinematics=kinematics_from_planter(p),
            shutoff_on_headland_inner=True,
            shutoff_on_tramlines=False,
        )
        result = run_precision_lines(project)
        self.assertGreater(len(result.planting_passes), 0)
        self.assertEqual(len(result.shutoff_segments), 0)


if __name__ == "__main__":
    unittest.main()
