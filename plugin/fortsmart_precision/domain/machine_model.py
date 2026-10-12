# -*- coding: utf-8 -*-
"""Cadastro de maquinas: largura operacional vs espacamento de linhas separados."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .operation_width import OperationWidth, WidthComparison
from .planter_geometry import PlanterGeometryConfig, PlanterGeometryError, resolve_effective_working_width
from .sprayer_overlap import (
    OVERLAP_MODE_METERS,
    SprayerOverlapError,
    effective_pass_spacing_m as _effective_pass_spacing_m,
    resolve_sprayer_overlap_m,
)

# Import tardio evita ciclo; SprayerTrafficConfiguration e opcional em SprayerMachine.
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .sprayer_traffic_configuration import SprayerTrafficConfiguration


class MachineKind(str, Enum):
    PLANTER = "planter"
    SPRAYER = "sprayer"


class MachineModelError(ValueError):
    """Erro no modelo de maquina."""


@dataclass(frozen=True)
class MachineTrack:
    track_width_m: float
    tire_width_m: float

    def validate(self) -> None:
        if self.track_width_m <= 0:
            raise MachineModelError("Bitola deve ser maior que zero.")
        if self.tire_width_m <= 0:
            raise MachineModelError("Largura do pneu deve ser maior que zero.")
        if self.tire_width_m > self.track_width_m:
            raise MachineModelError("Largura do pneu nao pode exceder a bitola.")


@dataclass(frozen=True)
class PlanterMachine:
    machine_id: str
    name: str
    row_count: int
    row_spacing_m: float
    track: MachineTrack | None
    # Largura de trabalho informada: fonte de verdade da distancia entre passadas.
    informed_operational_width_m: float | None = None
    gnss_offset_m: float = 0.0
    implement_center_offset_m: float = 0.0
    physical_width_m: float | None = None

    @property
    def kind(self) -> MachineKind:
        return MachineKind.PLANTER

    def validate(self) -> None:
        if not self.machine_id:
            raise MachineModelError("machine_id obrigatorio.")
        try:
            self.geometry_config.validate()
        except PlanterGeometryError as exc:
            raise MachineModelError(f"{exc} ({exc.code})") from exc
        if self.physical_width_m is not None and self.physical_width_m <= 0:
            raise MachineModelError("Largura fisica da plantadeira deve ser maior que zero.")
        if self.track is not None:
            self.track.validate()

    @property
    def geometry_config(self) -> PlanterGeometryConfig:
        return PlanterGeometryConfig(
            row_count=self.row_count,
            row_spacing_m=self.row_spacing_m,
            configured_width_m=self.informed_operational_width_m,
        )

    @property
    def operational_width_m(self) -> float:
        """Largura de trabalho: informada pelo usuario; sem ela, linhas x espacamento."""
        self.validate()
        return resolve_effective_working_width(self.geometry_config)

    @property
    def half_operational_width_m(self) -> float:
        return self.operational_width_m / 2.0

    def width_comparison(self) -> WidthComparison:
        return OperationWidth(
            informed_width_m=self.operational_width_m,
            method="count_spacing",
            count=self.row_count,
            spacing_m=self.row_spacing_m,
        ).compare()

    def row_offset_from_center(self, row_index: int) -> float:
        self.validate()
        if row_index < 1 or row_index > self.row_count:
            raise MachineModelError("Indice de linha fora da plantadeira.")
        return self.geometry_config.row_offsets()[row_index - 1]

    def all_row_offsets(self) -> list[float]:
        self.validate()
        return self.geometry_config.row_offsets()

    @property
    def physical_span_m(self) -> float:
        """Distancia entre a primeira e a ultima linha da barra."""
        self.validate()
        return 2.0 * self.geometry_config.outer_row_offset_m

    @property
    def meeting_half_gap_m(self) -> float:
        """Metade do espaco de encontro ida/volta (0,25 m + 0,25 m = 0,50 m)."""
        return self.geometry_config.outer_half_margin_m

    @property
    def effective_pass_spacing_m(self) -> float:
        """Distancia entre eixos de passadas = largura operacional da plantadeira.

        O encontro ida/volta fica com meeting_half_gap_m de cada lado (total =
        row_spacing_m entre a ultima linha da ida e a primeira da volta).
        """
        return self.operational_width_m

    def meeting_spacing_m(self) -> float:
        """Espacamento no ENCONTRO de duas passadas vizinhas (ida e volta).

        Deve ser igual ao espacamento interno: menor = remonte (semente
        dobrada), maior = falha sem semente.
        """
        return self.operational_width_m - self.physical_span_m

    def meeting_status(self, tolerance_m: float = 0.01) -> dict[str, object]:
        gap = self.meeting_spacing_m()
        difference = gap - self.row_spacing_m
        if abs(difference) <= tolerance_m:
            status = "correct"
        elif difference < 0:
            status = "overlap"
        else:
            status = "gap"
        return {
            "internal_spacing_m": self.row_spacing_m,
            "meeting_spacing_m": gap,
            "difference_m": difference,
            "status": status,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "machine_id": self.machine_id,
            "name": self.name,
            "kind": self.kind.value,
            "row_count": self.row_count,
            "row_spacing_m": self.row_spacing_m,
            "operational_width_m": self.operational_width_m,
            "physical_width_m": self.physical_width_m,
            "track_width_m": self.track.track_width_m if self.track is not None else None,
            "tire_width_m": self.track.tire_width_m if self.track is not None else None,
            "gnss_offset_m": self.gnss_offset_m,
            "implement_center_offset_m": self.implement_center_offset_m,
        }


@dataclass(frozen=True)
class SprayerMachine:
    machine_id: str
    name: str
    nozzle_count: int
    nozzle_spacing_m: float
    boom_width_m: float
    track: MachineTrack
    overlap_m: float = 0.0
    traffic: "SprayerTrafficConfiguration | None" = None
    # "meters" usa overlap_m como antes; "nozzles" = overlap_nozzle_count x espacamento.
    overlap_mode: str = OVERLAP_MODE_METERS
    overlap_nozzle_count: int = 0
    # Raio minimo de giro do PULVERIZADOR (nao da plantadeira). None = nao informado.
    sprayer_minimum_turn_radius_m: float | None = None

    @property
    def kind(self) -> MachineKind:
        return MachineKind.SPRAYER

    @property
    def minimum_turn_radius_m(self) -> float | None:
        """Alias lido pelo motor de desvio da aplicacao; None quando nao informado."""
        return self.sprayer_minimum_turn_radius_m

    def validate(self) -> None:
        if not self.machine_id:
            raise MachineModelError("machine_id obrigatorio.")
        if (
            self.sprayer_minimum_turn_radius_m is not None
            and self.sprayer_minimum_turn_radius_m <= 0
        ):
            raise MachineModelError("Raio minimo de giro do pulverizador deve ser maior que zero.")
        if self.nozzle_count < 0 or self.nozzle_spacing_m < 0:
            raise MachineModelError("Numero e espacamento de bicos nao podem ser negativos.")
        if (self.nozzle_count > 0) != (self.nozzle_spacing_m > 0):
            raise MachineModelError("Informe numero e espacamento de bicos juntos.")
        if self.overlap_mode == "nozzles" and self.nozzle_count <= 0:
            raise MachineModelError("Transpasse em bicos exige numero e espacamento reais.")
        if self.boom_width_m <= 0:
            raise MachineModelError("Largura da barra deve ser maior que zero.")
        if self.overlap_m < 0:
            raise MachineModelError("Remonte nao pode ser negativo.")
        try:
            self.resolved_overlap_m
        except SprayerOverlapError as exc:
            raise MachineModelError(str(exc)) from exc
        self.track.validate()
        if self.traffic is not None:
            self.traffic.validate()

    @property
    def effective_track(self) -> MachineTrack:
        """Bitola/pneu derivados do trafego quando configurado."""
        if self.traffic is not None:
            return self.traffic.to_machine_track()
        return self.track

    @property
    def operational_width_m(self) -> float:
        self.validate()
        return self.boom_width_m

    @property
    def half_operational_width_m(self) -> float:
        return self.operational_width_m / 2.0

    @property
    def calculated_boom_width_m(self) -> float:
        return self.nozzle_count * self.nozzle_spacing_m

    @property
    def resolved_overlap_m(self) -> float:
        return resolve_sprayer_overlap_m(
            self.overlap_mode,
            nozzle_count=self.nozzle_count,
            nozzle_spacing_m=self.nozzle_spacing_m,
            boom_width_m=self.boom_width_m,
            overlap_m=self.overlap_m,
            overlap_nozzle_count=self.overlap_nozzle_count,
        )

    @property
    def effective_pass_spacing_m(self) -> float:
        """Passo centro a centro; a barra fisica (boom_width_m) nao encolhe."""
        try:
            return _effective_pass_spacing_m(self.boom_width_m, self.resolved_overlap_m)
        except SprayerOverlapError as exc:
            raise MachineModelError("Remonte deve ser menor que a largura da barra.") from exc

    def width_comparison(self) -> WidthComparison:
        if self.nozzle_count <= 0:
            return OperationWidth(
                informed_width_m=self.boom_width_m,
                method="manual",
                manual_confirmed=True,
            ).compare()
        return OperationWidth(
            informed_width_m=self.boom_width_m,
            method="count_spacing",
            count=self.nozzle_count,
            spacing_m=self.nozzle_spacing_m,
        ).compare()

    def to_dict(self) -> dict[str, object]:
        return {
            "machine_id": self.machine_id,
            "name": self.name,
            "kind": self.kind.value,
            "nozzle_count": self.nozzle_count,
            "nozzle_spacing_m": self.nozzle_spacing_m,
            "boom_width_m": self.boom_width_m,
            "operational_width_m": self.operational_width_m,
            "track_width_m": self.track.track_width_m,
            "tire_width_m": self.track.tire_width_m,
            "overlap_m": self.overlap_m,
            "overlap_mode": self.overlap_mode,
            "overlap_nozzle_count": self.overlap_nozzle_count,
            "resolved_overlap_m": self.resolved_overlap_m,
            "effective_pass_spacing_m": self.effective_pass_spacing_m,
            "sprayer_minimum_turn_radius_m": self.sprayer_minimum_turn_radius_m,
            "traffic": self.traffic.report() if self.traffic is not None else None,
        }


MachineProfile = PlanterMachine | SprayerMachine


def load_machine_presets(path: Path | None = None) -> dict[str, MachineProfile]:
    """Carrega cadastro JSON de maquinas."""
    if path is None:
        path = Path(__file__).resolve().parents[1] / "presets" / "machines.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    machines: dict[str, MachineProfile] = {}
    for item in raw.get("machines", []):
        track = MachineTrack(
            track_width_m=float(item["track_width_m"]),
            tire_width_m=float(item["tire_width_m"]),
        )
        kind = item.get("kind", "planter")
        if kind == "sprayer":
            traffic = None
            if "inner_clearance_m" in item and "outer_width_m" in item:
                from .sprayer_traffic_configuration import (
                    SprayerTrafficConfiguration,
                    TrafficMeasureResolution,
                )

                traffic = SprayerTrafficConfiguration(
                    boom_width_m=float(item["boom_width_m"]),
                    tire_width_m=float(item["tire_width_m"]),
                    inner_clearance_m=float(item["inner_clearance_m"]),
                    outer_width_m=float(item["outer_width_m"]),
                    resolution=TrafficMeasureResolution(
                        item.get("traffic_resolution", TrafficMeasureResolution.USE_OUTER.value)
                    ),
                )
                track = traffic.to_machine_track()
            machine = SprayerMachine(
                machine_id=item["machine_id"],
                name=item["name"],
                nozzle_count=int(item["nozzle_count"]),
                nozzle_spacing_m=float(item["nozzle_spacing_m"]),
                boom_width_m=float(item["boom_width_m"]),
                track=track,
                overlap_m=float(item.get("overlap_m", 0.0)),
                traffic=traffic,
            )
        else:
            machine = PlanterMachine(
                machine_id=item["machine_id"],
                name=item["name"],
                row_count=int(item["row_count"]),
                row_spacing_m=float(item["row_spacing_m"]),
                track=track,
                informed_operational_width_m=item.get("informed_operational_width_m"),
                gnss_offset_m=float(item.get("gnss_offset_m", 0.0)),
                implement_center_offset_m=float(item.get("implement_center_offset_m", 0.0)),
            )
        machine.validate()
        machines[machine.machine_id] = machine
    return machines
