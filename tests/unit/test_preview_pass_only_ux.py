# -*- coding: utf-8 -*-
"""Mapa limpo: passadas do trator no preview; linhas virtuais so no motor."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.guidance_engine import TrafficPass
from plugin.fortsmart_precision.core.line_geometry import Segment
from plugin.fortsmart_precision.core.preview_layer_names import NAMED_PREVIEW_LAYERS
from plugin.fortsmart_precision.core.shutoff_engine import (
    PassShutoffVisual,
    RowShutoffSegment,
    aggregate_shutoff_on_passes,
    pass_shutoff_table,
)


class PreviewPassOnlyNamingTest(unittest.TestCase):
    def test_preview_has_passadas_plantio_not_seed_rows(self):
        self.assertIn("06_Passadas_Plantio", NAMED_PREVIEW_LAYERS)
        self.assertNotIn("06_Linhas_Plantio", NAMED_PREVIEW_LAYERS)


class AggregateShutoffOnPassesTest(unittest.TestCase):
    def test_projects_row_off_onto_tractor_pass(self):
        traffic = TrafficPass(
            pass_no=1,
            fs_id="p1",
            operation_id="planting",
            spacing_m=9.0,
            width_m=9.0,
            offset_m=0.0,
            azimuth_deg=90.0,
            direction="forward",
            clipped_segment=Segment((0.0, 0.0), (100.0, 0.0)),
            guidance_segment=Segment((0.0, 0.0), (100.0, 0.0)),
        )
        # Duas linhas virtuais OFF no meio da passada.
        offs = [
            RowShutoffSegment(
                fs_id="a",
                row_id=14,
                pass_id=1,
                machine_id="p",
                shutoff_state="off",
                segment=Segment((40.0, 1.0), (55.0, 1.0)),
            ),
            RowShutoffSegment(
                fs_id="b",
                row_id=21,
                pass_id=1,
                machine_id="p",
                shutoff_state="off",
                segment=Segment((42.0, -1.0), (58.0, -1.0)),
            ),
            RowShutoffSegment(
                fs_id="c",
                row_id=1,
                pass_id=1,
                machine_id="p",
                shutoff_state="on",
                segment=Segment((0.0, 0.0), (100.0, 0.0)),
            ),
        ]
        visuals = aggregate_shutoff_on_passes([traffic], offs)
        self.assertGreaterEqual(len(visuals), 1)
        self.assertTrue(all(isinstance(v, PassShutoffVisual) for v in visuals))
        # Uma geometria agregada, nao 36 linhas.
        self.assertLessEqual(len(visuals), 3)
        table = pass_shutoff_table(visuals)
        self.assertEqual(table[0]["pass_id"], 1)
        self.assertIn("14", table[0]["row_ids_off"])
        self.assertIn("21", table[0]["row_ids_off"])
        # Trecho OFF fica sobre a passada (y~0).
        for visual in visuals:
            for _x, y in visual.path_points:
                self.assertAlmostEqual(y, 0.0, places=5)


if __name__ == "__main__":
    unittest.main()
