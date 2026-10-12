"""
 ============================================================================
 AAP GIS - PARTE 4: LINHAS DE PLANTIO
 ============================================================================
 Sistema de Agricultura de Precisão com QGIS + SAGA GIS + PyQGIS
 
 Este script gera linhas de plantio paralelas otimizadas dentro da área útil
 do talhão, com espaçamento por cultura e direção baseada em critérios
 agronômicos.
 
 Autor: Sistema AAP GIS v2.0
 Data: 2024
 ============================================================================"""

import os
import math
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsField, QgsPointXY, QgsLineString
)
from qgis import processing
from qgis.PyQt.QtCore import QVariant


# ============================================================================
# CONFIGURAÇÕES POR CULTURA
# ============================================================================

class PlantioConfig:
    """Configurações de espaçamento por cultura"""
    
    ESPACAMENTOS = {
        'soja': 0.45,
        'milho': 0.90,
        'algodao': 0.90,  # ou 0.76 configurável
        'feijao': 0.50,
        'sorgo': 0.50,
    }
    
    @staticmethod
    def get_espacamento(cultura, espacamento_custom=None):
        """Retorna espaçamento para a cultura"""
        if espacamento_custom:
            return espacamento_custom
        return PlantioConfig.ESPACAMENTOS.get(
            cultura.lower(), 
            0.50  # Padrão
        )


# ============================================================================
# FUNÇÕES DE DETERMINAÇÃO DE DIREÇÃO (LINHA AB)
# ============================================================================

def calcular_azimute(ponto_a, ponto_b):
    """
    Calcula azimute entre dois pontos
    
    Parâmetros:
    - ponto_a: QgsPointXY
    - ponto_b: QgsPointXY
    
    Retorna:
    - Azimute em graus (0-360, Norte=0)
    """
    dx = ponto_b.x() - ponto_a.x()
    dy = ponto_b.y() - ponto_a.y()
    
    azimute = math.degrees(math.atan2(dx, dy))
    if azimute < 0:
        azimute += 360
    
    return azimute


def calcular_direcao_auto_eixo(geometry):
    """
    Método 1: Direção automática pelo maior eixo do retângulo envolvente
    
    Parâmetros:
    - geometry: QgsGeometry do talhão
    
    Retorna:
    - Azimute em graus
    """
    bounds = geometry.boundingBox()
    width = bounds.width()
    height = bounds.height()
    
    if width > height:
        # Maior eixo é horizontal (L-O)
        azimute = 90.0
    else:
        # Maior eixo é vertical (N-S)
        azimute = 0.0
    
    return azimute


def calcular_direcao_auto_slope(dem_path, geometry, intervalo=5):
    """
    Método 2: Direção automática que minimiza slope médio
    
    Itera 0° a 179° em intervalos e retorna azimute com menor slope
    
    Parâmetros:
    - dem_path: Caminho do DEM raster
    - geometry: QgsGeometry do talhão
    - intervalo: Intervalo em graus (padrão: 5)
    
    Retorna:
    - Azimute em graus
    """
    try:
        # Carregar DEM
        dem_layer = QgsRasterLayer(dem_path, "dem_temp")
        
        if not dem_layer.isValid():
            print("⚠ DEM inválido, usando direção por eixo")
            return calcular_direcao_auto_eixo(geometry)
        
        # Criar linha de teste central no talhão
        bounds = geometry.boundingBox()
        centro = bounds.center()
        
        melhor_azimute = 0
        menor_slope = float('inf')
        
        for angulo in range(0, 180, intervalo):
            # Criar linha de teste na direção
            rad = math.radians(angulo)
            dx = math.sin(rad) * 100  # 100m de comprimento
            dy = math.cos(rad) * 100
            
            ponto_a = QgsPointXY(centro.x() - dx, centro.y() - dy)
            ponto_b = QgsPointXY(centro.x() + dx, centro.y() + dy)
            
            line_geom = QgsGeometry.fromPolylineXY([ponto_a, ponto_b])
            
            # Sample raster values ao longo da linha
            params = {
                'INPUT': dem_layer,
                'SOURCE': line_geom,
                'COLUMN_PREFIX': 'slope_',
                'OUTPUT': 'memory:'
            }
            
            result = processing.run("qgis:rastersampling", params)
            sampled = result['OUTPUT']
            
            # Calcular slope médio (simplificado - usar DEM real)
            # Para implementação completa, usar SAGA slope antes
            slope_medio = 0  # Placeholder
            
            if slope_medio < menor_slope:
                menor_slope = slope_medio
                melhor_azimute = angulo
        
        return melhor_azimute
        
    except Exception as e:
        print(f"⚠ Erro no cálculo por slope: {str(e)}")
        return calcular_direcao_auto_eixo(geometry)


