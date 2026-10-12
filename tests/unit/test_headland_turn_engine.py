"""Manobras de cabeceira entre passadas existentes (10 testes obrigatorios + auxiliares).

Os testes puros rodam em qualquer Python; os marcados com HAS_QGIS (preview
repetido e salvar duas vezes) rodam no Python do QGIS 3.44.
"""

import ast
import copy
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from shapely.geometry import LineString, Point, box

from plugin.fortsmart_precision.core.headland_turn_engine import (
    STATUS_DIRECTION_CONFLICT,
    STATUS_INFEASIBLE_RADIUS,
    STATUS_OBSTACLE_CONFLICT,
    STATUS_OK,
    STATUS_WARNING_CROSSING,
    HeadlandTurn,
    HeadlandTurnError,
    LogicalPass,
    OperationalPass,
    PassClass,
    PassRecord,
    TurnMode,
    TurnSettings,
    build_logical_passes,
    check_connection,
    classify_pass,
    direction_from_attributes,
    endpoint_pairs,
    get_operational_end,
    get_operational_start,
    mark_crossings,
    plan_headland_turns,
    resolve_operational_directions,
    tangent_errors_deg,
    turn_id_for,
    u_turn_path,
)
from plugin.fortsmart_precision.core.layer_roles import HEADLAND_TURN_ROLE, layer_role_definition

try:
    from qgis.core import QgsApplication

    HAS_QGIS = True
except ImportError:
    HAS_QGIS = False

CRS = "EPSG:31981"
PLUGIN_DIR = Path(__file__).resolve().parents[2] / "plugin" / "fortsmart_precision"


def records(count, *, spacing=30.0, length=500.0, numbers=None, alternate=False, stagger=0.0):
    """Passadas verticais x = k*spacing; por padrao todas digitalizadas de baixo p/ cima."""
    numbers = numbers or list(range(1, count + 1))
    output = []
    for k, number in enumerate(numbers):
        x = k * spacing
        points = ((x, 0.0), (x, length + k * stagger))
        if alternate and k % 2:
            points = tuple(reversed(points))
        output.append(PassRecord(points, line_id=f"L{number:04d}", number=number))
    return output


def plan(recs, radius=12.0, **kwargs):
    passes, _source = build_logical_passes(recs)
    settings_keys = {"mode", "keep_inside", "respect_direction", "include_border"}
    settings = TurnSettings(min_turn_radius_m=radius, **{k: v for k, v in kwargs.items() if k in settings_keys})
    extra = {k: v for k, v in kwargs.items() if k not in settings_keys}
    return plan_headland_turns(passes, settings, **extra)


def assert_c1(test, turn, exit_heading, entry_heading):
    start_error, end_error = tangent_errors_deg(turn.points, exit_heading, entry_heading)
    test.assertLessEqual(start_error, 2.0)
    test.assertLessEqual(end_error, 2.0)
    for a, b, c in zip(turn.points, turn.points[1:], turn.points[2:]):
        h1 = (b[0] - a[0], b[1] - a[1])
        h2 = (c[0] - b[0], c[1] - b[1])
        angle = abs(math.degrees(math.atan2(h1[0] * h2[1] - h1[1] * h2[0], h1[0] * h2[0] + h1[1] * h2[1])))
        test.assertLess(angle, 2.5, "quina na manobra")


