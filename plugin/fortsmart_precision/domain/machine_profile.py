# -*- coding: utf-8 -*-
"""Perfil visual da maquina no simulador de rota (nao entra em calculo agronomico)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MachineType(str, Enum):
    TRACTOR_PLANTER = "TRACTOR_PLANTER"
    SPRAYER = "SPRAYER"
    SPREADER = "SPREADER"
    HARVESTER = "HARVESTER"
    TRACTOR = "TRACTOR"


MACHINE_TYPE_LABELS = {
    MachineType.TRACTOR_PLANTER: "Trator + plantadeira",
    MachineType.SPRAYER: "Pulverizador",
    MachineType.SPREADER: "Distribuidor",
    MachineType.HARVESTER: "Colhedora",
    MachineType.TRACTOR: "Trator isolado",
}


@dataclass(frozen=True)
class MachineProfile:
    id: str
    name: str
    machine_type: MachineType = MachineType.TRACTOR
    # None = nao informado; o marcador usa so um tamanho visual padrao.
    width_m: float | None = None
    length_m: float | None = None
    icon_type: str = "arrow_box"

    def validate(self) -> None:
        for value, label in ((self.width_m, "Largura"), (self.length_m, "Comprimento")):
            if value is not None and value <= 0:
                raise ValueError(f"{label} da maquina deve ser maior que zero.")
