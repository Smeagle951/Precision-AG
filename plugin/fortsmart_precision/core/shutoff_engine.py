# -*- coding: utf-8 -*-
"""Motor de desligamento linha a linha por cruzamento com rastros/tramlines/bordadura."""

from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import uuid4

from .line_geometry import (
    MultiPolygon,
    Point,
    Segment,
    add,
    distance,
    dot,
    mul,
    point_in_multipolygon,
    polyline_length,
    segment_samples,
    simplify_multipolygon_for_pip,
    split_polyline_by_multipolygon,
    sub,
)
from .row_engine import PlantingRow
from .tire_track_engine import TireTrack
from .tramline_engine import TramlineZone


class ShutoffEngineError(ValueError):
    """Erro no motor de desligamento."""


@dataclass(frozen=True)
class RowShutoffSegment:
    fs_id: str
    row_id: int
    pass_id: int
    machine_id: str
    shutoff_state: str
    segment: Segment
    path_points: tuple[Point, ...] = ()
    source_row_id: str = ""
    station_start_m: float = 0.0
    station_end_m: float = 0.0

    def line_points(self) -> tuple[Point, ...]:
        if self.path_points:
            return self.path_points
        return (self.segment.start, self.segment.end)

    def attributes(self) -> dict[str, object]:
        return {
            "fs_id": self.fs_id,
            "row_id": self.row_id,
            "pass_id": self.pass_id,
            "machine_id": self.machine_id,
            "shutoff_state": self.shutoff_state,
            "source_row_id": self.source_row_id,
            "station_start_m": self.station_start_m,
            "station_end_m": self.station_end_m,
            "length_m": polyline_length(list(self.line_points())),
        }


@dataclass(frozen=True)
class _TireStrip:
    """Indice leve: bbox expandido + vertices do eixo do pneu."""

    half_width_m: float
    points: tuple[Point, ...]
    xmin: float
    ymin: float
    xmax: float
    ymax: float


def tramline_as_multipolygon(zones: list[TramlineZone]) -> MultiPolygon:
    return [zone.polygon for zone in zones]


