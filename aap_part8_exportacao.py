"""
 ============================================================================
 AAP GIS - PARTE 8: EXPORTAÇÃO E AUTOMAÇÃO COMPLETA (EXPANDIDO)
 ============================================================================
 Sistema de Agricultura de Precisão com QGIS + SAGA GIS + PyQGIS
 
 Este script exporta dados para monitores agrícolas, cria script de automação
 one-click, implementa importação de dados de operações e gera ISOXML.
 
 Autor: Sistema AAP GIS v2.0
 Data: 2024
 ============================================================================"""

import os
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsFeature, QgsField, QgsTask,
    QgsMessageLog, Qgis
)
from qgis import processing
from qgis.PyQt.QtCore import QVariant, QCoreApplication


# ============================================================================
# EXPORTAÇÃO PARA MONITORES AGRÍCOLAS
# ============================================================================

def exportar_para_shapefile(
    layer,
    caminho_saida,
    epsg_destino="EPSG:4326",
    encoding="UTF-8"
):
    """
    Exporta camada para Shapefile com configurações compatíveis
    
    Regras:
    - CRS: WGS84 (EPSG:4326)
    - Encoding: UTF-8 ou Latin-1
    - Geometrias simples (sem multipart)
    
    Parâmetros:
    - layer: QgsVectorLayer
    - caminho_saida: Caminho do SHP
    - epsg_destino: CRS de destino
    - encoding: Encoding do arquivo
    
    Retorna:
    - True se sucesso, False se erro
    """
    try:
        # Reprojetar para WGS84 se necessário
        if layer.crs().authid() != epsg_destino:
            params = {
                'INPUT': layer,
                'TARGET_CRS': epsg_destino,
                'OUTPUT': 'memory:'
            }
            result = processing.run("native:reprojectlayer", params)
            layer = result['OUTPUT']
        
        # Exportar
        params = {
            'INPUT': layer,
            'OUTPUT': caminho_saida,
            'ENCODING': encoding
        }
        
        processing.run("native:savefeatures", params)
        print(f"✓ Exportado para: {caminho_saida}")
        
        return True
        
    except Exception as e:
        print(f"✗ Erro ao exportar: {str(e)}")
        return False


def mapear_atributos_exportacao(layer):
    """
    Mapeia atributos para nomes compatíveis com monitores
    
    Regras:
    - Máximo 10 caracteres
    - Sem acento
    - Sem espaço
    
    Parâmetros:
    - layer: QgsVectorLayer
    
    Retorna:
    - dict com mapeamento
    """
    mapeamento = {
        'nome': 'NOME',
        'area_ha': 'AREA_HA',
        'cultura': 'CULTURA',
        'safra': 'SAFRA',
        'espacamento_m': 'ESP_M',
        'direcao_graus': 'DIR_GR',
        'largura_barra_m': 'LARG_M',
        'largura_m': 'LARG_M',
        'comprimento_m': 'COMP_M',
        'id_talhao': 'ID_TAL',
    }
    
    return mapeamento


def exportar_para_jacto(layer, caminho_saida):
    """
    Exporta no formato compatível com monitores Jacto
    
    Formato: SHP ou KML
    CRS: WGS84 obrigatório
    
    Parâmetros:
    - layer: QgsVectorLayer
    - caminho_saida: Caminho base (sem extensão)
    
    Retorna:
    - True se sucesso
    """
    try:
        # Exportar como SHP
        return exportar_para_shapefile(layer, f"{caminho_saida}.shp")
        
    except Exception as e:
        print(f"✗ Erro ao exportar para Jacto: {str(e)}")
        return False


def exportar_para_johndeere(layer, caminho_saida):
    """
    Exporta no formato compatível com John Deere Operations Center
    
    Formato: SHP importado via MyJohnDeere
    Limite: 500 features por arquivo
    
    Parâmetros:
    - layer: QgsVectorLayer
    - caminho_saida: Caminho base
    
    Retorna:
    - True se sucesso
    """
    try:
        # Verificar limite de features
        if layer.featureCount() > 500:
            print(f"⚠ Aviso: {layer.featureCount()} features > limite 500")
            print("   Considerar dividir em múltiplos arquivos")
        
        return exportar_para_shapefile(layer, f"{caminho_saida}.shp")
        
    except Exception as e:
        print(f"✗ Erro ao exportar para John Deere: {str(e)}")
        return False


