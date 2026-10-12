"""Patch cirurgico: corte das linhas EXISTENTES por obstaculos (10 testes obrigatorios).

Os testes puros rodam em qualquer Python; os marcados com HAS_QGIS rodam no
Python do QGIS 3.44 (algoritmo, preview repetido e salvar uma vez).
"""

import ast
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from shapely.geometry import LineString, Point, box

from plugin.fortsmart_precision.core import parallel_pass_engine, precision_lines_engine
from plugin.fortsmart_precision.core.longitudinal_cut_engine import ObstacleInput
from plugin.fortsmart_precision.core.obstacle_border_pass_engine import (
    cut_work_line_records,
    ground_gaps,
    simulate_obstacle_cut,
)
from plugin.fortsmart_precision.core.planting_line_cut_engine import (
    BOUNDARY_AS_OBSTACLE_MESSAGE,
    SAME_LAYER_MESSAGE,
    SAME_LINES_AND_OBSTACLES_MESSAGE,
    PlantingLineCutError,
    cut_line_by_station_gaps,
    line_id_field,
    line_id_for,
    line_number_field,
    obstacle_layer_priority,
    spatial_line_numbers,
    substring_by_station,
    validate_line_layer_choice,
    validate_obstacle_layer_choice,
)
from plugin.fortsmart_precision.domain.operation_simulation import (
    MachineReferenceType,
    MachineWorkGeometry,
    ObstacleBorderMode,
    ObstacleStrategy,
)

try:
    from qgis.core import QgsApplication

    HAS_QGIS = True
except ImportError:
    HAS_QGIS = False

CRS = "EPSG:31981"
PLUGIN_DIR = Path(__file__).resolve().parents[2] / "plugin" / "fortsmart_precision"


def machine(width=20.0, offset=-18.0):
    return MachineWorkGeometry(
        work_width_m=width,
        reference_type=MachineReferenceType.GNSS_ANTENNA,
        reference_to_working_line_longitudinal_m=offset,
        border_mode=ObstacleBorderMode.ONE_IMPLEMENT_PASS,
    )


def family(count, length=1000.0, spacing=20.0, x0=0.0):
    return [(f"L{n}", [(x0, n * spacing), (x0 + length, n * spacing)]) for n in range(1, count + 1)]


def run_cut(passes, obstacles, **kwargs):
    sim = simulate_obstacle_cut(
        passes, obstacles, machine(), crs_authid=CRS, safety_margin_m=0.5,
        strategy=ObstacleStrategy.CUT_ONLY, **kwargs,
    )
    return sim, {record["pass_id"]: record for record in cut_work_line_records(sim)}


def length(points):
    return LineString(points).length


