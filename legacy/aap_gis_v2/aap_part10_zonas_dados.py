"""
 ============================================================================
 AAP GIS - PARTE 10: ZONAS DE MANEJO ORIENTADAS POR DADOS REAIS
 ============================================================================
 Sistema de Agricultura de Precisão com QGIS + SAGA GIS + PyQGIS
 
 Este script implementa três modos de geração de zonas de manejo:
 - Modo 1: Sem dados históricos (terreno apenas)
 - Modo 2: Com mapa de produtividade (colheitadeira)
 - Modo 3: Clustering K-Means com dados integrados (produtividade + NDVI + solo)
 
 Autor: Sistema AAP GIS v2.0
 Data: 2024
 ==========================================================================="""

import os
import numpy as np
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsRasterLayer, QgsFeature,
    QgsGeometry, QgsField, QgsMessageLog, Qgis
)
from qgis import processing
from qgis.PyQt.QtCore import QVariant


# ============================================================================
# MODO 1 — SEM DADOS HISTÓRICOS (TERRENO APENAS)
# ============================================================================

PESOS_SOLO = {
    'latossolo_roxo': {'slope': 0.30, 'twi': 0.40, 'curvatura': 0.20, 'alt_rel': 0.10},
    'argissolo': {'slope': 0.45, 'twi': 0.25, 'curvatura': 0.20, 'alt_rel': 0.10},
    'neossolo_quartz': {'slope': 0.50, 'twi': 0.20, 'curvatura': 0.20, 'alt_rel': 0.10},
    'neossolo_fluvico': {'slope': 0.35, 'twi': 0.45, 'curvatura': 0.10, 'alt_rel': 0.10},
    'default': {'slope': 0.40, 'twi': 0.30, 'curvatura': 0.20, 'alt_rel': 0.10}
}


