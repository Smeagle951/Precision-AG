# Regras do repositorio FortSmart Precision

- Nunca calcular area ou distancia em CRS geografico.
- Nunca inventar parametros de maquina.
- Nao alterar arquivos em `legacy/`.
- Toda nova funcao deve possuir teste.
- Execute os testes relevantes antes de concluir.
- Nao declarar compatibilidade com monitor sem evidencia.
- Exportacoes devem gerar relatorio de validacao.
- Use `qgis.PyQt`, nao imports diretos de `PyQt5`.
- Mantenha QGIS 3.44 LTR como alvo inicial.
- Documente mudancas no `CHANGELOG.md`.

## Estrategia de migracao

O legado AAP GIS fica preservado em `legacy/aap_gis_v2`. Novos recursos entram em `plugin/fortsmart_precision` como servicos, algoritmos de Processing, validadores e exportadores testaveis. Migrar uma funcao por vez, com fixture e teste de regressao quando aplicavel.

