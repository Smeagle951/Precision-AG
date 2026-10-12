# Riscos de regressão e correções prioritárias — Fase 0

| Prioridade | Risco e evidência | Verificação/correção seguinte | Proteção |
| --- | --- | --- | --- |
| P1 | Sete testes QGIS de regeneração/persistência falham no mesmo `RuntimeError`; `tests/qgis/test_workspace_canonical_preview.py` usa `FortSmartWorkspaceDialog.__new__` sem inicializar Qt | corrigir fixture, repetir os sete cenários e incluir teste do diálogo inicializado normalmente | não mudar lógica de limpeza sem reproduzir falha em uso real |
| P1 | `core/operational_generation.py:_causal_track` escolhe o rastro mais próximo sem limite de distância | exigir interseção/faixa causal com tolerância justificada e testar ausência de rastro | rejeitar relação causal incerta; não criar `tire_track_id` fictício |
| P1 | `docs/CONTRATO_TRAFEGO_CONTROLADO_V1.md` informa que nenhum exportador consome o contrato de desligamento | provar suporte por perfil e gerar relatório semântico antes de integrar | não exportar `WORK_OFF` como comando de controlador por inferência |
| P2 | `core/visual_coverage_engine.py` compara cada par de faixas, custo quadrático | medir com projeto sintético grande; considerar índice espacial preservando resultados | comparar áreas/camadas com baseline antes da otimização |
| P2 | Planner declara QGIS mínimo 3.34/máximo 4.99 e Conversor 3.16/4.99, enquanto alvo operacional declarado é 3.44 LTR | alinhar metadados somente após decisão de suporte e testes nas versões anunciadas | não anunciar compatibilidade 4.x por intervalo de metadata |
| P2 | O contrato entre plugins depende de `fortsmart_role` e nomes reais dos grupos | congelar fixtures e hashes de coleta/exportação | preservar IDs, geometrias, ordem e nomes canônicos |
| P2 | O writer SendTo2020 do FortSmart filtra só `EXTERNAL_BOUNDARY`, enquanto REA mostra chamadas para linhas AB/curvas no exportador .NET do AgroCAD instalado | investigar formato produzido em cenário sintético, comparar com especificação e provar importação antes de ampliar o writer | não alterar exportador nem declarar controle de semeadura com base apenas em nomes de métodos |
| P3 | REA 6.4.0 requer Node >=22.19; Node instalado é 22.14 | usar Node temporário 22.19, como nesta auditoria, e manter perguntas específicas por assembly | nenhuma inferência funcional a partir apenas de assinatura/nomes |

Não foram identificados “todos os problemas” por esta auditoria. A lista contém riscos demonstrados por falha reproduzida ou revisão localizada e serve para priorizar correções com testes. O histórico `docs/ETAPA_0G_REGRESSAO_FINAL.md` pertence a uma versão anterior e não sobrepõe a linha de base desta execução.
