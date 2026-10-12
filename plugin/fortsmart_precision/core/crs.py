# -*- coding: utf-8 -*-
"""Regras basicas de CRS para operacoes metricas."""

from dataclasses import dataclass


class CrsValidationError(ValueError):
    """Erro levantado quando um CRS nao pode ser usado com seguranca."""


@dataclass(frozen=True)
class CrsInfo:
    authid: str
    is_known: bool
    is_geographic: bool
    is_projected_metric: bool


GEOGRAPHIC_EPSG = {
    "EPSG:4326",  # WGS84
    "EPSG:4674",  # SIRGAS 2000 geografico
}

PROJECTED_METRIC_PREFIXES = (
    "EPSG:319",  # SIRGAS 2000 / UTM zonas Brasil
    "EPSG:326",  # WGS84 / UTM norte
    "EPSG:327",  # WGS84 / UTM sul
)


def normalize_authid(authid):
    """Normaliza um authid no formato EPSG:#### quando possivel."""
    if authid is None:
        return ""

    value = str(authid).strip().upper()
    if not value:
        return ""

    if value.isdigit():
        return f"EPSG:{value}"

    if value.startswith("EPSG"):
        digits = "".join(ch for ch in value if ch.isdigit())
        if digits:
            return f"EPSG:{digits}"

    return value


def inspect_authid(authid):
    """Classifica um CRS por authid sem depender do runtime QGIS."""
    normalized = normalize_authid(authid)
    is_known = bool(normalized)
    is_geographic = normalized in GEOGRAPHIC_EPSG
    is_projected_metric = (
        normalized.startswith(PROJECTED_METRIC_PREFIXES)
        and not is_geographic
    )
    return CrsInfo(
        authid=normalized,
        is_known=is_known,
        is_geographic=is_geographic,
        is_projected_metric=is_projected_metric,
    )


def require_projected_metric(authid, operation="operacao metrico-geometrica"):
    """Bloqueia area, distancia, buffer e offset fora de CRS projetado metrico."""
    info = inspect_authid(authid)
    if not info.is_known:
        raise CrsValidationError(
            f"CRS ausente: {operation} exige CRS projetado com unidade em metro."
        )

    if info.is_geographic:
        raise CrsValidationError(
            f"CRS geografico ({info.authid}) invalido para {operation}. "
            "Reprojete para um CRS projetado metrico antes de continuar."
        )

    if not info.is_projected_metric:
        raise CrsValidationError(
            f"CRS {info.authid} nao esta marcado como projetado metrico suportado "
            f"para {operation}."
        )

    return info


