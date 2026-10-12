# -*- coding: utf-8 -*-
"""Modo Rapido x Precisao: acelera sem sacrificar a geometria agricola."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
from plugin.fortsmart_precision.domain.headland_layout import HeadlandLayout
from plugin.fortsmart_precision.domain.machine_model import MachineTrack, PlanterMachine
from plugin.fortsmart_precision.domain.obstacle_model import obstacle_from_point
from plugin.fortsmart_precision.domain.planting_avoidance_configuration import (
    PlantingAvoidanceConfiguration,
)
from plugin.fortsmart_precision.domain.planting_kinematics import PlantingKinematics
from plugin.fortsmart_precision.domain.precision_project import (
    ABLine,
    FieldGeometry,
    PrecisionOperation,
    PrecisionProject,
)
from plugin.fortsmart_precision.domain.processing_profile import (
    ProcessingProfileError,
    final_profile,
    preview_profile,
    profile_from_mode,
)


def _rectangle():
    return [([(0.0, 0.0), (400.0, 0.0), (400.0, 240.0), (0.0, 240.0), (0.0, 0.0)], [])]


def _planter():
    return PlanterMachine(
        machine_id="p9",
        name="Plantadeira 9m",
        row_count=18,
        row_spacing_m=0.5,
        track=MachineTrack(track_width_m=1.8, tire_width_m=0.3),
    )


def _kinematics():
    return PlantingKinematics(
        operational_width_m=9.0,
        track_width_m=2.0,
        hitch_distance_m=3.0,
        tractor_length_m=4.0,
        row_count=18,
        row_spacing_m=0.5,
    )


def _project(profile):
    return PrecisionProject(
        field=FieldGeometry(
            field_boundary=_rectangle(),
            operational_boundary=_rectangle(),
            crs_authid="EPSG:31982",
        ),
        ab_line=ABLine(start=(0.0, 120.0), end=(400.0, 120.0)),
        planting=PrecisionOperation(
            operation_id="planting",
            machine=_planter(),
            headland=HeadlandLayout(
                pass_count=1, width_m=9.0, effective_spacing_m=9.0, mode="parallel_ab"
            ),
        ),
        obstacles=(obstacle_from_point((200.0, 120.0), obstacle_radius_m=1.0),),
        planting_kinematics=_kinematics(),
        planting_avoidance=PlantingAvoidanceConfiguration(),
        processing=profile,
    )


class ProfileModelTest(unittest.TestCase):
    def test_default_project_is_final(self):
        project = _project(final_profile())
        self.assertFalse(project.processing.is_preview)
        project.validate()

    def test_profile_from_mode_accepts_portuguese(self):
        self.assertTrue(profile_from_mode("rapido").is_preview)
        self.assertFalse(profile_from_mode("precisao").is_preview)
        with self.assertRaises(ProcessingProfileError):
            profile_from_mode("turbo")

    def test_preview_never_degrades_below_usable_resolution(self):
        preview = preview_profile()
        preview.validate()
        # Um arco de contorno precisa continuar sendo um arco.
        self.assertGreaterEqual(preview.arc_segments, 12)
        self.assertGreaterEqual(preview.boundary_max_vertices, 120)


class ProfileEffectTest(unittest.TestCase):
    def test_preview_skips_virtual_rows_final_materializes(self):
        preview = run_precision_lines(_project(preview_profile()))
        final = run_precision_lines(_project(final_profile()))
        self.assertEqual(len(preview.planting_rows), 0)
        self.assertGreater(len(final.planting_rows), 0)

    def test_both_modes_detect_the_same_obstacle(self):
        """A otimizacao e algoritmica: o desvio nao pode sumir no modo Rapido."""
        preview = run_precision_lines(_project(preview_profile()))
        final = run_precision_lines(_project(final_profile()))
        self.assertGreater(len(preview.planting_avoidance_results), 0)
        self.assertEqual(
            len(preview.planting_avoidance_results),
            len(final.planting_avoidance_results),
        )

    def test_both_modes_produce_the_same_passes(self):
        preview = run_precision_lines(_project(preview_profile()))
        final = run_precision_lines(_project(final_profile()))
        self.assertEqual(len(preview.planting_passes), len(final.planting_passes))

    def test_both_modes_share_the_same_headland(self):
        preview = run_precision_lines(_project(preview_profile()))
        final = run_precision_lines(_project(final_profile()))
        self.assertEqual(
            preview.boundary.reserved_width_m, final.boundary.reserved_width_m
        )
        self.assertEqual(
            len(preview.boundary.headland_centerlines),
            len(final.boundary.headland_centerlines),
        )


if __name__ == "__main__":
    unittest.main()
