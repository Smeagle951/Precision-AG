# -*- coding: utf-8 -*-
"""Configuracao de trafego do pulverizador: pneus, vao livre e zonas de shutoff.

O usuario informa medidas fisicas reais; o plugin calcula bitola, zonas de pneu
e quais linhas de plantio desligam — sem expor offsets como ±1,715 m.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .machine_model import MachineTrack, MachineModelError


class SprayerTrafficError(ValueError):
    """Erro na configuracao de trafego do pulverizador."""


class TrafficMeasureResolution(str, Enum):
    """Como resolver medidas inconsistentes (vao + 2×pneu ≠ externa)."""

    USE_OUTER = "use_outer"
    USE_INNER_AND_TIRES = "use_inner_and_tires"


@dataclass(frozen=True)
class TireZone:
    """Faixa lateral no frame da maquina (centro = 0, positivo = direita)."""

    side: str
    min_m: float
    max_m: float

    def validate(self) -> None:
        if self.min_m >= self.max_m:
            raise SprayerTrafficError(f"Zona de pneu {self.side} invalida: min >= max.")
        if self.max_m <= 0 and self.min_m < 0:
            pass  # esquerda: max pode ser <= 0
        if self.min_m >= 0 and self.max_m > 0:
            pass  # direita

    @property
    def width_m(self) -> float:
        return self.max_m - self.min_m

    @property
    def center_m(self) -> float:
        return (self.min_m + self.max_m) / 2.0

    def contains(self, lateral_offset_m: float, *, tol: float = 1e-9) -> bool:
        return (self.min_m - tol) <= lateral_offset_m <= (self.max_m + tol)


@dataclass(frozen=True)
class TrafficMeasureCheck:
    """Resultado da validacao vao + 2×pneu vs largura externa."""

    tire_width_m: float
    inner_clearance_m: float
    outer_width_m: float
    computed_outer_m: float
    difference_m: float
    is_consistent: bool
    tolerance_m: float = 0.005

    def message(self) -> str:
        if self.is_consistent:
            return "Medidas de trafego consistentes."
        return (
            f"Medidas inconsistentes: vao {self.inner_clearance_m:.2f} m + "
            f"2×pneu {2 * self.tire_width_m:.2f} m = {self.computed_outer_m:.2f} m, "
            f"externa informada {self.outer_width_m:.2f} m "
            f"(dif {self.difference_m:.2f} m)."
        )


@dataclass(frozen=True)
class SprayerTrafficConfiguration:
    """Trafego / pneus do pulverizador — separado da largura da barra (boom).

    Campos informados pelo usuario:
    - boom_width_m: largura da barra (aplicacao, bordadura spray, desvio)
    - tire_width_m: largura fisica do pneu
    - inner_clearance_m: vao livre entre faces internas dos pneus
    - outer_width_m: largura externa total (eixo a eixo externo)

    Campos calculados:
    - left_tire_zone / right_tire_zone
    - track_width_m (centro a centro dos pneus)
    """

    boom_width_m: float
    tire_width_m: float
    inner_clearance_m: float
    outer_width_m: float
    resolution: TrafficMeasureResolution = TrafficMeasureResolution.USE_OUTER
    safety_margin_m: float = 0.0

    def validate(self) -> None:
        if self.boom_width_m <= 0:
            raise SprayerTrafficError("Largura da barra deve ser maior que zero.")
        if self.tire_width_m <= 0:
            raise SprayerTrafficError("Largura do pneu deve ser maior que zero.")
        if self.inner_clearance_m <= 0:
            raise SprayerTrafficError("Vao livre entre pneus deve ser maior que zero.")
        if self.outer_width_m <= 0:
            raise SprayerTrafficError("Largura externa deve ser maior que zero.")
        if self.safety_margin_m < 0:
            raise SprayerTrafficError("Margem de seguranca nao pode ser negativa.")

    def measure_check(self, *, tolerance_m: float = 0.005) -> TrafficMeasureCheck:
        computed = self.inner_clearance_m + 2.0 * self.tire_width_m
        diff = abs(computed - self.outer_width_m)
        return TrafficMeasureCheck(
            tire_width_m=self.tire_width_m,
            inner_clearance_m=self.inner_clearance_m,
            outer_width_m=self.outer_width_m,
            computed_outer_m=computed,
            difference_m=diff,
            is_consistent=diff <= tolerance_m,
            tolerance_m=tolerance_m,
        )

    def resolved_outer_width_m(self) -> float:
        """Largura externa efetiva apos resolucao de inconsistencia."""
        self.validate()
        check = self.measure_check()
        if check.is_consistent:
            return self.outer_width_m
        if self.resolution == TrafficMeasureResolution.USE_INNER_AND_TIRES:
            return check.computed_outer_m
        return self.outer_width_m

    def resolved_tire_width_m(self) -> float:
        """Largura efetiva de cada zona de pneu (pode diferir levemente de tire_width_m)."""
        self.validate()
        check = self.measure_check()
        if not check.is_consistent and self.resolution == TrafficMeasureResolution.USE_INNER_AND_TIRES:
            return self.tire_width_m
        outer = self.resolved_outer_width_m()
        return (outer - self.inner_clearance_m) / 2.0

    def calculate_tire_zones(self) -> tuple[TireZone, TireZone]:
        """Deriva zonas fisicas de desligamento a partir das medidas informadas."""
        self.validate()
        half_outer = self.resolved_outer_width_m() / 2.0
        half_inner = self.inner_clearance_m / 2.0
        tw = self.resolved_tire_width_m()

        left = TireZone(
            side="left",
            min_m=-half_outer,
            max_m=-half_outer + tw,
        )
        right = TireZone(
            side="right",
            min_m=half_outer - tw,
            max_m=half_outer,
        )
        left.validate()
        right.validate()
        return left, right

    def calculate_exclusion_zones(self) -> tuple[TireZone, TireZone]:
        """Faixas operacionais do shutoff, com margem aplicada em ambos os lados."""
        left, right = self.calculate_tire_zones()
        margin = self.safety_margin_m
        exclusion_left = TireZone(
            side=left.side,
            min_m=left.min_m - margin,
            max_m=left.max_m + margin,
        )
        exclusion_right = TireZone(
            side=right.side,
            min_m=right.min_m - margin,
            max_m=right.max_m + margin,
        )
        exclusion_left.validate()
        exclusion_right.validate()
        return exclusion_left, exclusion_right

    @property
    def track_width_m(self) -> float:
        """Distancia entre centros dos pneus (para rastros e tramlines)."""
        left, right = self.calculate_tire_zones()
        return right.center_m - left.center_m

    @property
    def exclusion_width_m(self) -> float:
        """Largura usada no shutoff: pneu fisico mais margem em cada lado."""
        left, _right = self.calculate_exclusion_zones()
        return left.width_m

    def to_machine_track(self) -> MachineTrack:
        """Compatibilidade com motores que usam MachineTrack (bitola + pneu)."""
        left, right = self.calculate_tire_zones()
        exclusion_left, exclusion_right = self.calculate_exclusion_zones()
        track = MachineTrack(
            track_width_m=self.track_width_m,
            tire_width_m=left.width_m,
        )
        track.validate()
        return track

    def report(self) -> dict[str, object]:
        left, right = self.calculate_tire_zones()
        exclusion_left, exclusion_right = self.calculate_exclusion_zones()
        check = self.measure_check()
        return {
            "boom_width_m": self.boom_width_m,
            "tire_width_m": self.tire_width_m,
            "inner_clearance_m": self.inner_clearance_m,
            "outer_width_m": self.outer_width_m,
            "resolved_outer_m": self.resolved_outer_width_m(),
            "track_width_m": self.track_width_m,
            "safety_margin_m": self.safety_margin_m,
            "exclusion_width_m": self.exclusion_width_m,
            "left_tire_zone": (left.min_m, left.max_m),
            "right_tire_zone": (right.min_m, right.max_m),
            "left_exclusion_zone": (exclusion_left.min_m, exclusion_left.max_m),
            "right_exclusion_zone": (exclusion_right.min_m, exclusion_right.max_m),
            "measures_consistent": check.is_consistent,
            "resolution": self.resolution.value,
        }
