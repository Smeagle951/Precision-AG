# -*- coding: utf-8 -*-
"""Arvore canonica FORTSMART - {talhao} / secoes, montada so a partir de layer_roles."""

from __future__ import annotations

from qgis.core import QgsLayerTreeGroup, QgsLayerTreeLayer, QgsProject, QgsVectorLayer

from ..core.layer_roles import (
    AUXILIARY_SECTION,
    CLASSIFIED_BY_PROPERTY,
    ORIGINAL_GROUP_PATH_PROPERTY,
    ORIGINAL_NAME_PROPERTY,
    PERSISTED_PROPERTY,
    PREVIEW_SECTION,
    PROJECT_GROUP_PREFIX,
    SECTION_ORDER,
    SOURCE_HEURISTIC,
    SOURCE_ROLE,
    canonical_field_name,
    canonical_project_group_name,
    classify_layer,
    definition_for_role,
    format_normalization_report,
    is_generated_layer,
    is_persisted_layer,
    is_temporary_preview,
    layer_field_id,
    layer_inventory,
    layer_role,
    normalization_summary,
    role_order_index,
    section_order_index,
    set_layer_role_properties,
    SOURCE_LAYER_ID_PROPERTY,
    STORAGE_PROPERTY,
    STRATEGY_PREVIEW_PROPERTY,
    TEMPORARY_PREVIEW_PROPERTY,
    TEMPORARY_PROPERTY,
    UPDATED_AT_PROPERTY,
    format_storage_report,
)
from ..core.persistence_manager import FortSmartPersistenceManager, PersistenceError

_STORAGE_KEYS = {
    STORAGE_PROPERTY,
    PERSISTED_PROPERTY,
    UPDATED_AT_PROPERTY,
    SOURCE_LAYER_ID_PROPERTY,
    TEMPORARY_PREVIEW_PROPERTY,
    TEMPORARY_PROPERTY,
    STRATEGY_PREVIEW_PROPERTY,
}


def _child_group(parent, name):
    return next(
        (child for child in parent.children() if isinstance(child, QgsLayerTreeGroup) and child.name() == name),
        None,
    )


def project_group(root, field_name, *, create=True):
    title = canonical_project_group_name(field_name)
    group = _child_group(root, title)
    if group is None and create:
        group = root.insertGroup(0, title)
    return group


def project_group_of(root, layer):
    """Grupo 'FORTSMART - ...' que contem a camada, ou None."""
    node = root.findLayer(layer.id()) if layer is not None else None
    parent = node.parent() if node is not None else None
    while isinstance(parent, QgsLayerTreeGroup) and parent is not root:
        if parent.name().startswith(PROJECT_GROUP_PREFIX):
            return parent
        parent = parent.parent()
    return None


def section_group(parent, section, *, create=True):
    group = _child_group(parent, section)
    if group is not None or not create:
        return group
    rank = section_order_index(section)
    position = 0
    for index, child in enumerate(parent.children()):
        if not isinstance(child, QgsLayerTreeGroup):
            continue
        if child.name() == PREVIEW_SECTION or section_order_index(child.name()) <= rank:
            position = index + 1
    return parent.insertGroup(position, section)


def preview_group(parent, *, create=True):
    group = _child_group(parent, PREVIEW_SECTION)
    if group is None and create:
        group = parent.insertGroup(0, PREVIEW_SECTION)
    return group


def _ordered_position(group, layer):
    rank = role_order_index(layer_role(layer))
    for index, child in enumerate(group.children()):
        if isinstance(child, QgsLayerTreeLayer) and child.layer() is not None:
            if role_order_index(layer_role(child.layer())) > rank:
                return index
    return len(group.children())


def insert_layer_ordered(group, layer):
    """Insere na posicao do role (CANONICAL_ROLE_ORDER); camadas sem role vao ao fim."""
    return group.insertLayer(_ordered_position(group, layer), layer)


def _move_node(node, target):
    """Move o no preservando visibilidade/estilo; a camada continua no projeto."""
    layer = node.layer()
    target.insertChildNode(_ordered_position(target, layer), node.clone())
    node.parent().removeChildNode(node)
    return layer.name()


def remove_group_if_empty(group):
    parent = group.parent() if group is not None else None
    if parent is not None and not group.children():
        parent.removeChildNode(group)


def prune_empty_sections(parent):
    for child in list(parent.children()):
        if isinstance(child, QgsLayerTreeGroup) and (
            child.name() in SECTION_ORDER or child.name() == PREVIEW_SECTION
        ):
            remove_group_if_empty(child)


