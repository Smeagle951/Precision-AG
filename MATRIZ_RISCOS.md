# Matriz de Riscos - FortSmart Precision

| ID | Risco | Evidencia inicial | Impacto | Probabilidade | Severidade | Mitigacao |
|---|---|---|---|---|---|---|
| R01 | Calculo metrico em CRS geografico ou desconhecido | Uso direto de `geometry().area()`, `buffer()` e offsets no legado | Area, bordadura, linhas e cobertura incorretas | Alta | Critica | Criar `core/crs.py` e bloquear operacoes metricas sem CRS projetado |
| R02 | Caminhos absolutos quebrando instalacao | Varios `Desktop\\PYTON` hardcoded | Plugin falha fora da maquina original | Alta | Alta | Remover caminhos fixos na nova arquitetura |
| R03 | Interface chama motor com parametros errados | Chamadas posicionais incorretas em `aap_gis_interface_funcional.py` | Resultado errado ou excecao em clique | Alta | Alta | GUI nova deve chamar algoritmos Processing ou servicos tipados |
| R04 | API simples inconsistente | `aap_simple_api.py` usa parametros inexistentes | Fluxo unico nao confiavel | Alta | Alta | Substituir por caso de uso novo em cima do pipeline migrado |
| R05 | Compatibilidade de monitor declarada sem evidencia | Exportadores por marca existem, mas sem amostras reais registradas | Arquivo pode nao importar no equipamento | Media | Alta | Perfil experimental ate haver amostra, simulador ou campo |
| R06 | Dependencia obrigatoria do SAGA | Relevo usa varios algoritmos `saga:*` | Ferramentas falham em QGIS sem SAGA | Media | Media | QGIS/GDAL como base, SAGA como opcional |
| R07 | Legado grande e monolitico | Interface com 1085 linhas; linhas agronomicas com 1277 linhas | Refatoracao arriscada | Alta | Media | Migracao incremental por funcao, com testes |
| R08 | Dados ficticios na interface ou relatorios | KPIs simplificados e mensagens estimadas | Usuario pode interpretar como resultado real | Media | Alta | Marcar estimativas explicitamente; remover metricas ficticias do MVP |
| R09 | Exportacao Shapefile perde atributos | Limite de 10 caracteres e tipos DBF | Perda silenciosa de dados | Alta | Media | Mapeamento unico de campos e relatorio de perdas |
| R10 | ISOXML cedo demais | Modulo existe antes da base estar estabilizada | Complexidade e falso senso de compatibilidade | Media | Media | Adiar ISOXML ate SHP/KML/GeoPackage e validadores estarem estaveis |

## Prioridade de ataque

1. R01: CRS e metricas.
2. R02/R03/R04: confiabilidade de instalacao e chamada.
3. R09: validacao de exportacao aberta.
4. R05: perfis de monitores com evidencia.
5. R06/R10: dependencias e formatos avancados.