def criar_linha_ab(id_talhao, metodo='auto_eixo', azimute_manual=None, ponto_a=None, ponto_b=None):
    """
    Cria linha AB (direção de plantio) e salva na camada 'linha_ab'
    
    Parâmetros:
    - id_talhao: ID do talhão
    - metodo: 'auto_eixo', 'auto_slope', 'manual'
    - azimute_manual: Azimute em graus (se metodo='manual')
    - ponto_a: QgsPointXY (se metodo='manual' com pontos)
    - ponto_b: QgsPointXY (se metodo='manual' com pontos)
    
    Retorna:
    - feature_id da linha AB ou None
    """
    try:
        projeto = QgsProject.instance()
        
        # Encontrar talhão
        talhoes_layer = None
        for layer in projeto.mapLayers().values():
            if layer.name() == 'talhoes':
                talhoes_layer = layer
                break
        
        talhao_feat = None
        for feat in talhoes_layer.getFeatures():
            if feat['id'] == id_talhao:
                talhao_feat = feat
                break
        
        if not talhao_feat:
            print(f"✗ Talhão ID {id_talhao} não encontrado")
            return None
        
        geom = talhao_feat.geometry()
        bounds = geom.boundingBox()
        
        # Determinar azimute
        if metodo == 'manual' and ponto_a and ponto_b:
            azimute = calcular_azimute(ponto_a, ponto_b)
            # Criar linha AB através dos pontos
            linha_ab_geom = QgsGeometry.fromPolylineXY([ponto_a, ponto_b])
        elif metodo == 'manual' and azimute_manual is not None:
            azimute = azimute_manual
            # Criar linha AB através do centro do talhão
            centro = bounds.center()
            rad = math.radians(azimute)
            dx = math.sin(rad) * 200
            dy = math.cos(rad) * 200
            ponto_a = QgsPointXY(centro.x() - dx, centro.y() - dy)
            ponto_b = QgsPointXY(centro.x() + dx, centro.y() + dy)
            linha_ab_geom = QgsGeometry.fromPolylineXY([ponto_a, ponto_b])
        elif metodo == 'auto_slope':
            # Requer DEM
            print("⚠ Método auto_slope requer DEM (ainda não implementado)")
            azimute = calcular_direcao_auto_eixo(geom)
            centro = bounds.center()
            rad = math.radians(azimute)
            dx = math.sin(rad) * 200
            dy = math.cos(rad) * 200
            ponto_a = QgsPointXY(centro.x() - dx, centro.y() - dy)
            ponto_b = QgsPointXY(centro.x() + dx, centro.y() + dy)
            linha_ab_geom = QgsGeometry.fromPolylineXY([ponto_a, ponto_b])
        else:  # auto_eixo (padrão)
            azimute = calcular_direcao_auto_eixo(geom)
            centro = bounds.center()
            rad = math.radians(azimute)
            dx = math.sin(rad) * 200
            dy = math.cos(rad) * 200
            ponto_a = QgsPointXY(centro.x() - dx, centro.y() - dy)
            ponto_b = QgsPointXY(centro.x() + dx, centro.y() + dy)
            linha_ab_geom = QgsGeometry.fromPolylineXY([ponto_a, ponto_b])
        
        # Salvar na camada linha_ab
        linha_ab_layer = None
        for layer in projeto.mapLayers().values():
            if layer.name() == 'linha_ab':
                linha_ab_layer = layer
                break
        
        if not linha_ab_layer:
            print("✗ Camada 'linha_ab' não encontrada")
            return None
        
        provider = linha_ab_layer.dataProvider()
        
        nova_feat = QgsFeature(linha_ab_layer.fields())
        nova_feat.setGeometry(linha_ab_geom)
        
        max_id = 0
        for f in linha_ab_layer.getFeatures():
            if f['id'] > max_id:
                max_id = f['id']
        nova_feat.setAttribute('id', max_id + 1)
        nova_feat.setAttribute('id_talhao', id_talhao)
        nova_feat.setAttribute('azimute', azimute)
        nova_feat.setAttribute('metodo', metodo)
        
        provider.addFeature(nova_feat)
        linha_ab_layer.updateExtents()
        linha_ab_layer.triggerRepaint()
        
        print(f"✓ Linha AB criada: azimute {azimute:.1f}° (método: {metodo})")
        
        return nova_feat['id'], azimute
        
    except Exception as e:
        print(f"✗ Erro ao criar linha AB: {str(e)}")
        return None


# ============================================================================
# GERAÇÃO DE LINHAS PARALELAS
# ============================================================================