def apply_row_shutoff(
    rows: list[PlantingRow],
    zones: list[TramlineZone] | None = None,
    *,
    off_areas: MultiPolygon | None = None,
    on_areas: MultiPolygon | None = None,
    shutoff_on_tramlines: bool = True,
    tire_tracks: list[TireTrack] | None = None,
) -> list[RowShutoffSegment]:
    """Cruza polilinhas de plantio com zonas off/on (rastros/tramline/bordadura).

    - off_areas: trechos DENTRO = DESLIGA (anel de bordadura, zona de obstaculo)
    - on_areas: trechos FORA = DESLIGA (miolo: semente so no inner_work_area;
      bordadura: semente so no anel). Quando os dois vem juntos, off_areas
      continua valendo: DESLIGA dentro dele mesmo estando na area de semeadura.
    Tire tracks: distancia ao eixo do pneu ≤ half tire width.
    """
    if not rows:
        return []

    use_tracks = bool(shutoff_on_tramlines and tire_tracks)
    zone_mp: MultiPolygon = []
    if shutoff_on_tramlines and not use_tracks and zones:
        zone_mp.extend(tramline_as_multipolygon(zones))
    if off_areas and not on_areas:
        zone_mp.extend(off_areas)

    seed_on_mp: MultiPolygon = []
    forced_off_mp: MultiPolygon = []
    if on_areas:
        seed_on_mp = simplify_multipolygon_for_pip(
            list(on_areas),
            max_vertices=120,
            min_edge_m=3.0,
        )
        if off_areas:
            forced_off_mp = simplify_multipolygon_for_pip(
                list(off_areas),
                max_vertices=120,
                min_edge_m=3.0,
            )

    if not use_tracks and not zone_mp and not seed_on_mp:
        return [
            RowShutoffSegment(
                fs_id=str(uuid4()),
                row_id=row.row_id,
                pass_id=row.pass_id,
                machine_id=row.machine_id,
                shutoff_state="on",
                segment=row.segment,
                path_points=row.line_points(),
                source_row_id=row.fs_id,
                station_start_m=0.0,
                station_end_m=polyline_length(list(row.line_points())),
            )
            for row in rows
        ]

    envelopes = _build_tire_envelopes(tire_tracks) if use_tracks else []
    if zone_mp:
        zone_mp = simplify_multipolygon_for_pip(
            zone_mp,
            max_vertices=120,
            min_edge_m=3.0,
        )

    # Amostra grossa + refine local: evita O(rows × verts_densos) que trava o QGIS.
    densify = _TRACK_ROW_SAMPLE_M if use_tracks else 8.0

    result: list[RowShutoffSegment] = []
    for row in rows:
        points = list(row.line_points())
        if len(points) < 2:
            continue

        if seed_on_mp:
            # Semente LIGA so dentro de on_areas (miolo ou anel de bordadura).
            inside_chunks, outside_chunks = split_polyline_by_multipolygon(
                points,
                seed_on_mp,
                densify_m=densify,
            )
            # Dentro = ON; fora = OFF
            on_chunks, off_chunks = inside_chunks, outside_chunks
            if forced_off_mp and not use_tracks:
                densified = segment_samples(points, densify_m=densify)
                on_flags = [
                    point_in_multipolygon(pt, seed_on_mp, check_boundary=False)
                    and not point_in_multipolygon(pt, forced_off_mp, check_boundary=False)
                    for pt in densified
                ]
                on_chunks, off_chunks = _chunks_from_flags(densified, on_flags)
            if use_tracks:
                # Rastros forcam OFF tambem nos trechos ON.
                track_intervals = _exact_track_intervals(points, envelopes)
                if track_intervals:
                    densified, track_flags = _sample_row_with_track_intervals(
                        points, track_intervals, densify_m=densify
                    )
                    seed_flags = [
                        point_in_multipolygon(pt, seed_on_mp, check_boundary=False)
                        for pt in densified
                    ]
                    # ON so se dentro do on_area, fora do rastro e fora do off_area.
                    off_flags = (
                        [
                            point_in_multipolygon(pt, forced_off_mp, check_boundary=False)
                            for pt in densified
                        ]
                        if forced_off_mp
                        else [False] * len(densified)
                    )
                    on_flags = [
                        seed and (not track) and (not forced)
                        for seed, track, forced in zip(seed_flags, track_flags, off_flags)
                    ]
                    on_chunks, off_chunks = _exact_chunks_from_flags(densified, on_flags)
            # Com on_areas: inside=ON, outside=OFF
            for chunk in off_chunks:
                seg = _segment_from_points(chunk)
                if seg is None or seg.length <= 1e-6:
                    continue
                result.append(
                    RowShutoffSegment(
                        fs_id=str(uuid4()),
                        row_id=row.row_id,
                        pass_id=row.pass_id,
                        machine_id=row.machine_id,
                        shutoff_state="off",
                        segment=seg,
                        path_points=tuple(chunk),
                    )
                )
            for chunk in on_chunks:
                seg = _segment_from_points(chunk)
                if seg is None or seg.length <= 1e-6:
                    continue
                result.append(
                    RowShutoffSegment(
                        fs_id=str(uuid4()),
                        row_id=row.row_id,
                        pass_id=row.pass_id,
                        machine_id=row.machine_id,
                        shutoff_state="on",
                        segment=seg,
                        path_points=tuple(chunk),
                    )
                )
            continue

        if use_tracks:
            track_intervals = _exact_track_intervals(points, envelopes)
            if not track_intervals and not zone_mp:
                result.append(
                    RowShutoffSegment(
                        fs_id=str(uuid4()),
                        row_id=row.row_id,
                        pass_id=row.pass_id,
                        machine_id=row.machine_id,
                        shutoff_state="on",
                        segment=row.segment,
                        path_points=tuple(points),
                    )
                )
                continue
            densified, inside_flags = _sample_row_with_track_intervals(
                points, track_intervals, densify_m=densify
            )
            if zone_mp:
                inside_flags = [
                    flag or point_in_multipolygon(pt, zone_mp, check_boundary=False)
                    for flag, pt in zip(inside_flags, densified)
                ]
            inside_chunks, outside_chunks = _exact_chunks_from_flags(densified, inside_flags)
        else:
            inside_chunks, outside_chunks = split_polyline_by_multipolygon(
                points,
                zone_mp,
                densify_m=densify,
            )

        if not inside_chunks:
            result.append(
                RowShutoffSegment(
                    fs_id=str(uuid4()),
                    row_id=row.row_id,
                    pass_id=row.pass_id,
                    machine_id=row.machine_id,
                    shutoff_state="on",
                    segment=row.segment,
                    path_points=tuple(points),
                )
            )
            continue

        for chunk in inside_chunks:
            seg = _segment_from_points(chunk)
            if seg is None or seg.length <= 1e-6:
                continue
            result.append(
                RowShutoffSegment(
                    fs_id=str(uuid4()),
                    row_id=row.row_id,
                    pass_id=row.pass_id,
                    machine_id=row.machine_id,
                    shutoff_state="off",
                    segment=seg,
                    path_points=tuple(chunk),
                )
            )
        for chunk in outside_chunks:
            seg = _segment_from_points(chunk)
            if seg is None or seg.length <= 1e-6:
                continue
            result.append(
                RowShutoffSegment(
                    fs_id=str(uuid4()),
                    row_id=row.row_id,
                    pass_id=row.pass_id,
                    machine_id=row.machine_id,
                    shutoff_state="on",
                    segment=seg,
                    path_points=tuple(chunk),
                )
            )
    return _attach_row_stations(result, rows)


