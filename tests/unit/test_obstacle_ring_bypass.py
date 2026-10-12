# -*- coding: utf-8 -*-
"""Desvio por anel do buffer (Shapely): geometria real + Rmin/hitch."""

from __future__ import annotations

import unittest

from plugin.fortsmart_precision.core import obstacle_ring_bypass
from plugin.fortsmart_precision.core.line_geometry import Segment, distance
from plugin.fortsmart_precision.core.obstacle_ring_bypass import (
    _distancia_ponto_segmento,
    distancia_seguranca_ideal,
    desviar_circulo_anel,
    desviar_circulo_validado,
    desviar_pelo_anel,
    raio_curvatura_minimo_m,
)


class DistanciaSegurancaTest(unittest.TestCase):
    def test_includes_half_width_hitch_and_margin(self):
        d = distancia_seguranca_ideal(
            largura_implemento_m=12.0,
            raio_giro_minimo_m=6.5,
            distancia_pino_eixo_m=3.0,
            margem_extra_m=0.5,
        )
        # 6 + 9/(13) + 0.5 ≈ 7.19
        self.assertAlmostEqual(d, 6.0 + (9.0 / 13.0) + 0.5, places=5)


class RingBypassCircleTest(unittest.TestCase):
    def test_follows_real_circle_not_bbox(self):
        segment = Segment((0.0, 0.0), (100.0, 0.0))
        center = (50.0, 0.0)
        path = desviar_circulo_anel(segment, center, 15.0, segmentos_por_quadrante=24)
        self.assertIsNotNone(path)
        self.assertGreater(len(path), 40)
        mid = path[len(path) // 4 : 3 * len(path) // 4]
        on_arc = [p for p in mid if abs(distance(p, center) - 15.0) < 0.35]
        self.assertGreater(len(on_arc), 15)
        # Nao e um retangulo (so 4 cantos): muitos vertices no arco.
        self.assertGreater(len(path), 20)

    def test_validated_opens_curve_for_rmin(self):
        segment = Segment((0.0, 0.0), (100.0, 0.0))
        # Obstaculo pequeno: raio base 3 m, Rmin 8 m — precisa expandir.
        path = desviar_circulo_validado(
            segment,
            (50.0, 0.0),
            3.0,
            raio_giro_minimo_m=8.0,
            distancia_pino_eixo_m=0.0,
            incremento_m=0.5,
            max_tentativas=30,
        )
        self.assertIsNotNone(path)
        self.assertGreaterEqual(raio_curvatura_minimo_m(path), 7.5)


class RingBypassRadiusResolutionTest(unittest.TestCase):
    """O raio necessario e resolvido antes de gerar geometria, nao por tentativa."""

    def test_distance_to_segment_uses_interior_not_only_endpoints(self):
        segment = Segment((0.0, 0.0), (100.0, 0.0))
        self.assertAlmostEqual(_distancia_ponto_segmento((50.0, 7.0), segment), 7.0, places=6)
        # Fora da projecao: mede ate a ponta.
        self.assertAlmostEqual(_distancia_ponto_segmento((-3.0, 4.0), segment), 5.0, places=6)

    def test_obstacle_out_of_reach_returns_none_without_building_rings(self):
        segment = Segment((0.0, 0.0), (100.0, 0.0))
        calls = []
        original = obstacle_ring_bypass.desviar_circulo_anel

        def spy(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)

        obstacle_ring_bypass.desviar_circulo_anel = spy
        try:
            path = desviar_circulo_validado(
                segment,
                (50.0, 400.0),  # longe demais para qualquer tentativa alcancar
                5.0,
                raio_giro_minimo_m=8.0,
                incremento_m=0.5,
                max_tentativas=20,
            )
        finally:
            obstacle_ring_bypass.desviar_circulo_anel = original
        self.assertIsNone(path)
        self.assertEqual(calls, [])

    def test_starts_at_rmin_and_stops_when_widening_stops_helping(self):
        segment = Segment((0.0, 0.0), (100.0, 0.0))
        center = (50.0, 0.0)
        calls = []
        original = obstacle_ring_bypass.desviar_circulo_anel

        def spy(*args, **kwargs):
            calls.append(args[2])
            return original(*args, **kwargs)

        obstacle_ring_bypass.desviar_circulo_anel = spy
        try:
            path = desviar_circulo_validado(
                segment,
                center,
                3.0,
                raio_giro_minimo_m=18.0,
                incremento_m=0.5,
                max_tentativas=60,
            )
        finally:
            obstacle_ring_bypass.desviar_circulo_anel = original
        self.assertIsNotNone(path)
        # Primeira tentativa ja parte do raio dirigivel, nao do clearance de 3 m.
        self.assertAlmostEqual(calls[0], 18.0 * 0.98, places=6)
        # Alargar fecha a juncao reta x arco: para em poucas tentativas.
        self.assertLessEqual(len(calls), 4)
        # E devolve a melhor curvatura vista, nao a ultima (que seria a pior).
        # Afastamento lateral maximo = raio do anel efetivamente usado.
        self.assertLess(max(abs(p[1]) for p in path), 22.0)
        self.assertGreater(raio_curvatura_minimo_m(path), 15.0)

    def test_clearance_radius_is_never_reduced_by_the_shortcut(self):
        segment = Segment((0.0, 0.0), (100.0, 0.0))
        center = (50.0, 0.0)
        path = desviar_circulo_validado(
            segment,
            center,
            19.5,  # meia barra + margem ja embutidos
            raio_giro_minimo_m=12.0,
            distancia_pino_eixo_m=0.0,
            incremento_m=0.5,
            max_tentativas=20,
        )
        self.assertIsNotNone(path)
        # Rmin menor que o clearance nao pode encolher o desvio.
        self.assertGreaterEqual(min(distance(p, center) for p in path[2:-2]), 19.4)


class RingBypassPolygonTest(unittest.TestCase):
    def test_rectangle_follows_rounded_buffer(self):
        segment = Segment((0.0, 5.0), (40.0, 5.0))
        rect = (
            [(15.0, 0.0), (25.0, 0.0), (25.0, 10.0), (15.0, 10.0), (15.0, 0.0)],
            [],
        )
        path = desviar_pelo_anel(
            segment,
            rect,
            distancia_seguranca_m=2.0,
            segmentos_por_quadrante=16,
            cantos="round",
        )
        self.assertIsNotNone(path)
        self.assertGreater(len(path), 12)
        self.assertAlmostEqual(path[0][1], 5.0, places=3)
        self.assertAlmostEqual(path[-1][1], 5.0, places=3)


if __name__ == "__main__":
    unittest.main()
