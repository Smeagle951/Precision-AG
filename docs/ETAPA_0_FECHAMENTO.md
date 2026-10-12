# Etapa 0 — Fechamento

Estado da Etapa 0: **CONCLUSÃO TÉCNICA CONDICIONADA**. Falta a homologação visual no QGIS real, porque a instalação no perfil ainda não foi autorizada (ver seção 5).

## 1. Objetivo e regras seguidas

A Etapa 0 preparou a base do AgroCAD no FortSmart Precision Planner sem mudar o que já funcionava. Regras seguidas em todas as subfases:

- tudo atrás de chaves de recurso, **desligadas por padrão**;
- nenhuma alteração em geometria, IDs, atributos, CRS, tabelas ou nomes de GeoPackage;
- nenhuma camada do QGIS editada;
- nenhum motor, gerador (A-B, curva, bordadura, obstáculo, simulação), algoritmo de Processing ou exportador alterado;
- Precision Ag intocado; writers SendTo2020, Jacto, Stara, ISOXML, CNH e Fendt intocados;
- nenhuma migração de dados; nada pulado em silêncio;
- trabalho incremental e reversível, com backup antes de cada subfase e parada para aprovação.

## 2. Subfases

| Subfase | Entrega | Chave | Documento |
|---|---|---|---|
| 0A | Auditoria técnica e linha de base (testes, hashes de exportação, tempo de carga) | — | `ETAPA_0_AUDITORIA.md` |
| 0B | `ProjectContextService` somente leitura (projeto, talhão, fazenda, papel, seleção, CRS) e chaves persistidas; diagnóstico de gravação de geometria no GPKG | `ENABLE_GPKG_GEOMETRY_CHECK_V1` | `ETAPA_0B_CONTEXTO.md` |
| 0C | Árvore lógica de camadas 01–05 na aba "Camadas", só apresentação; visibilidade reversível | `ENABLE_LAYER_ORGANIZER_V1` | `ETAPA_0C_ORGANIZACAO.md` |
| 0D | Painel AgroCAD no dock: Editor, Obstáculos, Terreno, Planejamento, só atalhos para o que já existe; correções de ciclo de vida do dock | `ENABLE_AGROCAD_PANEL_V1` | `ETAPA_0D_PAINEL_AGROCAD.md` |
| 0E | Leitor da seleção nativa com identificador estável; gerenciador central de prévias só com `QgsRubberBand` | `ENABLE_PREVIEW_MANAGER_V1` | `ETAPA_0E_SELECAO_PREVIA.md` |
| 0F | Inspetor DEM somente leitura na seção Terreno | `ENABLE_DEM_INSPECTOR_V1` | `ETAPA_0F_INSPETOR_DEM.md` |
| 0G | Auditoria final, regressão, contrato de tráfego controlado e instalação controlada preparada | — | `ETAPA_0G_REGRESSAO_FINAL.md`, `CONTRATO_TRAFEGO_CONTROLADO_V1.md`, `SKILL_01_RELATORIO_FINAL.md` |

## 3. Arquivos da Etapa 0 no Planner

**Novos:**

- `core/project_context.py`, `core/geometry_write_check.py`, `core/logical_layer_tree.py`, `core/agrocad_tools.py`, `core/selection_reader.py`, `core/dem_inspector.py`, `core/dem_raster_reader.py`;
- `gui/layer_organizer_panel.py`, `gui/agrocad_panel.py`, `gui/preview_manager.py`, `gui/dem_inspector_widget.py`.

**Alterados, de forma pontual e condicionada às chaves:**

- `feature_flags.py`;
- `plugin.py`: entrega das ações ao dock e `unload` completo;
- `gui/main_dock.py`: abas por chave, contexto compartilhado e sinais;
- `core/persistence_manager.py`: métodos de diagnóstico somente leitura (`diagnose_geometry_write`, `table_geometry_type`); com `ENABLE_GPKG_GEOMETRY_CHECK_V1` ligada, `replace_role_layer` acrescenta avisos sem mudar a conversão gravada.

**Testes novos:**

- `tests/unit/`: `test_project_context`, `test_logical_layer_tree`, `test_agrocad_tools`, `test_selection_reader`, `test_dem_inspector`;
- `tests/qgis/`: `test_project_context_qgis`, `test_layer_organizer_qgis`, `test_agrocad_panel_qgis`, `test_selection_preview_qgis`, `test_dem_inspector_qgis`.

