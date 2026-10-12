# FortSmart — Fase 0: auditoria antes da engenharia de rastros

Data: 2026-10-12. Branch: `audit/rea-fase0`. Estado inicial do Planner: `dc96cfd`, árvore limpa. Esta entrega é documental; nenhum módulo de produção, exportador ou arquivo em `legacy/` foi alterado.

## Escopo e evidência

| Fonte | Método | Evidência | Limite e confiança |
| --- | --- | --- | --- |
| Planner `plugin/fortsmart_precision` | leitura de código, testes unitários, integração e QGIS 3.44.13 | motores e resultados abaixo | alta para código e testes, sem homologação em máquina |
| Conversor `C:/Users/fortu/Desktop/QGIS_Python_NDVI/qgis_plugin/fortsmart_gs3_import` | leitura do registro de perfis e testes | writers GS3, Gen4, 20\|20, ISOXML, Jacto e Stara | alta para funcionalidades implementadas; importação/atuação em monitor não foram demonstradas nesta auditoria |
| `rea-main.zip` e [REA oficial](https://github.com/morluto/rea) | leitura do pacote e documentação, seguida de análise estática dos assemblies instalados | `rea-agents` 6.4.0, MIT; provedor `rea-dotnet-static` funcionou com Node 22.19 temporário | alta para metadados/call graph; cobertura de membros parcial |
| `AgroCAD_setup_full.exe` | inspeção estática de assinatura, versão, cabeçalho e SHA-256 | assinatura Authenticode válida da Tecgraf; produto AgroCAD, versão `2026.10.07.1`; PE `MZ`; SHA-256 `59639BBC01E3925C026F51ABECBE0110A839212A8AD0F93F51C9EA63DD740E0C` | alta para identidade do arquivo; nenhuma conclusão sobre algoritmos internos |
| `C:/Tecgraf/AgroCAD` | inventário da instalação e `inspect-managed-artifact`/`inspect-managed-members` do REA | componentes .NET de pisoteio, semeadura, Precision Planting e John Deere | alta para existência e chamadas declaradas; sem teste de comportamento |

O Node instalado é 22.14, abaixo do mínimo 22.19 exigido pelo REA 6.4.0. Uma execução temporária com `npx -p node@22.19.0 -p rea-agents@6.4.0` permitiu analisar os assemblies .NET **sem carregá-los nem executá-los**. Não há Hopper, Ghidra ou IDA detectado no PATH/pastas de programas. O instalador em si não foi executado nem decompilado.

### Achados da instalação AgroCAD com REA

| Artefato (SHA-256) | Evidência REA | Observação estática | Limite |
| --- | --- | --- | --- |
| `Interface/Pisoteio.exe` (`baae2ea0970404acd14190349463790b2ffa405a865e9c54f822e69fbbfff07b`) | `ev_75afe8e1d641e55bc7fb0736626b2480d593728d9422dd3af948ad4af8ce8a0b` | assembly .NET Framework x86; método `formPrinc.analisePisoteio` (token `0x06000014`) | o nome do método não define como o cálculo é feito |
| `Interface/SeedingCleaner.exe` (`73824090e211fab43a8ab26cfbe6011006c395e82737845fe27063f2c0102dd6`) | `ev_f519a88bde9c3b4015d6ce383c28e838a650247ea296d2ba9e80b9f2a899fb2e` | método `SeedOpCleaner.Limpa`; referências a DotSpatial Topology/Data/Projections | sem confirmação da semântica de desligamento |
| `ADAPT/Interface_PrecisionPlanting.exe` (`f63008304d6d000d6d3d2d5bf49407038adce28f42e412cd1a32028ac018981e`) | `ev_2c1808e05869de5f8c2bfee4addf42b36db7da34ffe9ecc8e16dd475084f214c` | `PP_EXPORT.ExportPP2020` chama `AddBoundary`, `AddAbLine`, `AddAbCurve` e `AddAdaptiveCurve` no grafo de chamadas; também há `GuidanceCleanup` | sugere escopo de exportação mais amplo que boundary, mas não comprova arquivo aceito nem atuação no 20\|20 |
| `JDPlugin/ExportaDados.exe` (`3c78770715d204ed91da073a5987c228b2eb9b48cde760a5bff7c9930a5a623c`) | `ev_cb567b384bde1d0b8efb3b8412f26d7a5f94f2445c2955670e391df46b94d0a4` | métodos `CriaBoundary`, `CreateHeadlands`, offsets de cabeceira e `CriaValoresNaLinha` | metadados não revelam validade geométrica nem comportamento do monitor |

O REA informou cobertura `partial` para os inventários de membros. A observação mais útil para o FortSmart é verificável no código próprio: `SendTo2020Writer.SENDTO2020_ROLES` filtra somente `EXTERNAL_BOUNDARY`, enquanto o assembly instalado contém chamadas de exportação para linhas AB e curvas. Isso define uma **hipótese de expansão** para investigar com fixtures e formatos, não autorização para acrescentar esses dados ao writer sem validação.

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
5. **Exportação/homologação:** investigar separadamente os métodos `AddAbLine`, `AddAbCurve` e `AddAdaptiveCurve` observados no assembly Precision Planting; por perfil, comparar saída com baseline, produzir relatório de validação e coletar evidência de importação e, separadamente, de atuação no monitor.

Cada fase deve ter fixtures métricas, teste de regressão, relatório de diferença e opção de desativação. Não iniciar integração de desligamento no monitor com base apenas na existência de um writer ou num arquivo aceito por um simulador.

## Reversão

Somente documentos e `CHANGELOG.md` foram acrescentados/alterados nesta branch. O código de produção permanece no commit inicial; para voltar ao estado anterior basta deixar de usar `audit/rea-fase0` ou reverter seu futuro commit documental. Nenhum dado do projeto QGIS, plugin instalado ou exportação foi alterado.