class MandatoryPureTests(unittest.TestCase):
    def test_01_two_parallel_lines_one_smooth_u(self):
        recs = records(2, alternate=True)
        before = copy.deepcopy(recs)
        result = plan(recs)
        self.assertEqual(recs, before)
        (turn,) = result.turns
        self.assertEqual(turn.status, STATUS_OK)
        self.assertEqual((turn.from_pass, turn.to_pass), (1, 2))
        self.assertEqual(turn.points[0], (0.0, 500.0))
        self.assertEqual(turn.points[-1], (30.0, 500.0))
        self.assertAlmostEqual(turn.radius_m, 15.0, places=6)
        self.assertGreaterEqual(turn.radius_m, 12.0)
        assert_c1(self, turn, (0.0, 1.0), (0.0, -1.0))
        self.assertAlmostEqual(turn.length_m, math.pi * 15.0, delta=0.05)
        self.assertFalse(result.report["passes_modified"])

    def test_02_ten_lines_nine_turns(self):
        result = plan(records(10))
        self.assertEqual(len(result.turns), 9)
        self.assertTrue(all(turn.status == STATUS_OK for turn in result.turns))
        self.assertEqual([t.sequence for t in result.turns], list(range(1, 10)))

    def test_03_numbering_104_106_108_is_kept(self):
        result = plan(records(3, numbers=[108, 104, 106]))
        pairs = [(t.from_pass, t.to_pass) for t in result.turns]
        self.assertEqual(pairs, [(104, 106), (106, 108)])
        self.assertEqual(result.turns[0].turn_id, "T104_106")

    def test_04_alternating_direction_connects_operational_endpoints(self):
        for alternate, source in ((False, "zigzag"), (True, "geometry")):
            result = plan(records(4, alternate=alternate))
            self.assertEqual(result.report["direction_source"], source)
            ends = [t.points[0][1] for t in result.turns]
            self.assertEqual(ends, [500.0, 0.0, 500.0])
            for turn in result.turns:
                self.assertEqual(turn.status, STATUS_OK)
                self.assertEqual(turn.points[-1][1], turn.points[0][1])

    def test_05_border_passes_stay_out_of_main_sequence(self):
        recs = records(3)
        recs.append(PassRecord(((-40.0, 0.0), (-40.0, 500.0)), attributes={"label": "B1"}))
        recs.append(PassRecord(((200.0, 0.0), (200.0, 500.0)), attributes={"pass_class": "BORDER"}))
        result = plan(recs)
        self.assertEqual(result.report["border_passes_ignored"], 2)
        self.assertEqual([(t.from_pass, t.to_pass) for t in result.turns], [(1, 2), (2, 3)])

    def test_06_no_room_is_infeasible_radius_without_fake_corner(self):
        narrow = box(-50, -5, 150, 505)
        result = plan(records(2), turning_area=narrow)
        (turn,) = result.turns
        self.assertEqual(turn.status, STATUS_INFEASIBLE_RADIUS)
        self.assertEqual(turn.points, ())
        close = plan(records(2, spacing=20.0), radius=12.0)
        self.assertEqual(close.turns[0].status, STATUS_INFEASIBLE_RADIUS)
        self.assertEqual(close.turns[0].points, ())
        self.assertIn("20.00", close.turns[0].message)

    def test_07_obstacle_on_turn_is_conflict_and_pass_untouched(self):
        recs = records(2)
        before = copy.deepcopy(recs)
        zone = Point(15.0, 510.0).buffer(6.0)
        result = plan(recs, obstacles=zone)
        (turn,) = result.turns
        self.assertEqual(turn.status, STATUS_OBSTACLE_CONFLICT)
        self.assertTrue(LineString(turn.points).intersects(zone))
        self.assertEqual(recs, before)

    def test_small_obstacle_is_avoided_with_smaller_valid_radius(self):
        post = Point(15.0, 515.0).buffer(1.0)
        (turn,) = plan(records(2), obstacles=post).turns
        self.assertEqual(turn.status, STATUS_OK)
        self.assertFalse(LineString(turn.points).intersects(post))
        self.assertGreaterEqual(turn.radius_m, 12.0)

    def test_10_engine_does_not_touch_generator_or_other_engines(self):
        tree = ast.parse((PLUGIN_DIR / "core" / "headland_turn_engine.py").read_text(encoding="utf-8"))
        imported = {
            node.module.split(".")[-1]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        for forbidden in ("parallel_pass_engine", "precision_lines_engine", "turn_path_engine",
                          "obstacle_border_pass_engine", "longitudinal_cut_engine"):
            self.assertNotIn(forbidden, imported)
        self.assertEqual(layer_role_definition("06_Passadas_Plantio").role, "WORK_PATH")
        self.assertEqual(HEADLAND_TURN_ROLE.role, "HEADLAND_TURN")
        self.assertEqual(HEADLAND_TURN_ROLE.section, "10_PLANEJAMENTO")
        self.assertEqual(HEADLAND_TURN_ROLE.display_name, "16_Manobras_Cabeceira")


class LogicalIdentityTest(unittest.TestCase):
    def test_cut_line_uses_logical_end_not_segment_end(self):
        recs = [
            PassRecord(((0.0, 0.0), (0.0, 200.0)), line_id="L0112", number=112, segment_index=1),
            PassRecord(((0.0, 240.0), (0.0, 500.0)), line_id="L0112", number=112, segment_index=2),
            PassRecord(((30.0, 500.0), (30.0, 0.0)), line_id="L0114", number=114, segment_index=1),
        ]
        passes, source = build_logical_passes(recs)
        self.assertEqual(source, "attribute")
        self.assertEqual(len(passes), 2)
        result = plan(recs)
        (turn,) = result.turns
        self.assertEqual(turn.status, STATUS_OK)
        self.assertEqual(turn.points[0], (0.0, 500.0))

    def test_segments_without_index_are_ordered_along_line(self):
        recs = [
            PassRecord(((0.0, 240.0), (0.0, 500.0)), number=7),
            PassRecord(((0.0, 0.0), (0.0, 200.0)), number=7),
        ]
        (logical,), _source = build_logical_passes(recs)
        self.assertEqual(logical.start, (0.0, 0.0))
        self.assertEqual(logical.end, (0.0, 500.0))

    def test_missing_numbers_use_spatial_order_once(self):
        recs = [PassRecord(((60.0, 0.0), (60.0, 100.0))), PassRecord(((0.0, 0.0), (0.0, 100.0)))]
        passes, source = build_logical_passes(recs)
        self.assertEqual(source, "spatial_order")
        mapping = {p.start[0]: p.number for p in passes}
        self.assertEqual(sorted(mapping.values()), [1, 2])
        again, _source = build_logical_passes(list(reversed(recs)))
        self.assertEqual({p.start[0]: p.number for p in again}, mapping)

    def test_classify_and_direction_attributes(self):
        self.assertIs(classify_pass({"label": "B2"}), PassClass.BORDER)
        self.assertIs(classify_pass({"fortsmart_role": "FIELD_HEADLAND_PATH"}), PassClass.BORDER)
        self.assertIs(classify_pass({"label": "P3", "pass_class": None}), PassClass.MAIN)
        self.assertEqual(direction_from_attributes({"direction": "B->A"}), -1)
        self.assertEqual(direction_from_attributes({"Sentido": "ida"}), 1)
        self.assertEqual(direction_from_attributes({"reversed": "true"}), -1)
        self.assertIsNone(direction_from_attributes({"direction": "NULL"}))


class DirectionTest(unittest.TestCase):
    def logical(self, recs):
        passes, _source = build_logical_passes(recs)
        return sorted(passes, key=lambda p: p.number)

    def test_attribute_direction_has_priority(self):
        recs = records(2)
        recs = [
            PassRecord(r.points, r.line_id, r.number, attributes={"direction": d})
            for r, d in zip(recs, ("reverse", "forward"))
        ]
        ops, source = resolve_operational_directions(self.logical(recs))
        self.assertEqual(source, "attribute")
        self.assertEqual(get_operational_end(ops[0]).point, (0.0, 0.0))
        self.assertEqual(get_operational_start(ops[1]).point, (30.0, 0.0))
        self.assertEqual(get_operational_end(ops[0]).heading, (0.0, -1.0))

    def test_ab_line_orients_first_pass(self):
        ops, source = resolve_operational_directions(self.logical(records(2)), ab_heading=(0.0, -5.0))
        self.assertEqual(source, "ab_line")
        self.assertTrue(ops[0].reversed)
        self.assertFalse(ops[1].reversed)

    def test_same_direction_attributes_are_direction_conflict(self):
        recs = [PassRecord(r.points, r.line_id, r.number, attributes={"direction": "forward"}) for r in records(2)]
        result = plan(recs)
        self.assertEqual(result.turns[0].status, STATUS_DIRECTION_CONFLICT)
        self.assertEqual(result.turns[0].points, ())

    def test_four_endpoint_pairs_are_evaluated(self):
        ops, _source = resolve_operational_directions(self.logical(records(2)))
        pairs = endpoint_pairs(ops[0], ops[1])
        self.assertEqual(len(pairs), 4)
        self.assertIsNone(check_connection(ops[0], ops[1]))
        wrong = OperationalPass(ops[1].logical, not ops[1].reversed)
        self.assertIsNotNone(check_connection(ops[0], wrong))

    def test_original_geometry_is_never_inverted(self):
        passes = self.logical(records(2))
        ops, _source = resolve_operational_directions(passes)
        self.assertTrue(ops[1].reversed)
        self.assertEqual(ops[1].logical.segments, ((( 30.0, 0.0), (30.0, 500.0)),))


class GeometryTest(unittest.TestCase):
    def test_staggered_ends_keep_tangency_and_radius(self):
        result = plan(records(3, stagger=25.0))
        for turn in result.turns:
            self.assertEqual(turn.status, STATUS_OK)
            self.assertGreaterEqual(turn.radius_m, 12.0)
        first = result.turns[0]
        assert_c1(self, first, (0.0, 1.0), (0.0, -1.0))
        self.assertEqual(first.points[-1], (30.0, 525.0))

    def test_u_turn_rejects_loop_below_twice_radius(self):
        self.assertIsNone(u_turn_path((0, 0), (0, 1), (10, 0), (0, -1), 12.0, turn_left=False))
        built = u_turn_path((0, 0), (0, 1), (30, 0), (0, -1), 12.0, turn_left=False)
        points, theta1, theta2 = built
        self.assertAlmostEqual(theta1 + theta2, math.pi, places=6)
        self.assertAlmostEqual(points[-1][0], 30.0, places=6)

    def test_narrow_headland_prefers_smaller_radius_that_fits(self):
        area = box(-50, -50, 150, 515)
        result = plan(records(2, spacing=40.0), turning_area=area)
        (turn,) = result.turns
        self.assertEqual(turn.status, STATUS_OK)
        self.assertLess(turn.radius_m, 20.0)
        self.assertGreaterEqual(turn.radius_m, 12.0)
        self.assertTrue(area.covers(LineString(turn.points)))

    def test_keep_inside_false_ignores_area(self):
        result = plan(records(2), turning_area=box(-50, -5, 150, 505), keep_inside=False)
        self.assertEqual(result.turns[0].status, STATUS_OK)

    def test_crossing_turns_are_warned(self):
        a = HeadlandTurn("T1", 1, 2, "a", "b", "U_TURN", 12.0, 10.0, STATUS_OK, 1, ((0, 0), (10, 10)), 30.0)
        b = HeadlandTurn("T2", 3, 4, "c", "d", "U_TURN", 12.0, 10.0, STATUS_OK, 2, ((0, 10), (10, 0)), 30.0)
        c = HeadlandTurn("T3", 5, 6, "e", "f", "U_TURN", 12.0, 10.0, STATUS_OK, 3, ((20, 0), (30, 0)), 30.0)
        marked = mark_crossings([a, b, c])
        self.assertEqual([t.status for t in marked], [STATUS_WARNING_CROSSING] * 2 + [STATUS_OK])
        self.assertIn("T2", marked[0].message)

    def test_settings_validation_and_reserved_modes(self):
        with self.assertRaises(HeadlandTurnError):
            TurnSettings(min_turn_radius_m=0).validate()
        for mode in (TurnMode.TEARDROP, TurnMode.SKIP_PASS):
            with self.assertRaises(HeadlandTurnError):
                TurnSettings(min_turn_radius_m=12, mode=mode).validate()
        TurnSettings(min_turn_radius_m=12, mode=TurnMode.U_TURN).validate()
        self.assertEqual(turn_id_for(56, 58), "T056_058")
        self.assertEqual(turn_id_for(-1, 1), "TM001_001")

    def test_attributes_contract(self):
        (turn,) = plan(records(2)).turns
        attrs = turn.attributes("12_Passadas_Plantio")
        for key in ("turn_id", "from_pass", "to_pass", "turn_type", "radius_m", "length_m", "status",
                    "sequence", "source_layer", "simulation_only"):
            self.assertIn(key, attrs)
        self.assertTrue(attrs["simulation_only"])
        self.assertEqual(attrs["turn_type"], "U_TURN")


# ---------------------------------------------------------------- QGIS ----
_APP = None


def _qgis_setup():
    global _APP
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if QgsApplication.instance() is None:
        _APP = QgsApplication([], True)
        _APP.initQgis()


def _layer(uri, name, rows, role=None):
    from qgis.core import QgsFeature, QgsGeometry, QgsVectorLayer

    from plugin.fortsmart_precision.core.layer_roles import LayerRoleDefinition, apply_qgis_layer_role

    layer = QgsVectorLayer(uri, name, "memory")
    features = []
    for attributes, wkt in rows:
        feature = QgsFeature(layer.fields())
        feature.setAttributes(list(attributes))
        feature.setGeometry(QgsGeometry.fromWkt(wkt))
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    if role:
        apply_qgis_layer_role(layer, LayerRoleDefinition(name, "", role))
    return layer


class _Iface:
    def __init__(self):
        from qgis.PyQt.QtWidgets import QMainWindow

        self.window = QMainWindow()

    def mainWindow(self):
        return self.window

    def mapCanvas(self):
        return None


class _SilentBox:
    @staticmethod
    def _quiet(*_args, **_kwargs):
        return None

    warning = critical = information = _quiet


@unittest.skipUnless(HAS_QGIS, "QGIS nao disponivel")
class HeadlandTurnsDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _qgis_setup()

    def setUp(self):
        from qgis.core import QgsProject

        from plugin.fortsmart_precision.gui import headland_turns_dialog as module

        self.module = module
        self.project = QgsProject.instance()
        self.project.clear()
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.project.setFileName(str(Path(self.tmp.name) / "fazenda.qgz"))
        self.storage = Path(self.tmp.name) / "fortsmart_data" / "talhao_T" / "fortsmart_talhao_T.gpkg"
        uri = f"LineString?crs={CRS}&field=line_id:string&field=line_number:integer"
        self.passes = _layer(uri, "12_Passadas_Plantio", [
            ((f"L{n:04d}", n), f"LINESTRING({(n - 104) * 15} 0, {(n - 104) * 15} 500)")
            for n in (104, 106, 108, 110)
        ], role="WORK_PATH")
        self.border = _layer(f"LineString?crs={CRS}&field=label:string", "15_Passadas_Bordadura", [
            (("B1",), "LINESTRING(-30 -30, -30 530)"), (("B2",), "LINESTRING(120 -30, 120 530)"),
        ], role="FIELD_HEADLAND_PATH")
        self.headland = _layer(f"Polygon?crs={CRS}", "03_Bordadura", [
            ((), "POLYGON((-40 -60,130 -60,130 560,-40 560,-40 -60),(-20 20,110 20,110 480,-20 480,-20 20))"),
        ], role="HEADLAND")
        self.boundary = _layer(f"Polygon?crs={CRS}", "01_Limite_Externo", [
            ((), "POLYGON((-40 -60,130 -60,130 560,-40 560,-40 -60))"),
        ], role="EXTERNAL_BOUNDARY")
        root = self.project.layerTreeRoot()
        group = root.addGroup("FORTSMART - talhao_T")
        references = group.addGroup("00_REFERENCIAS")
        planning = group.addGroup("10_PLANEJAMENTO")
        for layer, parent in ((self.boundary, references), (self.headland, references),
                              (self.passes, planning), (self.border, planning)):
            self.project.addMapLayer(layer, False)
            parent.addLayer(layer)
        self.box_patch = mock.patch.object(module, "QMessageBox", _SilentBox)
        self.box_patch.start()
        self.dialog = module.HeadlandTurnsDialog(_Iface())
        self.dialog.radius_spin.setValue(6.0)

    def tearDown(self):
        self.dialog.reject()
        self.box_patch.stop()
        self.project.clear()
        self.tmp.cleanup()

    def turn_layers(self):
        return [layer for layer in self.project.mapLayers().values() if self.module.is_turn_layer(layer)]

    def test_auto_selection_by_role(self):
        self.assertIs(self.dialog.pass_combo.currentLayer(), self.passes)
        self.assertIs(self.dialog.area_combo.currentLayer(), self.headland)
        self.assertIs(self.dialog.boundary_combo.currentLayer(), self.boundary)
        self.assertEqual(self.dialog.source_combo.currentData(), "WORK_PATH")

    def test_missing_radius_blocks_preview(self):
        self.dialog.radius_spin.setValue(0.0)
        self.assertFalse(self.dialog.preview_btn.isEnabled())
        self.assertFalse(self.dialog.save_btn.isEnabled())

    def test_preview_connects_main_only_and_keeps_passes(self):
        before = [(f.attributes(), f.geometry().asWkt()) for f in self.passes.getFeatures()]
        fields = self.passes.fields().names()
        self.dialog.preview()
        (preview,) = self.turn_layers()
        rows = sorted((f["from_pass"], f["to_pass"], f["status"]) for f in preview.getFeatures())
        self.assertEqual(rows, [(104, 106, "OK"), (106, 108, "OK"), (108, 110, "OK")])
        self.assertEqual([(f.attributes(), f.geometry().asWkt()) for f in self.passes.getFeatures()], before)
        self.assertEqual(self.passes.fields().names(), fields)
        node = self.project.layerTreeRoot().findLayer(preview.id())
        self.assertEqual(node.parent().name(), "SIM_PREVIEW")
        self.assertEqual(node.parent().parent().name(), "FORTSMART - talhao_T")
        self.assertTrue(preview.customProperty("fortsmart_temporary_preview"))
        self.assertEqual(preview.customProperty("fortsmart_field_id"), "talhao_T")

    def test_empty_final_lines_fall_back_to_planting_passes(self):
        uri = f"LineString?crs={CRS}&field=line_id:string&field=line_number:integer"
        empty_final = _layer(uri, "31_Linhas_Finais", [], role="FINAL_WORK_PATH")
        self.project.addMapLayer(empty_final)
        dialog = self.module.HeadlandTurnsDialog(_Iface())
        try:
            self.assertEqual(dialog.source_combo.currentData(), "WORK_PATH")
            self.assertIs(dialog.pass_combo.currentLayer(), self.passes)
        finally:
            dialog.reject()

    def test_final_lines_with_features_are_preferred(self):
        uri = f"LineString?crs={CRS}&field=line_id:string&field=line_number:integer"
        final = _layer(uri, "Linhas finais renomeadas", [
            (("L0104", 104), "LINESTRING(0 0, 0 500)"),
        ], role="FINAL_WORK_PATH")
        self.project.addMapLayer(final)
        dialog = self.module.HeadlandTurnsDialog(_Iface())
        try:
            self.assertEqual(dialog.source_combo.currentData(), "FINAL_WORK_PATH")
            self.assertIs(dialog.pass_combo.currentLayer(), final)
        finally:
            dialog.reject()

    def test_preview_group_is_removed_when_dialog_closes(self):
        self.dialog.preview()
        group = self.project.layerTreeRoot().findGroup("FORTSMART - talhao_T")
        self.assertIsNotNone(group.findGroup("SIM_PREVIEW"))
        self.dialog.reject()
        self.assertIsNone(group.findGroup("SIM_PREVIEW"))
        self.assertIsNotNone(group.findGroup("10_PLANEJAMENTO"))

    def test_08_preview_ten_times_keeps_one_preview(self):
        base = len(self.project.mapLayers())
        for _ in range(10):
            self.dialog.preview()
        self.assertEqual(len(self.turn_layers()), 1)
        self.assertEqual(len(self.project.mapLayers()), base + 1)

    def test_09_save_twice_updates_same_layer(self):
        from qgis.core import QgsProviderRegistry

        self.dialog.preview()
        self.dialog.save()
        first = self.turn_layers()[0]
        self.assertEqual({f["radius_m"] for f in first.getFeatures()}, {15.0})
        self.dialog.radius_spin.setValue(16.0)
        self.dialog.preview()
        self.dialog.save()
        layers = self.turn_layers()
        self.assertEqual([layer.name() for layer in layers], ["16_Manobras_Cabeceira"])
        saved = layers[0]
        self.assertIs(saved, first)
        self.assertEqual(saved.providerType(), "ogr")
        self.assertEqual(saved.customProperty("fortsmart_role"), "HEADLAND_TURN")
        self.assertEqual(saved.customProperty("fortsmart_storage"), "geopackage")
        self.assertFalse(saved.customProperty(self.module.TURN_PREVIEW_PROPERTY, False))
        self.assertEqual(saved.featureCount(), 3)
        self.assertEqual({f["status"] for f in saved.getFeatures()}, {"INFEASIBLE_RADIUS"})
        self.assertEqual(len(QgsProviderRegistry.instance().querySublayers(str(self.storage))), 1)
        self.assertTrue((self.storage.parent / "16_Manobras_Cabeceira.validation.json").exists())
        node = self.project.layerTreeRoot().findLayer(saved.id())
        self.assertEqual(node.parent().name(), "10_PLANEJAMENTO")

    def test_saved_turns_survive_project_reopen(self):
        self.dialog.preview()
        self.dialog.save()
        project_file = self.project.fileName()
        self.dialog.reject()
        self.assertTrue(self.project.write())
        self.project.clear()
        self.assertTrue(self.project.read(project_file))
        turns = [layer for layer in self.project.mapLayers().values()
                 if layer.customProperty("fortsmart_role", "") == "HEADLAND_TURN"]
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].featureCount(), 3)
        self.assertEqual({f["fortsmart_role"] for f in turns[0].getFeatures()}, {"HEADLAND_TURN"})
        self.assertEqual({f["field_id"] for f in turns[0].getFeatures()}, {"talhao_T"})
        self.dialog = self.module.HeadlandTurnsDialog(_Iface())

    def test_unsaved_project_blocks_turn_save(self):
        self.project.setFileName("")
        self.dialog.preview()
        self.dialog.save()
        self.assertFalse(self.storage.exists())
        self.assertIsNotNone(self.dialog.last_plan)
        self.assertTrue(all(layer.providerType() == "memory" for layer in self.turn_layers()))

    def test_passes_ending_at_area_edge_are_infeasible_not_forced(self):
        self.dialog.area_combo.setLayer(self.boundary)
        tight = _layer(f"Polygon?crs={CRS}", "area_justa", [((), "POLYGON((-40 -2,130 -2,130 502,-40 502,-40 -2))")])
        self.project.addMapLayer(tight)
        self.dialog.area_combo.setLayer(tight)
        self.dialog.preview()
        (preview,) = self.turn_layers()
        self.assertEqual({f["status"] for f in preview.getFeatures()}, {"INFEASIBLE_RADIUS"})
        self.assertTrue(all(f.geometry().isNull() for f in preview.getFeatures()))
        self.assertIn("não têm espaço", self.dialog.status.text())


if __name__ == "__main__":
    unittest.main()
