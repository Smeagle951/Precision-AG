# -*- coding: utf-8 -*-
"""Resultado consolidado da validacao da rota (cache usado durante a simulacao)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from shapely.geometry import Point

from .warning_model import STRUCTURAL_TYPES, RouteWarning, Severity, WarningStatus


@dataclass
class ValidationResult:
    route_count: int
    obstacle_count: int = 0
    warnings: list[RouteWarning] = field(default_factory=list)
    settings: dict[str, object] = field(default_factory=dict)
    signature: str = ""

    def count(self, severity: Severity) -> int:
        return sum(1 for item in self.warnings if item.severity is severity)

    @property
    def critical_count(self) -> int:
        return self.count(Severity.CRITICAL)

    @property
    def warning_count(self) -> int:
        return self.count(Severity.WARNING)

    @property
    def info_count(self) -> int:
        return self.count(Severity.INFO)

    def warning(self, warning_id: str) -> RouteWarning:
        return next(item for item in self.warnings if item.id == warning_id)

    def warnings_for_pass(self, pass_id: str) -> list[RouteWarning]:
        """Consulta usada pelo simulador a cada passada (nao recalcula nada)."""
        return [item for item in self.warnings if item.involves(pass_id)]

    def filtered(self, category: str = "ALL") -> list[RouteWarning]:
        if category == "ALL":
            return list(self.warnings)
        if category == "CRITICAL":
            return [item for item in self.warnings if item.severity is Severity.CRITICAL]
        return [item for item in self.warnings if item.category == category]

    def blocked_pass_ids(self) -> list[str]:
        return sorted({item.pass_id for item in self.warnings if item.warning_type in STRUCTURAL_TYPES})

    def blocks_simulation(self, allow_with_warnings: bool = True) -> bool:
        """Vazia/invalida sempre bloqueia; avisos abertos so se a configuracao proibir."""
        if self.blocked_pass_ids():
            return True
        if allow_with_warnings:
            return False
        return any(
            item.status is WarningStatus.OPEN and item.severity is not Severity.INFO for item in self.warnings
        )

    def nearest_warning(self, x: float, y: float, tolerance_m: float) -> RouteWarning | None:
        """Aviso mais proximo de um clique no mapa (mesmo CRS da validacao)."""
        click = Point(x, y)
        best, best_distance = None, tolerance_m
        for item in self.warnings:
            if item.geometry is None or item.geometry.is_empty:
                continue
            distance = item.geometry.distance(click)
            if distance <= best_distance:
                best, best_distance = item, distance
        return best

    def set_status(self, warning_id: str, status: WarningStatus) -> None:
        self.warning(warning_id).status = WarningStatus(status)

    def summary(self) -> str:
        return (
            f"Total de problemas: {len(self.warnings)} | CRITICOS: {self.critical_count} | "
            f"AVISOS: {self.warning_count} | INFORMATIVOS: {self.info_count}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "route_count": self.route_count,
            "obstacle_count": self.obstacle_count,
            "critical": self.critical_count,
            "warning": self.warning_count,
            "info": self.info_count,
            "settings": dict(self.settings),
            "warnings": [item.to_dict() for item in self.warnings],
        }

    def write_json(self, path: str | Path) -> Path:
        target = Path(path)
        target.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return target
