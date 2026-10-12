# -*- coding: utf-8 -*-
"""Controlador QGIS para o fluxo visual de importacao."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFillSymbol,
    QgsLineSymbol,
    QgsProject,
    QgsSingleSymbolRenderer,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)

from ...core.project_manager import build_project_paths, read_project_config
from ...io.import_service import ImportService
from ...io.input_inspector import InputInspector
from ...validators.input_validator import InputValidator


DATA_TYPE_TO_LAYER = {
    "limite cadastral": "field_boundaries",
    "limite operacional": "operational_boundaries",
    "obstáculo": "obstacles",
    "exclusão": "exclusion_areas",
    "carreador": "access_roads",
    "outro": "field_boundaries",
}


class ImportController:
    def __init__(self, iface, import_service=None, inspector=None, validator=None):
        self.iface = iface
        self.import_service = import_service or ImportService()
        self.inspector = inspector or InputInspector()
        self.validator = validator or InputValidator()

    def vector_layers(self):
        return [
            layer
            for layer in QgsProject.instance().mapLayers().values()
            if isinstance(layer, QgsVectorLayer) and layer.isValid()
        ]

    def active_vector_layer(self):
        layer = self.iface.activeLayer()
        if isinstance(layer, QgsVectorLayer) and layer.isValid():
            return layer
        return None

    def inspect_path(self, path, **options):
        inspection = self.inspector.inspect(path, **options)
        validation = self.validator.validate(inspection, csv_options=options)
        return inspection, validation

    def inspect_layer(self, layer):
        return {
            "name": layer.name(),
            "source": layer.source(),
            "crs_authid": layer.crs().authid() or None,
            "geometry_type": QgsWkbTypes.displayString(layer.wkbType()),
            "feature_count": layer.featureCount(),
            "fields": [field.name() for field in layer.fields()],
        }

    def import_layer(self, project_root, layer, data_type):
        config = read_project_config(project_root)
        target_crs = config["master_crs"]
        temp_path = self.export_layer_to_geojson(project_root, layer, target_crs)
        self.patch_geojson_crs(temp_path, target_crs)
        target_layer = DATA_TYPE_TO_LAYER[data_type]
        archive_source = layer.source().split("|", 1)[0]
        if not Path(archive_source).exists():
            archive_source = str(temp_path)
        result = self.import_service.import_field_boundary(
            project_root,
            temp_path,
            target_layer=target_layer,
            data_type=data_type,
            archive_source_path=archive_source,
        )
        preview = None
        if result.status != "INVALID":
            preview = self.write_and_load_project_layer(project_root, temp_path, layer.name(), data_type, target_layer)
        return result, preview

    def import_file(self, project_root, file_path, data_type, internal_layer=None, **options):
        target_layer = DATA_TYPE_TO_LAYER[data_type]
        qgis_layer = self.load_file_as_layer(file_path, internal_layer)
        if qgis_layer is not None and qgis_layer.isValid():
            config = read_project_config(project_root)
            target_crs = config["master_crs"]
            temp_path = self.export_layer_to_geojson(project_root, qgis_layer, target_crs)
            self.patch_geojson_crs(temp_path, target_crs)
            result = self.import_service.import_field_boundary(
                project_root,
                temp_path,
                target_layer=target_layer,
                data_type=data_type,
                archive_source_path=file_path,
                selected_internal_layer=internal_layer,
                **options,
            )
            preview = None
            if result.status != "INVALID":
                preview = self.write_and_load_project_layer(
                    project_root,
                    temp_path,
                    Path(file_path).stem,
                    data_type,
                    target_layer,
                )
            return result, preview

        result = self.import_service.import_field_boundary(
            project_root,
            file_path,
            target_layer=target_layer,
            data_type=data_type,
            **options,
        )
        preview = None
        if result.status == "imported" and str(file_path).lower().endswith((".geojson", ".json")):
            preview = self.add_result_to_map(file_path, Path(file_path).stem, data_type)
        return result, preview

    def load_file_as_layer(self, file_path, internal_layer=None):
        path = str(file_path)
        lower = path.lower()
        uri = path
        if lower.endswith(".gpkg") and internal_layer:
            uri = f"{path}|layername={internal_layer}"
        elif lower.endswith(".kmz") and internal_layer:
            uri = f"/vsizip/{path}/{internal_layer}"
        layer = QgsVectorLayer(uri, internal_layer or Path(path).stem, "ogr")
        return layer if layer.isValid() else None

    def export_layer_to_geojson(self, project_root, layer, target_crs_authid):
        paths = build_project_paths(project_root)
        temp_dir = paths.logs_dir / "tmp_imports"
        temp_dir.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in layer.name())
        temp_path = temp_dir / f"{safe_name}_active_layer.geojson"

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GeoJSON"
        options.fileEncoding = "UTF-8"
        target_crs = QgsCoordinateReferenceSystem(target_crs_authid)
        if target_crs.isValid() and layer.crs() != target_crs:
            options.ct = QgsCoordinateTransform(layer.crs(), target_crs, QgsProject.instance())

        result = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            str(temp_path),
            QgsProject.instance().transformContext(),
            options,
        )
        error_code = result[0] if isinstance(result, tuple) else result
        if error_code != QgsVectorFileWriter.NoError:
            raise RuntimeError(f"Falha ao exportar camada para GeoJSON: {result}")
        return temp_path

    def patch_geojson_crs(self, temp_path, crs_authid):
        data = json.loads(Path(temp_path).read_text(encoding="utf-8"))
        data["crs"] = {"type": "name", "properties": {"name": crs_authid}}
        Path(temp_path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def add_result_to_map(self, path, source_name, data_type):
        layer = QgsVectorLayer(str(path), f"FortSmart - {data_type} - {source_name}", "ogr")
        if not layer.isValid():
            return None
        self.apply_initial_symbology(layer, data_type)
        QgsProject.instance().addMapLayer(layer)
        self.iface.setActiveLayer(layer)
        self.iface.zoomToActiveLayer()
        return layer

    def apply_initial_symbology(self, layer, data_type):
        geometry_type = QgsWkbTypes.geometryType(layer.wkbType())
        if geometry_type == QgsWkbTypes.LineGeometry:
            color = QColor("#8B5A2B") if data_type == "carreador" else QColor("#1f77b4")
            symbol = QgsLineSymbol.createSimple({"color": color.name(), "width": "0.6"})
        else:
            fill_by_type = {
                "limite cadastral": ("#2ca25f", "0,0,0,0"),
                "limite operacional": ("#2b8cbe", "0,0,0,0"),
                "obstáculo": ("#fdae61", "253,174,97,80"),
                "exclusão": ("#d7191c", "215,25,28,80"),
                "outro": ("#756bb1", "117,107,177,50"),
            }
            outline, fill = fill_by_type.get(data_type, fill_by_type["outro"])
            symbol = QgsFillSymbol.createSimple({"outline_color": outline, "color": fill, "outline_width": "0.6"})
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        layer.triggerRepaint()

    def write_and_load_project_layer(self, project_root, source_path, source_name, data_type, target_layer):
        paths = build_project_paths(project_root)
        source = QgsVectorLayer(str(source_path), f"{target_layer}_source", "ogr")
        if not source.isValid():
            return self.add_result_to_map(source_path, source_name, data_type)

        layer_name = f"{target_layer}_{uuid4().hex[:8]}"
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = layer_name
        options.fileEncoding = "UTF-8"
        if hasattr(QgsVectorFileWriter, "CreateOrOverwriteLayer"):
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer

        result = QgsVectorFileWriter.writeAsVectorFormatV3(
            source,
            str(paths.geopackage_path),
            QgsProject.instance().transformContext(),
            options,
        )
        error_code = result[0] if isinstance(result, tuple) else result
        if error_code != QgsVectorFileWriter.NoError:
            return self.add_result_to_map(source_path, source_name, data_type)

        gpkg_layer = QgsVectorLayer(
            f"{paths.geopackage_path}|layername={layer_name}",
            f"FortSmart - {data_type} - {source_name}",
            "ogr",
        )
        if not gpkg_layer.isValid():
            return self.add_result_to_map(source_path, source_name, data_type)
        self.apply_initial_symbology(gpkg_layer, data_type)
        QgsProject.instance().addMapLayer(gpkg_layer)
        self.iface.setActiveLayer(gpkg_layer)
        self.iface.zoomToActiveLayer()
        return gpkg_layer
