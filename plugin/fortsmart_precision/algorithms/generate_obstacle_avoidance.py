# -*- coding: utf-8 -*-
"""Algoritmo Processing: gerar desvio de obstaculos."""

from __future__ import annotations

from .simulate_obstacle_avoidance import SimulateObstacleAvoidanceAlgorithm


class GenerateObstacleAvoidanceAlgorithm(SimulateObstacleAvoidanceAlgorithm):
    def name(self):
        return "generate_obstacle_avoidance"

    def displayName(self):
        return self.tr("Gerar desvio de obstaculos (Precision Lines v2)")
