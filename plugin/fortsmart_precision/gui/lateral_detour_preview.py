# -*- coding: utf-8 -*-
"""Preview nao destrutivo do desvio lateral e desfazer apos salvar."""

from __future__ import annotations

from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsFillSymbol,
    QgsGeometry,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsPointXY,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
    QgsWkbTypes,
)
from shapely import wkb as shapely_wkb
from shapely.geometry import LineString
from shapely.strtree import STRtree

from ..core.lateral_detour.clearance import build_safe_obstacle, obstacle_core
from ..core.lateral_detour.engine import DETOURED, NO_CONFLICT, contour_radius_for, required_turn_radius
from ..core.lateral_detour.rows import generate_planter_rows
from ..core.lateral_detour.stitcher import WORK_OFF, WORK_ON
from ..core.layer_roles import PREVIEW_SECTION, LayerRoleDefinition, simulation_role_definition
from ..core.obstacle_strategy_controller import FALLBACK_TO_CUT, apply_obstacle_strategy
from ..core.planting_line_cut_engine import line_id_field, line_number_field, spatial_line_numbers
from ..domain.obstacle_strategy import DETOUR_NOT_FEASIBLE, ObstacleConfig

BEHAVIOR = "lateral_detour"

PREVIEW_DEFINITIONS = {
    "SIM_WORK_LINES": LayerRoleDefinition("Master_Path_Preview", PREVIEW_SECTION, "MASTER_PATH", "LAT_MASTER_PATH"),
    "LAT_DETOUR": LayerRoleDefinition("Detour_Preview", PREVIEW_SECTION, "LATERAL_DETOUR_PATH", "LAT_DETOUR"),
    "LAT_ROWS": LayerRoleDefinition("Planter_Rows_Preview", PREVIEW_SECTION, "ROW_PATH", "LAT_ROWS"),
    "LAT_OBSTACLE_BUFFER": LayerRoleDefinition(
        "Obstacle_Buffer_Preview", PREVIEW_SECTION, "OBSTACLE_CLEARANCE", "LAT_OBSTACLE_BUFFER"
    ),
    "SIM_WORK_OFF": LayerRoleDefinition("WORK_OFF_Preview", PREVIEW_SECTION, "WORK_OFF", "LAT_WORK_OFF"),
    "SIM_WORK_ON": LayerRoleDefinition("WORK_ON_Preview", PREVIEW_SECTION, "WORK_ON", "LAT_WORK_ON"),
}
ROW_PATH_DEFINITION = LayerRoleDefinition("36_Linhas_Plantadeira", "30_OPERACAO", "ROW_PATH", "LATERAL_ROW_PATH")
# Role proprio: publish_persisted remove camadas com o mesmo role, e 23_Desvios_Obstaculos e do gerador.
DETOUR_DEFINITION = LayerRoleDefinition(
    "37_Desvio_Lateral", "30_OPERACAO", "LATERAL_DETOUR_PATH", "LATERAL_DETOUR_PATH"
)

# Ordem de exibicao no preview: (chave, visivel)
PREVIEW_ORDER = (
    ("LAT_OBSTACLE_BUFFER", True),
    ("LAT_ROWS", True),
    ("SIM_WORK_LINES", True),
    ("LAT_DETOUR", True),
    ("SIM_WORK_OFF", True),
    ("SIM_WORK_ON", True),
)

MASTER_EXTRA_FIELDS = (
    ("obstacle_strategy", QVariant.String),
    ("detour_status", QVariant.String),
    ("detour_side", QVariant.String),
    ("obstacle_ids", QVariant.String),
    ("min_radius_m", QVariant.Double),
    ("min_clearance_m", QVariant.Double),
    ("fallback", QVariant.Int),
    ("fallback_reason", QVariant.String),
)


def to_shapely(geometry: QgsGeometry):
    return shapely_wkb.loads(bytes(geometry.asWkb()))


def to_qgs(shape) -> QgsGeometry:
    return QgsGeometry.fromWkt(shape.wkt)


