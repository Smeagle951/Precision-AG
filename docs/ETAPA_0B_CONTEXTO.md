# Etapa 0 / Subfase 0B — Catálogo lógico de camadas e contexto do projeto

**Data:** 2026-10-08
**Escopo:** FortSmart Precision Planner (`plugin/fortsmart_precision`). O FortSmart Precision Ag não foi alterado.
**Backup antes da 0B:** `plugin/backups/fortsmart_precision_antes_etapa0B_20261008_113236` (209 arquivos).

## 1. Decisão arquitetural

A estrutura 01 a 05 do painel é **só apresentação**. Nada foi renomeado, migrado, consolidado, duplicado ou removido: grupos `FORTSMART - <talhão>`, seções `00_`…`90_`, `SIM_PREVIEW`, nomes de camadas, tabelas GeoPackage e chaves de metadado continuam iguais. O serviço desta subfase só lê o projeto.

## 2. Arquivos

| Arquivo | Situação | Conteúdo |
|---|---|---|
| `plugin/fortsmart_precision/core/project_context.py` | novo | `ProjectContextService` e funções puras de contexto e diagnóstico |
| `plugin/fortsmart_precision/core/geometry_write_check.py` | novo | Classificação do tipo geométrico antes de gravar no GPKG |
| `plugin/fortsmart_precision/feature_flags.py` | alterado | Constantes antigas intactas; novas chaves em `QgsSettings` |
| `plugin/fortsmart_precision/core/persistence_manager.py` | alterado | Método novo `diagnose_geometry_write` (somente leitura) e avisos opcionais em `replace_role_layer` |
| `tests/unit/test_project_context.py` | novo | 29 testes sem QGIS |
| `tests/qgis/test_project_context_qgis.py` | novo | 9 testes com QGIS |
| `docs/baseline_etapa0/gerar_baseline.py` | alterado | Normaliza o id de camada do QGIS |
| `docs/baseline_etapa0/ag_2.9.20_export_hashes.json` | regenerado | Mesma linha de base, com a normalização corrigida |
| `CHANGELOG.md` | alterado | Entrada da 0B |

## 3. Contratos reutilizados (sem catálogo concorrente)

| Contrato | Origem | Uso no contexto |
|---|---|---|
| Papel, fonte e confiança | `layer_roles.classify_layer`, `CLASSIFICATION_ORDER` | Mesma ordem: role → internal_key → legacy_alias → display_name → heurística |
| Seção e nome canônico | `layer_roles.definition_for_role` (`LAYER_ROLES`, `SIMULATION_ROLES`, `HEADLAND_TURN_ROLE`) | `section` e `display_name` da camada |
| Identidade do talhão | `layer_roles.PROJECT_GROUP_PREFIX`, `canonical_field_name`, `layer_field_id` | Grupo `FORTSMART - <talhão>` e metadado `fortsmart_field_id` |
| Geração, preview, armazenamento | `is_generated_layer`, `is_temporary_preview`, `storage_kind` | Exibidos sem alteração |
| CRS | `core/crs.inspect_authid`, `SIRGAS_UTM_SOUTH_GUIDE` | Geográfico, métrico e padrão SIRGAS 2000 / UTM |
| Agrupamento do Precision Ag | `field_group_export._field_node` (Ag 2.9.20) | Replicado em `ag_field_group`; o teste QGIS compara com o código real do Ag |
| Papéis conhecidos pelo Ag | `canonical_project.ROLE_KIND_MAP` | Replicado em `AG_KNOWN_ROLES`; o teste QGIS compara com o Ag |

## 4. Identificação do talhão

`resolve_layer_field(root, layer)` devolve `RESOLVED`, `AMBIGUOUS` ou `UNRESOLVED`:

1. **RESOLVED:** a camada está dentro de um grupo `FORTSMART - <talhão>`, em qualquer profundidade. O talhão é `canonical_field_name(nome do grupo)`.
2. **AMBIGUOUS:** a camada está num grupo FortSmart, mas `fortsmart_field_id` indica outro talhão. Os dois aparecem como candidatos e nenhum é escolhido.
3. **UNRESOLVED:** a camada está fora de grupo FortSmart (raiz, grupo do usuário, árvore de import do Ag). Os candidatos vêm do metadado e do grupo mais próximo, nunca do nome da camada.

