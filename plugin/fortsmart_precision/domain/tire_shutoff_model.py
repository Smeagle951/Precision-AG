# -*- coding: utf-8 -*-
"""Modelo agronomico de shutoff: pneu × linha de semente × miolo.

Em agricultura de precisao, o desligamento linha a linha combina:

1. **Zona de pneu (OFF)** — faixa lateral onde o trator/pulverizador compacta o solo.
   Nenhuma semente deve cair sobre o rastro do pneu (tramlines / tire tracks).

2. **Corredor interno (ON)** — entre os dois eixos do pulverizador, fora das faixas
   de pneu, as linhas da plantadeira permanecem LIGADAS quando nao ha outra restricao.

3. **Classificacao estatica por offset** — cada linha da barra tem offset lateral fixo;
   `SprayerTrafficConfiguration.calculate_tire_zones()` define quais offsets caem
   sobre pneu esquerdo/direito (`calculate_planting_shutoff`).

4. **Classificacao espacial ao longo da passada** — `apply_row_shutoff` amostra cada
   linha virtual e cruza com poligonos de rastro, bordadura (off/on) e obstaculo.

Fluxo recomendado no workspace (etapas separadas 1 → 2 → Cruzar):

- Gerar passadas de plantio (etapa 2) e pulverizacao (etapa 1).
- No cruzamento, derivar **N linhas virtuais por passada** (`ensure_virtual_planting_rows`),
  nao apenas 1 linha por eixo do trator.
- Aplicar shutoff com rastros do pulverizador + zonas de bordadura/obstaculo.

Nunca remova funcionalidades existentes: o shutoff completo no mesmo projeto continua
em `precision_lines_engine`; o cruzamento reutiliza os mesmos motores.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.machine_model import PlanterMachine
from ..domain.sprayer_traffic_configuration import SprayerTrafficConfiguration, TireZone


@dataclass(frozen=True)
class TireShutoffZones:
    """Zonas laterais de desligamento derivadas do trafego do pulverizador."""

    left: TireZone
    right: TireZone
    inner_clearance_m: float

    @classmethod
    def from_traffic(cls, traffic: SprayerTrafficConfiguration) -> TireShutoffZones:
        traffic.validate()
        left, right = traffic.calculate_exclusion_zones()
        return cls(
            left=left,
            right=right,
            inner_clearance_m=traffic.inner_clearance_m,
        )

    def row_is_on_corridor(self, offset_m: float) -> bool:
        """True se o offset cai no miolo (fora das faixas de pneu)."""
        return not self.left.contains(offset_m) and not self.right.contains(offset_m)

    def classify_row_offset(self, offset_m: float) -> tuple[str, str | None]:
        """Retorna (LIGA|DESLIGA, lado do pneu ou None)."""
        if self.left.contains(offset_m):
            return "DESLIGA", "left"
        if self.right.contains(offset_m):
            return "DESLIGA", "right"
        return "LIGA", None


def tire_shutoff_from_machines(
    planter: PlanterMachine,
    traffic: SprayerTrafficConfiguration,
) -> tuple[TireShutoffZones, list[tuple[int, float, str, str | None]]]:
    """Resume zonas + classificacao linha a linha para GUI/export."""
    zones = TireShutoffZones.from_traffic(traffic)
    rows: list[tuple[int, float, str, str | None]] = []
    for row_id, offset_m in enumerate(planter.all_row_offsets(), start=1):
        action, side = zones.classify_row_offset(offset_m)
        rows.append((row_id, offset_m, action, side))
    return zones, rows