def generated_layers_for_role(project, role, field_name, *, include_temporary=False):
    """Camadas geradas pelo plugin com o role no talhao (substituiveis sem perguntar)."""
    field_id = canonical_field_name(field_name)
    root = project.layerTreeRoot()
    group = project_group(root, field_name, create=False)
    found = []
    for layer in project.mapLayers().values():
        if layer_role(layer) != role or not is_generated_layer(layer):
            continue
        if is_temporary_preview(layer) and not include_temporary:
            continue
        owner = layer_field_id(layer)
        if owner == field_id or (not owner and group is not None and group.findLayer(layer.id()) is not None):
            found.append(layer)
    return found


def _group_path(node, root):
    names = []
    parent = node.parent()
    while isinstance(parent, QgsLayerTreeGroup) and parent is not root:
        names.append(parent.name())
        parent = parent.parent()
    return "/" + "/".join(reversed(names))


def _move_to_auxiliaries(root, node, parent):
    """Original do usuario: guarda de onde veio e vai para 90_AUXILIARES."""
    layer = node.layer()
    if not layer.customProperty(ORIGINAL_GROUP_PATH_PROPERTY):
        layer.setCustomProperty(ORIGINAL_GROUP_PATH_PROPERTY, _group_path(node, root))
    return _move_node(node, section_group(parent, AUXILIARY_SECTION))


def move_layers_to_auxiliaries(root, parent, layers):
    """Originais soltos na raiz vao para 90_AUXILIARES; dados e nome intactos."""
    moved = []
    for layer in layers:
        if layer is None:
            continue
        node = root.findLayer(layer.id())
        if node is None or node.parent() is not root:
            continue
        moved.append(_move_to_auxiliaries(root, node, parent))
    return moved


def in_preview_group(root, layer):
    node = root.findLayer(layer.id())
    parent = node.parent() if node is not None else None
    return isinstance(parent, QgsLayerTreeGroup) and parent.name() == PREVIEW_SECTION


def copy_layer_presentation(source, target):
    """Estilo, rotulos, opacidade, nome e propriedades do usuario passam para a camada persistida."""
    if source.geometryType() == target.geometryType() and source.renderer() is not None:
        target.setRenderer(source.renderer().clone())
    labeling = source.labeling()
    if labeling is not None:
        target.setLabeling(labeling.clone())
    target.setLabelsEnabled(source.labelsEnabled())
    target.setOpacity(source.opacity())
    target.setName(source.name())
    for key in source.customPropertyKeys():
        if key not in _STORAGE_KEYS:
            target.setCustomProperty(key, source.customProperty(key))


def publish_persisted(project, source, persisted, *, reused, field_name, definition):
    """Coloca a camada do GPKG na secao do role e remove o no em memoria.

    Camada reaproveitada (ja apontava para a tabela) mantem estilo e nome do
    usuario; qualquer outra camada gerada com o mesmo role no talhao sai do projeto.
    """
    root = project.layerTreeRoot()
    old_node = root.findLayer(source.id()) if project.mapLayer(source.id()) is not None else None
    visible = old_node.itemVisibilityChecked() if old_node is not None else True
    if not reused:
        keep_name = layer_role(source) == definition.role and not is_temporary_preview(source)
        copy_layer_presentation(source, persisted)
        set_layer_role_properties(persisted, definition, field_name=field_name)
        if not keep_name:
            persisted.setName(definition.display_name)
        project.addMapLayer(persisted, False)
    node = root.findLayer(persisted.id())
    if node is None:
        section = section_group(project_group(root, field_name), definition.section)
        node = insert_layer_ordered(section, persisted)
        node.setItemVisibilityChecked(visible)
    node.setCustomProperty("showFeatureCount", True)
    stale = [
        layer.id()
        for layer in generated_layers_for_role(project, definition.role, field_name)
        if layer.id() != persisted.id() and not in_preview_group(root, layer)
    ]
    if stale:
        project.removeMapLayers(stale)
    return persisted


def field_name_for_layer(project, layer):
    """Talhao de uma camada de entrada: metadado, grupo FORTSMART ou None."""
    if layer is None:
        return None
    owner = project_group_of(project.layerTreeRoot(), layer)
    return layer_field_id(layer) or (owner.name() if owner is not None else None)


