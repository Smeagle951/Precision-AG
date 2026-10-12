# Plano de Migracao - FortSmart Precision

## Estrategia

Migracao por estrangulamento progressivo. O legado AAP GIS v2 permanece congelado em `legacy/aap_gis_v2`; funcoes sao migradas uma por vez para `plugin/fortsmart_precision`, com testes e criterio de aceite.

## Fase 0 - Inventario e fundacao

Status: em andamento.

Entregas:

- `legacy/aap_gis_v2` criado.
- `AGENTS.md` criado.
- Plugin minimo `plugin/fortsmart_precision` criado.
- `INVENTARIO_FUNCOES.csv` gerado.
- Auditoria, mapa de arquitetura, matriz de riscos e plano de migracao criados.

Criterio de saida:

- Plugin compila sintaticamente.
- Estrutura nova nao depende de caminho absoluto local.
- Legado preservado.

## Fase 1 - Nucleo de CRS e projeto

Status: iniciada.

Objetivo: criar base segura para qualquer operacao metrica.

Entregas planejadas:

- `core/crs.py` - iniciado
- `core/project_manager.py` - iniciado
- `core/geometry_metrics.py`
- `database/schema.py` - iniciado
- `database/migrations/migration_001_initial.py` - iniciado
- Algoritmo Processing para criar projeto/GeoPackage vazio
- Testes unitarios para:
  - detectar CRS geografico
  - detectar CRS projetado metrico
  - bloquear area/distancia em CRS invalido
  - calcular zona UTM sugerida por centroide
- Testes unitarios e de integracao para:
  - criar projeto FortSmart
  - impedir sobrescrita sem confirmacao
  - criar GeoPackage inicial
  - registrar versao do esquema
  - registrar tabelas e camadas no `gpkg_contents`
  - validar idempotencia da migracao atual

Criterio de aceite:

- Nenhuma area/distancia e calculada se CRS for desconhecido ou geografico.
- GeoPackage inicial e criado sem caminho absoluto.

## Fase 2 - Importacao e validacao

Status: pausada como prioridade principal.

Objetivo: migrar importacao de SHP, KML/KMZ, GeoJSON e GeoPackage.

Entregas planejadas:

- `io/input_inspector.py` - iniciado
- `validators/input_validator.py` - iniciado
- `io/import_service.py` - iniciado
- `models/input_report.py` - iniciado
- Algoritmo `Inspecionar arquivo de entrada` - iniciado
- Algoritmo `Importar limite de talhao` - iniciado
- Copia preservada do arquivo original - iniciado
- Checksum SHA-256 - iniciado
- Relatorio de importacao - iniciado
- Validacao de geometria, CRS e atributos minimos - iniciado

Criterio de aceite:

- Fixtures simples importam com area correta em hectares.
- Arquivos sem CRS falham explicitamente.
- Arquivo original nao e sobrescrito.

Limites atuais:

- Reprojecao real ainda depende da proxima etapa com runtime QGIS/GDAL.
- GeoPackage, Shapefile e KMZ multi-camada sao inspecionados/validados, mas a importacao espacial exige selecao de camada e motor GIS.
- GeoJSON projetado e CSV simples ja possuem fluxo inicial de copia, registro e escrita derivada no GeoPackage.

## Etapa visual 1 - Painel e importacao ativa

Status: iniciada.

Entregas:

- `gui/main_dock.py` - painel lateral inicial.
- `gui/start_page.py` - tela inicial quando nenhum projeto esta aberto.
- `gui/import_wizard.py` - assistente inicial de importacao.
- `gui/widgets/layer_summary_widget.py` - resumo de camada.
- `gui/widgets/validation_results_widget.py` - tabela de validacao.
- `gui/widgets/project_status_widget.py` - status do projeto.
- `gui/controllers/import_controller.py` - controlador QGIS do fluxo de importacao.
- Menu `FortSmart Precision > Abrir painel principal`.
- Menu `FortSmart Precision > Criar projeto`.
- Menu `FortSmart Precision > Abrir projeto`.
- Menu `FortSmart Precision > Importar`.
- Toolbar com atalho para painel e importacao.

