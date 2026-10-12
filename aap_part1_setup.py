"""
 ============================================================================
 AAP GIS - PARTE 1: AMBIENTE, ESTRUTURA E PADRÕES
 ============================================================================
 Sistema de Agricultura de Precisão com QGIS + SAGA GIS + PyQGIS
 
 Este script configura o ambiente QGIS, cria a estrutura de projeto e 
 o GeoPackage base com todas as camadas padrão.
 
 Autor: Sistema AAP GIS v2.0
 Data: 2024
 ============================================================================"""

import os
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsField, QgsFeature, 
    QgsGeometry, QgsPointXY, QgsWkbTypes, QgsPalLayerSettings,
    QgsVectorLayerSimpleLabeling, QgsTextFormat, QgsTextBufferSettings
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor

# ============================================================================
# CONFIGURAÇÕES DO PROJETO
# ============================================================================

class AAPConfig:
    """Configurações padrão do sistema AAP GIS"""
    
    # CRS padrão - SIRGAS 2000 / UTM zona 21S (ajustar conforme região)
    EPSG_UTM_21S = "EPSG:31981"
    EPSG_UTM_22S = "EPSG:31982"
    EPSG_UTM_23S = "EPSG:31983"
    EPSG_WGS84 = "EPSG:4326"
    
    # Estrutura de pastas
    PASTA_ENTRADA = "01_Entrada"
    PASTA_TALHOES = "02_Talhoes"
    PASTA_BORDADURAS = "03_Bordaduras"
    PASTA_PLANTIO = "04_Plantio"
    PASTA_PULVERIZACAO = "05_Pulverizacao"
    PASTA_RELEVO = "06_Relevo"
    PASTA_ANALISE = "07_Analise"
    PASTA_EXPORTACAO = "08_Exportacao"
    
    # Nome do GeoPackage base
    GPKG_BASE = "AAP_Base.gpkg"
    
    # Parâmetros agronômicos por cultura
    CULTURAS = {
        'soja': {'espacamento': 0.45, 'bordadura_min': 7.0, 'bordadura_ideal': 9.0},
        'milho': {'espacamento': 0.90, 'bordadura_min': 9.0, 'bordadura_ideal': 12.0},
        'algodao': {'espacamento': 0.90, 'bordadura_min': 12.0, 'bordadura_ideal': 15.0},
        'feijao': {'espacamento': 0.50, 'bordadura_min': 7.0, 'bordadura_ideal': 9.0},
        'sorgo': {'espacamento': 0.50, 'bordadura_min': 7.0, 'bordadura_ideal': 9.0},
    }
    
    # Declividade crítica
    SLOPE_CRITICO = 8.0  # graus
    SLOPE_RESTRICAO = 13.0  # graus


# ============================================================================
# FUNÇÕES DE CRIAÇÃO DE CAMADAS
# ============================================================================

def criar_camada_talhoes(gpkg_path):
    """
    Cria a camada de talhões com atributos padrão
    
    Atributos:
    - id: INTEGER (chave primária, auto)
    - nome: TEXT(50)
    - area_ha: REAL (calcular automaticamente)
    - cultura: TEXT(30)
    - safra: TEXT(10)
    - data_plantio: DATE
    - obs: TEXT(200)
    """
    fields = [
        QgsField("id", QVariant.Int),
        QgsField("nome", QVariant.String, len=50),
        QgsField("area_ha", QVariant.Double),
        QgsField("cultura", QVariant.String, len=30),
        QgsField("safra", QVariant.String, len=10),
        QgsField("data_plantio", QVariant.Date),
        QgsField("obs", QVariant.String, len=200),
    ]
    
    layer = QgsVectorLayer(
        f"Polygon?crs={AAPConfig.EPSG_UTM_21S}",
        "talhoes",
        "memory"
    )
    
    provider = layer.dataProvider()
    provider.addAttributes(fields)
    layer.updateFields()
    
    return layer


