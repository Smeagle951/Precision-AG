"""
 ============================================================================
 AAP GIS - PARTE 2: IMPORTAÇÃO E LIMPEZA DE DADOS
 ============================================================================
 Sistema de Agricultura de Precisão com QGIS + SAGA GIS + PyQGIS
 
 Este script importa talhões e DEM de diversos formatos, reprojeta para UTM
 SIRGAS 2000 e aplica pipeline de limpeza de geometrias.
 
 Autor: Sistema AAP GIS v2.0
 Data: 2024
 ============================================================================"""

import os
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsRasterLayer,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsFeature, QgsGeometry, QgsField,
    QgsProcessingFeedback, QgsProcessingContext
)
from qgis.core import QgsProcessingRegistry
from qgis import processing
from qgis.PyQt.QtCore import QVariant


# ============================================================================
# FUNÇÕES DE IMPORTAÇÃO DE TALHÕES
# ============================================================================

def importar_shapefile(caminho_shp, epsg_destino="EPSG:31981"):
    """
    Importa shapefile e reprojeta se necessário
    
    Parâmetros:
    - caminho_shp: Caminho do arquivo .shp
    - epsg_destino: EPSG de destino (UTM SIRGAS 2000)
    
    Retorna:
    - QgsVectorLayer reprojetada ou None se erro
    """
    try:
        # Carregar shapefile
        layer = QgsVectorLayer(caminho_shp, "talhao_temp", "ogr")
        
        if not layer.isValid():
            print(f"✗ Erro ao carregar shapefile: {caminho_shp}")
            return None
        
        # Verificar CRS original
        crs_origem = layer.crs()
        print(f"CRS original: {crs_origem.authid()}")
        
        # Reprojetar se necessário
        if crs_origem.authid() != epsg_destino:
            print(f"Reprojetando para {epsg_destino}...")
            
            # Usar processing para reprojetar
            params = {
                'INPUT': layer,
                'TARGET_CRS': epsg_destino,
                'OUTPUT': 'memory:'
            }
            
            result = processing.run("native:reprojectlayer", params)
            layer = result['OUTPUT']
            print("✓ Reprojeção concluída")
        
        return layer
        
    except Exception as e:
        print(f"✗ Erro ao importar shapefile: {str(e)}")
        return None


def importar_kml(caminho_kml, epsg_destino="EPSG:31981"):
    """
    Importa KML/KMZ e converte de WGS84 para UTM
    
    Parâmetros:
    - caminho_kml: Caminho do arquivo .kml ou .kmz
    - epsg_destino: EPSG de destino
    
    Retorna:
    - QgsVectorLayer reprojetada ou None se erro
    """
    try:
        # Carregar KML (vem em WGS84)
        layer = QgsVectorLayer(caminho_kml, "talhao_kml", "ogr")
        
        if not layer.isValid():
            print(f"✗ Erro ao carregar KML: {caminho_kml}")
            return None
        
        print("KML carregado (WGS84), reprojetando para UTM...")
        
        # Reprojetar de WGS84 para UTM
        params = {
            'INPUT': layer,
            'TARGET_CRS': epsg_destino,
            'OUTPUT': 'memory:'
        }
        
        result = processing.run("native:reprojectlayer", params)
        layer = result['OUTPUT']
        print("✓ KML importado e reprojetado")
        
        return layer
        
    except Exception as e:
        print(f"✗ Erro ao importar KML: {str(e)}")
        return None


def importar_geojson(caminho_geojson, epsg_destino="EPSG:31981"):
    """
    Importa GeoJSON e valida estrutura
    
    Parâmetros:
    - caminho_geojson: Caminho do arquivo .geojson
    - epsg_destino: EPSG de destino
    
    Retorna:
    - QgsVectorLayer ou None se erro
    """
    try:
        layer = QgsVectorLayer(caminho_geojson, "talhao_geojson", "ogr")
        
        if not layer.isValid():
            print(f"✗ Erro ao carregar GeoJSON: {caminho_geojson}")
            return None
        
        # Verificar e reprojetar se necessário
        if layer.crs().authid() != epsg_destino:
            params = {
                'INPUT': layer,
                'TARGET_CRS': epsg_destino,
                'OUTPUT': 'memory:'
            }
            result = processing.run("native:reprojectlayer", params)
            layer = result['OUTPUT']
        
        print("✓ GeoJSON importado")
        return layer
        
    except Exception as e:
        print(f"✗ Erro ao importar GeoJSON: {str(e)}")
        return None


