# -*- coding: utf-8 -*-
import unittest

from plugin.fortsmart_precision.core.generation_progress import report_progress, scaled_progress


class GenerationProgressTest(unittest.TestCase):
    def test_report_progress_clamps_percent(self):
        seen: list[tuple[int, str]] = []

        def cb(pct, msg):
            seen.append((pct, msg))

        report_progress(cb, -5, "a")
        report_progress(cb, 150, "b")
        self.assertEqual(seen, [(0, "a"), (100, "b")])

    def test_scaled_progress_maps_range(self):
        seen: list[tuple[int, str]] = []

        def cb(pct, msg):
            seen.append((pct, msg))

        inner = scaled_progress(cb, 20, 60)
        assert inner is not None
        inner(0, "start")
        inner(100, "end")
        self.assertEqual(seen[0][0], 20)
        self.assertEqual(seen[1][0], 60)


if __name__ == "__main__":
    unittest.main()
