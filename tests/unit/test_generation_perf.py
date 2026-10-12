# -*- coding: utf-8 -*-
"""Geracao separada plantio/pulverizacao nao pode densificar milhoes de pontos."""

from __future__ import annotations

import time
import unittest

from plugin.fortsmart_precision.core.application_obstacle_engine import (
    _PASS_POLYLINE_MAX_POINTS,
)
from plugin.fortsmart_precision.core.guidance_engine import TrafficPass
from plugin.fortsmart_precision.core.line_geometry import Segment, decimate_polyline
from plugin.fortsmart_precision.core.precision_lines_engine import (
    _passes_near_multipolygon,
    run_precision_lines,
)
from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
from plugin.fortsmart_precision.domain.machine_model import (
    MachineTrack,
    PlanterMachine,
    SprayerMachine,
)
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


def _big_field(width=800.0, height=600.0):
    outer = [(0.0, 0.0), (width, 0.0), (width, height), (0.0, height), (0.0, 0.0)]
    return [(outer, [])]


def _planter():
    return PlanterMachine(
        machine_id="p36",
        name="36x0.5",
        row_count=36,
        row_spacing_m=0.5,
        track=MachineTrack(track_width_m=1.8, tire_width_m=0.3),
    )


def _sprayer():
    return SprayerMachine(
        machine_id="s",
        name="36m",
        nozzle_count=72,
        nozzle_spacing_m=0.5,
        boom_width_m=36.0,
        track=MachineTrack(track_width_m=3.0, tire_width_m=0.37),
    )


