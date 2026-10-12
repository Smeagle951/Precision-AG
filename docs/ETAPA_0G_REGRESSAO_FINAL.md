# Etapa 0 / Subfase 0G — Auditoria final e regressão

Estado: **concluída tecnicamente; homologação visual pendente** (ver seção 6). A SKILL 02 não foi iniciada.

A 0G não alterou código do plugin. Os únicos arquivos alterados foram:

- documentação;
- a correção de um número em `docs/ETAPA_0F_INSPETOR_DEM.md`;
- dois scripts novos de instalação em `docs/instalacao_0g/`.

A comparação de hashes antes e depois da 0G está na seção 7.

## 1. Regressão final

Executada no estado atual do repositório em 08/10/2026, entre 19h05 e 19h15:

| Suíte | Linha de base (0A) | Final (0G) |
|---|---|---|
| Planner unit + integration (`py -3 -m pytest tests/unit tests/integration`) | 992 passed, 46 skipped | **1085 passed, 46 skipped**, 103 subtestes |
| Planner QGIS (`python-qgis-ltr.bat -m pytest tests/qgis`) | 153 passed | **228 passed, 0 failed**, 23 subtestes |
| Precision Ag pytest | 155 passed | **155 passed**, 26 subtestes |
| Precision Ag QGIS (`unittest tests.test_qgis_canonical_collector`) | 14 OK | **14 OK** |
| Exportações do Precision Ag contra a linha de base | 84 arquivos | **84/84 arquivos e 90/90 valores SHA-256 iguais** |

Parte do aumento de testes do Planner vem da Etapa 0, e o restante, do trabalho paralelo de pulverização e tráfego controlado.

| Subfase | Testes unitários | Testes QGIS |
|---|---|---|
| 0B | `test_project_context` | `test_project_context_qgis` |
| 0C | `test_logical_layer_tree` | `test_layer_organizer_qgis` |
| 0D | 10 | 15 |
| 0E | 8 | 19 |
| 0F | 12 | 15 |

**Chaves de recurso:** as cinco chaves da Etapa 0 estão desligadas por padrão em `feature_flags.PERSISTED_FLAG_DEFAULTS`:

- `ENABLE_AGROCAD_PANEL_V1`;
- `ENABLE_LAYER_ORGANIZER_V1`;
- `ENABLE_PREVIEW_MANAGER_V1`;
- `ENABLE_DEM_INSPECTOR_V1`;
- `ENABLE_GPKG_GEOMETRY_CHECK_V1`.

O perfil `default` do QGIS não tem nenhuma delas gravada no `QGIS3.ini`.

## 2. Falha do trabalho paralelo (`test_spray_ab_reference_and_cross_flow`)

**Sintoma (rodada da 0F, por volta de 18h57):**

- teste: `CrossFlowTest::test_cross_manual_then_detour_and_automatic_headland`;
- erro: `ValueError: Exclusao por pneu sem tire_track_id causal.`;
- origem: `domain/operational_contract.py:96`.

**Reprodutibilidade no estado atual:** **não se reproduz.**

| Rodada | Resultado |
|---|---|
| arquivo de teste isolado | 6 passed |
| mesmo arquivo + `test_operational_persistence_qgis.py`, 3 repetições | 7 passed em cada |
| `tests/unit/test_operational_contract.py` | 7 passed |
| suíte QGIS completa | 228 passed, 0 failed |

**Causa identificada:**

1. A regra que disparou está correta e não foi alterada. `OperationalSegment.validate()` exige `tire_track_id` sempre que o motivo do desligamento é `SPRAYER_TIRE_TRACK` ou `SAFETY_MARGIN`.
2. O segmento chega sem `tire_track_id` quando `build_operational_generation` não encontra o rastro causador (`_causal_track` devolve `None`) e mantém o motivo `SPRAYER_TIRE_TRACK`.
3. Na rodada que falhou, os arquivos desse fluxo estavam sendo editados pelo trabalho paralelo durante a execução:
   - `core/operational_generation.py`, gravado às 18h57m18s;
   - `tests/qgis/test_spray_ab_reference_and_cross_flow.py`, às 18h57m54s;
   - `gui/fortsmart_workspace_dialog.py`, às 18h59m48s.

   A suíte QGIS rodou entre cerca de 18h57 e 18h58. Ou seja, ela executou um estado intermediário desses arquivos.
