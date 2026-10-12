# -*- coding: utf-8 -*-
"""Prontidao canonica para exportacao, sem alterar camadas ou geometrias."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsProject,
    QgsVectorLayer,
)

from plugin.fortsmart_precision.core.export_readiness_validator import (
    CANONICAL_NOT_READY,
    CANONICAL_READY,
    CANONICAL_READY_WITH_WARNINGS,
    CanonicalExportReadinessValidator,
    available_export_field_ids,
    resolve_export_field_id,
    validate_field_for_export,
)
from plugin.fortsmart_precision.core.layer_roles import (
    GENERATED_PROPERTY,
    INTERNAL_KEY_PROPERTY,
    ROLE_PROPERTY,
    SCHEMA_PROPERTY,
    SECTION_KEY_PROPERTY,
    set_layer_role_properties,
    definition_for_role,
)
from plugin.fortsmart_precision.gui.export_readiness_dialog import ExportReadinessDialog


_APP = None
CRS = "EPSG:31981"


def _setup_qgis():
    global _APP
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if QgsApplication.instance() is None:
        _APP = QgsApplication([], True)
        _APP.initQgis()


def _layer(
    name,
    geometry_type,
    role,
    field_id="TL-12",
    wkts=(),
    fields=(),
    attributes=(),
    *,
    generated=True,
    add=True,
):
    layer = QgsVectorLayer(f"{geometry_type}?crs={CRS}", name, "memory")
    identity_fields = (
        ("fortsmart_role", QVariant.String),
        ("field_id", QVariant.String),
        ("source_id", QVariant.String),
    ) if generated else ()
    requested_fields = []
    seen = set()
    for field_spec in (*identity_fields, *fields):
        if field_spec[0] not in seen:
            requested_fields.append(field_spec)
            seen.add(field_spec[0])
    if requested_fields:
        layer.dataProvider().addAttributes(
            [QgsField(field_name, field_type) for field_name, field_type in requested_fields]
        )
        layer.updateFields()
    for index, wkt in enumerate(wkts):
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt(wkt))
        if generated:
            feature["fortsmart_role"] = role
            feature["field_id"] = field_id
            feature["source_id"] = f"{role}:{index + 1}"
        if attributes:
            row = attributes[index] if index < len(attributes) else {}
            for key, value in row.items():
                feature[key] = value
        layer.dataProvider().addFeature(feature)
    definition = definition_for_role(role)
    if definition is not None:
        set_layer_role_properties(layer, definition, field_name=field_id, generated=generated)
    else:
        layer.setCustomProperty(ROLE_PROPERTY, role)
        layer.setCustomProperty(SECTION_KEY_PROPERTY, "10_PLANEJAMENTO")
        layer.setCustomProperty(INTERNAL_KEY_PROPERTY, role)
        layer.setCustomProperty("fortsmart_field_id", field_id)
        layer.setCustomProperty(SCHEMA_PROPERTY, 1)
        layer.setCustomProperty(GENERATED_PROPERTY, generated)
    if add:
        QgsProject.instance().addMapLayer(layer)
    return layer


def _valid_boundary(field_id="TL-12"):
    return _layer(
        "01_Limite_Externo",
        "Polygon",
        "EXTERNAL_BOUNDARY",
        field_id,
        ("POLYGON((0 0,100 0,100 100,0 100,0 0))",),
    )


def _valid_ab(field_id="TL-12", points=2):
    coordinates = ",".join(f"{index * 2} 50" for index in range(points))
    return _layer("04_Linha_AB", "LineString", "AB_LINE", field_id, (f"LINESTRING({coordinates})",))


def _valid_work(field_id="TL-12", line_id="L0001"):
    return _layer(
        "12_Passadas_Plantio",
        "LineString",
        "WORK_PATH",
        field_id,
        ("LINESTRING(0 40,100 40)",),
        (("line_id", QVariant.String), ("pass_number", QVariant.Int)),
        ({"line_id": line_id, "pass_number": 1},),
    )


class _Iface:
    def __init__(self, active=None):
        self.active = active
        self.menu_actions = []

    @staticmethod
    def mainWindow():
        return None

    def activeLayer(self):
        return self.active

    def addPluginToMenu(self, menu, action):
        self.menu_actions.append((menu, action))

    def removePluginMenu(self, menu, action):
        self.menu_actions = [item for item in self.menu_actions if item != (menu, action)]

    @staticmethod
    def addToolBarIcon(_action):
        pass

    @staticmethod
    def removeToolBarIcon(_action):
        pass


class ExportReadinessValidatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()

    def setUp(self):
        QgsProject.instance().clear()

    def tearDown(self):
        QgsProject.instance().clear()

    def test_01_valid_field_is_canonical_ready(self):
        _valid_boundary()
        _valid_ab()
        _valid_work()

        report = validate_field_for_export("TL-12")

        self.assertEqual(report.status, CANONICAL_READY)
        self.assertAlmostEqual(report.area_ha, 1.0)
        self.assertEqual(report.crs, CRS)
        self.assertEqual(report.errors, ())
        self.assertEqual(report.warnings, ())

    def test_02_empty_boundary_is_error(self):
        _layer("01_Limite_Externo", "Polygon", "EXTERNAL_BOUNDARY", wkts=())
        _valid_ab()

        report = validate_field_for_export("TL-12")

        self.assertEqual(report.status, CANONICAL_NOT_READY)
        self.assertIn("EMPTY_ROLE_LAYER", {issue.code for issue in report.errors})

    def test_03_boundary_with_461k_vertices_reports_critical_complexity(self):
        _valid_boundary()
        _valid_ab()
        with patch(
            "plugin.fortsmart_precision.core.export_readiness_validator._geometry_vertex_count",
            return_value=461_569,
        ):
            report = validate_field_for_export("TL-12")

        self.assertEqual(report.status, CANONICAL_READY_WITH_WARNINGS)
        issue = next(item for item in report.warnings if item.code == "BOUNDARY_COMPLEXITY_CRITICAL")
        self.assertEqual(issue.details["vertex_count"], 461_569)

    def test_04_headland_linestring_is_role_geometry_mismatch(self):
        _valid_boundary()
        _valid_ab()
        _layer("03_Bordadura", "LineString", "HEADLAND", wkts=("LINESTRING(0 0,10 0)",))

        report = validate_field_for_export("TL-12")

        self.assertIn("ROLE_GEOMETRY_MISMATCH", {issue.code for issue in report.errors})

    def test_05_renamed_work_path_is_resolved_by_role(self):
        _valid_boundary()
        _valid_ab()
        _valid_work().setName("Minha operacao safra 2027")

        report = validate_field_for_export("TL-12")

        self.assertEqual(report.objects_detected["WORK_PATH"], 1)
        self.assertNotIn("LEGACY_CLASSIFICATION", {issue.code for issue in report.warnings})

    def test_06_legacy_work_path_is_reported_without_mutation(self):
        _valid_boundary()
        _valid_ab()
        legacy = QgsVectorLayer("LineString?crs=EPSG:31981", "06_Passadas_Plantio", "memory")
        feature = QgsFeature()
        feature.setGeometry(QgsGeometry.fromWkt("LINESTRING(0 40,100 40)"))
        legacy.dataProvider().addFeature(feature)
        QgsProject.instance().addMapLayer(legacy, False)
        group = QgsProject.instance().layerTreeRoot().addGroup("FORTSMART - TL-12")
        group.addLayer(legacy)
        before = feature.geometry().asWkt()

        report = validate_field_for_export("TL-12")

        codes = {issue.code for issue in report.warnings}
        self.assertIn("LEGACY_CLASSIFICATION", codes)
        self.assertIn("FIELD_ID_MISSING", codes)
        self.assertEqual(legacy.customProperty(ROLE_PROPERTY, ""), "")
        self.assertEqual(next(legacy.getFeatures()).geometry().asWkt(), before)

    def test_07_validation_is_isolated_by_field_id(self):
        _valid_boundary("TL-12")
        _valid_ab("TL-12")
        _valid_work("TL-12")
        _valid_boundary("TL-13")
        _valid_ab("TL-13")
        _valid_work("TL-13")

        report = validate_field_for_export("TL-12")

        self.assertEqual(report.objects_detected["EXTERNAL_BOUNDARY"], 1)
        self.assertEqual(report.objects_detected["WORK_PATH"], 1)
        self.assertEqual(available_export_field_ids(), ("TL-12", "TL-13"))

    def test_08_orphan_work_event_is_warning(self):
        _valid_boundary()
        _valid_ab()
        _valid_work(line_id="L0001")
        _layer(
            "32_Work_Off",
            "Point",
            "WORK_OFF",
            wkts=("POINT(50 40)",),
            fields=(("line_id", QVariant.String),),
            attributes=({"line_id": "L9999"},),
        )

        report = validate_field_for_export("TL-12")

        self.assertIn("WORK_EVENT_ORPHAN", {issue.code for issue in report.warnings})

    def test_09_densified_ab_line_remains_ab_line(self):
        _valid_boundary()
        ab = _valid_ab(points=50)

        report = validate_field_for_export("TL-12")

        self.assertEqual(ab.customProperty(ROLE_PROPERTY), "AB_LINE")
        self.assertEqual(report.objects_detected["AB_LINE"], 1)
        self.assertNotIn("ROLE_GEOMETRY_MISMATCH", {issue.code for issue in report.errors})

    def test_10_self_intersecting_boundary_is_error(self):
        _layer(
            "01_Limite_Externo",
            "Polygon",
            "EXTERNAL_BOUNDARY",
            wkts=("POLYGON((0 0,100 100,0 100,100 0,0 0))",),
        )
        _valid_ab()

        report = CanonicalExportReadinessValidator().validate("TL-12")

        self.assertEqual(report.status, CANONICAL_NOT_READY)
        self.assertIn("SELF_INTERSECTION", {issue.code for issue in report.errors})

    def test_active_layer_resolves_field_id_without_using_visual_name(self):
        work = _valid_work(field_id="TL-12")
        work.setName("Nome totalmente livre")
        self.assertEqual(resolve_export_field_id(work), "TL-12")

    def test_geographic_crs_is_blocked_for_metric_validation(self):
        boundary = _valid_boundary()
        boundary.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        _valid_ab()

        report = validate_field_for_export("TL-12")

        self.assertIn("CRS_NOT_PROJECTED_METERS", {issue.code for issue in report.errors})

    def test_dialog_prefers_active_field_and_renders_report(self):
        _valid_boundary("TL-12")
        _valid_ab("TL-12")
        active = _valid_work("TL-12")
        _valid_boundary("TL-13")
        _valid_ab("TL-13")
        dialog = ExportReadinessDialog(_Iface(active))

        self.assertEqual(dialog.selected_field_id(), "TL-12")
        dialog.validate_selected()
        self.assertIsNotNone(dialog.last_report)
        self.assertEqual(dialog.last_report.status, CANONICAL_READY)
        self.assertGreater(dialog.role_table.rowCount(), 0)
        self.assertIn("field_area_ha", dialog.technical_log.toPlainText())
        dialog.close()

    def test_plugin_registers_export_readiness_action(self):
        from plugin.fortsmart_precision.plugin import FortSmartPrecisionPlugin

        iface = _Iface()
        plugin = FortSmartPrecisionPlugin(iface)
        plugin.initGui()
        try:
            labels = [action.text() for _menu, action in iface.menu_actions]
            self.assertIn("Validar projeto para exportacao", labels)
            self.assertIsNotNone(plugin.action_export_readiness)
        finally:
            plugin.unload()

    def test_feature_field_id_mismatch_is_error(self):
        boundary = _valid_boundary()
        feature = next(boundary.getFeatures())
        field_index = boundary.fields().indexFromName("field_id")
        boundary.dataProvider().changeAttributeValues(
            {feature.id(): {field_index: "TL-13"}}
        )
        _valid_ab()

        report = validate_field_for_export("TL-12")

        self.assertIn("FEATURE_FIELD_ID_MISMATCH", {issue.code for issue in report.errors})

    def test_area_metadata_mismatch_is_warning(self):
        boundary = _valid_boundary()
        boundary.setCustomProperty("field_area_m2", 50_000.0)
        _valid_ab()

        report = validate_field_for_export("TL-12")

        self.assertIn("AREA_METADATA_MISMATCH", {issue.code for issue in report.warnings})

    def test_obstacle_outside_field_is_warning_and_is_not_removed(self):
        _valid_boundary()
        _valid_ab()
        obstacle = _layer(
            "21_Obstaculos_RTK",
            "Point",
            "OBSTACLE",
            wkts=("POINT(500 500)",),
        )

        report = validate_field_for_export("TL-12")

        self.assertIn("OBSTACLE_OUTSIDE_FIELD", {issue.code for issue in report.warnings})
        self.assertEqual(obstacle.featureCount(), 1)


if __name__ == "__main__":
    unittest.main()