def _locate_station_on_polyline(points: list[Point], point: Point) -> float:
    """Projeta um ponto na polilinha e devolve a estaca acumulada mais proxima."""
    best_distance = float("inf")
    best_station = 0.0
    station = 0.0
    for start, end in zip(points, points[1:]):
        edge = sub(end, start)
        length2 = dot(edge, edge)
        length = distance(start, end)
        if length2 <= 1e-18:
            continue
        ratio = max(0.0, min(1.0, dot(sub(point, start), edge) / length2))
        projected = add(start, mul(edge, ratio))
        gap = distance(point, projected)
        if gap < best_distance:
            best_distance = gap
            best_station = station + ratio * length
        station += length
    return best_station


def _attach_row_stations(
    segments: list[RowShutoffSegment],
    rows: list[PlantingRow],
) -> list[RowShutoffSegment]:
    """Anexa identidade da fonte e intervalo acumulado a cada trecho derivado."""
    by_key = {(row.pass_id, row.row_id, row.machine_id): row for row in rows}
    enriched: list[RowShutoffSegment] = []
    for item in segments:
        row = by_key.get((item.pass_id, item.row_id, item.machine_id))
        if row is None:
            enriched.append(item)
            continue
        row_points = list(row.line_points())
        item_points = list(item.line_points())
        start = _locate_station_on_polyline(row_points, item_points[0])
        end = _locate_station_on_polyline(row_points, item_points[-1])
        if end < start:
            start, end = end, start
        enriched.append(
            replace(
                item,
                source_row_id=row.fs_id,
                station_start_m=start,
                station_end_m=end,
            )
        )
    return enriched


def shutoff_summary(segments: list[RowShutoffSegment]) -> list[dict[str, object]]:
    """Resumo por linha: DESLIGA se houver trecho off."""
    by_row: dict[tuple[int, int], list[str]] = {}
    lengths: dict[tuple[int, int], float] = {}
    for item in segments:
        key = (item.pass_id, item.row_id)
        by_row.setdefault(key, []).append(item.shutoff_state)
        if item.shutoff_state == "off":
            lengths[key] = lengths.get(key, 0.0) + polyline_length(list(item.line_points()))
    summary: list[dict[str, object]] = []
    for (pass_id, row_id), states in sorted(by_row.items()):
        action = "DESLIGA" if "off" in states else "LIGA"
        summary.append(
            {
                "pass_id": pass_id,
                "row_id": row_id,
                "action": action,
                "off_length_m": round(lengths.get((pass_id, row_id), 0.0), 3),
            }
        )
    return summary


@dataclass(frozen=True)
class PassShutoffVisual:
    """Trecho OFF na trajetoria do trator (mapa limpo, sem N linhas)."""

    pass_id: int
    path_points: tuple[Point, ...]
    row_ids_off: tuple[int, ...]
    off_length_m: float

    def attributes(self) -> dict[str, object]:
        return {
            "pass_id": self.pass_id,
            "row_ids_off": ",".join(str(r) for r in self.row_ids_off),
            "row_off_count": len(self.row_ids_off),
            "off_length_m": round(self.off_length_m, 3),
            "shutoff_state": "off",
        }