class MandatoryPureTests(unittest.TestCase):
    def test_01_hundred_lines_without_obstacles_are_identical(self):
        passes = family(100)
        _sim, records = run_cut(passes, [ObstacleInput("far", Point(5000, 5000), 0.5)])
        self.assertEqual(len(records), 100)
        for pass_id, points in passes:
            record = records[pass_id]
            self.assertFalse(record["affected"])
            self.assertEqual(record["segments"], [tuple(points)])
            self.assertEqual(f"{length(record['segments'][0]):.2f}", "1000.00")

    def test_02_one_post_cuts_line_10_into_two_segments_same_line(self):
        passes = family(20)
        post_y = 10 * 20.0
        _sim, records = run_cut(passes, [ObstacleInput("P1", Point(500, post_y), 0.5)])
        numbers = spatial_line_numbers({key: tuple(points) for key, points in reversed(passes)})
        self.assertEqual(numbers["L10"], 10)
        self.assertEqual(len(records["L10"]["segments"]), 2)
        for key, points in passes:
            if key != "L10":
                self.assertEqual(records[key]["segments"], [tuple(points)], key)
        first, second = records["L10"]["segments"]
        self.assertEqual(first[0], (0.0, post_y))
        self.assertEqual(second[-1], (1000.0, post_y))
        # so a zona do poste (raio 0,5 + margem 0,5); a largura de 20 m nao entra
        self.assertAlmostEqual(first[-1][0], 499.0, delta=0.06)
        self.assertAlmostEqual(second[0][0], 501.0, delta=0.06)

    def test_03_two_posts_three_segments_one_logical_line(self):
        passes = family(20)
        y = 20 * 20.0
        _sim, records = run_cut(
            passes, [ObstacleInput("P1", Point(300, y), 0.5), ObstacleInput("P2", Point(700, y), 0.5)]
        )
        segments = records["L20"]["segments"]
        self.assertEqual(len(segments), 3)
        self.assertEqual(len([r for r in records.values() if r["pass_id"] == "L20"]), 1)
        xs = [x for segment in segments for x, _y in segment]
        self.assertEqual(xs, sorted(xs))

    def test_04_line_outside_field_without_obstacle_is_whole(self):
        points = [(-300.0, 0.0), (1300.0, 0.0)]
        field = box(0, -50, 1000, 50)
        _sim, records = run_cut([("L1", points)], [], field_polygon=field)
        self.assertEqual(records["L1"]["segments"], [tuple(points)])

    def test_05_obstacle_inside_field_keeps_parts_outside_field(self):
        points = [(-200.0, 0.0), (1200.0, 0.0)]
        field = box(0, -50, 1000, 50)
        _sim, records = run_cut(
            [("L1", points)], [ObstacleInput("P1", Point(500, 0), 0.5)], field_polygon=field
        )
        first, second = records["L1"]["segments"]
        self.assertEqual(first[0], (-200.0, 0.0))
        self.assertEqual(second[-1], (1200.0, 0.0))
        self.assertAlmostEqual(length(first) + length(second), 1400.0 - 2.0, delta=0.1)

    def test_06_boundary_as_obstacle_is_rejected(self):
        self.assertIsNone(obstacle_layer_priority("Boundary"))
        self.assertEqual(
            validate_obstacle_layer_choice(
                obstacle_layer_id="b2", obstacle_layer_name="Boundary - talhao_11",
                field_layer_id="f1", geometry_kind="polygon",
            ),
            BOUNDARY_AS_OBSTACLE_MESSAGE,
        )
        self.assertEqual(
            validate_obstacle_layer_choice(
                obstacle_layer_id="f1", obstacle_layer_name="Flag", field_layer_id="f1",
                geometry_kind="point",
            ),
            SAME_LAYER_MESSAGE,
        )

    def test_09_numbering_one_to_five_kept_line_3_two_segments(self):
        passes = family(5)
        shuffled = passes[:]
        random.Random(7).shuffle(shuffled)
        numbers = spatial_line_numbers({key: tuple(points) for key, points in shuffled})
        self.assertEqual([numbers[f"L{n}"] for n in range(1, 6)], [1, 2, 3, 4, 5])
        _sim, records = run_cut(shuffled, [ObstacleInput("P1", Point(500, 60), 0.5)])
        counts = {numbers[key]: len(record["segments"]) for key, record in records.items()}
        self.assertEqual(counts, {1: 1, 2: 1, 3: 2, 4: 1, 5: 1})

    def test_10_no_generator_function_is_called(self):
        def forbidden(*_args, **_kwargs):
            raise AssertionError("o corte nao pode chamar o gerador de linhas")

        with mock.patch.object(parallel_pass_engine, "generate_parallel_passes", forbidden), \
                mock.patch.object(precision_lines_engine, "run_precision_lines", forbidden):
            _sim, records = run_cut(family(5), [ObstacleInput("P1", Point(500, 60), 0.5)])
        self.assertEqual(len(records), 5)
        generators = {"parallel_pass_engine", "precision_lines_engine", "agricultural_lines_engine"}
        for relative in (
            "core/obstacle_border_pass_engine.py",
            "core/longitudinal_cut_engine.py",
            "core/planting_line_cut_engine.py",
            "algorithms/simulate_obstacle_border_cut.py",
            "gui/planting_line_cut_dialog.py",
        ):
            tree = ast.parse((PLUGIN_DIR / relative).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotIn(node.module.split(".")[-1], generators, relative)


class CutHelpersTest(unittest.TestCase):
    def test_gap_outside_line_returns_exact_input(self):
        path = ((0.0, 0.0), (10.0, 0.0), (20.0, 5.0))
        self.assertEqual(cut_line_by_station_gaps(path, [(-30.0, -5.0), (40.0, 50.0)]), [path])
        self.assertEqual(cut_line_by_station_gaps(path, []), [path])

    def test_cut_keeps_direction_and_source_vertices(self):
        forward = ((0.0, 0.0), (10.0, 0.0), (30.0, 0.0))
        pieces = cut_line_by_station_gaps(forward, [(12.0, 18.0)])
        self.assertEqual(pieces, [((0.0, 0.0), (10.0, 0.0), (12.0, 0.0)), ((18.0, 0.0), (30.0, 0.0))])
        backward = tuple(reversed(forward))
        pieces = cut_line_by_station_gaps(backward, [(12.0, 18.0)])
        self.assertEqual(pieces, [((30.0, 0.0), (18.0, 0.0)), ((12.0, 0.0), (10.0, 0.0), (0.0, 0.0))])

    def test_overlapping_gaps_merge_and_tiny_pieces_drop(self):
        path = ((0.0, 0.0), (100.0, 0.0))
        pieces = cut_line_by_station_gaps(path, [(10.0, 30.0), (25.0, 40.0), (40.005, 50.0)])
        self.assertEqual(pieces, [((0.0, 0.0), (10.0, 0.0)), ((50.0, 0.0), (100.0, 0.0))])

    def test_cut_requires_two_vertices(self):
        with self.assertRaises(PlantingLineCutError):
            cut_line_by_station_gaps(((0.0, 0.0),), [])

    def test_substring_by_station(self):
        path = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0))
        self.assertEqual(substring_by_station(path, 5.0, 15.0), ((5.0, 0.0), (10.0, 0.0), (10.0, 5.0)))
        self.assertEqual(substring_by_station(path, 5.0, 5.0), ())

    def test_ground_gaps_apply_offset_to_raised_interval(self):
        sim, _records = run_cut([("L1", [(0, 0), (300, 0)])], [ObstacleInput("P1", Point(150, 0), 0.5)])
        (start, end), = ground_gaps(sim.passes[0], sim.geometry)
        self.assertAlmostEqual(start, 149.0, delta=0.06)
        self.assertAlmostEqual(end, 151.0, delta=0.06)

    def test_spatial_numbers_ignore_digitizing_direction(self):
        lines = {
            "a": ((0, 40), (100, 40)),
            "b": ((100, 0), (0, 0)),
            "c": ((0, 20), (100, 20)),
        }
        self.assertEqual(spatial_line_numbers(lines), {"b": 1, "c": 2, "a": 3})
        self.assertEqual(spatial_line_numbers({}), {})

    def test_line_fields_and_ids(self):
        self.assertEqual(line_number_field(["nome", "LINE_NO", "pass_id"]), "LINE_NO")
        self.assertEqual(line_number_field(["line_number", "line_no"]), "line_number")
        self.assertIsNone(line_number_field(["nome"]))
        self.assertEqual(line_id_field(["parent_line_id", "x"]), "parent_line_id")
        self.assertEqual(line_id_for(42), "L0042")
        self.assertEqual(line_id_for(-3), "L-0003")

    def test_lines_layer_cannot_be_obstacles_or_boundary(self):
        self.assertEqual(
            validate_line_layer_choice(line_layer_id="a", obstacle_layer_id="a"),
            SAME_LINES_AND_OBSTACLES_MESSAGE,
        )
        self.assertIsNotNone(
            validate_line_layer_choice(line_layer_id="a", obstacle_layer_id="b", line_layer_name="Boundary")
        )
        self.assertIsNone(
            validate_line_layer_choice(line_layer_id="a", obstacle_layer_id="b", line_layer_name="06_Passadas_Plantio")
        )