def save_outputs():
    """(chave do preview, definicao persistida, permite vazio)."""
    return (
        ("SIM_WORK_LINES", simulation_role_definition("SIM_WORK_LINES"), False),
        ("SIM_WORK_OFF", simulation_role_definition("SIM_WORK_OFF"), True),
        ("SIM_WORK_ON", simulation_role_definition("SIM_WORK_ON"), True),
        ("LAT_DETOUR", DETOUR_DEFINITION, True),
        ("LAT_ROWS", ROW_PATH_DEFINITION, True),
    )


def _memory_layer(geometry: str, crs, name: str, fields) -> QgsVectorLayer:
    layer = QgsVectorLayer(f"{geometry}?crs={crs.authid()}", name, "memory")
    layer.dataProvider().addAttributes([QgsField(field_name, kind) for field_name, kind in fields])
    layer.updateFields()
    return layer


def _add(layer: QgsVectorLayer, geometry: QgsGeometry, values: dict) -> None:
    feature = QgsFeature(layer.fields())
    feature.setGeometry(geometry)
    for name, value in values.items():
        index = layer.fields().lookupField(name)
        if index >= 0:
            feature.setAttribute(index, value)
    layer.dataProvider().addFeature(feature)


def _round(value):
    try:
        return round(float(value), 3) if value is not None and abs(float(value)) != float("inf") else None
    except (TypeError, ValueError):
        return None