Criterio de aceite parcial:

- Painel mostra dados reais do projeto e da camada ativa.
- Assistente usa camada ativa, camada aberta ou arquivo selecionado.
- Usuario escolhe o tipo de dado antes de importar.
- Camada original nao e alterada.
- Camada ativa e exportada temporariamente no CRS mestre e enviada ao `ImportService`.
- Resultado e carregado como pre-visualizacao no mapa quando o GeoJSON temporario e valido.

Limites atuais:

- A tela cria a primeira experiencia visual, mas ainda nao substitui um wizard completo de 8 etapas.
- Simbologia inicial foi aplicada; paleta configuravel ainda nao existe.
- A GUI grava uma camada GeoPackage real para visualizacao quando o QGIS exporta com sucesso, com fallback para pre-visualizacao GeoJSON.
- A tabela `geom` interna usada pelo motor continua como registro derivado inicial; consolidacao total entre tabela auditavel e camada espacial final ainda e etapa pendente.

## MVP prioritario - Gerador de Linhas Agricolas

Status: iniciado.

Objetivo: entregar o primeiro recurso agricola funcional antes de aprofundar o assistente generico de importacao.

Entregas:

- `gui/agricultural_lines_dialog.py` - tela visual com abas Talhao, Linha A-B, Bordadura e Operacao.
- `gui/maptools/capture_ab_line_tool.py` - captura de dois pontos A-B diretamente no mapa.
- `domain/agricultural_lines.py` - regras agricolas para linhas paralelas, plantio, pulverizacao e macho/femea.
- `domain/operation_width.py` - comparacao de largura informada/calculada e meias larguras com offset lateral.
- `domain/planting_configuration.py` - configuracao de plantadeira, posicoes fisicas e encontro entre passadas.
- `domain/spraying_configuration.py` - configuracao de barra, bicos, remonte e espacamento efetivo.
- `domain/headland_layout.py` - distancias centrais de bordadura por passada.
- `domain/seed_corn_planning.py` - motor de milho semente com padrao global F/M1/M2 entre passadas.
- `core/line_geometry.py` - geometria 2D testavel para offsets, recorte por poligono, buracos e multipartes.
- `core/parallel_pass_engine.py` - motor comum de passadas com A-B como centro operacional.
- `core/coverage_strip_engine.py` - geracao de faixas de cobertura a partir das passadas.
- `algorithms/create_parallel_agricultural_lines.py` - algoritmo Processing equivalente.
- `algorithms/create_operation_passes.py` - algoritmo Processing para passadas centrais de operacao.
- `gui/operation_configuration_dialog.py` - tela unica de configuracao operacional.
- `tests/unit/test_agricultural_lines.py` - cobertura inicial do motor.
- `tests/unit/test_operation_planning.py` - cobertura de largura, bordadura, plantio, pulverizacao e milho semente.
- `tests/qgis/test_agricultural_lines_qgis.py` - ponto de entrada para validacao dentro do QGIS.

Criterio de aceite:

- Usuario seleciona talhao real ja aberto no QGIS.
- Usuario desenha ou seleciona uma linha A-B.
- Espacamentos de 18 m e 36 m geram pre-visualizacao recalculavel.
- Extensao padrao de 20 m prolonga os segmentos alem do limite.
- Bordadura interna de 36 m usa o limite interno para gerar linhas.
- Resultado pode ser salvo em GeoPackage ou Shapefile e reaberto depois.
- CRS geografico, como `EPSG:4326` ou `EPSG:4674`, e bloqueado.
- A tela `Configuracao da Operacao Agricola` mostra plantio, pulverizacao, bordadura, A-B, faixas e passadas pelo mesmo motor comum.
- O milho semente 6F+1M e calculado pela sequencia global de linhas fisicas, sem reiniciar a cada passada.

