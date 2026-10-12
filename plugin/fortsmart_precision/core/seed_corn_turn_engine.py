# -*- coding: utf-8 -*-
"""Voltas separadas por grupo de milho semente (F / M1 / M2)."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.boundary_areas import BoundaryAreas
from ..domain.seed_corn_planning import SeedCornPlan
from ..domain.turn_configuration import TurnConfiguration
from .line_geometry import MultiPolygon
from .parallel_pass_engine import ParallelPass
from .turn_path_engine import TurnPath, TurnPathResult, generate_turn_paths


SEED_CORN_GROUPS = ("F", "M1", "M2")


class SeedCornTurnError(ValueError):
    """Erro ao gerar voltas por grupo de milho semente."""


@dataclass(frozen=True)
class SeedCornGroupTurnResult:
    group: str
    pass_nos: tuple[int, ...]
    result: TurnPathResult

    @property
    def turns(self) -> list[TurnPath]:
        return self.result.turns


@dataclass(frozen=True)
class SeedCornTurnPlan:
    groups: list[SeedCornGroupTurnResult]

    @property
    def all_turns(self) -> list[TurnPath]:
        turns: list[TurnPath] = []
        for group in self.groups:
            turns.extend(group.turns)
        return turns

    def report(self) -> dict[str, object]:
        return {
            "groups": [
                {
                    "group": item.group,
                    "pass_nos": list(item.pass_nos),
                    "turn_count": len(item.turns),
                    "report": item.result.report,
                }
                for item in self.groups
            ],
            "total_turns": len(self.all_turns),
        }


def passes_for_seed_group(plan: SeedCornPlan, group: str) -> list[ParallelPass]:
    """Seleciona passadas centrais que contem linhas do grupo."""
    group = group.upper()
    if group == "F":
        rows = plan.female_rows
    elif group == "M1":
        rows = plan.male_rows_1
    elif group == "M2":
        rows = plan.male_rows_2
    else:
        raise SeedCornTurnError(f"Grupo de milho semente desconhecido: {group}")

    pass_nos = sorted({row.pass_no for row in rows})
    by_no = {item.pass_no: item for item in plan.passes}
    return [by_no[no] for no in pass_nos if no in by_no]


def generate_seed_corn_group_turns(
    plan: SeedCornPlan,
    areas: BoundaryAreas,
    group_configs: dict[str, TurnConfiguration],
    obstacles: MultiPolygon | None = None,
) -> SeedCornTurnPlan:
    """Gera voltas independentes para F, M1 e M2.

    Cada grupo pode ter sequencia, tipo de volta, maquina e area proprios.
    """
    if not group_configs:
        raise SeedCornTurnError("Nenhuma configuracao de grupo informada.")

    results: list[SeedCornGroupTurnResult] = []
    for group, config in group_configs.items():
        key = group.upper()
        if key not in SEED_CORN_GROUPS:
            raise SeedCornTurnError(f"Grupo de milho semente desconhecido: {group}")
        passes = passes_for_seed_group(plan, key)
        if not passes:
            results.append(
                SeedCornGroupTurnResult(
                    group=key,
                    pass_nos=(),
                    result=TurnPathResult(
                        turns=[],
                        connections=[],
                        report={"mode": "none", "turn_count": 0, "message": f"Sem passadas para {key}."},
                    ),
                )
            )
            continue
        result = generate_turn_paths(passes, config, areas, obstacles=obstacles)
        # Anexa grupo no relatorio sem alterar paths.
        enriched = TurnPathResult(
            turns=result.turns,
            connections=result.connections,
            report={**result.report, "seed_corn_group": key},
        )
        results.append(
            SeedCornGroupTurnResult(
                group=key,
                pass_nos=tuple(item.pass_no for item in passes),
                result=enriched,
            )
        )
    return SeedCornTurnPlan(groups=results)