def gerar_linhas_plantio(
    id_talhao,
    cultura,
    espacamento_m=None,
    metodo_direcao='auto_eixo',
    azimute_manual=None,
    ponto_a=None,
    ponto_b=None,
    centralizar=True
):
    """
    Gera linhas de plantio paralelas dentro da área útil
    
    Parâmetros:
    - id_talhao: ID do talhão
    - cultura: Nome da cultura
    - espacamento_m: Espaçamento em metros (None = usar padrão cultura)
    - metodo_direcao: 'auto_eixo', 'auto_slope', 'manual'
    - azimute_manual: Azimute manual (se metodo='manual')
    - ponto_a: Ponto A manual
    - ponto_b: Ponto B manual
    - centralizar: Centralizar linhas no talhão
    
    Retorna:
    - feature_ids das linhas criadas
    - dict com estatísticas
    """
    try:
        projeto = QgsProject.instance()
        
        print(f"\n{'='*60}")
        print(f"GERANDO LINHAS DE PLANTIO - TALHÃO {id_talhao}")
        print(f"{'='*60}")
        
        # Encontrar talhão
        talhoes_layer = None
        for layer in projeto.mapLayers().values():
            if layer.name() == 'talhoes':
                talhoes_layer = layer
                break
        
        talhao_feat = None
        for feat in talhoes_layer.getFeatures():
            if feat['id'] == id_talhao:
                talhao_feat = feat
                break
        
        if not talhao_feat:
            print("✗ Talhão não encontrado")
            return None, None
        
        # Encontrar bordadura (área útil)
        bordaduras_layer = None
        bordadura_geom = talhao_feat.geometry()  # Padrão: usar talhão completo
        
        for layer in projeto.mapLayers().values():
            if layer.name() == 'bordaduras':
                bordaduras_layer = layer
                break
        
        if bordaduras_layer:
            for feat in bordaduras_layer.getFeatures():
                if feat['id_talhao'] == id_talhao:
                    bordadura_geom = feat.geometry()
                    break
        
        # Criar linha AB
        resultado_ab = criar_linha_ab(
            id_talhao=id_talhao,
            metodo=metodo_direcao,
            azimute_manual=azimute_manual,
            ponto_a=ponto_a,
            ponto_b=ponto_b
        )
        
        if not resultado_ab:
            return None, None
        
        linha_ab_id, azimute = resultado_ab
        
        # Determinar espaçamento
        espacamento = PlantioConfig.get_espacamento(cultura, espacamento_m)
        
        print(f"Espaçamento: {espacamento}m")
        print(f"Direção: {azimute:.1f}°")
        
        # Gerar linhas paralelas usando offset
        # Algoritmo: criar linhas paralelas via buffer e recorte
        
        bounds = bordadura_geom.boundingBox()
        diagonal = math.sqrt(bounds.width()**2 + bounds.height()**2)
        
        # Criar linha base perpendicular à direção AB
        rad_perp = math.radians(azimute + 90)
        
        # Número de linhas necessárias
        n_linhas = int(diagonal / espacamento) + 2
        
        # Criar linhas
        linhas_geom = []
        
        for i in range(-n_linhas, n_linhas + 1):
            offset = i * espacamento
            
            # Criar linha perpendicular deslocada
            centro = bounds.center()
            
            # Ponto inicial e final da linha
            dx = math.sin(rad_perp) * diagonal
            dy = math.cos(rad_perp) * diagonal
            
            # Aplicar offset perpendicular à direção AB
            rad_ab = math.radians(azimute)
            offset_x = math.sin(rad_ab) * offset
            offset_y = math.cos(rad_ab) * offset
            
            ponto_a = QgsPointXY(
                centro.x() - dx + offset_x,
                centro.y() - dy + offset_y
            )
            ponto_b = QgsPointXY(
                centro.x() + dx + offset_x,
                centro.y() + dy + offset_y
            )
            
            linha_geom = QgsGeometry.fromPolylineXY([ponto_a, ponto_b])
            
            # Recortar pela bordadura
            linha_recortada = linha_geom.intersection(bordadura_geom)
            
            if linha_recortada and not linha_recortada.isEmpty():
                # Verificar comprimento mínimo
                if linha_recortada.length() >= 10:  # Mínimo 10m
                    linhas_geom.append(linha_recortada)
        
        print(f"Linhas geradas: {len(linhas_geom)}")
        
        # Salvar na camada linhas_plantio
        linhas_layer = None
        for layer in projeto.mapLayers().values():
            if layer.name() == 'linhas_plantio':
                linhas_layer = layer
                break
        
        if not linhas_layer:
            print("✗ Camada 'linhas_plantio' não encontrada")
            return None, None
        
        provider = linhas_layer.dataProvider()
        
        feature_ids = []
        comprimento_total = 0
        
        max_id = 0
        for f in linhas_layer.getFeatures():
            if f['id'] > max_id:
                max_id = f['id']
        
        for idx, geom in enumerate(linhas_geom):
            nova_feat = QgsFeature(linhas_layer.fields())
            nova_feat.setGeometry(geom)
            
            max_id += 1
            nova_feat.setAttribute('id', max_id)
            nova_feat.setAttribute('id_talhao', id_talhao)
            nova_feat.setAttribute('cultura', cultura)
            nova_feat.setAttribute('espacamento_m', espacamento)
            nova_feat.setAttribute('direcao_graus', azimute)
            nova_feat.setAttribute('comprimento_m', geom.length())
            
            provider.addFeature(nova_feat)
            feature_ids.append(max_id)
            comprimento_total += geom.length()
        
        linhas_layer.updateExtents()
        linhas_layer.triggerRepaint()
        
        # Calcular estatísticas
        area_util = bordadura_geom.area() / 10000  # ha
        area_coberta = (comprimento_total * espacamento) / 10000  # ha
        
        estatisticas = {
            'total_linhas': len(linhas_geom),
            'comprimento_total_m': comprimento_total,
            'comprimento_total_km': comprimento_total / 1000,
            'area_util_ha': area_util,
            'area_coberta_ha': area_coberta,
            'espacamento_m': espacamento,
            'direcao_graus': azimute
        }
        
        print(f"\n✓ Linhas de plantio geradas com sucesso")
        print(f"  Total de linhas: {estatisticas['total_linhas']}")
        print(f"  Comprimento total: {estatisticas['comprimento_total_km']:.2f} km")
        print(f"  Área útil: {area_util:.2f} ha")
        
        return feature_ids, estatisticas
        
    except Exception as e:
        print(f"✗ Erro ao gerar linhas de plantio: {str(e)}")
        return None, None


