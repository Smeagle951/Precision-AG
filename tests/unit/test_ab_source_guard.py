# -*- coding: utf-8 -*-
"""A-B nunca pode ser reapontada para uma camada gerada a partir das passadas."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core.layer_roles import (
    GENERATED_PASS_ROLES,
    INTERNAL_KEY_PROPERTY,
    LEGACY_INTERNAL_KEY_PROPERTY,
    ROLE_PROPERTY,
    ROLE_PROPERTY_NAMESPACED,
    ab_source_rejection_reason,
)


class _Layer:
    def __init__(self, name: str, **props):
        self._name = name
        self._props = props

    def name(self) -> str:
        return self._name

    def customProperty(self, key, default=None):
        return self._props.get(key, default)


class AbSourceGuardTest(unittest.TestCase):
    def test_user_lines_and_ab_layers_are_accepted(self):
        self.assertIsNone(ab_source_rejection_reason(None))
        self.assertIsNone(ab_source_rejection_reason(_Layer("Linha AB do usuario")))
        self.assertIsNone(ab_source_rejection_reason(_Layer("04_Linha_AB", **{ROLE_PROPERTY: "AB_LINE"})))
        self.assertIsNone(
            ab_source_rejection_reason(_Layer("Passadas antigas", **{ROLE_PROPERTY: "EXTERNAL_BOUNDARY"}))
        )

    def test_generated_pass_layers_are_rejected_with_clear_message(self):
        reason = ab_source_rejection_reason(_Layer("11_Passadas", **{ROLE_PROPERTY: "GUIDANCE_TRACK"}))
        self.assertIsNotNone(reason)
        self.assertIn("'11_Passadas'", reason)
        self.assertIn("nao pode ser usada como A-B", reason)
        self.assertIn("A A-B continua sendo a linha original", reason)

    def test_every_generated_role_is_rejected(self):
        for role in sorted(GENERATED_PASS_ROLES):
            with self.subTest(role=role):
                layer = _Layer(f"camada_{role}", **{ROLE_PROPERTY_NAMESPACED: role})
                self.assertIsNotNone(ab_source_rejection_reason(layer))

    def test_role_inferred_from_internal_key(self):
        self.assertIsNotNone(
            ab_source_rejection_reason(_Layer("Rastros", **{INTERNAL_KEY_PROPERTY: "08_Rastros_Pneus"}))
        )
        self.assertIsNotNone(
            ab_source_rejection_reason(_Layer("Prev", **{LEGACY_INTERNAL_KEY_PROPERTY: "05_Passadas"}))
        )
        self.assertIsNotNone(
            ab_source_rejection_reason(_Layer("Curvas", **{LEGACY_INTERNAL_KEY_PROPERTY: "HEADLAND_TURN"}))
        )
        self.assertIsNone(
            ab_source_rejection_reason(_Layer("AB", **{LEGACY_INTERNAL_KEY_PROPERTY: "04_Linha_AB"}))
        )


if __name__ == "__main__":
    unittest.main()