4. No código atual, `_causal_track` escolhe o rastro mais próximo entre todos os rastros com geometria. Assim, todo segmento de desligamento por pneu recebe um `tire_track_id`, desde que exista ao menos um rastro.

**O que foi feito:** nada no código. A validação de `tire_track_id` não foi enfraquecida, e o motor de pulverização e o contrato operacional não foram tocados.

**Situação:** a falha **não é bloqueante no estado atual**, porque não se reproduz. Ficam duas observações para o responsável pela pulverização:

- **Atribuição causal sem limite de distância.** `_causal_track` escolhe o rastro mais próximo, sem conferir se a distância é compatível com a largura de exclusão. Hoje, todo segmento de pneu nasce de uma faixa de pneu, então o resultado é coerente. Se outra fonte de desligamento entrar nessa lista, o segmento seria atribuído a um rastro sem relação causal real. Recomenda-se exigir distância ≤ meia largura de exclusão e, caso contrário, recusar com diagnóstico.
- **Falta um teste dedicado ao caso sem rastro.** O caso "segmento de pneu sem rastro disponível" é rejeitado pelo contrato, mas não há teste que o exercite pelo fluxo de geração.

## 3. Hashes de exportação: 84, 87, 90 e 96

Todos os números se referem ao mesmo arquivo de linha de base, `docs/baseline_etapa0/ag_2.9.20_export_hashes.json`, criado na 0A:

| Número | O que é | Onde apareceu |
|---|---|---|
| **84** | arquivos exportados: 3 talhões × (17 arquivos John Deere dual + 11 arquivos 20\|20) | 0A (por perfil), 0F, 0G |
| **90** | valores SHA-256 aceitos: 78 arquivos têm um valor e 6 têm dois (3 `CurveTrack….fdShape` e 3 `AdaptiveCurve….gjson`, cujas duas exportações da 0A geraram variantes, ambas registradas como aceitas) | 0G |
| **87** | na 0B: 87 valores iguais **mais** 3 relatórios `john_deere_guidance_report.json` explicados à parte (87 + 3 = 90). Na 0F: erro de contagem do meu script, que guardava as entradas `.fdShape` inteiras e contava as 3 de dois valores como uma só (90 − 3 = 87) | 0B, 0F (corrigido) |
| **96** | 90 valores SHA-256 + 6 marcadores `deterministic` dos arquivos `.fdShape`. O filtro "caminho contém sha" não diferenciava maiúsculas e casou com "fd**Sha**pe" | 0C, 0D, 0E |

Conferência no próprio JSON: 174 folhas, sendo 90 valores SHA-256 e 84 marcadores `deterministic`. As folhas cujo caminho contém "sha", sem diferenciar maiúsculas, são exatamente 96.

As comparações "96/96" da 0C, 0D e 0E incluíam todos os 90 valores SHA-256, então as conclusões daquelas subfases continuam válidas. Só o número era impreciso.

**Comparação estrita na 0G.** Foi feita arquivo por arquivo: o conjunto de hashes produzido agora precisa estar contido no conjunto aceito da linha de base.

```text
"C:\Program Files\QGIS 3.44.13\bin\python-qgis-ltr.bat" docs\baseline_etapa0\gerar_baseline.py C:\Users\fortu\Desktop\QGIS_Python_NDVI\qgis_plugin <novo.json>
```

Resultado:

- 84 arquivos na base e 84 gerados;
- 90 valores aceitos e 90 produzidos;
- 0 faltando, 0 a mais, 0 divergentes.

Nenhum exportador foi alterado.

## 4. Tempo de carga do plugin

Mesmo método para todas as versões: Python do QGIS 3.44.13, `iface` simulado dos testes, chaves desligadas, 3 execuções. A primeira execução é fria, por causa do cache do disco, e foi descartada.

