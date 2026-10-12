# -*- coding: utf-8 -*-
"""Reprojeta camadas vetoriais para CRS metrico (QGIS) — uma ou varias."""

from __future__ import annotations

from dataclasses import dataclass, field

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)

from ..core.crs import inspect_authid, normalize_authid, suggest_sirgas_utm_epsg
from ..core.zone_converter import build_zone_conversion_plan, crs_status


def layer_centroid_lonlat(layer) -> tuple[float, float] | None:
    """Centroide aproximado da camada em graus (EPSG:4674).

    Usa extent/centroide da primeira feicao — evita unaryUnion (pode travar
    em pivots e multipoligonos grandes).
    """
    if layer is None or not isinstance(layer, QgsVectorLayer):
        return None

    center = None
    extent = layer.extent()
    if extent is not None and not extent.isEmpty():
        center = QgsPointXY(extent.center())
    else:
        for feature in layer.getFeatures():
            geom = feature.geometry()
            if geom is None or geom.isEmpty():
                continue
            try:
                center = geom.centroid().asPoint()
            except Exception:
                pt = geom.boundingBox().center()
                center = QgsPointXY(pt.x(), pt.y())
            break
    if center is None:
        return None

    source = layer.crs()
    target = QgsCoordinateReferenceSystem("EPSG:4674")
    if not source.isValid():
        return (center.x(), center.y())
    if source == target or source.authid() in ("EPSG:4326", "EPSG:4674"):
        return (center.x(), center.y())
    try:
        transform = QgsCoordinateTransform(source, target, QgsProject.instance())
        point = transform.transform(center)
        return (point.x(), point.y())
    except Exception:
        return None


def _memory_uri_for_layer(layer: QgsVectorLayer, target_authid: str) -> str:
    """URI memory compatível com Multi*/curvas linearizadas."""
    wkb = layer.wkbType()
    flat = QgsWkbTypes.flatType(wkb)
    if QgsWkbTypes.isCurvedType(flat):
        geom_type = QgsWkbTypes.geometryType(flat)
        if geom_type == QgsWkbTypes.LineGeometry:
            type_name = "MultiLineString" if QgsWkbTypes.isMultiType(flat) else "LineString"
        elif geom_type == QgsWkbTypes.PolygonGeometry:
            type_name = "MultiPolygon" if QgsWkbTypes.isMultiType(flat) else "Polygon"
        else:
            type_name = "Point"
    else:
        type_name = QgsWkbTypes.displayString(flat) or "Polygon"
        if type_name in ("Unknown", "NoGeometry", ""):
            geom_type = layer.geometryType()
            if geom_type == QgsWkbTypes.PointGeometry:
                type_name = "Point"
            elif geom_type == QgsWkbTypes.LineGeometry:
                type_name = "LineString"
            else:
                type_name = "Polygon"
    return f"{type_name}?crs={target_authid}"


def reproject_vector_layer(layer: QgsVectorLayer, target_authid: str, *, suffix: str = "") -> QgsVectorLayer:
    """Copia camada vetorial reprojetada para CRS alvo (memoria)."""
    target_crs = QgsCoordinateReferenceSystem(target_authid)
    if not target_crs.isValid():
        raise ValueError(f"CRS invalido: {target_authid}")
    if not layer.isValid():
        raise ValueError(f"Camada invalida: {layer.name()}")

    out_name = f"{layer.name()}{suffix or f' ({target_authid})'}"
    # Evita duplicar sufixo se ja foi convertido.
    if target_authid.replace(":", "") in out_name.replace(":", "") and suffix == "":
        base = layer.name()
        if f"({target_authid})" in base:
            out_name = base
        else:
            out_name = f"{base} ({target_authid})"

    out = QgsVectorLayer(_memory_uri_for_layer(layer, target_authid), out_name, "memory")
    if not out.isValid():
        raise ValueError(
            f"Nao foi possivel criar camada de saida ({_memory_uri_for_layer(layer, target_authid)})."
        )

    out_fields = QgsFields(layer.fields())
    out.dataProvider().addAttributes(out_fields)
    out.updateFields()

    transform = QgsCoordinateTransform(layer.crs(), target_crs, QgsProject.instance())
    features = []
    errors = 0
    out_geom_type = out.geometryType()
    for feature in layer.getFeatures():
        if not feature.geometry() or feature.geometry().isEmpty():
            continue
        try:
            geom = QgsGeometry(feature.geometry())
            if QgsWkbTypes.isCurvedType(geom.wkbType()):
                try:
                    linear = geom.constGet().curveToLine()
                    geom = QgsGeometry(linear.clone())
                except Exception:
                    converted = geom.convertToType(out_geom_type, True)
                    if converted is not None and not converted.isEmpty():
                        geom = converted
            # Garante tipo compativel com a camada memory de saida.
            if geom.type() != out_geom_type:
                converted = geom.convertToType(out_geom_type, True)
                if converted is None or converted.isEmpty():
                    converted = geom.convertToType(out_geom_type, False)
                if converted is not None and not converted.isEmpty():
                    geom = converted
            result_code = geom.transform(transform)
            if result_code != 0:
                # Tenta novamente forcando contexto do projeto.
                geom = QgsGeometry(feature.geometry())
                geom.transform(transform)
            if geom.isEmpty():
                errors += 1
                continue
            new_feat = QgsFeature(out.fields())
            new_feat.setGeometry(geom)
            attrs = feature.attributes()
            # Copia atributos mesmo se contagem divergir (preenche o que couber).
            if attrs:
                new_feat.setAttributes(list(attrs)[: len(out.fields())])
            features.append(new_feat)
        except Exception:
            errors += 1
            continue

    if not features:
        raise ValueError(
            f"Nenhuma feicao foi reprojetada de '{layer.name()}' para {target_authid}. "
            f"Verifique geometrias invalidas ({errors} erro(s)) e o CRS de origem "
            f"({layer.crs().authid() or '?'})."
        )

    added, _ = out.dataProvider().addFeatures(features)
    if not added:
        raise ValueError(
            f"Falha ao gravar feicoes reprojetadas de '{layer.name()}' "
            f"({len(features)} geometria(s) transformada(s))."
        )
    out.updateExtents()
    if int(out.featureCount() or 0) <= 0:
        raise ValueError(
            f"Camada reprojetada '{out_name}' ficou com 0 feicoes. "
            "Use a camada original com geometria e tente novamente."
        )
    return out


