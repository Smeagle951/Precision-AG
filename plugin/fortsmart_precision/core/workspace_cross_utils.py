# -*- coding: utf-8 -*-
"""Utilitarios do cruzamento plantio × pulverizacao (sem depender de A-B)."""

from __future__ import annotations

from ..core.line_geometry import Point, distance


_CRS_CONVERT_HINT = (
    "\n\nUse o botao 'Converter automaticamente todas as camadas' "
    "na aba 1, ou o Conversor de zona (lote), para SIRGAS 2000 / UTM."
)


def project_avoidance_enabled(*, user_enabled: bool, obstacle_count: int) -> bool:
    """Desvio so entra no motor quando o usuario marcou e ha obstaculos validos."""
    return bool(user_enabled and obstacle_count > 0)


def format_workspace_error_message(text: str) -> str:
    """Mensagem de erro da GUI; nao sugere converter CRS em falhas de A-B."""
    lower = text.lower()
    if "converter automaticamente" in lower:
        return text
    # A-B ~0 / invalida cita EPSG de trabalho — nao e falta de SIRGAS.
    if "a-b" in lower and ("invalida" in lower or "~0" in lower or "comprimento" in lower):
        return text
    if "curta demais" in lower or "coincidem" in lower:
        return text
    if "geografico" in lower or "geographic" in lower:
        return text + _CRS_CONVERT_HINT
    return text


def ab_proxy_from_traffic_or_rows(
    spraying_passes,
    planting_rows,
) -> tuple[Point, Point, tuple[Point, ...]]:
    """Deriva A-B auxiliar a partir das linhas ja carregadas (cruzamento sem captura)."""
    for traffic in spraying_passes or ():
        pts = list(traffic.line_points())
        if len(pts) >= 2 and distance(pts[0], pts[-1]) >= 0.5:
            return pts[0], pts[-1], tuple(pts)
    for row in planting_rows or ():
        pts = list(row.line_points())
        if len(pts) >= 2 and distance(pts[0], pts[-1]) >= 0.5:
            return pts[0], pts[-1], tuple(pts)
    raise ValueError(
        "Nao foi possivel cruzar: faltam linhas de plantio/pulverizacao com comprimento real. "
        "Selecione as camadas na aba 5 ou gere aplicacao e plantio antes."
    )
