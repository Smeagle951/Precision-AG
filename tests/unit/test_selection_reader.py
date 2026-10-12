# -*- coding: utf-8 -*-
"""Etapa 0E: identificador estavel e resumo da selecao (sem QGIS)."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core import selection_reader as sr
from plugin.fortsmart_precision.core.selection_reader import FeatureIdentity, SelectionInfo, classify_identity


def _info(code, count, features=()):
    return SelectionInfo("L1", "linhas", "", False, None, None, code, count, tuple(features))


class IdentityTest(unittest.TestCase):
    def test_attribute_wins_over_every_fid(self):
        item = classify_identity(7, attribute_value="P-07", provider="memory")
        self.assertEqual((item.source, item.value, item.key), (sr.ID_ATTRIBUTE, "P-07", "ATTRIBUTE:P-07"))
        self.assertTrue(item.stable)

    def test_provider_key_session_and_unstable(self):
        self.assertEqual(classify_identity(3, provider="ogr", has_provider_key=True).source, sr.ID_PROVIDER_KEY)
        self.assertEqual(classify_identity(3, provider="memory").source, sr.ID_SESSION)
        self.assertEqual(classify_identity(3, provider="ogr").source, sr.ID_UNSTABLE)
        self.assertFalse(classify_identity(3, provider="memory").stable)

    def test_new_feature_is_never_called_stable(self):
        item = classify_identity(-2, provider="ogr", has_provider_key=True)
        self.assertEqual(item.source, sr.ID_NEW)
        self.assertFalse(item.stable)


class DiagnosticsTest(unittest.TestCase):
    def _codes(self, identities, **kwargs):
        return {item.code for item in sr.identity_diagnostics(identities, **kwargs)}

    def test_duplicate_attribute_values_are_reported(self):
        items = [FeatureIdentity(1, sr.ID_ATTRIBUTE, "A"), FeatureIdentity(2, sr.ID_ATTRIBUTE, "A")]
        self.assertEqual(self._codes(items), {sr.DUPLICATE_IDENTITY})

    def test_weak_sources_are_reported(self):
        items = [
            FeatureIdentity(1, sr.ID_UNSTABLE, "1"),
            FeatureIdentity(2, sr.ID_SESSION, "2"),
            FeatureIdentity(-1, sr.ID_NEW, "-1"),
        ]
        self.assertEqual(
            self._codes(items), {sr.UNSTABLE_IDENTITY, sr.SESSION_IDENTITY, sr.UNSAVED_FEATURES}
        )

    def test_stable_selection_has_no_diagnostics(self):
        items = [FeatureIdentity(1, sr.ID_PROVIDER_KEY, "1"), FeatureIdentity(2, sr.ID_ATTRIBUTE, "B")]
        self.assertEqual(self._codes(items), set())
        self.assertEqual(self._codes(items, truncated=True, count=900), {sr.SELECTION_TRUNCATED})


class SelectionInfoTest(unittest.TestCase):
    def test_single_and_multiple_lines(self):
        self.assertTrue(_info(2, 1).single_line)
        self.assertTrue(_info(5, 3).multiple_lines)
        self.assertFalse(_info(3, 1).single_line)
        self.assertTrue(_info(6, 1).is_polygon)

    def test_text(self):
        self.assertEqual(_info(2, 0).text(), "nenhuma feição selecionada")
        features = [FeatureIdentity(1, sr.ID_ATTRIBUTE, "L01"), FeatureIdentity(2, sr.ID_ATTRIBUTE, "L02")]
        self.assertEqual(_info(2, 2, features).text(), "2 linhas selecionadas · ID: atributo FortSmart · L01, L02")
        self.assertEqual(_info(3, 1).text(), "1 feição selecionada")


if __name__ == "__main__":
    unittest.main()
