# -*- coding: utf-8 -*-
"""Ordem de desenho e helpers do preview no mapa QGIS."""

from __future__ import annotations

from .preview_layer_names import NAMED_PREVIEW_LAYERS

# Poligonos embaixo; passadas principais sempre por cima (nao ficam invisiveis).
PREVIEW_POLYGON_LAYERS = (
    "01_Limite_Externo",
    "02_Bordadura",
    "03_Limite_Interno",
    "10_Zonas_Seguranca",
    "11_Desvios_Obstaculos",
    "14_Limite_Operacional",
)
PREVIEW_LINE_LAYERS_MID = (
    "07_Linha_Trator",
    "08_Rastros_Pneus",
    "12_Linhas_Finais",
    "13_Shutoff",
)
PREVIEW_LINE_LAYERS_TOP = (
    "05_Passadas",
    "06_Passadas_Plantio",
    "15_Passadas_Bordadura",
    "04_Linha_AB",
    "09_Obstaculos_RTK",
)


def preview_layer_draw_order() -> tuple[str, ...]:
    """Ordem bottom→top para addMapLayer (passadas por ultimo)."""
    order = PREVIEW_POLYGON_LAYERS + PREVIEW_LINE_LAYERS_MID + PREVIEW_LINE_LAYERS_TOP
    missing = set(NAMED_PREVIEW_LAYERS) - set(order)
    extra = set(order) - set(NAMED_PREVIEW_LAYERS)
    if missing or extra:
        raise ValueError(f"Ordem preview inconsistente: faltam {missing}, extras {extra}")
    return order


def traffic_pass_points(traffic) -> tuple[tuple[float, float], ...]:
    """Pontos da passada para desenho; fallback no segmento clipado."""
    from .line_geometry import decimate_polyline

    pts = traffic.line_points()
    if len(pts) >= 2:
        if len(pts) > 480:
            pts = tuple(decimate_polyline(list(pts), min_step_m=2.5, max_points=480))
        return pts
    seg = traffic.clipped_segment
    if seg.length > 0.01:
        return (seg.start, seg.end)
    return ()


def independent_tractor_paths(traffic_passes) -> tuple[tuple[tuple[float, float], ...], ...]:
    """Uma geometria por passada, sem costurar extremidades ou criar manobras."""
    paths = []
    for traffic in traffic_passes:
        points = traffic_pass_points(traffic)
        if len(points) >= 2:
            paths.append(points)
    return tuple(paths)


def preview_line_width_mm(short_name: str, default_width: float) -> float:
    """Larguras mais visiveis para passadas no mapa."""
    if short_name in ("05_Passadas", "06_Passadas_Plantio"):
        return max(default_width, 2.8)
    if short_name == "15_Passadas_Bordadura":
        return max(default_width, 2.2)
    if short_name == "04_Linha_AB":
        return max(default_width, 2.0)
    return default_width