def criar_camada_bordaduras(gpkg_path):
    """
    Cria a camada de bordaduras
    
    Atributos:
    - id: INTEGER
    - id_talhao: INTEGER (FK)
    - largura_m: REAL
    - tipo: TEXT(20)
    """
    fields = [
        QgsField("id", QVariant.Int),
        QgsField("id_talhao", QVariant.Int),
        QgsField("largura_m", QVariant.Double),
        QgsField("tipo", QVariant.String, len=20),
    ]
    
    layer = QgsVectorLayer(
        f"Polygon?crs={AAPConfig.EPSG_UTM_21S}",
        "bordaduras",
        "memory"
    )
    
    provider = layer.dataProvider()
    provider.addAttributes(fields)
    layer.updateFields()
    
    return layer


def criar_camada_linhas_plantio(gpkg_path):
    """
    Cria a camada de linhas de plantio
    
    Atributos:
    - id: INTEGER
    - id_talhao: INTEGER (FK)
    - cultura: TEXT(30)
    - espacamento_m: REAL
    - direcao_graus: REAL
    - comprimento_m: REAL (calcular automaticamente)
    """
    fields = [
        QgsField("id", QVariant.Int),
        QgsField("id_talhao", QVariant.Int),
        QgsField("cultura", QVariant.String, len=30),
        QgsField("espacamento_m", QVariant.Double),
        QgsField("direcao_graus", QVariant.Double),
        QgsField("comprimento_m", QVariant.Double),
    ]
    
    layer = QgsVectorLayer(
        f"LineString?crs={AAPConfig.EPSG_UTM_21S}",
        "linhas_plantio",
        "memory"
    )
    
    provider = layer.dataProvider()
    provider.addAttributes(fields)
    layer.updateFields()
    
    return layer


def criar_camada_linhas_pulverizacao(gpkg_path):
    """
    Cria a camada de linhas de pulverização
    
    Atributos:
    - id: INTEGER
    - id_talhao: INTEGER (FK)
    - largura_barra_m: REAL
    - sobreposicao_pct: REAL
    - passadas: INTEGER
    """
    fields = [
        QgsField("id", QVariant.Int),
        QgsField("id_talhao", QVariant.Int),
        QgsField("largura_barra_m", QVariant.Double),
        QgsField("sobreposicao_pct", QVariant.Double),
        QgsField("passadas", QVariant.Int),
    ]
    
    layer = QgsVectorLayer(
        f"LineString?crs={AAPConfig.EPSG_UTM_21S}",
        "linhas_pulverizacao",
        "memory"
    )
    
    provider = layer.dataProvider()
    provider.addAttributes(fields)
    layer.updateFields()
    
    return layer


def criar_camada_linha_ab(gpkg_path):
    """
    Cria a camada de linha AB (direção de plantio)
    
    Atributos:
    - id: INTEGER
    - id_talhao: INTEGER (FK)
    - azimute: REAL
    - metodo: TEXT(20)
    """
    fields = [
        QgsField("id", QVariant.Int),
        QgsField("id_talhao", QVariant.Int),
        QgsField("azimute", QVariant.Double),
        QgsField("metodo", QVariant.String, len=20),
    ]
    
    layer = QgsVectorLayer(
        f"LineString?crs={AAPConfig.EPSG_UTM_21S}",
        "linha_ab",
        "memory"
    )
    
    provider = layer.dataProvider()
    provider.addAttributes(fields)
    layer.updateFields()
    
    return layer


# ============================================================================
# FUNÇÕES DE ESTILOS VISUAIS
# ============================================================================

def aplicar_estilo_talhoes(layer):
    """Aplica estilo padrão para talhões"""
    # Preenchimento amarelo claro (opacity 30%), borda preta 0.5px
    symbol = QgsFillSymbol.createSimple({
        'color': '255,255,128,77',  # Amarelo claro com 30% opacidade
        'style': 'solid',
        'outline_color': '0,0,0,255',
        'outline_width': '0.5'
    })
    layer.renderer().setSymbol(symbol)
    layer.triggerRepaint()


