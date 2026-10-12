# Auditoria Tecnica Inicial - FortSmart Precision

Data: 2026-07-10

## Escopo

Auditoria inicial do legado AAP GIS v2 preservado em `legacy/aap_gis_v2`, conforme plano mestre FortSmart Precision. Esta fase nao refatora o legado; apenas classifica o que existe, aponta riscos e define a ordem de migracao.

## Inventario automatico

Arquivo gerado: `INVENTARIO_FUNCOES.csv`

Resumo:

| Tipo | Quantidade |
|---|---:|
| Funcoes de modulo | 190 |
| Classes | 10 |
| Metodos | 54 |
| Total | 254 |

Arquivos com maior concentracao de funcoes/classes:

| Entradas | Arquivo |
|---:|---|
| 31 | `legacy/aap_gis_v2/aap_gis_interface_funcional.py` |
| 24 | `legacy/aap_gis_v2/aap_part9_linhas_agronomicas.py` |
| 21 | `legacy/aap_gis_v2/aap_part8_exportacao_expanded.py` |
| 14 | `legacy/aap_gis_v2/aap_part1_setup.py` |
| 12 | `legacy/aap_gis_v2/aap_part6_relevo.py` |
| 12 | `legacy/aap_gis_v2/aap_part8_exportacao.py` |

## O que pode ser aproveitado

- Separacao inicial por etapas (`aap_part1` a `aap_part13`).
- Fluxo completo em `aap_part8_exportacao.py` e versao expandida em `aap_part8_exportacao_expanded.py`.
- Conhecimento agronomico ja codificado: bordadura, plantio, pulverizacao, relevo, zonas, conformidade e ISOXML.
- Interface QGIS rica em `aap_gis_interface_funcional.py`, aproveitavel como referencia de UX.
- Plugin QGIS legado em `AAP_GIS_Plugin`, aproveitavel como aprendizado, mas nao como base direta.
- Documentacao agricola em `AAP_GIS_README.md` e guia de monitores.

## Problemas confirmados

### Caminhos absolutos e erro de pasta

Varios arquivos apontam para `c:\Users\fortu\Desktop\PYTON`, enquanto o workspace atual e `C:\Users\fortu\Desktop\PYTHON`.

Impacto: importacoes e instaladores podem falhar em qualquer maquina diferente da original.

Exemplos:

- `aap_gis_interface_funcional.py`
- `aap_botao_qgis.py`
- `aap_import.py`
- `install_aap_gis_qgis.py`
- `copiar_plugin_automatico.py`
- `INSTALAR_AAP_GIS_PLUGIN.cmd`

### Chamadas incompatíveis entre API/interface e motor

`aap_simple_api.py` e `aap_gis_interface_funcional.py` chamam funcoes com argumentos que nao existem ou em posicoes incorretas.

Exemplos:

- `gerar_bordadura(..., projeto_path=...)` no fluxo simples, mas a funcao legado nao recebe `projeto_path`.
- `gerar_linhas_pulverizacao(..., cultura=..., alinhar_plantio=True)`, mas a funcao legado nao recebe esses parametros.
- `exportar_para_shapefile(id_talhao=...)`, mas a funcao legado espera uma camada e caminho.
- `gerar_linhas_plantio(id_talhao, cultura, metodo)` passa o metodo como `espacamento_m`.
- `gerar_linhas_pulverizacao(id_talhao, largura, sobreposicao, cultura)` passa a cultura como `incluir_bordadura`.

Impacto: a experiencia visual promete um fluxo unico, mas cliques podem produzir erro ou resultado incorreto.

### Erro direto no plugin legado

`AAP_GIS_Plugin/aap_plugin.py` chama `talhao_layer[0].crrs()`. O esperado no PyQGIS e `crs()`.

Impacto: exportacao temporaria do talhao falha no plugin.

### Variavel indefinida

`aap_simple_api.py` retorna `nome_talhao` dentro de `gerar_resultado_simples()`, mas a variavel nao existe no escopo da funcao.

Impacto: fluxo simples pode falhar depois de processar dados.

### CRS e metricas

Ha varios usos de `geometry().area()`, `buffer()` e `processing.run()` que precisam ser protegidos por regra de CRS projetado metrico. O legado assume muitas vezes que a camada ja esta em UTM.

Impacto: area, distancia, bordadura, pulverizacao e cobertura podem ficar erradas se a origem estiver em EPSG:4326 ou CRS desconhecido.

### Dependencias nao declaradas

`requirements.txt` do legado declara apenas `xhtml2pdf`, mas o codigo tambem usa:

- PyQGIS/QGIS Processing
- GDAL/SAGA via QGIS
- `numpy`
- `scikit-learn` opcional
- `matplotlib`
- `fastapi`, `pydantic`, `streamlit`, `folium`, `streamlit-folium` em esqueletos

Impacto: instalacao nao reproduzivel.

## Decisao tecnica inicial

Nao corrigir o legado diretamente. A partir de agora:

1. `legacy/aap_gis_v2` fica congelado.
2. Novos codigos entram em `plugin/fortsmart_precision`.
3. Cada migracao deve ganhar teste e criterio de aceite.
4. A primeira migracao funcional deve ser importacao + validacao de CRS + calculo de area.