# ---------------------------------------------------------------- QGIS ----
_APP = None
_PROVIDER = None


def _qgis_setup():
    global _APP, _PROVIDER
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if QgsApplication.instance() is None:
        _APP = QgsApplication([], True)
        _APP.initQgis()
    plugins = Path(QgsApplication.prefixPath()) / "python" / "plugins"
    if str(plugins) not in sys.path:
        sys.path.append(str(plugins))
    from processing.core.Processing import Processing

    Processing.initialize()
    from plugin.fortsmart_precision.provider import FortSmartProvider

    registry = QgsApplication.processingRegistry()
    if registry.providerById("fortsmart_precision") is None:
        _PROVIDER = FortSmartProvider()
        registry.addProvider(_PROVIDER)


def _memory_lines(name, rows, *, fields=(("line_number", "int"), ("nome", "string"))):
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsVectorLayer

    spec = "&".join(f"field={field}:{kind}" for field, kind in fields)
    layer = QgsVectorLayer(f"LineString?crs={CRS}&{spec}" if fields else f"LineString?crs={CRS}", name, "memory")
    features = []
    for attributes, points in rows:
        feature = QgsFeature(layer.fields())
        feature.setAttributes(list(attributes))
        feature.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in points]))
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    return layer


def _memory_layer(uri, name, geometries):
    from qgis.core import QgsFeature, QgsGeometry, QgsVectorLayer

    layer = QgsVectorLayer(uri, name, "memory")
    features = []
    for wkt in geometries:
        feature = QgsFeature()
        feature.setGeometry(QgsGeometry.fromWkt(wkt))
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    return layer