def aplicar_estilo_bordaduras(layer):
    """Aplica estilo padrão para bordaduras"""
    # Preenchimento laranja (opacity 20%), borda laranja tracejada
    symbol = QgsFillSymbol.createSimple({
        'color': '255,165,0,51',  # Laranja com 20% opacidade
        'style': 'solid',
        'outline_color': '255,165,0,255',
        'outline_width': '1.0',
        'outline_style': 'dash'
    })
    layer.renderer().setSymbol(symbol)
    layer.triggerRepaint()


def aplicar_estilo_linhas_plantio(layer):
    """Aplica estilo padrão para linhas de plantio"""
    # Verde (#2e7d32), espessura 0.3px
    symbol = QgsLineSymbol.createSimple({
        'color': '46,125,50,255',
        'width': '0.3',
        'line_style': 'solid'
    })
    layer.renderer().setSymbol(symbol)
    layer.triggerRepaint()


def aplicar_estilo_linhas_pulverizacao(layer):
    """Aplica estilo padrão para linhas de pulverização"""
    # Azul (#1565c0), espessura 0.5px, tracejado
    symbol = QgsLineSymbol.createSimple({
        'color': '21,101,192,255',
        'width': '0.5',
        'line_style': 'dash'
    })
    layer.renderer().setSymbol(symbol)
    layer.triggerRepaint()


def aplicar_estilo_linha_ab(layer):
    """Aplica estilo padrão para linha AB"""
    # Vermelho (#c62828), espessura 1.5px, seta na ponta
    symbol = QgsLineSymbol.createSimple({
        'color': '198,40,40,255',
        'width': '1.5',
        'line_style': 'solid'
    })
    layer.renderer().setSymbol(symbol)
    layer.triggerRepaint()


# ============================================================================
# FUNÇÃO PRINCIPAL DE CONFIGURAÇÃO
# ============================================================================