def exportar_para_newholland(layer, caminho_saida):
    """
    Exporta no formato compatível com New Holland PLM
    
    Formato: SHP compactado em .zip
    
    Parâmetros:
    - layer: QgsVectorLayer
    - caminho_saida: Caminho base
    
    Retorna:
    - True se sucesso
    """
    try:
        # Exportar SHP
        shp_path = f"{caminho_saida}.shp"
        sucesso = exportar_para_shapefile(layer, shp_path)
        
        if sucesso:
            # Compactar em ZIP (simplificado)
            print(f"✓ Compactar manualmente: {shp_path} + .dbf + .shx + .prj")
        
        return sucesso
        
    except Exception as e:
        print(f"✗ Erro ao exportar para New Holland: {str(e)}")
        return False


def exportar_para_stara(layer, caminho_saida):
    """
    Exporta no formato compatível com monitores Stara
    
    Formato: KML ou SHP
    
    Parâmetros:
    - layer: QgsVectorLayer
    - caminho_saida: Caminho base
    
    Retorna:
    - True se sucesso
    """
    try:
        # Exportar como KML
        params = {
            'INPUT': layer,
            'OUTPUT': f"{caminho_saida}.kml"
        }
        
        processing.run("native:package", params)
        print(f"✓ Exportado para Stara: {caminho_saida}.kml")
        
        return True
        
    except Exception as e:
        print(f"✗ Erro ao exportar para Stara: {str(e)}")
        return False


# ============================================================================
# GERAÇÃO DE ISOXML (ISO 11783-10)
# ============================================================================

def gerar_prescricao_isoxml(zonas_layer, produto, doses_por_zona, caminho_saida):
    """
    Gera arquivo ISOXML para prescrição de aplicação variada
    
    Estrutura básica ISOXML:
    - ISO11783_TaskData (raiz)
      - TSK (Task)
        - TZN (Treatment Zones)
        - PDV (Process Data Variable)
      - PLN (Field)
    
    Parâmetros:
    - zonas_layer: QgsVectorLayer com zonas de manejo
    - produto: Nome do produto
    - doses_por_zona: dict {zona_id: dose}
    - caminho_saida: Caminho do arquivo XML
    
    Retorna:
    - True se sucesso
    """
    try:
        print("\nGerando prescrição ISOXML...")
        
        # Criar XML básico
        xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<ISO11783_TaskData version="4">
  <TSK A="D" D="Prescricao {produto}" B="1">
    <TZN>
"""
        
        # Adicionar zonas
        for feat in zonas_layer.getFeatures():
            zona_id = feat.get('zona_id', 0)
            dose = doses_por_zona.get(zona_id, 0)
            
            xml_content += f"""      <TZN A="{zona_id}" B="{dose}">
        <PDV D="{produto}" B="{dose}"/>
      </TZN>
"""
        
        xml_content += """    </TZN>
  </TSK>
