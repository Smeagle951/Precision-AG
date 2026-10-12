# -*- coding: utf-8 -*-
"""Validacao canonica, somente leitura, antes da exportacao especializada."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from typing import Iterable

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsUnitTypes,
    QgsWkbTypes,
)

from .layer_roles import (
    FIELD_ID_PROPERTY,
    GENERATED_PROPERTY,
    INTERNAL_KEY_PROPERTY,
    PROJECT_GROUP_PREFIX,
    ROLE_PROPERTY,
    SCHEMA_PROPERTY,
    SECTION_KEY_PROPERTY,
    SOURCE_DISPLAY_NAME,
    SOURCE_HEURISTIC,
    SOURCE_INTERNAL_KEY,
    SOURCE_LEGACY_ALIAS,
    canonical_field_name,
    classify_layer,
    is_generated_layer,
    is_temporary_preview,
    layer_field_id,
)


CANONICAL_READY = "CANONICAL_READY"
CANONICAL_READY_WITH_WARNINGS = "CANONICAL_READY_WITH_WARNINGS"
CANONICAL_NOT_READY = "CANONICAL_NOT_READY"

SEVERITY_ERROR = "ERROR"
SEVERITY_WARNING = "WARNING"
SEVERITY_INFO = "INFO"

VALIDATED_ROLES = (
    "EXTERNAL_BOUNDARY",
    "INTERNAL_BOUNDARY",
    "HEADLAND",
    "AB_LINE",
    "AB_CURVE",
    "ADAPTIVE_CURVE",
    "BORDER_PASS",
    "FIELD_HEADLAND_PATH",
    "HEADLAND_WORK_PATH",
    "WORK_PATH",
    "FINAL_WORK_PATH",
    "OBSTACLE",
    "WORK_OFF",
    "WORK_ON",
    "SHUTOFF",
    "HEADLAND_TURN",
)

_POLYGON_ROLES = {"EXTERNAL_BOUNDARY", "INTERNAL_BOUNDARY", "HEADLAND"}
_LINE_ROLES = {
    "AB_LINE",
    "AB_CURVE",
    "ADAPTIVE_CURVE",
    "BORDER_PASS",
    "FIELD_HEADLAND_PATH",
    "HEADLAND_WORK_PATH",
    "WORK_PATH",
    "FINAL_WORK_PATH",
    "SHUTOFF",
    "HEADLAND_TURN",
}
_EVENT_ROLES = {"WORK_OFF", "WORK_ON"}
_UNIQUE_ROLES = {
    "EXTERNAL_BOUNDARY",
    "INTERNAL_BOUNDARY",
    "HEADLAND",
    "AB_LINE",
    "AB_CURVE",
    "ADAPTIVE_CURVE",
}
_LEGACY_SOURCES = {
    SOURCE_INTERNAL_KEY,
    SOURCE_LEGACY_ALIAS,
    SOURCE_DISPLAY_NAME,
    SOURCE_HEURISTIC,
}
_REQUIRED_LAYER_PROPERTIES = (
    GENERATED_PROPERTY,
    ROLE_PROPERTY,
    SECTION_KEY_PROPERTY,
    INTERNAL_KEY_PROPERTY,
    FIELD_ID_PROPERTY,
    SCHEMA_PROPERTY,
)


@dataclass(frozen=True)
class ExportReadinessThresholds:
    boundary_warning_vertex_count: int = 10_000
    boundary_critical_vertex_count: int = 100_000
    area_metadata_tolerance_ratio: float = 0.02

    def validate(self) -> None:
        if self.boundary_warning_vertex_count <= 0:
            raise ValueError("Limite de alerta de vertices deve ser positivo.")
        if self.boundary_critical_vertex_count <= self.boundary_warning_vertex_count:
            raise ValueError("Limite critico deve ser maior que o limite de alerta.")
        if not 0 <= self.area_metadata_tolerance_ratio < 1:
            raise ValueError("Tolerancia de area deve estar entre 0 e 1.")


@dataclass(frozen=True)
class ExportReadinessIssue:
    severity: str
    code: str
    message: str
    role: str = ""
    layer_name: str = ""
    feature_id: str = ""
    details: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "role": self.role,
            "layer_name": self.layer_name,
            "feature_id": self.feature_id,
            "details": self.details,
        }


@dataclass(frozen=True)
class RoleReadiness:
    role: str
    layer_count: int
    feature_count: int
    geometry_types: tuple[str, ...]
    status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "layer_count": self.layer_count,
            "feature_count": self.feature_count,
            "geometry_types": list(self.geometry_types),
            "status": self.status,
        }


@dataclass(frozen=True)
class ExportReadinessReport:
    field_id: str
    field_name: str
    area_m2: float
    area_ha: float
    crs: str
    objects_detected: dict[str, int]
    role_report: tuple[RoleReadiness, ...]
    issues: tuple[ExportReadinessIssue, ...]
    status: str

    @property
    def errors(self) -> tuple[ExportReadinessIssue, ...]:
        return tuple(item for item in self.issues if item.severity == SEVERITY_ERROR)

    @property
    def warnings(self) -> tuple[ExportReadinessIssue, ...]:
        return tuple(item for item in self.issues if item.severity == SEVERITY_WARNING)

    @property
    def info(self) -> tuple[ExportReadinessIssue, ...]:
        return tuple(item for item in self.issues if item.severity == SEVERITY_INFO)

    def to_dict(self) -> dict[str, object]:
        return {
            "field_id": self.field_id,
            "field_name": self.field_name,
            "field_area_m2": round(self.area_m2, 6),
            "field_area_ha": round(self.area_ha, 6),
            "crs": self.crs,
            "objects_detected": self.objects_detected,
            "role_report": [item.to_dict() for item in self.role_report],
            "errors": [item.to_dict() for item in self.errors],
            "warnings": [item.to_dict() for item in self.warnings],
            "info": [item.to_dict() for item in self.info],
            "status": self.status,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False, sort_keys=True)

    def to_text(self) -> str:
        lines = [
            "FORTSMART EXPORT READINESS REPORT",
            "",
            f"Talhao: {self.field_name} ({self.field_id})",
            f"Area: {self.area_ha:.2f} ha",
            f"CRS: {self.crs or 'nao identificado'}",
            "",
            "OBJETOS",
        ]
        for item in self.role_report:
            geometry = "/".join(item.geometry_types) or "-"
            lines.append(
                f"{item.role}: {item.feature_count} feicao(oes), "
                f"{item.layer_count} camada(s), {geometry}, {item.status}"
            )
        for title, entries in (("ERROS", self.errors), ("AVISOS", self.warnings), ("INFO", self.info)):
            if entries:
                lines.extend(("", title))
                lines.extend(f"{item.code}: {item.message}" for item in entries)
        lines.extend(("", f"STATUS: {self.status}"))
        return "\n".join(lines)


def _custom_property(layer, key: str, default=None):
    try:
        return layer.customProperty(key, default)
    except Exception:
        return default


def _layer_name(layer) -> str:
    try:
        return str(layer.name())
    except Exception:
        return ""


def _feature_count(layer) -> int:
    try:
        return int(layer.featureCount())
    except Exception:
        return -1


def _geometry_type_name(layer) -> str:
    try:
        kind = QgsWkbTypes.geometryType(layer.wkbType())
    except Exception:
        return "Unknown"
    return {
        QgsWkbTypes.PointGeometry: "Point",
        QgsWkbTypes.LineGeometry: "LineString",
        QgsWkbTypes.PolygonGeometry: "Polygon",
    }.get(kind, "Unknown")


def _field_group_id(project, layer) -> str:
    try:
        node = project.layerTreeRoot().findLayer(layer.id())
    except Exception:
        return ""
    parent = node.parent() if node is not None else None
    while parent is not None:
        try:
            name = str(parent.name())
        except Exception:
            name = ""
        if name.upper().startswith(PROJECT_GROUP_PREFIX.upper()):
            return canonical_field_name(name)
        parent = parent.parent()
    return ""


def available_export_field_ids(project=None) -> tuple[str, ...]:
    """Talhoes identificados por metadata ou por grupo canonico."""
    project = project or QgsProject.instance()
    found: set[str] = set()
    for layer in project.mapLayers().values():
        owner = layer_field_id(layer) or _field_group_id(project, layer)
        if owner:
            found.add(canonical_field_name(owner))
    try:
        groups = project.layerTreeRoot().findGroups()
    except Exception:
        groups = ()
    for group in groups:
        name = str(group.name())
        if name.upper().startswith(PROJECT_GROUP_PREFIX.upper()):
            found.add(canonical_field_name(name))
    return tuple(sorted(found, key=str.casefold))


def resolve_export_field_id(layer, project=None) -> str:
    """Resolve pelo metadado e, como fallback, pelo grupo canonico."""
    if layer is None:
        return ""
    project = project or QgsProject.instance()
    return canonical_field_name(layer_field_id(layer) or _field_group_id(project, layer)) \
        if (layer_field_id(layer) or _field_group_id(project, layer)) else ""


def _layer_belongs_to_field(layer, field_id: str, project) -> bool:
    owner = layer_field_id(layer)
    if owner:
        return canonical_field_name(owner) == field_id
    return _field_group_id(project, layer) == field_id


def _is_metric_projected(layer) -> bool:
    try:
        crs = layer.crs()
        return crs.isValid() and not crs.isGeographic() and crs.mapUnits() == QgsUnitTypes.DistanceMeters
    except Exception:
        return False


def _transform_to_geographic_is_valid(layer, project) -> bool:
    try:
        transform = QgsCoordinateTransform(
            layer.crs(), QgsCoordinateReferenceSystem("EPSG:4326"), project.transformContext()
        )
        return transform.isValid()
    except Exception:
        return False


def _geometry_vertex_count(geometry) -> int:
    try:
        const_geometry = geometry.constGet()
        return int(const_geometry.nCoordinates()) if const_geometry is not None else 0
    except Exception:
        return sum(1 for _point in geometry.vertices())


def _geometry_coordinate_sanity(geometry) -> tuple[bool, bool]:
    """Retorna (coordenada_nao_finita, duplicata_consecutiva) em uma passagem."""
    previous = None
    non_finite = False
    duplicate = False
    try:
        for point in geometry.vertices():
            current = (point.x(), point.y())
            if not math.isfinite(current[0]) or not math.isfinite(current[1]):
                non_finite = True
            if current == previous:
                duplicate = True
            previous = current
    except Exception:
        return True, duplicate
    return non_finite, duplicate


def _feature_value(feature, names: Iterable[str]):
    fields = feature.fields().names()
    folded = {name.casefold(): name for name in fields}
    for candidate in names:
        actual = folded.get(candidate.casefold())
        if actual is None:
            continue
        value = feature[actual]
        if value is not None and str(value).strip() not in ("", "NULL"):
            return value
    return None


class CanonicalExportReadinessValidator:
    """Valida semantica e geometria sem modificar o projeto QGIS."""

    def __init__(self, thresholds: ExportReadinessThresholds | None = None):
        self.thresholds = thresholds or ExportReadinessThresholds()
        self.thresholds.validate()

    def validate(self, field_id: str, project=None) -> ExportReadinessReport:
        project = project or QgsProject.instance()
        target = canonical_field_name(field_id) if str(field_id or "").strip() else ""
        if not target:
            issue = ExportReadinessIssue(
                SEVERITY_ERROR, "FIELD_ID_MISSING", "Nao foi possivel determinar o talhao."
            )
            return ExportReadinessReport(
                "", "", 0.0, 0.0, "", {}, (), (issue,), CANONICAL_NOT_READY
            )

        layers = []
        classifications: dict[str, tuple[str, str]] = {}
        for layer in project.mapLayers().values():
            if is_temporary_preview(layer) or not _layer_belongs_to_field(layer, target, project):
                continue
            role, source = classify_layer(layer)
            if role in VALIDATED_ROLES:
                layers.append(layer)
                classifications[layer.id()] = (role, source)

        issues: list[ExportReadinessIssue] = []
        by_role: dict[str, list] = {}
        for layer in layers:
            role, source = classifications[layer.id()]
            by_role.setdefault(role, []).append(layer)
            self._validate_layer_identity(layer, role, source, target, issues)

        boundaries = by_role.get("EXTERNAL_BOUNDARY", [])
        if not boundaries:
            issues.append(ExportReadinessIssue(
                SEVERITY_ERROR,
                "EXTERNAL_BOUNDARY_MISSING",
                "Limite externo canonico nao encontrado para o talhao.",
                role="EXTERNAL_BOUNDARY",
            ))

        for role in _UNIQUE_ROLES:
            count = len(by_role.get(role, ()))
            if count > 1:
                severity = SEVERITY_ERROR if role == "EXTERNAL_BOUNDARY" else SEVERITY_WARNING
                issues.append(ExportReadinessIssue(
                    severity,
                    "DUPLICATE_ROLE",
                    f"Role {role} possui {count} camadas no mesmo talhao.",
                    role=role,
                    details={"layer_count": count},
                ))

        area_m2 = 0.0
        crs_authid = ""
        boundary_geometries = []
        valid_line_ids: set[str] = set()
        pending_events: list[tuple[object, str, str]] = []
        for role, role_layers in by_role.items():
            for layer in role_layers:
                if not crs_authid:
                    try:
                        crs_authid = layer.crs().authid()
                    except Exception:
                        pass
                feature_count = _feature_count(layer)
                if feature_count == 0:
                    issues.append(ExportReadinessIssue(
                        SEVERITY_ERROR if role == "EXTERNAL_BOUNDARY" else SEVERITY_WARNING,
                        "EMPTY_ROLE_LAYER",
                        f"Camada {_layer_name(layer)} existe, mas nao possui feicoes.",
                        role=role,
                        layer_name=_layer_name(layer),
                    ))
                    continue
                self._validate_layer_crs(layer, role, project, issues)
                expected = self._expected_geometry_types(role)
                actual = _geometry_type_name(layer)
                if expected and actual not in expected:
                    issues.append(ExportReadinessIssue(
                        SEVERITY_ERROR,
                        "ROLE_GEOMETRY_MISMATCH",
                        f"Role {role} exige {'/'.join(sorted(expected))}, mas a camada e {actual}.",
                        role=role,
                        layer_name=_layer_name(layer),
                        details={"expected": sorted(expected), "actual": actual},
                    ))
                self._validate_feature_schema(layer, role, issues)
                for feature in layer.getFeatures():
                    geometry = feature.geometry()
                    feature_id = str(feature.id())
                    if geometry is None or geometry.isNull() or geometry.isEmpty():
                        issues.append(ExportReadinessIssue(
                            SEVERITY_ERROR,
                            "EMPTY_GEOMETRY",
                            "Feicao possui geometria nula ou vazia.",
                            role=role,
                            layer_name=_layer_name(layer),
                            feature_id=feature_id,
                        ))
                        continue
                    vertex_count = _geometry_vertex_count(geometry)
                    if role == "EXTERNAL_BOUNDARY":
                        self._validate_boundary_complexity(
                            vertex_count, role, _layer_name(layer), feature_id, issues
                        )
                    non_finite, duplicate = _geometry_coordinate_sanity(geometry)
                    if non_finite:
                        issues.append(ExportReadinessIssue(
                            SEVERITY_ERROR,
                            "NON_FINITE_COORDINATE",
                            "Geometria possui coordenada NaN ou infinita.",
                            role=role,
                            layer_name=_layer_name(layer),
                            feature_id=feature_id,
                        ))
                    if duplicate:
                        issues.append(ExportReadinessIssue(
                            SEVERITY_WARNING,
                            "DUPLICATE_CONSECUTIVE_POINT",
                            "Geometria possui vertices consecutivos duplicados.",
                            role=role,
                            layer_name=_layer_name(layer),
                            feature_id=feature_id,
                        ))
                    self._validate_feature_semantics(
                        feature, role, target, _layer_name(layer), issues
                    )
                    self._validate_topology(
                        geometry, role, _layer_name(layer), feature_id, issues
                    )
                    if role == "EXTERNAL_BOUNDARY" and actual == "Polygon":
                        boundary_geometries.append(geometry)
                        if _is_metric_projected(layer):
                            area_m2 += max(0.0, float(geometry.area()))
                    if role in {"WORK_PATH", "FINAL_WORK_PATH"}:
                        line_id = _feature_value(feature, ("line_id", "parent_line_id"))
                        if line_id is not None:
                            valid_line_ids.add(str(line_id))
                        self._validate_work_identity(feature, role, _layer_name(layer), issues)
                    if role in _EVENT_ROLES:
                        pending_events.append((feature, role, _layer_name(layer)))

        for feature, role, layer_name in pending_events:
            self._validate_event_identity(
                feature, role, layer_name, valid_line_ids, issues
            )

        if boundaries and area_m2 <= 0 and all(_is_metric_projected(layer) for layer in boundaries):
            issues.append(ExportReadinessIssue(
                SEVERITY_ERROR,
                "FIELD_AREA_INVALID",
                "Limite externo existe, mas a area geometrica e zero.",
                role="EXTERNAL_BOUNDARY",
            ))

        external = boundary_geometries[0] if boundary_geometries else None
        if external is not None:
            for geometry in boundary_geometries[1:]:
                external = external.combine(geometry)
            self._validate_spatial_associations(by_role, external, issues)
            self._validate_area_metadata(boundaries, area_m2, issues)

        if not any(by_role.get(role) for role in ("AB_LINE", "AB_CURVE", "ADAPTIVE_CURVE")):
            issues.append(ExportReadinessIssue(
                SEVERITY_WARNING,
                "GUIDANCE_REFERENCE_MISSING",
                "Nenhuma referencia AB_LINE, AB_CURVE ou ADAPTIVE_CURVE foi encontrada.",
            ))

        role_report = self._build_role_report(by_role, issues)
        status = CANONICAL_NOT_READY if any(i.severity == SEVERITY_ERROR for i in issues) else (
            CANONICAL_READY_WITH_WARNINGS
            if any(i.severity == SEVERITY_WARNING for i in issues)
            else CANONICAL_READY
        )
        objects = {item.role: item.feature_count for item in role_report}
        return ExportReadinessReport(
            field_id=target,
            field_name=target,
            area_m2=area_m2,
            area_ha=area_m2 / 10_000.0,
            crs=crs_authid,
            objects_detected=objects,
            role_report=role_report,
            issues=tuple(issues),
            status=status,
        )

    def _validate_layer_identity(self, layer, role, source, field_id, issues) -> None:
        name = _layer_name(layer)
        if source in _LEGACY_SOURCES:
            issues.append(ExportReadinessIssue(
                SEVERITY_WARNING,
                "LEGACY_CLASSIFICATION",
                f"Camada {name} foi reconhecida por {source}; normalize o projeto.",
                role=role,
                layer_name=name,
            ))
        if not layer_field_id(layer):
            issues.append(ExportReadinessIssue(
                SEVERITY_WARNING,
                "FIELD_ID_MISSING",
                f"Camada {name} nao possui fortsmart_field_id; o grupo canonico foi usado.",
                role=role,
                layer_name=name,
            ))
        elif canonical_field_name(layer_field_id(layer)) != field_id:
            issues.append(ExportReadinessIssue(
                SEVERITY_ERROR,
                "FIELD_ID_MISMATCH",
                f"Camada {name} pertence a outro talhao.",
                role=role,
                layer_name=name,
            ))
        if is_generated_layer(layer):
            missing = [key for key in _REQUIRED_LAYER_PROPERTIES if _custom_property(layer, key, None) in (None, "")]
            if missing:
                issues.append(ExportReadinessIssue(
                    SEVERITY_WARNING,
                    "CANONICAL_METADATA_MISSING",
                    f"Camada {name} nao possui todos os metadados canonicos.",
                    role=role,
                    layer_name=name,
                    details={"missing": missing},
                ))

    @staticmethod
    def _expected_geometry_types(role: str) -> set[str]:
        if role in _POLYGON_ROLES:
            return {"Polygon"}
        if role in _LINE_ROLES:
            return {"LineString"}
        if role in _EVENT_ROLES:
            return {"Point", "LineString"}
        if role == "OBSTACLE":
            return {"Point", "LineString", "Polygon"}
        return set()

    @staticmethod
    def _validate_feature_schema(layer, role, issues) -> None:
        if not is_generated_layer(layer):
            return
        try:
            names = set(layer.fields().names())
        except Exception:
            names = set()
        missing = [name for name in ("fortsmart_role", "field_id", "source_id") if name not in names]
        if missing:
            issues.append(ExportReadinessIssue(
                SEVERITY_WARNING,
                "FEATURE_IDENTITY_FIELDS_MISSING",
                f"Camada {_layer_name(layer)} nao possui todos os campos de identidade por feicao.",
                role,
                _layer_name(layer),
                details={"missing": missing},
            ))

    @staticmethod
    def _validate_feature_semantics(feature, role, field_id, layer_name, issues) -> None:
        feature_role = _feature_value(feature, ("fortsmart_role",))
        feature_field = _feature_value(feature, ("field_id",))
        if feature_role is not None and str(feature_role) != role:
            issues.append(ExportReadinessIssue(
                SEVERITY_ERROR,
                "FEATURE_ROLE_MISMATCH",
                f"Feicao declara role {feature_role}, mas a camada declara {role}.",
                role,
                layer_name,
                str(feature.id()),
            ))
        if feature_field is not None and canonical_field_name(str(feature_field)) != field_id:
            issues.append(ExportReadinessIssue(
                SEVERITY_ERROR,
                "FEATURE_FIELD_ID_MISMATCH",
                f"Feicao pertence ao talhao {feature_field}, nao a {field_id}.",
                role,
                layer_name,
                str(feature.id()),
            ))

    @staticmethod
    def _validate_layer_crs(layer, role, project, issues) -> None:
        name = _layer_name(layer)
        try:
            crs = layer.crs()
        except Exception:
            crs = None
        if crs is None or not crs.isValid():
            issues.append(ExportReadinessIssue(
                SEVERITY_ERROR, "CRS_UNKNOWN", f"Camada {name} possui CRS desconhecido.", role, name
            ))
            return
        if not _is_metric_projected(layer):
            issues.append(ExportReadinessIssue(
                SEVERITY_ERROR,
                "CRS_NOT_PROJECTED_METERS",
                f"Camada {name} deve usar CRS projetado em metros para validacao de area e distancia.",
                role,
                name,
            ))
        if not _transform_to_geographic_is_valid(layer, project):
            issues.append(ExportReadinessIssue(
                SEVERITY_ERROR,
                "CRS_TRANSFORM_UNAVAILABLE",
                f"Nao ha transformacao valida de {crs.authid()} para EPSG:4326.",
                role,
                name,
            ))

    def _validate_boundary_complexity(self, count, role, layer_name, feature_id, issues) -> None:
        if count > self.thresholds.boundary_critical_vertex_count:
            issues.append(ExportReadinessIssue(
                SEVERITY_WARNING,
                "BOUNDARY_COMPLEXITY_CRITICAL",
                f"Limite externo possui {count:,} vertices; excede o limite critico configurado.",
                role,
                layer_name,
                feature_id,
                {"vertex_count": count},
            ))
        elif count > self.thresholds.boundary_warning_vertex_count:
            issues.append(ExportReadinessIssue(
                SEVERITY_WARNING,
                "BOUNDARY_COMPLEXITY_WARNING",
                f"Limite externo possui {count:,} vertices.",
                role,
                layer_name,
                feature_id,
                {"vertex_count": count},
            ))

    @staticmethod
    def _validate_topology(geometry, role, layer_name, feature_id, issues) -> None:
        if role in _POLYGON_ROLES:
            try:
                valid = geometry.isGeosValid()
            except Exception:
                valid = False
            if not valid:
                issues.append(ExportReadinessIssue(
                    SEVERITY_ERROR,
                    "SELF_INTERSECTION",
                    "Poligono invalido ou auto-intersectante.",
                    role,
                    layer_name,
                    feature_id,
                ))
        elif role in _LINE_ROLES:
            try:
                simple = geometry.isSimple()
            except Exception:
                simple = True
            if not simple:
                issues.append(ExportReadinessIssue(
                    SEVERITY_WARNING,
                    "LINE_SELF_INTERSECTION",
                    "Linha possui auto-intersecao.",
                    role,
                    layer_name,
                    feature_id,
                ))

    @staticmethod
    def _validate_work_identity(feature, role, layer_name, issues) -> None:
        line_id = _feature_value(feature, ("line_id", "parent_line_id"))
        pass_number = _feature_value(feature, ("pass_number", "line_number", "line_no", "pass_no"))
        if line_id is None or pass_number is None:
            issues.append(ExportReadinessIssue(
                SEVERITY_WARNING,
                "LINE_IDENTITY_MISSING",
                "Trajetoria operacional sem line_id/parent_line_id ou pass_number.",
                role,
                layer_name,
                str(feature.id()),
            ))
        if role == "FINAL_WORK_PATH" and _feature_value(feature, ("parent_line_id",)) is None:
            issues.append(ExportReadinessIssue(
                SEVERITY_WARNING,
                "SEGMENT_IDENTITY_MISSING",
                "Segmento final nao possui parent_line_id.",
                role,
                layer_name,
                str(feature.id()),
            ))

    @staticmethod
    def _validate_event_identity(feature, role, layer_name, valid_line_ids, issues) -> None:
        line_id = _feature_value(feature, ("line_id", "parent_line_id", "pass_id"))
        if line_id is None:
            issues.append(ExportReadinessIssue(
                SEVERITY_WARNING,
                "WORK_EVENT_LINE_ID_MISSING",
                "Evento operacional nao possui line_id.",
                role,
                layer_name,
                str(feature.id()),
            ))
        elif str(line_id) not in valid_line_ids:
            issues.append(ExportReadinessIssue(
                SEVERITY_WARNING,
                "WORK_EVENT_ORPHAN",
                f"Evento referencia line_id inexistente: {line_id}.",
                role,
                layer_name,
                str(feature.id()),
            ))

    @staticmethod
    def _validate_spatial_associations(by_role, external, issues) -> None:
        for role in ("INTERNAL_BOUNDARY", "HEADLAND", "OBSTACLE"):
            for layer in by_role.get(role, ()):
                for feature in layer.getFeatures():
                    geometry = feature.geometry()
                    if geometry is None or geometry.isNull() or geometry.isEmpty():
                        continue
                    try:
                        associated = geometry.intersects(external)
                    except Exception:
                        associated = False
                    if not associated:
                        severity = SEVERITY_WARNING if role == "OBSTACLE" else SEVERITY_ERROR
                        code = "OBSTACLE_OUTSIDE_FIELD" if role == "OBSTACLE" else "FIELD_ASSOCIATION_MISMATCH"
                        issues.append(ExportReadinessIssue(
                            severity,
                            code,
                            f"Feicao {role} nao esta espacialmente associada ao limite externo.",
                            role,
                            _layer_name(layer),
                            str(feature.id()),
                        ))

    def _validate_area_metadata(self, boundaries, area_m2, issues) -> None:
        if area_m2 <= 0:
            return
        for layer in boundaries:
            stored = _custom_property(layer, "field_area_m2", None)
            if stored in (None, ""):
                stored_ha = _custom_property(layer, "field_area_ha", None)
                if stored_ha not in (None, ""):
                    try:
                        stored = float(stored_ha) * 10_000.0
                    except (TypeError, ValueError):
                        stored = None
            if stored in (None, ""):
                continue
            try:
                ratio = abs(float(stored) - area_m2) / area_m2
            except (TypeError, ValueError):
                ratio = 1.0
            if ratio > self.thresholds.area_metadata_tolerance_ratio:
                issues.append(ExportReadinessIssue(
                    SEVERITY_WARNING,
                    "AREA_METADATA_MISMATCH",
                    "Area armazenada diverge da area geometrica do limite externo.",
                    "EXTERNAL_BOUNDARY",
                    _layer_name(layer),
                    details={"geometric_area_m2": area_m2, "difference_ratio": ratio},
                ))

    @staticmethod
    def _build_role_report(by_role, issues) -> tuple[RoleReadiness, ...]:
        report = []
        for role in VALIDATED_ROLES:
            layers = by_role.get(role, ())
            if not layers:
                continue
            relevant = [item for item in issues if item.role == role]
            status = "ERROR" if any(i.severity == SEVERITY_ERROR for i in relevant) else (
                "WARNING" if any(i.severity == SEVERITY_WARNING for i in relevant) else "OK"
            )
            report.append(RoleReadiness(
                role=role,
                layer_count=len(layers),
                feature_count=sum(max(0, _feature_count(layer)) for layer in layers),
                geometry_types=tuple(sorted({_geometry_type_name(layer) for layer in layers})),
                status=status,
            ))
        return tuple(report)


def validate_field_for_export(
    field_id: str,
    *,
    project=None,
    thresholds: ExportReadinessThresholds | None = None,
) -> ExportReadinessReport:
    """API estavel para consumidores externos; nao conhece formatos de monitor."""
    return CanonicalExportReadinessValidator(thresholds).validate(field_id, project=project)