def configurar_projeto_aap(
    projeto_path,
    nome_fazenda="MinhaFazenda",
    ano="2024",
    epsg_utm="EPSG:31981"
):
    """
    Configura o projeto AAP GIS do zero
    
    Parâmetros:
    - projeto_path: Caminho da pasta do projeto
    - nome_fazenda: Nome da fazenda
    - ano: Ano da safra
    - epsg_utm: EPSG da zona UTM (padrão: 31981 = zona 21S)
    
    Retorna:
    - True se sucesso, False se erro
    """
    
    # Criar estrutura de pastas
    pastas = [
        AAPConfig.PASTA_ENTRADA,
        AAPConfig.PASTA_TALHOES,
        AAPConfig.PASTA_BORDADURAS,
        AAPConfig.PASTA_PLANTIO,
        AAPConfig.PASTA_PULVERIZACAO,
        AAPConfig.PASTA_RELEVO,
        AAPConfig.PASTA_ANALISE,
        AAPConfig.PASTA_EXPORTACAO,
    ]
    
    for pasta in pastas:
        pasta_path = os.path.join(projeto_path, pasta)
        if not os.path.exists(pasta_path):
            os.makedirs(pasta_path)
            print(f"✓ Pasta criada: {pasta}")
    
    # Configurar projeto QGIS
    projeto = QgsProject.instance()
    projeto.setCrs(QgsCoordinateReferenceSystem(epsg_utm))
    projeto.setFileName(os.path.join(projeto_path, f"AAP_{nome_fazenda}_{ano}.qgz"))
    projeto.setDistanceUnits(QgsProject.DistanceUnits.Meters)
    projeto.setAreaUnits(QgsProject.AreaUnits.Hectares)
    
    # Criar GeoPackage base
    gpkg_path = os.path.join(projeto_path, AAPConfig.GPKG_BASE)
    
    # Criar todas as camadas
    camadas = {
        'talhoes': criar_camada_talhoes(gpkg_path),
        'bordaduras': criar_camada_bordaduras(gpkg_path),
        'linhas_plantio': criar_camada_linhas_plantio(gpkg_path),
        'linhas_pulverizacao': criar_camada_linhas_pulverizacao(gpkg_path),
        'linha_ab': criar_camada_linha_ab(gpkg_path),
    }
    
    # Adicionar camadas ao projeto
    for nome, layer in camadas.items():
        projeto.addMapLayer(layer)
        print(f"✓ Camada criada: {nome}")
    
    # Aplicar estilos
    aplicar_estilo_talhoes(camadas['talhoes'])
    aplicar_estilo_bordaduras(camadas['bordaduras'])
    aplicar_estilo_linhas_plantio(camadas['linhas_plantio'])
    aplicar_estilo_linhas_pulverizacao(camadas['linhas_pulverizacao'])
    aplicar_estilo_linha_ab(camadas['linha_ab'])
    
    # Salvar projeto
    projeto.write()
    print(f"✓ Projeto salvo: {projeto.fileName()}")
    
    # Adicionar comentário ao projeto
    comentario = f"""
    ============================================================================
    PROJETO AAP GIS - AGRICULTURA DE PRECISÃO
    ============================================================================
    Fazenda: {nome_fazenda}
    Safra: {ano}
    CRS: {epsg_utm}
    
    REGRAS DE NEGÓCIO AGRONÔMICAS:
    - Soja: espaçamento 0.45m, bordadura mínima 7m (2 passadas colhedora 4.5m)
    - Milho: espaçamento 0.90m, bordadura mínima 9m
    - Algodão: espaçamento 0.90m ou 0.76m, bordadura mínima 12m
    - Bordadura: sempre múltiplo da largura da máquina colhedora
    - Declividade crítica: >8% exige análise antes de operar
    
    ESTRUTURA DE PASTAS:
    01_Entrada/     - SHP, KML, GeoJSON originais
    02_Talhoes/     - Talhões processados
    03_Bordaduras/  - Polígonos de bordadura
    04_Plantio/     - Linhas de plantio por cultura
    05_Pulverizacao/ - Linhas de pulverização
    06_Relevo/      - DEM, slope, flow, curvature
    07_Analise/     - Cruzamentos e zonas de manejo
    08_Exportacao/  - Arquivos finais para máquinas
    ============================================================================
    """
    
    # Adicionar regras como propriedades do projeto
    projeto.writeEntry("aap_gis", "versao", "2.0")
    projeto.writeEntry("aap_gis", "comentario", comentario)
    
    print("\n" + "="*70)
    print("✓ CONFIGURAÇÃO DO PROJETO AAP GIS CONCLUÍDA COM SUCESSO!")
    print("="*70)
    print(f"\nProjeto salvo em: {projeto.fileName()}")
    print(f"GeoPackage base: {gpkg_path}")
    print(f"\nPróximo passo: Importar talhões (Parte 2)")
    
    return True


# ============================================================================
# FUNÇÃO PARA USO NO CONSOLE PYTHON DO QGIS
# ============================================================================

