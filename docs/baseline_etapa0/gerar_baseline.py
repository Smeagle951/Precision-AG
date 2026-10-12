"""Linha de base da Etapa 0: hashes dos pacotes exportados pelo FortSmart Precision Ag.

Uso (Python do QGIS):
    python-qgis-ltr.bat gerar_baseline.py <pasta_plugins_ag> <saida.json>

Cada talhao de exemplo e exportado duas vezes por perfil. Arquivos de texto sao
normalizados (UUIDs e datas viram marcadores) antes do hash; arquivos cujo hash
muda entre as duas execucoes ficam marcados como nao deterministicos.
"""

import hashlib
import json
import re
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

plugin_root, out_json = sys.argv[1], sys.argv[2]
sys.path.insert(0, plugin_root)
from qgis.core import QgsApplication, QgsProject, QgsVectorLayer  # noqa: E402

app = QgsApplication([], False)
app.initQgis()

from fortsmart_gs3_import.export_collector import collect_export_bundles  # noqa: E402
from fortsmart_gs3_import.field_group_export import export_name_map, group_export_layers  # noqa: E402
from fortsmart_gs3_import.jd_guidance_plan import (  # noqa: E402
    JohnDeereGuidanceOptions, pass_layer_audit, source_pass_counts,
)
from fortsmart_gs3_import.monitor_registry import export_fields  # noqa: E402

BASE = Path(r"C:\Users\fortu\Desktop\IGUACU\MAPAS FERRADURA  JF\T 6 B C\th-6-a-b")
FIELDS = ("talhao-6-a", "talhao-6-b", "th-6-a_b")
NAMES = ["15_passadas_bordadura", "12_passadas_plantio", "03_bordadura", "02_limite_interno", "01_limite_externo"]
PROFILES = ("john_deere_dual", "sendto2020")
# Aceita "_" porque o id de camada do QGIS (nome_<uuid>) muda a cada processo.
UUID = re.compile(r"[0-9a-fA-F]{8}[-_]?[0-9a-fA-F]{4}[-_]?[0-9a-fA-F]{4}[-_]?[0-9a-fA-F]{4}[-_]?[0-9a-fA-F]{12}")
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?")


def load(folder):
    project = QgsProject.instance()
    project.clear()
    group = project.layerTreeRoot().addGroup(folder)
    for name in NAMES:
        layer = QgsVectorLayer(str(BASE / folder / f"{name}.gpkg"), name, "ogr")
        project.addMapLayer(layer, False)
        group.addLayer(layer)
    layers = [layer for layer in project.mapLayers().values() if isinstance(layer, QgsVectorLayer)]
    groups = [g for g in group_export_layers(layers, project.layerTreeRoot()) if g.label == folder]
    names = export_name_map(groups, {g.key: g.label for g in groups})
    audit = []
    bundles = collect_export_bundles(
        only_selected_layers=True, selected_layer_ids=set(names), field_names_by_layer_id=names, audit=audit
    )
    return bundles, audit


def digest(path: Path) -> str:
    payload = path.read_bytes()
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return hashlib.sha256(payload).hexdigest()
    text = STAMP.sub("<data>", UUID.sub("<uuid>", text))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def export_once(bundles, audit, profile):
    options = JohnDeereGuidanceOptions(include_planting_passes=True, include_border_passes=True)
    options = replace(options, source_pass_counts=source_pass_counts(audit),
                      collection_audit=tuple(pass_layer_audit(audit)))
    files = {}
    with tempfile.TemporaryDirectory(prefix="fs-baseline-") as temp_dir:
        root = Path(temp_dir)
        kwargs = {"guidance_options": options} if profile == "john_deere_dual" else {}
        try:
            export_fields(bundles, root, profile_id=profile, **kwargs)
        except Exception as exc:  # registrado na linha de base, nao escondido
            return {"error": f"{type(exc).__name__}: {exc}"}
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            key = UUID.sub("<uuid>", str(path.relative_to(root)).replace("\\", "/"))
            files.setdefault(key, []).append(digest(path))
    return {key: sorted(values) for key, values in files.items()}


result = {"fields": {}}
for folder in FIELDS:
    bundles, audit = load(folder)
    result["fields"][folder] = {}
    for profile in PROFILES:
        first = export_once(bundles, audit, profile)
        second = export_once(bundles, audit, profile)
        if "error" in first:
            result["fields"][folder][profile] = first
            continue
        result["fields"][folder][profile] = {
            key: {"sha256": first[key], "deterministic": first[key] == second.get(key)}
            for key in sorted(first)
        }
Path(out_json).write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
QgsProject.instance().clear()
app.exitQgis()
