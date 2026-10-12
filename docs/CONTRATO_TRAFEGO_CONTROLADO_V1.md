# Contrato de tráfego controlado — V1

Documento da Etapa 0 / 0G. Ele descreve **o que existe no código em 08/10/2026**, separado do que é proposta.

Fontes conferidas, todas no repositório do Planner (`plugin/fortsmart_precision`), salvo indicação:

- `domain/sprayer_traffic_configuration.py`;
- `domain/tire_shutoff_model.py`;
- `core/tire_track_engine.py`;
- `core/sprayer_traffic_engine.py`;
- `core/shutoff_engine.py`;
- `core/cross_workflow.py`;
- `domain/operational_contract.py`;
- `core/operational_generation.py`;
- `core/operational_persistence.py`;
- `core/export_operation_bundle.py`;
- `gui/fortsmart_workspace_dialog.py` (aba de cruzamento);
- `gui/line_import_utils.py`;
- `gui/cross_confirm_dialog.py`;
- `gui/operational_preview.py`;
- os writers do Precision Ag, em `QGIS_Python_NDVI/qgis_plugin/fortsmart_gs3_import`.

Esse código pertence à frente de pulverização e tráfego controlado, que está em desenvolvimento paralelo. **A Etapa 0 não alterou nenhum desses arquivos**, e este contrato não muda comportamento. Se o código mudar, este documento precisa ser revisto.

Legenda:

- **IMPLEMENTADO**: verificado no código e coberto por testes;
- **PARCIAL**: existe, com a lacuna indicada;
- **NÃO IMPLEMENTADO**: não existe no código;
- **PROPOSTA**: comportamento desejado para versões futuras.

## 1. Regras do contrato

| # | Regra | Situação |
|---|---|---|
| R1 | O usuário pode selecionar linhas reais de pulverização já existentes | **IMPLEMENTADO** |
| R2 | A seleção pode representar uma linha-base ou passadas existentes, conforme o modo operacional suportado | **IMPLEMENTADO** (2 modos) |
| R3 | O ângulo de cruzamento é derivado das geometrias, nunca exigido como entrada obrigatória | **IMPLEMENTADO** quanto a não ser entrada; **NÃO IMPLEMENTADO** como valor calculado e informado |
| R4 | Os dois rastros físicos dos pneus são entidades distintas das linhas de aplicação | **IMPLEMENTADO** |
| R5 | As exclusões de sementes precisam de rastreabilidade causal | **IMPLEMENTADO** para exclusões por pneu; **PARCIAL** no critério de atribuição |
| R6 | A exportação de desligamentos por máquina exige validação própria | **PARCIAL**: a validação existe, mas **nenhum exportador a consome** |

## 2. R1 e R2: origem da pulverização

Na aba de cruzamento do workspace, a caixa "Origem da pulverizacao" tem dois modos (`SPRAY_CROSS_SOURCE_*` em `gui/fortsmart_workspace_dialog.py`):

| Modo na tela | Valor | `CrossSourceMode` | De onde vêm as passadas |
|---|---|---|---|
| "Linha-base (passadas geradas na etapa 1)" | `line_base` | `GENERATED_BASELINE` | passadas geradas pelo botão 1 a partir da referência A-B da aba Aplicação. Essa referência pode ser uma feição existente selecionada ("Usar apenas feicao selecionada na camada"). Camadas geradas pelo FortSmart são recusadas como A-B (`ab_source_rejection_reason`) |
| "Passadas existentes (feicoes selecionadas)" | `existing_passes` | `EXISTING_PASSES` | as feições selecionadas no mapa na "Camada de pulverizacao", usadas como estão (`spray_passes_from_line_layer(..., selected_only=True)`) |

Garantias do modo "Passadas existentes", verificadas em `_cross_layers`:

