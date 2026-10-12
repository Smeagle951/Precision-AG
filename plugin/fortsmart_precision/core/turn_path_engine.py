# -*- coding: utf-8 -*-
"""Motor de caminhos de volta entre passadas centrais."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from ..domain.boundary_areas import BoundaryAreas, headland_available_width_m
from ..domain.turn_configuration import (
    SUPPORTED_TURN_TYPES,
    TurnConfiguration,
    TurnFinishMode,
    TurnStatus,
    TurnType,
)
from .line_geometry import (
    MultiPolygon,
    Point,
    add,
    arc_polyline,
    distance,
    drop_polyline,
    mul,
    normalize,
    omega_polyline,
    point_in_multipolygon,
    polyline_length,
    segment_samples,
    sub,
    three_point_polyline,
)
from .pass_sequence_engine import PassConnection, build_pass_sequence
from .parallel_pass_engine import ParallelPass


class TurnPathError(ValueError):
    """Erro do motor de voltas."""


@dataclass(frozen=True)
class TurnPath:
    fs_id: str
    from_pass: int
    to_pass: int
    turn_type: str
    turn_location: str
    sequence_no: int
    radius_m: float | None
    required_width_m: float | None
    available_width_m: float
    clearance_m: float | None
    status: str
    is_estimated: bool
    outside_boundary: bool
    external_area_id: str
    length_m: float
    points: tuple[Point, ...]
    label: str
    configured_extension_m: float | None = None
    minimum_extension_m: float | None = None
    is_special_maneuver: bool = False

    def attributes(self) -> dict[str, object]:
        return {
            "fs_id": self.fs_id,
            "from_pass": self.from_pass,
            "to_pass": self.to_pass,
            "turn_type": self.turn_type,
            "turn_location": self.turn_location,
            "sequence_no": self.sequence_no,
            "radius_m": self.radius_m,
            "required_width_m": self.required_width_m,
            "available_width_m": self.available_width_m,
            "clearance_m": self.clearance_m,
            "status": self.status,
            "is_estimated": self.is_estimated,
            "outside_boundary": self.outside_boundary,
            "external_area_id": self.external_area_id,
            "length_m": self.length_m,
            "label": self.label,
            "configured_extension_m": self.configured_extension_m,
            "minimum_extension_m": self.minimum_extension_m,
            "is_special_maneuver": self.is_special_maneuver,
        }

    @property
    def is_valid_for_save(self) -> bool:
        return self.status in {TurnStatus.VALID.value, TurnStatus.VALID_LOW_MARGIN.value}


@dataclass(frozen=True)
class TurnPathResult:
    turns: list[TurnPath]
    connections: list[PassConnection]
    report: dict[str, object]


def _choose_bulge(
    start: Point,
    end: Point,
    areas: BoundaryAreas,
    *,
    prefer_external: bool = False,
) -> bool:
    """Prefere o lado do arco que permanece na area autorizada."""
    left = arc_polyline(start, end, bulge_left=True, segments=8)
    right = arc_polyline(start, end, bulge_left=False, segments=8)
    left_mid = left[len(left) // 2]
    right_mid = right[len(right) // 2]

    def score(point: Point) -> int:
        value = 0
        if prefer_external:
            if areas.point_in_external_turn(point):
                value += 3
            if areas.point_in_operational(point):
                value -= 1
        else:
            if areas.point_in_headland(point):
                value += 2
            if areas.point_in_operational(point) and not areas.point_in_inner(point):
                value += 1
            if areas.point_in_inner(point):
                value -= 2
        return value

    left_score = score(left_mid)
    right_score = score(right_mid)
    if left_score > right_score:
        return True
    if right_score > left_score:
        return False
    return True


def _exit_forward(connection: PassConnection) -> Point:
    """Direcao de saida da passada de origem."""
    segment = connection.from_pass.clipped_segment
    if connection.travel_reversed_on_from:
        return normalize(sub(segment.start, segment.end))
    return normalize(sub(segment.end, segment.start))


def _entry_approach(connection: PassConnection) -> Point:
    """Direcao de aproximacao ate a entrada da passada destino (para tras no traco)."""
    segment = connection.to_pass.clipped_segment
    if connection.travel_reversed_on_to:
        # Viaja end->start; aproxima-se pelo end vindo de fora = direcao start->end invertida na saida
        return normalize(sub(segment.end, segment.start))
    return normalize(sub(segment.start, segment.end))


def _choose_drop_forward(start: Point, end: Point, connection: PassConnection, areas: BoundaryAreas) -> Point:
    """Escolhe o sentido longitudinal da gota que cai na area autorizada."""
    travel = _exit_forward(connection)
    candidates = (travel, mul(travel, -1.0))
    best = travel
    best_score = -1
    radius = connection.from_pass.spacing_m / 2.0
    for fwd in candidates:
        path = drop_polyline(start, end, forward=fwd, radius_m=radius, segments=8)
        mid = path[len(path) // 2]
        score = 0
        if areas.point_in_headland(mid):
            score += 2
        if areas.point_in_external_turn(mid):
            score += 3
        if areas.point_in_operational(mid) and not areas.point_in_inner(mid):
            score += 1
        if score > best_score:
            best_score = score
            best = fwd
    return best


def _pass_spacing(connection: PassConnection) -> float:
    spacing = abs(connection.from_pass.offset_m - connection.to_pass.offset_m)
    if spacing <= 0:
        return connection.from_pass.spacing_m
    return spacing


def _evaluate_path(
    points: list[Point],
    *,
    config: TurnConfiguration,
    areas: BoundaryAreas,
    available_width_m: float,
    pass_spacing_m: float,
    obstacles: MultiPolygon,
    outside_mode: bool = False,
) -> tuple[str, bool, float | None, float | None]:
    """Retorna status, is_estimated, required_width, clearance."""
    is_estimated = not config.has_complete_machine_params()
    required = config.required_turn_width_m(pass_spacing_m)
    clearance = None if required is None else available_width_m - required

    samples = segment_samples(points, densify_m=2.0)
    interior_samples = samples[1:-1] if len(samples) > 2 else samples
    hits_inner = False
    hits_obstacle = False
    leaves_headland = False
    outside_operational = False
    leaves_authorized_external = False

    max_outside = config.max_outside_distance_m
    for point in interior_samples:
        in_operational = areas.point_in_operational(point)
        in_external = areas.point_in_external_turn(point)
        if not in_operational:
            outside_operational = True
            if outside_mode:
                if not in_external:
                    leaves_authorized_external = True
                if max_outside is not None:
                    # Distancia aproximada ao operacional: se ponto fora e longe demais.
                    # Usa rejeicao se estiver fora da area externa (ja coberta) ou
                    # se a area externa existir mas o ponto estiver alem do envelope max.
                    pass
            elif config.finish_mode == TurnFinishMode.INSIDE_HEADLAND:
                pass
        if config.avoid_planted_area and areas.point_in_inner(point):
            hits_inner = True
        if not outside_mode and areas.headland_area is not None and not areas.point_in_headland(point):
            if not in_operational or areas.point_in_inner(point):
                leaves_headland = True
        if outside_mode and not in_external and not in_operational:
            leaves_authorized_external = True
        if config.avoid_obstacles and obstacles and point_in_multipolygon(point, obstacles):
            hits_obstacle = True

    if hits_obstacle:
        return TurnStatus.IMPOSSIBLE.value, is_estimated, required, clearance
    if outside_mode:
        if leaves_authorized_external:
            return TurnStatus.IMPOSSIBLE.value, is_estimated, required, clearance
        if hits_inner and config.avoid_planted_area:
            return TurnStatus.IMPOSSIBLE.value, is_estimated, required, clearance
    else:
        if outside_operational and config.finish_mode == TurnFinishMode.INSIDE_HEADLAND:
            return TurnStatus.IMPOSSIBLE.value, is_estimated, required, clearance
        if hits_inner and config.avoid_planted_area:
            return TurnStatus.IMPOSSIBLE.value, is_estimated, required, clearance
        if leaves_headland and config.finish_mode == TurnFinishMode.INSIDE_HEADLAND:
            return TurnStatus.IMPOSSIBLE.value, is_estimated, required, clearance

    # Extensao insuficiente (volta externa).
    if outside_mode:
        ext_status = config.extension_status()
        if ext_status["status"] == "insufficient":
            return TurnStatus.IMPOSSIBLE.value, False, required, clearance
        if ext_status["status"] == "insufficient_data":
            is_estimated = True

    if is_estimated:
        return TurnStatus.INSUFFICIENT_DATA.value, True, required, clearance

    assert clearance is not None and required is not None
    if clearance < 0:
        return TurnStatus.IMPOSSIBLE.value, False, required, clearance
    if clearance < config.safety.recommended_clearance_m:
        return TurnStatus.VALID_LOW_MARGIN.value, False, required, clearance
    return TurnStatus.VALID.value, False, required, clearance


def _extend_endpoint(point: Point, direction: Point, extension_m: float) -> Point:
    return add(point, mul(direction, extension_m))


def _build_u_turn(
    connection: PassConnection,
    config: TurnConfiguration,
    areas: BoundaryAreas,
    obstacles: MultiPolygon,
    *,
    turn_type: TurnType = TurnType.U,
    label: str = "U",
    outside_mode: bool = False,
) -> TurnPath:
    if outside_mode:
        ext_out = config.resolved_extension_after_m()
        start = _extend_endpoint(connection.from_exit, _exit_forward(connection), ext_out)
        end = _extend_endpoint(connection.to_entry, _entry_approach(connection), ext_out)
        # Conectar com hastes: saida -> ponto externo -> arco -> ponto externo destino -> entrada
        bulge_left = _choose_bulge(start, end, areas, prefer_external=True)
        arc = arc_polyline(start, end, bulge_left=bulge_left, segments=20)
        points = [connection.from_exit, *arc, connection.to_entry]
        turn_location = "external"
        available = config.max_outside_distance_m if config.max_outside_distance_m is not None else ext_out
        # Disponivel efetivo: extensao configurada (comparada tambem via extension_status).
        available = float(available)
    else:
        start = connection.from_exit
        end = connection.to_entry
        bulge_left = _choose_bulge(start, end, areas)
        points = arc_polyline(start, end, bulge_left=bulge_left, segments=20)
        turn_location = "headland"
        available = headland_available_width_m(areas)

    geometric_radius = distance(start, end) / 2.0
    pass_spacing = _pass_spacing(connection)

    status, is_estimated, required, clearance = _evaluate_path(
        points,
        config=config,
        areas=areas,
        available_width_m=available if not outside_mode else max(available, config.resolved_extension_after_m()),
        pass_spacing_m=pass_spacing,
        obstacles=obstacles,
        outside_mode=outside_mode,
    )

    machine_radius = config.min_turn_radius_m
    if (
        not outside_mode
        and machine_radius is not None
        and geometric_radius + 1e-6 < machine_radius
        and turn_type in {TurnType.U, TurnType.SKIP_PASS}
    ):
        status = TurnStatus.IMPOSSIBLE.value
        is_estimated = False
        required = config.required_turn_width_m(pass_spacing)
        clearance = None if required is None else available - required

    ext_status = config.extension_status() if outside_mode else None
    return TurnPath(
        fs_id=str(uuid4()),
        from_pass=connection.from_pass.pass_no,
        to_pass=connection.to_pass.pass_no,
        turn_type=turn_type.value,
        turn_location=turn_location,
        sequence_no=connection.sequence_no,
        radius_m=machine_radius if machine_radius is not None else geometric_radius,
        required_width_m=required,
        available_width_m=available,
        clearance_m=clearance,
        status=status,
        is_estimated=is_estimated,
        outside_boundary=outside_mode,
        external_area_id=config.external_area_id if outside_mode else "",
        length_m=polyline_length(points),
        points=tuple(points),
        label=label,
        configured_extension_m=None if not outside_mode else float(ext_status["configured_m"]),
        minimum_extension_m=None if not outside_mode or ext_status["minimum_m"] is None else float(ext_status["minimum_m"]),
    )


def _build_drop_turn(
    connection: PassConnection,
    config: TurnConfiguration,
    areas: BoundaryAreas,
    obstacles: MultiPolygon,
    *,
    outside_mode: bool = False,
) -> TurnPath:
    if outside_mode:
        ext_out = config.resolved_extension_after_m()
        start = _extend_endpoint(connection.from_exit, _exit_forward(connection), ext_out)
        end = _extend_endpoint(connection.to_entry, _entry_approach(connection), ext_out)
        turn_location = "external"
        available = float(
            config.max_outside_distance_m
            if config.max_outside_distance_m is not None
            else ext_out
        )
    else:
        start = connection.from_exit
        end = connection.to_entry
        turn_location = "headland"
        available = headland_available_width_m(areas)

    pass_spacing = _pass_spacing(connection)
    geometric_radius = (
        config.min_turn_radius_m
        if config.min_turn_radius_m is not None
        else max(pass_spacing / 2.0, distance(start, end) / 2.0)
    )
    forward = _choose_drop_forward(start, end, connection, areas)
    arc = drop_polyline(start, end, forward=forward, radius_m=geometric_radius, segments=24)
    points = [connection.from_exit, *arc, connection.to_entry] if outside_mode else arc

    status, is_estimated, required, clearance = _evaluate_path(
        points,
        config=config,
        areas=areas,
        available_width_m=available if not outside_mode else max(available, config.resolved_extension_after_m()),
        pass_spacing_m=pass_spacing,
        obstacles=obstacles,
        outside_mode=outside_mode,
    )

    ext_status = config.extension_status() if outside_mode else None
    return TurnPath(
        fs_id=str(uuid4()),
        from_pass=connection.from_pass.pass_no,
        to_pass=connection.to_pass.pass_no,
        turn_type=TurnType.DROP.value,
        turn_location=turn_location,
        sequence_no=connection.sequence_no,
        radius_m=config.min_turn_radius_m if config.min_turn_radius_m is not None else geometric_radius,
        required_width_m=required,
        available_width_m=available,
        clearance_m=clearance,
        status=status,
        is_estimated=is_estimated,
        outside_boundary=outside_mode,
        external_area_id=config.external_area_id if outside_mode else "",
        length_m=polyline_length(points),
        points=tuple(points),
        label="GOTA",
        configured_extension_m=None if not outside_mode else float(ext_status["configured_m"]),
        minimum_extension_m=None if not outside_mode or ext_status["minimum_m"] is None else float(ext_status["minimum_m"]),
    )


def _build_shaped_turn(
    connection: PassConnection,
    config: TurnConfiguration,
    areas: BoundaryAreas,
    obstacles: MultiPolygon,
    *,
    turn_type: TurnType,
    label: str,
    points_builder,
    outside_mode: bool = False,
    special: bool = False,
) -> TurnPath:
    if outside_mode:
        ext_out = config.resolved_extension_after_m()
        start = _extend_endpoint(connection.from_exit, _exit_forward(connection), ext_out)
        end = _extend_endpoint(connection.to_entry, _entry_approach(connection), ext_out)
        turn_location = "external"
        available = float(
            config.max_outside_distance_m
            if config.max_outside_distance_m is not None
            else ext_out
        )
    else:
        start = connection.from_exit
        end = connection.to_entry
        turn_location = "headland"
        available = headland_available_width_m(areas)

    pass_spacing = _pass_spacing(connection)
    geometric_radius = (
        config.min_turn_radius_m
        if config.min_turn_radius_m is not None
        else max(pass_spacing / 2.0, distance(start, end) / 2.0)
    )
    forward = _choose_drop_forward(start, end, connection, areas)
    arc = points_builder(start, end, forward=forward, radius_m=geometric_radius)
    points = [connection.from_exit, *arc, connection.to_entry] if outside_mode else list(arc)

    status, is_estimated, required, clearance = _evaluate_path(
        points,
        config=config,
        areas=areas,
        available_width_m=available if not outside_mode else max(available, config.resolved_extension_after_m()),
        pass_spacing_m=pass_spacing,
        obstacles=obstacles,
        outside_mode=outside_mode,
    )
    if config.is_towed_implement() and status == TurnStatus.VALID.value:
        # Rebocado: rebaixa para margem baixa quando a folga e apertada.
        if clearance is not None and clearance < config.safety.recommended_clearance_m * 1.5:
            status = TurnStatus.VALID_LOW_MARGIN.value

    ext_status = config.extension_status() if outside_mode else None
    return TurnPath(
        fs_id=str(uuid4()),
        from_pass=connection.from_pass.pass_no,
        to_pass=connection.to_pass.pass_no,
        turn_type=turn_type.value,
        turn_location=turn_location,
        sequence_no=connection.sequence_no,
        radius_m=config.min_turn_radius_m if config.min_turn_radius_m is not None else geometric_radius,
        required_width_m=required,
        available_width_m=available,
        clearance_m=clearance,
        status=status,
        is_estimated=is_estimated,
        outside_boundary=outside_mode,
        external_area_id=config.external_area_id if outside_mode else "",
        length_m=polyline_length(points),
        points=tuple(points),
        label=label,
        configured_extension_m=None if not outside_mode else float(ext_status["configured_m"]),
        minimum_extension_m=None if not outside_mode or ext_status["minimum_m"] is None else float(ext_status["minimum_m"]),
        is_special_maneuver=special,
    )


def _build_turn_for_connection(
    connection: PassConnection,
    config: TurnConfiguration,
    areas: BoundaryAreas,
    obstacles: MultiPolygon,
    *,
    outside_mode: bool = False,
) -> TurnPath:
    if config.turn_type == TurnType.DROP:
        return _build_drop_turn(connection, config, areas, obstacles, outside_mode=outside_mode)
    if config.turn_type == TurnType.OMEGA:
        return _build_shaped_turn(
            connection,
            config,
            areas,
            obstacles,
            turn_type=TurnType.OMEGA,
            label="OMEGA",
            points_builder=omega_polyline,
            outside_mode=outside_mode,
        )
    if config.turn_type == TurnType.THREE_POINT:
        return _build_shaped_turn(
            connection,
            config,
            areas,
            obstacles,
            turn_type=TurnType.THREE_POINT,
            label="3P",
            points_builder=three_point_polyline,
            outside_mode=outside_mode,
            special=True,
        )
    if config.turn_type == TurnType.SKIP_PASS:
        return _build_u_turn(
            connection,
            config,
            areas,
            obstacles,
            turn_type=TurnType.SKIP_PASS,
            label="PULA",
            outside_mode=outside_mode,
        )
    return _build_u_turn(connection, config, areas, obstacles, outside_mode=outside_mode)


def generate_turn_paths(
    passes: list[ParallelPass],
    config: TurnConfiguration,
    areas: BoundaryAreas,
    obstacles: MultiPolygon | None = None,
) -> TurnPathResult:
    """Gera caminhos de volta (Etapa 4: U/gota/pula/omega/3P, bordadura ou externa)."""
    config.validate()
    obstacles = obstacles or []

    if not config.generate_turns or config.finish_mode == TurnFinishMode.NONE:
        return TurnPathResult(
            turns=[],
            connections=[],
            report={
                "mode": TurnFinishMode.NONE.value,
                "turn_count": 0,
                "message": "Sem volta automatica.",
            },
        )

    if config.turn_type not in SUPPORTED_TURN_TYPES:
        raise TurnPathError(f"Tipo '{config.turn_type.value}' nao implementado nesta etapa.")

    outside_mode = config.finish_mode in {
        TurnFinishMode.OUTSIDE_BOUNDARY,
        TurnFinishMode.MANEUVER_AREA,
    }

    if config.finish_mode == TurnFinishMode.INSIDE_HEADLAND:
        if areas.reserved_width_m <= 0 or not areas.headland_area:
            raise TurnPathError("Bordadura inexistente para volta interna.")
    elif outside_mode:
        if not areas.external_turn_area:
            raise TurnPathError("Area externa autorizada nao informada para volta externa.")
        if config.finish_mode == TurnFinishMode.OUTSIDE_BOUNDARY and not config.allow_outside_boundary:
            raise TurnPathError("Saida do limite exige autorizacao explicita.")
        if config.finish_mode == TurnFinishMode.MANEUVER_AREA and not config.use_maneuver_area:
            raise TurnPathError("Area de manobra especifica nao foi habilitada.")
    else:
        raise TurnPathError(
            f"Modo '{config.finish_mode.value}' nao implementado nesta etapa."
        )

    sequence_mode = config.effective_sequence_mode()
    connections = build_pass_sequence(
        passes,
        mode=sequence_mode,
        custom_order=config.custom_sequence,
        skip_passes=config.resolved_skip_passes(),
        block_size=config.block_size,
    )
    turns = [
        _build_turn_for_connection(conn, config, areas, obstacles, outside_mode=outside_mode)
        for conn in connections
    ]

    summary = {
        TurnStatus.VALID.value: 0,
        TurnStatus.VALID_LOW_MARGIN.value: 0,
        TurnStatus.IMPOSSIBLE.value: 0,
        TurnStatus.INSUFFICIENT_DATA.value: 0,
    }
    for turn in turns:
        summary[turn.status] = summary.get(turn.status, 0) + 1

    return TurnPathResult(
        turns=turns,
        connections=connections,
        report={
            "mode": config.finish_mode.value,
            "turn_type": config.turn_type.value,
            "sequence_mode": sequence_mode.value,
            "skip_passes": config.resolved_skip_passes(),
            "block_size": config.block_size,
            "special_maneuver_count": sum(1 for turn in turns if turn.is_special_maneuver),
            "towed_implement": config.is_towed_implement(),
            "turn_count": len(turns),
            "available_width_m": (
                headland_available_width_m(areas)
                if not outside_mode
                else config.resolved_extension_after_m()
            ),
            "extension_status": config.extension_status() if outside_mode else None,
            "status_counts": summary,
            "is_estimated": not config.has_complete_machine_params(),
            "config": config.report(),
            "areas": areas.report(),
        },
    )


def filter_savable_turns(turns: list[TurnPath], *, include_low_margin: bool = True) -> list[TurnPath]:
    allowed = {TurnStatus.VALID.value}
    if include_low_margin:
        allowed.add(TurnStatus.VALID_LOW_MARGIN.value)
    return [turn for turn in turns if turn.status in allowed]
