# Relatorio de testes - Fase 2 importacao e inspecao

Data: 2026-07-10

## Escopo

Validacao automatizada da primeira versao de:

- `InputInspector`;
- `InputValidator`;
- `ImportService`;
- schema expandido para `fs_source_files`, `fs_operations` e `fs_validations`;
- algoritmos Processing de inspecao/importacao;
- copia nao destrutiva e registro por checksum.

## Comandos executados

```powershell
& "C:\Users\fortu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m unittest discover -s tests -p "test_*.py"
```

Resultado:

```text
Ran 25 tests in 1.249s

OK
```

```powershell
& "C:\Users\fortu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m py_compile (Get-ChildItem -Recurse -Filter *.py | Where-Object { $_.FullName -notmatch '\\legacy\\' } | ForEach-Object { $_.FullName })
```

Resultado: compilacao concluida sem erros.

## Cobertura adicionada

- Shapefile completo com CRS geografico.
- Shapefile sem `.prj`.
- Shapefile sem `.shx`.
- GeoJSON com geometria vazia.
- GeoPackage com multiplas camadas e tabelas internas ignoradas.
- KMZ com multiplos KML internos.
- CSV exigindo X/Y, CRS e separador explicitos.
- Importacao GeoJSON com copia original, registro e normalizacao Polygon -> MultiPolygon.
- Duplicidade por checksum.
- Falha durante importacao sem deixar linhas parciais no banco.
- Projeto movido de pasta com caminho relativo preservado.

## Limitacoes conhecidas

- Testes rodam fora do QGIS; a exibicao da camada no mapa ainda nao foi validada.
- Reprojecao geometrica real ainda nao foi implementada sem QGIS/GDAL.
- Shapefile, GeoPackage multi-camada e KMZ multi-KML sao inspecionados e validados; a importacao espacial completa exige selecao de camada e motor GIS.
- A coluna `geom` guarda representacao derivada inicial para testes; a gravacao final compatível com visualizacao plena no QGIS sera consolidada na etapa com PyQGIS/GDAL.

