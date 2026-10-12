# SKILL 01 — Relatório final

## Estado: **CONCLUSÃO TÉCNICA CONDICIONADA**

As verificações técnicas obrigatórias passaram: testes, exportações, chaves desligadas por padrão e preservação do trabalho paralelo. O estado **CONCLUÍDA E HOMOLOGADA** depende de uma única pendência: **a homologação visual no QGIS real**, que exige instalar o plugin no perfil. A instalação está preparada e testada, mas não foi autorizada nem executada.

A falha do trabalho paralelo citada na autorização da 0G **não se reproduz** no estado atual (seção 2). Por isso, ela não é mais uma condição.

## 1. Critério de homologação

| Verificação obrigatória | Situação | Evidência |
|---|---|---|
| Regressão do Planner sem QGIS | **aprovada** | 1085 passed, 46 skipped |
| Regressão do Planner no QGIS | **aprovada** | 228 passed, 0 failed |
| Regressão do Precision Ag | **aprovada** | 155 passed + 14 OK |
| Exportações iguais à linha de base | **aprovada** | 84/84 arquivos, 90/90 SHA-256, sem faltas nem sobras |
| Chaves desligadas por padrão | **aprovada** | 5/5 em `PERSISTED_FLAG_DEFAULTS`; nada gravado no perfil |
| Comportamento com as chaves desligadas igual ao anterior | **aprovada** | testes "chave desligada" em cada subfase; hashes; tempo de carga sem diferença mensurável |
| Trabalho paralelo preservado | **aprovada** | snapshots de hashes antes e depois de cada subfase; nenhum arquivo da pulverização foi tocado |
| Falha `test_spray_ab_reference_and_cross_flow` | **não reproduzível** | 3 repetições + suíte completa, todas passando; causa: execução durante edições simultâneas |
| Homologação visual no QGIS real | **pendente** | instalação não autorizada; scripts prontos em `docs/instalacao_0g/` |

## 2. Falha do trabalho paralelo

- **Reproduzida no estado atual?** Não:
  - arquivo isolado: 6/6;
  - com a persistência operacional: 7/7 em 3 repetições;
  - unitário do contrato: 7/7;
  - suíte QGIS completa: 228/228.
- **Causa da falha vista na 0F:** a suíte rodou entre cerca de 18h57 e 18h58, enquanto a frente de pulverização gravava `core/operational_generation.py` (18h57m18s), o próprio teste (18h57m54s) e `gui/fortsmart_workspace_dialog.py` (18h59m48s). Num estado intermediário, um segmento de desligamento por pneu ficou sem rastro causal, e a validação do contrato o rejeitou, como deve.
- **O que não foi feito, conforme a autorização:**
  - a validação de `tire_track_id` não foi enfraquecida;
  - o motor de pulverização e o contrato não foram modificados.
- **Recomendação ao responsável pela pulverização:**
  - `_causal_track` escolhe o rastro mais próximo sem limite de distância; exigir distância ≤ meia largura de exclusão e recusar com diagnóstico;
  - criar um teste para o caso "segmento de pneu sem rastro compatível".

  Concordo com a recomendação recebida: tratar isso numa correção própria da frente de pulverização, fora da SKILL 01.

## 3. O que a SKILL 01 entregou

Detalhes em `ETAPA_0_FECHAMENTO.md`.

- **Contexto do projeto (0B):** um serviço somente leitura que responde, sem adivinhar pelo nome da camada:
  - qual é o talhão, a fazenda, a camada ativa, o papel, a seleção e o CRS;
  - diagnósticos do que está ambíguo.
- **Organização lógica (0C):** a aba "Camadas" com a árvore 01–05 por talhão, só apresentação, e visibilidade reversível.
- **Painel AgroCAD (0D):** Editor, Obstáculos, Terreno e Planejamento no dock, usando só ações já existentes. Correção do ciclo de vida do dock.
- **Seleção e prévia (0E):** o leitor da seleção nativa com a origem do identificador estável, e um gerenciador central de prévias sem camadas.
- **Inspetor DEM (0F):** fonte, CRS, resolução, NoData, unidades e cobertura do talhão, somente leitura, com a leitura em segundo plano.
- **Fechamento (0G):**
  - regressão final;
  - explicação dos números de hash;
  - contrato de tráfego controlado baseado no código real;
  - instalação controlada com backup e reversão.

## 4. Riscos

| Risco | Classe | Tratamento |
|---|---|---|
| Homologação visual não feita | **bloqueante** para "HOMOLOGADA" | instalar com `instalar_planner_controlado.ps1 -Executar` depois de autorizado; roteiro na seção 6 de `ETAPA_0G_REGRESSAO_FINAL.md` |
| A instalação também atualiza arquivos da pulverização no perfil | **coordenação** | o perfil já tem arquivos da pulverização instalados pelo responsável; combinar a janela de instalação; a reversão restaura o perfil anterior |
| Atribuição causal pelo rastro mais próximo (`_causal_track`) | **não bloqueante**; correção própria da pulverização | seção 2 |
| Exportação de desligamentos para a máquina sem o contrato operacional | **não bloqueante para a SKILL 01**; relevante para a SKILL de exportação | `CONTRATO_TRAFEGO_CONTROLADO_V1.md`, seção 6: o contrato existe, mas nenhum writer o consome; o ISOXML lê `13_Shutoff` direto da camada |
| DEM não invalidado ao editar o limite | não bloqueante | clicar de novo em "Verificar DEM" |
| Elevação e NoData por amostra | não bloqueante | declarado na tela |
| Unidade vertical só na sessão | melhoria futura | — |
| Limites ambíguos bloqueiam o DEM | não bloqueante (desejado) | o diagnóstico lista os limites |
| Banda legada do `CaptureABLineTool` | não bloqueante, pré-existente | etapa própria de migração de prévias |
| Identificadores duplicados fora da seleção | não bloqueante | melhoria futura com índice |

## 5. Recomendações

1. **Autorizar a instalação controlada** numa janela combinada com a frente de pulverização e fazer o teste visual do roteiro. Se tudo passar, o estado sobe para **CONCLUÍDA E HOMOLOGADA**.
2. **Corrigir `_causal_track` dentro da frente de pulverização**, com teste, antes de qualquer exportação de desligamentos.
3. **Exportação de desligamentos para a máquina** só via `ExportOperationBundle` (geração `ACTIVE`), com relatório de perda semântica e linha de base própria. Não usar a camada `13_Shutoff` diretamente.
4. **Na SKILL 02:**
   - reutilizar o `ProjectContextService`, o leitor de seleção e o gerenciador de prévias;
   - não criar mecanismos paralelos;
   - manter o padrão de chave desligada, backup e parada por subfase.
5. **Documentações antigas:** usar "84 arquivos / 90 valores SHA-256" daqui em diante. O "96" da 0C, 0D e 0E era uma contagem com 6 marcadores a mais, sem efeito na conclusão.

## 6. Documentos

- `docs/ETAPA_0_AUDITORIA.md` (0A)
- `docs/ETAPA_0B_CONTEXTO.md` a `docs/ETAPA_0F_INSPETOR_DEM.md`
- `docs/ETAPA_0G_REGRESSAO_FINAL.md`
- `docs/ETAPA_0_FECHAMENTO.md`
- `docs/CONTRATO_TRAFEGO_CONTROLADO_V1.md`
- `docs/SKILL_01_RELATORIO_FINAL.md` (este)
- `docs/instalacao_0g/instalar_planner_controlado.ps1` e `reverter_planner_controlado.ps1`

A SKILL 02 não foi iniciada.
