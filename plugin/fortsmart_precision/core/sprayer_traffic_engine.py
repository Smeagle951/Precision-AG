# -*- coding: utf-8 -*-
"""Motor de trafego do pulverizador: zonas de pneu e shutoff por offset lateral."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.machine_model import PlanterMachine
from ..domain.sprayer_traffic_configuration import SprayerTrafficConfiguration, TireZone


@dataclass(frozen=True)
class RowShutoffClassification:
    """Classificacao LIGA/DESLIGA de uma linha da plantadeira vs zonas de pneu."""

    row_id: int
    offset_m: float
    action: str  # "LIGA" | "DESLIGA"
    zone_side: str | None  # "left" | "right" | None

    def attributes(self) -> dict[str, object]:
        return {
            "row_id": self.row_id,
            "offset_m": self.offset_m,
            "action": self.action,
            "zone_side": self.zone_side or "",
        }


def classify_lateral_offset(
    offset_m: float,
    left_zone: TireZone,
    right_zone: TireZone,
) -> tuple[str, str | None]:
    """Retorna (acao, zona) para um offset lateral no frame da maquina."""
    if left_zone.contains(offset_m):
        return "DESLIGA", "left"
    if right_zone.contains(offset_m):
        return "DESLIGA", "right"
    return "LIGA", None


def calculate_planting_shutoff(
    planter: PlanterMachine,
    traffic: SprayerTrafficConfiguration,
) -> list[RowShutoffClassification]:
    """Classifica cada linha da plantadeira vs zonas de pneu do pulverizador.

    O usuario nao informa quais linhas desligam — deriva de:
    posicao das linhas (offset lateral) × zonas fisicas dos pneus.
    """
    planter.validate()
    traffic.validate()
    left, right = traffic.calculate_exclusion_zones()
    result: list[RowShutoffClassification] = []
    for row_id, offset_m in enumerate(planter.all_row_offsets(), start=1):
        action, zone = classify_lateral_offset(offset_m, left, right)
        result.append(
            RowShutoffClassification(
                row_id=row_id,
                offset_m=offset_m,
                action=action,
                zone_side=zone,
            )
        )
    return result


def shutoff_classification_summary(
    classifications: list[RowShutoffClassification],
) -> list[dict[str, object]]:
    """Tabela resumida para GUI / export."""
    return [
        {
            "row_id": item.row_id,
            "offset_m": round(item.offset_m, 3),
            "action": item.action,
            "zone_side": item.zone_side or "",
        }
        for item in classifications
    ]