**Linha de base:** `docs/baseline_etapa0/` (`gerar_baseline.py` e `ag_2.9.20_export_hashes.json`).

**Backups**, em `plugin/backups/`: um antes de cada subfase, de `fortsmart_precision_antes_etapa0_20261007_221536` até `fortsmart_precision_antes_etapa0F_20261008_185158`.

## 4. Evidências finais

Detalhes em `ETAPA_0G_REGRESSAO_FINAL.md`.

| Verificação | Resultado |
|---|---|
| Planner unit + integration | 1085 passed, 46 skipped (0A: 992) |
| Planner QGIS | 228 passed, 0 failed (0A: 153) |
| Precision Ag pytest / QGIS | 155 passed / 14 OK (iguais à 0A) |
| Exportações do Ag contra a linha de base | 84/84 arquivos e 90/90 valores SHA-256 iguais |
| Chaves da Etapa 0 | 5 chaves, todas desligadas por padrão; nenhuma gravada no perfil do QGIS |
| Carga do plugin com as chaves desligadas | sem diferença mensurável em relação ao plugin anterior à 0B (~540–600 ms no mesmo método); +6 módulos |
| Trabalho paralelo (pulverização e tráfego) | preservado; nenhum arquivo dele foi alterado, restaurado ou limpo pela Etapa 0 |

## 5. Pendências que condicionam a homologação

1. **Homologação visual (bloqueante para "HOMOLOGADA").** A instalação está preparada e testada num perfil falso (`docs/instalacao_0g/`), mas não foi executada no perfil real.
   - Ela precisa de autorização explícita.
   - Também precisa ser combinada com a frente de pulverização, porque o perfil instalado tem arquivos dessa frente e a instalação os atualizaria para o estado do repositório.
2. **Falha do contrato operacional da pulverização (não bloqueante no estado atual).** Ela não se reproduz; a causa foi uma execução durante edições simultâneas. Fica a recomendação de critério de distância em `_causal_track`, a cargo do responsável pela pulverização.

## 6. Situação dos riscos levantados na 0A

| Risco (0A) | Situação no fechamento |
|---|---|
| Renomear seções quebra a exportação para monitor | **evitado**: a Etapa 0 nunca renomeia; a 0C só apresenta; hashes iguais |
| Ciclo de vida da interface (sinais nunca desligados, dock perde sinal, `unload` incompleto) | **corrigido no dock** (0D) e seguido nos painéis novos, com testes de reabrir sem duplicar conexões; o workspace protegido continua como estava |
| Remoções implícitas em `publish_persisted`, `place_generated_result` e `_clear_preview` | **não tocado**; a organização da 0C não passa por essas rotinas |
| `processEvents` em motores com `QThread` | **fora do escopo** (motores protegidos) |
| Dois produtores por tabela (`31_Linhas_Finais`, `22_Zonas_Seguranca`) | **fora do escopo**; registrado |
| Prévias em camadas permanentes | **base pronta** (gerenciador central da 0E); migração das prévias legadas, incluindo o `CaptureABLineTool`, fica para etapa própria |

## 7. Limitações conhecidas

Classificação completa em `ETAPA_0G_REGRESSAO_FINAL.md`, seção 5.

**Não bloqueantes:**

- o DEM não é invalidado ao editar o limite;
- elevação e NoData vêm de amostra;
- limites ambíguos bloqueiam a verificação, por desenho;
- a banda legada do `CaptureABLineTool` continua;
- identificadores duplicados só são detectados dentro da seleção.

**Melhoria futura:** a unidade vertical declarada vale só na sessão.

## 8. Como desligar tudo

As chaves são lidas de `QgsSettings` (`fortsmart_precision/flags/<nome>`). Para voltar ao comportamento anterior à Etapa 0:

```python
from fortsmart_precision.feature_flags import PERSISTED_FLAG_DEFAULTS, set_enabled
for name in PERSISTED_FLAG_DEFAULTS:
    set_enabled(name, False)
```

Para remover também o código, reinstale o backup do perfil com `docs/instalacao_0g/reverter_planner_controlado.ps1`, ou use os backups em `plugin/backups/`.
