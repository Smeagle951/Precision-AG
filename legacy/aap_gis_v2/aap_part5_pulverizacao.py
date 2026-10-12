"""
 ============================================================================
 AAP GIS - PARTE 5: LINHAS DE PULVERIZAÇÃO
 ============================================================================
 Sistema de Agricultura de Precisão com QGIS + SAGA GIS + PyQGIS
 
 Este script gera linhas de pulverização com espaçamento baseado na largura
 da barra, considerando sobreposição técnica e cobertura total da área.
 
 Autor: Sistema AAP GIS v2.0
 Data: 2024
 ============================================================================"""

import os
import math
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsField, QgsPointXY
)
from qgis import processing
from qgis.PyQt.QtCore import QVariant


# ============================================================================
# CONFIGURAÇÕES DE PULVERIZADORAS
# ============================================================================

class PulverizadoraConfig:
    """Configurações de pulverizadoras comuns no Brasil"""
    
    PRESETS = {
        'jacto_uniport_3030': {'largura_barra': 24.0, 'sobreposicao': 5.0},
        'jacto_uniport_4030': {'largura_barra': 28.0, 'sobreposicao': 5.0},
        'jd_r4044_24m': {'largura_barra': 24.0, 'sobreposicao': 5.0},
        'jd_r4044_30m': {'largura_barra': 30.0, 'sobreposicao': 5.0},
        'jd_r4044_36m': {'largura_barra': 36.0, 'sobreposicao': 5.0},
        'nh_guardian_24m': {'largura_barra': 24.0, 'sobreposicao': 5.0},
        'nh_guardian_30m': {'largura_barra': 30.0, 'sobreposicao': 5.0},
        'stara_touro_24m': {'largura_barra': 24.0, 'sobreposicao': 5.0},
        'stara_touro_30m': {'largura_barra': 30.0, 'sobreposicao': 5.0},
        'stara_touro_36m': {'largura_barra': 36.0, 'sobreposicao': 5.0},
    }
    
    @staticmethod
    def get_config(preset=None, largura_barra=None, sobreposicao=5.0):
        """
        Retorna configuração da pulverizadora
        
        Parâmetros:
        - preset: Nome do preset (ex: 'jacto_uniport_3030')
        - largura_barra: Largura da barra em metros
        - sobreposicao: Sobreposição em %
        
        Retorna:
        - dict com largura_barra e sobreposicao
        """
        if preset and preset in PulverizadoraConfig.PRESETS:
            return PulverizadoraConfig.PRESETS[preset]
        
        return {
            'largura_barra': largura_barra or 24.0,
            'sobreposicao': sobreposicao
        }
    
    @staticmethod
    def calcular_espacamento_efetivo(largura_barra, sobreposicao_pct):
        """
        Calcula espaçamento efetivo entre passadas
        
        Parâmetros:
        - largura_barra: Largura da barra em metros
        - sobreposicao_pct: Sobreposição em %
        
        Retorna:
        - Espaçamento efetivo em metros
        """
        return largura_barra * (1 - sobreposicao_pct / 100)


# ============================================================================
# FUNÇÕES DE GERAÇÃO DE LINHAS DE PULVERIZAÇÃO
# ============================================================================

