# -*- coding: utf-8 -*-
"""Area operacional multi-talhao para aplicacao continua."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.line_geometry import MultiPolygon
from .headland_layout import HeadlandLayout


class ApplicationZoneError(ValueError):
    """Erro na area de aplicacao."""


@dataclass(frozen=True)
class FieldZone:
    field_id: str
    field_boundary: MultiPolygon
    operational_boundary: MultiPolygon
    headland: HeadlandLayout = field(default_factory=HeadlandLayout)
    headland_color: str = ""

    def validate(self) -> None:
        if not self.field_id:
            raise ApplicationZoneError("field_id obrigatorio.")
        if not self.operational_boundary:
            raise ApplicationZoneError("Limite operacional vazio.")


@dataclass(frozen=True)
class ApplicationZone:
    fields: tuple[FieldZone, ...]
    crs_authid: str
    continuous_spray_across_fields: bool = True
    inner_work_areas: MultiPolygon | None = None

    def validate(self) -> None:
        if not self.crs_authid:
            raise ApplicationZoneError("CRS obrigatorio.")
        if not self.fields:
            raise ApplicationZoneError("Informe ao menos um talhao.")
        for item in self.fields:
            item.validate()

    @property
    def operational_union(self) -> MultiPolygon:
        merged: MultiPolygon = []
        for zone in self.fields:
            merged.extend(zone.operational_boundary)
        return merged

    def work_area_for_operation(self) -> MultiPolygon:
        """Area onde a aplicacao pode ocorrer."""
        if self.inner_work_areas is not None:
            return self.inner_work_areas
        return self.operational_union

    @classmethod
    def from_single_field(
        cls,
        field_boundary: MultiPolygon,
        operational_boundary: MultiPolygon,
        crs_authid: str,
        *,
        inner_work_area: MultiPolygon | None = None,
        field_id: str = "field_1",
    ) -> ApplicationZone:
        return cls(
            fields=(
                FieldZone(
                    field_id=field_id,
                    field_boundary=field_boundary,
                    operational_boundary=operational_boundary,
                ),
            ),
            crs_authid=crs_authid,
            inner_work_areas=inner_work_area,
        )
