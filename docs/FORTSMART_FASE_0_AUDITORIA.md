# FortSmart — Fase 0: auditoria antes da engenharia de rastros

Data: 2026-10-12. Branch: `audit/rea-fase0`. Estado inicial do Planner: `dc96cfd`, árvore limpa. Esta entrega é documental; nenhum módulo de produção, exportador ou arquivo em `legacy/` foi alterado.

## Escopo e evidência

| Fonte | Método | Evidência | Limite e confiança |
| --- | --- | --- | --- |
| Planner `plugin/fortsmart_precision` | leitura de código, testes unitários, integração e QGIS 3.44.13 | motores e resultados abaixo | alta para código e testes, sem homologação em máquina |
| Conversor `C:/Users/fortu/Desktop/QGIS_Python_NDVI/qgis_plugin/fortsmart_gs3_import` | leitura do registro de perfis e testes | writers GS3, Gen4, 20\|20, ISOXML, Jacto e Stara | alta para funcionalidades implementadas; importação/atuação em monitor não foram demonstradas nesta auditoria |
| `rea-main.zip` e [REA oficial](https://github.com/morluto/rea) | leitura do pacote e documentação | `rea-agents` 6.4.0, MIT; análise nativa requer Hopper, Ghidra ou IDA | alta para requisitos da ferramenta |
| `AgroCAD_setup_full.exe` | inspeção estática de assinatura, versão, cabeçalho e SHA-256 | assinatura Authenticode válida da Tecgraf; produto AgroCAD, versão `2026.10.07.1`; PE `MZ`; SHA-256 `59639BBC01E3925C026F51ABECBE0110A839212A8AD0F93F51C9EA63DD740E0C` | alta para identidade do arquivo; nenhuma conclusão sobre algoritmos internos |

O Node local é 22.14, abaixo do mínimo 22.19 exigido pelo REA 6.4.0. Não há `rea`, Hopper, Ghidra ou IDA detectado no PATH/pastas de programas. Assim, **REA não analisou o binário** nesta fase. O instalador não foi executado nem decompilado. O próximo uso de REA deve começar com ambiente compatível e pergunta técnica delimitada; capturar evidência e limitações de cada conclusão.

## Arquitetura encontrada

O Planner entra por `plugin.py`/`provider.py`; a tela operacional está em `gui/fortsmart_workspace_dialog.py`. `core/precision_lines_engine.py` gera as passadas. `core/tire_track_engine.py` gera dois rastros derivados por passada com dimensões informadas; `core/shutoff_engine.py` calcula intervalos `WORK_ON`/`WORK_OFF`; `core/cross_workflow.py` integra plantio e pulverização; `core/operational_generation.py` produz manifesto e relações. `core/headland_turn_engine.py`, `core/turn_path_engine.py` e `core/spray_border_entry.py` cobrem caminhos de manobra. `core/visual_coverage_engine.py` fornece cobertura visual, remonte e falha. `core/layer_roles.py` define a identidade das camadas. `core/export_readiness_validator.py` faz a checagem prévia de exportação.

O Conversor é um plugin separado. `monitor_registry.py` mapeia perfis para adapters. O caminho de exportação passa pelas propriedades `fortsmart_role` e grupos de talhão do Planner, então alterações em nomes/roles afetam a coleta. A auditoria anterior `docs/ETAPA_0_AUDITORIA.md` e o contrato `docs/CONTRATO_TRAFEGO_CONTROLADO_V1.md` detalham essa ligação; ambos são históricos e não substituem a execução dos testes atuais.

## Linha de base executada agora

| Suíte | Resultado |
| --- | --- |
| Planner `tests/unit`, Python 3.12 | 1105 passaram, 46 ignorados, 111 subtestes passaram |
| Planner `tests/integration`, Python 3.12 | 8 passaram |
| Planner `tests/qgis`, Python QGIS 3.44.13 | **234 passaram, 7 falharam**, 23 subtestes passaram |
| Conversor `tests` sem teste que importa QGIS, Python 3.12 | 196 passaram, 1 ignorado, 30 subtestes passaram |
| Conversor `tests.test_qgis_canonical_collector`, Python QGIS 3.44.13 | 14 passaram |

O teste `tests/qgis/test_workspace_canonical_preview.py` falha em sete casos com a mesma causa imediata. Seu helper `_generator` constrói `FortSmartWorkspaceDialog` via `__new__` sem chamar `QDialog.__init__`; `_render_preview` chama `_clear_preview`, que acessa `border_entry_preview` por `getattr` e o wrapper Qt responde `RuntimeError: super-class __init__() ... was never called`. A falha foi reproduzida isoladamente. Isso invalida o teste como prova de regeneração/persistência no estado atual; ainda não demonstra falha do diálogo criado normalmente na interface. Prioridade: corrigir o fixture e repetir os sete cenários, depois testar abertura real do diálogo no QGIS.

## Plano das próximas fases (sem implementação nesta entrega)

1. **Fechar a linha de base:** restaurar os sete testes QGIS, registrar caso de diálogo real, confirmar hashes de exportação por perfil com `docs/baseline_etapa0/gerar_baseline.py` e a base existente.
2. **Rastros:** medir offsets e polígonos já produzidos por `tire_track_engine.py` em retas, curvas, reversões e pneus assimétricos; adicionar entradas físicas apenas quando fornecidas pelo usuário/equipamento.
3. **Cruzamento/desligamento:** verificar conservação dos intervalos, tangência, 10°/15°, atribuição causal por distância e distinção entre exclusão geométrica e comando realizável por seções.
4. **Manobras e simulação:** preservar B1 real no cenário A7→B1→A8, validar raio e continuidade com parâmetros conhecidos; manter o simulador visual separado de execução real.
5. **Exportação/homologação:** por perfil, comparar saída com baseline, produzir relatório de validação e coletar evidência de importação e, separadamente, de atuação no monitor.

Cada fase deve ter fixtures métricas, teste de regressão, relatório de diferença e opção de desativação. Não iniciar integração de desligamento no monitor com base apenas na existência de um writer ou num arquivo aceito por um simulador.

## Reversão

Somente documentos e `CHANGELOG.md` foram acrescentados/alterados nesta branch. O código de produção permanece no commit inicial; para voltar ao estado anterior basta deixar de usar `audit/rea-fase0` ou reverter seu futuro commit documental. Nenhum dado do projeto QGIS, plugin instalado ou exportação foi alterado.
