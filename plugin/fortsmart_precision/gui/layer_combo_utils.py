# -*- coding: utf-8 -*-
"""Utilitarios para QgsMapLayerComboBox (QGIS 3.44 LTR e QGIS 4.x)."""

from __future__ import annotations

from qgis.core import QgsMapLayerProxyModel, QgsProject, QgsVectorLayer, QgsWkbTypes
from qgis.gui import QgsMapLayerComboBox

from ..core.crs import inspect_authid


def _resolve_filter(name: str):
    """Resolve constante de filtro em QGIS 3 ou QGIS 4."""
    try:
        from qgis.core import Qgis

        layer_filter = getattr(Qgis, "LayerFilter", None)
        if layer_filter is not None:
            value = getattr(layer_filter, name, None)
            if value is not None:
                return value
    except ImportError:
        pass

    filter_enum = getattr(QgsMapLayerProxyModel, "Filter", None)
    if filter_enum is not None:
        value = getattr(filter_enum, name, None)
        if value is not None:
            return value

    return getattr(QgsMapLayerProxyModel, name, None)


def resolve_layer_filters(*names: str):
    """Combina filtros de camada de forma compativel entre versoes."""
    combined = None
    for name in names:
        value = _resolve_filter(name)
        if value is None:
            continue
        if combined is None:
            combined = value
            continue
        try:
            combined = combined | value
        except TypeError:
            try:
                combined = int(combined) | int(value)
            except (TypeError, ValueError):
                combined = value
    return combined


def configure_layer_combo(combo: QgsMapLayerComboBox, *filter_names: str) -> None:
    """Configura combo com projeto atual e filtros de camada."""
    combo.setProject(QgsProject.instance())
    flags = resolve_layer_filters(*filter_names)
    if flags is not None:
        try:
            combo.setFilters(flags)
        except Exception:
            # QGIS 4 pode rejeitar flags misturados; tenta VectorLayer.
            fallback = resolve_layer_filters("VectorLayer")
            if fallback is not None:
                try:
                    combo.setFilters(fallback)
                except Exception:
                    pass
    combo.setEnabled(True)
    combo.setVisible(True)
    try:
        combo.setShowCrs(True)
    except Exception:
        pass
    try:
        combo.setAllowEmptyLayer(True)
    except Exception:
        pass
    try:
        combo.setExcludedProviders([])
    except Exception:
        pass


def is_point_like_vector_layer(layer) -> bool:
    """True para camadas vetoriais Point/MultiPoint."""
    if not isinstance(layer, QgsVectorLayer):
        return False
    return layer.geometryType() == QgsWkbTypes.PointGeometry


def is_line_like_vector_layer(layer) -> bool:
    """True para camadas vetoriais Line/MultiLine/curva."""
    if not isinstance(layer, QgsVectorLayer):
        return False
    if not layer.isValid():
        return False
    return layer.geometryType() == QgsWkbTypes.LineGeometry


def is_polygon_like_vector_layer(layer) -> bool:
    if not isinstance(layer, QgsVectorLayer):
        return False
    return layer.geometryType() == QgsWkbTypes.PolygonGeometry


def is_obstacle_like_vector_layer(layer) -> bool:
    """True para camada vetorial de obstaculo: ponto, linha ou poligono."""
    if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
        return False
    return layer.geometryType() in {
        QgsWkbTypes.PointGeometry,
        QgsWkbTypes.LineGeometry,
        QgsWkbTypes.PolygonGeometry,
    }


def geometry_type_label(layer) -> str:
    if not isinstance(layer, QgsVectorLayer):
        return "desconhecido"
    geom = layer.geometryType()
    if geom == QgsWkbTypes.PointGeometry:
        return "ponto"
    if geom == QgsWkbTypes.LineGeometry:
        return "linha"
    if geom == QgsWkbTypes.PolygonGeometry:
        return "poligono"
    return "vetor"


def _refresh_typed_vector_combo(combo: QgsMapLayerComboBox, predicate) -> int:
    """Lista vetores do tipo pedido via excepted list (robusto no QGIS 4)."""
    configure_layer_combo(combo, "VectorLayer")
    project = QgsProject.instance()
    layers = list(project.mapLayers().values())
    allowed = [layer for layer in layers if predicate(layer)]
    excepted = [layer for layer in layers if layer not in allowed]
    try:
        combo.setExceptedLayerList(excepted)
    except Exception:
        pass
    # Garante que o combo nao fica com camada invalida selecionada.
    current = combo.currentLayer()
    if current is not None and current not in allowed:
        if allowed:
            combo.setLayer(allowed[0])
        else:
            try:
                combo.setLayer(None)
            except Exception:
                pass
    return len(allowed)


def refresh_point_layer_combo(combo: QgsMapLayerComboBox) -> int:
    """Lista camadas pontuais abertas no projeto; retorna quantidade disponivel."""
    return _refresh_typed_vector_combo(combo, is_point_like_vector_layer)


