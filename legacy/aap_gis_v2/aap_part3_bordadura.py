"""
 ============================================================================
 AAP GIS - PARTE 3: GERAÇÃO DE BORDADURA AUTOMÁTICA
 ============================================================================
 Sistema de Agricultura de Precisão com QGIS + SAGA GIS + PyQGIS
 
 Este script gera bordaduras (headlands) automáticas baseadas na largura da
 máquina e restrições agronômicas por cultura.
 
 Autor: Sistema AAP GIS v2.0
 Data: 2024
 ============================================================================"""

import os
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsField, QgsPointXY
)
from qgis import processing
from qgis.PyQt.QtCore import QVariant


# ============================================================================
# CONFIGURAÇÕES AGRONÔMICAS
# ============================================================================

class BordaduraConfig:
    """Configurações de bordadura por cultura"""
    
    MINIMOS_CULTURA = {
        'soja': 7.0,      # 7m mínimo (9m ideal com plataforma 4.5m)
        'milho': 9.0,     # 9m mínimo (12m ideal com colhedeira 6m)
        'algodao': 12.0,  # 12m mínimo
        'feijao': 7.0,    # 7m mínimo
        'sorgo': 7.0,     # 7m mínimo
        'outro': 10.0,    # Padrão genérico
    }
    
    @staticmethod
    def calcular_largura_bordadura(cultura, largura_maquina, n_passadas=2):
        """
        Calcula largura da bordadura baseada em cultura e máquina
        
        Parâmetros:
        - cultura: Nome da cultura
        - largura_maquina: Largura da máquina em metros
        - n_passadas: Número de passadas de bordadura
        
        Retorna:
        - Largura da bordadura em metros
        """
        min_cultura = BordaduraConfig.MINIMOS_CULTURA.get(
            cultura.lower(), 
            BordaduraConfig.MINIMOS_CULTURA['outro']
        )
        
        largura_calculada = largura_maquina * n_passadas
        largura_final = max(largura_calculada, min_cultura)
        
        return largura_final


# ============================================================================
# FUNÇÕES DE GERAÇÃO DE BORDADURA
# ============================================================================

