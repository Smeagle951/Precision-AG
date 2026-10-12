# -*- coding: utf-8 -*-
"""Auditoria do desvio de obstaculos: raio operacional, clearance e cobertura.

Torna o resultado do desvio **auditavel**: em vez de apenas desenhar a linha,
o motor reporta os numeros que justificam a geometria gerada.

Modelo (identico para qualquer maquina — nada fixo no codigo):

    meia_largura   = largura_operacional / 2
    raio_operacional = raio_obstaculo + meia_largura + margem_seguranca

A condicao de colisao usa o CENTRO da maquina, mas protege as PONTAS:

    distancia(centro_maquina, obstaculo) < raio_operacional  ->  desvio

O `clearance` reportado e a folga que sobrou entre a ponta da barra e a
geometria fisica do obstaculo ao longo da trajetoria final:

    clearance = min(distancia(trajetoria, centro_obstaculo))
                - raio_obstaculo
                - meia_largura

Valor negativo significa que a ponta da barra invadiu o obstaculo — erro.
Valor proximo de zero significa que passou raspando a margem informada.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.machine_model import MachineProfile
from ..domain.obstacle_model import Obstacle
from .line_geometry import Point, distance, point_at_segment_t


@dataclass(frozen=True)
class ObstacleClearance:
    """Folga medida entre a ponta do implemento e um obstaculo."""

    obstacle_id: str
    pass_id: int
    min_center_distance_m: float
    obstacle_radius_m: float
    half_width_m: float

    @property
    def clearance_m(self) -> float:
        return self.min_center_distance_m - self.obstacle_radius_m - self.half_width_m

    @property
    def is_safe(self) -> bool:
        return self.clearance_m >= -1e-6


@dataclass
class AvoidanceAudit:
    """Relatorio auditavel de um ciclo de desvio."""

    operation_id: str
    machine_name: str
    operational_width_m: float
    half_width_m: float
    safety_margin_m: float
    obstacle_radius_m: float
    minimum_turn_radius_m: float
    extension_m: float
    obstacle_count: int = 0
    affected_pass_count: int = 0
    deviation_count: int = 0
    clearances: list[ObstacleClearance] = field(default_factory=list)
    unsafe: list[ObstacleClearance] = field(default_factory=list)

    @property
    def operational_radius_m(self) -> float:
        """Raio que o CENTRO da maquina deve manter do centro do obstaculo."""
        return self.obstacle_radius_m + self.half_width_m + self.safety_margin_m

    @property
    def min_clearance_m(self) -> float | None:
        if not self.clearances:
            return None
        return min(item.clearance_m for item in self.clearances)

    @property
    def ok(self) -> bool:
        return not self.unsafe

    def rows(self) -> list[tuple[str, str]]:
        """Linhas rotulo/valor para exibicao na GUI."""
        clearance = self.min_clearance_m
        clearance_txt = "—" if clearance is None else f"{clearance:,.2f} m".replace(",", ".")
        return [
            ("Barra / largura operacional", f"{self.operational_width_m:.2f} m"),
            ("Meia barra", f"{self.half_width_m:.2f} m"),
            ("Margem de seguranca", f"{self.safety_margin_m:.2f} m"),
            ("Raio do obstaculo", f"{self.obstacle_radius_m:.2f} m"),
            ("Raio operacional", f"{self.operational_radius_m:.2f} m"),
            ("Raio minimo de giro", f"{self.minimum_turn_radius_m:.2f} m"),
            ("Extensao fora do talhao", f"{self.extension_m:.2f} m"),
            ("Obstaculos encontrados", str(self.obstacle_count)),
            ("Passadas afetadas", str(self.affected_pass_count)),
            ("Desvios gerados", str(self.deviation_count)),
            ("Clearance minimo", clearance_txt),
        ]

    def summary_text(self) -> str:
        status = "OK" if self.ok else f"ATENCAO ({len(self.unsafe)} trecho(s) sem folga)"
        lines = [f"{label}: {value}" for label, value in self.rows()]
        lines.append(f"Situacao: {status}")
        return "\n".join(lines)


def _polyline_min_distance(points: list[Point] | tuple[Point, ...], target: Point) -> float:
    """Menor distancia entre a polilinha e um ponto (inclui interior dos segmentos)."""
    from .line_geometry import Segment

    pts = list(points)
    if not pts:
        return float("inf")
    if len(pts) == 1:
        return distance(pts[0], target)
    best = float("inf")
    for start, end in zip(pts, pts[1:]):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length2 = dx * dx + dy * dy
        if length2 <= 1e-12:
            best = min(best, distance(start, target))
            continue
        t = ((target[0] - start[0]) * dx + (target[1] - start[1]) * dy) / length2
        t = max(0.0, min(1.0, t))
        closest = point_at_segment_t(Segment(start, end), t)
        best = min(best, distance(closest, target))
    return best


def _obstacle_by_id(obstacles: list[Obstacle]) -> dict[str, Obstacle]:
    return {item.obstacle_id: item for item in obstacles}


def build_avoidance_audit(
    *,
    operation_id: str,
    machine: MachineProfile,
    obstacles: list[Obstacle],
    avoided_paths: list,
    safety_margin_m: float,
    minimum_turn_radius_m: float = 0.0,
    extension_m: float = 0.0,
) -> AvoidanceAudit:
    """Mede o resultado real do desvio contra a geometria dos obstaculos."""
    half_w = float(getattr(machine, "half_operational_width_m", 0.0) or 0.0)
    width = float(getattr(machine, "operational_width_m", half_w * 2.0) or 0.0)
    radii = [float(item.obstacle_radius_m or 0.0) for item in obstacles]
    obstacle_radius = max(radii) if radii else 0.0

    audit = AvoidanceAudit(
        operation_id=operation_id,
        machine_name=str(getattr(machine, "name", "") or ""),
        operational_width_m=width,
        half_width_m=half_w,
        safety_margin_m=float(safety_margin_m or 0.0),
        obstacle_radius_m=obstacle_radius,
        minimum_turn_radius_m=float(minimum_turn_radius_m or 0.0),
        extension_m=float(extension_m or 0.0),
        obstacle_count=len(obstacles),
    )

    relevant = [
        path
        for path in avoided_paths
        if str(getattr(path, "operation_id", "")) == operation_id or not operation_id
    ]
    audit.deviation_count = len(relevant)
    audit.affected_pass_count = len({getattr(path, "pass_id", -1) for path in relevant})

    by_id = _obstacle_by_id(obstacles)
    for path in relevant:
        obstacle_id = str(getattr(path, "obstacle_id", ""))
        points = list(getattr(path, "modified_points", ()) or ())
        if len(points) < 2:
            continue
        for part in (obstacle_id.split("+") if obstacle_id else []):
            obstacle = by_id.get(part)
            if obstacle is None:
                continue
            min_center = _polyline_min_distance(points, obstacle.center)
            item = ObstacleClearance(
                obstacle_id=part,
                pass_id=int(getattr(path, "pass_id", 0) or 0),
                min_center_distance_m=min_center,
                obstacle_radius_m=float(obstacle.obstacle_radius_m or 0.0),
                half_width_m=half_w,
            )
            audit.clearances.append(item)
            if not item.is_safe:
                audit.unsafe.append(item)
    return audit


def audit_table(audit: AvoidanceAudit) -> list[dict[str, object]]:
    """Tabela por obstaculo/passada para export ou GUI."""
    return [
        {
            "pass_id": item.pass_id,
            "obstacle_id": item.obstacle_id,
            "min_center_distance_m": round(item.min_center_distance_m, 3),
            "clearance_m": round(item.clearance_m, 3),
            "status": "OK" if item.is_safe else "SEM FOLGA",
        }
        for item in audit.clearances
    ]