def layer_needs_reprojection(layer: QgsVectorLayer, target_authid: str) -> bool:
    """True se a camada nao esta no CRS alvo SIRGAS/UTM."""
    if layer is None or not isinstance(layer, QgsVectorLayer) or not layer.isValid():
        return False
    current = normalize_authid(layer.crs().authid())
    target = normalize_authid(target_authid)
    if not current:
        return True
    if current == target:
        return False
    # Ja em outro SIRGAS UTM sul: ainda "precisa" se destino for outro (zona errada).
    return True


def suggest_target_from_layers(layers: list[QgsVectorLayer]) -> str | None:
    """Infere EPSG SIRGAS recomendado a partir das camadas (centroide)."""
    for layer in layers:
        if not isinstance(layer, QgsVectorLayer):
            continue
        centroid = layer_centroid_lonlat(layer)
        if centroid is None:
            continue
        lon, lat = centroid
        try:
            return suggest_sirgas_utm_epsg(lon, lat)
        except Exception:
            continue
    return None


@dataclass
class BatchReprojectResult:
    target_authid: str
    converted: list[QgsVectorLayer] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    mapping: dict[str, QgsVectorLayer] = field(default_factory=dict)  # old id -> new layer

    @property
    def ok_count(self) -> int:
        return len(self.converted)

    def summary(self) -> str:
        lines = [
            f"Destino: {self.target_authid}",
            f"Convertidas: {len(self.converted)}",
            f"Ja ok / ignoradas: {len(self.skipped)}",
            f"Falhas: {len(self.failed)}",
        ]
        if self.converted:
            lines.append("Novas camadas:")
            for layer in self.converted:
                lines.append(f"  • {layer.name()}")
        if self.failed:
            lines.append("Falhas:")
            for name, err in self.failed:
                lines.append(f"  • {name}: {err}")
        return "\n".join(lines)


def collect_project_vector_layers(
    *,
    include_ids: set[str] | None = None,
    only_needing: bool = False,
    target_authid: str | None = None,
) -> list[QgsVectorLayer]:
    """Lista camadas vetoriais do projeto (opcionalmente so as que precisam converter)."""
    layers: list[QgsVectorLayer] = []
    for layer in QgsProject.instance().mapLayers().values():
        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            continue
        if include_ids is not None and layer.id() not in include_ids:
            continue
        # Pula camadas memory ja convertidas com o sufixo do destino (evita loop).
        name = layer.name()
        if target_authid and f"({target_authid})" in name and only_needing:
            current = normalize_authid(layer.crs().authid())
            if current == normalize_authid(target_authid):
                continue
        if only_needing and target_authid:
            if not layer_needs_reprojection(layer, target_authid):
                continue
            status = crs_status(layer.crs().authid())
            # Converte geografico e nao-padrao; se ja e outro UTM SIRGAS, inclui se != alvo.
            if status.value == "ok" and normalize_authid(layer.crs().authid()) == normalize_authid(
                target_authid
            ):
                continue
        layers.append(layer)
    return layers