Limites atuais:

- A ferramenta usa camadas ja abertas no QGIS; o assistente generico completo de importacao fica para depois.
- A camada de bordadura existente aparece na interface, mas a consolidacao espacial dessa opcao ainda sera detalhada.
- Bordadura acompanhando limite ainda fica representada por reserva/limite interno; linhas de contorno complexas e relatorio completo de gargalos exigem evolucao QGIS especifica.
- Saidas separadas de milho semente ja existem no dominio, mas a exportacao visual por camada `seed_*` ainda sera consolidada na GUI.
- ISOXML, formatos proprietarios, giros cinematicos, zonas de manejo, terreno e multiplos monitores continuam fora do MVP.

## Fase 3 - Limites, obstaculos e limite operacional

Objetivo: separar limite cadastral, limite operacional, obstaculos e areas de exclusao.

Criterio de aceite:

- Obstaculos descontados sem alteracao silenciosa do limite cadastral.
- Multipartes tratadas com rastreabilidade.

## Fase 4 - Bordaduras

Objetivo: migrar bordadura interna com analise de gargalos.

Criterio de aceite:

- Largura solicitada nao e alterada silenciosamente.
- Relatorio indica partes perdidas, gargalos e componentes.

## Fase 5 - Plantio

Status: iniciada via motor Precision Lines.

Objetivo: gerar linha mestra, linhas fisicas e passadas separadamente.

Entregas iniciadas:

- `domain/machine_model.py`, `domain/precision_project.py`
- `core/guidance_engine.py`, `core/row_engine.py`, `core/boundary_engine.py`
- `core/precision_lines_engine.py`

Criterio de aceite:

- Espacamento validado com tolerancia inicial de 1 cm.
- Linhas fisicas e passadas nao sao misturadas.

## Fase 6 - Pulverizacao

Status: iniciada via motor Precision Lines.

Objetivo: separar largura nominal, sobreposicao total e distancia entre passadas.

Entregas iniciadas:

- `core/tramline_engine.py`, `core/shutoff_engine.py`
- presets Uniport 5030 (103 x 0,35 m)

Criterio de aceite:

- Interface e algoritmo mostram unidades e base da sobreposicao.
- Cobertura validada contra limite operacional.

## Precision Lines v2 — Obstacle Avoidance

Status: iniciada.

Entregas:

- `domain/obstacle_model.py`, `application_zone.py`, `guidance_reference.py`, `avoidance_configuration.py`
- `core/obstacle_engine.py`, `obstacle_buffer_engine.py`, `path_smoothing_engine.py`, `obstacle_validation_engine.py`
- Integracao no pipeline antes de tramlines/shutoff
- GUI `obstacle_avoidance_dialog.py` e algoritmos Processing de simulacao
- Teste de referencia `test_circular_obstacle_application_ring_18m`

Criterio de aceite:

- Anel concetrico com raio = meia largura operacional (+ margens)
- Trajetoria retorna a linha original apos desvio
- Desvio nao atravessa zona do obstaculo

## Fase 7 - Exportacao aberta

Objetivo: exportar Shapefile, KML/KMZ e GeoPackage reimportaveis.

Criterio de aceite:

- SHP gera SHP, SHX, DBF, PRJ e CPG quando aplicavel.
- Nomes de campos possuem ate 10 caracteres e unicidade.
- Relatorio de validacao acompanha o pacote.

## Fase 8 - Primeiro monitor real

Objetivo: validar um perfil especifico com evidencia.

Criterio de aceite:

- Modelo, firmware, tipo de dado, formato e evidencia documentados.
- Status muda de experimental para validado somente apos teste.

## Itens fora do MVP inicial

- ISOXML completo.
- Giros cinematicos certificados.
- Compatibilidade ampla com varios monitores.
- Recomendacao agronomica automatica sem metodologia validada.
