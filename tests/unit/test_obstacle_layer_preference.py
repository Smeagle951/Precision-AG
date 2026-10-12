# -*- coding: utf-8 -*-
"""Testes de preferencia de camada pontual nao vazia (logica pura)."""

from __future__ import annotations

import unittest


class PreferNonemptyPointLogicTest(unittest.TestCase):
    def test_prefers_layer_with_features(self):
        layers = [
            ("PointFeature", 0),
            ("POSTES", 12),
            ("Pedras", 3),
        ]
        nonempty = [name for name, count in layers if count > 0]
        self.assertEqual(nonempty[0], "POSTES")
        self.assertNotIn("PointFeature", nonempty[:1])

    def test_falls_back_when_all_empty(self):
        layers = [("A", 0), ("B", 0)]
        nonempty = [name for name, count in layers if count > 0]
        pool = nonempty if nonempty else [name for name, _ in layers]
        self.assertEqual(pool[0], "A")


if __name__ == "__main__":
    unittest.main()
