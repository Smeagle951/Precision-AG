# -*- coding: utf-8 -*-
"""Processing Provider do FortSmart Precision."""

from qgis.core import QgsProcessingProvider

from .algorithms.create_parallel_agricultural_lines import CreateParallelAgriculturalLinesAlgorithm
from .algorithms.create_operation_passes import CreateOperationPassesAlgorithm
from .algorithms.create_turn_paths import CreateTurnPathsAlgorithm
from .algorithms.generate_precision_lines import GeneratePrecisionLinesAlgorithm
from .algorithms.create_obstacles import CreateObstaclesAlgorithm
from .algorithms.generate_obstacle_avoidance import GenerateObstacleAvoidanceAlgorithm
from .algorithms.simulate_obstacle_avoidance import SimulateObstacleAvoidanceAlgorithm
from .algorithms.simulate_real_operation import SimulateRealOperationAlgorithm
from .algorithms.simulate_obstacle_border_cut import SimulateObstacleBorderCutAlgorithm
from .algorithms.validate_precision_project import ValidatePrecisionProjectAlgorithm
from .algorithms.health_check import HealthCheckAlgorithm
from .algorithms.import_field_boundary import ImportFieldBoundaryAlgorithm
from .algorithms.inspect_input import InspectInputAlgorithm


class FortSmartProvider(QgsProcessingProvider):
    """Agrupa algoritmos Processing do plugin."""

    def id(self):
        return "fortsmart_precision"

    def name(self):
        return "FortSmart Precision"

    def longName(self):
        return "FortSmart Precision Planner"

    def loadAlgorithms(self):
        self.addAlgorithm(HealthCheckAlgorithm())
        self.addAlgorithm(InspectInputAlgorithm())
        self.addAlgorithm(ImportFieldBoundaryAlgorithm())
        self.addAlgorithm(CreateParallelAgriculturalLinesAlgorithm())
        self.addAlgorithm(CreateOperationPassesAlgorithm())
        self.addAlgorithm(CreateTurnPathsAlgorithm())
        self.addAlgorithm(GeneratePrecisionLinesAlgorithm())
        self.addAlgorithm(ValidatePrecisionProjectAlgorithm())
        self.addAlgorithm(CreateObstaclesAlgorithm())
        self.addAlgorithm(GenerateObstacleAvoidanceAlgorithm())
        self.addAlgorithm(SimulateObstacleAvoidanceAlgorithm())
        self.addAlgorithm(SimulateRealOperationAlgorithm())
        self.addAlgorithm(SimulateObstacleBorderCutAlgorithm())