def place_generated_result(project, layer, definition, field_name):
    """Resultado gerado (ex.: saida do Processing): role, nome canonico e secao do talhao.

    Resultados anteriores ainda nao salvos do mesmo role/talhao saem; o salvo
    (GPKG) fica ate o usuario persistir o novo.
    """
    set_layer_role_properties(layer, definition, field_name=field_name)
    layer.setName(definition.display_name)
    if not field_name:
        return layer
    root = project.layerTreeRoot()
    if project.mapLayer(layer.id()) is None:
        project.addMapLayer(layer, False)
    section = section_group(project_group(root, field_name), definition.section)
    node = root.findLayer(layer.id())
    if node is None:
        insert_layer_ordered(section, layer)
    elif node.parent() is not section:
        _move_node(node, section)
    stale = [
        other.id()
        for other in generated_layers_for_role(project, definition.role, field_name)
        if other.id() != layer.id()
        and not is_persisted_layer(other)
        and not in_preview_group(root, other)
    ]
    if stale:
        project.removeMapLayers(stale)
    return layer


def persist_generated_memory_layers(project=None, manager=None):
    """Migracao: camadas geradas em memoria vao para o GPKG do seu talhao.

    Previews (SIM_PREVIEW / temporarias), camadas externas e do usuario sao ignoradas.
    """
    project = project or QgsProject.instance()
    manager = manager or FortSmartPersistenceManager(project)
    manager.get_project_storage_root()
    root = project.layerTreeRoot()
    entries = []
    ignored = 0
    for layer_id in list(project.mapLayers()):
        layer = project.mapLayer(layer_id)
        if not isinstance(layer, QgsVectorLayer) or not is_generated_layer(layer):
            continue
        if is_temporary_preview(layer) or in_preview_group(root, layer):
            ignored += 1
            continue
        if layer.providerType() != "memory":
            continue
        definition = definition_for_role(layer_role(layer))
        if definition is None:
            continue
        owner = project_group_of(root, layer)
        field_name = layer_field_id(layer) or (owner.name() if owner is not None else "")
        name = layer.name()
        count = layer.featureCount()
        entry = {"field_id": canonical_field_name(field_name) if field_name else "", "name": name, "features": count}
        try:
            result = manager.persist_layer(layer, definition, field_name)
            publish_persisted(
                project, layer, result.layer, reused=result.reused_layer, field_name=field_name, definition=definition
            )
            entry.update(status=result.status, message=result.message, features=result.feature_count)
        except PersistenceError as exc:
            entry.update(status=exc.code, message=str(exc))
        entries.append(entry)
    return {"entries": entries, "ignored_previews": ignored, "text": format_storage_report(entries, ignored_previews=ignored)}


def normalize_legacy_project_layers(project=None):
    """Classifica camadas antigas e as coloca na arvore canonica, sem tocar geometria.

    - criada pelo plugin (metadado atual ou legado): recebe o role e vai para a
      secao canonica do seu grupo FORTSMART;
    - camada do usuario: nunca recebe role nem nome novo; se estiver solta num grupo
      FORTSMART, ou na raiz com nome de um talhao existente, vai para 90_AUXILIARES;
    - demais: so aparecem no relatorio.
    """
    project = project or QgsProject.instance()
    root = project.layerTreeRoot()
    moved = []
    for layer in list(project.mapLayers().values()):
        node = root.findLayer(layer.id())
        if node is None or is_temporary_preview(layer):
            continue
        parent = node.parent()
        parent_name = parent.name() if isinstance(parent, QgsLayerTreeGroup) and parent is not root else ""
        if parent_name in (AUXILIARY_SECTION, PREVIEW_SECTION):
            continue
        owner = project_group_of(root, layer)
        if owner is None:
            if parent is root and not is_generated_layer(layer) and canonical_field_name(layer.name()) != "PROJETO":
                field_group = project_group(root, layer.name(), create=False)
                if field_group is not None:
                    moved.append(_move_to_auxiliaries(root, node, field_group))
            continue
        if not is_generated_layer(layer):
            if parent is owner:
                moved.append(_move_to_auxiliaries(root, node, owner))
            continue
        role, source = classify_layer(layer)
        if not role or source == SOURCE_HEURISTIC:
            continue
        definition = definition_for_role(role)
        if source != SOURCE_ROLE:
            layer.setCustomProperty(ORIGINAL_NAME_PROPERTY, layer.name())
            layer.setCustomProperty(CLASSIFIED_BY_PROPERTY, source)
            set_layer_role_properties(layer, definition, field_name=owner.name())
        if parent is owner or (parent_name in SECTION_ORDER and parent_name != definition.section):
            moved.append(_move_node(node, section_group(owner, definition.section)))
    entries = layer_inventory(project.mapLayers().values())
    summary = normalization_summary(entries)
    return {
        "summary": summary,
        "moved": moved,
        "entries": entries,
        "text": format_normalization_report(summary, moved=tuple(moved)),
    }