class GenerationPerfTest(unittest.TestCase):
    def test_decimate_polyline_caps(self):
        pts = [(float(i) * 0.5, 0.0) for i in range(4001)]
        out = decimate_polyline(pts, min_step_m=5.0, max_points=100)
        self.assertLessEqual(len(out), 100)

    def test_planting_only_finishes_fast(self):
        field = _big_field()
        project = PrecisionProject(
            field=FieldGeometry(
                field_boundary=field,
                operational_boundary=field,
                crs_authid="EPSG:31981",
            ),
            ab_line=ABLine(start=(0.0, 300.0), end=(800.0, 300.0)),
            planting=PrecisionOperation(
                operation_id="planting",
                machine=_planter(),
                extension_m=10.0,
                headland=HeadlandLayout(
                    pass_count=1,
                    width_m=18.0,
                    effective_spacing_m=18.0,
                    mode="follow_boundary",
                ),
            ),
            line_smoothing=PathSmoothingConfiguration(level=SmoothingLevel.LOW),
            shutoff_on_headland_inner=True,
            shutoff_on_tramlines=True,
        )
        t0 = time.perf_counter()
        result = run_precision_lines(project)
        elapsed = time.perf_counter() - t0
        self.assertGreater(len(result.planting_passes), 10)
        # Linhas virtuais (0,50 m) so sao calculadas quando shutoff/obstaculo exige.
        self.assertEqual(len(result.planting_rows), 0)
        self.assertEqual(len(result.shutoff_segments), 0)
        self.assertLess(
            elapsed,
            8.0,
            f"gerar plantio demorou {elapsed:.2f}s — risco de travar o QGIS",
        )

    def test_spraying_only_finishes_fast(self):
        field = _big_field()
        project = PrecisionProject(
            field=FieldGeometry(
                field_boundary=field,
                operational_boundary=field,
                crs_authid="EPSG:31981",
            ),
            ab_line=ABLine(start=(0.0, 300.0), end=(800.0, 300.0)),
            spraying=PrecisionOperation(
                operation_id="spraying",
                machine=_sprayer(),
                extension_m=10.0,
                headland=HeadlandLayout(
                    pass_count=1,
                    width_m=36.0,
                    effective_spacing_m=36.0,
                    mode="follow_boundary",
                ),
            ),
            line_smoothing=PathSmoothingConfiguration(level=SmoothingLevel.LOW),
        )
        t0 = time.perf_counter()
        result = run_precision_lines(project)
        elapsed = time.perf_counter() - t0
        self.assertGreater(len(result.spraying_passes), 5)
        self.assertGreater(len(result.tire_tracks), 0)
        self.assertEqual(len(result.tramline_zones), 0)
        # Rastros acompanham a polilinha (passo fino); teto 720 pts.
        self.assertTrue(all(len(t.points) <= 720 for t in result.tire_tracks))
        self.assertLess(
            elapsed,
            8.0,
            f"gerar aplicacao demorou {elapsed:.2f}s — risco de travar o QGIS",
        )

    def test_spraying_with_obstacles_finishes_fast(self):
        field = _big_field()
        from plugin.fortsmart_precision.domain.obstacle_model import obstacle_from_polygon
        from plugin.fortsmart_precision.domain.avoidance_configuration import (
            AvoidanceConfiguration,
            AvoidanceMode,
        )

        obstacles = tuple(
            obstacle_from_polygon(
                [
                    (
                        (80.0 + i * 18.0, 285.0),
                        (88.0 + i * 18.0, 285.0),
                        (88.0 + i * 18.0, 315.0),
                        (80.0 + i * 18.0, 315.0),
                        (80.0 + i * 18.0, 285.0),
                    ),
                    [],
                ],
                obstacle_radius_m=0.0,
                safety_margin_m=0.35,
                name=f"ob{i}",
                obstacle_id=f"ob{i}",
            )
            for i in range(20)
        )
        ab_path = [(0.0, 300.0), (400.0, 300.0), (800.0, 320.0)]
        project = PrecisionProject(
            field=FieldGeometry(
                field_boundary=field,
                operational_boundary=field,
                crs_authid="EPSG:31982",
            ),
            ab_line=ABLine(
                start=ab_path[0],
                end=ab_path[-1],
                path_points=tuple(ab_path),
            ),
            spraying=PrecisionOperation(
                operation_id="spraying",
                machine=_sprayer(),
                extension_m=10.0,
                headland=HeadlandLayout(
                    pass_count=1,
                    width_m=36.0,
                    effective_spacing_m=36.0,
                    mode="follow_boundary",
                ),
            ),
            obstacles=obstacles,
            avoidance=AvoidanceConfiguration(
                mode=AvoidanceMode.CONCENTRIC_RING,
                merge_adjacent_envelopes_m=0.0,
            ),
            line_smoothing=PathSmoothingConfiguration(level=SmoothingLevel.LOW),
        )
        t0 = time.perf_counter()
        result = run_precision_lines(project)
        elapsed = time.perf_counter() - t0
        self.assertGreater(len(result.spraying_passes), 5)
        max_pts = max(len(p.line_points()) for p in result.spraying_passes)
        self.assertLessEqual(max_pts, _PASS_POLYLINE_MAX_POINTS + 20)
        self.assertLess(
            elapsed,
            12.0,
            f"pulverizacao com obstaculos demorou {elapsed:.2f}s — risco de travar o QGIS",
        )


    def test_passes_near_multipolygon_filters_distant_passes(self):
        zone = [([(195.0, 95.0), (205.0, 95.0), (205.0, 105.0), (195.0, 105.0), (195.0, 95.0)], [])]
        near = TrafficPass(
            pass_no=1,
            fs_id="n",
            operation_id="planting",
            spacing_m=20.0,
            width_m=20.0,
            offset_m=0.0,
            azimuth_deg=0.0,
            direction="forward",
            clipped_segment=Segment((190.0, 100.0), (210.0, 100.0)),
            guidance_segment=Segment((190.0, 100.0), (210.0, 100.0)),
        )
        far = TrafficPass(
            pass_no=2,
            fs_id="f",
            operation_id="planting",
            spacing_m=20.0,
            width_m=20.0,
            offset_m=0.0,
            azimuth_deg=0.0,
            direction="forward",
            clipped_segment=Segment((0.0, 100.0), (50.0, 100.0)),
            guidance_segment=Segment((0.0, 100.0), (50.0, 100.0)),
        )
        out = _passes_near_multipolygon([near, far], zone, margin_m=10.0)
        self.assertEqual([p.fs_id for p in out], ["n"])


if __name__ == "__main__":
    unittest.main()