No serviço, `set_explicit_field` só aceita talhões que já existem como grupo. A escolha fica em memória, não vai para o projeto e vale sobre a camada ativa; se a camada ativa for de outro talhão, aparece `EXPLICIT_FIELD_DIFFERS_FROM_LAYER`. Sem camada ativa nem escolha, o contexto fica `UNRESOLVED`, lista os talhões existentes e emite `FIELD_NOT_SELECTED`, mesmo havendo um único talhão.

Casos cobertos pelos testes:
- `01_Limite_Externo` solto na raiz: não vira talhão, não cria grupo nem GPKG.
- `Todos — Limites` do import do Ag: sem talhão, sem grupo no Ag.
- Grupo `TL-12` do import do Ag: só candidato.

**Fazenda:** vem apenas dos atributos `fazenda`/`farm` das camadas do talhão. Se houver um único valor, fica resolvida; mais de um valor gera `FARM_AMBIGUOUS`; sem atributo, `FARM_NOT_RECORDED`. O Planner não grava a fazenda no projeto QGIS: o nome digitado no "Novo projeto" do dock vai para `fortsmart_project.json` (`property_name`) e para `fs_properties` no GPKG mestre da pasta escolhida no dock, que não está ligada ao `.qgz`. Por isso a fazenda não é deduzida dessa pasta.

## 5. Diagnósticos

Nenhum diagnóstico corrige nada.

| Código | Severidade | Quando |
|---|---|---|
| `LAYER_NOT_IN_TREE` | WARNING | Camada fora da árvore |
| `LAYER_OUTSIDE_FIELD_GROUP` | INFO (WARNING se gerada pelo plugin) | Camada fora de grupo `FORTSMART - …` |
| `FIELD_METADATA_CONFLICT` | WARNING | Grupo e `fortsmart_field_id` divergem |
| `DUPLICATE_FIELD_GROUP` | WARNING | Dois grupos com o mesmo talhão, que compartilham o mesmo GPKG |
| `FIELD_NOT_SELECTED` | INFO | Contexto sem talhão resolvido |
| `EXPLICIT_FIELD_DIFFERS_FROM_LAYER` | INFO | Escolha explícita diferente do talhão da camada ativa |
| `REPROJECTED_COPY` | INFO | Nome `… (EPSG:n)`; informa a origem encontrada no projeto |
| `REPROJECTED_COPY_WITHOUT_METADATA` | WARNING | Cópia sem papel/chave FortSmart; informa o papel que ficou no atributo e que o Ag lê |
| `ROLE_BY_NAME_ONLY` | INFO | Papel reconhecido só pelo nome |
| `ROLE_ONLY_IN_ATTRIBUTE` | INFO | Papel só no atributo `fortsmart_role`/`role`; o Ag usa, o Planner não |
| `ROLE_ATTRIBUTE_CONFLICT` | WARNING | Feições com outro papel conhecido; no Ag o papel da feição prevalece |
| `ROLE_UNKNOWN_TO_AG` | INFO | Papel que o Ag não exporta (ex.: `HEADLAND_WORK_PATH`, `COVERAGE`) |
| `AG_GROUP_DIFFERS` | WARNING | O Ag agruparia a camada em outro grupo (ex.: `SIM_PREVIEW` de talhão sem seções) |
| `MULTIPLE_APPLICABLE_BOUNDARIES` | WARNING | Mais de uma feição `EXTERNAL_BOUNDARY`/`OPERATIONAL_BOUNDARY` visível no talhão; o John Deere aceita uma |
| `NO_APPLICABLE_BOUNDARY` | INFO | Nenhum limite visível |
| `FIELD_ERID_INCONSISTENT` | WARNING | Mais de um `field_erid` válido no talhão; o Ag dividiria o pacote |
| `FIELD_ERID_INVALID` | WARNING | `field_erid` que não é UUID; o Ag o ignora |
| `CRS_INVALID`, `CRS_GEOGRAPHIC`, `CRS_NOT_METRIC` | WARNING | CRS da camada |
| `FARM_NOT_RECORDED` / `FARM_AMBIGUOUS` | INFO / WARNING | Fazenda |

