# -*- coding: utf-8 -*-
"""Modelo interno do projeto Precision Lines."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from ..core.line_geometry import MultiPolygon, Point, distance
from ..core.ab_direction import ab_has_valid_direction, resolve_ab_direction_end
from .application_zone import ApplicationZone
from .avoidance_configuration import AvoidanceConfiguration
from .guidance_reference import GuidanceReference
from .headland_layout import HeadlandLayout
from .machine_model import MachineProfile, PlanterMachine, SprayerMachine
from .obstacle_model import Obstacle
from .path_smoothing_configuration import PathSmoothingConfiguration
from .planting_avoidance_configuration import PlantingAvoidanceConfiguration
from .planting_kinematics import PlantingKinematics
from .processing_profile import ProcessingProfile, final_profile


class PrecisionProjectError(ValueError):
    """Erro no modelo de projeto."""


# Cabeceira da pulverizacao (como sai de uma passada e entra na proxima).
# Independente da bordadura (HeadlandLayout) e do headland_turn_mode do plantio.
SPRAY_HEADLAND_TURN_MANUAL = "manual"
SPRAY_HEADLAND_TURN_AUTOMATIC = "automatic"
SPRAY_HEADLAND_TURN_MODES = (SPRAY_HEADLAND_TURN_MANUAL, SPRAY_HEADLAND_TURN_AUTOMATIC)


@dataclass(frozen=True)
class FieldGeometry:
    field_boundary: MultiPolygon
    operational_boundary: MultiPolygon
    crs_authid: str = ""
    field_id: str = field(default_factory=lambda: str(uuid4()))

    def validate(self) -> None:
        if not self.operational_boundary:
            raise PrecisionProjectError("Limite operacional vazio.")
        if not self.crs_authid:
            raise PrecisionProjectError("CRS do talhao obrigatorio.")


@dataclass(frozen=True)
class ABLine:
    start: Point
    end: Point
    ab_id: str = field(default_factory=lambda: str(uuid4()))
    path_points: tuple[Point, ...] = ()

    def validate(self) -> None:
        if not ab_has_valid_direction(self.start, self.end, self.path_points):
            raise PrecisionProjectError(
                "Linha A-B invalida: pontos A e B coincidem ou estao muito proximos."
            )

    def line_points(self) -> tuple[Point, ...]:
        """Geometria mestra completa (curva preservada)."""
        from ..core.line_geometry import sanitize_master_polyline

        if len(self.path_points) >= 2:
            return tuple(sanitize_master_polyline(self.path_points))
        return (self.start, self.end)


@dataclass(frozen=True)
class PrecisionOperation:
    operation_id: str
    machine: MachineProfile
    headland: HeadlandLayout = field(default_factory=HeadlandLayout)
    extension_m: float = 10.0

    def validate(self) -> None:
        if not self.operation_id:
            raise PrecisionProjectError("operation_id obrigatorio.")
        self.machine.validate()
        self.headland.validate()
        if self.extension_m < 0:
            raise PrecisionProjectError("Extensao nao pode ser negativa.")

    @property
    def pass_spacing_m(self) -> float:
        if isinstance(self.machine, SprayerMachine):
            return self.machine.effective_pass_spacing_m
        if isinstance(self.machine, PlanterMachine):
            return self.machine.effective_pass_spacing_m
        return self.machine.operational_width_m


@dataclass(frozen=True)
class PrecisionProject:
    field: FieldGeometry
    ab_line: ABLine
    planting: PrecisionOperation | None = None
    spraying: PrecisionOperation | None = None
    application_zone: ApplicationZone | None = None
    guidance_reference: GuidanceReference | None = None
    obstacles: tuple[Obstacle, ...] = ()
    avoidance: AvoidanceConfiguration = field(default_factory=AvoidanceConfiguration)
    planting_avoidance: PlantingAvoidanceConfiguration = field(
        default_factory=PlantingAvoidanceConfiguration
    )
    planting_kinematics: PlantingKinematics | None = None
    line_smoothing: PathSmoothingConfiguration = field(default_factory=PathSmoothingConfiguration)
    shutoff_on_tramlines: bool = True
    shutoff_on_headland_inner: bool = True
    headland_turn_mode: str = "extend"  # extend | offset_turn
    processing: ProcessingProfile = field(default_factory=final_profile)
    spray_headland_turn_mode: str = SPRAY_HEADLAND_TURN_MANUAL

    def validate(self) -> None:
        self.field.validate()
        self.ab_line.validate()
        self.processing.validate()
        if self.guidance_reference is not None:
            self.guidance_reference.validate()
        self.avoidance.validate()
        self.planting_avoidance.validate()
        if self.planting_kinematics is not None:
            self.planting_kinematics.validate()
        for obstacle in self.obstacles:
            obstacle.validate()
        if self.application_zone is not None:
            self.application_zone.validate()
        if self.planting is None and self.spraying is None:
            raise PrecisionProjectError("Informe ao menos uma operacao (plantio ou pulverizacao).")
        if self.planting is not None:
            if not isinstance(self.planting.machine, PlanterMachine):
                raise PrecisionProjectError("Operacao de plantio exige plantadeira.")
            self.planting.validate()
        if self.spraying is not None:
            if not isinstance(self.spraying.machine, SprayerMachine):
                raise PrecisionProjectError("Operacao de pulverizacao exige pulverizador.")
            self.spraying.validate()
        if self.headland_turn_mode not in {"extend", "offset_turn"}:
            raise PrecisionProjectError(
                "headland_turn_mode deve ser 'extend' ou 'offset_turn'."
            )
        if self.spray_headland_turn_mode not in SPRAY_HEADLAND_TURN_MODES:
            raise PrecisionProjectError(
                "spray_headland_turn_mode deve ser 'manual' ou 'automatic'."
            )

    def effective_guidance(self) -> GuidanceReference:
        if self.guidance_reference is not None:
            return self.guidance_reference
        return GuidanceReference.from_ab(self.ab_line.start, self.ab_line.end)

    def effective_ab_line(self) -> ABLine:
        guidance = self.effective_guidance()
        path = guidance.full_path_points()
        end = resolve_ab_direction_end(guidance.start, guidance.end, path)
        return ABLine(
            start=guidance.start,
            end=end,
            ab_id=guidance.reference_id,
            path_points=path,
        )

    def effective_application_zone(self) -> ApplicationZone:
        if self.application_zone is not None:
            return self.application_zone
        return ApplicationZone.from_single_field(
            self.field.field_boundary,
            self.field.operational_boundary,
            self.field.crs_authid,
            field_id=self.field.field_id,
        )