- a camada de plantio é recusada como pulverização: "A camada selecionada pertence ao plantio…";
- "Usar somente as feicoes selecionadas no mapa" precisa estar marcada; caso contrário, o cálculo é recusado;
- sem feição selecionada, o cálculo é recusado: "Nenhuma feicao sera usada silenciosamente";
- só geometrias de linha são lidas, transformadas em memória para o CRS métrico de trabalho, sem alterar a camada;
- a identidade de cada passada vem de `fs_id`, `source_id`, `line_id` ou `pass_id`; na falta deles, de `<id da camada>:<fid>`;
- os IDs selecionados ficam registrados no manifesto (`cross_snapshot.selected_spray_feature_ids`), junto com `selected_spray_count`, `spray_layer` e `source_crs`.

Lacunas:

- **Feições ignoradas sem aviso.** Uma feição selecionada sem geometria de linha, ou com menos de 2 vértices, é ignorada por `_feature_lines`, sem aviso próprio. O total usado aparece na confirmação ("Passadas aplicacao: N"), mas a diferença para a seleção não é destacada. **PROPOSTA:** informar as feições descartadas.
- **Leitor de seleção da 0E fora do fluxo.** O leitor (`core/selection_reader.py`) ainda não é usado no cruzamento. **PROPOSTA (SKILL 02):** reutilizá-lo para mostrar a origem do identificador e os avisos de identificador instável ou repetido das passadas escolhidas.

## 3. R3: ângulo de cruzamento

- Nenhuma tela, função ou parâmetro do cruzamento pede ângulo. A busca por `angulo`, `angle_deg`, `crossing_angle` e `cross_angle` nos arquivos do fluxo não encontrou nada.
- O cruzamento é **puramente geométrico**: `apply_row_shutoff` amostra cada linha de plantio contra as faixas dos rastros de pneu (distância ao eixo do pneu ≤ meia largura de exclusão). Por isso, qualquer ângulo entre plantio e pulverização é tratado sem entrada do usuário.
- Os rumos existem só como atributos derivados da geometria (`azimuth_degrees(primeiro, último ponto)` em `line_import_utils`).
- **NÃO IMPLEMENTADO:** o ângulo de cruzamento não é calculado nem informado como resultado.
- **PROPOSTA:** derivar o ângulo local em cada interseção, a partir dos rumos dos dois segmentos no ponto de cruzamento, e informá-lo no manifesto e no resumo. Ele seria só diagnóstico, nunca entrada.

## 4. R4: rastros físicos dos pneus

**Configuração** (`SprayerTrafficConfiguration`). O usuário informa medidas físicas reais:

- barra (`boom_width_m`);
- largura do pneu;
- vão livre entre pneus;
- largura externa;
- margem de segurança.

O plugin calcula:

- a bitola centro a centro;
- as zonas de pneu esquerda e direita (`calculate_tire_zones`);
- as zonas de exclusão com a margem (`calculate_exclusion_zones`).

Medidas inconsistentes (vão + 2 × pneu ≠ externa, com tolerância de 5 mm) são resolvidas por escolha explícita (`USE_OUTER` ou `USE_INNER_AND_TIRES`) e informadas em `measure_check().message()`. Sem essa configuração, usa-se a bitola e o pneu do `SprayerMachine` (`generate_tire_tracks`).

**Geração** (`core/tire_track_engine.py`):

- **dois** `TireTrack` por passada (`side` "left" e "right"), deslocados da trajetória **completa** da passada, incluindo arcos e desvios, decimada a 0,75 m e no máximo 720 pontos;
- identidade própria `track_id = TT_<fs_id da passada>_<LADO>_<8 hex>`, com `source_feature_id` = passada de origem;
- largura física, margem e largura de exclusão efetiva por rastro.

**Contrato** (`TireTrackRecord`):

- exige `track_id`, `generation_id`, `spray_pass_id`, lado `LEFT`/`RIGHT`, larguras > 0, margem ≥ 0 e geometria linear;
- a relação `SPRAY_PASS_TO_TIRE_TRACK` liga cada rastro à sua passada.

