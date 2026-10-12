# -*- coding: utf-8 -*-
"""Configuracao global de suavizacao de linhas operacionais."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SmoothingLevel(str, Enum):
    LOW = "low"
    MED = "med"
    HIGH = "high"
    OFF = "off"


@dataclass(frozen=True)
class PathSmoothingConfiguration:
    """Aplica-se a todas as linhas do pipeline Precision Lines."""

    level: SmoothingLevel = SmoothingLevel.LOW
    densify_m: float | None = None

    def enabled(self) -> bool:
        return self.level != SmoothingLevel.OFF

    def resolved_densify_m(self) -> float:
        if self.densify_m is not None:
            return self.densify_m
        if self.level == SmoothingLevel.HIGH:
            return 2.5
        if self.level == SmoothingLevel.MED:
            return 5.0
        return 8.0
