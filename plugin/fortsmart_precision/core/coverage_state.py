# -*- coding: utf-8 -*-
"""Cobertura ja percorrida no simulador: uma faixa por passada (sem dissolver o transpasse)."""

from __future__ import annotations

from dataclasses import dataclass

import shapely


@dataclass(frozen=True)
class PassCoverage:
    pass_id: str
    pass_index: int
    geometry: object  # Polygon/MultiPolygon shapely, CRS metrico da rota
    distance_m: float
    completed: bool

    @property
    def area_m2(self) -> float:
        return self.geometry.area


class CoverageState:
    """Passadas concluidas (consolidadas) + a faixa da passada ativa ate a maquina."""

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.completed: dict[int, PassCoverage] = {}
        self.current: PassCoverage | None = None
        self.revision = 0
        self._completed_union = None
        self._unique_cache: tuple[int, float] | None = None

    # ---------------------------------------------------------- escrita ----
    def complete(self, coverage: PassCoverage) -> None:
        self.completed[coverage.pass_index] = coverage
        if self.current is not None and self.current.pass_index == coverage.pass_index:
            self.current = None
        geometry = coverage.geometry
        if not geometry.is_empty:
            self._completed_union = (
                geometry if self._completed_union is None else self._completed_union.union(geometry)
            )
        self.revision += 1

    def set_current(self, coverage: PassCoverage | None) -> None:
        self.current = coverage
        self.revision += 1

    # ---------------------------------------------------------- leitura ----
    def passes(self) -> list[PassCoverage]:
        items = [self.completed[i] for i in sorted(self.completed)]
        return items + ([self.current] if self.current is not None else [])

    @property
    def coverage_by_pass(self) -> dict[str, object]:
        return {item.pass_id: item.geometry for item in self.passes()}

    @property
    def gross_area_m2(self) -> float:
        """Soma das faixas (transpasse contado duas vezes)."""
        return sum(item.area_m2 for item in self.passes())

    @property
    def unique_area_m2(self) -> float:
        """Area efetivamente coberta (uniao); a passada ativa so e comparada com o entorno dela."""
        if self._unique_cache is not None and self._unique_cache[0] == self.revision:
            return self._unique_cache[1]
        union = self._completed_union
        area = 0.0 if union is None else union.area
        current = self.current
        if current is not None and not current.geometry.is_empty:
            area += current.area_m2
            if union is not None:
                nearby = shapely.clip_by_rect(union, *current.geometry.bounds)
                if not nearby.is_empty:
                    area -= current.geometry.intersection(nearby).area
        self._unique_cache = (self.revision, area)
        return area

    @property
    def overlap_area_m2(self) -> float:
        return max(0.0, self.gross_area_m2 - self.unique_area_m2)
