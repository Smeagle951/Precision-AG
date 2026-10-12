# -*- coding: utf-8 -*-
"""Pre-visualizacao das linhas fisicas da plantadeira (somente depuracao).

A trajetoria (TRACTOR_CENTERLINE) continua sendo a passada; aqui as linhas
(PLANTER_ROWS) sao offsets dela, so para conferir o encontro entre passadas.
Nunca sao salvas nem exportadas (`fortsmart_preview = true`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..domain.planter_geometry import PlanterGeometryConfig
from .line_geometry import Point, offset_open_polyline

ROW_PREVIEW_ROLE = "PLANTER_ROWS"


@dataclass(frozen=True)
class RowPreviewLine:
    label: str
    row_index: int
    offset_m: float
    points: tuple[Point, ...]

    def attributes(self) -> dict[str, object]:
        return {
            "row_label": self.label,
            "row_index": self.row_index,
            "offset_m": self.offset_m,
            "fortsmart_preview": True,
            "preview_kind": ROW_PREVIEW_ROLE,
        }


def _offset_left(points: Sequence[Point], distance_m: float) -> tuple[Point, ...]:
    """Offset a esquerda com distancia exata (juncao redonda do GEOS)."""
    if abs(distance_m) <= 1e-12:
        return tuple(points)
    try:
        from shapely.geometry import LineString

        line = LineString(points).offset_curve(distance_m, quad_segs=32, join_style="round")
        if not line.is_empty and line.geom_type == "LineString":
            return tuple((float(x), float(y)) for x, y in line.coords)
    except Exception:
        pass
    return tuple(offset_open_polyline(list(points), distance_m))


def build_row_preview(
    center_path: Sequence[Point],
    config: PlanterGeometryConfig,
    *,
    direction: str = "forward",
) -> list[RowPreviewLine]:
    """ROW_01..ROW_N a partir do eixo; ROW_01 e a linha mais a esquerda do sentido.

    Na volta (`reverse`) o eixo e percorrido ao contrario: a ordem logica das
    linhas inverte, a distribuicao espacial continua simetrica ao eixo.
    """
    config.validate()
    path = list(center_path)
    if direction == "reverse":
        path.reverse()
    width = len(str(config.row_count))
    lines: list[RowPreviewLine] = []
    for index, offset in enumerate(config.row_offsets()):
        # offset positivo = direita do sentido; offset_curve positivo = esquerda.
        lines.append(
            RowPreviewLine(
                label=f"ROW_{index + 1:0{max(2, width)}d}",
                row_index=index + 1,
                offset_m=offset,
                points=_offset_left(path, -offset),
            )
        )
    return lines