def gerar_linhas_pulverizacao(
    id_talhao,
    largura_barra_m,
    sobreposicao_pct=5.0,
    incluir_bordadura=True,
    preset_maquina=None,
    densidade_calda_l_ha=None,
    velocidade_km_h=None
):
    """
    Gera linhas de pulverização cobrindo todo o talhão
    
    Parâmetros:
    - id_talhao: ID do talhão
    - largura_barra_m: Largura da barra em metros
    - sobreposicao_pct: Sobreposição entre passadas (%)
    - incluir_bordadura: Incluir bordadura na cobertura
    - preset_maquina: Preset da máquina (ex: 'jacto_uniport_3030')
    - densidade_calda_l_ha: Densidade de calda (L/ha)
    - velocidade_km_h: Velocidade operacional (km/h)
    
    Retorna:
    - feature_ids das linhas criadas
    - dict com estatísticas
    """
    try:
        projeto = QgsProject.instance()
        
        print(f"\n{'='*60}")
        print(f"GERANDO LINHAS DE PULVERIZAÇÃO - TALHÃO {id_talhao}")
        print(f"{'='*60}")
        
        # Obter configuração
        config = PulverizadoraConfig.get_config(
            preset=preset_maquina,
            largura_barra=largura_barra_m,
            sobreposicao=sobreposicao_pct
        )
        
        largura_barra = config['largura_barra']
        sobreposicao = config['sobreposicao']
        espacamento_efetivo = PulverizadoraConfig.calcular_espacamento_efetivo(
            largura_barra, sobreposicao
        )
        
        print(f"Largura barra: {largura_barra}m")
        print(f"Sobreposição: {sobreposicao}%")
        print(f"Espaçamento efetivo: {espacamento_efetivo:.2f}m")
        
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
        
        # Usar talhão completo (não apenas área útil)
        area_geom = talhao_feat.geometry()
        
        # Obter direção das linhas de plantio (se existirem)
        direcao_graus = 0
        linha_ab_layer = None
        for layer in projeto.mapLayers().values():
            if layer.name() == 'linha_ab':
                linha_ab_layer = layer
                break
        
        if linha_ab_layer:
            for feat in linha_ab_layer.getFeatures():
                if feat['id_talhao'] == id_talhao:
                    direcao_graus = feat['azimute']
                    break
        
        print(f"Direção: {direcao_graus:.1f}°")
        
        # Gerar linhas paralelas (algoritmo similar ao plantio)
        bounds = area_geom.boundingBox()
        diagonal = math.sqrt(bounds.width()**2 + bounds.height()**2)
        
        # Número de passadas
        n_passadas = int(diagonal / espacamento_efetivo) + 2
        
        # Criar linhas
        linhas_geom = []
        
        rad_perp = math.radians(direcao_graus + 90)
        
        for i in range(-n_passadas, n_passadas + 1):
            offset = i * espacamento_efetivo
            
            # Criar linha perpendicular deslocada
            centro = bounds.center()
            
            dx = math.sin(rad_perp) * diagonal
            dy = math.cos(rad_perp) * diagonal
            
            # Aplicar offset perpendicular à direção
            rad_ab = math.radians(direcao_graus)
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
            
            # Recortar pelo talhão completo
            linha_recortada = linha_geom.intersection(area_geom)
            
            if linha_recortada and not linha_recortada.isEmpty():
                if linha_recortada.length() >= 10:
                    linhas_geom.append(linha_recortada)
        
        print(f"Linhas geradas: {len(linhas_geom)}")
        
        # Salvar na camada linhas_pulverizacao
        linhas_layer = None
        for layer in projeto.mapLayers().values():
            if layer.name() == 'linhas_pulverizacao':
                linhas_layer = layer
                break
        
        if not linhas_layer:
            print("✗ Camada 'linhas_pulverizacao' não encontrada")
            return None, None
        
        provider = linhas_layer.dataProvider()
        
        feature_ids = []
        comprimento_total = 0
        
        max_id = 0
        for f in linhas_layer.getFeatures():
            if f['id'] > max_id:
                max_id = f['id']
        
        for geom in linhas_geom:
            nova_feat = QgsFeature(linhas_layer.fields())
            nova_feat.setGeometry(geom)
            
            max_id += 1
            nova_feat.setAttribute('id', max_id)
            nova_feat.setAttribute('id_talhao', id_talhao)
            nova_feat.setAttribute('largura_barra_m', largura_barra)
            nova_feat.setAttribute('sobreposicao_pct', sobreposicao)
            nova_feat.setAttribute('passadas', len(linhas_geom))
            
            provider.addFeature(nova_feat)
            feature_ids.append(max_id)
            comprimento_total += geom.length()
        
        linhas_layer.updateExtents()
        linhas_layer.triggerRepaint()
        
        # Calcular estatísticas
        area_total = area_geom.area() / 10000  # ha
        area_coberta = (comprimento_total * largura_barra) / 10000  # ha
        
        estatisticas = {
            'passadas': len(linhas_geom),
            'area_coberta_ha': area_coberta,
            'km_total': comprimento_total / 1000,
            'largura_barra_m': largura_barra,
            'sobreposicao_pct': sobreposicao,
            'espacamento_efetivo_m': espacamento_efetivo
        }
        
        # Calcular volume de calda e tempo se parâmetros fornecidos
        if densidade_calda_l_ha:
            estatisticas['volume_calda_l'] = area_coberta * densidade_calda_l_ha
        
        if velocidade_km_h:
            estatisticas['tempo_estimado_h'] = (comprimento_total / 1000) / velocidade_km_h
        
        print(f"\n✓ Linhas de pulverização geradas")
        print(f"  Passadas: {estatisticas['passadas']}")
        print(f"  Área coberta: {area_coberta:.2f} ha")
        print(f"  Distância total: {estatisticas['km_total']:.2f} km")
        
        if 'volume_calda_l' in estatisticas:
            print(f"  Volume de calda: {estatisticas['volume_calda_l']:.0f} L")
        
        if 'tempo_estimado_h' in estatisticas:
            print(f"  Tempo estimado: {estatisticas['tempo_estimado_h']:.1f} h")
        
        return feature_ids, estatisticas
        
    except Exception as e:
        print(f"✗ Erro ao gerar linhas de pulverização: {str(e)}")
        return None, None