Contratos de exportação preservados: os diagnósticos seguem as regras do Ag 2.9.20, sem alterá-las.
- **Limite:** visibilidade como no coletor do Ag; feições `LIMITE` contadas como em `multiple_external_boundary_errors`.
- **`field_erid`:** UUID válido e único.
- **`role`/`fortsmart_role`:** papel da feição prevalece quando conhecido; valores desconhecidos (ex.: `traffic`) ficam como estão.

## 6. Tipo geométrico antes de gravar no GeoPackage

O mecanismo de persistência não foi reescrito. Foram acrescentadas duas coisas:
- **`FortSmartPersistenceManager.diagnose_geometry_write(source, definition, field_name)`:** só lê o tipo da tabela existente e simula, numa cópia, o `ogr.ForceTo` de cada geometria. Devolve avisos e não grava nada. Sem tabela (primeira gravação), devolve lista vazia.
- **Com `ENABLE_GPKG_GEOMETRY_CHECK_V1` ligada:** `replace_role_layer` acrescenta os mesmos avisos a `PersistResult.warnings`. A geometria gravada é a mesma com a chave ligada ou desligada; isso é conferido em teste. Se o próprio diagnóstico falhar, a gravação continua e o aviso `GEOMETRY_CHECK_FAILED` é registrado.

Códigos: `MULTIPART_INTO_SINGLE`, `GEOMETRY_FAMILY_MISMATCH`, `FORCED_GEOMETRY_INVALID`, `COLLECTION_INTO_TYPED_TABLE`.

## 7. Chaves de recurso

Todas são lidas de `QgsSettings` em `fortsmart_precision/flags/<nome>` e começam desligadas. Fora do QGIS vale o padrão.

| Chave | Uso previsto |
|---|---|
| `ENABLE_AGROCAD_PANEL_V1` | Painel AgroCAD (0D) |
| `ENABLE_LAYER_ORGANIZER_V1` | Organização reversível (0C) |
| `ENABLE_PREVIEW_MANAGER_V1` | Previews em rubber band (0E) |
| `ENABLE_DEM_INSPECTOR_V1` | Inspetor DEM (0F) |
| `ENABLE_GPKG_GEOMETRY_CHECK_V1` | Avisos de tipo geométrico na persistência (0B) |

O `ProjectContextService` ainda não tem chamador. Ele passa a ser usado atrás de `ENABLE_AGROCAD_PANEL_V1` na 0D.

## 8. Algoritmos de Processing

Os 13 algoritmos não foram alterados. O novo `ProcessingProviderQgisTest` confere que o provider continua registrando exatamente os 13.

A conferência nos testes mostrou que **11** algoritmos não têm teste próprio, e não 10 como dizia a 0A. A 0A contava `import_field_boundary` e `validate_precision_project` como cobertos "de passagem", mas a cobertura é dos motores, não do algoritmo. Só `simulate_real_operation` e `simulate_obstacle_border_cut` são executados por testes.

| Algoritmo | Motor já coberto | Plano de regressão (sem alterar o algoritmo) | Prioridade |
|---|---|---|---|
| `generate_precision_lines` | `run_precision_lines` (dezenas de testes) | Rodar via `processing.run` com talhão e A-B em memória; comparar o REPORT com `run_precision_lines` direto | Alta |
| `validate_precision_project` | `validation_engine` | Projeto válido e inválido; comparar códigos do REPORT | Alta |
| `create_turn_paths` | `turn_path_engine` (`test_turn_paths_etapa1..4`) | Fixture retangular; contagem e atributos de OUTPUT_TURNS/OUTPUT_INVALID | Alta |
| `create_operation_passes` | `parallel_pass_engine` | Contagem, espaçamento e campos de OUTPUT | Média |
| `create_parallel_agricultural_lines` | `domain/agricultural_lines` | Contagem e comprimento mínimo; SELECTED_ONLY | Média |
| `simulate_obstacle_avoidance` | `run_precision_lines` com obstáculos | REPORT com e sem obstáculo | Média |
| `generate_obstacle_avoidance` | herda de `simulate_obstacle_avoidance` | Mesmo REPORT que o algoritmo base | Baixa |
| `create_obstacles` | `obstacle_from_point` | JSON do REPORT; nenhuma camada criada | Baixa |
| `import_field_boundary` | `ImportService` (`tests/integration/test_import_service.py`) | CSV/SHP de exemplo num projeto temporário | Média |
| `inspect_input` | `InputInspector`/`InputValidator` (`test_input_inspector_validator`) | REPORT para arquivo válido e inválido | Baixa |
| `health_check` | — | Saída OUTPUT não vazia | Baixa |