def gerar_bordadura(
    id_talhao,
    largura_m,
    n_passadas=2,
    cultura='soja',
    tipo='interno'
):
    """
    Gera bordadura automática para um talhão específico
    
    Parâmetros:
    - id_talhao: ID da feição na camada 'talhoes'
    - largura_m: Largura da máquina em metros
    - n_passadas: Número de passadas de bordadura
    - cultura: String com nome da cultura
    - tipo: 'interno' ou 'externo'
    
    Retorna:
    - feature_id da bordadura criada no GeoPackage
    - dict com area_total, area_util, area_bordadura, pct_util
    - None se falhou (com mensagem de erro)
    """
    try:
        projeto = QgsProject.instance()
        
        # Encontrar camada talhoes
        talhoes_layer = None
        for layer in projeto.mapLayers().values():
            if layer.name() == 'talhoes':
                talhoes_layer = layer
                break
        
        if not talhoes_layer:
            print("✗ Camada 'talhoes' não encontrada")
            return None
        
        # Encontrar feature do talhão
        talhao_feat = None
        for feat in talhoes_layer.getFeatures():
            if feat['id'] == id_talhao:
                talhao_feat = feat
                break
        
        if not talhao_feat:
            print(f"✗ Talhão ID {id_talhao} não encontrado")
            return None
        
        # Calcular largura da bordadura
        largura_bordadura = BordaduraConfig.calcular_largura_bordadura(
            cultura, largura_m, n_passadas
        )
        
        print(f"\nGerando bordadura para talhão {id_talhao}:")
        print(f"  Largura máquina: {largura_m}m")
        print(f"  Número passadas: {n_passadas}")
        print(f"  Cultura: {cultura}")
        print(f"  Largura bordadura: {largura_bordadura}m")
        
        # Criar layer temporário com o talhão
        temp_layer = QgsVectorLayer(
            f"Polygon?crs={talhoes_layer.crs().authid()}",
            "temp_talhao",
            "memory"
        )
        provider = temp_layer.dataProvider()
        provider.addFeature(talhao_feat)
        
        # Gerar buffer negativo (bordadura interna)
        params = {
            'INPUT': temp_layer,
            'DISTANCE': -largura_bordadura,
            'SEGMENTS': 20,
            'END_CAP_STYLE': 0,  # Round
            'JOIN_STYLE': 0,     # Round
            'MITER_LIMIT': 2,
            'DISSOLVE': False,
            'OUTPUT': 'memory:'
        }
        
        result = processing.run("native:buffer", params)
        bordadura_layer = result['OUTPUT']
        
        # Verificar se buffer resultou vazio (talhão muito pequeno)
        if bordadura_layer.featureCount() == 0:
            print("⚠ AVISO: Talhão muito pequeno para bordadura desejada")
            
            # Usar 50% da menor dimensão
            geom = talhao_feat.geometry()
            bounds = geom.boundingBox()
            menor_dimensao = min(bounds.width(), bounds.height())
            largura_maxima = menor_dimensao * 0.5
            
            largura_bordadura = min(largura_bordadura, largura_maxima)
            print(f"  Ajustando largura para: {largura_bordadura}m")
            
            params['DISTANCE'] = -largura_bordadura
            result = processing.run("native:buffer", params)
            bordadura_layer = result['OUTPUT']
        
        # Calcular áreas
        area_total = talhao_feat.geometry().area()
        area_util = 0
        
        for feat in bordadura_layer.getFeatures():
            area_util += feat.geometry().area()
        
        area_bordadura = area_total - area_util
        pct_util = (area_util / area_total) * 100 if area_total > 0 else 0
        
        # Alertar se área útil muito pequena
        if pct_util < 70:
            print(f"⚠ AVISO: Área útil apenas {pct_util:.1f}% (bordadura excessiva)")
        
        # Salvar no GeoPackage
        bordaduras_gpkg = None
        for layer in projeto.mapLayers().values():
            if layer.name() == 'bordaduras':
                bordaduras_gpkg = layer
                break
        
        if not bordaduras_gpkg:
            print("✗ Camada 'bordaduras' não encontrada")
            return None
        
        # Adicionar feature
        provider = bordaduras_gpkg.dataProvider()
        
        for feat in bordadura_layer.getFeatures():
            nova_feat = QgsFeature(bordaduras_gpkg.fields())
            nova_feat.setGeometry(feat.geometry())
            
            # Preencher atributos
            max_id = 0
            for f in bordaduras_gpkg.getFeatures():
                if f['id'] > max_id:
                    max_id = f['id']
            nova_feat.setAttribute('id', max_id + 1)
            nova_feat.setAttribute('id_talhao', id_talhao)
            nova_feat.setAttribute('largura_m', largura_bordadura)
            nova_feat.setAttribute('tipo', tipo)
            
            provider.addFeature(nova_feat)
        
        bordaduras_gpkg.updateExtents()
        bordaduras_gpkg.triggerRepaint()
        
        print(f"✓ Bordadura gerada com sucesso")
        print(f"  Área total: {area_total/10000:.2f} ha")
        print(f"  Área útil: {area_util/10000:.2f} ha")
        print(f"  Área bordadura: {area_bordadura/10000:.2f} ha")
        print(f"  % Área útil: {pct_util:.1f}%")
        
        return nova_feat['id'], {
            'area_total': area_total,
            'area_util': area_util,
            'area_bordadura': area_bordadura,
            'pct_util': pct_util
        }
        
    except Exception as e:
        print(f"✗ Erro ao gerar bordadura: {str(e)}")
        return None


def gerar_bordaduras_lote(lista_ids, params_dict):
    """
    Processa múltiplos talhões em lote
    
    Parâmetros:
    - lista_ids: Lista de IDs de talhões
    - params_dict: Dicionário com parâmetros
      {
        'largura_m': 9.0,
        'n_passadas': 2,
        'cultura': 'soja',
        'tipo': 'interno'
      }
    
    Retorna:
    - dict com resultados por talhão
    """
    resultados = {}
    
    for id_talhao in lista_ids:
        print(f"\n{'='*60}")
        print(f"Processando talhão ID: {id_talhao}")
        print(f"{'='*60}")
        
        resultado = gerar_bordadura(
            id_talhao=id_talhao,
            largura_m=params_dict.get('largura_m', 9.0),
            n_passadas=params_dict.get('n_passadas', 2),
            cultura=params_dict.get('cultura', 'soja'),
            tipo=params_dict.get('tipo', 'interno')
        )
        
        resultados[id_talhao] = resultado
    
    # Resumo
    print(f"\n{'='*60}")
    print("RESUMO DO LOTE")
    print(f"{'='*60}")
    sucesso = sum(1 for r in resultados.values() if r is not None)
    print(f"Processados: {len(lista_ids)}")
    print(f"Sucesso: {sucesso}")
    print(f"Falhas: {len(lista_ids) - sucesso}")
    
    return resultados