def verificar_alinhamento_plantio_pulverizacao(id_talhao):
    """
    Verifica alinhamento entre linhas de plantio e pulverização
    
    Parâmetros:
    - id_talhao: ID do talhão
    
    Retorna:
    - dict com relatório de alinhamento
    """
    try:
        projeto = QgsProject.instance()
        
        # Obter espaçamento de plantio
        linhas_plantio_layer = None
        espacamento_plantio = 0.5  # Padrão
        
        for layer in projeto.mapLayers().values():
            if layer.name() == 'linhas_plantio':
                linhas_plantio_layer = layer
                break
        
        if linhas_plantio_layer:
            for feat in linhas_plantio_layer.getFeatures():
                if feat['id_talhao'] == id_talhao:
                    espacamento_plantio = feat['espacamento_m']
                    break
        
        # Obter largura da barra
        linhas_pulv_layer = None
        largura_barra = 24.0  # Padrão
        
        for layer in projeto.mapLayers().values():
            if layer.name() == 'linhas_pulverizacao':
                linhas_pulv_layer = layer
                break
        
        if linhas_pulv_layer:
            for feat in linhas_pulv_layer.getFeatures():
                if feat['id_talhao'] == id_talhao:
                    largura_barra = feat['largura_barra_m']
                    break
        
        # Verificar se é múltiplo
        relacao = largura_barra / espacamento_plantio
        is_multiplo = abs(relacao - round(relacao)) < 0.01
        
        relatorio = {
            'espacamento_plantio_m': espacamento_plantio,
            'largura_barra_m': largura_barra,
            'relacao': relacao,
            'linhas_por_passada': round(relacao),
            'alinhado': is_multiplo
        }
        
        print(f"\n{'='*60}")
        print("RELATÓRIO DE ALINHAMENTO")
        print(f"{'='*60}")
        print(f"Espaçamento plantio: {espacamento_plantio}m")
        print(f"Largura barra: {largura_barra}m")
        print(f"Relação: {largura_barra} / {espacamento_plantio} = {relacao:.2f}")
        print(f"Linhas de plantio por passada: {relacao['linhas_por_passada']}")
        
        if is_multiplo:
            print("✓ ALINHADO: relação é número inteiro")
        else:
            print("⚠ DESALINHADO: relação não é inteiro")
        
        return relatorio
        
    except Exception as e:
        print(f"✗ Erro ao verificar alinhamento: {str(e)}")
        return None


