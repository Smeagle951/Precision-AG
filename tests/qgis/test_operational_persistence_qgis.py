# -*- coding: utf-8 -*-

from __future__ import annotations

import os

from qgis.core import QgsApplication, QgsProject

from plugin.fortsmart_precision.core.operational_persistence import OperationalPersistenceStore
from plugin.fortsmart_precision.core.persistence_manager import FortSmartPersistenceManager
from plugin.fortsmart_precision.gui.operational_preview import build_operational_preview_layers
from tests.unit.test_operational_contract import _generation

_APP = None


def _setup_qgis():
    global _APP
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if QgsApplication.instance() is None:
        _APP = QgsApplication([], True)
        _APP.initQgis()


def test_real_geopackage_reopens_active_generation_and_preview(tmp_path):
    _setup_qgis()
    project = QgsProject.instance()
    project.clear()
    project.write(str(tmp_path / "operacao.qgz"))
    manager = FortSmartPersistenceManager(project)
    path = manager.ensure_geopackage(manager.get_field_storage_path("Talhao 12"))

    store = OperationalPersistenceStore(path)
    saved = store.save_generation(_generation("QGIS_G1"))
    reopened = OperationalPersistenceStore(path).load_active("talhao_12")

    assert reopened == saved
    layers = build_operational_preview_layers(reopened)
    by_role = {definition.role: layer for definition, layer in layers}
    assert by_role["WORK_PATH"].featureCount() == 1
    assert by_role["TIRE_TRACK"].featureCount() == 1
    assert by_role["SHUTOFF"].featureCount() == 1
    assert by_role["SHUTOFF"].crs().authid() == "EPSG:31981"
    assert by_role["SHUTOFF"].customProperty("fortsmart_generation_id") == "QGIS_G1"
    project.clear()