def aggregate_shutoff_on_passes(
    passes: list,
    shutoff_segments: list[RowShutoffSegment],
) -> list[PassShutoffVisual]:
    """Projeta DESLIGA das linhas virtuais na passada do trator (1 geometria limpa)."""
    if not passes or not shutoff_segments:
        return []

    off_by_pass: dict[int, list[RowShutoffSegment]] = {}
    for seg in shutoff_segments:
        if seg.shutoff_state != "off":
            continue
        # So passadas do miolo (pass_id >= 0). Bordadura/linhas virtuais
        # nao viram geometria no mapa.
        if seg.pass_id < 0:
            continue
        off_by_pass.setdefault(seg.pass_id, []).append(seg)

    by_pass_no = {item.pass_no: item for item in passes}
    visuals: list[PassShutoffVisual] = []
    for pass_id, offs in sorted(off_by_pass.items()):
        traffic = by_pass_no.get(pass_id)
        if traffic is None:
            # Nunca desenhar geometria de row virtual no mapa.
            continue

        pass_pts = list(traffic.line_points())
        if len(pass_pts) < 2:
            continue
        intervals: list[tuple[float, float]] = []
        row_ids: set[int] = set()
        total_len = _polyline_arclength(pass_pts)
        if total_len <= 1e-9:
            continue
        for seg in offs:
            row_ids.add(seg.row_id)
            s0 = _project_point_s(seg.segment.start, pass_pts, total_len)
            s1 = _project_point_s(seg.segment.end, pass_pts, total_len)
            a, b = (s0, s1) if s0 <= s1 else (s1, s0)
            if b - a < 1e-3:
                mid = 0.5 * (a + b)
                a = max(0.0, mid - 0.5)
                b = min(total_len, mid + 0.5)
            intervals.append((a, b))
        merged = _merge_intervals(intervals)
        for a, b in merged:
            chunk = _subpolyline_by_s(pass_pts, a, b, total_len)
            if len(chunk) < 2:
                continue
            visuals.append(
                PassShutoffVisual(
                    pass_id=pass_id,
                    path_points=tuple(chunk),
                    row_ids_off=tuple(sorted(row_ids)),
                    off_length_m=b - a,
                )
            )
    return visuals


def pass_shutoff_table(visuals: list[PassShutoffVisual]) -> list[dict[str, object]]:
    """Tabela de auditoria: passada → linhas OFF (mapa limpo)."""
    by_pass: dict[int, set[int]] = {}
    lengths: dict[int, float] = {}
    for item in visuals:
        by_pass.setdefault(item.pass_id, set()).update(item.row_ids_off)
        lengths[item.pass_id] = lengths.get(item.pass_id, 0.0) + item.off_length_m
    rows: list[dict[str, object]] = []
    for pass_id in sorted(by_pass.keys()):
        ids = sorted(by_pass[pass_id])
        rows.append(
            {
                "pass_id": pass_id,
                "row_ids_off": ",".join(str(i) for i in ids),
                "row_off_count": len(ids),
                "off_length_m": round(lengths.get(pass_id, 0.0), 3),
                "action": "DESLIGA",
            }
        )
    return rows


def _polyline_arclength(points: list[Point]) -> float:
    total = 0.0
    for a, b in zip(points, points[1:]):
        total += distance(a, b)
    return total


def _project_point_s(point: Point, polyline: list[Point], total_len: float) -> float:
    best_s = 0.0
    best_d = float("inf")
    walked = 0.0
    for a, b in zip(polyline, polyline[1:]):
        edge = sub(b, a)
        length2 = edge[0] * edge[0] + edge[1] * edge[1]
        length = length2 ** 0.5
        if length2 <= 1e-18:
            d = distance(point, a)
            if d < best_d:
                best_d = d
                best_s = walked
            continue
        t = max(0.0, min(1.0, dot(sub(point, a), edge) / length2))
        proj = add(a, mul(edge, t))
        d = distance(point, proj)
        if d < best_d:
            best_d = d
            best_s = walked + t * length
        walked += length
    return max(0.0, min(total_len, best_s))


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not intervals:
        return []
    ordered = sorted(intervals)
    merged = [ordered[0]]
    for a, b in ordered[1:]:
        la, lb = merged[-1]
        if a <= lb + 0.5:
            merged[-1] = (la, max(lb, b))
        else:
            merged.append((a, b))
    return merged


def _subpolyline_by_s(
    points: list[Point],
    s0: float,
    s1: float,
    total_len: float,
) -> list[Point]:
    if s1 <= s0 or total_len <= 1e-9:
        return []
    s0 = max(0.0, min(total_len, s0))
    s1 = max(0.0, min(total_len, s1))
    out: list[Point] = []
    walked = 0.0
    started = False
    for a, b in zip(points, points[1:]):
        length = distance(a, b)
        if length <= 1e-12:
            continue
        end_s = walked + length
        if end_s < s0 - 1e-9:
            walked = end_s
            continue
        if walked > s1 + 1e-9:
            break
        t0 = 0.0 if walked >= s0 else (s0 - walked) / length
        t1 = 1.0 if end_s <= s1 else (s1 - walked) / length
        t0 = max(0.0, min(1.0, t0))
        t1 = max(0.0, min(1.0, t1))
        p0 = add(a, mul(sub(b, a), t0))
        p1 = add(a, mul(sub(b, a), t1))
        if not started:
            out.append(p0)
            started = True
        elif distance(out[-1], p0) > 1e-6:
            out.append(p0)
        if distance(out[-1], p1) > 1e-6:
            out.append(p1)
        walked = end_s
    return out


