# -*- coding: utf-8 -*-
"""Geometria declarada para o corte longitudinal por obstaculos.

Este contrato e independente do simulador visual de cobertura: ele descreve
somente a referencia e a barra ativa quando o operador escolhe CUT+bordadura.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MachineReferenceType(str, Enum):
    GNSS_ANTENNA = "GNSS_ANTENNA"
    HITCH_PIN = "HITCH_PIN"
    REAR_AXLE = "REAR_AXLE"
    FRONT_AXLE = "FRONT_AXLE"
    TRACTOR_FRONT = "TRACTOR_FRONT"
    IMPLEMENT_REFERENCE = "IMPLEMENT_REFERENCE"
    CUSTOM = "CUSTOM"


class ObstacleBorderMode(str, Enum):
    ONE_IMPLEMENT_PASS = "ONE_IMPLEMENT_PASS"
    CUSTOM = "CUSTOM"
    NONE = "NONE"


class ObstacleStrategy(str, Enum):
    CUT_FOR_BORDER = "CUT_FOR_BORDER"
    CUT_ONLY = "CUT_ONLY"
    AUTO = "AUTO"
    DIRECT_CONTOUR = "DIRECT_CONTOUR"


class WorkGeometryStatus(str, Enum):
    COMPLETE = "COMPLETE"
    GEOMETRY_INCOMPLETE = "GEOMETRY_INCOMPLETE"


class WorkState(str, Enum):
    WORKING = "WORKING"
    RAISED = "RAISED"


@dataclass(frozen=True)
class MachineWorkGeometry:
    work_width_m: float
    reference_type: MachineReferenceType = MachineReferenceType.GNSS_ANTENNA
    reference_to_working_line_longitudinal_m: float | None = None
    reference_lateral_offset_m: float = 0.0
    implement_lateral_offset_m: float = 0.0
    safety_margin_longitudinal_m: float = 0.0
    safety_margin_lateral_m: float = 0.0
    obstacle_border_width_m: float = 0.0
    border_mode: ObstacleBorderMode = ObstacleBorderMode.ONE_IMPLEMENT_PASS
    min_turn_radius_m: float | None = None
    longitudinal_anticipation_m: float = 0.0

    def validate(self) -> None:
        if self.work_width_m <= 0:
            raise ValueError("Largura de trabalho deve ser maior que zero.")
        for value, label in (
            (self.safety_margin_longitudinal_m, "Margem longitudinal"),
            (self.safety_margin_lateral_m, "Margem lateral"),
            (self.obstacle_border_width_m, "Bordadura"),
            (self.longitudinal_anticipation_m, "Antecipacao de desligamento"),
        ):
            if value < 0:
                raise ValueError(f"{label} nao pode ser negativa.")
        if self.border_mode is ObstacleBorderMode.CUSTOM and self.obstacle_border_width_m <= 0:
            raise ValueError("Bordadura personalizada deve ser maior que zero.")
        if self.min_turn_radius_m is not None and self.min_turn_radius_m <= 0:
            raise ValueError("Raio minimo de giro deve ser maior que zero.")

    @property
    def half_width_m(self) -> float:
        return self.work_width_m / 2.0

    @property
    def working_lateral_offset_m(self) -> float:
        return self.implement_lateral_offset_m - self.reference_lateral_offset_m

    @property
    def status(self) -> WorkGeometryStatus:
        return (
            WorkGeometryStatus.GEOMETRY_INCOMPLETE
            if self.reference_to_working_line_longitudinal_m is None
            else WorkGeometryStatus.COMPLETE
        )

    @property
    def reference_to_operation_m(self) -> float | None:
        return self.reference_to_working_line_longitudinal_m

    def desired_border_width_m(self) -> float:
        """Faixa lateral de protecao (passada de contorno); nunca distancia de corte."""
        if self.border_mode is ObstacleBorderMode.NONE:
            return 0.0
        if self.border_mode is ObstacleBorderMode.CUSTOM:
            return self.obstacle_border_width_m
        return self.work_width_m

    def required_cut_distance_m(self) -> float:
        """Folga longitudinal barra -> zona de seguranca; largura, espacamento e bordadura nao entram."""
        return self.safety_margin_longitudinal_m

    def to_dict(self) -> dict[str, object]:
        return {
            "work_width_m": self.work_width_m,
            "half_width_m": self.half_width_m,
            "reference_type": self.reference_type.value,
            "reference_to_working_line_longitudinal_m": self.reference_to_working_line_longitudinal_m,
            "reference_lateral_offset_m": self.reference_lateral_offset_m,
            "implement_lateral_offset_m": self.implement_lateral_offset_m,
            "working_lateral_offset_m": self.working_lateral_offset_m,
            "safety_margin_longitudinal_m": self.safety_margin_longitudinal_m,
            "safety_margin_lateral_m": self.safety_margin_lateral_m,
            "longitudinal_anticipation_m": self.longitudinal_anticipation_m,
            "border_mode": self.border_mode.value,
            "border_width_m": self.desired_border_width_m(),
            "min_turn_radius_m": self.min_turn_radius_m,
            "status": self.status.value,
        }