**Camadas:**

- prévia em `08_Rastros_Pneus` (`gui/operational_preview.py`), separada de `06_Passadas_Plantio` e de `13_Shutoff`;
- a linha de aplicação continua sendo a passada; o rastro é outra entidade, com outra geometria.

## 5. R5: rastreabilidade causal das exclusões

**Segmento operacional** (`OperationalSegment`). Exige:

- identidade persistente (`segment_id`, `generation_id`, `field_id`);
- `source_row_id`;
- geometria linear;
- intervalo de estação válido;
- comprimento > 0;
- motivo explícito para `WORK_OFF`.

**Regra causal** (`operational_contract.py:92-96`): se o motivo for `SPRAYER_TIRE_TRACK` ou `SAFETY_MARGIN`, o `tire_track_id` é obrigatório. Sem ele, a geração é rejeitada: "Exclusao por pneu sem tire_track_id causal."

**Validação da geração** (`OperationalGeneration.validate`):

- `source_row_id` único;
- todo rastro e todo segmento pertencem à mesma geração;
- todo segmento aponta para uma linha de plantio existente;
- todo `tire_track_id` aponta para um rastro existente.

**Relações gravadas:**

- `PLANTING_ROW_TO_SHUTOFF`;
- `TIRE_TRACK_TO_SHUTOFF`;
- `SPRAY_PASS_TO_TIRE_TRACK`.

**Persistência** (`OperationalPersistenceStore`, no GeoPackage do talhão):

- tabelas `fortsmart_operation_manifest`, `_planting_rows`, `_spray_passes`, `_tire_tracks`, `_segments` e `_relations`;
- `save_generation` valida, grava como `DRAFT`, confere as contagens gravadas e, **na mesma transação**, passa a geração ativa anterior a `SUPERSEDED` e a nova a `ACTIVE`;
- a tela invalida o rascunho quando a plantadeira, o pulverizador, a camada de plantio ou a origem mudam ("Desatualizado - recalcule antes de salvar").

**Lacunas (PARCIAL):**

1. **Atribuição sem limite de distância.** `_causal_track` atribui cada segmento ao rastro **mais próximo**, sem limite de distância. Hoje todo segmento de pneu nasce de uma faixa de pneu, então a atribuição é coerente. **PROPOSTA:** exigir distância ≤ meia largura de exclusão e recusar com diagnóstico quando não houver rastro compatível.
2. **Só exclusões por pneu entram na geração.** A geração só recebe `tire_shutoff_segments`. Os desligamentos por bordadura e obstáculo (`off_areas` e `on_areas`) aparecem no resultado do cruzamento, mas **não** entram na geração operacional, embora `HEADLAND` e `OBSTACLE` existam em `OperationalReason`. **PROPOSTA:** levá-los com a causa própria (o ID da zona ou do obstáculo).
3. **`mark_active_stale` sem chamador.** O método existe, mas nenhuma tela o chama. Uma geração `ACTIVE` não vira `STALE` quando as camadas de origem mudam depois de salva.
4. **Histórico da falha da 0F.** A falha de `test_spray_ab_reference_and_cross_flow` vista na 0F não se reproduz no estado atual; a análise está em `ETAPA_0G_REGRESSAO_FINAL.md`, seção 2. A regra causal está correta e **não deve ser enfraquecida**.

## 6. R6: exportação de desligamentos por máquina

**O que existe:**

- **`ExportOperationBundle`** (`domain/operational_contract.py`) e **`build_export_operation_bundle`** (`core/export_operation_bundle.py`):
  - montam o pacote **somente** a partir da geração canônica persistida;
  - revalidam a geração inteira;
  - exigem status `ACTIVE`.
- **`ExporterCapabilities`** e **`assess_export_capabilities`**: comparam o pacote com o que o formato alvo suporta (guias, estados de trabalho, rastros…) e informam, sem converter nem descartar em silêncio:
  - objetos nativos;
  - objetos auxiliares;
  - objetos sem suporte ("exportacao exige decisao explicita").