class LateralDetourPreviewBuilder:
    """Executa a estrategia por passada usando os helpers do dialogo de corte."""

    def __init__(self, dialog, config: ObstacleConfig):
        self.dialog = dialog
        self.config = config

    def build(self):
        dialog = self.dialog
        config = self.config.validate()
        lines = dialog.lines_combo.currentLayer()
        field = dialog.field_combo.currentLayer()
        obstacles_layer = dialog.obstacle_combo.currentLayer()
        if not isinstance(lines, QgsVectorLayer) or lines.geometryType() != QgsWkbTypes.LineGeometry:
            raise ValueError("Selecione a camada de linhas geradas.")
        if not isinstance(field, QgsVectorLayer) or field.geometryType() != QgsWkbTypes.PolygonGeometry:
            raise ValueError("Selecione a camada poligonal do talhao.")
        if not isinstance(obstacles_layer, QgsVectorLayer) or not obstacles_layer.isValid():
            raise ValueError("Selecione a camada de postes/obstaculos.")

        target_crs = dialog._metric_crs(field)
        field_geom = dialog._combined_geometry(field, target_crs, selected_first=True)
        if field_geom is None or field_geom.isEmpty() or not field_geom.isGeosValid():
            raise ValueError("A geometria do talhao esta vazia ou invalida.")
        allowed_area = to_shapely(field_geom)
        obstacles = [
            (str(fid), to_shapely(geometry))
            for fid, geometry, _name in dialog._obstacle_geometries(obstacles_layer, target_crs)
        ]
        tree = STRtree([geometry for _id, geometry in obstacles]) if obstacles else None
        required = required_turn_radius(config)
        reach = 2.0 * config.clearance + config.obstacle_radius + contour_radius_for(config, required) \
            + 2.0 * max(config.approach_distance, config.return_distance)

        master = _memory_layer("LineString", target_crs, PREVIEW_DEFINITIONS["SIM_WORK_LINES"].display_name, [])
        master.dataProvider().addAttributes(list(lines.fields()))
        master.updateFields()
        dialog._extra_field_names = dialog._add_extra_fields(master.dataProvider(), master.fields().names())
        existing = {name.lower() for name in master.fields().names()}
        master.dataProvider().addAttributes(
            [QgsField(name, kind) for name, kind in MASTER_EXTRA_FIELDS if name not in existing]
        )
        master.updateFields()
        detour_layer = _memory_layer(
            "LineString", target_crs, PREVIEW_DEFINITIONS["LAT_DETOUR"].display_name,
            [("line_id", QVariant.String), ("line_number", QVariant.Int), ("obstacle_ids", QVariant.String),
             ("side", QVariant.String), ("segment_role", QVariant.String), ("min_radius_m", QVariant.Double),
             ("required_radius_m", QVariant.Double)],
        )
        rows_layer = _memory_layer(
            "MultiLineString", target_crs, PREVIEW_DEFINITIONS["LAT_ROWS"].display_name,
            [("line_id", QVariant.String), ("line_number", QVariant.Int), ("row_index", QVariant.Int),
             ("offset_m", QVariant.Double), ("row_spacing_m", QVariant.Double), ("spacing_ok", QVariant.Int)],
        )
        buffer_layer = _memory_layer(
            "Polygon", target_crs, PREVIEW_DEFINITIONS["LAT_OBSTACLE_BUFFER"].display_name,
            [("obstacle_id", QVariant.String), ("clearance_m", QVariant.Double)],
        )
        event_fields = [("event", QVariant.String), ("line_id", QVariant.String), ("line_number", QVariant.Int)]
        events = {
            WORK_OFF: _memory_layer("Point", target_crs, PREVIEW_DEFINITIONS["SIM_WORK_OFF"].display_name, event_fields),
            WORK_ON: _memory_layer("Point", target_crs, PREVIEW_DEFINITIONS["SIM_WORK_ON"].display_name, event_fields),
        }

        for obstacle_id, geometry in obstacles:
            safe = build_safe_obstacle(obstacle_core(geometry, config.obstacle_radius), config.clearance)
            _add(buffer_layer, to_qgs(safe), {"obstacle_id": obstacle_id, "clearance_m": config.clearance})

        source_names = lines.fields().names()
        dialog._number_field = line_number_field(source_names)
        dialog._id_field = line_id_field(source_names)
        transform = dialog._transform(lines.crs(), target_crs)
        features = (
            lines.selectedFeatures()
            if dialog.selected_lines_check.isChecked() and lines.selectedFeatureCount() > 0
            else lines.getFeatures()
        )
        records = []
        for feature in features:
            geometry = QgsGeometry(feature.geometry())
            if geometry.isEmpty():
                continue
            if transform is not None:
                geometry.transform(transform)
            parts = geometry.asMultiPolyline() if geometry.isMultipart() else [geometry.asPolyline()]
            source_id = str(feature.id())
            for part_index, part in enumerate(parts, start=1):
                if len(part) < 2:
                    continue
                points = tuple((point.x(), point.y()) for point in part)
                part_source = source_id if len(parts) == 1 else f"{source_id}_P{part_index}"
                records.append((feature, source_id, part_source, points))

        computed_numbers = {} if dialog._number_field else spatial_line_numbers(
            {source_id: points for _f, source_id, _p, points in reversed(records)}
        )
        counts = {"detoured": 0, "no_conflict": 0, "fallback": 0, "not_feasible": 0}
        log: list[dict] = []
        errors: list[str] = []
        spacing = {"min": None, "max": None}
        pieces_by_line: dict[str, list] = {}

        for feature, source_id, part_source, points in records:
            path = LineString(points)
            nearby = []
            if tree is not None:
                window = path.buffer(reach, quad_segs=4)
                nearby = [obstacles[int(index)] for index in tree.query(window, predicate="intersects")]
            outcome = apply_obstacle_strategy(path, nearby, config, allowed_area=allowed_area, source_id=part_source)
            number = dialog._line_number(feature, computed_numbers.get(source_id))
            parent_id = dialog._parent_line_id(feature, number)
            pieces = pieces_by_line.setdefault(source_id, [])
            for entry in outcome.log:
                log.append({**entry, "line_id": parent_id, "line_number": number})

            detour = outcome.detour
            if outcome.status == NO_CONFLICT:
                counts["no_conflict"] += 1
                pieces.append((feature, part_source, f"{part_source}_S01", points, "PASS", {}))
            elif outcome.status == DETOURED:
                counts["detoured"] += 1
                validation = detour.validation
                values = {
                    "obstacle_strategy": BEHAVIOR,
                    "detour_status": DETOURED,
                    "detour_side": ",".join(section.side.value for section in detour.sections),
                    "obstacle_ids": ",".join(i for section in detour.sections for i in section.obstacle_ids),
                    "min_radius_m": _round(validation.minimum_radius),
                    "min_clearance_m": _round(validation.minimum_clearance),
                    "fallback": 0,
                }
                pieces.append((feature, part_source, f"{part_source}_D01", tuple(detour.final_path.coords), "DETOUR", values))
                self._add_detour_parts(detour_layer, detour, parent_id, number)
                for state, line in detour.work_segments:
                    if state == WORK_OFF:
                        self._add_event(events[WORK_OFF], line.coords[0], WORK_OFF, parent_id, number)
                        self._add_event(events[WORK_ON], line.coords[-1], WORK_ON, parent_id, number)
                if config.generate_rows:
                    rows = generate_planter_rows(
                        detour.final_path, config.row_count, config.row_spacing,
                        spacing_tolerance=config.spacing_tolerance, allowed_area=allowed_area,
                    )
                    self._add_rows(rows_layer, rows, parent_id, number, config.row_spacing)
                    spacing["min"] = rows.minimum_spacing if spacing["min"] is None else min(spacing["min"], rows.minimum_spacing)
                    spacing["max"] = rows.maximum_spacing if spacing["max"] is None else max(spacing["max"], rows.maximum_spacing)
                    errors.extend(f"{parent_id}: {message}" for message in rows.errors)
            elif outcome.status == FALLBACK_TO_CUT:
                counts["fallback"] += 1
                values = {
                    "obstacle_strategy": BEHAVIOR,
                    "detour_status": DETOUR_NOT_FEASIBLE,
                    "fallback": 1,
                    "fallback_reason": outcome.fallback_reason[:250],
                }
                for segment in outcome.existing_result:
                    pieces.append((feature, segment.source_id, segment.segment_id, segment.path_points, "CUT", values))
            else:
                counts["not_feasible"] += 1
                errors.append(f"{parent_id}: desvio inviavel ({outcome.fallback_reason}).")
                values = {"obstacle_strategy": BEHAVIOR, "detour_status": DETOUR_NOT_FEASIBLE, "fallback": 0,
                          "fallback_reason": outcome.fallback_reason[:250]}
                pieces.append((feature, part_source, f"{part_source}_S01", points, "PASS", values))

        output_features = []
        for source_id, pieces in pieces_by_line.items():
            feature = pieces[0][0]
            number = dialog._line_number(feature, computed_numbers.get(source_id))
            parent_id = dialog._parent_line_id(feature, number)
            for index, (feat, part_source, segment_id, points, mode, extra) in enumerate(pieces, start=1):
                before = len(output_features)
                dialog._append_output_feature(
                    output_features, master, feat, part_source, segment_id, points, mode, 0,
                    identity={
                        "line_id": parent_id, "line_number": number, "parent_line_id": parent_id,
                        "segment_index": index, "segment_count": len(pieces),
                    },
                )
                if len(output_features) > before:
                    created = output_features[-1]
                    created.setAttribute(master.fields().lookupField("machine_width_m"), config.machine_width)
                    created.setAttribute(master.fields().lookupField("clearance_m"), config.clearance)
                    for name, value in extra.items():
                        index_field = master.fields().lookupField(name)
                        if index_field >= 0:
                            created.setAttribute(index_field, value)
        master.dataProvider().addFeatures(output_features)
        for layer in (master, detour_layer, rows_layer, buffer_layer, *events.values()):
            layer.updateExtents()

        layers = {
            "SIM_WORK_LINES": master,
            "LAT_DETOUR": detour_layer,
            "LAT_ROWS": rows_layer,
            "LAT_OBSTACLE_BUFFER": buffer_layer,
            "SIM_WORK_OFF": events[WORK_OFF],
            "SIM_WORK_ON": events[WORK_ON],
        }
        report = {
            "status": "OK" if not errors else "INVALID",
            "behavior": BEHAVIOR,
            "obstacle_strategy": config.strategy.value,
            "config": config.to_dict(),
            "source_layer": lines.name(),
            "field_layer": field.name(),
            "obstacle_layer": obstacles_layer.name(),
            "working_crs": target_crs.authid(),
            "machine_width_m": config.machine_width,
            "clearance_m": config.clearance,
            "required_radius_m": required,
            "contour_radius_m": contour_radius_for(config, required),
            "obstacle_count": len(obstacles),
            "source_line_count": len(records),
            "output_logical_line_count": len(pieces_by_line),
            "detoured_count": counts["detoured"],
            "no_conflict_count": counts["no_conflict"],
            "fallback_count": counts["fallback"],
            "not_feasible_count": counts["not_feasible"],
            "row_spacing_min_m": _round(spacing["min"]),
            "row_spacing_max_m": _round(spacing["max"]),
            "obstacle_log": log,
            "errors": errors,
            "original_layers_modified": False,
        }
        return layers, report

    @staticmethod
    def _add_detour_parts(layer, detour, line_id, number):
        for section in detour.sections:
            for role, coords in (
                ("DETOUR_ENTRY", section.transition_in),
                ("DETOUR_CONTOUR", section.contour),
                ("DETOUR_EXIT", section.transition_out),
            ):
                if len(coords) < 2:
                    continue
                _add(layer, QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in coords]), {
                    "line_id": line_id,
                    "line_number": number,
                    "obstacle_ids": ",".join(section.obstacle_ids),
                    "side": section.side.value,
                    "segment_role": role,
                    "min_radius_m": _round(section.minimum_radius),
                    "required_radius_m": _round(detour.required_radius),
                })

    @staticmethod
    def _add_event(layer, xy, event, line_id, number):
        _add(layer, QgsGeometry.fromPointXY(QgsPointXY(xy[0], xy[1])), {
            "event": event, "line_id": line_id, "line_number": number,
        })

    @staticmethod
    def _add_rows(layer, rows, line_id, number, row_spacing):
        for row in rows.rows:
            parts = row.clipped_parts or ()
            if not parts:
                continue
            geometry = QgsGeometry.fromMultiPolylineXY(
                [[QgsPointXY(x, y) for x, y in part.coords] for part in parts]
            )
            _add(layer, geometry, {
                "line_id": line_id,
                "line_number": number,
                "row_index": row.row_index,
                "offset_m": row.offset,
                "row_spacing_m": row_spacing,
                "spacing_ok": 1 if rows.spacing_ok else 0,
            })