def reproject_layers_batch(
    layers: list[QgsVectorLayer],
    target_authid: str,
    *,
    add_to_project: bool = True,
    set_project_crs: bool = True,
    skip_if_already_target: bool = True,
) -> BatchReprojectResult:
    """Reprojeta varias camadas para o mesmo SIRGAS 2000 / UTM."""
    target = normalize_authid(target_authid)
    result = BatchReprojectResult(target_authid=target)
    project = QgsProject.instance()

    for layer in layers:
        if layer is None or not isinstance(layer, QgsVectorLayer):
            continue
        name = layer.name()
        if skip_if_already_target and not layer_needs_reprojection(layer, target):
            result.skipped.append(name)
            result.mapping[layer.id()] = layer
            continue
        # Evita reconverter camada ja com sufixo do destino.
        if f"({target})" in name and normalize_authid(layer.crs().authid()) == target:
            result.skipped.append(name)
            result.mapping[layer.id()] = layer
            continue
        try:
            new_layer = reproject_vector_layer(layer, target)
            if add_to_project:
                project.addMapLayer(new_layer)
            result.converted.append(new_layer)
            result.mapping[layer.id()] = new_layer
        except Exception as exc:
            result.failed.append((name, str(exc)))

    if set_project_crs and (result.converted or result.skipped):
        crs = QgsCoordinateReferenceSystem(target)
        if crs.isValid():
            project.setCrs(crs)

    return result


def find_existing_metric_twin(
    source_layer: QgsVectorLayer,
    target_authid: str,
) -> QgsVectorLayer | None:
    """Se ja existe 'Nome (EPSG:…)' no projeto COM FEICOES, reutiliza."""
    if source_layer is None:
        return None
    target = normalize_authid(target_authid)
    wanted = f"{source_layer.name()} ({target})"
    base = source_layer.name().split("(EPSG:")[0].strip()
    for layer in list(QgsProject.instance().mapLayers().values()):
        if not isinstance(layer, QgsVectorLayer):
            continue
        if normalize_authid(layer.crs().authid()) != target:
            continue
        if layer.name() == wanted or layer.name().startswith(base + " (EPSG:"):
            if int(layer.featureCount() or 0) > 0:
                return layer
            # Twin vazio: remove para nao bloquear reconversao.
            try:
                QgsProject.instance().removeMapLayer(layer.id())
            except Exception:
                pass
    return None


def ensure_layers_metric(
    layers: list[QgsVectorLayer | None],
    *,
    target_authid: str | None = None,
) -> BatchReprojectResult:
    """Garante camadas no CRS metrico: reusa twin se existir, senao converte."""
    cleaned = [layer for layer in layers if isinstance(layer, QgsVectorLayer)]
    if not cleaned:
        return BatchReprojectResult(target_authid=target_authid or "")

    # Prefere fontes com feicoes (evita converter/usar camada vazia).
    cleaned_nonempty = [layer for layer in cleaned if int(layer.featureCount() or 0) > 0]
    cleaned = cleaned_nonempty or cleaned

    target = target_authid or suggest_target_from_layers(cleaned)
    if not target:
        for layer in cleaned:
            centroid = layer_centroid_lonlat(layer)
            if centroid is None:
                continue
            plan = build_zone_conversion_plan(layer.crs().authid(), centroid[0], centroid[1])
            target = plan.target_authid
            break
    if not target:
        raise ValueError(
            "Nao foi possivel sugerir SIRGAS 2000 / UTM. "
            "Carregue ao menos uma camada com geometria (talhao/limite)."
        )

    result = BatchReprojectResult(target_authid=normalize_authid(target))
    to_convert: list[QgsVectorLayer] = []
    for layer in cleaned:
        if int(layer.featureCount() or 0) <= 0:
            result.failed.append((layer.name(), "camada com 0 feicoes"))
            continue
        twin = find_existing_metric_twin(layer, result.target_authid)
        if twin is not None:
            result.skipped.append(layer.name())
            result.mapping[layer.id()] = twin
            continue
        if not layer_needs_reprojection(layer, result.target_authid):
            result.skipped.append(layer.name())
            result.mapping[layer.id()] = layer
            continue
        to_convert.append(layer)

    if to_convert:
        batch = reproject_layers_batch(
            to_convert,
            result.target_authid,
            add_to_project=True,
            set_project_crs=True,
        )
        result.converted.extend(batch.converted)
        result.failed.extend(batch.failed)
        result.mapping.update(batch.mapping)
    elif result.skipped:
        crs = QgsCoordinateReferenceSystem(result.target_authid)
        if crs.isValid():
            QgsProject.instance().setCrs(crs)

    return result