def _five_lines(name="06_Passadas_Plantio", fields=(("line_number", "int"), ("nome", "string"))):
    rows = [((n, f"linha {n}") if fields else (), [(0.0, n * 20.0), (1000.0, n * 20.0)]) for n in (5, 2, 4, 1, 3)]
    return _memory_lines(name, rows, fields=fields)


@unittest.skipUnless(HAS_QGIS, "QGIS nao disponivel")
class AlgorithmIdentityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _qgis_setup()

    def run_algorithm(self, lines):
        import processing
        from qgis.core import QgsProcessingContext, QgsProcessingFeedback

        field = _memory_layer(f"Polygon?crs={CRS}", "Boundary", ["POLYGON((0 0,1000 0,1000 120,0 120,0 0))"])
        flag = _memory_layer(f"Point?crs={CRS}", "Flag", ["POINT(500 60)"])
        context = QgsProcessingContext()
        result = processing.run(
            "fortsmart_precision:simulate_obstacle_border_cut",
            {
                "PASSES": lines, "OBSTACLES": flag, "FIELD": field,
                "WORK_WIDTH": 20.0, "WORKING_OFFSET": -18.0, "OBSTACLE_RADIUS": 0.5,
                "SAFETY_MARGIN": 0.5, "SIM_WORK_LINES": "TEMPORARY_OUTPUT",
            },
            context=context, feedback=QgsProcessingFeedback(),
        )
        output = result["SIM_WORK_LINES"]
        if isinstance(output, str):
            output = context.getMapLayer(output)
        return output

    def test_numbering_inherited_and_uncut_geometry_identical(self):
        lines = _five_lines()
        output = self.run_algorithm(lines)
        features = list(output.getFeatures())
        self.assertEqual(len(features), 6)
        by_number = {}
        for feature in features:
            by_number.setdefault(feature["line_number"], []).append(feature)
        self.assertEqual(sorted(by_number), [1, 2, 3, 4, 5])
        self.assertEqual(len(by_number[3]), 2)
        self.assertEqual({f["parent_line_id"] for f in by_number[3]}, {"L0003"})
        self.assertEqual(sorted(f["segment_index"] for f in by_number[3]), [1, 2])
        self.assertEqual({f["nome"] for f in by_number[3]}, {"linha 3"})
        source = {f["line_number"]: f.geometry() for f in lines.getFeatures()}
        for number in (1, 2, 4, 5):
            (feature,) = by_number[number]
            self.assertEqual(feature.geometry().asWkt(6), source[number].asWkt(6))
            self.assertEqual(f"{feature.geometry().length():.2f}", "1000.00")

    def test_numbering_created_by_spatial_order_when_absent(self):
        output = self.run_algorithm(_five_lines(fields=()))
        numbers = sorted(
            (f["line_number"], round(f.geometry().boundingBox().yMinimum())) for f in output.getFeatures()
        )
        self.assertEqual([n for n, _y in numbers], [1, 2, 3, 3, 4, 5])
        self.assertEqual([y for _n, y in numbers], [20, 40, 60, 60, 80, 100])


