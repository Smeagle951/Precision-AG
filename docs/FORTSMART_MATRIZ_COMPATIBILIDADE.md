# Matriz de capacidades e evidência — Fase 0

Esta matriz registra capacidades observáveis do código em 2026-10-12, sem declarar homologação em monitor. `Implementado` significa presença no código/testes; `Validado em equipamento` exige evidência externa específica.

| Fluxo | Implementação encontrada | Evidência local | Estado de equipamento / lacuna |
| --- | --- | --- | --- |
| Planner: passadas de plantio e pulverização | `core/precision_lines_engine.py`, `gui/fortsmart_workspace_dialog.py` | testes unitários e QGIS; sete testes de regeneração bloqueados por fixture Qt | planejamento geométrico, sem garantia de execução |
| Rastros de pneus | `core/tire_track_engine.py`, `domain/sprayer_traffic_configuration.py` | testes de tráfego e desligamento existentes | validar geometrias em curvas/reversões com medições reais |
| Cruzamento e desligamento | `core/shutoff_engine.py`, `core/cross_workflow.py`, `domain/operational_contract.py` | testes de intervalos e contrato existentes | estado planejado não equivale a atuação no controlador |
| Cobertura visual | `core/visual_coverage_engine.py`, `algorithms/simulate_real_operation.py` | `tests/unit/test_visual_coverage_engine.py` | somente simulação, sem trajetória executada |
| John Deere GS3/Gen4 | Conversor: `monitor_registry.py`, adapters e relatórios de orientação | testes de exportação e 14 testes QGIS do coletor | importação e atuação precisam de evidência por geração/versão; não presumir Section Control |
| Precision Planting 20\|20 | Conversor: `sendto2020_writer.py`, `sendto2020_export.py`, `sendto2020_preflight.py` | testes de estrutura SHP/limites | writer observado para limites; desligamento por linha ou seção não validado |
| ISOXML, Jacto, Stara | Conversor: adapters respectivos | suítes do Conversor passaram no escopo indicado | fora da primeira alteração; validar por dispositivo antes de alegar compatibilidade operacional |

Fonte dos caminhos e limitações: `docs/ETAPA_0_AUDITORIA.md`, `docs/CONTRATO_TRAFEGO_CONTROLADO_V1.md` e leitura dos módulos citados. A descrição em `metadata.txt` do Conversor contém a palavra “validado”; nesta auditoria ela **não foi tomada como evidência de homologação em hardware**.

Critério para atualizar uma célula a `Validado em equipamento`: registrar fabricante, modelo, versão de firmware, configuração de seções, formato, arquivo exportado, relatório de validação, prova de importação e prova de atuação quando a alegação envolver controle físico. Evidência de importação não substitui evidência de atuação.
