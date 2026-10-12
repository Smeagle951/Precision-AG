# FortSmart Precision Planner

Plugin QGIS para planejamento e validacao de operacoes agricolas georreferenciadas.

O projeto nasce a partir do legado AAP GIS v2 e sera migrado de forma incremental, sem reescrita total. O foco inicial e confiabilidade: GeoPackage como banco mestre, calculos metricos em CRS projetado, validacao antes da exportacao e perfis de equipamento com evidencia.

## Produto

- Nome principal: FortSmart Precision Planner
- Nome comercial: FortSmart Agricultura de Precisao
- Plataforma alvo inicial: QGIS 3.44 LTR
- Banco mestre: GeoPackage por projeto
- Relevo: QGIS/GDAL como base; SAGA opcional
- Escopo inicial: planejamento de escritorio e preparacao de arquivos

## Estrutura

```text
plugin/fortsmart_precision/   Plugin QGIS novo
legacy/aap_gis_v2/            Copia preservada do AAP GIS atual
tests/                        Testes unitarios, integracao, regressao e fixtures
docs/                         Arquitetura, manuais, monitores e validacoes
scripts/                      Utilitarios de auditoria e desenvolvimento
```

## Regras essenciais

- Nao alterar `legacy/` durante a migracao.
- Nunca calcular area, distancia, buffer ou offset em CRS geografico.
- Nao inventar parametros agricolas ou de maquinas.
- Nao declarar compatibilidade com monitor sem evidencia documentada.
- Toda exportacao deve gerar validacao rastreavel.

## Estado atual

Fase 0 em andamento: inventario, auditoria tecnica, matriz de riscos e fundacao do plugin.

# Precision-AG