def refresh_obstacle_layer_combo(combo: QgsMapLayerComboBox) -> int:
    """Lista camadas de obstaculo (ponto, linha ou poligono)."""
    return _refresh_typed_vector_combo(combo, is_obstacle_like_vector_layer)


def prefer_nonempty_point_layer(combo: QgsMapLayerComboBox) -> QgsVectorLayer | None:
    """Prefere camada pontual com feicoes (evita PointFeature vazia)."""
    return prefer_nonempty_layer(combo, is_point_like_vector_layer)


def prefer_nonempty_obstacle_layer(combo: QgsMapLayerComboBox) -> QgsVectorLayer | None:
    """Prefere camada de obstaculo com feicoes (ponto/linha/poligono)."""
    return prefer_nonempty_layer(combo, is_obstacle_like_vector_layer)


def prefer_nonempty_layer(combo: QgsMapLayerComboBox, predicate) -> QgsVectorLayer | None:
    """Prefere camada que passa no predicado e tem feicoes."""
    current = combo.currentLayer()
    layers = [
        layer
        for layer in QgsProject.instance().mapLayers().values()
        if predicate(layer)
    ]
    if not layers:
        return None
    nonempty = [layer for layer in layers if int(layer.featureCount() or 0) > 0]
    pool = nonempty if nonempty else layers
    if current is not None and current in pool and int(current.featureCount() or 0) > 0:
        return current
    chosen = pool[0]
    combo.setLayer(chosen)
    return chosen


def refresh_line_layer_combo(combo: QgsMapLayerComboBox) -> int:
    """Lista camadas de linha (reta/curva) abertas no projeto."""
    return _refresh_typed_vector_combo(combo, is_line_like_vector_layer)


def refresh_polygon_layer_combo(combo: QgsMapLayerComboBox) -> int:
    """Lista camadas poligonais (talhao / limite)."""
    return _refresh_typed_vector_combo(combo, is_polygon_like_vector_layer)


def prefer_metric_polygon_layer(combo: QgsMapLayerComboBox) -> QgsVectorLayer | None:
    """Prefere poligono metrico COM FEICOES; evita irma UTM vazia (0 feicoes)."""
    current = combo.currentLayer()
    polygons = [
        layer
        for layer in QgsProject.instance().mapLayers().values()
        if is_polygon_like_vector_layer(layer)
    ]
    if not polygons:
        return current if isinstance(current, QgsVectorLayer) else None

    def _nonempty(layer) -> bool:
        return int(layer.featureCount() or 0) > 0

    metric_nonempty = [
        layer
        for layer in polygons
        if inspect_authid(layer.crs().authid() or "").is_projected_metric and _nonempty(layer)
    ]
    any_nonempty = [layer for layer in polygons if _nonempty(layer)]

    # Se atual ja e metrico e tem feicoes, mantem.
    if isinstance(current, QgsVectorLayer):
        info = inspect_authid(current.crs().authid() or "")
        if info.is_projected_metric and _nonempty(current):
            return current

    # Se atual e geografico, tenta irma metrica nao vazia pelo nome.
    if isinstance(current, QgsVectorLayer):
        info = inspect_authid(current.crs().authid() or "")
        if info.is_geographic:
            base = current.name().split("(EPSG:")[0].strip().lower()
            for layer in metric_nonempty:
                other_base = layer.name().split("(EPSG:")[0].strip().lower()
                if other_base == base or base in other_base or other_base in base:
                    combo.setLayer(layer)
                    return layer

    # Atual vazio (comum: '... (EPSG:31981)' sem feicoes) → troca.
    # Prefere irma com o mesmo nome-base (ex.: Boundary PV 1).
    if isinstance(current, QgsVectorLayer) and not _nonempty(current):
        base = current.name().split("(EPSG:")[0].strip().lower()
        pool = metric_nonempty or any_nonempty
        if pool:
            for layer in pool:
                other_base = layer.name().split("(EPSG:")[0].strip().lower()
                if other_base == base or base in other_base or other_base in base:
                    combo.setLayer(layer)
                    return layer
            combo.setLayer(pool[0])
            return pool[0]

    if metric_nonempty:
        if current not in metric_nonempty:
            combo.setLayer(metric_nonempty[0])
        return combo.currentLayer()

    if any_nonempty and (current is None or not _nonempty(current)):
        combo.setLayer(any_nonempty[0])
        return any_nonempty[0]

    return current if isinstance(current, QgsVectorLayer) else None


def extract_points_from_geometry(geom) -> list[tuple[float, float]]:
    """Extrai coordenadas de geometrias Point ou MultiPoint."""
    if geom is None or geom.isEmpty():
        return []
    if geom.type() != QgsWkbTypes.PointGeometry:
        return []
    if geom.isMultipart():
        multipoint = geom.asMultiPoint()
        return [(point.x(), point.y()) for point in multipoint] if multipoint else []
    point = geom.asPoint()
    return [(point.x(), point.y())]
