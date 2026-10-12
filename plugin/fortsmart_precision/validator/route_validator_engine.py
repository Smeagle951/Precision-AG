# -*- coding: utf-8 -*-
"""Motor de validacao da rota: detecta, classifica e localiza; nunca corrige.

Roda uma vez antes da simulacao. O simulador so consulta o resultado
(`ValidationResult.warnings_for_pass`), sem validacao pesada por frame.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import replace
from typing import Sequence

from ..core.simulation_route import RoutePassInput
from .boundary_validator import validate_boundary
from .crossing_validator import validate_crossings
from .geometry_validator import duplicated_routes, sharp_direction_changes, short_routes, structural_check
from .obstacle_validator import ObstacleInput, validate_obstacles
from .route_geometry import PreparedRoute
from .spacing_validator import validate_spacing
from .transition_validator import validate_transitions
from .validation_config import ValidationConfig
from .validation_result import ValidationResult
from .warning_model import RouteWarning, Severity

LOGGER = logging.getLogger("fortsmart_precision.validation")

_SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}


def _ordered(routes: Sequence[RoutePassInput]) -> list[RoutePassInput]:
    """Ordem da sequencia informada (sem sequencia: ordem de entrada). Nao reordena a rota."""
    return [
        item for _, item in sorted(
            enumerate(routes),
            key=lambda pair: (pair[1].sequence is None, pair[1].sequence or 0, pair[0]),
        )
    ]


class RouteValidatorEngine:
    def __init__(self, config: ValidationConfig | None = None):
        self.config = config or ValidationConfig()
        self._cache_key: str | None = None
        self._cache: ValidationResult | None = None

    def validate(
        self,
        routes: Sequence[RoutePassInput],
        allowed_area=None,
        obstacles: Sequence[ObstacleInput] = (),
        expected_spacing_m: float | None = None,
    ) -> ValidationResult:
        """Valida a rota inteira; mesma entrada devolve o mesmo resultado (cache por hash)."""
        config = self.config
        key = self._signature(routes, allowed_area, obstacles, expected_spacing_m)
        if key == self._cache_key and self._cache is not None:
            LOGGER.info("VALIDATION CACHE HIT route_count=%d", len(routes))
            return self._cache
        LOGGER.info(
            "VALIDATION START route_count=%d obstacle_count=%d expected_spacing=%s tolerance=%.2f",
            len(routes), len(obstacles),
            "-" if expected_spacing_m is None else f"{expected_spacing_m:.2f}",
            config.spacing_tolerance_m,
        )
        ordered = _ordered(routes)
        warnings, valid = structural_check(ordered)
        self._log("STRUCTURE", warnings)
        prepared = [
            PreparedRoute(item.id, index, item.sequence, item.route_type, item.segments)
            for index, item in valid
        ]
        steps = (
            ("BOUNDARY", lambda: validate_boundary(prepared, allowed_area, config)),
            ("OBSTACLE", lambda: validate_obstacles(prepared, obstacles, config)),
            ("CROSSING", lambda: validate_crossings(prepared, config)),
            ("SPACING", lambda: validate_spacing(prepared, expected_spacing_m, config)),
            ("DUPLICATE", lambda: duplicated_routes(prepared, config)),
            ("SHORT", lambda: short_routes(prepared, config)),
            ("DIRECTION", lambda: sharp_direction_changes(prepared, config)),
            ("TRANSITION", lambda: validate_transitions(prepared, expected_spacing_m, config)),
        )
        for name, run in steps:
            found = run()
            self._log(name, found)
            warnings.extend(found)
        warnings.sort(key=lambda w: (_SEVERITY_ORDER[w.severity], w.pass_index if w.pass_index is not None else -1))
        for number, warning in enumerate(warnings, start=1):
            warning.id = f"W{number:04d}"
        result = ValidationResult(
            route_count=len(routes),
            obstacle_count=len(obstacles),
            warnings=warnings,
            settings={**config.as_dict(), "expected_spacing_m": expected_spacing_m},
            signature=key,
        )
        LOGGER.info(
            "VALIDATION FINISHED critical=%d warning=%d info=%d",
            result.critical_count, result.warning_count, result.info_count,
        )
        self._cache_key, self._cache = key, result
        return result

    def with_config(self, **changes) -> "RouteValidatorEngine":
        return RouteValidatorEngine(replace(self.config, **changes))

    @staticmethod
    def _log(name: str, found: list[RouteWarning]) -> None:
        LOGGER.info("VALIDATOR: %s warnings=%d", name, len(found))

    def _signature(self, routes, allowed_area, obstacles, expected_spacing_m) -> str:
        digest = hashlib.sha1()
        digest.update(repr(self.config).encode())
        digest.update(repr(expected_spacing_m).encode())
        for item in routes:
            digest.update(repr((item.id, item.sequence, item.route_type, item.segments)).encode())
        digest.update(b"" if allowed_area is None else allowed_area.wkb)
        for obstacle in obstacles:
            digest.update(obstacle.id.encode())
            digest.update(b"" if obstacle.geometry is None else obstacle.geometry.wkb)
        return digest.hexdigest()
