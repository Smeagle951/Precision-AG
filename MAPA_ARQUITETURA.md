# Mapa de Arquitetura - FortSmart Precision

## Arquitetura alvo

```text
Interface QGIS
    |
Casos de uso / servicos
    |
Algoritmos de Processing
    |
Motores de dominio
    |- core: CRS, geometria, tolerancias e metricas
    |- domain: plantio, pulverizacao, bordaduras, maquinas
    |- database: GeoPackage, migracoes e historico
    |- validators: CRS, geometria, atributos e pacotes
    |- exporters: perfis por formato/equipamento
    |
GeoPackage mestre + historico
    |
Validacao
    |
Pacote final + relatorio
```

## Estrutura criada

```text
plugin/fortsmart_precision/
    metadata.txt
    plugin.py
    provider.py
    algorithms/
    core/
    domain/
    database/
    exporters/
    validators/
    gui/
    resources/
    presets/

legacy/aap_gis_v2/
tests/
docs/
scripts/
```

## Mapeamento do legado para a arquitetura nova

| Legado | Papel atual | Destino provavel |
|---|---|---|
| `aap_part1_setup.py` | Cria estrutura e camadas base | `database/schema.py`, `database/project.py` |
| `aap_part2_importacao.py` | Importa e limpa dados | `algorithms/import_layer.py`, `validators/input.py`, `core/crs.py` |
| `aap_part3_bordadura.py` | Bordaduras | `domain/headlands.py`, `algorithms/create_headland.py` |
| `aap_part4_plantio.py` | Linhas de plantio | `domain/planting.py`, `algorithms/create_planting_lines.py` |
| `aap_part5_pulverizacao.py` | Pulverizacao | `domain/spraying.py`, `algorithms/create_spray_passes.py` |
| `aap_part6_relevo.py` | Relevo com SAGA/GDAL | `domain/terrain.py`, `algorithms/terrain_*` |
| `aap_part7_cruzamento.py` | Cruzamentos | `domain/analysis.py` |
| `aap_part8_exportacao.py` | Exportacao basica e pipeline | `exporters/`, `validators/export_package.py` |
| `aap_part8_exportacao_expanded.py` | Exportacao expandida e task | `exporters/`, `algorithms/export_package.py` |
| `aap_part9_linhas_agronomicas.py` | Linhas agronomicas avancadas | `domain/planting_advanced.py` |
| `aap_part10_zonas_dados.py` | Zonas de manejo | `domain/zones.py` |
| `aap_part11_conformidade.py` | Conformidade operacional | `validators/operation_conformance.py` |
| `aap_part12_isoxml_profissional.py` | ISOXML | `exporters/isoxml/` apos fases basicas |
| `aap_part13_motor_decisao.py` | Recomendacoes, API e dashboard | Separar dominio real de esqueletos externos |
| `aap_gis_interface_funcional.py` | Interface monolitica | `gui/` como referencia de telas |
| `AAP_GIS_Plugin/` | Plugin legado | Substituido por `plugin/fortsmart_precision` |

## Dependencias principais observadas

```text
aap_import.py
    -> aap_part1_setup
    -> aap_part2_importacao
    -> aap_part3_bordadura
    -> aap_part4_plantio
    -> aap_part5_pulverizacao
    -> aap_part6_relevo
    -> aap_part7_cruzamento
    -> aap_part8_exportacao_expanded
    -> aap_part9_linhas_agronomicas
    -> aap_part10_zonas_dados
    -> aap_part11_conformidade
    -> aap_part12_isoxml_profissional
    -> aap_part13_motor_decisao

aap_part8_exportacao_expanded.py
    -> aap_part2_importacao
    -> aap_part3_bordadura
    -> aap_part4_plantio
    -> aap_part5_pulverizacao
    -> aap_part6_relevo opcional
    -> exportar_para_shapefile

aap_simple_api.py
    -> tenta orquestrar partes 1,2,3,4,5,8,9
    -> atualmente inconsistente com assinaturas reais
```

## Fronteiras obrigatorias

- GUI nao executa calculo geometrico complexo.
- Algoritmo Processing declara entradas, saidas, erros e chama servicos.
- Core valida CRS antes de area/distancia/buffer/offset.
- Exportador nunca altera dado mestre.
- Validador informa erro; nao corrige silenciosamente erro critico.

## Componentes iniciados da importacao

| Componente | Arquivo | Responsabilidade |
|---|---|---|
| Modelo de relatorio | `plugin/fortsmart_precision/models/input_report.py` | Estruturar inspecao, validacao e resultado de importacao |
| Inspetor | `plugin/fortsmart_precision/io/input_inspector.py` | Examinar arquivo sem alterar/importar |
| Validador | `plugin/fortsmart_precision/validators/input_validator.py` | Classificar entrada como `VALID`, `VALID_WITH_WARNINGS` ou `INVALID` |
| Servico de importacao | `plugin/fortsmart_precision/io/import_service.py` | Copiar original, registrar fonte/operacao/validacoes e gravar derivado inicial |
| Algoritmo de inspecao | `plugin/fortsmart_precision/algorithms/inspect_input.py` | Expor inspecao na Caixa de Processamento |
| Algoritmo de importacao | `plugin/fortsmart_precision/algorithms/import_field_boundary.py` | Expor importacao nao destrutiva na Caixa de Processamento |

## Componentes visuais iniciados

| Componente | Arquivo | Responsabilidade |
|---|---|---|
| Painel principal | `plugin/fortsmart_precision/gui/main_dock.py` | Mostrar projeto atual, camada ativa, avisos e acoes rapidas |
| Tela inicial | `plugin/fortsmart_precision/gui/start_page.py` | Mostrar acoes de criar/abrir projeto quando nenhum projeto esta aberto |
| Assistente de importacao | `plugin/fortsmart_precision/gui/import_wizard.py` | Importar camada ativa, camada aberta ou arquivo selecionado |
| Controlador de importacao | `plugin/fortsmart_precision/gui/controllers/import_controller.py` | Encapsular acesso ao QGIS, exportacao temporaria, simbologia e zoom |
| Widget de projeto | `plugin/fortsmart_precision/gui/widgets/project_status_widget.py` | Exibir estado do projeto |
| Widget de camada | `plugin/fortsmart_precision/gui/widgets/layer_summary_widget.py` | Exibir resumo da camada ativa/origem |
| Widget de validacao | `plugin/fortsmart_precision/gui/widgets/validation_results_widget.py` | Exibir erros e avisos em tabela |
| Entrada do plugin | `plugin/fortsmart_precision/plugin.py` | Registrar menu, toolbar, painel lateral e provider |

## Fluxo visual de importacao atual

```text
Camada ativa / camada aberta / arquivo
    |
ImportWizard
    |
ImportController
    |- inspeciona e valida
    |- abre camada com QGIS quando necessario
    |- exporta GeoJSON temporario no CRS mestre
    |- chama ImportService
    |- grava camada visual em GeoPackage do projeto
    |- aplica simbologia e zoom
    |
ImportService
    |- arquiva original em 00_ORIGINAIS
    |- registra fs_source_files, fs_operations, fs_validations
    |- gera relatorio HTML em 04_RELATORIOS
```
