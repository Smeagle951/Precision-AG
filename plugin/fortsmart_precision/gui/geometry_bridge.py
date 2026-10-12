# -*- coding: utf-8 -*-
"""Ponte QGIS ↔ MultiPolygon do nucleo (sem bbox como geometria)."""

from __future__ import annotations

from qgis.core import QgsGeometry, QgsPointXY, QgsWkbTypes

from ..core.line_geometry import (
    MultiPolygon,
    Point,
    assert_not_degenerate_field,
    circularity_score,
    looks_like_axis_aligned_bbox,
)


class GeometryBridgeError(ValueError):
    """Geometria do talhao invalida ou degenerada."""


__all__ = [
    "GeometryBridgeError",
    "assert_not_degenerate_field",
    "densify_polygon_geometry",
    "qgs_geometry_to_multipolygon",
    "vertex_count",
    "is_axis_aligned_rectangle",
    "pick_field_qgs_geometry",
]


def densify_polygon_geometry(geometry: QgsGeometry, *, densify_m: float = 2.0) -> QgsGeometry:
    """Lineariza curvas e densifica o anel — preserva circunferencia do pivo.

    Em pivos grandes, densify fixo de 2 m gera ~1500+ vertices e trava o
    shutoff/PIP. Usa passo adaptativo (~360 pontos no perimetro).
    """
    if geometry is None or geometry.isEmpty():
        raise GeometryBridgeError("Geometria vazia.")

    geom = QgsGeometry(geometry)
    wkb = geom.wkbType()
    if QgsWkbTypes.isCurvedType(wkb):
        try:
            linear = geom.constGet().curveToLine()
            geom = QgsGeometry(linear.clone())
        except Exception:
            converted = geom.convertToType(QgsWkbTypes.PolygonGeometry, geom.isMultipart())
            if converted is None or converted.isEmpty():
                raise GeometryBridgeError(
                    "Nao foi possivel linearizar geometria curva do talhao "
                    "(CurvePolygon/Circulo). Exporte como Polygon densificado."
                )
            geom = converted

    if geom.type() != QgsWkbTypes.PolygonGeometry:
        converted = geom.convertToType(QgsWkbTypes.PolygonGeometry, True)
        if converted is None or converted.isEmpty():
            converted = geom.convertToType(QgsWkbTypes.PolygonGeometry, False)
        if converted is None or converted.isEmpty():
            raise GeometryBridgeError(
                f"Geometria do talhao nao e poligono "
                f"(tipo={QgsWkbTypes.displayString(geom.wkbType())})."
            )
        geom = converted

    try:
        step = densify_m
        if densify_m > 0:
            # Circunferencia aproximada pelo bbox: limita vertices do pivo.
            extent = geom.boundingBox()
            if extent is not None and not extent.isEmpty():
                peri_approx = 2.0 * (extent.width() + extent.height())
                if peri_approx > 0:
                    adaptive = peri_approx / 360.0
                    step = max(densify_m, min(20.0, adaptive))
            densified = geom.densifyByDistance(step)
            if densified is not None and not densified.isEmpty():
                geom = densified
    except Exception:
        pass
    return geom


def qgs_geometry_to_multipolygon(geometry: QgsGeometry) -> MultiPolygon:
    """Converte QgsGeometry em MultiPolygon do nucleo.

    Nunca usa boundingBox. Densifica curvas antes de ler vertices.
    """
    geom = densify_polygon_geometry(geometry)
    if geom.isMultipart():
        raw_polygons = geom.asMultiPolygon()
    else:
        raw_polygons = [geom.asPolygon()]

    polygons: MultiPolygon = []
    for raw_polygon in raw_polygons:
        if not raw_polygon:
            continue
        rings = []
        for ring in raw_polygon:
            if not ring or len(ring) < 3:
                continue
            pts = [(float(point.x()), float(point.y())) for point in ring]
            cleaned: list[Point] = []
            for pt in pts:
                if not cleaned or abs(cleaned[-1][0] - pt[0]) > 1e-9 or abs(cleaned[-1][1] - pt[1]) > 1e-9:
                    cleaned.append(pt)
            if len(cleaned) >= 3:
                rings.append(cleaned)
        if rings:
            polygons.append((rings[0], rings[1:]))

    if not polygons:
        raise GeometryBridgeError(
            "Limite operacional sem poligonos validos apos densificar. "
            "Verifique se a feicao e um poligono (nao linha/ponto) e nao esta vazia."
        )
    return polygons


def vertex_count(geometry: QgsGeometry) -> int:
    try:
        geom = densify_polygon_geometry(geometry, densify_m=0.0)
    except Exception:
        return 0
    total = 0
    if geom.isMultipart():
        for poly in geom.asMultiPolygon() or []:
            for ring in poly:
                total += max(0, len(ring) - 1)
    else:
        for ring in geom.asPolygon() or []:
            total += max(0, len(ring) - 1)
    return total


def is_axis_aligned_rectangle(geometry: QgsGeometry) -> bool:
    """Detecta envelope retangular (4 verts ou densificado colinear nas bordas)."""
    try:
        mp = qgs_geometry_to_multipolygon(geometry)
    except Exception:
        return False
    if not mp:
        return False
    return looks_like_axis_aligned_bbox(mp[0])


def pick_field_qgs_geometry(
    geometries: list[QgsGeometry],
    *,
    ab_start: Point | None = None,
    ab_end: Point | None = None,
) -> QgsGeometry:
    """Escolhe a feicao do talhao — evita bbox densificado vencer o pivo circular.

    Nunca faz unaryUnion. Prefere geometria circular (alta circularidade) que
    contem o meio da A-B; rejeita envelopes retangulares.
    """
    valid = [QgsGeometry(g) for g in geometries if g is not None and not g.isEmpty()]
    if not valid:
        raise GeometryBridgeError("Talhao sem geometria.")
    if len(valid) == 1:
        return valid[0]

    scored: list[tuple[float, int, QgsGeometry]] = []
    for geom in valid:
        try:
            mp = qgs_geometry_to_multipolygon(geom)
        except Exception:
            continue
        poly = mp[0]
        if looks_like_axis_aligned_bbox(poly):
            continue
        score = circularity_score(poly)
        containing = 0
        if ab_start is not None and ab_end is not None:
            mid = QgsPointXY(
                (ab_start[0] + ab_end[0]) / 2.0,
                (ab_start[1] + ab_end[1]) / 2.0,
            )
            mid_geom = QgsGeometry.fromPointXY(mid)
            if geom.contains(mid_geom) or geom.intersects(mid_geom):
                containing = 1
        scored.append((score + containing * 10.0, vertex_count(geom), geom))

    if scored:
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return scored[0][2]

    # So restaram retangulos — nao inventar uniao; falhar com instrucao clara.
    raise GeometryBridgeError(
        "So encontrei geometria retangular (Bounding Box / extent), nao o pivo circular. "
        "Na camada LIMITE (EPSG metrico), selecione a feicao circular do talhao "
        "(ferramenta Selecionar feicoes), marque 'Usar apenas a feicao SELECIONADA' "
        "e limpe o preview antes de gerar de novo. Nao use a camada 'Boundary' se ela for o envelope."
    )
