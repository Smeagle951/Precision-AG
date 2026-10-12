# -*- coding: utf-8 -*-
"""Areas espaciais separadas: limite, bordadura, area central e manobra externa."""

from __future__ import annotations

from dataclasses import dataclass

from ..core.line_geometry import (
    MultiPolygon,
    Point,
    close_ring,
    eroded_polygon_geos,
    point_in_multipolygon,
    ring_signed_area,
    shrink_polygon_components,
)


class BoundaryAreasError(ValueError):
    """Erro na construcao de areas de limite/bordadura."""


@dataclass(frozen=True)
class BoundaryAreas:
    """Objetos geometricos tipados usados pelo motor de voltas.

    `external_turn_area` e obrigatoria para voltas fora do limite (Etapa 3).
    """

    field_boundary: MultiPolygon | None
    operational_boundary: MultiPolygon
    headland_area: MultiPolygon | None
    inner_work_area: MultiPolygon | None
    external_turn_area: MultiPolygon | None = None
    reserved_width_m: float = 0.0

    def point_in_operational(self, point: Point) -> bool:
        return point_in_multipolygon(point, self.operational_boundary)

    def point_in_inner(self, point: Point) -> bool:
        if not self.inner_work_area:
            return False
        return point_in_multipolygon(point, self.inner_work_area)

    def point_in_headland(self, point: Point) -> bool:
        """Bordadura = operacional menos area central."""
        if self.reserved_width_m <= 0 or not self.inner_work_area:
            return False
        return self.point_in_operational(point) and not self.point_in_inner(point)

    def point_in_external_turn(self, point: Point) -> bool:
        if not self.external_turn_area:
            return False
        return point_in_multipolygon(point, self.external_turn_area)

    def report(self) -> dict[str, object]:
        return {
            "has_field_boundary": bool(self.field_boundary),
            "has_operational_boundary": bool(self.operational_boundary),
            "has_headland_area": bool(self.headland_area),
            "has_inner_work_area": bool(self.inner_work_area),
            "has_external_turn_area": bool(self.external_turn_area),
            "reserved_width_m": self.reserved_width_m,
        }


def build_inner_and_headland(
    operational: MultiPolygon,
    reserved_width_m: float,
    field_boundary: MultiPolygon | None = None,
    external_turn_area: MultiPolygon | None = None,
) -> BoundaryAreas:
    """Constroi area central e bordadura a partir do limite operacional real.

    O limite selecionado e a geometria-mae: encolhe por buffer de anel, nunca
    por bounding box. A bordadura = operacional com buraco = miolo.
    """
    if not operational:
        raise BoundaryAreasError("Limite operacional vazio.")
    if reserved_width_m < 0:
        raise BoundaryAreasError("Largura reservada de bordadura nao pode ser negativa.")

    if reserved_width_m == 0:
        return BoundaryAreas(
            field_boundary=field_boundary,
            operational_boundary=operational,
            headland_area=None,
            inner_work_area=list(operational),
            external_turn_area=external_turn_area,
            reserved_width_m=0.0,
        )

    # Estreitamento < 2x a faixa separa o miolo em partes: todas continuam.
    inner: MultiPolygon = []
    components_by_polygon: list[MultiPolygon] = []
    for polygon in operational:
        components = shrink_polygon_components(polygon, reserved_width_m)
        _guard_component_loss(polygon, components, reserved_width_m)
        components_by_polygon.append(components)
        inner.extend(components)
    if not inner:
        raise BoundaryAreasError("A bordadura eliminou a area de trabalho.")

    # Representacao da bordadura: anel externo com buraco = cada parte do miolo.
    headland: MultiPolygon = []
    for op_poly, components in zip(operational, components_by_polygon):
        outer, existing_holes = op_poly
        holes = list(existing_holes) + [list(close_ring(ring)) for ring, _holes in components]
        headland.append((list(close_ring(outer)), holes))

    return BoundaryAreas(
        field_boundary=field_boundary,
        operational_boundary=operational,
        headland_area=headland,
        inner_work_area=inner,
        external_turn_area=external_turn_area,
        reserved_width_m=reserved_width_m,
    )


def _guard_component_loss(polygon, components: MultiPolygon, reserved_width_m: float) -> None:
    """Aborta se o miolo recebido tem menos area que o buffer GEOS real."""
    from ..core.polygon_components import (
        UNEXPECTED_MULTIPART_COMPONENT_LOSS,
        extract_polygon_components,
        validate_component_area_conservation,
    )

    reference = eroded_polygon_geos(polygon, reserved_width_m)
    if reference is None:
        return
    if len(extract_polygon_components(reference)) <= 1 and len(components) <= 1:
        return
    validate_component_area_conservation(
        reference.area,
        [
            abs(ring_signed_area(ring)) - sum(abs(ring_signed_area(hole)) for hole in holes)
            for ring, holes in components
        ],
        code=UNEXPECTED_MULTIPART_COMPONENT_LOSS,
    )


def headland_available_width_m(areas: BoundaryAreas) -> float:
    """Largura de manobra disponivel na bordadura (reserva configurada)."""
    return max(0.0, areas.reserved_width_m)