| Versão | `classFactory` | `initGui` | abrir o painel | módulos `fortsmart_precision` |
|---|---|---|---|---|
| backup anterior à 0B | ~540 ms | 1 ms | 4–5 ms | 163 |
| plugin instalado no perfil (sem Etapa 0) | ~605–635 ms | 1–2 ms | 6–7 ms | 167 |
| repositório atual, chaves desligadas | ~565–600 ms | 1–3 ms | 12–13 ms | 169 |
| repositório atual, chaves ligadas | ~545–550 ms | 1 ms | ~90 ms | 176 |

Leitura dos resultados:

- **Chaves desligadas:** a Etapa 0 não muda o tempo de carga de forma mensurável; a variação fica dentro do ruído. Ela acrescenta 6 módulos e cerca de 8 ms na abertura do painel.
- **Chaves ligadas:** a abertura do painel sobe para cerca de 90 ms, porque monta as abas AgroCAD e Camadas e o inspetor.
- **Diferença para a 0A:** os 245 ms registrados na 0A vieram de outro método de medição. No mesmo método, a versão anterior à Etapa 0 mede cerca de 540 ms.

## 5. Revisão das limitações

| # | Limitação | Origem | Classificação | Justificativa |
|---|---|---|---|---|
| 1 | O DEM não é invalidado automaticamente quando a geometria do talhão é editada | 0F | **não bloqueante** | a verificação é somente leitura e manual; o usuário clica de novo em "Verificar DEM"; trocar talhão, raster, CRS ou projeto já invalida |
| 2 | Elevação e NoData vêm de uma amostra de até 256 × 256 pixels | 0F | **não bloqueante** | a cobertura geométrica é exata; a amostra é declarada na tela; não há análise de terreno que dependa disso |
| 3 | A unidade vertical declarada vale só na sessão | 0F | **melhoria futura** | por desenho: nada é gravado no projeto nem no raster; persistir exigiria decidir onde gravar sem alterar a raster |
| 4 | Limites ambíguos bloqueiam a verificação do DEM | 0F | **não bloqueante (comportamento conservador desejado)** | escolher um limite em silêncio violaria "nada de skip silencioso"; o diagnóstico mostra os limites candidatos |
| 5 | A prévia legada do `CaptureABLineTool` tem uma banda que nunca é removida | 0A | **não bloqueante, pré-existente** | fora do escopo por decisão explícita; migrar mexeria em telas protegidas; fica para etapa própria |
| 6 | Identificadores duplicados só são detectados dentro da seleção | 0E | **não bloqueante** | o leitor avisa `DUPLICATE_IDENTITY` dentro da seleção; verificar a camada inteira exigiria varrer todas as feições a cada mudança de seleção; melhoria futura com índice |
| 7 | Falha do contrato operacional da pulverização | trabalho paralelo | **não bloqueante no estado atual** (não reproduzível); **recomendação ao responsável** | seção 2; a validação causal está correta; resta o critério de distância em `_causal_track` |
| 8 | Homologação visual no QGIS real | 0G | **bloqueante para "HOMOLOGADA"** | a instalação no perfil não foi autorizada nesta subfase (seção 6) |
| 9 | O plugin instalado tem estado misto (pulverização atual, Etapa 0 ausente) | 0G | **risco de coordenação** | instalar a cópia do repositório também atualiza arquivos da pulverização no perfil; combinar com o responsável |

## 6. Instalação controlada (preparada, **não executada**)

Situação do perfil `default` (`%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\fortsmart_precision`), levantada só por leitura:

- o plugin instalado tem 214 arquivos, contra 225 no repositório;
- **11 arquivos não existem no instalado**: todos os da Etapa 0 (`project_context`, `geometry_write_check`, `logical_layer_tree`, `agrocad_tools`, `selection_reader`, `dem_inspector`, `dem_raster_reader`, `layer_organizer_panel`, `agrocad_panel`, `preview_manager` e `dem_inspector_widget`);
- **10 arquivos são diferentes**:
  - da Etapa 0: `feature_flags.py`, `plugin.py`, `core/persistence_manager.py` e `gui/main_dock.py`;
  - da pulverização, mais antigos no instalado: `core/shutoff_engine.py`, `core/sprayer_traffic_engine.py`, `domain/tire_shutoff_model.py`, `gui/cross_confirm_dialog.py`, `gui/line_import_utils.py` e `gui/machine_config_widgets.py`;
