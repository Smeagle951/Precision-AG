# Guia inicial QGIS - FortSmart Precision

Este guia cobre a primeira etapa visual do plugin: painel principal e importacao inicial.

## Abrir o painel

1. Reinicie o QGIS depois de instalar ou atualizar o plugin.
2. Acesse `FortSmart Precision > Abrir painel principal`.
3. O painel `FortSmart Precision` deve aparecer na lateral direita.

## Criar projeto

1. No painel, clique em `Criar projeto`.
2. Escolha a pasta do projeto.
3. Informe:
   - nome do projeto;
   - fazenda/propriedade;
   - safra;
   - CRS mestre, por exemplo `EPSG:31981`.
4. Confirme a criacao.

O plugin cria:

```text
00_ORIGINAIS/
01_BANCO/fortsmart.gpkg
02_RASTERS/
03_EXPORTACOES/
04_RELATORIOS/
05_BACKUPS/
06_LOGS/
fortsmart_project.json
```

## Importar camada

1. Carregue uma camada de talhao no QGIS.
2. Selecione a camada no painel de camadas.
3. Clique em `Importar` no painel FortSmart.
4. Escolha uma origem:
   - camada ativa;
   - outra camada aberta;
   - arquivo selecionado.
5. Confira nome, fonte, CRS, geometria, feicoes e campos.
6. Escolha o tipo de dado:
   - limite cadastral;
   - limite operacional;
   - obstaculo;
   - exclusao;
   - carreador;
   - outro.
7. Verifique erros e avisos.
8. Se o arquivo possuir camadas internas, selecione a camada desejada.
9. Clique em `Importar`.

## O que acontece

- A camada original nao e alterada.
- Para camadas abertas no QGIS, o plugin cria uma copia temporaria em GeoJSON no CRS mestre do projeto.
- O `ImportService` copia o original/temporario para `00_ORIGINAIS`.
- O banco registra arquivo, operacao e validacoes.
- Uma camada visual e gravada no GeoPackage do projeto quando o QGIS permite.
- Se a gravacao em GeoPackage falhar, uma pre-visualizacao GeoJSON e adicionada ao mapa.
- O QGIS aplica simbologia inicial e da zoom na camada.
- Um relatorio HTML e gravado em `04_RELATORIOS`.

## Limitacoes desta etapa

- O fluxo visual ainda e inicial e nao substitui o assistente completo de 8 etapas.
- A tabela auditavel `geom` do motor ainda nao substitui totalmente a camada espacial visual gravada pelo QGIS.
- A selecao interna foi iniciada para arquivos multicamada, mas ainda precisa de validacao manual com amostras reais de campo.
- Nao avance para bordadura, plantio ou pulverizacao antes de validar este fluxo com arquivos reais.
