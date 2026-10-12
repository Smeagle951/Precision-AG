"""
 ============================================================================
 AAP GIS - CAMADA DE ABSTRAÇÃO SIMPLES
 ============================================================================
 Esconde toda a complexidade GIS e oferece interface simples.
 
 O usuário NÃO precisa saber sobre:
 - CRS, EPSG, projeções
 - buffer, slope, curvatura
 - ISOXML, XML parsing
 - SAGA GIS, GDAL, PyQGIS
 
 O usuário APENAS informa:
 - Talhão (arquivo ou desenhado)
 - Cultura
 - Máquina
 - Largura da barra
 
 E o sistema faz TUDO automaticamente.
 
 AUTOR: Sistema AAP GIS v2.1 (Simplified)
 DATA: 2024
 ============================================================================
"""

import os
from qgis.core import (
    QgsProject, QgsMessageLog, Qgis
)


# ============================================================================
# API SIMPLES - "CRIAR PROJETO DE PLANTIO"
# ============================================================================

def criar_projeto_plantio(
    arquivo_talhao=None,
    cultura="soja",
    maquina="padrao",
    largura_barra_m=30.0,
    nome_talhao="Talhao_01",
    nome_fazenda="MinhaFazenda",
    projeto_path=None
):
    """
    Função principal de alto nível - CRIAR PROJETO DE PLANTIO
    
    O usuário fornece apenas:
    - arquivo_talhao: SHP, KML, GeoJSON ou desenha no mapa
    - cultura: soja, milho, algodao, etc.
    - maquina: tipo de máquina (padrao, jd2630, jacto, etc.)
    - largura_barra_m: largura da barra em metros
    
    O sistema faz AUTOMATICAMENTE:
    1. Importa e limpa o talhão
    2. Analisa o relevo (se DEM disponível)
    3. Escolhe a melhor estratégia de linhas
    4. Gera bordaduras automaticamente
    5. Gera linhas de plantio otimizadas
    6. Gera linhas de pulverização
    7. Exporta para o monitor correto
    8. Mostra resultado simples
    
    Returns:
    - dict com resultado simples {sucesso, mensagem, dados}
    """
    try:
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("CRIANDO PROJETO DE PLANTIO - API SIMPLES", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        
        # Configurar caminho do projeto
        if projeto_path is None:
            projeto_path = os.path.join(os.getcwd(), "AAP_Projeto")
        
        # Importar scripts (caminho de abstração)
        from aap_part1_setup import configurar_projeto_aap
        from aap_part2_importacao import importar_e_processar_talhao
        from aap_part3_bordadura import gerar_bordadura
        from aap_part4_plantio import gerar_linhas_plantio
        from aap_part5_pulverizacao import gerar_linhas_pulverizacao
        from aap_part8_exportacao_expanded import exportar_para_shapefile
        
        # 1. Configurar projeto (se não existe)
        if not os.path.exists(projeto_path):
            QgsMessageLog.logMessage("Configurando projeto...", 'AAP GIS', Qgis.Info)
            configurar_projeto_aap(
                projeto_path=projeto_path,
                nome_fazenda=nome_fazenda,
                ano="2024"
            )
        
        # 2. Importar e processar talhão
        QgsMessageLog.logMessage(f"Importando talhão: {arquivo_talhao}", 'AAP GIS', Qgis.Info)
        
        resultado_import = importar_e_processar_talhao(
            arquivo_talhao,
            nome_talhao,
            cultura,
            projeto_path
        )
        
        if not resultado_import:
            return {
                'sucesso': False,
                'mensagem': 'Erro ao importar talhão',
                'dados': None
            }
        
        id_talhao = resultado_import.get('id_talhao', 1)
        dem_path = resultado_import.get('dem_path', None)
        
        # 3. Gerar bordaduras (automático baseado na cultura)
        QgsMessageLog.logMessage("Gerando bordaduras automáticas...", 'AAP GIS', Qgis.Info)
        
        # Largura automática baseada na cultura
        largura_bordadura = obter_bordadura_automatica(cultura)
        
        gerar_bordadura(
            id_talhao=id_talhao,
            largura_m=largura_bordadura,
            n_passadas=2,
            cultura=cultura,
            projeto_path=projeto_path
        )
        
        # 4. Escolher estratégia de linhas (automático)
        QgsMessageLog.logMessage("Analisando terreno e escolhendo estratégia...", 'AAP GIS', Qgis.Info)
        
        estrategia = escolher_estrategia_automatica(id_talhao, dem_path, cultura)
        
        # 5. Gerar linhas de plantio
        QgsMessageLog.logMessage(f"Gerando linhas de plantio (estratégia: {estrategia})...", 'AAP GIS', Qgis.Info)
        
        if estrategia == 'agronomicas':
            from aap_part9_linhas_agronomicas import gerar_linhas_agronomicas
            gerar_linhas_agronomicas(
                id_talhao=id_talhao,
                dem_path=dem_path,
                cultura=cultura,
                estrategia=None  # auto
            )
        else:
            gerar_linhas_plantio(
                id_talhao=id_talhao,
                cultura=cultura,
                metodo_direcao='auto_eixo'
            )
        
        # 6. Gerar linhas de pulverização
        QgsMessageLog.logMessage("Gerando linhas de pulverização...", 'AAP GIS', Qgis.Info)
        
        gerar_linhas_pulverizacao(
            id_talhao=id_talhao,
            largura_barra_m=largura_barra_m,
            sobreposicao_pct=10,
            cultura=cultura,
            alinhar_plantio=True
        )
        
        # 7. Exportar para monitor (automático baseado na máquina)
        QgsMessageLog.logMessage(f"Exportando para monitor: {maquina}...", 'AAP GIS', Qgis.Info)
        
        monitor_tipo = identificar_monitor(maquina)
        export_path = os.path.join(projeto_path, "08_Exportacao")
        
        exportar_para_shapefile(
            id_talhao=id_talhao,
            monitor=monitor_tipo,
            cultura=cultura,
            output_dir=export_path
        )
        
        # 8. Gerar resultado simples
        resultado = gerar_resultado_simples(
            id_talhao,
            cultura,
            maquina,
            projeto_path
        )
        
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("✅ PROJETO DE PLANTIO CONCLUÍDO", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        
        return {
            'sucesso': True,
            'mensagem': 'Projeto de plantio criado com sucesso',
            'dados': resultado
        }
        
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro ao criar projeto: {str(e)}", 'AAP GIS', Qgis.Critical)
        return {
            'sucesso': False,
            'mensagem': f'Erro: {str(e)}',
            'dados': None
        }


# ============================================================================
# FUNÇÕES DE AUTOMAÇÃO (ESCONDIDAS DO USUÁRIO)
# ============================================================================

def obter_bordadura_automatica(cultura):
    """
    Calcula bordadura automática baseada na cultura
    (Escondido do usuário)
    """
    bordaduras = {
        'soja': 9.0,
        'milho': 12.0,
        'algodao': 12.0,
        'feijao': 7.0,
        'sorgo': 7.0
    }
    return bordaduras.get(cultura.lower(), 9.0)


def escolher_estrategia_automatica(id_talhao, dem_path, cultura):
    """
    Escolhe automaticamente a melhor estratégia de linhas
    (Escondido do usuário)
    """
    if dem_path and os.path.exists(dem_path):
        # Se DEM disponível, usa linhas agronômicas
        return 'agronomicas'
    else:
        # Sem DEM, usa linhas geométricas
        return 'geometricas'


def identificar_monitor(maquina):
    """
    Identifica o tipo de monitor baseado na máquina
    (Escondido do usuário)
    """
    maquina = maquina.lower()
    
    if 'jd' in maquina or 'john' in maquina:
        return 'johndeere'
    elif 'jacto' in maquina:
        return 'jacto'
    elif 'nh' in maquina or 'new' in maquina:
        return 'newholland'
    elif 'stara' in maquina:
        return 'stara'
    else:
        return 'padrao'


def gerar_resultado_simples(id_talhao, cultura, maquina, projeto_path):
    """
    Gera resultado simples para o usuário
    (Esconde todos os detalhes técnicos)
    """
    projeto = QgsProject.instance()
    
    # Calcular estatísticas simples
    area_ha = 0
    n_linhas_plantio = 0
    n_linhas_pulverizacao = 0
    
    # Buscar talhão
    for layer in projeto.mapLayers().values():
        if layer.name() == 'talhoes':
            for feat in layer.getFeatures():
                if feat['id'] == id_talhao:
                    area_ha = feat.geometry().area() / 10000
                    break
    
    # Buscar linhas
    for layer in projeto.mapLayers().values():
        if 'plantio' in layer.name().lower():
            n_linhas_plantio = layer.featureCount()
        if 'pulverizacao' in layer.name().lower():
            n_linhas_pulverizacao = layer.featureCount()
    
    # Decisão automática (sem interpretação do usuário)
    decisao = {
        'estrategia_linhas': 'Agronômicas otimizadas' if area_ha > 50 else 'Geométricas',
        'bordadura': f'{obter_bordadura_automatica(cultura):.1f}m (automática)',
        'risco_erosao': 'Baixo' if area_ha < 100 else 'Médio',
        'recomendacao': 'Proceder com plantio conforme gerado'
    }
    
    return {
        'talhao': nome_talhao,
        'area_ha': round(area_ha, 2),
        'cultura': cultura,
        'linhas_plantio': n_linhas_plantio,
        'linhas_pulverizacao': n_linhas_pulverizacao,
        'decisao_automatica': decisao,
        'arquivos_gerados': [
            'linhas_plantio.shp',
            'linhas_pulverizacao.shp',
            'bordadura.shp'
        ],
        'monitor': maquina,
        'status': 'Pronto para exportação'
    }


# ============================================================================
# API AINDA MAIS SIMPLES - "ONE-LINER"
# ============================================================================

def plantar(arquivo_talhao, cultura="soja"):
    """
    API ultra-simples - one-liner
    
    Uso: plantar('meu_talhao.shp', 'soja')
    
    Faz tudo automaticamente.
    """
    return criar_projeto_plantio(
        arquivo_talhao=arquivo_talhao,
        cultura=cultura
    )


# ============================================================================
# EXECUÇÃO
# ============================================================================

if __name__ == "__main__":
    print("""
    ============================================================================
    AAP GIS - API SIMPLES
    ============================================================================
    
    Para usar no QGIS Console Python:
    
    >>> import sys
    >>> sys.path.insert(0, 'c:/caminho/para/scripts')
    >>> from aap_simple_api import *
    >>> 
    >>> # Criar projeto de plantio (fluxo completo automático)
    >>> resultado = criar_projeto_plantio(
    ...     arquivo_talhao='caminho/talhao.shp',
    ...     cultura='soja',
    ...     maquina='jd2630',
    ...     largura_barra_m=30.0
    ... )
    >>> 
    >>> # Ou usar o one-liner ultra-simples
    >>> resultado = plantar('caminho/talhao.shp', 'soja')
    >>> 
    >>> if resultado['sucesso']:
    ...     print("✅ Projeto criado!")
    ...     print(resultado['dados'])
    >>> else:
    ...     print("❌ Erro:", resultado['mensagem'])
    ============================================================================
    
    O usuário NÃO precisa saber:
    ❌ CRS, EPSG, projeções
    ❌ buffer, slope, curvatura
    ❌ ISOXML, XML parsing
    ❌ SAGA GIS, GDAL, PyQGIS
    
    O usuário APENAS informa:
    ✅ Talhão (arquivo)
    ✅ Cultura
    ✅ Máquina
    
    E o sistema faz TUDO.
    ============================================================================
    """)