def style_preview_layer(key: str, layer: QgsVectorLayer) -> None:
    def line(color, width, style="solid"):
        return QgsLineSymbol.createSimple({"line_color": color, "line_width": str(width), "line_style": style})

    symbols = {
        "SIM_WORK_LINES": line("30,170,70", 0.9),
        "LAT_DETOUR": line("230,120,0", 1.2),
        "LAT_ROWS": line("90,90,90", 0.25),
        "LAT_OBSTACLE_BUFFER": QgsFillSymbol.createSimple(
            {"color": "220,40,40,70", "outline_color": "200,30,30,255", "outline_width": "0.3"}
        ),
        "SIM_WORK_OFF": QgsMarkerSymbol.createSimple({"name": "square", "color": "220,30,30", "size": "2.6"}),
        "SIM_WORK_ON": QgsMarkerSymbol.createSimple({"name": "triangle", "color": "30,170,70", "size": "2.8"}),
    }
    if key in symbols:
        layer.setRenderer(QgsSingleSymbolRenderer(symbols[key]))
        layer.triggerRepaint()


def snapshot_role_layers(manager, field_name, definitions):
    """Copia em memoria o que ja estava salvo para cada role (None = nao existia)."""
    snapshots = []
    for definition in definitions:
        layer, _reused = manager.load_persisted_layer(field_name, definition)
        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            snapshots.append((definition, None))
            continue
        geometry = QgsWkbTypes.displayString(layer.wkbType())
        copy = QgsVectorLayer(f"{geometry}?crs={layer.crs().authid()}", definition.display_name, "memory")
        copy.dataProvider().addAttributes(list(layer.fields()))
        copy.updateFields()
        features = []
        for source in layer.getFeatures():
            feature = QgsFeature(copy.fields())
            feature.setGeometry(QgsGeometry(source.geometry()))
            feature.setAttributes(source.attributes())
            features.append(feature)
        copy.dataProvider().addFeatures(features)
        copy.updateExtents()
        snapshots.append((definition, copy))
    return snapshots


def restore_role_layers(project, manager, field_name, snapshots, publish):
    """Volta cada role ao estado anterior ao salvamento do desvio."""
    restored = []
    for definition, snapshot in snapshots:
        if snapshot is None:
            manager.remove_role_layer(field_name, definition)
            restored.append(f"{definition.display_name} (removida)")
            continue
        result = manager.persist_layer(snapshot, definition, field_name, allow_empty=True)
        publish(project, snapshot, result.layer, reused=result.reused_layer, field_name=field_name, definition=definition)
        restored.append(f"{definition.display_name} (restaurada)")
    return restored