def suggest_sirgas_utm_epsg(longitude, latitude):
    """Sugere EPSG SIRGAS 2000 / UTM para coordenadas no Brasil.

    Padrao FortSmart: sempre SIRGAS 2000 / UTM (EPSG:31972–31985), zona
    determinada pela LONGITUDE (nao pelo estado — um estado pode ter 2 zonas).
    """
    lon = float(longitude)
    lat = float(latitude)

    if lat >= 0:
        raise CrsValidationError(
            "As zonas SIRGAS 2000 / UTM sul esperadas para o MVP exigem latitude negativa."
        )

    zone = int((lon + 180) // 6) + 1
    epsg = 31960 + zone

    if epsg < 31972 or epsg > 31985:
        raise CrsValidationError(
            f"Coordenada fora das zonas SIRGAS 2000 / UTM sul esperadas: zona {zone}."
        )

    return f"EPSG:{epsg}"


# Guia de zonas SIRGAS 2000 / UTM sul no Brasil (referencia por longitude).
# A zona correta e pela coordenada do talhao, nao por "padrao do estado".
SIRGAS_UTM_SOUTH_GUIDE = {
    18: ("EPSG:31978", "oeste extremo (AC/AM fronteira)"),
    19: ("EPSG:31979", "AC / AM oeste"),
    20: ("EPSG:31980", "AM / RR / RO oeste"),
    21: ("EPSG:31981", "MT / MS / RO / PA / TO oeste — comum no Centro-Oeste"),
    22: ("EPSG:31982", "GO / DF / MG / SP / PR / SC / RS leste relativo"),
    23: ("EPSG:31983", "BA / MG / ES / RJ / SP leste"),
    24: ("EPSG:31984", "SE / AL / PE / PB / RN / CE leste"),
    25: ("EPSG:31985", "litoral NE extremo"),
}


def describe_sirgas_utm_zone(zone: int) -> str:
    """Texto curto da zona UTM SIRGAS 2000 sul."""
    zone = int(zone)
    entry = SIRGAS_UTM_SOUTH_GUIDE.get(zone)
    if entry is None:
        return f"UTM zona {zone}S (fora do intervalo tipico 18–25 no Brasil)"
    authid, hint = entry
    return f"{authid} — SIRGAS 2000 / UTM {zone}S ({hint})"


def list_sirgas_utm_south_standards() -> list[tuple[str, int, str]]:
    """Lista oficial FortSmart: apenas SIRGAS 2000 / UTM sul (EPSG:31978–31985).

    Nao inclui WGS84/UTM (327xx), SAD69, Web Mercator nem CRS livres.
    """
    result: list[tuple[str, int, str]] = []
    for zone in sorted(SIRGAS_UTM_SOUTH_GUIDE):
        authid, hint = SIRGAS_UTM_SOUTH_GUIDE[zone]
        result.append((authid, zone, hint))
    return result


def recommended_sirgas_targets(
    longitude: float,
    latitude: float,
) -> list[dict[str, object]]:
    """Alvos recomendados para o ponto: principal + vizinhos de zona.

    Cada item: {authid, zone, label, is_primary, reason}.
    """
    primary = suggest_sirgas_utm_epsg(longitude, latitude)
    zone = int((float(longitude) + 180) // 6) + 1
    lon = float(longitude)
    # Distancia ao limite de zona (multiplos de 6° a partir de -180).
    zone_west = -180 + (zone - 1) * 6
    zone_east = zone_west + 6
    dist_west = abs(lon - zone_west)
    dist_east = abs(lon - zone_east)

    items: list[dict[str, object]] = []
    for authid, z, hint in list_sirgas_utm_south_standards():
        is_primary = authid == primary
        reason = "recomendado pela longitude do talhao" if is_primary else "padrao oficial SIRGAS 2000"
        if not is_primary and z == zone - 1 and dist_west <= 0.5:
            reason = "alternativa: talhao perto do limite oeste da zona"
        elif not is_primary and z == zone + 1 and dist_east <= 0.5:
            reason = "alternativa: talhao perto do limite leste da zona"
        items.append(
            {
                "authid": authid,
                "zone": z,
                "label": f"{authid} — UTM {z}S — {hint}",
                "is_primary": is_primary,
                "reason": reason,
            }
        )
    # Ordena: primario primeiro, depois zona crescente.
    items.sort(key=lambda item: (0 if item["is_primary"] else 1, int(item["zone"])))
    return items


def sirgas_utm_standard_summary() -> str:
    """Resumo do padrao CRS usado pelo FortSmart."""
    lines = [
        "Padrao FortSmart (agricultura BR): SOMENTE SIRGAS 2000 / UTM em metros.",
        "Zona determinada pela LONGITUDE do talhao — nao por estado e nao 'qualquer EPSG'.",
        "Nao use: EPSG:4326 (graus), Web Mercator, SAD69, WGS84/UTM (327xx) como padrao.",
        "Ex.: lon ≈ -54° → zona 21S → EPSG:31981 (SIRGAS 2000 / UTM zone 21S).",
        "",
        "Zonas oficiais suportadas:",
    ]
    for zone in sorted(SIRGAS_UTM_SOUTH_GUIDE):
        lines.append(f"  • {describe_sirgas_utm_zone(zone)}")
    return "\n".join(lines)
