# -*- coding: utf-8 -*-
"""Reconstrucao visual de uma geracao operacional persistida."""

from __future__ import annotations

from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsLineSymbol,
    QgsPointXY,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
)

from ..core.layer_roles import apply_qgis_layer_role, layer_role_definition

GENERATION_PROPERTY = "fortsmart_generation_id"
RESTORED_PROPERTY = "fortsmart_operational_restored"


def _line_layer(name: str, crs_authid: str, fields) -> QgsVectorLayer:
    layer = QgsVectorLayer(f"LineString?crs={crs_authid}", name, "memory")
    layer.dataProvider().addAttributes([QgsField(key, kind) for key, kind in fields])
    layer.updateFields()
    return layer


def _feature(layer, points, values) -> QgsFeature:
    feature = QgsFeature(layer.fields())
    feature.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in points]))
    feature.setAttributes(values)
    return feature


def build_operational_preview_layers(generation) -> list[tuple[object, QgsVectorLayer]]:
    """Cria camadas de memoria a partir do GPKG, sem recalcular a geometria."""
    crs = generation.manifest.working_crs
    field_name = generation.manifest.field_name
    generation_id = generation.manifest.generation_id
    specs = []

    row_definition = layer_role_definition("06_Passadas_Plantio")
    rows = _line_layer(
        row_definition.display_name,
        crs,
        (("source_row_id", QVariant.String), ("pass_id", QVariant.Int),
         ("row_id", QVariant.Int), ("length_m", QVariant.Double)),
    )
    rows.dataProvider().addFeatures([
        _feature(rows, item.geometry, [item.source_row_id, item.pass_id, item.row_id, item.length_m])
        for item in generation.planting_rows
    ])
    specs.append((row_definition, rows, "35,150,70,255", "0.55"))

    track_definition = layer_role_definition("08_Rastros_Pneus")
    tracks = _line_layer(
        track_definition.display_name,
        crs,
        (("track_id", QVariant.String), ("spray_pass_id", QVariant.String),
         ("side", QVariant.String), ("physical_width_m", QVariant.Double),
         ("margin_m", QVariant.Double), ("exclusion_width_m", QVariant.Double)),
    )
    tracks.dataProvider().addFeatures([
        _feature(tracks, item.geometry, [item.track_id, item.spray_pass_id, item.side,
                 item.physical_tire_width_m, item.safety_margin_m,
                 item.effective_exclusion_width_m])
        for item in generation.tire_tracks
    ])
    specs.append((track_definition, tracks, "120,70,25,255", "0.8"))

    shutoff_definition = layer_role_definition("13_Shutoff")
    shutoff = _line_layer(
        shutoff_definition.display_name,
        crs,
        (("segment_id", QVariant.String), ("source_row_id", QVariant.String),
         ("state", QVariant.String), ("reason", QVariant.String),
         ("station_start_m", QVariant.Double), ("station_end_m", QVariant.Double),
         ("tire_track_id", QVariant.String), ("tire_side", QVariant.String)),
    )
    shutoff.dataProvider().addFeatures([
        _feature(shutoff, item.geometry, [item.segment_id, item.source_row_id,
                 item.state.value, item.reason.value, item.station_start_m,
                 item.station_end_m, item.tire_track_id, item.tire_side])
        for item in generation.segments
    ])
    specs.append((shutoff_definition, shutoff, "210,30,40,255", "1.2"))

    result = []
    for definition, layer, color, width in specs:
        layer.updateExtents()
        apply_qgis_layer_role(layer, definition, field_name=field_name)
        layer.setCustomProperty(GENERATION_PROPERTY, generation_id)
        layer.setCustomProperty(RESTORED_PROPERTY, True)
        layer.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple({
            "color": color, "width": width, "capstyle": "round", "joinstyle": "round",
        })))
        result.append((definition, layer))
    return result