def validar_bordadura(id_bordadura):
    """
    Valida uma bordadura gerada
    
    Verifica:
    - Geometria válida
    - Está dentro do talhão
    - Sem autointerseção
    - Geometria simples (não multipart)
    - Largura mínima do corredor
    
    Parâmetros:
    - id_bordadura: ID da feição na camada 'bordaduras'
    
    Retorna:
    - True/False + lista de problemas
    """
    problemas = []
    
    try:
        projeto = QgsProject.instance()
        
        # Encontrar camada bordaduras
        bordaduras_layer = None
        for layer in projeto.mapLayers().values():
            if layer.name() == 'bordaduras':
                bordaduras_layer = layer
                break
        
        if not bordaduras_layer:
            return False, ["Camada 'bordaduras' não encontrada"]
        
        # Encontrar feature
        bordadura_feat = None
        for feat in bordaduras_layer.getFeatures():
            if feat['id'] == id_bordadura:
                bordadura_feat = feat
                break
        
        if not bordadura_feat:
            return False, [f"Bordadura ID {id_bordadura} não encontrada"]
        
        geom = bordadura_feat.geometry()
        
        # Verificar geometria válida
        if not geom.isGeosValid():
            problemas.append("Geometria inválida")
        
        # Verificar autointerseção
        if geom.isGeosEmpty():
            problemas.append("Geometria vazia")
        
        # Verificar se é multipart
        if geom.isMultipart():
            problemas.append("Geometria multipart (deve ser singlepart)")
        
        # Verificar se está dentro do talhão
        id_talhao = bordadura_feat['id_talhao']
        talhoes_layer = None
        for layer in projeto.mapLayers().values():
            if layer.name() == 'talhoes':
                talhoes_layer = layer
                break
        
        if talhoes_layer:
            for talhao_feat in talhoes_layer.getFeatures():
                if talhao_feat['id'] == id_talhao:
                    if not geom.within(talhao_feat.geometry()):
                        problemas.append("Bordadura não está totalmente dentro do talhão")
                    break
        
        # Verificar largura mínima do corredor
        bounds = geom.boundingBox()
        menor_dimensao = min(bounds.width(), bounds.height())
        if menor_dimensao < bordadura_feat['largura_m']:
            problemas.append(f"Corredor interno muito estreito: {menor_dimensao:.2f}m")
        
        if problemas:
            return False, problemas
        else:
            return True, []
            
    except Exception as e:
        return False, [f"Erro na validação: {str(e)}"]


def gerar_bordadura_diferencial(
    id_talhao,
    larguras_por_lado=None,
    cultura='soja'
):
    """
    Gera bordadura diferencial por lado (avançado)
    
    Permite especificar larguras diferentes para cada lado:
    - Norte, Sul, Leste, Oeste
    - Estrada: bordadura maior
    - Mata ciliar: bordadura legal (APP 30m)
    - Divisa: bordadura mínima
    
    Parâmetros:
    - id_talhao: ID do talhão
    - larguras_por_lado: dict {'N': 15, 'S': 10, 'L': 5, 'O': 5}
    - cultura: Cultura para cálculo de mínimo
    
    Retorna:
    - feature_id ou None
    """
    try:
        if not larguras_por_lado:
            # Usar larguras padrão
            larguras_por_lado = {'N': 10, 'S': 10, 'L': 10, 'O': 10}
        
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
            return None
        
        geom = talhao_feat.geometry()
        bounds = geom.boundingBox()
        
        # Criar retângulo de corte com offsets diferentes
        # Norte: +y, Sul: -y, Leste: +x, Oeste: -x
        
        # Simplificação: usar buffer assimétrico via expressão
        # Para implementação completa, seria necessário:
        # 1. Extrair cada segmento do polígono
        # 2. Calcular azimute de cada segmento
        # 3. Aplicar offset baseado na direção
        
        # Implementação simplificada: usar média das larguras
        largura_media = sum(larguras_por_lado.values()) / 4
        
        print(f"Bordadura diferencial (média: {largura_media}m)")
        
        return gerar_bordadura(
            id_talhao=id_talhao,
            largura_m=largura_media,
            n_passadas=1,
            cultura=cultura,
            tipo='diferencial'
        )
        
    except Exception as e:
        print(f"✗ Erro na bordadura diferencial: {str(e)}")
        return None