- **os arquivos novos da pulverização já estão instalados e idênticos ao repositório**: `operational_*`, `cross_workflow.py`, `tire_track_engine.py` e `fortsmart_workspace_dialog.py`. Isso indica que o responsável por essa frente instala o próprio trabalho nesse perfil;
- nenhum arquivo existe só no instalado, então a instalação não apagaria nada exclusivo dele.

**Scripts preparados (em `docs/instalacao_0g/`):**

- `instalar_planner_controlado.ps1`
  - Sem `-Executar`, só simula e mostra: "11 arquivo(s) novo(s), 10 alterado(s), 0 removido(s)".
  - Com `-Executar`:
    1. recusa se o QGIS estiver aberto;
    2. copia o plugin instalado e o `QGIS3.ini` para `plugin/backups/perfil_default_antes_instalacao_0G_<data>` e confere os hashes do backup;
    3. instala uma cópia sem `__pycache__`/`.pyc` e confere os hashes instalados.

  Não liga nenhuma chave.
- `reverter_planner_controlado.ps1 -Backup <pasta> [-RestaurarIni] -Executar`
  - devolve o plugin anterior e confere os hashes;
  - com `-RestaurarIni`, devolve também o `QGIS3.ini`, o que desfaz as chaves ligadas durante o teste.

**Teste dos scripts:** feito num perfil falso em `%TEMP%`, com uma cópia do plugin instalado.

1. simulação;
2. instalação: backup de 214 arquivos conferido e 225 arquivos instalados conferidos;
3. reversão: 214 arquivos restaurados e conferidos.

Ao final, o perfil falso ficou idêntico ao original. O perfil real não foi alterado: a pasta continua com data de 07/10/2026 22h00.

O script antigo `install_plugin_qgis.ps1` apaga a pasta instalada sem backup e copia `__pycache__`. Ele não foi alterado nem usado.

**Roteiro do teste visual**, depois de autorizado e combinado com a frente de pulverização:

1. Fechar o QGIS e rodar `instalar_planner_controlado.ps1 -Executar`.
2. Abrir o QGIS com todas as chaves desligadas e conferir que o dock, os menus e o fluxo de pulverização estão como antes.
3. No console Python, ligar as chaves uma a uma com `set_enabled(...)`, reabrindo o dock a cada vez:
   - Camadas (`ENABLE_LAYER_ORGANIZER_V1`);
   - AgroCAD (`ENABLE_AGROCAD_PANEL_V1`);
   - prévia (`ENABLE_PREVIEW_MANAGER_V1`);
   - Terreno (`ENABLE_DEM_INSPECTOR_V1`).
4. Num projeto real, com cópia, verificar:
   - talhão de trabalho;
   - seleção e prévia de uma passada;
   - inspetor DEM com uma raster real;
   - fechar e reabrir o dock;
   - trocar de projeto.
5. Desligar todas as chaves e reverter, se for o caso.

## 7. Arquivos da 0G

| Arquivo | Mudança |
|---|---|
| `docs/ETAPA_0G_REGRESSAO_FINAL.md` | **novo** (este documento) |
| `docs/ETAPA_0_FECHAMENTO.md` | **novo** |
| `docs/CONTRATO_TRAFEGO_CONTROLADO_V1.md` | **novo** |
| `docs/SKILL_01_RELATORIO_FINAL.md` | **novo** |
| `docs/instalacao_0g/instalar_planner_controlado.ps1` | **novo** |
| `docs/instalacao_0g/reverter_planner_controlado.ps1` | **novo** |
| `docs/ETAPA_0F_INSPETOR_DEM.md` | correção: "87 valores" passou a "90 valores" |
| `CHANGELOG.md` | entrada da 0G |

O snapshot de hashes de `plugin/fortsmart_precision` e `tests`, feito antes e depois da 0G, confirma: **nenhum arquivo de código ou teste foi alterado pela 0G**. Os arquivos da pulverização e do tráfego controlado foram preservados e não foram restaurados nem limpos.
