# -*- coding: utf-8 -*-
"""Conversor de zonas UTM e diagnostico de coordenadas para usuarios."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .crs import (
    CrsValidationError,
    describe_sirgas_utm_zone,
    inspect_authid,
    list_sirgas_utm_south_standards,
    normalize_authid,
    recommended_sirgas_targets,
    suggest_sirgas_utm_epsg,
)


class CoordinateKind(str, Enum):
    GEOGRAPHIC = "geographic"
    WEB_MERCATOR = "web_mercator"
    PROJECTED_METRIC = "projected_metric"
    UNKNOWN = "unknown"


class CrsStatus(str, Enum):
    OK = "ok"
    GEOGRAPHIC = "geographic"
    UNSUPPORTED = "unsupported"
    MISSING = "missing"


@dataclass(frozen=True)
class CoordinateSample:
    x: float
    y: float
    kind: CoordinateKind
    explanation: str


@dataclass(frozen=True)
class ZoneConversionPlan:
    source_authid: str
    target_authid: str
    utm_zone: int
    hemisphere: str
    status: CrsStatus
    longitude: float
    latitude: float
    message: str
    needs_reprojection: bool
    recommended_targets: tuple[dict[str, object], ...] = ()

    def summary(self) -> str:
        return self.message


def utm_zone_from_longitude(longitude: float) -> int:
    """Calcula numero da zona UTM (1-60) a partir da longitude."""
    lon = float(longitude)
    if lon < -180 or lon > 180:
        raise CrsValidationError("Longitude fora do intervalo -180..180 graus.")
    return int((lon + 180) // 6) + 1


def sirgas_utm_authid(zone: int, *, southern: bool = True) -> str:
    """Retorna authid SIRGAS 2000 / UTM sul para a zona informada."""
    zone = int(zone)
    if zone < 18 or zone > 25:
        raise CrsValidationError(
            f"Zona UTM {zone} fora do intervalo tipico do Brasil (18-25)."
        )
    if not southern:
        raise CrsValidationError("Somente hemisferio sul (SIRGAS 2000 / UTM) no MVP.")
    return f"EPSG:{31960 + zone}"


def classify_coordinate_pair(x: float, y: float) -> CoordinateSample:
    """Identifica se um par x,y parece grau, Web Mercator ou metrico projetado."""
    x = float(x)
    y = float(y)
    if abs(x) <= 180 and abs(y) <= 90 and not (abs(x) < 1e-9 and abs(y) < 1e-9):
        return CoordinateSample(
            x,
            y,
            CoordinateKind.GEOGRAPHIC,
            "Valores parecem latitude/longitude em graus (ex.: EPSG:4326).",
        )
    # UTM tipico Brasil: easting ~100k-900k, northing ~1M-10M (hemisferio sul).
    if 50_000 <= abs(x) <= 999_999 and 1_000_000 <= abs(y) <= 10_000_000:
        return CoordinateSample(
            x,
            y,
            CoordinateKind.PROJECTED_METRIC,
            "Valores parecem coordenadas UTM/metricas (metros).",
        )
    if abs(x) > 180 or abs(y) > 90:
        return CoordinateSample(
            x,
            y,
            CoordinateKind.WEB_MERCATOR,
            "Valores parecem Web Mercator ou CRS projetado do mapa (nao sao graus).",
        )
    return CoordinateSample(
        x,
        y,
        CoordinateKind.UNKNOWN,
        "Nao foi possivel classificar automaticamente; confira o CRS da camada.",
    )


def crs_status(authid: str) -> CrsStatus:
    info = inspect_authid(authid)
    if not info.is_known:
        return CrsStatus.MISSING
    if info.is_geographic:
        return CrsStatus.GEOGRAPHIC
    if info.is_projected_metric:
        return CrsStatus.OK
    return CrsStatus.UNSUPPORTED


def build_zone_conversion_plan(
    source_authid: str,
    longitude: float,
    latitude: float,
    *,
    operation: str = "planejamento agricola",
    preferred_target: str | None = None,
) -> ZoneConversionPlan:
    """Monta plano de conversao para SIRGAS 2000 / UTM a partir de lon/lat."""
    normalized = normalize_authid(source_authid)
    status = crs_status(normalized)
    zone = utm_zone_from_longitude(longitude)
    recommended = recommended_sirgas_targets(longitude, latitude)
    primary = suggest_sirgas_utm_epsg(longitude, latitude)
    target = normalize_authid(preferred_target) if preferred_target else primary
    allowed = {item["authid"] for item in recommended}
    if target not in allowed:
        raise CrsValidationError(
            f"Destino {target} nao e padrao FortSmart. "
            f"Use apenas SIRGAS 2000 / UTM sul: {', '.join(sorted(allowed))}."
        )
    targets_tuple = tuple(recommended)

    if status == CrsStatus.OK and normalized == target:
        message = (
            f"CRS {normalized} ja e o padrao metrico correto "
            f"(SIRGAS 2000 / UTM zona {zone}S — {describe_sirgas_utm_zone(zone)}). "
            "Nenhuma conversao necessaria."
        )
        return ZoneConversionPlan(
            source_authid=normalized,
            target_authid=target,
            utm_zone=zone,
            hemisphere="S",
            status=status,
            longitude=longitude,
            latitude=latitude,
            message=message,
            needs_reprojection=False,
            recommended_targets=targets_tuple,
        )

    if status == CrsStatus.GEOGRAPHIC:
        message = (
            f"CRS geografico ({normalized}) NAO serve para {operation} "
            "(calculos em metros). "
            f"Padrao recomendado: {primary} (SIRGAS 2000 / UTM zona {zone}S). "
            f"Destino escolhido: {target}. "
            f"Centro: lon {longitude:.6f}, lat {latitude:.6f}."
        )
        return ZoneConversionPlan(
            source_authid=normalized,
            target_authid=target,
            utm_zone=_zone_from_authid(target) or zone,
            hemisphere="S",
            status=status,
            longitude=longitude,
            latitude=latitude,
            message=message,
            needs_reprojection=True,
            recommended_targets=targets_tuple,
        )

    if status == CrsStatus.OK and normalized != target:
        message = (
            f"CRS {normalized} e metrico, mas o padrao recomendado para esta area "
            f"e {primary} (zona {zone}S). Destino escolhido: {target}. "
            "Prefira SIRGAS 2000 / UTM da zona do talhao (nao WGS84/UTM nem zona vizinha "
            "sem necessidade)."
        )
        return ZoneConversionPlan(
            source_authid=normalized,
            target_authid=target,
            utm_zone=_zone_from_authid(target),
            hemisphere="S",
            status=status,
            longitude=longitude,
            latitude=latitude,
            message=message,
            needs_reprojection=True,
            recommended_targets=targets_tuple,
        )

    if status == CrsStatus.UNSUPPORTED:
        message = (
            f"CRS {normalized} nao e padrao FortSmart (SIRGAS 2000 / UTM). "
            f"Recomendado: {primary} (zona {zone}S). Destino: {target}."
        )
    else:
        message = (
            f"CRS ausente ou invalido. Para {operation}, use {primary} "
            f"(SIRGAS 2000 / UTM zona {zone}S)."
        )
    return ZoneConversionPlan(
        source_authid=normalized or "?",
        target_authid=target,
        utm_zone=_zone_from_authid(target) if target else zone,
        hemisphere="S",
        status=status,
        longitude=longitude,
        latitude=latitude,
        message=message,
        needs_reprojection=True,
        recommended_targets=targets_tuple,
    )


def _zone_from_authid(authid: str) -> int:
    for item_authid, zone, _hint in list_sirgas_utm_south_standards():
        if item_authid == normalize_authid(authid):
            return zone
    digits = "".join(ch for ch in normalize_authid(authid) if ch.isdigit())
    if digits:
        code = int(digits)
        if 31978 <= code <= 31985:
            return code - 31960
    return 0


def explain_ab_mismatch(
    field_authid: str,
    ab_x: float,
    ab_y: float,
    *,
    ab_crs_authid: str | None = None,
) -> str | None:
    """Retorna aviso se A-B parece estar em CRS diferente do talhao."""
    field_status = crs_status(field_authid)
    ab_sample = classify_coordinate_pair(ab_x, ab_y)
    if field_status == CrsStatus.GEOGRAPHIC and ab_sample.kind == CoordinateKind.WEB_MERCATOR:
        return (
            "A linha A-B foi capturada no CRS do mapa (provavelmente Web Mercator), "
            "mas o talhao esta em graus (EPSG:4326). Use o conversor de zona ou "
            "carregue a A-B de uma camada no mesmo CRS do talhao."
        )
    if field_status == CrsStatus.GEOGRAPHIC and ab_sample.kind == CoordinateKind.PROJECTED_METRIC:
        return (
            "A-B parece estar em metros, mas o talhao esta em graus. "
            "Reprojete o talhao ou capture a A-B no mesmo CRS."
        )
    if ab_crs_authid:
        field_norm = normalize_authid(field_authid)
        ab_norm = normalize_authid(ab_crs_authid)
        if field_norm and ab_norm and field_norm != ab_norm:
            field_kind = crs_status(field_norm)
            ab_kind = crs_status(ab_norm)
            if field_kind != ab_kind or field_norm != ab_norm:
                return (
                    f"Talhao ({field_norm}) e A-B ({ab_norm}) estao em CRS diferentes. "
                    "O plugin tenta converter automaticamente, mas reprojetar as camadas "
                    "evita erros."
                )
    return None