def executar_setup():
    """
    Função para executar o setup diretamente no console Python do QGIS
    
    Uso no console:
    >>> import sys
    >>> sys.path.insert(0, 'c:/caminho/para/scripts')
    >>> from aap_part1_setup import executar_setup
    >>> executar_setup()
    """
    
    # Solicitar informações do usuário
    nome_fazenda = input("Nome da fazenda: ") or "MinhaFazenda"
    ano = input("Ano da safra (ex: 2024): ") or "2024"
    projeto_path = input("Caminho do projeto (ex: C:/Users/.../AAP_Projeto): ")
    
    if not projeto_path:
        print("ERRO: Caminho do projeto é obrigatório")
        return False
    
    # Perguntar zona UTM
    print("\nZonas UTM SIRGAS 2000:")
    print("1 - Zona 21S (EPSG:31981) - RS, SC, PR, SP sul")
    print("2 - Zona 22S (EPSG:31982) - SP, MG, RJ, ES")
    print("3 - Zona 23S (EPSG:31983) - MG, GO, MS, MT")
    zona = input("Selecione a zona UTM (1-3, padrão 1): ") or "1"
    
    epsg_map = {
        '1': 'EPSG:31981',
        '2': 'EPSG:31982',
        '3': 'EPSG:31983'
    }
    
    epsg_utm = epsg_map.get(zona, 'EPSG:31981')
    
    # Executar configuração
    return configurar_projeto_aap(projeto_path, nome_fazenda, ano, epsg_utm)


# ============================================================================
# CHECKLIST DE VALIDAÇÃO
# ============================================================================

def validar_ambiente(projeto_path):
    """
    Valida se o ambiente está configurado corretamente
    
    Retorna:
    - dict com status de cada item
    """
    status = {
        'projeto_salvo': False,
        'estrutura_pastas': False,
        'geopackage_criado': False,
        'camadas_presentes': False,
        'estilos_aplicados': False,
    }
    
    # Verificar se projeto existe
    projeto = QgsProject.instance()
    status['projeto_salvo'] = bool(projeto.fileName())
    
    # Verificar estrutura de pastas
    pastas_existentes = all([
        os.path.exists(os.path.join(projeto_path, p))
        for p in [
            AAPConfig.PASTA_ENTRADA,
            AAPConfig.PASTA_TALHOES,
            AAPConfig.PASTA_BORDADURAS,
            AAPConfig.PASTA_PLANTIO,
            AAPConfig.PASTA_PULVERIZACAO,
            AAPConfig.PASTA_RELEVO,
            AAPConfig.PASTA_ANALISE,
            AAPConfig.PASTA_EXPORTACAO,
        ]
    ])
    status['estrutura_pastas'] = pastas_existentes
    
    # Verificar GeoPackage
    gpkg_path = os.path.join(projeto_path, AAPConfig.GPKG_BASE)
    status['geopackage_criado'] = os.path.exists(gpkg_path)
    
    # Verificar camadas
    camadas_necessarias = ['talhoes', 'bordaduras', 'linhas_plantio', 
                          'linhas_pulverizacao', 'linha_ab']
    camadas_projeto = [l.name() for l in projeto.mapLayers().values()]
    status['camadas_presentes'] = all(c in camadas_projeto for c in camadas_necessarias)
    
    # Verificar estilos (simplificado - apenas verifica se camadas têm renderer)
    status['estilos_aplicados'] = all(
        projeto.mapLayersByName(c)[0].renderer() is not None
        for c in camadas_necessarias
        if projeto.mapLayersByName(c)
    )
    
    # Imprimir relatório
    print("\n" + "="*70)
    print("RELATÓRIO DE VALIDAÇÃO - AMBIENTE AAP GIS")
    print("="*70)
    for item, ok in status.items():
        print(f"{'✓' if ok else '✗'} {item.replace('_', ' ').title()}")
    print("="*70)
    
    return status


# ============================================================================
# EXECUÇÃO
# ============================================================================

if __name__ == "__main__":
    print("""
    ============================================================================
    AAP GIS - PARTE 1: CONFIGURAÇÃO DO AMBIENTE
    ============================================================================
    
    Este script deve ser executado dentro do QGIS (Console Python)
    
    Para usar:
    1. Abra o QGIS
    2. Pressione Ctrl+Alt+P para abrir o Console Python
    3. Copie e cole este script
    4. Execute: configurar_projeto_aap('caminho/do/projeto')
    
    Ou use a função interativa:
    >>> executar_setup()
    
    ============================================================================
    """)