def gerar_linhas_bordadura_pulverizacao(id_talhao, largura_barra_m):
    """
    Gera linhas de pulverização na bordadura (passadas circulares)
    
    Segue o contorno interno da bordadura com voltas concêntricas
    
    Parâmetros:
    - id_talhao: ID do talhão
    - largura_barra_m: Largura da barra em metros
    
    Retorna:
    - feature_ids ou None
    """
    try:
        projeto = QgsProject.instance()
        
        # Encontrar bordadura
        bordaduras_layer = None
        bordadura_geom = None
        
        for layer in projeto.mapLayers().values():
            if layer.name() == 'bordaduras':
                bordaduras_layer = layer
                break
        
        if bordaduras_layer:
            for feat in bordaduras_layer.getFeatures():
                if feat['id_talhao'] == id_talhao:
                    bordadura_geom = feat.geometry()
                    break
        
        if not bordadura_geom:
            print("⚠ Bordadura não encontrada")
            return None
        
        largura_bordadura = bordadura_geom.constGet().area()  # Simplificado
        
        # Número de voltas
        n_voltas = math.ceil(largura_bordadura / largura_barra_m)
        
        print(f"Gerando {n_voltas} voltas na bordadura")
        
        # Implementação: usar offset de polilinha
        # Para simplificação, criar buffer concêntrico
        linhas_geom = []
        
        for i in range(n_voltas):
            offset = i * largura_barra_m
            
            # Buffer negativo da bordadura
            params = {
                'INPUT': bordadura_geom,
                'DISTANCE': -offset,
                'SEGMENTS': 20,
                'OUTPUT': 'memory:'
            }
            
            result = processing.run("native:buffer", params)
            buffer_geom = result['OUTPUT']
            
            if buffer_geom and not buffer_geom.isEmpty():
                # Converter polígono para linha (boundary)
                params = {
                    'INPUT': buffer_geom,
                    'OUTPUT': 'memory:'
                }
                result = processing.run("native:boundary", params)
                linha_geom = result['OUTPUT']
                
                if linha_geom and not linha_geom.isEmpty():
                    linhas_geom.append(linha_geom)
        
        # Salvar como tipo especial (requer campo adicional)
        # Para simplificação, adicionar ao layer existente com atributo
        
        return linhas_geom
        
    except Exception as e:
        print(f"✗ Erro ao gerar linhas de bordadura: {str(e)}")
        return None


# ============================================================================
# TABELA DE REFERÊNCIA
# ============================================================================

def tabela_presets_pulverizadoras():
    """
    Imprime tabela de presets de pulverizadoras
    """
    tabela = """
    ============================================================================
    TABELA DE PRESETS - PULVERIZADORAS BRASILEIRAS
    ============================================================================
    Marca/Modelo           | Barra  | Sobreposição | Preset
    ------------------------|--------|--------------|--------------------------
    Jacto Uniport 3030      | 24m    | 5%           | jacto_uniport_3030
    Jacto Uniport 4030      | 28m    | 5%           | jacto_uniport_4030
    John Deere R4044       | 24m    | 5%           | jd_r4044_24m
    John Deere R4044       | 30m    | 5%           | jd_r4044_30m
    John Deere R4044       | 36m    | 5%           | jd_r4044_36m
    New Holland Guardian   | 24m    | 5%           | nh_guardian_24m
    New Holland Guardian   | 30m    | 5%           | nh_guardian_30m
    Stara Touro            | 24m    | 5%           | stara_touro_24m
    Stara Touro            | 30m    | 5%           | stara_touro_30m
    Stara Touro            | 36m    | 5%           | stara_touro_36m
    
    Cálculo:
    Espaçamento efetivo = largura_barra × (1 - sobreposicao/100)
    
    Exemplo: Barra 24m + 5% = 24 × 0.95 = 22.8m entre passadas
    
    Volume de calda:
    Volume (L) = Área (ha) × Densidade (L/ha)
    
    Tempo estimado:
    Tempo (h) = Distância total (km) / Velocidade (km/h)
    ============================================================================
    """
    return tabela


# ============================================================================
# EXECUÇÃO
# ============================================================================

if __name__ == "__main__":
    print("""
    ============================================================================
    AAP GIS - PARTE 5: LINHAS DE PULVERIZAÇÃO
    ============================================================================
    
    Este script deve ser executado dentro do QGIS (Console Python)
    
    Para usar:
    >>> import sys
    >>> sys.path.insert(0, 'c:/caminho/para/scripts')
    >>> from aap_part5_pulverizacao import *
    >>> 
    >>> # Gerar linhas de pulverização
    >>> gerar_linhas_pulverizacao(
    ...     id_talhao=1,
    ...     largura_barra_m=30.0,
    ...     sobreposicao_pct=5.0,
    ...     preset_maquina='jd_r4044_30m',
    ...     densidade_calda_l_ha=100,
    ...     velocidade_km_h=15
    ... )
    >>> 
    >>> # Verificar alinhamento
    >>> verificar_alinhamento_plantio_pulverizacao(id_talhao=1)
    >>> 
    >>> # Ver tabela de presets
    >>> print(tabela_presets_pulverizadoras())
    ============================================================================
    """)
