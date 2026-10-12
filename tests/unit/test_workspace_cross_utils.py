# -*- coding: utf-8 -*-
"""Cruzamento sem A-B e mensagens de erro sem forcar SIRGAS."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.guidance_engine import TrafficPass
from plugin.fortsmart_precision.core.line_geometry import Segment
from plugin.fortsmart_precision.core.row_engine import PlantingRow
from plugin.fortsmart_precision.core.workspace_cross_utils import (
    ab_proxy_from_traffic_or_rows,
    format_workspace_error_message,
    project_avoidance_enabled,
)


class ProjectAvoidanceEnabledTest(unittest.TestCase):
    def test_requires_user_flag_and_obstacles(self):
        self.assertFalse(project_avoidance_enabled(user_enabled=False, obstacle_count=3))
        self.assertFalse(project_avoidance_enabled(user_enabled=True, obstacle_count=0))
        self.assertTrue(project_avoidance_enabled(user_enabled=True, obstacle_count=2))


class WorkspaceErrorMessageTest(unittest.TestCase):
    def test_ab_invalid_does_not_append_sirgas_convert_hint(self):
        msg = (
            "Linha A-B invalida (comprimento ~0 m no CRS de trabalho "
            "EPSG:31981). Capture A e B separados no mapa."
        )
        out = format_workspace_error_message(msg)
        self.assertEqual(out, msg)
        self.assertNotIn("Converter automaticamente", out)

    def test_geographic_crs_still_gets_convert_hint(self):
        msg = "Talhao em CRS geografico EPSG:4326."
        out = format_workspace_error_message(msg)
        self.assertIn("Converter automaticamente", out)


class AbProxyFromTrafficTest(unittest.TestCase):
    def test_uses_spray_pass_endpoints(self):
        traffic = TrafficPass(
            pass_no=1,
            fs_id="s1",
            operation_id="spraying",
            spacing_m=36.0,
            width_m=36.0,
            offset_m=0.0,
            azimuth_deg=0.0,
            direction="forward",
            clipped_segment=Segment((0.0, 0.0), (100.0, 0.0)),
            guidance_segment=Segment((0.0, 0.0), (100.0, 0.0)),
            path_points=((0.0, 0.0), (100.0, 0.0)),
        )
        start, end, path = ab_proxy_from_traffic_or_rows([traffic], [])
        self.assertEqual(start, (0.0, 0.0))
        self.assertEqual(end, (100.0, 0.0))
        self.assertEqual(path[0], start)

    def test_falls_back_to_planting_row(self):
        row = PlantingRow(
            fs_id="r1",
            row_id=1,
            pass_id=1,
            machine_id="p",
            spacing_m=0.5,
            direction="forward",
            offset_m=0.0,
            azimuth_deg=0.0,
            segment=Segment((10.0, 5.0), (80.0, 5.0)),
        )
        start, end, _path = ab_proxy_from_traffic_or_rows([], [row])
        self.assertEqual(start, (10.0, 5.0))
        self.assertEqual(end, (80.0, 5.0))


if __name__ == "__main__":
    unittest.main()