# Passo de amostragem da linha de plantio vs rastro (m).
_TRACK_ROW_SAMPLE_M = 2.5
# Passo minimo ao decimar eixos de pneu densificados pela suavizacao.
_TRACK_AXIS_DECIMATE_M = 4.0
_TRACK_AXIS_MAX_POINTS = 100


def _build_tire_strips(tracks: list[TireTrack]) -> list[_TireStrip]:
    strips: list[_TireStrip] = []
    for track in tracks:
        half = track.tire_width_m / 2.0
        # Decima (nao densifica): rastros suavizados chegam com milhares de verts.
        step = max(_TRACK_AXIS_DECIMATE_M, half * 4.0)
        pts = _decimate_polyline(
            track.points,
            min_step_m=step,
            max_points=_TRACK_AXIS_MAX_POINTS,
        )
        if len(pts) < 2:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        strips.append(
            _TireStrip(
                half_width_m=half,
                points=tuple(pts),
                xmin=min(xs) - half,
                ymin=min(ys) - half,
                xmax=max(xs) + half,
                ymax=max(ys) + half,
            )
        )
    return strips


# Intervalos OFF que se tocam (ate 1 mm) viram um so; separados continuam eventos distintos.
_EXACT_INTERVAL_MERGE_M = 1e-3


@dataclass(frozen=True)
class _TireEnvelope:
    """Faixa do pneu: buffer(eixo completo, tire_width_m / 2) em CRS metrico."""

    polygon: object
    prepared: object
    bbox: tuple[float, float, float, float]


def _build_tire_envelopes(tracks: list[TireTrack]) -> list[_TireEnvelope]:
    from shapely.geometry import LineString
    from shapely.prepared import prep

    envelopes: list[_TireEnvelope] = []
    for track in tracks:
        half = track.tire_width_m / 2.0
        points: list[Point] = []
        for point in track.points:
            if not points or distance(points[-1], point) > 1e-9:
                points.append((float(point[0]), float(point[1])))
        if half <= 0 or len(points) < 2:
            continue
        polygon = LineString(points).buffer(half)
        if polygon.is_empty:
            continue
        envelopes.append(_TireEnvelope(polygon, prep(polygon), tuple(polygon.bounds)))
    return envelopes


def _linear_parts(geometry) -> list:
    if geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [geometry]
    if hasattr(geometry, "geoms"):
        return [part for item in geometry.geoms for part in _linear_parts(item)]
    return []


def _merge_exact_intervals(
    intervals: list[tuple[float, float]],
    tolerance_m: float = _EXACT_INTERVAL_MERGE_M,
) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1] + tolerance_m:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _exact_track_intervals(
    row_points: list[Point],
    envelopes: list[_TireEnvelope],
) -> list[tuple[float, float]]:
    """Estacas [inicio, fim] da linha dentro de alguma faixa de pneu, por intersecao exata.

    Cada aresta da linha e cruzada com cada faixa; a estaca vem da distancia ao
    inicio da aresta, sem depender de passo de amostragem.
    """
    from shapely.geometry import LineString

    row_bbox = _polyline_bbox(row_points)
    candidates = [env for env in envelopes if _bboxes_overlap(row_bbox, env.bbox)]
    if not candidates:
        return []
    intervals: list[tuple[float, float]] = []
    walked = 0.0
    for start, end in zip(row_points, row_points[1:]):
        length = distance(start, end)
        if length <= 1e-12:
            continue
        edge_bbox = (
            min(start[0], end[0]),
            min(start[1], end[1]),
            max(start[0], end[0]),
            max(start[1], end[1]),
        )
        edge = None
        for envelope in candidates:
            if not _bboxes_overlap(edge_bbox, envelope.bbox):
                continue
            edge = edge or LineString([start, end])
            if not envelope.prepared.intersects(edge):
                continue
            for part in _linear_parts(edge.intersection(envelope.polygon)):
                coords = list(part.coords)
                d0 = distance(start, coords[0])
                d1 = distance(start, coords[-1])
                lo, hi = min(d0, d1), max(d0, d1)
                if hi - lo > 1e-9:
                    intervals.append((walked + lo, walked + hi))
        walked += length
    return _merge_exact_intervals(intervals)


