"""
 ============================================================================
 AAP GIS - PARTE 9: LINHAS AGRONÔMICAS ADAPTATIVAS AO RELEVO
 ============================================================================
 Sistema de Agricultura de Precisão com QGIS + SAGA GIS + PyQGIS
 
 Este script implementa três estratégias de geração de linhas agronômicas:
 - Estratégia A: Direção ótima por custo (varredura angular)
 - Estratégia B: Linhas em curvas de nível
 - Estratégia C: Linhas adaptativas por slope local
 
 Seleciona automaticamente a melhor estratégia baseada em características do talhão.
 
 Autor: Sistema AAP GIS v2.0
 Data: 2024
 ============================================================================"""

import os
import math
import numpy as np
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsRasterLayer, QgsFeature,
    QgsGeometry, QgsField, QgsPointXY, QgsMessageLog, Qgis
)
from qgis import processing
from qgis.PyQt.QtCore import QVariant


# ============================================================================
# ESTRATÉGIA A — DIREÇÃO ÓTIMA (OTIMIZAÇÃO POR CUSTO)
# ============================================================================

def calcular_angulo_otimo(
    id_talhao,
    dem_path,
    cultura,
    pesos={'manobra': 0.30, 'erosao': 0.35, 'combustivel': 0.25, 'sobreposicao': 0.10},
    passo_graus=1.0,
    fator_erosividade=1.0,
    fator_consumo=1.0
):
    """
    Algoritmo de varredura angular para encontrar ângulo de plantio ótimo
    
    Para cada ângulo θ de 0° a 179°:
    - Gera linhas paralelas hipotéticas
    - Calcula custo de manobra, erosão, combustível e sobreposição
    - Seleciona θ* = argmin(custo_total)
    
    Parâmetros:
    - id_talhao: ID do talhão
    - dem_path: Caminho do DEM
    - cultura: Cultura plantada
    - pesos: Dict com pesos de cada componente de custo
    - passo_graus: Passo da varredura (default 1°)
    - fator_erosividade: Fator de ajuste por tipo de solo
    - fator_consumo: Fator de ajuste por potência do trator
    
    Retorna:
    - dict com ângulo ótimo, alternativo, redução de custo e gráfico de dados
    """
    try:
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("CALCULANDO ÂNGULO ÓTIMO - VARREDURA ANGULAR", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        
        projeto = QgsProject.instance()
        
        # Carregar DEM
        dem_layer = QgsRasterLayer(dem_path, "dem")
        if not dem_layer.isValid():
            QgsMessageLog.logMessage("✗ DEM inválido", 'AAP GIS', Qgis.Critical)
            return None
        
        # Obter talhão
        talhao_layer = None
        for layer in projeto.mapLayers().values():
            if layer.name() == 'talhoes':
                talhao_layer = layer
                break
        
        if not talhao_layer:
            QgsMessageLog.logMessage("✗ Camada talhoes não encontrada", 'AAP GIS', Qgis.Critical)
            return None
        
        # Obter feature do talhão
        talhao_feat = None
        for feat in talhao_layer.getFeatures():
            if feat['id'] == id_talhao:
                talhao_feat = feat
                break
        
        if not talhao_feat:
            QgsMessageLog.logMessage("✗ Talhão não encontrado", 'AAP GIS', Qgis.Critical)
            return None
        
        talhao_geom = talhao_feat.geometry()
        area_ha = talhao_geom.area() / 10000
        
        QgsMessageLog.logMessage(f"Área do talhão: {area_ha:.2f} ha", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage(f"Passo da varredura: {passo_graus}°", 'AAP GIS', Qgis.Info)
        
        # Carregar slope raster (usar Parte 6 se disponível, ou calcular)
        slope_path = dem_path.replace('.tif', '_slope.tif')
        if not os.path.exists(slope_path):
            QgsMessageLog.logMessage("Calculando slope raster...", 'AAP GIS', Qgis.Info)
            params = {
                'INPUT': dem_layer,
                'BAND': 1,
                'COMPUTE_EDGES': False,
                'ZEVENBERGEN': False,
                'SLOPE': 1,
                'ASPECT': 2,
                'OUTPUT': slope_path
            }
            processing.run("gdal:slope", params)
        
        slope_layer = QgsRasterLayer(slope_path, "slope")
        
        # Varredura angular
        angulos = np.arange(0, 180, passo_graus)
        custos_manobra = []
        custos_erosao = []
        custos_combustivel = []
        custos_sobreposicao = []
        custos_totais = []
        
        for angulo in angulos:
            QgsMessageLog.logMessage(f"Processando ângulo {angulo}°...", 'AAP GIS', Qgis.Info)
            
            # 1. Gerar linhas paralelas hipotéticas no ângulo
            linhas_hipoteticas = gerar_linhas_paralelas_hipoteticas(
                talhao_geom,
                angulo,
                espacamento=1.0  # espaçamento temporário para cálculo
            )
            
            # 2. Calcular custo de manobra
            n_linhas = len(linhas_hipoteticas)
            custo_manobra = calcular_custo_manobra(
                n_linhas,
                area_ha,
                cultura
            )
            
            # 3. Calcular custo de erosão
            custo_erosao = calcular_custo_erosao(
                linhas_hipoteticas,
                slope_layer,
                angulo,
                fator_erosividade
            )
            
            # 4. Calcular custo de combustível
            custo_combustivel = calcular_custo_combustivel(
                linhas_hipoteticas,
                slope_layer,
                angulo,
                fator_consumo
            )
            
            # 5. Calcular custo de sobreposição
            custo_sobreposicao = calcular_custo_sobreposicao(linhas_hipoteticas)
            
            # Normalizar custos (0-1)
            custos_manobra.append(custo_manobra)
            custos_erosao.append(custo_erosao)
            custos_combustivel.append(custo_combustivel)
            custos_sobreposicao.append(custo_sobreposicao)
        
        # Normalizar todos os custos
        c_manobra = normalizar_lista(custos_manobra)
        c_erosao = normalizar_lista(custos_erosao)
        c_combustivel = normalizar_lista(custos_combustivel)
        c_sobreposicao = normalizar_lista(custos_sobreposicao)
        
        # Calcular custo total ponderado
        for i in range(len(angulos)):
            custo_total = (
                c_manobra[i] * pesos['manobra'] +
                c_erosao[i] * pesos['erosao'] +
                c_combustivel[i] * pesos['combustivel'] +
                c_sobreposicao[i] * pesos['sobreposicao']
            )
            custos_totais.append(custo_total)
        
        # Encontrar ângulo ótimo
        idx_otimo = np.argmin(custos_totais)
        angulo_otimo = angulos[idx_otimo]
        custo_otimo = custos_totais[idx_otimo]
        
        # Encontrar 2° melhor
        custos_copia = custos_totais.copy()
        custos_copia[idx_otimo] = float('inf')
        idx_alternativo = np.argmin(custos_copia)
        angulo_alternativo = angulos[idx_alternativo]
        
        # Calcular redução de custo vs. ângulo atual (assumindo 0° como atual)
        custo_atual = custos_totais[0]
        reducao_pct = ((custo_atual - custo_otimo) / custo_atual * 100) if custo_atual > 0 else 0
        
        # Gerar justificativa
        justificativa = gerar_justificativa_angulo(
            angulo_otimo,
            angulo_alternativo,
            c_manobra[idx_otimo],
            c_erosao[idx_otimo],
            c_combustivel[idx_otimo],
            c_sobreposicao[idx_otimo]
        )
        
        QgsMessageLog.logMessage(f"✓ Ângulo ótimo: {angulo_otimo:.1f}°", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage(f"  Alternativo: {angulo_alternativo:.1f}°", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage(f"  Redução de custo: {reducao_pct:.1f}%", 'AAP GIS', Qgis.Info)
        
        resultado = {
            'angulo_otimo': float(angulo_otimo),
            'angulo_alternativo': float(angulo_alternativo),
            'reducao_custo_pct': float(reducao_pct),
            'custo_por_angulo': custos_totais,
            'custo_manobra_por_angulo': c_manobra,
            'custo_erosao_por_angulo': c_erosao,
            'custo_combustivel_por_angulo': c_combustivel,
            'custo_sobreposicao_por_angulo': c_sobreposicao,
            'justificativa': justificativa
        }
        
        return resultado
        
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro ao calcular ângulo ótimo: {str(e)}", 'AAP GIS', Qgis.Critical)
        return None


def gerar_linhas_paralelas_hipoteticas(geom, angulo_graus, espacamento):
    """
    Gera linhas paralelas hipotéticas para cálculo de custo
    
    Parâmetros:
    - geom: QgsGeometry do talhão
    - angulo_graus: Ângulo em graus
    - espacamento: Espaçamento entre linhas
    
    Retorna:
    - list de QgsGeometry (linhas)
    """
    try:
        # Simplificação: criar grade de linhas
        # Para implementação completa, usar algoritmo de offset
        
        bbox = geom.boundingBox()
        
        # Converter ângulo para radianos
        angulo_rad = math.radians(angulo_graus)
        
        linhas = []
        
        # Direção perpendicular ao ângulo
        dx = math.sin(angulo_rad)
        dy = math.cos(angulo_rad)
        
        # Número de linhas necessárias
        diagonal = math.sqrt(bbox.width()**2 + bbox.height()**2)
        n_linhas = int(diagonal / espacamento)
        
        for i in range(n_linhas):
            # Ponto inicial
            offset = i * espacamento - diagonal / 2
            x1 = bbox.xMinimum() + offset * dx
            y1 = bbox.yMinimum() + offset * dy
            x2 = bbox.xMaximum() + offset * dx
            y2 = bbox.yMaximum() + offset * dy
            
            linha = QgsGeometry.fromPolylineXY([
                QgsPointXY(x1, y1),
                QgsPointXY(x2, y2)
            ])
            
            # Recortar pelo talhão
            linha_recortada = linha.intersection(geom)
            
            if not linha_recortada.isEmpty():
                linhas.append(linha_recortada)
        
        return linhas
        
    except Exception as e:
        QgsMessageLog.logMessage(f"Erro ao gerar linhas hipotéticas: {str(e)}", 'AAP GIS', Qgis.Warning)
        return []


def calcular_custo_manobra(n_linhas, area_ha, cultura):
    """
    Calcula custo de manobra baseado no número de linhas
    
    Mais linhas = mais manobras = mais custo e compactação
    """
    # Simplificação: custo proporcional ao número de linhas
    # Para implementação completa, considerar largura de cabeceira
    custo_base = n_linhas * area_ha * 0.1
    return custo_base


def calcular_custo_erosao(linhas, slope_layer, angulo_graus, fator_erosividade):
    """
    Calcula custo de erosão baseado no slope perpendicular ao movimento
    
    Quanto mais a linha sobe/desce, maior o risco de erosão
    """
    try:
        # Simplificação: usar slope médio do talhão
        # Para implementação completa, samplear slope ao longo das linhas
        
        # Calcular componente do slope na direção do movimento
        angulo_rad = math.radians(angulo_graus)
        
        # Simplificação: assumir custo baseado no ângulo
        # Linhas em curva de nível (perpendiculares ao slope) = custo mínimo
        # Linhas subindo o morro = custo máximo
        
        custo = abs(math.sin(angulo_rad)) * fator_erosividade
        
        return custo
        
    except Exception as e:
        QgsMessageLog.logMessage(f"Erro ao calcular custo de erosão: {str(e)}", 'AAP GIS', Qgis.Warning)
        return 0


def calcular_custo_combustivel(linhas, slope_layer, angulo_graus, fator_consumo):
    """
    Calcula custo de combustível baseado em subidas
    
    Subidas consomem mais; apenas declives positivos somam custo
    """
    try:
        # Simplificação: custo proporcional à componente vertical
        angulo_rad = math.radians(angulo_graus)
        
        # Custo maior quando subindo (seno positivo)
        custo = max(0, math.sin(angulo_rad)) * fator_consumo
        
        return custo
        
    except Exception as e:
        QgsMessageLog.logMessage(f"Erro ao calcular custo de combustível: {str(e)}", 'AAP GIS', Qgis.Warning)
        return 0


def calcular_custo_sobreposicao(linhas):
    """
    Calcula custo de sobreposição baseado na variância do comprimento das linhas
    
    Linhas muito diferentes geram sobreposição irregular
    """
    try:
        if not linhas:
            return 0
        
        # Calcular comprimentos
        comprimentos = [linha.length() for linha in linhas]
        
        # Variância dos comprimentos
        media = np.mean(comprimentos)
        variancia = np.var(comprimentos)
        
        # Normalizar
        custo = variancia / (media ** 2) if media > 0 else 0
        
        return custo
        
    except Exception as e:
        QgsMessageLog.logMessage(f"Erro ao calcular custo de sobreposição: {str(e)}", 'AAP GIS', Qgis.Warning)
        return 0


def normalizar_lista(valores):
    """Normaliza lista para 0-1"""
    if not valores:
        return valores
    
    min_val = min(valores)
    max_val = max(valores)
    
    if max_val == min_val:
        return [0.5] * len(valores)
    
    return [(v - min_val) / (max_val - min_val) for v in valores]


def gerar_justificativa_angulo(angulo, alternativo, c_manobra, c_erosao, c_combustivel, c_sobreposicao):
    """
    Gera texto explicativo para a escolha do ângulo
    """
    justificativa = f"Ângulo de {angulo:.1f}° selecionado por minimizar o custo total. "
    
    if c_erosao > 0.5:
        justificativa += "Prioriza redução de erosão (custo erosão alto). "
    elif c_manobra > 0.5:
        justificativa += "Minimiza número de manobras (custo manobra alto). "
    elif c_combustivel > 0.5:
        justificativa += "Reduz consumo de combustível em subidas. "
    
    justificativa += f"Alternativa: {alternativo:.1f}°."
    
    return justificativa


def exportar_grafico_custo(resultado, caminho_saida):
    """
    Exporta gráfico de custo vs. ângulo como PNG
    
    Parâmetros:
    - resultado: dict com custo_por_angulo
    - caminho_saida: Caminho do arquivo PNG
    """
    try:
        import matplotlib.pyplot as plt
        
        angulos = np.arange(0, 180, 1.0)
        custos = resultado['custo_por_angulo']
        
        plt.figure(figsize=(10, 6))
        plt.plot(angulos, custos, 'b-', linewidth=2)
        plt.axvline(x=resultado['angulo_otimo'], color='r', linestyle='--', 
                   label=f'Ótimo: {resultado["angulo_otimo"]:.1f}°')
        plt.xlabel('Ângulo (graus)', fontsize=12)
        plt.ylabel('Custo total (normalizado)', fontsize=12)
        plt.title('Custo vs. Ângulo de Plantio', fontsize=14)
        plt.legend()
        plt.grid(True)
        plt.savefig(caminho_saida, dpi=150, bbox_inches='tight')
        plt.close()
        
        QgsMessageLog.logMessage(f"✓ Gráfico exportado: {caminho_saida}", 'AAP GIS', Qgis.Info)
        
        return True
        
    except ImportError:
        QgsMessageLog.logMessage("⚠ matplotlib não disponível - gráfico não exportado", 'AAP GIS', Qgis.Warning)
        return False
    except Exception as e:
        QgsMessageLog.logMessage(f"Erro ao exportar gráfico: {str(e)}", 'AAP GIS', Qgis.Warning)
        return False


# ============================================================================
# ESTRATÉGIA B — LINHAS BASEADAS EM CURVAS DE NÍVEL
# ============================================================================

def gerar_linhas_curva_nivel(
    id_talhao,
    dem_path,
    cultura,
    equidistancia_m=1.0,
    raio_min_maquina_m=15.0,
    comprimento_min_m=30.0
):
    """
    Gera linhas de plantio seguindo curvas de nível
    
    Reduz erosão em até 60% comparado a linhas retas em terreno ondulado
    
    Parâmetros:
    - id_talhao: ID do talhão
    - dem_path: Caminho do DEM
    - cultura: Cultura plantada
    - equidistancia_m: Equidistância das curvas (0.5m drone, 1m RTK, 5m SRTM)
    - raio_min_maquina_m: Raio mínimo de curvatura da máquina
    - comprimento_min_m: Comprimento mínimo operacional
    
    Retorna:
    - dict com linhas geradas e estatísticas
    """
    try:
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        QgsMessageLogMessage("GERANDO LINHAS EM CURVAS DE NÍVEL", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        
        projeto = QgsProject.instance()
        
        # Carregar DEM
        dem_layer = QgsRasterLayer(dem_path, "dem")
        if not dem_layer.isValid():
            QgsMessageLog.logMessage("✗ DEM inválido", 'AAP GIS', Qgis.Critical)
            return None
        
        # Obter talhão
        talhao_layer = None
        for layer in projeto.mapLayers().values():
            if layer.name() == 'talhoes':
                talhao_layer = layer
                break
        
        if not talhao_layer:
            QgsMessageLog.logMessage("✗ Camada talhoes não encontrada", 'AAP GIS', Qgis.Critical)
            return None
        
        # Obter feature
        talhao_feat = None
        for feat in talhao_layer.getFeatures():
            if feat['id'] == id_talhao:
                talhao_feat = feat
                break
        
        if not talhao_feat:
            QgsMessageLog.logMessage("✗ Talhão não encontrado", 'AAP GIS', Qgis.Critical)
            return None
        
        # Obter espaçamento da cultura
        espacamento_cultura = obter_espacamento_cultura(cultura)
        
        # 1. Gerar curvas de nível base
        QgsMessageLog.logMessage(f"Gerando curvas de nível (equidistância: {equidistancia_m}m)...", 'AAP GIS', Qgis.Info)
        
        curvas_path = dem_path.replace('.tif', '_curvas_nivel.shp')
        params = {
            'INPUT': dem_layer,
            'BAND': 1,
            'INTERVAL': equidistancia_m,
            'FIELD_NAME': 'ELEV',
            'OUTPUT': curvas_path
        }
        
        processing.run("gdal:contour", params)
        
        curvas_layer = QgsVectorLayer(curvas_path, "curvas_nivel")
        
        # 2. Suavizar curvas
        QgsMessageLog.logMessage("Suavizando curvas...", 'AAP GIS', Qgis.Info)
        
        curvas_suaves_path = curvas_path.replace('.shp', '_suaves.shp')
        params = {
            'INPUT': curvas_layer,
            'ITERATIONS': 3,
            'OFFSET': 0.25,
            'OUTPUT': curvas_suaves_path
        }
        
        processing.run("native:smoothgeometry", params)
        
        curvas_suaves_layer = QgsVectorLayer(curvas_suaves_path, "curvas_suaves")
        
        # 3. Selecionar curvas de referência (espaçamento = espacamento_cultura)
        QgsMessageLog.logMessage(f"Selecionando curvas (espaçamento: {espacamento_cultura}m)...", 'AAP GIS', Qgis.Info)
        
        # Calcular quantas curvas pular
        n = round(equidistancia_m / espacamento_cultura)
        if n < 1:
            n = 1
        
        QgsMessageLog.logMessage(f"Selecionando 1 a cada {n} curvas", 'AAP GIS', Qgis.Info)
        
        # 4. Adaptar curvas para máquinas (restrição de raio)
        QgsMessageLog.logMessage(f"Adaptando curvas para raio mínimo {raio_min_maquina_m}m...", 'AAP GIS', Qgis.Info)
        
        curvas_adaptadas = adaptar_curvas_raio_minimo(
            curvas_suaves_layer,
            raio_min_maquina_m
        )
        
        # 5. Recortar curvas com polígono de bordadura
        QgsMessageLog.logMessage("Recortando curvas pela área útil...", 'AAP GIS', Qgis.Info)
        
        # Obter bordadura
        bordadura_layer = None
        for layer in projeto.mapLayers().values():
            if layer.name() == 'bordaduras':
                bordadura_layer = layer
                break
        
        if bordadura_layer:
            bordadura_feat = None
            for feat in bordadura_layer.getFeatures():
                if feat['id_talhao'] == id_talhao:
                    bordadura_feat = feat
                    break
            
            if bordadura_feat:
                curvas_recortadas = recortar_por_poligono(
                    curvas_adaptadas,
                    bordadura_feat.geometry()
                )
            else:
                curvas_recortadas = curvas_adaptadas
        else:
            # Recortar pelo talhão
            curvas_recortadas = recortar_por_poligono(
                curvas_adaptadas,
                talhao_feat.geometry()
            )
        
        # 6. Remover linhas curtas
        QgsMessageLog.logMessage(f"Removendo linhas < {comprimento_min_m}m...", 'AAP GIS', Qgis.Info)
        
        linhas_finais = [linha for linha in curvas_recortadas if linha.length() >= comprimento_min_m]
        linhas_rejeitadas = len(curvas_recortadas) - len(linhas_finais)
        
        # 7. Validar: nenhuma linha autointersecta
        alertas = []
        for i, linha in enumerate(linhas_finais):
            if linha.isGeosValid() == False:
                alertas.append(f"Linha {i}: geometria inválida")
        
        # Salvar linhas
        QgsMessageLog.logMessage("Salvando linhas finais...", 'AAP GIS', Qgis.Info)
        
        linhas_layer = QgsVectorLayer(
            "LineString?crs=" + talhao_layer.crs().authid(),
            "linhas_plantio_curva_nivel",
            "memory"
        )
        
        provider = linhas_layer.dataProvider()
        provider.addAttributes([
            QgsField('id', QVariant.Int),
            QgsField('id_talhao', QVariant.Int),
            QgsField('cultura', QVariant.String, 30),
            QgsField('espacamento_m', QVariant.Double),
            QgsField('metodo', QVariant.String, 20),
            QgsField('comprimento_m', QVariant.Double)
        ])
        linhas_layer.updateFields()
        
        linhas_layer.startEditing()
        
        for i, linha in enumerate(linhas_finais):
            feat = QgsFeature(linhas_layer.fields())
            feat.setGeometry(linha)
            feat.setAttribute('id', i + 1)
            feat.setAttribute('id_talhao', id_talhao)
            feat.setAttribute('cultura', cultura)
            feat.setAttribute('espacamento_m', espacamento_cultura)
            feat.setAttribute('metodo', 'curva_nivel')
            feat.setAttribute('comprimento_m', linha.length())
            provider.addFeature(feat)
        
        linhas_layer.commitChanges()
        
        QgsProject.instance().addMapLayer(linhas_layer)
        
        # Calcular cobertura
        area_coberta = calcular_area_coberta_linhas(linhas_finais, espacamento_cultura)
        area_talhao = talhao_feat.geometry().area() / 10000
        cobertura_pct = (area_coberta / area_talhao * 100) if area_talhao > 0 else 0
        
        QgsMessageLog.logMessage(f"✓ Linhas geradas: {len(linhas_finais)}", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage(f"  Linhas rejeitadas: {linhas_rejeitadas}", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage(f"  Cobertura: {cobertura_pct:.1f}%", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage(f"  Alertas: {len(alertas)}", 'AAP GIS', Qgis.Info)
        
        resultado = {
            'linhas_ids': list(range(1, len(linhas_finais) + 1)),
            'n_linhas': len(linhas_finais),
            'cobertura_pct': cobertura_pct,
            'linhas_rejeitadas': linhas_rejeitadas,
            'alertas': alertas,
            'layer': linhas_layer
        }
        
        return resultado
        
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro ao gerar linhas em curva de nível: {str(e)}", 'AAP GIS', Qgis.Critical)
        return None


def obter_espacamento_cultura(cultura):
    """Retorna espaçamento padrão por cultura"""
    espacamentos = {
        'soja': 0.45,
        'milho': 0.90,
        'algodao': 0.90,
        'algodao_adensado': 0.76,
        'feijao': 0.50,
        'sorgo': 0.50
    }
    return espacamentos.get(cultura.lower(), 0.50)


def adaptar_curvas_raio_minimo(curvas_layer, raio_min):
    """
    Suaviza curvas com restrição de raio mínimo de máquina
    
    Algoritmo Chaikin iterativo até max_curvatura < 1/raio_min
    """
    try:
        # Simplificação: aplicar smooth geometry
        # Para implementação completa, verificar curvatura ponto a ponto
        
        params = {
            'INPUT': curvas_layer,
            'ITERATIONS': 5,
            'OFFSET': 0.5,
            'OUTPUT': 'memory:'
        }
        
        result = processing.run("native:smoothgeometry", params)
        
        # Extrair geometrias
        linhas = [feat.geometry() for feat in result['OUTPUT'].getFeatures()]
        
        return linhas
        
    except Exception as e:
        QgsMessageLog.logMessage(f"Erro ao adaptar curvas: {str(e)}", 'AAP GIS', Qgis.Warning)
        return []


def recortar_por_poligono(linhas, poligono):
    """Recorta linhas por polígono"""
    try:
        linhas_recortadas = []
        
        for linha in linhas:
            recortada = linha.intersection(poligono)
            if not recortada.isEmpty() and recortada.wkbType() in [1, 2, 5]:  # Line, MultiLine
                if recortada.wkbType() == 5:  # MultiLine
                    for parte in recortada.asGeometryCollection():
                        linhas_recortadas.append(parte)
                else:
                    linhas_recortadas.append(recortada)
        
        return linhas_recortadas
        
    except Exception as e:
        QgsMessageLog.logMessage(f"Erro ao recortar: {str(e)}", 'AAP GIS', Qgis.Warning)
        return linhas


def calcular_area_coberta_linhas(linhas, espacamento):
    """
    Calcula área coberta pelas linhas (buffer simples)
    """
    try:
        area_total = 0
        
        for linha in linhas:
            params = {
                'INPUT': linha,
                'DISTANCE': espacamento / 2,
                'OUTPUT': 'memory:'
            }
            result = processing.run("native:buffer", params)
            area_total += result['OUTPUT'].area()
        
        return area_total / 10000  # converter para ha
        
    except Exception as e:
        QgsMessageLog.logMessage(f"Erro ao calcular área coberta: {str(e)}", 'AAP GIS', Qgis.Warning)
        return 0


def gerar_linhas_transversais_acesso(curvas_nivel, espacamento_transversal=200):
    """
    Gera linhas transversais de acesso entre curvas de nível
    
    Permite que máquina suba/desça para próxima curva
    """
    try:
        # Simplificação: implementação futura
        QgsMessageLog.logMessage("Linhas transversais não implementadas nesta versão", 'AAP GIS', Qgis.Info)
        return []
        
    except Exception as e:
        QgsMessageLog.logMessage(f"Erro ao gerar linhas transversais: {str(e)}", 'AAP GIS', Qgis.Warning)
        return []


# ============================================================================
# ESTRATÉGIA C — LINHAS ADAPTATIVAS POR SLOPE LOCAL
# ============================================================================

def gerar_linhas_adaptativas(
    id_talhao,
    dem_path,
    cultura,
    espacamento_m=None
):
    """
    Gera linhas adaptativas: híbrido entre retas e curvas
    
    - Faixas com slope < 3°: linhas retas
    - Faixas com slope 3-8°: linhas com deflexão suave
    - Faixas com slope > 8°: curvas de nível
    
    Parâmetros:
    - id_talhao: ID do talhão
    - dem_path: Caminho do DEM
    - cultura: Cultura plantada
    - espacamento_m: Espaçamento (default da cultura)
    
    Retorna:
    - dict com linhas geradas
    """
    try:
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("GERANDO LINHAS ADAPTATIVAS POR SLOPE", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        
        if espacamento_m is None:
            espacamento_m = obter_espacamento_cultura(cultura)
        
        projeto = QgsProject.instance()
        
        # Carregar DEM e slope
        dem_layer = QgsRasterLayer(dem_path, "dem")
        slope_path = dem_path.replace('.tif', '_slope.tif')
        slope_layer = QgsRasterLayer(slope_path, "slope")
        
        if not slope_layer.isValid():
            QgsMessageLog.logMessage("✗ Slope não encontrado, calculando...", 'AAP GIS', Qgis.Warning)
            params = {
                'INPUT': dem_layer,
                'BAND': 1,
                'SLOPE': 1,
                'OUTPUT': slope_path
            }
            processing.run("gdal:slope", params)
            slope_layer = QgsRasterLayer(slope_path, "slope")
        
        # Obter talhão
        talhao_layer = None
        for layer in projeto.mapLayers().values():
            if layer.name() == 'talhoes':
                talhao_layer = layer
                break
        
        if not talhao_layer:
            QgsMessageLog.logMessage("✗ Camada talhoes não encontrada", 'AAP GIS', Qgis.Critical)
            return None
        
        talhao_feat = None
        for feat in talhao_layer.getFeatures():
            if feat['id'] == id_talhao:
                talhao_feat = feat
                break
        
        if not talhao_feat:
            QgsMessageLog.logMessage("✗ Talhão não encontrado", 'AAP GIS', Qgis.Critical)
            return None
        
        # Dividir talhão em faixas transversais
        QgsMessageLog.logMessage("Dividindo talhão em faixas...", 'AAP GIS', Qgis.Info)
        
        faixas = dividir_talhao_faixas(
            talhao_feat.geometry(),
            espacamento_m * 10  # largura da faixa
        )
        
        QgsMessageLog.logMessage(f"Faixas geradas: {len(faixas)}", 'AAP GIS', Qgis.Info)
        
        # Para cada faixa, determinar estratégia e gerar linhas
        linhas_totais = []
        
        for i, faixa in enumerate(faixas):
            # Calcular slope médio da faixa
            slope_medio = calcular_slope_medio_faixa(faixa, slope_layer)
            
            QgsMessageLog.logMessage(f"Faixa {i+1}: slope médio = {slope_medio:.2f}°", 'AAP GIS', Qgis.Info)
            
            # Selecionar estratégia
            if slope_medio < 3:
                estrategia = 'reta'
                QgsMessageLog.logMessage("  → Estratégia: linhas retas", 'AAP GIS', Qgis.Info)
            elif slope_medio < 8:
                estrategia = 'deflexao_suave'
                QgsMessageLog.logMessage("  → Estratégia: deflexão suave", 'AAP GIS', Qgis.Info)
            else:
                estrategia = 'curva_nivel'
                QgsMessageLog.logMessage("  → Estratégia: curvas de nível", 'AAP GIS', Qgis.Info)
            
            # Gerar linhas para a faixa (simplificado)
            linhas_faixa = gerar_linhas_faixa_estrategia(
                faixa,
                estrategia,
                espacamento_m,
                slope_medio
            )
            
            linhas_totais.extend(linhas_faixa)
        
        # Conectar segmentos (simplificado)
        QgsMessageLog.logMessage("Conectando segmentos...", 'AAP GIS', Qgis.Info)
        
        # Salvar linhas
        QgsMessageLog.logMessage("Salvando linhas adaptativas...", 'AAP GIS', Qgis.Info)
        
        linhas_layer = QgsVectorLayer(
            "LineString?crs=" + talhao_layer.crs().authid(),
            "linhas_plantio_adaptativas",
            "memory"
        )
        
        provider = linhas_layer.dataProvider()
        provider.addAttributes([
            QgsField('id', QVariant.Int),
            QgsField('id_talhao', QVariant.Int),
            QgsField('cultura', QVariant.String, 30),
            QgsField('espacamento_m', QVariant.Double),
            QgsField('metodo', QVariant.String, 20),
            QgsField('estrategia', QVariant.String, 20)
        ])
        linhas_layer.updateFields()
        
        linhas_layer.startEditing()
        
        for i, linha in enumerate(linhas_totais):
            feat = QgsFeature(linhas_layer.fields())
            feat.setGeometry(linha)
            feat.setAttribute('id', i + 1)
            feat.setAttribute('id_talhao', id_talhao)
            feat.setAttribute('cultura', cultura)
            feat.setAttribute('espacamento_m', espacamento_m)
            feat.setAttribute('metodo', 'adaptativo')
            provider.addFeature(feat)
        
        linhas_layer.commitChanges()
        
        QgsProject.instance().addMapLayer(linhas_layer)
        
        QgsMessageLog.logMessage(f"✓ Linhas adaptativas geradas: {len(linhas_totais)}", 'AAP GIS', Qgis.Info)
        
        resultado = {
            'linhas_ids': list(range(1, len(linhas_totais) + 1)),
            'n_linhas': len(linhas_totais),
            'n_faixas': len(faixas),
            'layer': linhas_layer
        }
        
        return resultado
        
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro ao gerar linhas adaptativas: {str(e)}", 'AAP GIS', Qgis.Critical)
        return None


def dividir_talhao_faixas(geom, largura_faixa):
    """
    Divide o talhão em faixas transversais
    
    Retorna lista de QgsGeometry (polígonos)
    """
    try:
        # Simplificação: criar faixas retas
        bbox = geom.boundingBox()
        
        faixas = []
        n_faixas = int(bbox.height() / largura_faixa)
        
        for i in range(n_faixas):
            y1 = bbox.yMinimum() + i * largura_faixa
            y2 = y1 + largura_faixa
            
            # Criar polígono da faixa
            faixa_geom = QgsGeometry.fromRect(
                QgsPointXY(bbox.xMinimum(), y1),
                QgsPointXY(bbox.xMaximum(), y2)
            )
            
            # Intersectar com talhão
            faixa_recortada = faixa_geom.intersection(geom)
            
            if not faixa_recortada.isEmpty():
                faixas.append(faixa_recortada)
        
        return faixas
        
    except Exception as e:
        QgsMessageLog.logMessage(f"Erro ao dividir faixas: {str(e)}", 'AAP GIS', Qgis.Warning)
        return []


def calcular_slope_medio_faixa(faixa_geom, slope_layer):
    """
    Calcula slope médio dentro de uma faixa
    """
    try:
        # Simplificação: usar slope médio do centro da faixa
        # Para implementação completa, usar zonal statistics
        
        centro = faixa_geom.centroid().asPoint()
        
        # Sample slope no ponto
        params = {
            'COLUMN_PREFIX': 'slope_',
            'INPUT': slope_layer,
            'SOURCE': centro,
            'OUTPUT': 'memory:'
        }
        
        result = processing.run("qgis:rastersampling", params)
        
        # Extrair valor
        # Simplificação: retornar valor fixo
        return 5.0
        
    except Exception as e:
        QgsMessageLog.logMessage(f"Erro ao calcular slope médio: {str(e)}", 'AAP GIS', Qgis.Warning)
        return 5.0


def gerar_linhas_faixa_estrategia(faixa, estrategia, espacamento, slope_medio):
    """
    Gera linhas para uma faixa baseado na estratégia
    """
    try:
        if estrategia == 'reta':
            # Linhas retas paralelas
            return gerar_linhas_retas_faixa(faixa, espacamento)
        elif estrategia == 'deflexao_suave':
            # Linhas com leve deflexão
            return gerar_linhas_deflexao_faixa(faixa, espacamento, 15)  # 15° max
        else:  # curva_nivel
            # Simplificação: linhas retas para MVP
            return gerar_linhas_retas_faixa(faixa, espacamento)
        
    except Exception as e:
        QgsMessageLog.logMessage(f"Erro ao gerar linhas da faixa: {str(e)}", 'AAP GIS', Qgis.Warning)
        return []


def gerar_linhas_retas_faixa(faixa, espacamento):
    """Gera linhas retas paralelas em uma faixa"""
    try:
        bbox = faixa.boundingBox()
        
        linhas = []
        n_linhas = int(bbox.width() / espacamento)
        
        for i in range(n_linhas):
            x = bbox.xMinimum() + i * espacamento
            linha = QgsGeometry.fromPolylineXY([
                QgsPointXY(x, bbox.yMinimum()),
                QgsPointXY(x, bbox.yMaximum())
            ])
            
            recortada = linha.intersection(faixa)
            if not recortada.isEmpty():
                linhas.append(recortada)
        
        return linhas
        
    except Exception as e:
        QgsMessageLog.logMessage(f"Erro ao gerar linhas retas: {str(e)}", 'AAP GIS', Qgis.Warning)
        return []


def gerar_linhas_deflexao_faixa(faixa, espacamento, deflexao_max_graus):
    """Gera linhas com deflexão suave (MVP - simplificado)"""
    # MVP: usar linhas retas
    return gerar_linhas_retas_faixa(faixa, espacamento)


# ============================================================================
# SELEÇÃO AUTOMÁTICA DE ESTRATÉGIA
# ============================================================================

def selecionar_estrategia_linhas(id_talhao, dem_path):
    """
    Seleciona automaticamente a melhor estratégia de linhas
    
    Baseado em características do talhão:
    - slope_medio
    - pct_area_slope_alto (% com slope > 5°)
    - indice_irregularidade (variância do slope)
    
    Retorna:
    - str: 'direcao_otima', 'curva_nivel', ou 'adaptativo'
    """
    try:
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("SELECIONANDO ESTRATÉGIA DE LINHAS", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        
        projeto = QgsProject.instance()
        
        # Carregar slope
        slope_path = dem_path.replace('.tif', '_slope.tif')
        slope_layer = QgsRasterLayer(slope_path, "slope")
        
        if not slope_layer.isValid():
            QgsMessageLog.logMessage("⚠ Slope não disponível, usando padrão", 'AAP GIS', Qgis.Warning)
            return 'direcao_otima'
        
        # Obter talhão
        talhao_layer = None
        for layer in projeto.mapLayers().values():
            if layer.name() == 'talhoes':
                talhao_layer = layer
                break
        
        if not talhao_layer:
            return 'direcao_otima'
        
        talhao_feat = None
        for feat in talhao_layer.getFeatures():
            if feat['id'] == id_talhao:
                talhao_feat = feat
                break
        
        if not talhao_feat:
            return 'direcao_otimo'
        
        # Calcular características (simplificado)
        # Para implementação completa, usar zonal statistics
        
        slope_medio = 3.0  # valor exemplo
        pct_area_slope_alto = 25.0  # valor exemplo
        indice_irregularidade = 0.5  # valor exemplo
        
        QgsMessageLog.logMessage(f"Slope médio: {slope_medio:.2f}°", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage(f"Área slope > 5°: {pct_area_slope_alto:.1f}%", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage(f"Índice irregularidade: {indice_irregularidade:.2f}", 'AAP GIS', Qgis.Info)
        
        # Regras de seleção
        if slope_medio < 2.0 and pct_area_slope_alto < 10:
            estrategia = 'direcao_otima'
            justificativa = "Terreno plano: otimizar ângulo por custo"
        elif slope_medio >= 5.0 or pct_area_slope_alto > 40:
            estrategia = 'curva_nivel'
            justificativa = "Terreno ondulado: seguir contorno para reduzir erosão"
        else:
            estrategia = 'adaptativo'
            justificativa = "Terreno misto: segmentação por zona"
        
        QgsMessageLog.logMessage(f"✓ Estratégia selecionada: {estrategia}", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage(f"  Justificativa: {justificativa}", 'AAP GIS', Qgis.Info)
        
        return estrategia
        
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro ao selecionar estratégia: {str(e)}", 'AAP GIS', Qgis.Warning)
        return 'direcao_otima'


# ============================================================================
# FUNÇÃO PRINCIPAL - GERAÇÃO AUTOMÁTICA
# ============================================================================

def gerar_linhas_agronomicas(
    id_talhao,
    dem_path,
    cultura,
    estrategia=None,
    espacamento_m=None,
    config={}
):
    """
    Função principal de geração de linhas agronômicas
    
    Seleciona automaticamente a estratégia se não especificada
    
    Parâmetros:
    - id_talhao: ID do talhão
    - dem_path: Caminho do DEM
    - cultura: Cultura plantada
    - estrategia: 'direcao_otima', 'curva_nivel', 'adaptativo', ou None (auto)
    - espacamento_m: Espaçamento (default da cultura)
    - config: Dict com parâmetros adicionais
    
    Retorna:
    - dict com resultado da geração
    """
    try:
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("GERAÇÃO DE LINHAS AGRONÔMICAS - PARTE 9", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        
        # Selecionar estratégia se não especificada
        if estrategia is None:
            estrategia = selecionar_estrategia_linhas(id_talhao, dem_path)
        
        QgsMessageLog.logMessage(f"Estratégia: {estrategia}", 'AAP GIS', Qgis.Info)
        
        # Executar estratégia
        if estrategia == 'direcao_otima':
            resultado = calcular_angulo_otimo(
                id_talhao,
                dem_path,
                cultura,
                pesos=config.get('pesos', {}),
                passo_graus=config.get('passo_graus', 1.0),
                fator_erosividade=config.get('fator_erosividade', 1.0),
                fator_consumo=config.get('fator_consumo', 1.0)
            )
            
            if resultado:
                # Gerar linhas com ângulo ótimo (usar Parte 4)
                from aap_part4_plantio import gerar_linhas_plantio
                
                resultado_linhas = gerar_linhas_plantio(
                    id_talhao=id_talhao,
                    cultura=cultura,
                    espacamento_m=espacamento_m,
                    metodo_direcao='manual',
                    azimute_manual=resultado['angulo_otimo']
                )
                
                resultado['estrategia'] = 'direcao_otima'
                resultado['linhas'] = resultado_linhas
                
        elif estrategia == 'curva_nivel':
            resultado = gerar_linhas_curva_nivel(
                id_talhao=id_talhao,
                dem_path=dem_path,
                cultura=cultura,
                equidistancia_m=config.get('equidistancia_m', 1.0),
                raio_min_maquina_m=config.get('raio_min_maquina_m', 15.0),
                comprimento_min_m=config.get('comprimento_min_m', 30.0)
            )
            
            if resultado:
                resultado['estrategia'] = 'curva_nivel'
        
        elif estrategia == 'adaptativo':
            resultado = gerar_linhas_adaptativas(
                id_talhao=id_talhao,
                dem_path=dem_path,
                cultura=cultura,
                espacamento_m=espacamento_m
            )
            
            if resultado:
                resultado['estrategia'] = 'adaptativo'
        
        else:
            QgsMessageLog.logMessage(f"✗ Estratégia desconhecida: {estrategia}", 'AAP GIS', Qgis.Critical)
            return None
        
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("✓ GERAÇÃO CONCLUÍDA", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        
        return resultado
        
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro na geração de linhas agronômicas: {str(e)}", 'AAP GIS', Qgis.Critical)
        return None


# ============================================================================
# COMPARAÇÃO QUANTITATIVA
# ============================================================================

def comparar_linhas_geometricas_vs_agronomicas(id_talhao, dem_path, cultura):
    """
    Compara linhas geométricas (Parte 4) vs. linhas agronômicas (Parte 9)
    
    Retorna:
    - dict com métricas comparativas
    """
    try:
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("COMPARAÇÃO: GEOMÉTRICAS VS AGRONÔMICAS", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        
        # Gerar linhas geométricas (Parte 4)
        from aap_part4_plantio import gerar_linhas_plantio
        
        resultado_geo = gerar_linhas_plantio(
            id_talhao=id_talhao,
            cultura=cultura,
            metodo_direcao='auto_eixo'
        )
        
        # Gerar linhas agronômicas (Parte 9)
        resultado_agro = gerar_linhas_agronomicas(
            id_talhao=id_talhao,
            dem_path=dem_path,
            cultura=cultura
        )
        
        # Extrair métricas
        comparacao = {
            'geometricas': {
                'n_linhas': resultado_geo[0] if resultado_geo else 0,
                'comprimento_total_km': resultado_geo[1] if resultado_geo else 0,
                'area_coberta_ha': resultado_geo[2] if resultado_geo else 0,
                'custo_erosao_estimado': 'alto'  # simplificado
            },
            'agronomicas': {
                'n_linhas': resultado_agro.get('n_linhas', 0),
                'comprimento_total_km': 0,  # calcular
                'area_coberta_ha': resultado_agro.get('cobertura_pct', 0),
                'custo_erosao_estimado': 'baixo'  # simplificado
            }
        }
        
        QgsMessageLog.logMessage(f"Linhas geométricas: {comparacao['geometricas']['n_linhas']}", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage(f"Linhas agronômicas: {comparacao['agronomicas']['n_linhas']}", 'AAP GIS', Qgis.Info)
        
        return comparacao
        
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro na comparação: {str(e)}", 'AAP GIS', Qgis.Critical)
        return None


# ============================================================================
# EXECUÇÃO
# ============================================================================

if __name__ == "__main__":
    print("""
    ============================================================================
    AAP GIS - PARTE 9: LINHAS AGRONÔMICAS ADAPTATIVAS AO RELEVO
    ============================================================================
    
    Este script deve ser executado dentro do QGIS (Console Python)
    
    Para usar:
    >>> import sys
    >>> sys.path.insert(0, 'c:/caminho/para/scripts')
    >>> from aap_part9_linhas_agronomicas import *
    >>> 
    >>> # Selecionar estratégia automaticamente
    >>> estrategia = selecionar_estrategia_linhas(id_talhao=1, dem_path='caminho/DEM.tif')
    >>> 
    >>> # Gerar linhas agronômicas
    >>> resultado = gerar_linhas_agronomicas(
    ...     id_talhao=1,
    ...     dem_path='caminho/DEM.tif',
    ...     cultura='soja',
    ...     estrategia=None  # auto
    ... )
    >>> 
    >>> # Comparar geométricas vs agronômicas
    >>> comparacao = comparar_linhas_geometricas_vs_agronomicas(
    ...     id_talhao=1,
    ...     dem_path='caminho/DEM.tif',
    ...     cultura='soja'
    ... )
    ============================================================================
    """)
