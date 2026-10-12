# -*- coding: utf-8 -*-
"""Persistencia canonica das camadas FortSmart em GeoPackage (um arquivo por talhao).

Preview continua em memoria; so resultados confirmados passam por aqui. A
identidade persistente e (field_id, fortsmart_role): uma tabela por role no
GPKG do talhao, com o nome canonico (display_name) do catalogo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsField,
    QgsProject,
    QgsProviderRegistry,
    QgsVectorFileWriter,
    QgsVectorLayer,
)

from .geometry_write_check import GeometryWriteAudit
from .layer_roles import (
    PERSISTED_PROPERTY,
    SOURCE_LAYER_ID_PROPERTY,
    STORAGE_GEOPACKAGE,
    STORAGE_PROPERTY,
    UPDATED_AT_PROPERTY,
    LayerRoleDefinition,
    canonical_field_name,
    feature_identity,
    role_field_schema,
    set_layer_role_properties,
)

STORAGE_DIR_NAME = "fortsmart_data"

PROJECT_NOT_SAVED = "PROJECT_NOT_SAVED"
STORAGE_PATH_UNAVAILABLE = "STORAGE_PATH_UNAVAILABLE"
GPKG_WRITE_FAILED = "GPKG_WRITE_FAILED"
FIELD_ID_MISSING = "FIELD_ID_MISSING"
SCHEMA_CONFLICT = "SCHEMA_CONFLICT"

STATUS_PERSISTED = "OK"
STATUS_KEPT_PREVIOUS = "KEPT_PREVIOUS"

MESSAGES = {
    PROJECT_NOT_SAVED: "Salve o projeto QGIS antes de persistir os resultados FortSmart.",
    STORAGE_PATH_UNAVAILABLE: "Não foi possível criar o diretório de dados FortSmart.",
    GPKG_WRITE_FAILED: "Não foi possível salvar {name}.",
    FIELD_ID_MISSING: "A camada não possui identificação de talhão.",
    SCHEMA_CONFLICT: "A tabela existente possui estrutura incompatível.",
}
KEPT_PREVIOUS_MESSAGE = "Resultado vazio. A camada persistida anterior foi mantida."

_FIELD_TYPES = {"string": QVariant.String, "int": QVariant.Int, "double": QVariant.Double}


class PersistenceError(Exception):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or MESSAGES.get(code, code))
        self.code = code


@dataclass
class PersistResult:
    status: str
    layer: QgsVectorLayer | None
    table: str
    path: str
    feature_count: int
    reused_layer: bool = False
    warnings: list = field(default_factory=list)
    message: str = ""


def _storage_slug(field_id: str) -> str:
    return re.sub(r"[^\w.-]+", "_", field_id, flags=re.UNICODE).strip("._") or "PROJETO"


def _python_value(value):
    if value is None:
        return None
    checker = getattr(value, "isNull", None)
    if callable(checker) and checker():
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str)):
        return value
    return str(value)


def _ogr_field_type(qgs_field):
    from osgeo import ogr

    kind = qgs_field.type()
    if kind in (QVariant.Int, QVariant.Bool):
        return ogr.OFTInteger
    if kind in (QVariant.LongLong, QVariant.UInt, QVariant.ULongLong):
        return ogr.OFTInteger64
    if kind == QVariant.Double:
        return ogr.OFTReal
    return ogr.OFTString


def _numeric_ogr(kind) -> bool:
    from osgeo import ogr

    return kind in (ogr.OFTInteger, ogr.OFTInteger64, ogr.OFTReal)


def _observe_ogr_geometry(audit: GeometryWriteAudit, ogr_geometry, table_geometry_type, feature_id) -> None:
    """Registra o que ForceTo faria; trabalha numa copia, a geometria gravada nao muda."""
    from osgeo import ogr

    flat = ogr.GT_Flatten(ogr_geometry.GetGeometryType())
    parts = ogr_geometry.GetGeometryCount() if flat in (4, 5, 6, 7) else 1
    valid_before = bool(ogr_geometry.IsValid())
    forced = ogr.ForceTo(ogr_geometry.Clone(), table_geometry_type)
    valid_after = bool(forced.IsValid()) if forced is not None else False
    audit.observe(
        flat, feature_id=feature_id, part_count=parts, valid_before=valid_before, valid_after=valid_after
    )


def _geometry_audit(table: str, table_geometry_type) -> GeometryWriteAudit | None:
    from osgeo import ogr

    from ..feature_flags import ENABLE_GPKG_GEOMETRY_CHECK_V1, is_enabled

    if not is_enabled(ENABLE_GPKG_GEOMETRY_CHECK_V1):
        return None
    return GeometryWriteAudit(table, ogr.GT_Flatten(table_geometry_type))


def _open(path, *, update=False):
    """Abre o GPKG como vetor; None se nao existe/invalido (com ou sem gdal.UseExceptions)."""
    from osgeo import gdal

    if not Path(path).exists():
        return None
    flags = gdal.OF_VECTOR | (gdal.OF_UPDATE if update else 0)
    try:
        return gdal.OpenEx(str(path), flags)
    except RuntimeError:
        return None


class FortSmartPersistenceManager:
    """Unico ponto que grava/le o GPKG canonico; dialogs so chamam persist_layer."""

    def __init__(self, project: QgsProject | None = None):
        self.project = project or QgsProject.instance()

    # ------------------------------------------------------------ caminhos --
    def get_project_storage_root(self) -> Path:
        if not self.project.fileName():
            raise PersistenceError(PROJECT_NOT_SAVED)
        return Path(self.project.absolutePath()) / STORAGE_DIR_NAME

    def storage_available(self) -> bool:
        return bool(self.project.fileName())

    def get_field_storage_path(self, field_name: str | None) -> Path:
        slug = _storage_slug(self._field_id(field_name))
        return self.get_project_storage_root() / slug / f"fortsmart_{slug}.gpkg"

    @staticmethod
    def _field_id(field_name: str | None) -> str:
        if not str(field_name or "").strip():
            raise PersistenceError(FIELD_ID_MISSING)
        return canonical_field_name(field_name)

    def ensure_geopackage(self, path: Path) -> Path:
        from osgeo import gdal

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PersistenceError(STORAGE_PATH_UNAVAILABLE) from exc
        if not path.exists():
            try:
                source = gdal.GetDriverByName("GPKG").Create(str(path), 0, 0, 0, gdal.GDT_Unknown)
            except RuntimeError as exc:
                raise PersistenceError(STORAGE_PATH_UNAVAILABLE) from exc
            if source is None:
                raise PersistenceError(STORAGE_PATH_UNAVAILABLE)
            source = None
        return path

    # -------------------------------------------------------------- leitura --
    @staticmethod
    def table_feature_count(path: Path, table: str) -> int | None:
        """Feicoes da tabela; None se a tabela (ou o arquivo) nao existe."""
        source = _open(path)
        if source is None:
            return None
        layer = source.GetLayerByName(table)
        count = None if layer is None else int(layer.GetFeatureCount())
        source = None
        return count

    @staticmethod
    def table_geometry_type(path: Path, table: str) -> int | None:
        """Tipo OGR achatado da tabela, lido do cabecalho; None se a tabela nao existe."""
        from osgeo import ogr

        source = _open(path)
        if source is None:
            return None
        layer = source.GetLayerByName(table)
        kind = None if layer is None else int(ogr.GT_Flatten(layer.GetGeomType()))
        source = None
        return kind

    @staticmethod
    def table_names(path: Path) -> list[str]:
        source = _open(path)
        if source is None:
            return []
        names = [source.GetLayerByIndex(index).GetName() for index in range(source.GetLayerCount())]
        source = None
        return names

    def _project_layers_for_table(self, path: Path, table: str) -> list[QgsVectorLayer]:
        target = str(Path(path).resolve()).casefold()
        found = []
        for layer in self.project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer) or layer.providerType() != "ogr":
                continue
            parts = QgsProviderRegistry.instance().decodeUri("ogr", layer.source())
            source_path = parts.get("path") or ""
            if source_path and str(Path(source_path).resolve()).casefold() == target \
                    and parts.get("layerName") == table:
                found.append(layer)
        return found

    def load_persisted_layer(self, field_name: str | None, definition: LayerRoleDefinition):
        """(camada, reutilizada): recarrega a camada do projeto que ja aponta para a tabela."""
        path = self.get_field_storage_path(field_name)
        if self.table_feature_count(path, definition.display_name) is None:
            return None, False
        existing = self._project_layers_for_table(path, definition.display_name)
        if existing:
            layer = existing[0]
            layer.dataProvider().reloadData()
            layer.reload()
            layer.updateExtents()
            layer.triggerRepaint()
            return layer, True
        layer = QgsVectorLayer(f"{path}|layername={definition.display_name}", definition.display_name, "ogr")
        return (layer, False) if layer.isValid() else (None, False)

    # ------------------------------------------------------------- escrita --
    def persist_layer(
        self,
        source: QgsVectorLayer,
        definition: LayerRoleDefinition,
        field_name: str | None,
        *,
        allow_empty: bool = False,
    ) -> PersistResult:
        field_id = self._field_id(field_name)
        path = self.ensure_geopackage(self.get_field_storage_path(field_name))
        table = definition.display_name
        enriched = self._enriched_copy(source, definition, field_id)
        count = enriched.featureCount()
        previous = self.table_feature_count(path, table)
        if count == 0 and previous and not allow_empty:
            layer, reused = self.load_persisted_layer(field_name, definition)
            self._mark_persisted(layer, definition, field_name, source)
            return PersistResult(
                STATUS_KEPT_PREVIOUS, layer, table, str(path), previous, reused, message=KEPT_PREVIOUS_MESSAGE
            )
        warnings = []
        if previous is None:
            self._write_new_table(enriched, path, table)
        else:
            warnings = self.replace_role_layer(enriched, path, table)
        self.ensure_spatial_index(path, table)
        layer, reused = self.load_persisted_layer(field_name, definition)
        if layer is None:
            raise PersistenceError(GPKG_WRITE_FAILED, MESSAGES[GPKG_WRITE_FAILED].format(name=table))
        self._mark_persisted(layer, definition, field_name, source)
        return PersistResult(STATUS_PERSISTED, layer, table, str(path), count, reused, warnings)

    @staticmethod
    def _mark_persisted(layer, definition, field_name, source) -> None:
        if layer is None:
            return
        set_layer_role_properties(layer, definition, field_name=field_name)
        layer.setCustomProperty(STORAGE_PROPERTY, STORAGE_GEOPACKAGE)
        layer.setCustomProperty(PERSISTED_PROPERTY, True)
        layer.setCustomProperty(UPDATED_AT_PROPERTY, datetime.now(timezone.utc).isoformat(timespec="seconds"))
        try:
            layer.setCustomProperty(SOURCE_LAYER_ID_PROPERTY, source.id())
        except RuntimeError:
            pass

    @staticmethod
    def _enriched_copy(source: QgsVectorLayer, definition: LayerRoleDefinition, field_id: str) -> QgsVectorLayer:
        """Copia em memoria com os campos minimos do role; a fonte nao e alterada."""
        copy = source.materialize(QgsFeatureRequest())
        provider = copy.dataProvider()
        existing = {name.casefold() for name in copy.fields().names()}
        missing = [
            QgsField(name, _FIELD_TYPES[kind])
            for name, kind in role_field_schema(definition.role)
            if name.casefold() not in existing
        ]
        if missing:
            provider.addAttributes(missing)
            copy.updateFields()
        names = copy.fields().names()
        changes = {}
        for feature in copy.getFeatures():
            attributes = dict(zip(names, feature.attributes()))
            values = feature_identity(definition.role, attributes, field_id=field_id, feature_id=feature.id())
            if values:
                changes[feature.id()] = {copy.fields().indexFromName(name): value for name, value in values.items()}
        if changes:
            provider.changeAttributeValues(changes)
        return copy

    def _write_new_table(self, layer: QgsVectorLayer, path: Path, table: str) -> None:
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = table
        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        options.layerOptions = ["SPATIAL_INDEX=YES"]
        result = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer, str(path), self.project.transformContext(), options
        )
        code = result[0] if isinstance(result, tuple) else result
        written = self.table_feature_count(path, table)
        if code != QgsVectorFileWriter.NoError or written != layer.featureCount():
            self.remove_table(path, table)
            raise PersistenceError(GPKG_WRITE_FAILED, MESSAGES[GPKG_WRITE_FAILED].format(name=table))

    def replace_role_layer(self, layer: QgsVectorLayer, path: Path, table: str) -> list[str]:
        """Troca o conteudo da tabela numa transacao: se falhar, a anterior continua valida.

        Campos do usuario nunca sao removidos; campos faltantes sao adicionados.
        """
        from osgeo import ogr

        failed = MESSAGES[GPKG_WRITE_FAILED].format(name=table)
        source = _open(path, update=True)
        target = source.GetLayerByName(table) if source is not None else None
        if target is None:
            raise PersistenceError(GPKG_WRITE_FAILED, failed)
        warnings = []
        try:
            definition = target.GetLayerDefn()
            fid_column = (target.GetFIDColumn() or "fid").casefold()
            existing = {
                definition.GetFieldDefn(index).GetName().casefold(): definition.GetFieldDefn(index)
                for index in range(definition.GetFieldCount())
            }
            for qgs_field in layer.fields():
                name = qgs_field.name()
                if name.casefold() == fid_column:
                    continue
                current = existing.get(name.casefold())
                wanted = _ogr_field_type(qgs_field)
                if current is None:
                    try:
                        created = target.CreateField(ogr.FieldDefn(name, wanted))
                    except RuntimeError:
                        created = 1
                    if created != 0:
                        raise PersistenceError(SCHEMA_CONFLICT)
                elif _numeric_ogr(wanted) and not _numeric_ogr(current.GetType()):
                    warnings.append(f"{SCHEMA_CONFLICT}: campo '{name}' existente e texto; valores gravados como texto.")
            transform = None
            table_srs = target.GetSpatialRef()
            if table_srs is not None:
                from qgis.core import QgsCoordinateReferenceSystem

                table_crs = QgsCoordinateReferenceSystem.fromWkt(table_srs.ExportToWkt())
                if table_crs.isValid() and table_crs != layer.crs():
                    transform = QgsCoordinateTransform(layer.crs(), table_crs, self.project)
            geometry_type = target.GetGeomType()
            audit = None
            if geometry_type not in (ogr.wkbUnknown, ogr.wkbNone):
                audit = _geometry_audit(table, geometry_type)
            names = layer.fields().names()
            try:
                started = source.StartTransaction()
            except RuntimeError:
                started = 1
            if started != 0:
                raise PersistenceError(GPKG_WRITE_FAILED, failed)
            try:
                target.ResetReading()
                for fid in [feature.GetFID() for feature in target]:
                    if target.DeleteFeature(fid) != 0:
                        raise RuntimeError("delete")
                layer_definition = target.GetLayerDefn()
                for feature in layer.getFeatures():
                    output = ogr.Feature(layer_definition)
                    for name, value in zip(names, feature.attributes()):
                        index = output.GetFieldIndex(name)
                        if index < 0 or name.casefold() == fid_column:
                            continue
                        value = _python_value(value)
                        if value is None:
                            output.SetFieldNull(index)
                        else:
                            output.SetField(index, value)
                    geometry = feature.geometry()
                    if geometry is not None and not geometry.isNull():
                        if transform is not None:
                            geometry.transform(transform)
                        ogr_geometry = ogr.CreateGeometryFromWkb(bytes(geometry.asWkb()))
                        if geometry_type not in (ogr.wkbUnknown, ogr.wkbNone):
                            if audit is not None:
                                try:
                                    _observe_ogr_geometry(audit, ogr_geometry, geometry_type, feature.id())
                                except Exception as exc:
                                    audit = None
                                    warnings.append(f"GEOMETRY_CHECK_FAILED: diagnostico interrompido em '{table}' ({exc}).")
                            ogr_geometry = ogr.ForceTo(ogr_geometry, geometry_type)
                        output.SetGeometry(ogr_geometry)
                    if target.CreateFeature(output) != 0:
                        raise RuntimeError("insert")
                if source.CommitTransaction() != 0:
                    raise RuntimeError("commit")
                if audit is not None:
                    warnings.extend(audit.warnings())
            except Exception as exc:
                try:
                    source.RollbackTransaction()
                except RuntimeError:
                    pass
                raise PersistenceError(GPKG_WRITE_FAILED, failed) from exc
        finally:
            target = None
            source = None
        return warnings

    def diagnose_geometry_write(
        self, source: QgsVectorLayer, definition: LayerRoleDefinition, field_name: str | None
    ) -> list[str]:
        """Somente leitura: avisos que a substituicao da tabela do role geraria hoje.

        Nada e gravado; sem tabela existente (primeira gravacao) nao ha conversao.
        """
        from osgeo import ogr

        path = self.get_field_storage_path(field_name)
        source_gpkg = _open(path)
        if source_gpkg is None:
            return []
        target = source_gpkg.GetLayerByName(definition.display_name)
        geometry_type = target.GetGeomType() if target is not None else ogr.wkbNone
        target = None
        source_gpkg = None
        if geometry_type in (ogr.wkbUnknown, ogr.wkbNone):
            return []
        audit = GeometryWriteAudit(definition.display_name, ogr.GT_Flatten(geometry_type))
        for feature in source.getFeatures():
            geometry = feature.geometry()
            if geometry is None or geometry.isNull():
                continue
            ogr_geometry = ogr.CreateGeometryFromWkb(bytes(geometry.asWkb()))
            if ogr_geometry is not None:
                _observe_ogr_geometry(audit, ogr_geometry, geometry_type, feature.id())
        return audit.warnings()

    @staticmethod
    def remove_table(path: Path, table: str) -> bool:
        source = _open(path, update=True)
        if source is None:
            return False
        removed = False
        try:
            for index in range(source.GetLayerCount()):
                if source.GetLayerByIndex(index).GetName() == table:
                    removed = source.DeleteLayer(index) == 0
                    break
        except RuntimeError:
            removed = False
        source = None
        return removed

    def remove_role_layer(self, field_name: str | None, definition: LayerRoleDefinition) -> bool:
        """Apaga a tabela do role no talhao e tira do projeto as camadas que a usam."""
        path = self.get_field_storage_path(field_name)
        layers = self._project_layers_for_table(path, definition.display_name)
        if layers:
            self.project.removeMapLayers([layer.id() for layer in layers])
        return self.remove_table(path, definition.display_name)

    @staticmethod
    def archived_versions(path: Path, table: str) -> list[int]:
        pattern = re.compile(rf"^{re.escape(table)}_v(\d+)$")
        return sorted(int(match.group(1)) for match in map(pattern.match, FortSmartPersistenceManager.table_names(path)) if match)

    def archive_role_table(self, field_name: str | None, definition: LayerRoleDefinition) -> str | None:
        """Copia a tabela do role para '{tabela}_v{n}' no mesmo GPKG; a ativa nao muda.

        A copia nao e carregada no projeto (so uma camada definitiva por role).
        None quando ainda nao existe tabela para arquivar.
        """
        path = self.get_field_storage_path(field_name)
        table = definition.display_name
        if self.table_feature_count(path, table) is None:
            return None
        archived = f"{table}_v{max(self.archived_versions(path, table), default=0) + 1}"
        failed = MESSAGES[GPKG_WRITE_FAILED].format(name=archived)
        source = _open(path, update=True)
        if source is None:
            raise PersistenceError(GPKG_WRITE_FAILED, failed)
        copied = None
        try:
            copied = source.CopyLayer(source.GetLayerByName(table), archived)
            ok = copied is not None
        except RuntimeError:
            ok = False
        finally:
            copied = None
            source = None
        if not ok or self.table_feature_count(path, archived) != self.table_feature_count(path, table):
            self.remove_table(path, archived)
            raise PersistenceError(GPKG_WRITE_FAILED, failed)
        return archived

    @staticmethod
    def ensure_spatial_index(path: Path, table: str) -> bool:
        source = _open(path, update=True)
        if source is None:
            return False
        try:
            layer = source.GetLayerByName(table)
            column = layer.GetGeometryColumn() if layer is not None else ""
            if not column:
                return False
            quoted_table = table.replace("'", "''")
            result = source.ExecuteSQL(f"SELECT HasSpatialIndex('{quoted_table}', '{column}')")
            has_index = bool(result.GetNextFeature().GetField(0)) if result is not None else False
            if result is not None:
                source.ReleaseResultSet(result)
            if not has_index:
                created = source.ExecuteSQL(f"SELECT CreateSpatialIndex('{quoted_table}', '{column}')")
                if created is not None:
                    source.ReleaseResultSet(created)
            return True
        except RuntimeError:
            return False
        finally:
            source = None