def _point_at_station(points: list[Point], station: float) -> Point:
    walked = 0.0
    for start, end in zip(points, points[1:]):
        length = distance(start, end)
        if length <= 1e-12:
            continue
        if walked + length >= station:
            t = max(0.0, min(1.0, (station - walked) / length))
            return add(start, mul(sub(end, start), t))
        walked += length
    return points[-1]


def _sample_row_with_track_intervals(
    points: list[Point],
    intervals: list[tuple[float, float]],
    *,
    densify_m: float,
) -> tuple[list[Point], list[bool]]:
    """Amostras da linha + par de pontos (antes/depois) em cada borda exata do rastro.

    As amostras so servem as areas poligonais; o flag do rastro vem dos intervalos.
    """
    coarse = segment_samples(points, densify_m=densify_m)
    boundaries: list[tuple[float, bool, bool]] = []
    for start, end in intervals:
        boundaries.append((start, False, True))
        boundaries.append((end, True, False))
    out_pts: list[Point] = []
    out_flags: list[bool] = []
    index = 0
    station = 0.0
    for position, point in enumerate(coarse):
        if position:
            station += distance(coarse[position - 1], point)
        while index < len(boundaries) and boundaries[index][0] <= station + 1e-9:
            boundary, before, after = boundaries[index]
            at = _point_at_station(points, boundary)
            out_pts.extend((at, at))
            out_flags.extend((before, after))
            index += 1
        if any(abs(station - item[0]) <= 1e-9 for item in boundaries):
            continue
        out_pts.append(point)
        out_flags.append(any(start < station < end for start, end in intervals))
    while index < len(boundaries):
        boundary, before, after = boundaries[index]
        at = _point_at_station(points, boundary)
        out_pts.extend((at, at))
        out_flags.extend((before, after))
        index += 1
    return out_pts, out_flags


def _exact_chunks_from_flags(
    points: list[Point],
    flags: list[bool],
) -> tuple[list[list[Point]], list[list[Point]]]:
    """Como _chunks_from_flags, sem vertices repetidos dos pares de borda."""

    def clean(chunks: list[list[Point]]) -> list[list[Point]]:
        out: list[list[Point]] = []
        for chunk in chunks:
            unique = [chunk[0]]
            for point in chunk[1:]:
                if distance(unique[-1], point) > 1e-9:
                    unique.append(point)
            if len(unique) >= 2:
                out.append(unique)
        return out

    inside, outside = _chunks_from_flags(points, flags)
    return clean(inside), clean(outside)


def _decimate_polyline(
    points: tuple[Point, ...] | list[Point],
    *,
    min_step_m: float,
    max_points: int | None = None,
) -> list[Point]:
    """Remove vertices densos mantendo o shape (passo minimo entre pontos)."""
    pts = list(points)
    if len(pts) < 2:
        return pts
    if min_step_m <= 0:
        out = pts
    else:
        out = [pts[0]]
        for point in pts[1:-1]:
            if distance(out[-1], point) >= min_step_m - 1e-9:
                out.append(point)
        if distance(out[-1], pts[-1]) > 1e-9:
            out.append(pts[-1])
        elif len(out) == 1:
            out.append(pts[-1])
    if max_points is not None and len(out) > max_points:
        # Subamostra uniforme por indice (mantem extremos).
        last = len(out) - 1
        idxs = [0]
        for i in range(1, max_points - 1):
            idxs.append(int(round(i * last / (max_points - 1))))
        idxs.append(last)
        # Dedup indices monotônicos.
        uniq: list[int] = []
        for idx in idxs:
            if not uniq or idx > uniq[-1]:
                uniq.append(idx)
        out = [out[i] for i in uniq]
    return out


