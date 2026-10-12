# -*- coding: utf-8 -*-
"""Desvio manual de obstaculo no QGIS: preview sem efeito, aplicar/undo/restaurar, exportar."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
)
from qgis.gui import QgsMapCanvas

from plugin.fortsmart_precision.core.obstacle_detour import DetourParameters, DetourType
from plugin.fortsmart_precision.core.obstacle_detour.models import MSG_SELECT_ONE_EACH
from plugin.fortsmart_precision.gui.obstacle_detour_service import (
    DETOUR_FIELDS,
    DETOUR_LAYER_NAME,
    STATUS_APPLIED,
    STATUS_RESTORED,
    STATUS_SUPERSEDED,
    DetourServiceError,
    active_record,
    apply_detour,
    compute_detour,
    ensure_detour_layer,
    find_detour_layer,
    line_history,
    restore_original,
    to_shapely,
)

_APP = None
CRS = "EPSG:31982"
SPACING = 3.0


def _setup_qgis():
    global _APP
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if QgsApplication.instance() is None:
        _APP = QgsApplication([], True)
        _APP.initQgis()


def _lines(count=50, crs=CRS, geometry="LineString", name="12_Passadas_Plantio", transform=None):
    layer = QgsVectorLayer(f"{geometry}?crs={crs}", name, "memory")
    layer.dataProvider().addAttributes([
        QgsField("line_id", QVariant.String),
        QgsField("line_number", QVariant.Int),
        QgsField("width_m", QVariant.Double),
    ])
    layer.updateFields()
    features = []
    for index in range(count):
        feature = QgsFeature(layer.fields())
        geometry_value = QgsGeometry.fromWkt(f"LINESTRING(0 {index * SPACING}, 200 {index * SPACING})")
        if transform is not None:
            geometry_value.transform(transform)
        feature.setGeometry(geometry_value)
        feature.setAttributes([f"L{index + 1:04d}", index + 1, 2.0])
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    QgsProject.instance().addMapLayer(layer)
    return layer


def _obstacles(points, crs=CRS):
    layer = QgsVectorLayer(f"Point?crs={crs}", "Flag", "memory")
    layer.dataProvider().addAttributes([QgsField("obstacle_id", QVariant.String)])
    layer.updateFields()
    features = []
    for index, (x, y) in enumerate(points):
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt(f"POINT({x} {y})"))
        feature.setAttributes([f"OB-{index + 1:03d}"])
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    QgsProject.instance().addMapLayer(layer)
    return layer


def _feature_by(layer, field, value):
    return next(feature for feature in layer.getFeatures() if feature[field] == value)


def _wkts(layer):
    return {feature.id(): feature.geometry().asWkt(6) for feature in layer.getFeatures()}


def _params(detour_type=DetourType.LATERAL_LEFT, **overrides):
    values = dict(implement_width_m=2.0, obstacle_radius_m=1.0, safety_margin_m=0.5)
    values.update(overrides)
    return DetourParameters(detour_type, **values)


class ObstacleDetourServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()

    def setUp(self):
        QgsProject.instance().clear()
        self.lines = _lines()
        # L0024 em y = 69; poste sobre a linha e outros obstaculos longe dela.
        self.obstacles = _obstacles([(120.0, 69.0)] + [(10.0 + 5 * i, 300.0) for i in range(99)])
        self.line = _feature_by(self.lines, "line_id", "L0024")
        self.obstacle = _feature_by(self.obstacles, "obstacle_id", "OB-001")

    def tearDown(self):
        try:
            if self.lines.isEditable():
                self.lines.rollBack()
        except RuntimeError:
            pass
        QgsProject.instance().clear()

    def _apply(self, params=None):
        records = ensure_detour_layer(self.lines.crs())
        computation = compute_detour(
            self.lines, self.line, self.obstacles, self.obstacle, params or _params(), records
        )
        self.assertTrue(computation.detour.ok, computation.detour.messages)
        record = apply_detour(
            self.lines, self.line.id(), computation, records,
            obstacle_layer=self.obstacles, obstacle_fid=self.obstacle.id(),
        )
        return computation, records, record

    def test_preview_computation_does_not_change_any_layer(self):
        before = _wkts(self.lines)
        computation = compute_detour(self.lines, self.line, self.obstacles, self.obstacle, _params())
        self.assertTrue(computation.detour.ok)
        self.assertEqual(_wkts(self.lines), before)
        self.assertFalse(self.lines.isEditable())
        self.assertIsNone(find_detour_layer())

    def test_apply_changes_only_selected_line_and_records_history(self):
        before = _wkts(self.lines)
        computation, records, record = self._apply()
        after = _wkts(self.lines)
        changed = [fid for fid in before if before[fid] != after[fid]]
        self.assertEqual(changed, [self.line.id()])
        for neighbour in ("L0023", "L0025"):
            fid = _feature_by(self.lines, "line_id", neighbour).id()
            self.assertEqual(after[fid], before[fid])
        self.assertEqual(self.lines.featureCount(), 50)
        new_geometry = to_shapely(self.lines.getFeature(self.line.id()).geometry())
        self.assertGreaterEqual(new_geometry.distance(to_shapely(self.obstacle.geometry())), 1.5 + 1.0 - 0.03)

        self.assertEqual(records.name(), DETOUR_LAYER_NAME)
        self.assertEqual(records.featureCount(), 1)
        names = records.fields().names()
        for required in (
            "detour_id", "line_id", "obstacle_id", "detour_type", "side", "obstacle_radius_m",
            "safety_margin_m", "anticipation_m", "return_m", "reference_to_operation_m", "created_at",
        ):
            self.assertIn(required, names)
        self.assertEqual(len(names), len(DETOUR_FIELDS))
        self.assertEqual(record["line_id"], "L0024")
        self.assertEqual(record["obstacle_id"], "OB-001")
        self.assertEqual(record["detour_type"], "LATERAL_LEFT")
        self.assertEqual(record["side"], "LEFT")
        self.assertEqual(record["status"], STATUS_APPLIED)
        self.assertEqual(record["version"], 1)
        self.assertTrue(QgsGeometry.fromWkt(record["original_wkt"]).equals(self.line.geometry()))

    def test_undo_restores_original_geometry(self):
        original = self.line.geometry().asWkt(6)
        self._apply()
        self.assertTrue(self.lines.isEditable())
        self.assertNotEqual(self.lines.getFeature(self.line.id()).geometry().asWkt(6), original)
        self.lines.undoStack().undo()
        self.assertEqual(self.lines.getFeature(self.line.id()).geometry().asWkt(6), original)
        self.lines.undoStack().redo()
        self.assertNotEqual(self.lines.getFeature(self.line.id()).geometry().asWkt(6), original)

    def test_restore_original_removes_only_that_detour(self):
        before = _wkts(self.lines)
        _computation, records, _record = self._apply()
        restored = restore_original(self.lines, self.line.id(), records)
        self.assertEqual(_wkts(self.lines), before)
        refreshed = records.getFeature(restored.id())
        self.assertEqual(refreshed["status"], STATUS_RESTORED)
        self.assertTrue(refreshed["restored_at"])
        self.assertIsNone(active_record(records, self.lines, self.line.id()))
        with self.assertRaises(DetourServiceError):
            restore_original(self.lines, self.line.id(), records)

    def test_reapply_creates_new_version_from_original(self):
        self._apply(_params(longitudinal_anticipation_m=3.0))
        self.line = self.lines.getFeature(self.line.id())
        computation, records, record = self._apply(_params(longitudinal_anticipation_m=5.0))
        self.assertIsNotNone(computation.superseded_record_id)
        self.assertEqual(record["version"], 2)
        statuses = [feature["status"] for feature in line_history(records, self.lines, self.line.id())]
        self.assertEqual(statuses, [STATUS_SUPERSEDED, STATUS_APPLIED])
        restore_original(self.lines, self.line.id(), records)
        restored = self.lines.getFeature(self.line.id()).geometry()
        self.assertEqual(restored.asWkt(6), "LineString (0 69, 200 69)")

    def test_cut_resume_on_single_part_layer_adds_part_and_restore_removes_it(self):
        before = _wkts(self.lines)
        _computation, records, record = self._apply(_params(DetourType.CUT_RESUME))
        self.assertEqual(self.lines.featureCount(), 51)
        pieces = [f for f in self.lines.getFeatures() if f["line_id"] == "L0024"]
        self.assertEqual(len(pieces), 2)
        self.assertTrue(all(f["width_m"] == 2.0 for f in pieces))
        total = sum(f.geometry().length() for f in pieces)
        self.assertAlmostEqual(total, 200.0 - (3.0 + 1.5 + 1.5 + 3.0), places=2)
        self.assertEqual(record["detour_type"], "CUT_RESUME")
        restore_original(self.lines, self.line.id(), records)
        self.assertEqual(self.lines.featureCount(), 50)
        self.assertEqual(_wkts(self.lines), before)

    def test_cut_resume_on_multipart_layer_keeps_single_feature(self):
        QgsProject.instance().clear()
        self.lines = _lines(geometry="MultiLineString")
        self.obstacles = _obstacles([(120.0, 69.0)])
        self.line = _feature_by(self.lines, "line_id", "L0024")
        self.obstacle = next(self.obstacles.getFeatures())
        self._apply(_params(DetourType.CUT_RESUME))
        self.assertEqual(self.lines.featureCount(), 50)
        geometry = self.lines.getFeature(self.line.id()).geometry()
        self.assertEqual(len(geometry.asGeometryCollection()), 2)

    def test_geographic_layer_is_computed_in_metric_crs_without_changing_layer_crs(self):
        QgsProject.instance().clear()
        utm = QgsCoordinateReferenceSystem(CRS)
        geographic = QgsCoordinateReferenceSystem("EPSG:4674")
        to_geo = QgsCoordinateTransform(utm, geographic, QgsProject.instance())
        lines = QgsVectorLayer("LineString?crs=EPSG:4674", "linhas_geo", "memory")
        lines.dataProvider().addAttributes([QgsField("line_id", QVariant.String)])
        lines.updateFields()
        feature = QgsFeature(lines.fields())
        geometry = QgsGeometry.fromWkt("LINESTRING(500000 7400000, 500200 7400000)")
        geometry.transform(to_geo)
        feature.setGeometry(geometry)
        feature.setAttributes(["L0001"])
        lines.dataProvider().addFeature(feature)
        QgsProject.instance().addMapLayer(lines)
        point = QgsGeometry.fromWkt("POINT(500100 7400000)")
        point.transform(to_geo)
        obstacles = QgsVectorLayer("Point?crs=EPSG:4674", "Flag", "memory")
        obstacle = QgsFeature(obstacles.fields())
        obstacle.setGeometry(point)
        obstacles.dataProvider().addFeature(obstacle)
        QgsProject.instance().addMapLayer(obstacles)
        line = next(lines.getFeatures())
        computation = compute_detour(lines, line, obstacles, next(obstacles.getFeatures()), _params())
        self.assertTrue(computation.metric_crs.authid().startswith("EPSG:319"))
        self.assertTrue(computation.detour.ok, computation.detour.messages)
        self.assertAlmostEqual(computation.detour.original_geometry.length, 200.0, places=1)
        self.assertEqual(lines.crs().authid(), "EPSG:4674")
        records = ensure_detour_layer(lines.crs())
        apply_detour(lines, line.id(), computation, records)
        self.assertEqual(lines.crs().authid(), "EPSG:4674")
        lines.rollBack()

    def test_phase_10_export_after_detour(self):
        self._apply()
        self.assertTrue(self.lines.commitChanges())
        detoured = self.lines.getFeature(self.line.id()).geometry()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            for driver, extension in (("GPKG", "gpkg"), ("ESRI Shapefile", "shp")):
                path = os.path.join(folder, f"linhas.{extension}")
                options = QgsVectorFileWriter.SaveVectorOptions()
                options.driverName = driver
                error = QgsVectorFileWriter.writeAsVectorFormatV3(
                    self.lines, path, QgsProject.instance().transformContext(), options
                )
                self.assertEqual(error[0], QgsVectorFileWriter.NoError, error)
                exported = QgsVectorLayer(path, "exportada", "ogr")
                self.assertEqual(exported.featureCount(), 50)
                match = next(f for f in exported.getFeatures() if f["line_id"] == "L0024")
                self.assertLess(
                    to_shapely(match.geometry()).hausdorff_distance(to_shapely(detoured)), 1e-6
                )
                del exported

    def test_phase_10_export_readiness_is_unchanged_by_detour(self):
        from plugin.fortsmart_precision.core.export_readiness_validator import validate_field_for_export
        from plugin.fortsmart_precision.core.layer_roles import definition_for_role, set_layer_role_properties

        QgsProject.instance().clear()
        boundary = QgsVectorLayer(f"Polygon?crs={CRS}", "01_Limite_Externo", "memory")
        feature = QgsFeature()
        feature.setGeometry(QgsGeometry.fromWkt("POLYGON((-10 -10,210 -10,210 160,-10 160,-10 -10))"))
        boundary.dataProvider().addFeature(feature)
        set_layer_role_properties(boundary, definition_for_role("EXTERNAL_BOUNDARY"), field_name="TL-12")
        QgsProject.instance().addMapLayer(boundary)
        self.lines = _lines()
        set_layer_role_properties(self.lines, definition_for_role("WORK_PATH"), field_name="TL-12")
        self.obstacles = _obstacles([(120.0, 69.0)])
        self.line = _feature_by(self.lines, "line_id", "L0024")
        self.obstacle = next(self.obstacles.getFeatures())

        before = validate_field_for_export("TL-12")
        self._apply()
        self.assertTrue(self.lines.commitChanges())
        after = validate_field_for_export("TL-12")
        self.assertEqual(after.status, before.status)
        self.assertEqual(
            sorted(str(item) for item in after.errors), sorted(str(item) for item in before.errors)
        )


def _field(wkt="POLYGON((-10 -10,210 -10,210 70.5,-10 70.5,-10 -10))", role=True, name="Area"):
    from plugin.fortsmart_precision.core.layer_roles import definition_for_role, set_layer_role_properties

    layer = QgsVectorLayer(f"Polygon?crs={CRS}", name, "memory")
    feature = QgsFeature()
    feature.setGeometry(QgsGeometry.fromWkt(wkt))
    layer.dataProvider().addFeature(feature)
    if role:
        set_layer_role_properties(layer, definition_for_role("EXTERNAL_BOUNDARY"), field_name="TL-12")
    QgsProject.instance().addMapLayer(layer)
    return layer


class ObstacleDetourSurroundingsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()

    def setUp(self):
        QgsProject.instance().clear()
        self.lines = _lines()
        # OB-002 fica ao lado do desvio pela esquerda de L0024 (y = 69).
        self.obstacles = _obstacles([(120.0, 69.0), (120.0, 73.0), (20.0, 69.0 + 30.0)])
        self.line = _feature_by(self.lines, "line_id", "L0024")
        self.obstacle = _feature_by(self.obstacles, "obstacle_id", "OB-001")

    def tearDown(self):
        if self.lines.isEditable():
            self.lines.rollBack()
        QgsProject.instance().clear()

    def test_other_obstacle_in_detour_is_warned_and_recorded(self):
        records = ensure_detour_layer(self.lines.crs())
        computation = compute_detour(self.lines, self.line, self.obstacles, self.obstacle, _params(), records)
        self.assertTrue(computation.detour.ok)
        self.assertEqual(
            computation.detour.warnings, ("⚠ O desvio passa pela zona de outro obstáculo: OB-002.",)
        )
        right = compute_detour(
            self.lines, self.line, self.obstacles, self.obstacle, _params(DetourType.LATERAL_RIGHT)
        )
        self.assertEqual(right.detour.warnings, ())
        record = apply_detour(self.lines, self.line.id(), computation, records)
        self.assertIn("OB-002", record["warnings"])

    def test_detour_leaving_field_is_warned(self):
        field = _field()
        computation = compute_detour(
            self.lines, self.line, self.obstacles, self.obstacle, _params(DetourType.LATERAL_RIGHT),
            field_layer=field,
        )
        self.assertEqual(computation.detour.warnings, ())
        left = compute_detour(
            self.lines, self.line, self.obstacles, self.obstacle,
            _params(obstacle_radius_m=1.0), field_layer=field,
        )
        self.assertTrue(any("sai do talhão" in item for item in left.detour.warnings), left.detour.warnings)

    def test_field_layer_is_auto_detected_and_dialog_confirmation_defaults_to_no(self):
        _field()
        _field(name="Outra area", role=False)
        canvas = QgsMapCanvas()
        iface = MagicMock()
        iface.mainWindow.return_value = None
        iface.mapCanvas.return_value = canvas
        from plugin.fortsmart_precision.gui.obstacle_detour_dialog import ObstacleDetourDialog

        dialog = ObstacleDetourDialog(iface)
        self.assertEqual(dialog.field_combo.currentLayer().name(), "Area")
        dialog.line_combo.setLayer(self.lines)
        dialog.obstacle_combo.setLayer(self.obstacles)
        dialog.set_line(self.line)
        dialog.set_obstacle(self.obstacle)
        self.assertTrue(dialog.run_preview())
        self.assertIn("OB-002", dialog.status_label.text())
        self.assertIn("#b35c00", dialog.status_label.styleSheet())
        with patch(
            "plugin.fortsmart_precision.gui.obstacle_detour_dialog.QMessageBox.question",
            return_value=QMessageBox.No,
        ) as question:
            self.assertFalse(dialog.apply_with_confirmation())
        args = question.call_args[0]
        self.assertIn("ATENÇÃO", args[2])
        self.assertIn("Aplicar mesmo assim?", args[2])
        self.assertEqual(args[4], QMessageBox.No)
        self.assertFalse(self.lines.isEditable())
        dialog.close()


class ObstacleDetourDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()

    def setUp(self):
        QgsProject.instance().clear()
        self.lines = _lines(30)
        self.obstacles = _obstacles([(120.0, 69.0), (50.0, 300.0)])
        self.canvas = QgsMapCanvas()
        self.iface = MagicMock()
        self.iface.mainWindow.return_value = None
        self.iface.mapCanvas.return_value = self.canvas
        from plugin.fortsmart_precision.gui.obstacle_detour_dialog import ObstacleDetourDialog

        self.dialog = ObstacleDetourDialog(self.iface)
        self.dialog.line_combo.setLayer(self.lines)
        self.dialog.obstacle_combo.setLayer(self.obstacles)

    def tearDown(self):
        self.dialog.close()
        if self.lines.isEditable():
            self.lines.rollBack()
        QgsProject.instance().clear()

    def test_obstacle_layer_is_auto_detected_and_planned_types_disabled(self):
        from plugin.fortsmart_precision.gui.obstacle_detour_dialog import ObstacleDetourDialog

        dialog = ObstacleDetourDialog(self.iface)
        self.assertIs(dialog.obstacle_combo.currentLayer(), self.obstacles)
        model = dialog.type_combo.model()
        enabled = {
            dialog.type_combo.itemData(i): model.item(i).isEnabled() for i in range(dialog.type_combo.count())
        }
        self.assertEqual(
            {key for key, value in enabled.items() if value}, {"LATERAL_LEFT", "LATERAL_RIGHT", "CUT_RESUME"}
        )
        dialog.close()

    def test_selection_validation_messages(self):
        self.lines.selectByIds([f.id() for f in list(self.lines.getFeatures())[:2]])
        self.obstacles.selectByIds([next(self.obstacles.getFeatures()).id()])
        self.assertFalse(self.dialog.use_map_selection())
        self.assertEqual(self.dialog.status_label.text(), MSG_SELECT_ONE_EACH)
        self.assertFalse(self.dialog.run_preview())
        self.assertEqual(self.dialog.status_label.text(), "Selecione uma linha de plantio.")

    def test_preview_apply_and_restore_through_dialog(self):
        line = _feature_by(self.lines, "line_id", "L0024")
        obstacle = _feature_by(self.obstacles, "obstacle_id", "OB-001")
        self.lines.selectByIds([line.id()])
        self.obstacles.selectByIds([obstacle.id()])
        self.assertTrue(self.dialog.use_map_selection())
        self.assertEqual(self.dialog.line_label.text(), "L0024")
        self.assertEqual(self.dialog.obstacle_label.text(), "OB-001")
        self.assertAlmostEqual(self.dialog.width_spin.value(), 2.0)

        before = _wkts(self.lines)
        self.assertTrue(self.dialog.run_preview(), self.dialog.status_label.text())
        self.assertEqual(_wkts(self.lines), before)
        self.assertFalse(self.lines.isEditable())
        self.assertTrue(self.dialog.apply_button.isEnabled())
        self.assertGreaterEqual(len(self.dialog.preview.bands), 4)

        with patch(
            "plugin.fortsmart_precision.gui.obstacle_detour_dialog.QMessageBox.question",
            return_value=QMessageBox.Yes,
        ) as question:
            self.assertTrue(self.dialog.apply_with_confirmation())
            text = question.call_args[0][2]
            for token in ("Aplicar desvio?", "Linha: L0024", "Obstáculo: OB-001", "A geometria original será preservada."):
                self.assertIn(token, text)
            self.assertNotEqual(_wkts(self.lines)[line.id()], before[line.id()])
            self.assertEqual(self.dialog.preview.bands, [])
            self.assertTrue(self.dialog.restore_with_confirmation())
        self.assertEqual(_wkts(self.lines), before)

    def test_changing_parameters_requires_new_preview(self):
        self.dialog.set_line(_feature_by(self.lines, "line_id", "L0024"))
        self.dialog.set_obstacle(_feature_by(self.obstacles, "obstacle_id", "OB-001"))
        self.assertTrue(self.dialog.run_preview())
        self.dialog.margin_spin.setValue(1.0)
        self.assertFalse(self.dialog.apply_button.isEnabled())
        self.assertIsNone(self.dialog.computation)
        self.assertIn("Zona de segurança: 2.00 m", self.dialog.summary_label.text().replace(",", "."))

    def test_infeasible_transition_suggests_without_applying(self):
        self.dialog.set_line(_feature_by(self.lines, "line_id", "L0024"))
        self.dialog.set_obstacle(_feature_by(self.obstacles, "obstacle_id", "OB-001"))
        self.dialog.width_spin.setValue(12.0)
        self.assertFalse(self.dialog.run_preview())
        text = self.dialog.status_label.text()
        self.assertIn("Não foi possível criar uma transição válida", text)
        self.assertIn("Sugestão: antecipação", text)
        self.assertFalse(self.dialog.apply_button.isEnabled())
        self.assertAlmostEqual(self.dialog.anticipation_spin.value(), 3.0)


class ObstacleDetourPluginActionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_qgis()

    def test_plugin_registers_detour_action_in_menu_and_toolbar(self):
        from plugin.fortsmart_precision import plugin as plugin_module

        iface = MagicMock()
        iface.mainWindow.return_value = None
        plugin = plugin_module.FortSmartPrecisionPlugin(iface)
        with patch.object(QgsApplication, "processingRegistry"):
            plugin.initGui()
        action = plugin.action_obstacle_detour
        self.assertEqual(action.text(), "↪ Desvio de Obstáculo")
        self.assertEqual(action.toolTip(), "Criar desvio manual de uma linha ao redor de um obstáculo")
        iface.addPluginToMenu.assert_any_call("FortSmart Precision", action)
        iface.addToolBarIcon.assert_any_call(action)
        with patch.object(QgsApplication, "processingRegistry"):
            plugin.unload()
        iface.removeToolBarIcon.assert_any_call(action)


if __name__ == "__main__":
    unittest.main()