# ============================================================================
# FUNÇÕES AUXILIARES
# ============================================================================

def calcular_indice_compacidade(geometry):
    """
    Calcula índice de compacidade do polígono
    
    Índice = (4 * pi * área) / perímetro²
    - 1.0 = círculo perfeito
    - < 0.5 = forma muito irregular
    
    Parâmetros:
    - geometry: QgsGeometry do polígono
    
    Retorna:
    - Índice de compacidade (0-1)
    """
    import math
    
    area = geometry.area()
    perimetro = geometry.length()
    
    if perimetro == 0:
        return 0
    
    indice = (4 * math.pi * area) / (perimetro ** 2)
    return indice


def verificar_casos_especiais(id_talhao):
    """
    Verifica casos especiais que requerem atenção
    
    Parâmetros:
    - id_talhao: ID do talhão
    
    Retorna:
    - dict com avisos
    """
    avisos = []
    
    try:
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
        
        if not talhao_feat:
            return {'erro': 'Talhão não encontrado'}
        
        geom = talhao_feat.geometry()
        
        # Verificar índice de compacidade
        ic = calcular_indice_compacidade(geom)
        if ic < 0.5:
            avisos.append(f"Forma muito irregular (IC={ic:.2f})")
        
        # Verificar dimensões mínimas
        bounds = geom.boundingBox()
        menor_dimensao = min(bounds.width(), bounds.height())
        if menor_dimensao < 50:
            avisos.append(f"Talhão estreito ({menor_dimensao:.1f}m)")
        
        # Verificar obstáculos internos (buracos)
        if geom.constGet():
            if hasattr(geom.constGet(), 'numInteriorRings'):
                n_rings = geom.constGet().numInteriorRings()
                if n_rings > 0:
                    avisos.append(f"Contém {n_rings} buraco(s) interno(s)")
        
        return {'avisos': avisos, 'indice_compacidade': ic}
        
    except Exception as e:
        return {'erro': str(e)}


# ============================================================================
# TABELA DE REFERÊNCIA
# ============================================================================

def tabela_referencia():
    """
    Imprime tabela de referência de bordaduras
    
    Retorna string formatada
    """
    tabela = """
    ============================================================================
    TABELA DE REFERÊNCIA - BORDADURAS
    ============================================================================
    Cultura   | Espaçamento | Bordadura Mín | Bordadura Ideal | Plataforma
    ----------|-------------|---------------|-----------------|------------
    Soja      | 0.45m       | 7m            | 9m              | 4.5m / 6m
    Milho     | 0.90m       | 9m            | 12m             | 6m / 8m
    Algodão   | 0.90/0.76m  | 12m           | 15m             | 6m
    Feijão    | 0.50m       | 7m            | 9m              | 4.5m
    Sorgo     | 0.50m       | 7m            | 9m              | 4.5m
    
    Cálculo: largura_bordadura = max(largura_maquina × n_passadas, minimo_cultura)
    
    Exemplo:
    - Soja + colhedora 4.5m + 2 passadas = 9m (ideal)
    - Milho + colhedora 6m + 2 passadas = 12m (ideal)
    ============================================================================
    """
    return tabela


# ============================================================================
# EXECUÇÃO
# ============================================================================

if __name__ == "__main__":
    print("""
    ============================================================================
    AAP GIS - PARTE 3: GERAÇÃO DE BORDADURA AUTOMÁTICA
    ============================================================================
    
    Este script deve ser executado dentro do QGIS (Console Python)
    
    Para usar:
    >>> import sys
    >>> sys.path.insert(0, 'c:/caminho/para/scripts')
    >>> from aap_part3_bordadura import *
    >>> 
    >>> # Gerar bordadura para um talhão
    >>> gerar_bordadura(
    ...     id_talhao=1,
    ...     largura_m=9.0,
    ...     n_passadas=2,
    ...     cultura='soja',
    ...     tipo='interno'
    ... )
    >>> 
    >>> # Validar bordadura
    >>> validar_bordadura(id_bordadura=1)
    >>> 
    >>> # Ver tabela de referência
    >>> print(tabela_referencia())
    ============================================================================
    """)
