# -*- coding: utf-8 -*-
"""Estrategia LATERAL_DETOUR (isolada do corte existente)."""

from .clearance import (
    MachineEnvelope,
    ObstacleGroup,
    build_safe_obstacle,
    calculate_machine_envelope,
    detect_obstacle_conflict,
)
from .contour import (
    calculate_post_exit_point,
    calculate_pre_entry_point,
    extract_obstacle_contour,
    find_entry_exit_points,
)
from .engine import (
    DETOURED,
    NO_CONFLICT,
    DetourSection,
    LateralDetourResult,
    choose_detour_side,
    create_lateral_detour,
    required_turn_radius,
)
from .rows import PlanterRow, RowGenerationResult, generate_planter_rows, generate_row_offsets, validate_row_spacing
from .stitcher import WORK_OFF, WORK_ON, stitch_local_detour
from .transition import build_entry_transition, build_exit_transition, minimum_radius, validate_turn_radius
from .validator import DetourValidation, validate_final_path
