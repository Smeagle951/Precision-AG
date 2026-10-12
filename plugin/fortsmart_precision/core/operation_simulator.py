# -*- coding: utf-8 -*-
"""Tipos de compatibilidade da validacao de corte por obstaculo.

O simulador visual de cobertura esta em ``visual_coverage_engine`` e nao usa
estes estados. Eles pertencem somente ao fluxo especializado CUT+borda.
"""

from enum import Enum


class SimulationStatus(str, Enum):
    VALID = "VALID"
    VALID_WITH_WARNINGS = "VALID_WITH_WARNINGS"
    INVALID = "INVALID"