Regras do plano: entradas sintéticas em CRS métrico, sem dados de cliente; comparar com o motor direto (o algoritmo não pode divergir); conferir que nenhuma camada de entrada é alterada; um arquivo `tests/qgis/test_processing_<algoritmo>_qgis.py` por algoritmo, sem mudar o código do algoritmo.

## 9. Resultados de regressão (2026-10-08)

| Suíte | Antes (0A) | Depois (0B) |
|---|---|---|
| Planner unit + integration (`py -3`) | 992 passaram, 46 pulados | **1021 passaram, 46 pulados** (+29 novos) |
| Planner QGIS (`python-qgis-ltr.bat`) | 153 passaram | **162 passaram** (+9 novos, nenhum pulado) |
| Ag pytest | 155 passaram, 26 subtestes | **155 passaram, 26 subtestes** |
| Ag QGIS (`unittest`) | 14 OK | **14 OK** |
| Hashes de exportação (JD dual e 20\|20, 3 talhões) | linha de base | **87 de 87 hashes de arquivos iguais**; 3 relatórios explicados abaixo |
| `classFactory` do Planner (sem cache de bytecode, mesma máquina) | 576–614 ms, 163 módulos | 573–609 ms, 164 módulos (`project_context` não é carregado) |

**Correção da linha de base.** O `john_deere_guidance_report.json` grava o id de camada do QGIS (`12_passadas_plantio_<uuid com _>`), que muda a cada processo. A normalização da 0A só aceitava `-`, então o hash desse relatório mudava entre execuções em processos diferentes. Os arquivos do Ag não mudaram desde a linha de base: o último arquivo é de 07/10 22:10 e a linha de base de 22:22. O script agora aceita `_`; duas execuções em processos separados dão o mesmo resultado e os outros 87 hashes coincidem com a 0A.

## 10. Riscos restantes

1. **Réplica das regras do Ag.** `ag_field_group` e `AG_KNOWN_ROLES` copiam o Ag 2.9.20. Se o Ag mudar, os testes QGIS de compatibilidade falham, o que é intencional. Esses testes procuram o Ag em `FORTSMART_AG_PLUGIN_DIR` ou no perfil padrão do QGIS e são pulados, com o motivo, se o Ag não estiver instalado.
2. **`SIM_PREVIEW` em talhão sem seções.** O Ag agrupa a camada no próprio `SIM_PREVIEW`. Agora isso é diagnosticado (`AG_GROUP_DIFFERS`), mas não foi corrigido, por ser comportamento do Ag.
3. **Projetos do Planner com limite externo e operacional visíveis** geram `MULTIPLE_APPLICABLE_BOUNDARIES`. O comportamento do Ag não mudou; o usuário precisa ocultar um deles antes de exportar para John Deere.
4. **`ENABLE_GPKG_GEOMETRY_CHECK_V1` desligada:** a persistência continua aplicando `ogr.ForceTo` sem aviso. O método `diagnose_geometry_write` pode ser chamado antes de salvar, mas ainda não há tela que o chame.
5. **Plugin instalado no QGIS:** continua sendo a versão anterior à 0B. Como todas as chaves começam desligadas, instalar não muda o comportamento visível.
6. Os riscos da 0A que esta subfase não tocou continuam valendo: ciclo de vida das janelas, remoções implícitas, `processEvents` em `QThread` e dois produtores por tabela.
