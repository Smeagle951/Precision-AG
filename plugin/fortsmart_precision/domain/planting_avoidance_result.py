# -*- coding: utf-8 -*-
"""Resultado rastreavel de desvio de plantio."""

from __future__ import annotations

from dataclasses import dataclass

from ..core.line_geometry import Point
from .planting_avoidance_configuration import PlantingAvoidanceStrategy


@dataclass(frozen=True)
class PlantingAvoidanceResult:
    fs_id: str
    pass_id: int
    obstacle_ids: tuple[str, ...]
    strategy_used: PlantingAvoidanceStrategy
    conflict_type: str
    original_tractor_path: tuple[Point, ...]
    avoidance_path: tuple[Point, ...]
    entry_transition: tuple[Point, ...]
    avoidance_arc: tuple[Point, ...]
    exit_transition: tuple[Point, ...]
    return_path: tuple[Point, ...]
    affected_rows: tuple[int, ...]
    coverage_gap_m2: float
    overlap_area_m2: float
    returns_to_guidance: bool
    tractor_radius_m: float = 0.0

    def attributes(self) -> dict[str, object]:
        return {
            "fs_id": self.fs_id,
            "pass_id": self.pass_id,
            "obstacle_ids": ",".join(self.obstacle_ids),
            "strategy_used": self.strategy_used.value,
            "conflict_type": self.conflict_type,
            "affected_rows": ",".join(str(r) for r in self.affected_rows),
            "coverage_gap_m2": self.coverage_gap_m2,
            "overlap_area_m2": self.overlap_area_m2,
            "returns_to_guidance": self.returns_to_guidance,
            "tractor_radius_m": self.tractor_radius_m,
        }
