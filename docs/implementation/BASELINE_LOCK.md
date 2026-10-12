# Baseline bloqueada — Skill 00

Data: 2026-10-12. Branch de trabalho: `work/guardrails-baseline`, derivada de `audit/rea-fase0` no commit `6bb1750`. Escopo: auditoria, teste e documentação; nenhum módulo de produção, writer, arquivo em `legacy/`, instalação do QGIS ou dado de origem foi alterado. O ZIP de instruções recebido permanece fora do commit, em `.codex-remote-attachments/`.

## Ambiente e estado inicial

- QGIS 3.44.13-Solothurn (alvo 3.44 LTR), Python do QGIS 3.12.13; testes unitários também executados com `py -3.12`.
- Os 227 arquivos-fonte `.py`, `.txt` e `.svg` comparados com a instalação do Planner no perfil QGIS têm SHA-256 idêntico (0 ausentes, 0 diferentes). A instalação não foi modificada.
- Árvore inicialmente limpa, exceto o anexo não rastreado fornecido pelo usuário. O Conversor em `C:\Users\fortu\Desktop\QGIS_Python_NDVI` permaneceu limpo.
- A baseline histórica `docs/baseline_etapa0/ag_2.9.20_export_hashes.json` não foi sobrescrita.

## Testes executados

| Projeto / verificação | Comando | Resultado | Duração aproximada |
| --- | --- | --- | --- |
| Planner, teste QGIS focal | `python-qgis-ltr.bat -m pytest tests/qgis/test_workspace_canonical_preview.py -q --disable-warnings` | 13 passed | 7,47 s |
| Planner, unitários e integração | `py -3.12 -m pytest tests/unit tests/integration -q --disable-warnings` | 1113 passed, 46 skipped, 111 subtests | 74,28 s |
| Planner, QGIS | `python-qgis-ltr.bat -m pytest tests/qgis -q --disable-warnings` | 242 passed, 23 subtests | 65,78 s |
| Conversor, sem coletor QGIS | `py -3.12 -m pytest tests --ignore=tests/test_qgis_canonical_collector.py -q --disable-warnings` | 196 passed, 1 skipped, 30 subtests | 47,51 s |
| Conversor, coletor QGIS | `python-qgis-ltr.bat -m unittest tests.test_qgis_canonical_collector -q` | 14 OK | 3,43 s |

Para os comandos `python-qgis-ltr.bat`, o executável é `C:\Program Files\QGIS 3.44.13\bin\python-qgis-ltr.bat`; os dois comandos do Conversor foram executados na raiz de seu repositório. Warnings observados: 941 na suíte focal, 4226 na suíte QGIS completa e avisos de depreciação `QgsField` no coletor; não foram tratados como falhas.

As sete falhas QGIS anteriores provinham do fixture que construía `FortSmartWorkspaceDialog` com `__new__` sem inicializar a base Qt. O fixture agora chama `QDialog.__init__` e inicializa seu atributo de prévia. Um teste adicional instancia o diálogo real, abre, processa eventos e fecha com QGIS/Qt inicializados. Isso demonstra abertura no ambiente de teste, não homologação visual interativa no QGIS do usuário.

## Entradas reais e exportação

O script existente `docs/baseline_etapa0/gerar_baseline.py` foi lido antes da execução. Foram usadas apenas as três pastas de talhão que ele já referencia, com cinco GeoPackages cada; nenhum parâmetro de máquina ou dado de campo foi inventado. O inventário [ag_source_inventory_20261012.json](../baseline_etapa0/ag_source_inventory_20261012.json) registra, para cada uma das 15 fontes, tamanho em bytes, SHA-256 do arquivo, CRS, tipo WKB, contagem de feições, hash da sequência de IDs e hash da geometria WKB. Todos os arquivos carregaram em `EPSG:31981`, CRS projetado métrico. As contagens são 78, 45 e 25 feições, respectivamente, para `talhao-6-a`, `talhao-6-b` e `th-6-a_b`.

O coletor e os writers existentes exportaram cada talhão duas vezes para diretórios temporários. [ag_all_profiles_20261012.json](../baseline_etapa0/ag_all_profiles_20261012.json) registra hashes por caminho normalizado e a comparação das duas execuções para os 11 perfis registrados:

| Perfil | Arquivos por talhão | Geração repetida no mesmo dia |
| --- | ---: | --- |
| `john_deere_dual` | 17 | estável |
| `john_deere_gs3` | 10 | estável |
| `john_deere_gen4` | 2 | estável |
| `isoxml_v4` | 2 | estável |
| `isoxml_v3` | 1 | estável |
| `cnh` | 2 | estável |
| `fendt` | 2 | estável |
| `jacto` | 5 | estável |
| `sendto2020` | 11 | estável |
| `stara` | 5 | estável |
| `precision_planting` | 2 | estável |

Total: 177 arquivos em 33 exportações por perfil/talhão; todas as repetições no mesmo dia tiveram hash igual. O inventário das entradas guarda bytes/IDs/CRS/geometrias; o snapshot dos arquivos exportados guarda hash, perfil e caminho, não tamanho nem IDs internos de cada formato. Esses campos não devem ser presumidos a partir do snapshot.

Comparação com a baseline histórica dos dois perfis nela presentes: 81 dos 84 arquivos conservaram o SHA-256 bruto. As únicas diferenças brutas foram os três `.dbf` de `SendTo2020`. Nos três, substituir *somente* os bytes 1–3 do cabeçalho DBF (data de 2026-10-12 para 2026-10-08, data da captura histórica) reproduziu exatamente o hash esperado. Assim, os 84/84 conteúdos comparados coincidem após normalização desse campo volátil; os hashes históricos originais continuam intactos. Uma comparação futura em outro dia deve normalizar explicitamente esses três bytes de cabeçalho, sem esconder diferenças em qualquer outro byte.

Durante a geração dos Shapefiles, GDAL avisou que campos `CLIENT`, `FARM`, `FIELD` e `NAME` de largura 255 foram limitados a 254. O aviso não impediu a geração, mas permanece como risco de truncamento de valores longos; não houve confirmação em equipamento. Para os nove perfis sem snapshot histórico, esta captura é o ponto inicial, não uma prova de ausência de regressão anterior.

O pacote solicitava novos fixtures sintéticos. Pela instrução explícita de não introduzir dados fictícios, não foram adicionados fixtures novos nem valores de máquina exemplificativos. Os testes já existentes cobrem coleta canônica e geometria de teste em `EPSG:31981`; a exportação acima usou fontes reais. Nenhuma distância ou área foi calculada em CRS geográfico nesta etapa.

## Gate e rollback

**Skill 00: PASS para baseline de software e geração de arquivos, com limites declarados.** As suítes estão verdes e os arquivos históricos comparáveis permanecem iguais após normalização comprovada da data DBF. **Não validado:** importação, leitura ou atuação em monitor físico; verificação visual manual do diálogo; ausência de truncamento quando nomes ultrapassam 254 caracteres. Não avançar para a Skill 01 sem aceite do usuário, conforme o pacote.

Rollback: a mudança desta branch limita-se a um fixture/teste, estes documentos e snapshots. Reverter o commit da branch restaura exatamente o código de teste anterior; nenhuma instalação ou fonte de dados precisaria ser revertida. Antes de qualquer alteração futura em writer, executar novamente as cinco suítes, comparar os 84 arquivos históricos com a normalização DBF delimitada e comparar os 177 arquivos desta captura, examinando qualquer diferença por perfil.