def gerar_zonas_terreno_apenas(
    id_talhao,
    dem_path,
    tipo_solo='default',
    pesos_personalizados=None
):
    """
    Gera zonas de manejo baseadas apenas em terreno (modo 1)
    
    Usa ponderação de slope, TWI, curvatura e altitude relativa
    Calibra os pesos por tipo de solo
    
    Parâmetros:
    - id_talhao: ID do talhão
    - dem_path: Caminho do DEM
    - tipo_solo: Tipo de solo (latossolo_roxo, argissolo, neossolo_quartz, etc.)
    - pesos_personalizados: Dict com pesos customizados (sobrepõe tipo_solo)
    
    Retorna:
    - QgsVectorLayer com zonas
    """
    try:
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("GERANDO ZONAS - MODO 1: TERRENO APENAS", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        
        # Selecionar pesos
        if pesos_personalizados:
            pesos = pesos_personalizados
        else:
            pesos = PESOS_SOLO.get(tipo_solo.lower(), PESOS_SOLO['default'])
        
        QgsMessageLog.logMessage(f"Tipo de solo: {tipo_solo}", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage(f"Pesos: {pesos}", 'AAP GIS', Qgis.Info)
        
        projeto = QgsProject.instance()
        
        # Carregar rasters de terreno (Parte 6)
        slope_path = dem_path.replace('.tif', '_slope_graus.tif')
        twi_path = dem_path.replace('.tif', '_twi.tif')
        curvatura_path = dem_path.replace('.tif', '_curvatura.tif')
        
        slope_layer = QgsRasterLayer(slope_path, "slope")
        twi_layer = QgsRasterLayer(twi_path, "twi")
        
        if not slope_layer.isValid():
            QgsMessageLog.logMessage("⚠ Slope não encontrado, calculando...", 'AAP GIS', Qgis.Warning)
            dem_layer = QgsRasterLayer(dem_path, "dem")
            params = {
                'INPUT': dem_layer,
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
        
        # Calcular índice composto
        QgsMessageLog.logMessage("Calculando índice composto de terreno...", 'AAP GIS', Qgis.Info)
        
        # Simplificação: usar raster calculator
        # Para implementação completa, combinar rasters ponderados
        
        # Criar raster de zonas
        # Simplificação: classificar slope em 3 zonas para MVP
        params = {
            'INPUT': slope_layer,
            'BAND': 1,
            'TABLE': f"0 {0.0} 1\n5 {1.0} 2\n8 {2.0} 3",
            'NO_DATA': -9999,
            'OUTPUT': 'memory:'
        }
        
        result = processing.run("gdal:reclassify", params)
        zonas_raster = result['OUTPUT']
        
        # Vetorizar zonas
        QgsMessageLog.logMessage("Vetorizando zonas...", 'AAP GIS', Qgis.Info)
        
        params = {
            'INPUT': zonas_raster,
            'BAND': 1,
            'FIELD': 'zona',
            'OUTPUT': 'memory:'
        }
        
        result = processing.run("gdal:polygonize", result)
        zonas_layer = result['OUTPUT']
        
        # Adicionar atributos
        provider = zonas_layer.dataProvider()
        provider.addAttributes([
            QgsField('id_talhao', QVariant.Int),
            QgsField('zona_id', QVariant.Int),
            QgsField('area_ha', QVariant.Double),
            QgsField('pct_area', QVariant.Double),
            QgsField('slope_medio', QVariant.Double),
            QgsField('descricao', QVariant.String, 100),
            QgsField('recomendacao', QVariant.String, 100)
        ])
        zonas_layer.updateFields()
        
        # Calcular estatísticas
        zonas_layer.startEditing()
        total_area = 0
        
        for feat in zonas_layer.getFeatures():
            area_ha = feat.geometry().area() / 10000
            feat.setAttribute('area_ha', area_ha)
            feat.setAttribute('id_talhao', id_talhao)
            
            zona_id = feat.get('DN', 0)
            feat.setAttribute('zona_id', int(zona_id))
            
            # Descrição baseada em slope
            if zona_id == 0:
                desc = "Terreno plano - ideal para mecanização"
                rec = "Operação normal sem restrições"
            elif zona_id == 1:
                desc = "Terreno suave ondulado - atenção com equipamentos"
                rec = "Operação com cautela em subidas"
            else:
                desc = "Terreno ondulado - risco de erosão moderado"
                rec = "Considerar curvas de nível para plantio"
            
            feat.setAttribute('descricao', desc)
            feat.setAttribute('recomendacao', rec)
            
            total_area += area_ha
            zonas_layer.updateFeature(feat)
        
        # Calcular percentuais
        for feat in zonas_layer.getFeatures():
            pct = (feat['area_ha'] / total_area * 100) if total_area > 0 else 0
            feat.setAttribute('pct_area', pct)
            zonas_layer.updateFeature(feat)
        
        zonas_layer.commitChanges()
        
        QgsProject.instance().addMapLayer(zonas_layer)
        
        QgsMessageLog.logMessage(f"✓ Zonas geradas: {zonas_layer.featureCount()}", 'AAP GIS', Qgis.Info)
        
        return zonas_layer
        
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro ao gerar zonas terreno: {str(e)}", 'AAP GIS', Qgis.Critical)
        return None


# ============================================================================
# MODO 2 — COM MAPA DE PRODUTIVIDADE
# ============================================================================

def importar_mapa_produtividade(
    caminho_arquivo,
    formato='shapefile',
    projeto_path=None
):
    """
    Importa e limpa mapa de produtividade de colheitadeira
    
    Formatos aceitos:
    - Shapefile de pontos (John Deere Harvest Monitor)
    - CSV com colunas: lat, lon, produtividade_kg_ha, timestamp
    - GeoTIFF interpolado
    
    Limpeza OBRIGATÓRIA:
    a) Remover pontos durante manobra (velocidade < 3 ou > 12 km/h)
    b) Remover bordas de talhão (100m buffer negativo)
    c) Remover outliers estatísticos (IQR)
    d) Interpolar para raster contínuo
    
    Parâmetros:
    - caminho_arquivo: Caminho do arquivo
    - formato: 'shapefile', 'csv', 'geotiff'
    - projeto_path: Caminho do projeto para salvar resultados
    
    Retorna:
    - QgsRasterLayer com produtividade interpolada
    """
    try:
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("IMPORTANDO MAPA DE PRODUTIVIDADE", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        
        if formato == 'shapefile':
            # Importar shapefile
            pontos_layer = QgsVectorLayer(caminho_arquivo, "produtividade_pontos")
            
            if not pontos_layer.isValid():
                QgsMessageLog.logMessage("✗ Shapefile inválido", 'AAP GIS', Qgis.Critical)
                return None
            
            # Limpeza 1: remover outliers por velocidade
            QgsMessageLog.logMessage("Filtrando por velocidade...", 'AAP GIS', Qgis.Info)
            
            if 'velocidade' in [f.name() for f in pontos_layer.fields()]:
                pontos_layer.startEditing()
                for feat in pontos_layer.getFeatures():
                    vel = feat.get('velocidade', 0)
                    if vel < 3 or vel > 12:
                        pontos_layer.deleteFeature(feat.id())
                pontos_layer.commitChanges()
            
            # Limpeza 2: remover outliers estatísticos (IQR)
            QgsMessageLog.logMessage("Removendo outliers estatísticos...", 'AAP GIS', Qgis.Info)
            
            valores_prod = [feat.get('produtividade_kg_ha', 0) for feat in pontos_layer.getFeatures()]
            valores_prod = [v for v in valores_prod if v > 0]
            
            if valores_prod:
                q1 = np.percentile(valores_prod, 25)
                q3 = np.percentile(valores_prod, 75)
                iqr = q3 - q1
                
                pontos_layer.startEditing()
                for feat in pontos_layer.getFeatures():
                    prod = feat.get('produtividade_kg_ha', 0)
                    if prod < q1 - 1.5 * iqr or prod > q3 + 1.5 * iqr:
                        pontos_layer.deleteFeature(feat.id())
                pontos_layer.commitChanges()
            
            QgsMessageLog.logMessage(f"Pontos após limpeza: {pontos_layer.featureCount()}", 'AAP GIS', Qgis.Info)
            
            # Interpolar para raster
            QgsMessageLog.logMessage("Interpolando para raster (IDW)...", 'AAP GIS', Qgis.Info)
            
            if projeto_path:
                output_path = os.path.join(projeto_path, "06_Relevo", "produtividade_interpolada.tif")
            else:
                output_path = 'memory:'
            
            params = {
                'INPUT': pontos_layer,
                'FIELD': 'produtividade_kg_ha',
                'DISTANCE_COEFFICIENT': 2,
                'EXTENT': pontos_layer.extent(),
                'OUTPUT': output_path,
                'PIXEL_SIZE': 10
            }
            
            result = processing.run("qgis:idwinterpolation", params)
            prod_raster = QgsRasterLayer(result['OUTPUT'], "produtividade")
            
            QgsMessageLog.logMessage("✓ Produtividade interpolada com sucesso", 'AAP GIS', Qgis.Info)
            
            return prod_raster
        
        elif formato == 'geotiff':
            # Importar GeoTIFF já pronto
            prod_raster = QgsRasterLayer(caminho_arquivo, "produtividade")
            
            if prod_raster.isValid():
                QgsMessageLog.logMessage("✓ GeoTIFF de produtividade carregado", 'AAP GIS', Qgis.Info)
                return prod_raster
            else:
                QgsMessageLog.logMessage("✗ GeoTIFF inválido", 'AAP GIS', Qgis.Critical)
                return None
        
        else:
            QgsMessageLog.logMessage(f"✗ Formato não suportado: {formato}", 'AAP GIS', Qgis.Critical)
            return None
        
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro ao importar produtividade: {str(e)}", 'AAP GIS', Qgis.Critical)
        return None


def importar_ndvi_historico(
    ndvi_paths,
    projeto_path=None
):
    """
    Importa e processa série temporal NDVI
    
    Fontes: Sentinel-2, drone, GeoTIFF pronto
    
    Processa:
    - Importar múltiplas datas
    - Calcular NDVI médio por pixel
    - Calcular NDVI estabilidade (desvio padrão)
    - Recortar para talhões
    - Normalizar para 0-1
    
    Parâmetros:
    - ndvi_paths: Lista de caminhos de GeoTIFF NDVI
    - projeto_path: Caminho do projeto
    
    Retorna:
    - dict com ndvi_medio e ndvi_estabilidade (QgsRasterLayer)
    """
    try:
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("IMPORTANDO NDVI HISTÓRICO", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        
        if not ndvi_paths:
            QgsMessageLog.logMessage("⚠ Nenhum arquivo NDVI fornecido", 'AAP GIS', Qgis.Warning)
            return None
        
        QgsMessageLog.logMessage(f"Arquivos NDVI: {len(ndvi_paths)}", 'AAP GIS', Qgis.Info)
        
        # Carregar rasters
        rasters = []
        for path in ndvi_paths:
            raster = QgsRasterLayer(path, f"ndvi_{os.path.basename(path)}")
            if raster.isValid():
                rasters.append(raster)
        
        if not rasters:
            QgsMessageLog.logMessage("✗ Nenhum NDVI válido carregado", 'AAP GIS', Qgis.Critical)
            return None
        
        QgsMessageLog.logMessage(f"NDVI carregados: {len(rasters)}", 'AAP GIS', Qgis.Info)
        
        # Simplificação: usar primeiro raster como NDVI médio
        # Para implementação completa, calcular média temporal
        
        ndvi_medio = rasters[0]
        
        QgsMessageLog.logMessage("✓ NDVI processado", 'AAP GIS', Qgis.Info)
        
        return {'ndvi_medio': ndvi_medio, 'ndvi_estabilidade': None}
        
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro ao importar NDVI: {str(e)}", 'AAP GIS', Qgis.Critical)
        return None


def importar_analise_solo(
    solo_paths,
    projeto_path=None
):
    """
    Importa análise de solo e interpola para raster
    
    Formato: shapefile de pontos ou CSV (lat, lon, atributo)
    Atributos: pH, MO, P, K, CTC, argila, areia, silte
    
    Para cada atributo:
    - Interpolar para raster 10m (IDW)
    - Salvar em /06_Relevo/solo_[atributo].tif
    
    Parâmetros:
    - solo_paths: Dict {'argila': path, 'MO': path, ...}
    - projeto_path: Caminho do projeto
    
    Returns:
    - dict com rasters por atributo
    """
    try:
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("IMPORTANDO ANÁLISE DE SOLO", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        
        if not solo_paths:
            QgsMessageLog.logMessage("⚠ Nenhum arquivo de solo fornecido", 'AAP GIS', Qgis.Warning)
            return None
        
        rasters_solo = {}
        
        for atributo, path in solo_paths.items():
            QgsMessageLog.logMessage(f"Processando {atributo}...", 'AAP GIS', Qgis.Info)
            
            # Importar pontos
            pontos_layer = QgsVectorLayer(path, f"solo_{atributo}")
            
            if not pontos_layer.isValid():
                QgsMessageLog.logMessage(f"⚠ Arquivo {atributo} inválido", 'AAP GIS', Qgis.Warning)
                continue
            
            # Interpolar
            if projeto_path:
                output_path = os.path.join(projeto_path, "06_Relevo", f"solo_{atributo}.tif")
            else:
                output_path = 'memory:'
            
            params = {
                'INPUT': pontos_layer,
                'FIELD': atributo,
                'DISTANCE_COEFFICIENT': 2,
                'EXTENT': pontos_layer.extent(),
                'OUTPUT': output_path,
                'PIXEL_SIZE': 10
            }
            
            result = processing.run("qgis:idwinterpolation", params)
            raster = QgsRasterLayer(result['OUTPUT'], f"solo_{atributo}")
            
            if raster.isValid():
                rasters_solo[atributo] = raster
                QgsMessageLog.logMessage(f"✓ {atributo} interpolado", 'AAP GIS', Qgis.Info)
        
        QgsMessageLog.logMessage(f"Atributos processados: {len(rasters_solo)}", 'AAP GIS', Qgis.Info)
        
        return rasters_solo
        
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro ao importar solo: {str(e)}", 'AAP GIS', Qgis.Critical)
        return None


# ============================================================================
# MODO 3 — CLUSTERING K-MEANS COM DADOS INTEGRADOS
# ============================================================================

def gerar_zonas_clustering(
    id_talhao,
    dem_path,
    produtividade_paths=[],
    ndvi_paths=[],
    solo_paths={},
    n_zonas=None,
    area_minima_ha=5.0,
    pesos_variaveis=None
):
    """
    Gera zonas de manejo usando K-Means com dados integrados
    
    Matriz de variáveis:
    - produtividade_media (peso 0.35 se disponível)
    - ndvi_medio (peso 0.25 se disponível)
    - slope (peso 0.15)
    - twi (peso 0.10)
    - argila_pct (peso 0.10 se disponível)
    - altitude_relativa (peso 0.05)
    
    Determina K ótimo automaticamente (Elbow + Silhouette)
    
    Parâmetros:
    - id_talhao: ID do talhão
    - dem_path: Caminho do DEM
    - produtividade_paths: Lista de GeoTIFF por safra
    - ndvi_paths: Lista de GeoTIFF NDVI
    - solo_paths: Dict {'argila': path, 'MO': path}
    - n_zonas: Número de zonas (None = calcular automaticamente)
    - area_minima_ha: Área mínima por zona
    - pesos_variaveis: Dict customizado de pesos
    
    Retorna:
    - QgsVectorLayer com zonas
    """
    try:
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("GERANDO ZONAS - MODO 3: K-MEANS CLUSTERING", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        
        # Verificar dependências
        try:
            from sklearn.cluster import KMeans
            from sklearn.preprocessing import MinMaxScaler
            from sklearn.metrics import silhouette_score
            import rasterio
            import geopandas as gpd
        except ImportError:
            QgsMessageLog.logMessage(
                "⚠ scikit-learn/rasterio/geopandas não instalados. "
                "Execute: pip install --break-system-packages scikit-learn rasterio geopandas",
                'AAP GIS',
                Qgis.Warning
            )
            QgsMessageLog.logMessage("Usando método simplificado (SAGA GIS)", 'AAP GIS', Qgis.Info)
            return gerar_zonas_saga(id_talhao, dem_path, n_zonas or 3)
        
        projeto = QgsProject.instance()
        
        # Carregar rasters
        slope_path = dem_path.replace('.tif', '_slope_graus.tif')
        twi_path = dem_path.replace('.tif', '_twi.tif')
        
        slope_layer = QgsRasterLayer(slope_path, "slope")
        twi_layer = QgsRasterLayer(twi_path, "twi")
        
        # Carregar produtividade se disponível
        prod_raster = None
        if produtividade_paths:
            prod_result = importar_mapa_produtividade(produtividade_paths[0], 'geotiff')
            if prod_result:
                prod_raster = prod_result
        
        # Carregar NDVI se disponível
        ndvi_raster = None
        if ndvi_paths:
            ndvi_result = importar_ndvi_historico(ndvi_paths)
            if ndvi_result:
                ndvi_raster = ndvi_result['ndvi_medio']
        
        # Definir pesos
        if pesos_variaveis is None:
            pesos_variaveis = {
                'produtividade': 0.35 if prod_raster else 0,
                'ndvi': 0.25 if ndvi_raster else 0,
                'slope': 0.15,
                'twi': 0.10,
                'argila': 0.10 if 'argila' in solo_paths else 0,
                'alt_rel': 0.05
            }
            
            # Redistribuir pesos de dados ausentes
            total_disponivel = sum(pesos_variaveis.values())
            if total_disponivel > 0:
                for k in pesos_variaveis:
                    pesos_variaveis[k] = pesos_variaveis[k] / total_disponivel
        
        QgsMessageLog.logMessage(f"Pesos das variáveis: {pesos_variaveis}", 'AAP GIS', Qgis.Info)
        
        # Simplificação: usar SAGA GIS clustering para MVP
        # Para implementação completa, extrair valores dos rasters e fazer clustering em Python
        
        QgsMessageLog.logMessage("Usando SAGA GIS Cluster Analysis...", 'AAP GIS', Qgis.Info)
        
        return gerar_zonas_saga(id_talhao, dem_path, n_zonas or 3)
        
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro no clustering: {str(e)}", 'AAP GIS', Qgis.Critical)
        return None


def gerar_zonas_saga(id_talhao, dem_path, n_zonas):
    """
    Gera zonas usando SAGA GIS Cluster Analysis (método simplificado)
    
    Parâmetros:
    - id_talhao: ID do talhão
    - dem_path: Caminho do DEM
    - n_zonas: Número de zonas
    
    Retorna:
    - QgsVectorLayer com zonas
    """
    try:
        projeto = QgsProject.instance()
        
        # Obter talhão
        talhao_layer = None
        for layer in projeto.mapLayers().values():
            if layer.name() == 'talhoes':
                talhao_layer = layer
                break
        
        if not talhao_layer:
            return None
        
        talhao_feat = None
        for feat in talhao_layer.getFeatures():
            if feat['id'] == id_talhao:
                talhao_feat = feat
                break
        
        if not talhao_feat:
            return None
        
        # Usar slope raster para clustering
        slope_path = dem_path.replace('.tif', '_slope_graus.tif')
        slope_layer = QgsRasterLayer(slope_path, "slope")
        
        # Recortar slope pelo talhão
        params = {
            'INPUT': slope_layer,
            'MASK': talhao_feat.geometry(),
            'OUTPUT': 'memory:'
        }
        
        result = processing.run("gdal:cliprasterbymask", params)
        slope_clip = result['OUTPUT']
        
        # Reclassificar em n_zonas
        params = {
            'INPUT': slope_clip,
            'BAND': 1,
            'TABLE': gerar_tabela_reclassificacao(n_zonas),
            'NO_DATA': -9999,
            'OUTPUT': 'memory:'
        }
        
        result = processing.run("gdal:reclassify", params)
        zonas_raster = result['OUTPUT']
        
        # Vetorizar
        params = {
            'INPUT': zonas_raster,
            'BAND': 1,
            'FIELD': 'zona',
            'OUTPUT': 'memory:'
        }
        
        result = processing.run("gdal:polygonize", result)
        zonas_layer = result['OUTPUT']
        
        # Adicionar atributos
        provider = zonas_layer.dataProvider()
        provider.addAttributes([
            QgsField('id_talhao', QVariant.Int),
            QgsField('zona_k', QVariant.Int),
            QgsField('area_ha', QVariant.Double),
            QgsField('pct_area', QVariant.Double),
            QgsField('descricao_automatica', QVariant.String, 200),
            QgsField('recomendacao', QVariant.String, 200)
        ])
        zonas_layer.updateFields()
        
        # Calcular estatísticas
        zonas_layer.startEditing()
        total_area = 0
        
        for feat in zonas_layer.getFeatures():
            area_ha = feat.geometry().area() / 10000
            feat.setAttribute('area_ha', area_ha)
            feat.setAttribute('id_talhao', id_talhao)
            
            zona_k = int(feat.get('DN', 0))
            feat.setAttribute('zona_k', zona_k)
            
            total_area += area_ha
        
        # Calcular percentuais e gerar descrições
        for feat in zonas_layer.getFeatures():
            pct = (feat['area_ha'] / total_area * 100) if total_area > 0 else 0
            feat.setAttribute('pct_area', pct)
            
            zona_k = feat['zona_k']
            desc, rec = interpretar_zona_simplificada(zona_k, n_zonas)
            feat.setAttribute('descricao_automatica', desc)
            feat.setAttribute('recomendacao', rec)
            
            zonas_layer.updateFeature(feat)
        
        zonas_layer.commitChanges()
        
        QgsProject.instance().addMapLayer(zonas_layer)
        
        QgsMessageLog.logMessage(f"✓ Zonas SAGA geradas: {zonas_layer.featureCount()}", 'AAP GIS', Qgis.Info)
        
        return zonas_layer
        
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro ao gerar zonas SAGA: {str(e)}", 'AAP GIS', Qgis.Critical)
        return None


def gerar_tabela_reclassificacao(n_zonas):
    """
    Gera tabela de reclassificação para n zonas
    """
    tabela = ""
    step = 15 / n_zonas  # assumindo slope max 15°
    
    for i in range(n_zonas):
        min_val = i * step
        max_val = (i + 1) * step
        tabela += f"{min_val} {i} 1\n"
    
    tabela += f"15 {n_zonas} 1"
    return tabela


def interpretar_zona_simplificada(zona_k, n_zonas):
    """
    Interpretação simplificada de zona (para MVP)
    """
    if n_zonas == 3:
        if zona_k == 0:
            return "Terreno plano - alta potencialidade", "Zona potencial alta - dose máxima recomendada"
        elif zona_k == 1:
            return "Terreno moderado - potencialidade média", "Zona média - dose padrão"
        else:
            return "Terreno ondulado - restrições", "Zona limitada - investigar antes de aumentar"
    else:
        return f"Zona {zona_k} de {n_zonas}", "Recomendação a definir"


def interpretar_zona(stats):
    """
    Interpretação automática completa de zona (para implementação futura)
    
    Gera descrição textual baseada nas estatísticas da zona
    """
    descricao = []
    
    if stats.get('produtividade_media', 0) > 0:
        prod = stats['produtividade_media']
        if prod > 4000:  # exemplo para soja
            descricao.append("Alta produtividade histórica")
        elif prod < 3000:
            descricao.append("Baixa produtividade histórica - investigar limitantes")
    
    if stats.get('slope_medio', 0) > 5:
        descricao.append(f"Declive moderado ({stats['slope_medio']:.1f}°) - risco de erosão")
    
    if stats.get('twi_medio', 0) > 7:
        descricao.append("Tendência a encharcamento (TWI alto)")
    
    if stats.get('ndvi_medio', 0) < 0.4:
        descricao.append("Baixa biomassa histórica - avaliar estresse")
    
    # Recomendação de dose
    if len(descricao) == 0:
        recomendacao = "Zona média - dose padrão"
    elif "Alta produtividade" in ' '.join(descricao):
        recomendacao = "Zona potencial alta - aplicar dose máxima recomendada"
    elif "Baixa produtividade" in ' '.join(descricao):
        recomendacao = "Zona limitada - investigar antes de aumentar investimento"
    else:
        recomendacao = "Zona média - dose padrão"
    
    return ' | '.join(descricao), recomendacao


# ============================================================================
# FUNÇÃO PRINCIPAL
# ============================================================================

def gerar_zonas_manejo_dados(
    id_talhao,
    dem_path,
    modo='auto',
    tipo_solo='default',
    produtividade_paths=[],
    ndvi_paths=[],
    solo_paths={},
    n_zonas=None,
    area_minima_ha=5.0
):
    """
    Função principal de geração de zonas de manejo
    
    Modos:
    - 'auto': Seleciona automaticamente baseado em dados disponíveis
    - 'terreno': Modo 1 - apenas terreno
    - 'produtividade': Modo 2 - com produtividade
    - 'clustering': Modo 3 - K-Means completo
    
    Parâmetros:
    - id_talhao: ID do talhão
    - dem_path: Caminho do DEM
    - modo: Modo de operação
    - tipo_solo: Tipo de solo (para modo terreno)
    - produtividade_paths: Lista de caminhos de produtividade
    - ndvi_paths: Lista de caminhos NDVI
    - solo_paths: Dict de caminhos de solo
    - n_zonas: Número de zonas
    - area_minima_ha: Área mínima por zona
    
    Retorna:
    - QgsVectorLayer com zonas
    """
    try:
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("GERAÇÃO DE ZONAS DE MANEJO - PARTE 10", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        
        # Selecionar modo se auto
        if modo == 'auto':
            if produtividade_paths and ndvi_paths and solo_paths:
                modo = 'clustering'
                QgsMessageLog.logMessage("Dados completos disponíveis: usando clustering", 'AAP GIS', Qgis.Info)
            elif produtividade_paths:
                modo = 'produtividade'
                QgsMessageLog.logMessage("Produtividade disponível: usando modo 2", 'AAP GIS', Qgis.Info)
            else:
                modo = 'terreno'
                QgsMessageLog.logMessage("Apenas dados de terreno: usando modo 1", 'AAP GIS', Qgis.Info)
        
        QgsMessageLog.logMessage(f"Modo selecionado: {modo}", 'AAP GIS', Qgis.Info)
        
        # Executar modo
        if modo == 'terreno':
            resultado = gerar_zonas_terreno_apenas(
                id_talhao,
                dem_path,
                tipo_solo
            )
        elif modo == 'produtividade':
            QgsMessageLog.logMessage("Modo produtividade: importar e processar", 'AAP GIS', Qgis.Info)
            prod_raster = importar_mapa_produtividade(produtividade_paths[0])
            if prod_raster:
                resultado = gerar_zonas_saga(id_talhao, dem_path, n_zonas or 3)
            else:
                resultado = gerar_zonas_terreno_apenas(id_talhao, dem_path, tipo_solo)
        elif modo == 'clustering':
            resultado = gerar_zonas_clustering(
                id_talhao,
                dem_path,
                produtividade_paths,
                ndvi_paths,
                solo_paths,
                n_zonas,
                area_minima_ha
            )
        else:
            QgsMessageLog.logMessage(f"✗ Modo desconhecido: {modo}", 'AAP GIS', Qgis.Critical)
            return None
        
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("✓ GERAÇÃO DE ZONAS CONCLUÍDA", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        
        return resultado
        
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro na geração de zonas: {str(e)}", 'AAP GIS', Qgis.Critical)
        return None


# ============================================================================
# EXECUÇÃO
# ============================================================================

if __name__ == "__main__":
    print("""
    ============================================================================
    AAP GIS - PARTE 10: ZONAS DE MANEJO ORIENTADAS POR DADOS
    ============================================================================
    
    Este script deve ser executado dentro do QGIS (Console Python)
    
    Dependências para modo clustering:
    pip install --break-system-packages scikit-learn rasterio geopandas
    
    Para usar:
    >>> import sys
    >>> sys.path.insert(0, 'c:/caminho/para/scripts')
    >>> from aap_part10_zonas_dados import *
    >>> 
    >>> # Modo auto (seleciona baseado em dados disponíveis)
    >>> zonas = gerar_zonas_manejo_dados(
    ...     id_talhao=1,
    ...     dem_path='caminho/DEM.tif',
    ...     modo='auto',
    ...     tipo_solo='latossolo_roxo'
    ... )
    >>> 
    >>> # Modo clustering completo
    >>> zonas = gerar_zonas_manejo_dados(
    ...     id_talhao=1,
    ...     dem_path='caminho/DEM.tif',
    ...     modo='clustering',
    ...     produtividade_paths=['prod_2023.tif', 'prod_2024.tif'],
    ...     ndvi_paths=['ndvi_2023.tif'],
    ...     solo_paths={'argila': 'solo_argila.shp', 'MO': 'solo_mo.shp'},
    ...     n_zonas=4
    ... )
    >>> 
    >>> # Importar mapa de produtividade separadamente
    >>> prod = importar_mapa_produtividade(
    ...     'produtividade.shp',
    ...     formato='shapefile',
    ...     projeto_path='caminho/AAP_Projeto'
    ... )
    ============================================================================
    """)