def importar_csv_coordenadas(caminho_csv, epsg_destino="EPSG:31981"):
    """
    Importa CSV com coordenadas lat/lon e cria polígono
    
    Formato CSV esperado:
    lat,lon,ordem
    -23.5,-46.6,1
    -23.5,-46.5,2
    ...
    
    Parâmetros:
    - caminho_csv: Caminho do arquivo CSV
    - epsg_destino: EPSG de destino
    
    Retorna:
    - QgsVectorLayer com polígono ou None se erro
    """
    try:
        import csv
        
        # Ler CSV
        pontos = []
        with open(caminho_csv, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                pontos.append({
                    'lat': float(row['lat']),
                    'lon': float(row['lon']),
                    'ordem': int(row.get('ordem', 0))
                })
        
        # Ordenar por ordem
        pontos.sort(key=lambda x: x['ordem'])
        
        # Criar layer temporário
        layer = QgsVectorLayer(
            f"Polygon?crs={epsg_destino}",
            "talhao_csv",
            "memory"
        )
        
        provider = layer.dataProvider()
        provider.addAttributes([QgsField("id", QVariant.Int)])
        layer.updateFields()
        
        # Criar geometria do polígono
        from qgis.core import QgsPoint
        vertices = []
        for p in pontos:
            # Converter lat/lon para ponto (assumindo WGS84)
            point = QgsPointXY(p['lon'], p['lat'])
            vertices.append(point)
        
        # Fechar polígono
        if vertices:
            vertices.append(vertices[0])
        
        # Criar feature
        feat = QgsFeature(layer.fields())
        geom = QgsGeometry.fromPolygonXY([vertices])
        feat.setGeometry(geom)
        feat.setAttribute('id', 1)
        
        provider.addFeature(feat)
        layer.updateExtents()
        
        print(f"✓ CSV importado com {len(pontos)} pontos")
        return layer
        
    except Exception as e:
        print(f"✗ Erro ao importar CSV: {str(e)}")
        return None


def importar_talhao(caminho_arquivo, epsg_destino="EPSG:31981"):
    """
    Função unificada de importação que detecta formato automaticamente
    
    Parâmetros:
    - caminho_arquivo: Caminho do arquivo (qualquer formato)
    - epsg_destino: EPSG de destino
    
    Retorna:
    - QgsVectorLayer ou None se erro
    """
    ext = os.path.splitext(caminho_arquivo)[1].lower()
    
    if ext == '.shp':
        return importar_shapefile(caminho_arquivo, epsg_destino)
    elif ext in ['.kml', '.kmz']:
        return importar_kml(caminho_arquivo, epsg_destino)
    elif ext == '.geojson':
        return importar_geojson(caminho_arquivo, epsg_destino)
    elif ext == '.csv':
        return importar_csv_coordenadas(caminho_arquivo, epsg_destino)
    else:
        print(f"✗ Formato não suportado: {ext}")
        return None


# ============================================================================
# PIPELINE DE LIMPEZA DE GEOMETRIAS
# ============================================================================

def limpar_geometrias(layer):
    """
    Executa pipeline completo de limpeza de geometrias
    
    Ordem:
    1. Fix Geometries
    2. Remove Null Geometries
    3. Delete Holes (buracos < 100m²)
    4. Simplify (se vértices > 500)
    5. Dissolve (se múltiplos polígonos)
    6. Multipart to Singleparts
    
    Parâmetros:
    - layer: QgsVectorLayer de entrada
    
    Retorna:
    - QgsVectorLayer limpa ou None se erro
    """
    try:
        current_layer = layer
        
        # 1. Fix Geometries
        print("1. Fix Geometries...")
        params = {
            'INPUT': current_layer,
            'OUTPUT': 'memory:'
        }
        result = processing.run("native:fixgeometries", params)
        current_layer = result['OUTPUT']
        
        # 2. Remove Null Geometries
        print("2. Remove Null Geometries...")
        params = {
            'INPUT': current_layer,
            'OUTPUT': 'memory:'
        }
        result = processing.run("native:removenullgeometries", params)
        current_layer = result['OUTPUT']
        
        # 3. Delete Holes (buracos < 100m²)
        print("3. Delete Holes (< 100m²)...")
        params = {
            'INPUT': current_layer,
            'MIN_AREA': 100,
            'OUTPUT': 'memory:'
        }
        result = processing.run("native:deleteholes", params)
        current_layer = result['OUTPUT']
        
        # 4. Simplify (se necessário)
        for feat in current_layer.getFeatures():
            if feat.geometry().constGet().nCoordinates() > 500:
                print("4. Simplify (vértices excessivos)...")
                params = {
                    'INPUT': current_layer,
                    'TOLERANCE': 0.1,
                    'OUTPUT': 'memory:'
                }
                result = processing.run("native:simplifygeometries", params)
                current_layer = result['OUTPUT']
                break
        
        # 5. Dissolve (se múltiplos polígonos)
        if current_layer.featureCount() > 1:
            print("5. Dissolve (múltiplos polígonos)...")
            params = {
                'INPUT': current_layer,
                'OUTPUT': 'memory:'
            }
            result = processing.run("native:dissolve", params)
            current_layer = result['OUTPUT']
        
        # 6. Multipart to Singleparts (OBRIGATÓRIO)
        print("6. Multipart to Singleparts...")
        params = {
            'INPUT': current_layer,
            'OUTPUT': 'memory:'
        }
        result = processing.run("native:multiparttosingleparts", params)
        current_layer = result['OUTPUT']
        
        print("✓ Limpeza de geometrias concluída")
        return current_layer
        
    except Exception as e:
        print(f"✗ Erro na limpeza de geometrias: {str(e)}")
        return layer  # Retorna original se falhar


# ============================================================================
# VALIDAÇÃO DE TALHÕES
# ============================================================================

def validar_talhoes(layer, area_min_ha=1.0):
    """
    Valida talhões após importação e limpeza
    
    Verifica:
    - Geometria válida
    - Área mínima
    - Sem sobreposição entre talhões
    - CRS correto
    
    Parâmetros:
    - layer: QgsVectorLayer de talhões
    - area_min_ha: Área mínima em hectares
    
    Retorna:
    - dict com relatório de validação
    """
    relatorio = {
        'total_talhoes': 0,
        'area_total_ha': 0,
        'problemas': [],
        'talhoes_rejeitados': [],
        'talhoes_validos': 0
    }
    
    try:
        relatorio['total_talhoes'] = layer.featureCount()
        
        for feat in layer.getFeatures():
            geom = feat.geometry()
            
            # Verificar geometria válida
            if not geom.isGeosValid():
                relatorio['problemas'].append(
                    f"Feature {feat.id()}: geometria inválida"
                )
                relatorio['talhoes_rejeitados'].append(feat.id())
                continue
            
            # Verificar área mínima
            area_m2 = geom.area()
            area_ha = area_m2 / 10000
            
            if area_ha < area_min_ha:
                relatorio['problemas'].append(
                    f"Feature {feat.id()}: área {area_ha:.2f}ha < mínimo {area_min_ha}ha"
                )
                relatorio['talhoes_rejeitados'].append(feat.id())
                continue
            
            relatorio['area_total_ha'] += area_ha
            relatorio['talhoes_validos'] += 1
        
        # Verificar sobreposição (se mais de 1 talhão)
        if layer.featureCount() > 1:
            params = {
                'INPUT': layer,
                'PREDICATE': [2],  # intersects
                'OUTPUT': 'memory:'
            }
            result = processing.run("native:extractbylocation", params)
            overlaps = result['OUTPUT']
            
            if overlaps.featureCount() > layer.featureCount():
                relatorio['problemas'].append(
                    "Sobreposição detectada entre talhões"
                )
        
        # Verificar CRS
        if layer.crs().authid() not in ['EPSG:31981', 'EPSG:31982', 'EPSG:31983']:
            relatorio['problemas'].append(
                f"CRS incorreto: {layer.crs().authid()}"
            )
        
        return relatorio
        
    except Exception as e:
        relatorio['problemas'].append(f"Erro na validação: {str(e)}")
        return relatorio


def gerar_relatorio_validacao(relatorio, caminho_saida):
    """
    Gera relatório de validação em formato TXT
    
    Parâmetros:
    - relatorio: dict com dados de validação
    - caminho_saida: Caminho do arquivo de saída
    """
    with open(caminho_saida, 'w', encoding='utf-8') as f:
        f.write("="*70 + "\n")
        f.write("RELATÓRIO DE VALIDAÇÃO - TALHÕES AAP GIS\n")
        f.write("="*70 + "\n\n")
        
        f.write(f"Total de talhões importados: {relatorio['total_talhoes']}\n")
        f.write(f"Área total: {relatorio['area_total_ha']:.2f} ha\n")
        f.write(f"Talhões válidos: {relatorio['talhoes_validos']}\n")
        f.write(f"Talhões rejeitados: {len(relatorio['talhoes_rejeitados'])}\n\n")
        
        if relatorio['problemas']:
            f.write("PROBLEMAS ENCONTRADOS:\n")
            f.write("-" * 70 + "\n")
            for prob in relatorio['problemas']:
                f.write(f"✗ {prob}\n")
        else:
            f.write("✓ Nenhum problema encontrado\n")
        
        f.write("\n" + "="*70 + "\n")
    
    print(f"✓ Relatório salvo em: {caminho_saida}")


# ============================================================================
# IMPORTAÇÃO DE DEM
# ============================================================================

def importar_dem(caminho_dem, epsg_destino="EPSG:31981", extensao_buffer=200):
    """
    Importa DEM, reprojeta e recorta para extensão dos talhões
    
    Parâmetros:
    - caminho_dem: Caminho do DEM (.tif, .hgt, .asc)
    - epsg_destino: EPSG de destino
    - extensao_buffer: Buffer em metros ao redor dos talhões
    
    Retorna:
    - QgsRasterLayer processada ou None se erro
    """
    try:
        # Carregar DEM
        dem_layer = QgsRasterLayer(caminho_dem, "dem_temp")
        
        if not dem_layer.isValid():
            print(f"✗ Erro ao carregar DEM: {caminho_dem}")
            return None
        
        print(f"CRS original do DEM: {dem_layer.crs().authid()}")
        
        # Reprojetar se necessário
        if dem_layer.crs().authid() != epsg_destino:
            print("Reprojetando DEM...")
            params = {
                'INPUT': dem_layer,
                'TARGET_CRS': epsg_destino,
                'RESAMPLING': 0,  # Nearest neighbour
                'OUTPUT': 'memory:'
            }
            result = processing.run("gdal:warpreproject", params)
            dem_layer = result['OUTPUT']
        
        # Recortar para extensão dos talhões (se disponíveis)
        projeto = QgsProject.instance()
        talhoes_layer = None
        
        for layer in projeto.mapLayers().values():
            if layer.name() == 'talhoes':
                talhoes_layer = layer
                break
        
        if talhoes_layer and talhoes_layer.featureCount() > 0:
            print("Recortando DEM para extensão dos talhões...")
            
            # Criar buffer ao redor dos talhões
            params = {
                'INPUT': talhoes_layer,
                'DISTANCE': extensao_buffer,
                'OUTPUT': 'memory:'
            }
            result = processing.run("native:buffer", params)
            buffer_layer = result['OUTPUT']
            
            # Recortar DEM
            params = {
                'INPUT': dem_layer,
                'MASK': buffer_layer,
                'OUTPUT': 'memory:'
            }
            result = processing.run("gdal:cliprasterbymasklayer", params)
            dem_layer = result['OUTPUT']
            
            print("✓ DEM recortado")
        
        print("✓ DEM importado com sucesso")
        return dem_layer
        
    except Exception as e:
        print(f"✗ Erro ao importar DEM: {str(e)}")
        return None


# ============================================================================
# FUNÇÃO PRINCIPAL DE IMPORTAÇÃO
# ============================================================================

def importar_e_processar_talhao(
    caminho_arquivo,
    nome_talhao,
    cultura="soja",
    safra="2024/25",
    projeto_path=None,
    epsg_utm="EPSG:31981"
):
    """
    Função completa de importação e processamento de talhão
    
    Parâmetros:
    - caminho_arquivo: Caminho do arquivo de entrada
    - nome_talhao: Nome do talhão
    - cultura: Cultura (soja, milho, algodao, etc.)
    - safra: Safra (ex: 2024/25)
    - projeto_path: Caminho do projeto AAP
    - epsg_utm: EPSG da zona UTM
    
    Retorna:
    - feature_id se sucesso, None se erro
    """
    try:
        print("\n" + "="*70)
        print(f"IMPORTANDO TALHÃO: {nome_talhao}")
        print("="*70)
        
        # 1. Importar
        print("\n[1/5] Importando arquivo...")
        layer = importar_talhao(caminho_arquivo, epsg_utm)
        if not layer:
            return None
        
        # 2. Limpar geometrias
        print("\n[2/5] Limpando geometrias...")
        layer = limpar_geometrias(layer)
        if not layer:
            return None
        
        # 3. Validar
        print("\n[3/5] Validando...")
        relatorio = validar_talhoes(layer)
        
        if relatorio['talhoes_validos'] == 0:
            print("✗ Nenhum talhão válido após validação")
            return None
        
        # 4. Salvar no GeoPackage
        print("\n[4/5] Salvando no GeoPackage...")
        projeto = QgsProject.instance()
        
        # Encontrar camada talhoes no projeto
        talhoes_gpkg = None
        for layer_proj in projeto.mapLayers().values():
            if layer_proj.name() == 'talhoes':
                talhoes_gpkg = layer_proj
                break
        
        if not talhoes_gpkg:
            print("✗ Camada 'talhoes' não encontrada no projeto")
            return None
        
        # Adicionar feature ao GeoPackage
        provider = talhoes_gpkg.dataProvider()
        
        for feat in layer.getFeatures():
            nova_feat = QgsFeature(talhoes_gpkg.fields())
            nova_feat.setGeometry(feat.geometry())
            
            # Preencher atributos
            nova_feat.setAttribute('nome', nome_talhao)
            nova_feat.setAttribute('area_ha', feat.geometry().area() / 10000)
            nova_feat.setAttribute('cultura', cultura)
            nova_feat.setAttribute('safra', safra)
            nova_feat.setAttribute('data_plantio', None)
            nova_feat.setAttribute('obs', '')
            
            # ID automático
            max_id = 0
            for f in talhoes_gpkg.getFeatures():
                if f['id'] > max_id:
                    max_id = f['id']
            nova_feat.setAttribute('id', max_id + 1)
            
            provider.addFeature(nova_feat)
        
        talhoes_gpkg.updateExtents()
        
        # 5. Gerar relatório
        print("\n[5/5] Gerando relatório...")
        if projeto_path:
            caminho_relatorio = os.path.join(
                projeto_path,
                AAPConfig.PASTA_TALHOES,
                f"relatorio_validacao_{nome_talhao}.txt"
            )
            gerar_relatorio_validacao(relatorio, caminho_relatorio)
        
        # Salvar também como SHP em 02_Talhoes
        if projeto_path:
            caminho_shp = os.path.join(
                projeto_path,
                AAPConfig.PASTA_TALHOES,
                f"{nome_talhao}.shp"
            )
            
            params = {
                'INPUT': talhoes_gpkg,
                'OUTPUT': caminho_shp
            }
            processing.run("native:savefeatures", params)
            print(f"✓ Talhão salvo como SHP: {caminho_shp}")
        
        print("\n" + "="*70)
        print("✓ TALHÃO IMPORTADO COM SUCESSO!")
        print("="*70)
        print(f"Nome: {nome_talhao}")
        print(f"Área: {relatorio['area_total_ha']:.2f} ha")
        print(f"Cultura: {cultura}")
        print(f"Safra: {safra}")
        
        return nova_feat['id']
        
    except Exception as e:
        print(f"✗ Erro ao processar talhão: {str(e)}")
        return None


# ============================================================================
# EXECUÇÃO
# ============================================================================

if __name__ == "__main__":
    print("""
    ============================================================================
    AAP GIS - PARTE 2: IMPORTAÇÃO E LIMPEZA DE DADOS
    ============================================================================
    
    Este script deve ser executado dentro do QGIS (Console Python)
    
    Para usar:
    >>> import sys
    >>> sys.path.insert(0, 'c:/caminho/para/scripts')
    >>> from aap_part2_importacao import *
    >>> 
    >>> # Importar talhão
    >>> importar_e_processar_talhao(
    ...     caminho_arquivo='C:/caminho/talhao.shp',
    ...     nome_talhao='Talhao_01',
    ...     cultura='soja',
    ...     safra='2024/25',
    ...     projeto_path='C:/caminho/AAP_Projeto',
    ...     epsg_utm='EPSG:31981'
    ... )
    
    ============================================================================
    """)
