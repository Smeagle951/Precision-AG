# -*- coding: utf-8 -*-
"""Chaves de recursos em implantacao gradual."""

ENABLE_STRATEGY_ANALYZER = True
# Linhas ROW_01..ROW_N temporarias (fortsmart_preview) para conferir o encontro.
SHOW_ROW_PREVIEW = False

# Etapa 0: chaves persistidas em QgsSettings, todas desligadas por padrao.
FLAG_SETTINGS_PREFIX = "fortsmart_precision/flags/"
ENABLE_AGROCAD_PANEL_V1 = "ENABLE_AGROCAD_PANEL_V1"
ENABLE_LAYER_ORGANIZER_V1 = "ENABLE_LAYER_ORGANIZER_V1"
ENABLE_PREVIEW_MANAGER_V1 = "ENABLE_PREVIEW_MANAGER_V1"
ENABLE_DEM_INSPECTOR_V1 = "ENABLE_DEM_INSPECTOR_V1"
# Diagnostico do tipo geometrico ao substituir tabela no GPKG (so avisos).
ENABLE_GPKG_GEOMETRY_CHECK_V1 = "ENABLE_GPKG_GEOMETRY_CHECK_V1"
# Fase 2: entra e sai pela bordadura (previa em memoria, sem gravacao).
ENABLE_SPRAY_BORDER_ENTRY_V1 = "ENABLE_SPRAY_BORDER_ENTRY_V1"

PERSISTED_FLAG_DEFAULTS = {
    ENABLE_AGROCAD_PANEL_V1: False,
    ENABLE_LAYER_ORGANIZER_V1: False,
    ENABLE_PREVIEW_MANAGER_V1: False,
    ENABLE_DEM_INSPECTOR_V1: False,
    ENABLE_GPKG_GEOMETRY_CHECK_V1: False,
    ENABLE_SPRAY_BORDER_ENTRY_V1: False,
}


def _settings(settings=None):
    if settings is not None:
        return settings
    try:
        from qgis.core import QgsSettings
    except ImportError:
        return None
    return QgsSettings()


def _as_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "on"):
        return True
    if text in ("false", "0", "no", "off", ""):
        return False
    return default


def is_enabled(name: str, settings=None) -> bool:
    """Valor da chave persistida; sem QGIS (ou chave desconhecida) vale o padrao."""
    if name not in PERSISTED_FLAG_DEFAULTS:
        raise KeyError(f"Chave de recurso desconhecida: {name}")
    default = PERSISTED_FLAG_DEFAULTS[name]
    store = _settings(settings)
    if store is None:
        return default
    return _as_bool(store.value(FLAG_SETTINGS_PREFIX + name, default), default)


def set_enabled(name: str, enabled: bool, settings=None) -> None:
    if name not in PERSISTED_FLAG_DEFAULTS:
        raise KeyError(f"Chave de recurso desconhecida: {name}")
    store = _settings(settings)
    if store is None:
        raise RuntimeError("QgsSettings indisponivel fora do QGIS.")
    store.setValue(FLAG_SETTINGS_PREFIX + name, bool(enabled))


def persisted_flags(settings=None) -> dict[str, bool]:
    return {name: is_enabled(name, settings) for name in PERSISTED_FLAG_DEFAULTS}