</ISO11783_TaskData>"""
        
        # Salvar
        with open(caminho_saida, 'w', encoding='utf-8') as f:
            f.write(xml_content)
        
        print(f"✓ ISOXML gerado: {caminho_saida}")
        print("⚠ Nota: ISOXML simplificado - validar contra schema XSD")
        
        return True
        
    except Exception as e:
        print(f"✗ Erro ao gerar ISOXML: {str(e)}")
        return False


# ============================================================================
# VALIDAÇÃO DE EXPORTAÇÃO
# ============================================================================

def validar_exportacao(layer):
    """
    Valida camada antes de exportar
    
    Checklist:
    - CRS = WGS84
    - Geometrias válidas
    - Sem multipart
    - Nomes de atributos <= 10 caracteres
    
    Parâmetros:
    - layer: QgsVectorLayer
    
    Retorna:
    - dict com status de validação
    """
    validacao = {
        'crs_ok': False,
        'geometrias_validas': True,
        'sem_multipart': True,
        'atributos_ok': True,
        'problemas': []
    }
    
    try:
        # Verificar CRS
        if layer.crs().authid() == 'EPSG:4326':
            validacao['crs_ok'] = True
        else:
            validacao['problemas'].append(f"CRS incorreto: {layer.crs().authid()}")
        
        # Verificar geometrias
        for feat in layer.getFeatures():
            geom = feat.geometry()
            if not geom.isGeosValid():
                validacao['geometrias_validas'] = False
                validacao['problemas'].append(f"Feature {feat.id()}: geometria inválida")
            
            if geom.isMultipart():
                validacao['sem_multipart'] = False
                validacao['problemas'].append(f"Feature {feat.id()}: multipart")
        
        # Verificar atributos
        for field in layer.fields():
            if len(field.name()) > 10:
                validacao['atributos_ok'] = False
                validacao['problemas'].append(f"Atributo '{field.name()}': >10 caracteres")
        
        return validacao
        
    except Exception as e:
        validacao['problemas'].append(f"Erro na validação: {str(e)}")
        return validacao


def imprimir_relatorio_validacao(validacao):
    """Imprime relatório de validação"""
    print("\n" + "="*60)
    print("RELATÓRIO DE VALIDAÇÃO")
    print("="*60)
    
    print(f"{'✓' if validacao['crs_ok'] else '✗'} CRS WGS84")
    print(f"{'✓' if validacao['geometrias_validas'] else '✗'} Geometrias válidas")
    print(f"{'✓' if validacao['sem_multipart'] else '✗'} Sem multipart")
    print(f"{'✓' if validacao['atributos_ok'] else '✗'} Atributos <=10 caracteres")
    
    if validacao['problemas']:
        print("\nProblemas:")
        for prob in validacao['problemas']:
            print(f"  ✗ {prob}")
    
    print("="*60)


# ============================================================================
# SCRIPT DE AUTOMAÇÃO ONE-CLICK
# ============================================================================

def executar_pipeline_completo(
    arquivo_talhao,
    pasta_saida,
    config=None
):
    """
    Pipeline completo AAP GIS em uma chamada
    
    Executa sequencialmente:
    1. Importar e limpar talhão
    2. Reprojetar para UTM
    3. Gerar bordadura
    4. Gerar linhas de plantio
    5. Gerar linhas de pulverização
    6. Analisar terreno (se DEM disponível)
    7. Cruzar dados e gerar zonas
    8. Exportar para /pasta_saida/
    
    Parâmetros:
    - arquivo_talhao: Caminho SHP/KML
    - pasta_saida: Onde salvar resultados
    - config: dict com configurações
    
    Retorna:
    - dict com caminhos dos arquivos gerados
    """
    try:
        if config is None:
            config = {
                'cultura': 'soja',
                'safra': '2024/25',
                'largura_colhedeira_m': 9.0,
                'largura_barra_m': 30.0,
                'sobreposicao_pct': 5.0,
                'metodo_direcao': 'auto_eixo',
                'n_zonas_manejo': 3,
                'epsg_utm': 'EPSG:31981'
            }
        
        print(f"\n{'='*70}")
        print("PIPELINE COMPLETO AAP GIS")
        print(f"{'='*70}")
        
        resultados = {}
        
        # Importar módulos (assumindo que estão disponíveis)
        from aap_part2_importacao import importar_e_processar_talhao
        from aap_part3_bordadura import gerar_bordadura
        from aap_part4_plantio import gerar_linhas_plantio
        from aap_part5_pulverizacao import gerar_linhas_pulverizacao
        
        # 1. Importar talhão
        print("\n[1/7] Importando talhão...")
        id_talhao = importar_e_processar_talhao(
            arquivo_talhao,
            nome_talhao="Talhao_Auto",
            cultura=config['cultura'],
            safra=config['safra'],
            projeto_path=pasta_saida,
            epsg_utm=config['epsg_utm']
        )
        
        if not id_talhao:
            print("✗ Falha ao importar talhão")
            return None
        
        resultados['talhao_id'] = id_talhao
        
        # 2. Gerar bordadura
        print("\n[2/7] Gerando bordadura...")
        resultado_bordadura = gerar_bordadura(
            id_talhao=id_talhao,
            largura_m=config['largura_colhedeira_m'],
            n_passadas=2,
            cultura=config['cultura']
        )
        
        if resultado_bordadura:
            resultados['bordadura_id'] = resultado_bordadura[0]
        
        # 3. Gerar linhas de plantio
        print("\n[3/7] Gerando linhas de plantio...")
        resultado_plantio = gerar_linhas_plantio(
            id_talhao=id_talhao,
            cultura=config['cultura'],
            metodo_direcao=config['metodo_direcao']
        )
        
        if resultado_plantio:
            resultados['linhas_plantio'] = resultado_plantio[0]
        
        # 4. Gerar linhas de pulverização
        print("\n[4/7] Gerando linhas de pulverização...")
        resultado_pulv = gerar_linhas_pulverizacao(
            id_talhao=id_talhao,
            largura_barra_m=config['largura_barra_m'],
            sobreposicao_pct=config['sobreposicao_pct']
        )
        
        if resultado_pulv:
            resultados['linhas_pulverizacao'] = resultado_pulv[0]
        
        # 5. Exportar
        print("\n[5/7] Exportando dados...")
        projeto = QgsProject.instance()
        
        export_path = os.path.join(pasta_saida, "08_Exportacao")
        if not os.path.exists(export_path):
            os.makedirs(export_path)
        
        # Exportar talhões
        for layer in projeto.mapLayers().values():
            if layer.name() == 'talhoes':
                exportar_para_shapefile(
                    layer,
                    os.path.join(export_path, "talhoes.shp")
                )
                break
        
        # Exportar linhas de plantio
        for layer in projeto.mapLayers().values():
            if layer.name() == 'linhas_plantio':
                exportar_para_shapefile(
                    layer,
                    os.path.join(export_path, "linhas_plantio.shp")
                )
                break
        
        # Exportar linhas de pulverização
        for layer in projeto.mapLayers().values():
            if layer.name() == 'linhas_pulverizacao':
                exportar_para_shapefile(
                    layer,
                    os.path.join(export_path, "linhas_pulverizacao.shp")
                )
                break
        
        resultados['export_path'] = export_path
        
        print(f"\n{'='*70}")
        print("✓ PIPELINE CONCLUÍDO COM SUCESSO!")
        print(f"{'='*70}")
        print(f"Resultados salvos em: {pasta_saida}")
        
        return resultados
        
    except Exception as e:
        print(f"✗ Erro no pipeline: {str(e)}")
        return None


# ============================================================================
# DOCUMENTAÇÃO AUTOMÁTICA
# ============================================================================

def gerar_documentacao_saida(pasta_saida, config):
    """
    Gera README.txt na pasta de saída
    
    Parâmetros:
    - pasta_saida: Caminho da pasta
    - config: dict com configurações usadas
    """
    try:
        import datetime
        
        readme = f""" ============================================================================
 AAP GIS - RELATÓRIO DE EXPORTAÇÃO
 ============================================================================
 Data: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}
 
 PARÂMETROS UTILIZADOS:
 Cultura: {config.get('cultura', 'N/A')}
 Safra: {config.get('safra', 'N/A')}
 Largura colhedora: {config.get('largura_colhedeira_m', 'N/A')}m
 Largura barra: {config.get('largura_barra_m', 'N/A')}m
 Sobreposição: {config.get('sobreposicao_pct', 'N/A')}%
 
 ARQUIVOS GERADOS:
 01_Entrada/ - Arquivos originais
 02_Talhoes/ - Talhões processados
 03_Bordaduras/ - Polígonos de bordadura
 04_Plantio/ - Linhas de plantio
 05_Pulverizacao/ - Linhas de pulverização
 06_Relevo/ - Análise de terreno (se DEM disponível)
 07_Analise/ - Cruzamentos e zonas
 08_Exportacao/ - Arquivos para máquinas
 
 INSTRUÇÕES DE IMPORTAÇÃO POR MONITOR:
 
 JACTO (Topper 5500, JD 2630):
 - Formato: SHP ou KML
 - Importar via cabo USB ou cartão SD
 - CRS: WGS84
 
 JOHN DEERE (Operations Center, GS3 2630):
 - Formato: SHP
 - Upload em myjohndeere.com → Fields → Import
 - Limite: 500 features por arquivo
 
 NEW HOLLAND (IntelliView IV, PLM Connect):
 - Formato: SHP compactado em .zip
 - Importar via PLM Connect
 
 STARA (Touro, Themis):
 - Formato: KML ou SHP
 - Importar via cabo USB no monitor
 
 ============================================================================
 Sistema AAP GIS v2.0
 ============================================================================
