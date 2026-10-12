# -*- coding: utf-8 -*-
"""Testes de helpers de cruzamento de linhas."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.line_geometry import Segment, azimuth_degrees


class LineImportHelpersTest(unittest.TestCase):
    def test_azimuth_for_imported_rows(self):
        self.assertAlmostEqual(azimuth_degrees((0.0, 0.0), (0.0, 10.0)), 0.0, places=5)
        self.assertAlmostEqual(azimuth_degrees((0.0, 0.0), (10.0, 0.0)), 90.0, places=5)

    def test_segment_length_for_imported_row(self):
        segment = Segment(start=(0.0, 0.0), end=(100.0, 0.0))
        self.assertAlmostEqual(segment.length, 100.0, places=5)


if __name__ == "__main__":
    unittest.main()