def _resample_polyline(points: tuple[Point, ...] | list[Point], *, max_step_m: float) -> list[Point]:
    """Garante passo maximo (densifica trechos longos). Preferir _decimate_polyline para rastros."""
    pts = list(points)
    if len(pts) < 2 or max_step_m <= 0:
        return pts
    out: list[Point] = [pts[0]]
    for start, end in zip(pts, pts[1:]):
        length = distance(start, end)
        if length <= max_step_m + 1e-9:
            if out[-1] != end:
                out.append(end)
            continue
        steps = max(1, int(length // max_step_m))
        for i in range(1, steps + 1):
            t = min(1.0, (i * max_step_m) / length)
            if t >= 1.0 - 1e-12:
                break
            out.append(add(start, mul(sub(end, start), t)))
        if out[-1] != end:
            out.append(end)
    return out


def _polyline_bbox(points: list[Point] | tuple[Point, ...]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _bboxes_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def _candidate_strips(row_points: list[Point], strips: list[_TireStrip]) -> list[_TireStrip]:
    rb = _polyline_bbox(row_points)
    return [
        strip
        for strip in strips
        if _bboxes_overlap(rb, (strip.xmin, strip.ymin, strip.xmax, strip.ymax))
    ]


def _point_in_strips(point: Point, strips: list[_TireStrip]) -> bool:
    x, y = point
    for strip in strips:
        if x < strip.xmin or x > strip.xmax or y < strip.ymin or y > strip.ymax:
            continue
        if (
            _distance_point_to_polyline(
                point,
                strip.points,
                early_exit_m=strip.half_width_m + 1e-6,
            )
            <= strip.half_width_m + 1e-6
        ):
            return True
    return False


def _sample_row_against_strips(
    points: list[Point],
    strips: list[_TireStrip],
    *,
    densify_m: float,
) -> tuple[list[Point], list[bool]]:
    """Amostra a linha; refine binario so onde o bbox cruza faixa de pneu."""
    coarse = segment_samples(points, densify_m=densify_m)
    if not strips:
        return coarse, [False] * len(coarse)

    min_len = max(0.15, min(s.half_width_m for s in strips) * 0.75)

    out_pts: list[Point] = []
    out_flags: list[bool] = []
    for index, point in enumerate(coarse):
        flag = _point_in_strips(point, strips)
        if index == 0:
            out_pts.append(point)
            out_flags.append(flag)
            continue
        prev = coarse[index - 1]
        prev_flag = out_flags[-1]
        if prev_flag != flag:
            _append_transition(prev, point, prev_flag, flag, strips, out_pts, out_flags)
        elif (not prev_flag) and _segment_bbox_hits_strips(prev, point, strips):
            # Ambos fora: busca binaria por faixa fina (sem varrer todas as arestas).
            _append_hidden_crossings(prev, point, strips, out_pts, out_flags, min_len=min_len)
        out_pts.append(point)
        out_flags.append(flag)
    return out_pts, out_flags


def _append_transition(
    start: Point,
    end: Point,
    start_flag: bool,
    end_flag: bool,
    strips: list[_TireStrip],
    out_pts: list[Point],
    out_flags: list[bool],
) -> None:
    lo, hi = start, end
    lo_flag = start_flag
    for _ in range(8):
        mid = add(lo, mul(sub(hi, lo), 0.5))
        mid_flag = _point_in_strips(mid, strips)
        if mid_flag == lo_flag:
            lo = mid
        else:
            hi = mid
    if distance(out_pts[-1], lo) > 1e-4:
        out_pts.append(lo)
        out_flags.append(lo_flag)
    if distance(lo, hi) > 1e-4 and distance(hi, end) > 1e-4:
        out_pts.append(hi)
        out_flags.append(end_flag)


def _append_hidden_crossings(
    start: Point,
    end: Point,
    strips: list[_TireStrip],
    out_pts: list[Point],
    out_flags: list[bool],
    *,
    min_len: float,
    depth: int = 0,
    max_depth: int = 12,
) -> None:
    """Insere pontos OFF ocultos entre extremos ON (busca binaria por bbox)."""
    if depth >= max_depth or distance(start, end) < min_len:
        return
    if not _segment_bbox_hits_strips(start, end, strips):
        return
    mid = add(start, mul(sub(end, start), 0.5))
    mid_flag = _point_in_strips(mid, strips)
    if mid_flag:
        _append_transition(start, mid, False, True, strips, out_pts, out_flags)
        if distance(out_pts[-1], mid) > 1e-4:
            out_pts.append(mid)
            out_flags.append(True)
        _append_transition(mid, end, True, False, strips, out_pts, out_flags)
        return
    _append_hidden_crossings(
        start, mid, strips, out_pts, out_flags, min_len=min_len, depth=depth + 1, max_depth=max_depth
    )
    _append_hidden_crossings(
        mid, end, strips, out_pts, out_flags, min_len=min_len, depth=depth + 1, max_depth=max_depth
    )


def _segment_bbox_hits_strips(start: Point, end: Point, strips: list[_TireStrip]) -> bool:
    seg_bbox = (
        min(start[0], end[0]),
        min(start[1], end[1]),
        max(start[0], end[0]),
        max(start[1], end[1]),
    )
    for strip in strips:
        pad = strip.half_width_m
        expanded = (
            strip.xmin - pad,
            strip.ymin - pad,
            strip.xmax + pad,
            strip.ymax + pad,
        )
        if _bboxes_overlap(seg_bbox, expanded):
            return True
    return False


def densify_pad(strip: _TireStrip) -> float:
    return strip.half_width_m


def _min_distance_segment_to_polyline(
    start: Point,
    end: Point,
    polyline: tuple[Point, ...] | list[Point],
) -> float:
    best = float("inf")
    for a, b in zip(polyline, polyline[1:]):
        d = _segment_segment_distance(start, end, a, b)
        if d < best:
            best = d
            if best <= 1e-9:
                return 0.0
    return best


def _orient(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_intersect(a0: Point, a1: Point, b0: Point, b1: Point) -> bool:
    """True se os segmentos se cruzam (inclui tocamento nas pontas)."""
    o1 = _orient(a0, a1, b0)
    o2 = _orient(a0, a1, b1)
    o3 = _orient(b0, b1, a0)
    o4 = _orient(b0, b1, a1)
    if o1 == 0.0 and o2 == 0.0 and o3 == 0.0 and o4 == 0.0:
        return not (
            max(a0[0], a1[0]) < min(b0[0], b1[0]) - 1e-12
            or max(b0[0], b1[0]) < min(a0[0], a1[0]) - 1e-12
            or max(a0[1], a1[1]) < min(b0[1], b1[1]) - 1e-12
            or max(b0[1], b1[1]) < min(a0[1], a1[1]) - 1e-12
        )
    return (o1 * o2 <= 0.0) and (o3 * o4 <= 0.0)


def _segment_segment_distance(a0: Point, a1: Point, b0: Point, b1: Point) -> float:
    """Distancia minima entre dois segmentos finitos (detecta cruzamento)."""
    if _segments_intersect(a0, a1, b0, b1):
        return 0.0
    candidates = (
        _distance_point_to_segment(a0, b0, b1),
        _distance_point_to_segment(a1, b0, b1),
        _distance_point_to_segment(b0, a0, a1),
        _distance_point_to_segment(b1, a0, a1),
    )
    return min(candidates)


def _distance_point_to_segment(point: Point, start: Point, end: Point) -> float:
    edge = sub(end, start)
    length2 = edge[0] * edge[0] + edge[1] * edge[1]
    if length2 <= 1e-18:
        return distance(point, start)
    t = max(0.0, min(1.0, dot(sub(point, start), edge) / length2))
    return distance(point, add(start, mul(edge, t)))


def _distance_point_to_polyline(
    point: Point,
    polyline: tuple[Point, ...] | list[Point],
    *,
    early_exit_m: float | None = None,
) -> float:
    """Distancia euclidiana ao ponto mais proximo da polilinha (t clampado)."""
    best = float("inf")
    exit_at = 0.0 if early_exit_m is None else max(0.0, early_exit_m)
    for start, end in zip(polyline, polyline[1:]):
        edge = sub(end, start)
        length2 = edge[0] * edge[0] + edge[1] * edge[1]
        if length2 <= 1e-18:
            d = distance(point, start)
        else:
            t = max(0.0, min(1.0, dot(sub(point, start), edge) / length2))
            proj = add(start, mul(edge, t))
            d = distance(point, proj)
        if d < best:
            best = d
            if best <= 1e-9:
                return 0.0
            if early_exit_m is not None and best <= exit_at:
                return best
    return best


def _chunks_from_flags(
    points: list[Point],
    inside_flags: list[bool],
) -> tuple[list[list[Point]], list[list[Point]]]:
    inside_chunks: list[list[Point]] = []
    outside_chunks: list[list[Point]] = []
    if not points:
        return inside_chunks, outside_chunks
    current: list[Point] = [points[0]]
    current_inside = inside_flags[0]
    for point, flag in zip(points[1:], inside_flags[1:]):
        if flag == current_inside:
            current.append(point)
            continue
        if len(current) >= 2:
            if current_inside:
                inside_chunks.append(current)
            else:
                outside_chunks.append(current)
        current = [current[-1], point]
        current_inside = flag
    if len(current) >= 2:
        if current_inside:
            inside_chunks.append(current)
        else:
            outside_chunks.append(current)
    return inside_chunks, outside_chunks


def _segment_from_points(points: list[Point]) -> Segment | None:
    if len(points) < 2:
        return None
    return Segment(points[0], points[-1])