def calcular_azimute_otimo(id_talhao, dem_path=None):
    """
    Calcula azimute ótimo baseado em análise de slope (avançado)
    
    Itera 180 direções e retorna a com menor variação de slope
    
    Parâmetros:
    - id_talhao: ID do talhão
    - dem_path: Caminho do DEM (opcional)
    
    Retorna:
    - Azimute em graus
    """
    if not dem_path:
        projeto = QgsProject.instance()
        talhoes_layer = None
        for layer in projeto.mapLayers().values():
            if layer.name() == 'talhoes':
                talhoes_layer = layer
                break
        
        talhao_feat = None
        for feat in talhoes_layer.getFeatures():
            if feat['id'] == id_talhao:
                talhao_feat = feat
                break
        
        if talhao_feat:
            return calcular_direcao_auto_eixo(talhao_feat.geometry())
    
    # Implementação completa requer SAGA slope + análise
    return calcular_direcao_auto_eixo(None)


# ============================================================================
# TABELA DE REFERÊNCIA
# ============================================================================

def tabela_referencia_plantio():
    """
    Imprime tabela de referência de plantio
    """
    tabela = """
    ============================================================================
    TABELA DE REFERÊNCIA - PLANTIO
    ============================================================================
    Cultura   | Espaçamento | Linhas/ha (aprox) | Observação
    ----------|-------------|-------------------|------------------------
    Soja      | 0.45m       | ~2222             | Padrão Brasil
    Milho     | 0.90m       | ~1111             | Padrão Brasil
    Algodão   | 0.90m       | ~1111             | Ou 0.76m (~1316/ha)
    Feijão    | 0.50m       | ~2000             | Padrão
    Sorgo     | 0.50m       | ~2000             | Padrão
    
    Linhas por hectare = 10000 / espaçamento
    
    Exemplo: Soja 0.45m = 10000 / 0.45 = 2222 linhas/ha
    ============================================================================
    """
    return tabela


# ============================================================================
# EXECUÇÃO
# ============================================================================

if __name__ == "__main__":
    print("""
    ============================================================================
    AAP GIS - PARTE 4: LINHAS DE PLANTIO
    ============================================================================
    
    Este script deve ser executado dentro do QGIS (Console Python)
    
    Para usar:
    >>> import sys
    >>> sys.path.insert(0, 'c:/caminho/para/scripts')
    >>> from aap_part4_plantio import *
    >>> 
    >>> # Gerar linhas de plantio
    >>> gerar_linhas_plantio(
    ...     id_talhao=1,
    ...     cultura='soja',
    ...     espacamento_m=0.45,
    ...     metodo_direcao='auto_eixo',
    ...     centralizar=True
    ... )
    >>> 
    >>> # Ver tabela de referência
    >>> print(tabela_referencia_plantio())
    ============================================================================
    """)