**O que não existe:**

- **Nenhum exportador consome esse contrato.** As únicas referências a `build_export_operation_bundle` e `assess_export_capabilities` estão nos próprios módulos e em `tests/unit/test_operational_contract.py`.
- **Writers do Precision Ag:**

| Writer | Tratamento de `SHUTOFF`, `WORK_OFF` e `TIRE_TRACK` |
|---|---|
| John Deere (`jd_guidance_plan.py`) | ignorados explicitamente (`SKIP_GROUPS`) |
| 20\|20 (`sendto2020_export.py`) | ignorados explicitamente (`SKIPPED_ROLES`) |
| ISOXML (`adapters/isoxml_writer.py`) | `SHUTOFF` está entre os papéis aceitos (`ISOXML_ROLES`), lido da **camada** `13_Shutoff`, sem `generation_id`, sem `tire_track_id` e sem exigir geração `ACTIVE` |

  O que o ISOXML gera a partir disso não foi auditado na Etapa 0.
- **Exportação para arquivo:** o exportador GeoPackage/GeoJSON do Planner (`exporters/geopackage_exporter.py`) grava `shutoff_segments.geojson` e `tire_tracks.geojson` a partir do resultado do motor. É exportação para arquivo, não para a máquina, e também não passa pelo contrato operacional.

**Situação:** **PARCIAL**. A validação própria existe e está testada, mas nenhum exportador de máquina a usa.

**PROPOSTA:** qualquer exportação de desligamentos para monitor deve:

1. partir de `build_export_operation_bundle` (geração `ACTIVE` e validada);
2. declarar `ExporterCapabilities` reais do formato;
3. mostrar ao usuário o `ExportSemanticReport` antes de gravar;
4. ter comparação de saída (hashes) própria.

Os writers protegidos (SendTo2020, Jacto, Stara, ISOXML, CNH, Fendt, John Deere) **não** foram alterados.

## 7. Fluxo atual de ponta a ponta (referência)

1. **Aplicação (botão 1):** passadas de pulverização a partir da referência A-B. É o modo linha-base.
2. **Plantio (botão 2):** passadas de plantio e linhas virtuais por linha da plantadeira (`ensure_virtual_planting_rows`).
3. **Aba de cruzamento:** escolha das linhas de plantio e da origem da pulverização (linha-base ou passadas selecionadas), mais as opções "Desligar semente no rastro do pneu" e "Desligar semente na bordadura interna".
4. **Confirmação** (`CrossConfirmDialog`): plantadeira, barra, bitola, pneu, margem, faixa de exclusão e quantidade e origem das passadas.
5. **`run_cross_shutoff`:**
   - rastros de pneu (`ensure_tire_tracks`);
   - tramlines;
   - segmentos ON/OFF por linha (`apply_row_shutoff`);
   - tabela com a classificação estática por deslocamento lateral (`calculate_planting_shutoff`).
6. **`build_operational_generation`:** geração `DRAFT` com manifesto, linhas, passadas, rastros, segmentos de pneu e relações. A prévia fica em camadas de memória (`06`, `08` e `13`).
7. **"Salvar resultado operacional":** `save_generation` torna a geração `ACTIVE` no GeoPackage do talhão.

## 8. Próximos passos sugeridos (não iniciados)

1. Critério de distância em `_causal_track`, com teste do caso "segmento de pneu sem rastro compatível".
2. Desligamentos por bordadura e obstáculo na geração operacional, com causa própria.
3. Chamar `mark_active_stale` quando as origens de uma geração ativa mudarem.
4. Ângulo de cruzamento derivado, como diagnóstico.
5. Exportação de desligamentos por máquina somente via `ExportOperationBundle`, com relatório de perda semântica e linha de base própria.
6. Reutilizar o leitor de seleção (0E) e o gerenciador de prévias (0E) no cruzamento.