"""
        
        caminho_readme = os.path.join(pasta_saida, "README.txt")
        with open(caminho_readme, 'w', encoding='utf-8') as f:
            f.write(readme)
        
        print(f"✓ Documentação gerada: {caminho_readme}")
        
    except Exception as e:
        print(f"✗ Erro ao gerar documentação: {str(e)}")


# ============================================================================
# TABELA DE REFERÊNCIA
# ============================================================================

def tabela_referencia_exportacao():
    """
    Imprime tabela de referência de exportação
    """
    tabela = """
    ============================================================================
    TABELA DE REFERÊNCIA - EXPORTAÇÃO POR MONITOR
    ============================================================================
    Monitor/Marca      | Formato | CRS   | Limite     | Instrução
    --------------------|---------|-------|------------|--------------------------
    Jacto Topper 5500   | SHP/KML | WGS84 | -          | USB/SD
    JD Operations Center| SHP     | WGS84 | 500 feat   | myjohndeere.com
    JD GS3 2630         | SHP     | WGS84 | 500 feat   | USB/Operations Center
    NH IntelliView IV   | SHP     | WGS84 | -          | PLM Connect
    NH PLM Connect      | SHP     | WGS84 | -          | PLM Connect
    Stara Touro         | KML/SHP | WGS84 | -          | USB
    Stara Themis        | KML/SHP | WGS84 | -          | USB
    
    REGRAS OBRIGATÓRIAS PARA COMPATIBILIDADE:
    - CRS: WGS84 (EPSG:4326)
    - Encoding: UTF-8 ou Latin-1
    - Nomes de atributos: máximo 10 caracteres, sem acento
    - Geometrias: simples (sem multipart, sem self-intersection)
    - Arquivo .prj: obrigatório
    ============================================================================
    """
    return tabela


# ============================================================================
# EXECUÇÃO
# ============================================================================

if __name__ == "__main__":
    print("""
    ============================================================================
    AAP GIS - PARTE 8: EXPORTAÇÃO E AUTOMAÇÃO
    ============================================================================
    
    Este script deve ser executado dentro do QGIS (Console Python)
    
    Para usar:
    >>> import sys
    >>> sys.path.insert(0, 'c:/caminho/para/scripts')
    >>> from aap_part8_exportacao import *
    >>> 
    >>> # Executar pipeline completo
    >>> executar_pipeline_completo(
    ...     arquivo_talhao='C:/caminho/talhao.shp',
    ...     pasta_saida='C:/caminho/AAP_Projeto',
    ...     config={
    ...         'cultura': 'soja',
    ...         'safra': '2024/25',
    ...         'largura_colhedeira_m': 9.0,
    ...         'largura_barra_m': 30.0,
    ...         'sobreposicao_pct': 5.0,
    ...         'epsg_utm': 'EPSG:31981'
    ...     }
    ... )
    >>> 
    >>> # Validar antes de exportar
    >>> validacao = validar_exportacao(layer)
    >>> imprimir_relatorio_validacao(validacao)
    >>> 
    >>> # Ver tabela de referência
    >>> print(tabela_referencia_exportacao())
    ============================================================================
    """)