class _Canvas:
    def setExtent(self, *_):
        pass

    def refresh(self):
        pass


class _Iface:
    def __init__(self):
        from qgis.PyQt.QtWidgets import QMainWindow

        self.window = QMainWindow()

    def mainWindow(self):
        return self.window

    def activeLayer(self):
        return None

    def mapCanvas(self):
        return _Canvas()


class _SilentBox:
    @staticmethod
    def _quiet(*_args, **_kwargs):
        return None

    warning = critical = information = _quiet


@unittest.skipUnless(HAS_QGIS, "QGIS nao disponivel")
class DialogPreviewSaveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _qgis_setup()

    def setUp(self):
        from qgis.core import QgsProject

        from plugin.fortsmart_precision.gui import planting_line_cut_dialog as module

        self.module = module
        self.project = QgsProject.instance()
        self.project.clear()
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.project.setFileName(str(Path(self.tmp.name) / "fazenda.qgz"))
        self.storage = Path(self.tmp.name) / "fortsmart_data" / "Boundary" / "fortsmart_Boundary.gpkg"
        self.lines = _five_lines()
        self.field = _memory_layer(f"Polygon?crs={CRS}", "Boundary", ["POLYGON((0 0,1000 0,1000 120,0 120,0 0))"])
        self.flag = _memory_layer(f"Point?crs={CRS}", "Flag", ["POINT(500 60)"])
        for layer in (self.field, self.flag, self.lines):
            self.project.addMapLayer(layer)
        self.box_patch = mock.patch.object(module, "QMessageBox", _SilentBox)
        self.box_patch.start()
        self.dialog = module.PlantingLineCutDialog(_Iface())
        self.dialog.lines_combo.setLayer(self.lines)
        self.dialog.field_combo.setLayer(self.field)
        self.dialog.obstacle_combo.setLayer(self.flag)
        geometry = self.dialog.work_geometry_box
        geometry.strategy_combo.setCurrentIndex(0)
        geometry.offset_spin.setValue(-18.0)

    def tearDown(self):
        self.dialog.reject()
        self.box_patch.stop()
        self.project.clear()
        self.tmp.cleanup()

    @staticmethod
    def sublayer_count(path):
        from qgis.core import QgsProviderRegistry

        return len(QgsProviderRegistry.instance().querySublayers(path))

    def cut_layers(self):
        return [
            layer for layer in self.project.mapLayers().values()
            if layer.customProperty("fortsmart_role", "") == "FINAL_WORK_PATH"
        ]

    def test_dialog_uses_scrollable_compact_layout(self):
        from qgis.PyQt.QtWidgets import QApplication, QScrollArea

        self.dialog.treatment_box.detour_radio.setChecked(True)
        self.dialog.resize(620, 480)
        self.dialog.show()
        QApplication.processEvents()

        self.assertIsInstance(self.dialog.content_scroll, QScrollArea)
        self.assertTrue(self.dialog.content_scroll.widgetResizable())
        self.assertEqual(self.dialog.treatment_box.params.layout().columnCount(), 4)
        self.assertLess(self.dialog.treatment_box.height(), 430)
        self.assertLessEqual(self.dialog.treatment_box.minimumSizeHint().width(), 620)
        self.assertTrue(self.dialog.close_btn.isVisible())
        self.assertTrue(self.dialog.status.isVisible())
        self.assertGreater(
            self.dialog.content_scroll.verticalScrollBar().maximum(), 0
        )
        self.assertLessEqual(self.dialog.width(), 820)
        self.assertLessEqual(self.dialog.height(), 760)

    def border_work_layers(self):
        return [
            layer for layer in self.project.mapLayers().values()
            if layer.customProperty("fortsmart_role", "") == "HEADLAND_WORK_PATH"
        ]

    def test_07_preview_ten_times_keeps_one_preview(self):
        for _ in range(10):
            self.dialog.preview()
        self.assertTrue(self.dialog.preview_valid)
        self.assertEqual(len(self.cut_layers()), 1)
        group = self.project.layerTreeRoot().findGroup(self.module.SIM_GROUP_NAME)
        names = [child.name() for child in group.children()]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("31_Linhas_Finais", names)
        self.assertIn("32_Work_Off", names)
        self.assertIn("33_Work_On", names)
        final = self.dialog.sim_layers_by_key["SIM_WORK_LINES"]
        self.assertEqual(final.customProperty("fortsmart_role"), "FINAL_WORK_PATH")
        self.assertIn("fortsmart_role", final.fields().names())
        self.assertEqual(
            {feature["fortsmart_role"] for feature in final.getFeatures()},
            {"FINAL_WORK_PATH"},
        )
        self.assertEqual(len(self.project.mapLayers()), 3 + len(self.dialog.sim_layer_ids))

    def test_radial_mode_keeps_numbering_and_ignores_field_limit(self):
        outside = _memory_layer(f"Point?crs={CRS}", "Flag", ["POINT(500 60)", "POINT(1200 60)"])
        self.project.addMapLayer(outside)
        self.dialog.obstacle_combo.setLayer(outside)
        self.dialog.work_geometry_box.strategy_combo.setCurrentIndex(2)
        self.dialog.preview()
        layer = self.project.mapLayer(self.dialog.safe_layer_id)
        report = self.dialog.last_report
        self.assertEqual(report["obstacle_count"], 2)
        self.assertEqual(report["obstacles_inside_field"], 1)
        self.assertFalse(report["clipped_by_field"])
        self.assertEqual(report["output_logical_line_count"], 5)
        rows = [(f["line_number"], f["segment_index"], f["parent_line_id"]) for f in layer.getFeatures()]
        self.assertEqual(sorted(n for n, _s, _p in rows), [1, 2, 3, 3, 4, 5])
        self.assertEqual(sorted(s for n, s, _p in rows if n == 3), [1, 2])
        self.assertEqual({p for n, _s, p in rows if n == 3}, {"L0003"})

    def test_field_as_obstacle_blocks_preview_and_save(self):
        self.dialog.obstacle_combo.setLayer(self.field)
        self.assertFalse(self.dialog.preview_btn.isEnabled())
        self.assertFalse(self.dialog.save_btn.isEnabled())

    def test_08_save_keeps_cut_lines_and_border_tractor_path(self):
        self.dialog.preview()
        self.dialog.save()
        self.dialog.save()
        self.assertEqual(len(self.cut_layers()), 1)
        saved = self.cut_layers()[0]
        self.assertEqual(saved.providerType(), "ogr")
        self.assertEqual(saved.featureCount(), 6)
        self.assertTrue(saved.labelsEnabled())
        self.assertEqual(saved.customProperty("fortsmart_storage"), "geopackage")
        path = str(self.storage)
        self.assertEqual(self.sublayer_count(path), 4)
        self.assertEqual(len(self.border_work_layers()), 1)
        border = self.border_work_layers()[0]
        self.assertEqual(border.name(), "35_Linhas_Bordadura")
        self.assertGreater(border.featureCount(), 0)
        self.assertTrue((self.storage.parent / "31_Linhas_Finais.validation.json").exists())
        self.assertFalse(self.dialog.save_btn.isEnabled())

        saved_id = saved.id()
        self.dialog.preview()
        self.dialog.save()
        self.assertEqual([layer.id() for layer in self.cut_layers()], [saved_id])
        self.assertEqual(len(self.border_work_layers()), 1)
        self.assertEqual(self.sublayer_count(path), 4)

        self.dialog.preview()
        self.dialog.save()
        self.assertEqual([layer.name() for layer in self.cut_layers()], ["31_Linhas_Finais"])
        self.assertEqual([layer.name() for layer in self.border_work_layers()], ["35_Linhas_Bordadura"])

    def test_cut_preview_stays_in_memory_and_save_writes_31_32_33(self):
        for _ in range(3):
            self.dialog.preview()
        self.assertFalse(self.storage.exists())
        self.assertTrue(all(
            layer.providerType() == "memory"
            for layer in self.dialog.sim_layers_by_key.values()
        ))
        self.dialog.save()
        from plugin.fortsmart_precision.core.persistence_manager import FortSmartPersistenceManager

        tables = FortSmartPersistenceManager.table_names(self.storage)
        self.assertEqual(
            sorted(tables), ["31_Linhas_Finais", "32_Work_Off", "33_Work_On", "35_Linhas_Bordadura"]
        )
        events = [
            layer for layer in self.project.mapLayers().values()
            if layer.customProperty("fortsmart_role", "") in ("WORK_OFF", "WORK_ON")
        ]
        self.assertEqual(len(events), 2)
        self.assertTrue(all(layer.providerType() == "ogr" for layer in events))
        self.assertTrue(all(layer.featureCount() > 0 for layer in events))

    def test_unsaved_project_blocks_cut_save(self):
        self.project.setFileName("")
        self.dialog.preview()
        self.dialog.save()
        self.assertFalse(self.storage.exists())
        self.assertTrue(self.dialog.preview_valid)
        self.assertTrue(all(layer.providerType() == "memory" for layer in self.cut_layers()))

    def test_saved_outputs_go_to_canonical_sections_of_the_field(self):
        self.dialog.preview()
        self.dialog.save()
        root = self.project.layerTreeRoot()
        group = root.findGroup("FORTSMART - Boundary")
        self.assertIsNone(group.findGroup("SIM_PREVIEW"))
        for layer in self.cut_layers() + self.border_work_layers():
            node = root.findLayer(layer.id())
            self.assertEqual(node.parent().name(), "30_OPERACAO")
            self.assertEqual(node.parent().parent().name(), "FORTSMART - Boundary")
            self.assertEqual(layer.customProperty("fortsmart_field_id"), "Boundary")
            self.assertTrue(layer.customProperty("fortsmart_generated"))
            self.assertFalse(layer.customProperty("fortsmart_temporary_preview", False))
        operation = group.findGroup("30_OPERACAO")
        self.assertEqual(
            [child.name() for child in operation.children()],
            ["31_Linhas_Finais", "32_Work_Off", "33_Work_On", "35_Linhas_Bordadura"],
        )

    def test_save_replaces_role_only_in_same_field(self):
        from plugin.fortsmart_precision.core.layer_roles import set_layer_role_properties, simulation_role_definition

        definition = simulation_role_definition("SIM_WORK_LINES")
        other_field = _memory_layer(f"LineString?crs={CRS}", "31_Linhas_Finais", ["LINESTRING(0 0, 1 1)"])
        set_layer_role_properties(other_field, definition, field_name="talhao_outro")
        renamed = _memory_layer(f"LineString?crs={CRS}", "Linhas finais antigas", ["LINESTRING(0 0, 1 1)"])
        set_layer_role_properties(renamed, definition, field_name="Boundary")
        for layer in (other_field, renamed):
            self.project.addMapLayer(layer)
        other_id, renamed_id = other_field.id(), renamed.id()
        self.dialog.preview()
        self.dialog.save()
        self.assertIsNotNone(self.project.mapLayer(other_id))
        self.assertIsNone(self.project.mapLayer(renamed_id))
        same_field = [layer for layer in self.cut_layers() if layer.customProperty("fortsmart_field_id") == "Boundary"]
        self.assertEqual([layer.name() for layer in same_field], ["31_Linhas_Finais"])


if __name__ == "__main__":
    unittest.main()
