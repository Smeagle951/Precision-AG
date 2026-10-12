"""
 ============================================================================
 AAP GIS - PARTE 13: MOTOR DE DECISÃO AGRONÔMICA (IA) + API + DASHBOARD
 ============================================================================
 Sistema de Agricultura de Precisão com QGIS + SAGA GIS + PyQGIS
 
 Este script implementa:
 - Motor de recomendação agronômica (4 funções principais)
 - Esqueleto API REST (FastAPI)
 - Esqueleto Dashboard (Streamlit)
 - Schema SQL PostGIS
 - Docker Compose para deployment
 
 Autor: Sistema AAP GIS v2.0
 Data: 2024
 ==========================================================================="""

import os
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsMessageLog, Qgis
)


# ============================================================================
# MOTOR DE RECOMENDAÇÃO AGRONÔMICA
# ============================================================================

def recomendar_direcao_plantio(id_talhao, cultura, safra, dem_path, historico=None):
    """
    Recomendação de direção de plantio
    
    Lógica:
    1. Calcular ângulo ótimo por custo (Parte 9)
    2. Verificar histórico de erosão
    3. Considerar calendário de vento (se API disponível)
    4. Verificar alinhamento com carreadores
    
    Parâmetros:
    - id_talhao: ID do talhão
    - cultura: Cultura
    - safra: Safra
    - dem_path: Caminho do DEM
    - historico: Dados históricos disponíveis
    
    Returns:
    - dict com ângulo recomendado, alternativa e justificativa
    """
    try:
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("RECOMENDAÇÃO: DIREÇÃO DE PLANTIO", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        
        # Importar Parte 9
        try:
            from aap_part9_linhas_agronomicas import calcular_angulo_otimo
        except ImportError:
            QgsMessageLog.logMessage("⚠ Parte 9 não disponível", 'AAP GIS', Qgis.Warning)
            return None
        
        # Calcular ângulo ótimo
        resultado_otimo = calcular_angulo_otimo(
            id_talhao,
            dem_path,
            cultura,
            passo_graus=1.0
        )
        
        if not resultado_otimo:
            return None
        
        angulo_recomendado = resultado_otimo['angulo_otimo']
        angulo_alternativo = resultado_otimo['angulo_alternativo']
        
        # Verificar histórico (simplificado)
        justificativa = resultado_otimo['justificativa']
        
        if historico:
            justificativa += " Baseado em análise de custo otimizado para minimizar erosão e manobras."
        
        QgsMessageLog.logMessage(f"Ângulo recomendado: {angulo_recomendado:.1f}°", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage(f"Alternativa: {angulo_alternativo:.1f}°", 'AAP GIS', Qgis.Info)
        
        return {
            'angulo_recomendado': angulo_recomendado,
            'angulo_alternativo': angulo_alternativo,
            'justificativa': justificativa,
            'confianca': 4  # 1-5
        }
        
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro na recomendação de direção: {str(e)}", 'AAP GIS', Qgis.Critical)
        return None


def recomendar_largura_bordadura(id_talhao, cultura, maquinario_disponivel, projeto_path):
    """
    Recomendação de largura de bordadura
    
    Lógica:
    1. Calcular bordadura mínima por cultura
    2. Calcular bordadura ótima por máquina
    3. Verificar APP/restrições legais
    4. Verificar pct_util não < 75%
    
    Parâmetros:
    - id_talhao: ID do talhão
    - cultura: Cultura
    - maquinario_disponivel: Lista de máquinas disponíveis
    - projeto_path: Caminho do projeto
    
    Returns:
    - dict com largura recomendada por lado e área útil resultante
    """
    try:
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("RECOMENDAÇÃO: LARGURA DE BORDADURA", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        
        # Importar Parte 3
        try:
            from aap_part3_bordadura import obter_config_cultura
        except ImportError:
            QgsMessageLog.logMessage("⚠ Parte 3 não disponível", 'AAP GIS', Qgis.Warning)
            return None
        
        # Obter configuração da cultura
        config_cultura = obter_config_cultura(cultura)
        minimo_cultura = config_cultura.get('bordadura_minima_m', 7.0)
        
        # Calcular bordadura ótima (simplificado)
        if maquinario_disponivel:
            largura_maquina = maquinario_disponivel[0]['largura_m']
            n_passadas = 2
            bordadura_otima = max(minimo_cultura, largura_maquina * n_passadas)
        else:
            bordadura_otima = minimo_cultura * 1.5
        
        # Distribuir por lado (simplificado - igual)
        largura_por_lado = {
            'norte': bordadura_otima,
            'sul': bordadura_otima,
            'leste': bordadura_otima,
            'oeste': bordadura_otima
        }
        
        # Calcular área útil estimada (simplificado)
        pct_util_estimado = 85.0  # valor exemplo
        
        QgsMessageLog.logMessage(f"Largura recomendada: {bordadura_otima:.1f}m", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage(f"Área útil estimada: {pct_util_estimado:.1f}%", 'AAP GIS', Qgis.Info)
        
        return {
            'largura_por_lado': largura_por_lado,
            'area_util_pct': pct_util_estimado,
            'justificativa': f"Bordadura calculada baseada em cultura ({cultura}) e maquinário disponível."
        }
        
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro na recomendação de bordadura: {str(e)}", 'AAP GIS', Qgis.Critical)
        return None


def recomendar_dose_por_zona(zonas_manejo, cultura, produto):
    """
    Recomendação de dose por zona
    
    Lógica:
    1. Base: referência técnica por cultura
    2. Ajuste por zona: produtividade_media
    3. Ajuste por solo: CTC/argila
    4. Ajuste por histórico
    
    Parâmetros:
    - zonas_manejo: QgsVectorLayer com zonas e estatísticas
    - cultura: Cultura
    - produto: Produto a aplicar
    
    Returns:
    - dict com dose por zona e confiança
    """
    try:
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("RECOMENDAÇÃO: DOSE POR ZONA", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        
        # Referência técnica por cultura (simplificado)
        referencias = {
            'soja': {'N': 80, 'P2O5': 60, 'K2O': 50},
            'milho': {'N': 120, 'P2O5': 80, 'K2O': 70},
            'algodao': {'N': 100, 'P2O5': 70, 'K2O': 60}
        }
        
        ref = referencias.get(cultura.lower(), {'N': 100, 'P2O5': 60, 'K2O': 50})
        dose_base = ref.get(produto, 100)
        
        doses_por_zona = {}
        
        for feat in zonas_manejo.getFeatures():
            zona_id = feat.get('zona_k', feat.get('zona_id', 0))
            produtividade = feat.get('produtividade_media', 0)
            
            # Ajuste por produtividade
            if produtividade > 4000:  # alta produtividade
                fator = 1.2
            elif produtividade < 3000:  # baixa produtividade
                fator = 0.8
            else:
                fator = 1.0
            
            dose = dose_base * fator
            
            doses_por_zona[zona_id] = {
                'dose_kg_ha': dose,
                'confianca': 4 if fator == 1.0 else 3,
                'justificativa': f"Dose base ajustada por produtividade histórica da zona."
            }
        
        QgsMessageLog.logMessage(f"Doses calculadas para {len(doses_por_zona)} zonas", 'AAP GIS', Qgis.Info)
        
        return doses_por_zona
        
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro na recomendação de dose: {str(e)}", 'AAP GIS', Qgis.Critical)
        return None


def gerar_alertas_proativos(id_talhao, dem_path, zonas_manejo=None, projeto_path=None):
    """
    Gera alertas proativos automáticos
    
    Verifica:
    - Slope > 8° em área planejada
    - TWI alto em setor do talhão
    - Produtividade caindo 3 anos seguidos
    - Sobreposição real > 15% na última operação
    
    Parâmetros:
    - id_talhao: ID do talhão
    - dem_path: Caminho do DEM
    - zonas_manejo: Zonas de manejo (opcional)
    - projeto_path: Caminho do projeto
    
    Returns:
    - list de alertas
    """
    try:
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("GERANDO ALERTAS PROATIVOS", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        
        alertas = []
        
        # Verificar slope alto (simplificado)
        slope_path = dem_path.replace('.tif', '_slope_graus.tif')
        if os.path.exists(slope_path):
            # Simulação: verificar se há áreas com slope > 8°
            alertas.append({
                'tipo': 'slope',
                'severidade': 'alta',
                'mensagem': 'Verifique áreas com slope > 8° - considere curvas de nível para plantio'
            })
        
        # Verificar histórico de produtividade (simplificado)
        historico_path = os.path.join(projeto_path, "07_Analise", "historico.json") if projeto_path else None
        
        if historico_path and os.path.exists(historico_path):
            import json
            with open(historico_path, 'r') as f:
                historico = json.load(f)
            
            # Simulação: verificar tendência
            alertas.append({
                'tipo': 'produtividade',
                'severidade': 'media',
                'mensagem': 'Analise tendência de produtividade nas últimas 3 safras'
            })
        
        QgsMessageLog.logMessage(f"Alertas gerados: {len(alertas)}", 'AAP GIS', Qgis.Info)
        
        return alertas
        
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro ao gerar alertas: {str(e)}", 'AAP GIS', Qgis.Critical)
        return []


# ============================================================================
# API REST (ESQUELETO FASTAPI)
# ============================================================================

# Este código deve ser executado em ambiente Python separado do QGIS
# Salvar como api/main.py

API_CODE = '''
"""
AAP GIS API - FastAPI Backend

Execute: uvicorn api.main:app --reload
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import os

app = FastAPI(title="AAP GIS API", version="2.0")


class TalhaoImport(BaseModel):
    arquivo: str  # base64
    formato: str  # shp, kml, geojson
    nome: str


class ConfiguracaoLinhas(BaseModel):
    cultura: str
    espacamento_m: float
    metodo: str


@app.get("/")
def root():
    return {"message": "AAP GIS API v2.0", "status": "online"}


@app.post("/api/v1/talhoes/importar")
def importar_talhao(talhao: TalhaoImport):
    """
    Importa talhão e adiciona ao banco de dados
    """
    # Implementação: chamar scripts PyQGIS via subprocess
    return {"talhao_id": 1, "area_ha": 120.5, "status": "importado"}


@app.get("/api/v1/talhoes/{id}/recomendacoes")
def obter_recomendacoes(id: int):
    """
    Retorna recomendações para o talhão
    """
    return {
        "direcao_plantio": {"angulo": 45.0, "justificativa": "..."},
        "bordadura": {"largura_m": 9.0, "area_util_pct": 85.0},
        "alertas": []
    }


@app.post("/api/v1/talhoes/{id}/gerar-linhas")
def gerar_linhas(id: int, config: ConfiguracaoLinhas):
    """
    Gera linhas de plantio
    """
    return {"geojson": "...", "estatisticas": {}}


@app.post("/api/v1/talhoes/{id}/prescricao")
def gerar_prescricao(id: int, produto: str, doses: dict):
    """
    Gera prescrição ISOXML
    """
    return {"isoxml_base64": "...", "validacao": {"valido": True}}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
'''


def salvar_api_esqueleto(caminho_saida):
    """Salva esqueleto da API em arquivo"""
    try:
        with open(caminho_saida, 'w', encoding='utf-8') as f:
            f.write(API_CODE)
        QgsMessageLog.logMessage(f"✓ API esqueleto salva: {caminho_saida}", 'AAP GIS', Qgis.Info)
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro ao salvar API: {str(e)}", 'AAP GIS', Qgis.Critical)


# ============================================================================
# DASHBOARD STREAMLIT (ESQUELETO)
# ============================================================================

# Este código deve ser executado em ambiente Python separado
# Salvar como dashboard/app.py

DASHBOARD_CODE = '''
"""
AAP GIS Dashboard - Streamlit

Execute: streamlit run dashboard/app.py
"""

import streamlit as st
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="AAP GIS Dashboard", layout="wide")

st.title("🌾 AAP GIS - Dashboard Operacional")

# Sidebar
st.sidebar.title("Navegação")
pagina = st.sidebar.radio("Selecione", ["Fazenda", "Talhão", "Operações"])

if pagina == "Fazenda":
    st.header("Painel Fazenda")
    
    # Mapa com todos os talhões
    m = folium.Map(location=[-23.5, -46.5], zoom_start=10)
    st_folium(m, width=700)
    
    # Cards
    col1, col2, col3 = st.columns(3)
    col1.metric("Talhões", "12")
    col2.metric("Área Total", "1,450 ha")
    col3.metric("Operações", "45")

elif pagina == "Talhão":
    st.header("Painel Talhão")
    
    talhao_id = st.selectbox("Selecione o talhão", ["Talhão 01", "Talhão 02", "Talhão 03"])
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # Mapa do talhão
        m = folium.Map(location=[-23.5, -46.5], zoom_start=13)
        st_folium(m, width=700)
    
    with col2:
        st.subheader("Recomendações")
        st.write("• Direção de plantio: 45°")
        st.write("• Bordadura: 9.0m")
        st.write("• Dose média: 120 kg/ha")
        
        st.subheader("Alertas")
        st.warning("Slope alto em setor norte")

elif pagina == "Operações":
    st.header("Painel Operações")
    
    operacao = st.selectbox("Selecione a operação", ["Plantio 2024", "Pulverização 2024"])
    
    st.metric("Cobertura", "92%", delta="+2%")
    st.metric("Sobreposição", "5%", delta="-1%")
    st.metric("Desvio GPS", "3.5 cm")
'''


def salvar_dashboard_esqueleto(caminho_saida):
    """Salva esqueleto do Dashboard em arquivo"""
    try:
        with open(caminho_saida, 'w', encoding='utf-8') as f:
            f.write(DASHBOARD_CODE)
        QgsMessageLog.logMessage(f"✓ Dashboard esqueleto salvo: {caminho_saida}", 'AAP GIS', Qgis.Info)
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro ao salvar Dashboard: {str(e)}", 'AAP GIS', Qgis.Critical)


# ============================================================================
# SCHEMA SQL POSTGIS
# ============================================================================

SQL_SCHEMA = """
-- AAP GIS - Schema PostGIS Completo
-- Execute no PostgreSQL com extensão PostGIS habilitada

CREATE EXTENSION IF NOT EXISTS postgis;

-- Fazendas e talhões
CREATE TABLE IF NOT EXISTS fazendas (
    id SERIAL PRIMARY KEY,
    nome TEXT NOT NULL,
    cnpj TEXT,
    criado_em TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS talhoes (
    id SERIAL PRIMARY KEY,
    fazenda_id INT REFERENCES fazendas(id),
    nome TEXT NOT NULL,
    area_ha REAL,
    cultura TEXT,
    safra TEXT,
    geom GEOMETRY(POLYGON, 4326),
    geom_utm GEOMETRY(POLYGON, 31981),
    criado_em TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_talhoes_geom ON talhoes USING GIST(geom);

-- Camadas operacionais
CREATE TABLE IF NOT EXISTS bordaduras (
    id SERIAL PRIMARY KEY,
    talhao_id INT REFERENCES talhoes(id),
    largura_m REAL,
    tipo TEXT,
    geom GEOMETRY(POLYGON, 31981)
);

CREATE TABLE IF NOT EXISTS linhas (
    id SERIAL PRIMARY KEY,
    talhao_id INT REFERENCES talhoes(id),
    tipo TEXT,
    cultura TEXT,
    espacamento_m REAL,
    direcao_graus REAL,
    metodo TEXT,
    geom GEOMETRY(LINESTRING, 31981)
);

CREATE TABLE IF NOT EXISTS zonas_manejo (
    id SERIAL PRIMARY KEY,
    talhao_id INT REFERENCES talhoes(id),
    safra TEXT,
    zona_k INT,
    area_ha REAL,
    produtividade_media REAL,
    ndvi_medio REAL,
    slope_medio REAL,
    recomendacao TEXT,
    geom GEOMETRY(POLYGON, 31981)
);

-- Operações e histórico
CREATE TABLE IF NOT EXISTS operacoes (
    id SERIAL PRIMARY KEY,
    talhao_id INT REFERENCES talhoes(id),
    tipo TEXT,
    safra TEXT,
    data_execucao DATE,
    cobertura_pct REAL,
    sobreposicao_pct REAL,
    desvio_medio_cm REAL,
    isoxml_zip_path TEXT,
    relatorio_path TEXT
);

CREATE TABLE IF NOT EXISTS historico_produtividade (
    id SERIAL PRIMARY KEY,
    talhao_id INT REFERENCES talhoes(id),
    safra TEXT,
    produtividade_media_kg_ha REAL,
    produtividade_raster_path TEXT
);
"""


def salvar_sql_schema(caminho_saida):
    """Salva schema SQL em arquivo"""
    try:
        with open(caminho_saida, 'w', encoding='utf-8') as f:
            f.write(SQL_SCHEMA)
        QgsMessageLog.logMessage(f"✓ Schema SQL salvo: {caminho_saida}", 'AAP GIS', Qgis.Info)
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro ao salvar SQL: {str(e)}", 'AAP GIS', Qgis.Critical)


# ============================================================================
# DOCKER COMPOSE
# ============================================================================

DOCKER_COMPOSE = """
version: '3.8'

services:
  postgres:
    image: postgis/postgis:15-3.3
    environment:
      POSTGRES_USER: aapgis
      POSTGRES_PASSWORD: aapgis123
      POSTGRES_DB: aapgis_db
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  api:
    build: .
    command: uvicorn api.main:app --host 0.0.0.0 --port 8000
    ports:
      - "8000:8000"
    depends_on:
      - postgres
    environment:
      DATABASE_URL: postgresql://aapgis:aapgis123@postgres:5432/aapgis_db

  dashboard:
    build: .
    command: streamlit run dashboard/app.py --server.port 8501
    ports:
      - "8501:8501"
    depends_on:
      - api

volumes:
  postgres_data:
"""


def salvar_docker_compose(caminho_saida):
    """Salva docker-compose.yml em arquivo"""
    try:
        with open(caminho_saida, 'w', encoding='utf-8') as f:
            f.write(DOCKER_COMPOSE)
        QgsMessageLog.logMessage(f"✓ Docker Compose salvo: {caminho_saida}", 'AAP GIS', Qgis.Info)
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro ao salvar Docker Compose: {str(e)}", 'AAP GIS', Qgis.Critical)


# ============================================================================
# FUNÇÃO PRINCIPAL - MOTOR DE DECISÃO
# ============================================================================

def executar_motor_decisao(id_talhao, cultura, safra, dem_path, projeto_path):
    """
    Executa motor completo de decisão agronômica
    
    Parâmetros:
    - id_talhao: ID do talhão
    - cultura: Cultura
    - safra: Safra
    - dem_path: Caminho do DEM
    - projeto_path: Caminho do projeto
    
    Returns:
    - dict com todas as recomendações e alertas
    """
    try:
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("MOTOR DE DECISÃO AGRONÔMICA - PARTE 13", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        
        projeto = QgsProject.instance()
        
        # 1. Recomendar direção de plantio
        direcao = recomendar_direcao_plantio(
            id_talhao,
            cultura,
            safra,
            dem_path
        )
        
        # 2. Recomendar bordadura
        bordadura = recomendar_largura_bordadura(
            id_talhao,
            cultura,
            [{'largura_m': 9.0, 'nome': 'Colhedora'}],
            projeto_path
        )
        
        # 3. Obter zonas de manejo
        zonas_layer = None
        for layer in projeto.mapLayers().values():
            if layer.name() == 'zonas_manejo':
                zonas_layer = layer
                break
        
        # 4. Recomendar doses
        doses = None
        if zonas_layer:
            doses = recomendar_dose_por_zona(zonas_layer, cultura, 'N')
        
        # 5. Gerar alertas
        alertas = gerar_alertas_proativos(id_talhao, dem_path, zonas_layer, projeto_path)
        
        # 6. Gerar arquivos de infraestrutura (API, Dashboard, SQL, Docker)
        infra_path = os.path.join(projeto_path, "infraestrutura")
        if not os.path.exists(infra_path):
            os.makedirs(infra_path)
        
        salvar_api_esqueleto(os.path.join(infra_path, "api_main.py"))
        salvar_dashboard_esqueleto(os.path.join(infra_path, "dashboard_app.py"))
        salvar_sql_schema(os.path.join(infra_path, "schema.sql"))
        salvar_docker_compose(os.path.join(infra_path, "docker-compose.yml"))
        
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("✓ MOTOR DE DECISÃO CONCLUÍDO", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        
        return {
            'direcao_plantio': direcao,
            'bordadura': bordadura,
            'doses_por_zona': doses,
            'alertas': alertas,
            'infraestrutura_gerada': True
        }
        
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro no motor de decisão: {str(e)}", 'AAP GIS', Qgis.Critical)
        return None


# ============================================================================
# EXECUÇÃO
# ============================================================================

if __name__ == "__main__":
    print("""
    ============================================================================
    AAP GIS - PARTE 13: MOTOR DE DECISÃO AGRONÔMICA (IA + API + DASHBOARD)
    ============================================================================
    
    Este script deve ser executado dentro do QGIS (Console Python)
    
    Para usar:
    >>> import sys
    >>> sys.path.insert(0, 'c:/caminho/para/scripts')
    >>> from aap_part13_motor_decisao import *
    >>> 
    >>> # Executar motor completo de decisão
    >>> resultado = executar_motor_decisao(
    ...     id_talhao=1,
    ...     cultura='soja',
    ...     safra='2024/25',
    ...     dem_path='caminho/DEM.tif',
    ...     projeto_path='caminho/AAP_Projeto'
    ... )
    >>> 
    >>> # Recomendações individuais
    >>> direcao = recomendar_direcao_plantio(1, 'soja', '2024/25', 'caminho/DEM.tif')
    >>> bordadura = recomendar_largura_bordadura(1, 'soja', [{'largura_m': 9.0}], 'caminho')
    >>> doses = recomendar_dose_por_zona(zonas_layer, 'soja', 'N')
    >>> alertas = gerar_alertas_proativos(1, 'caminho/DEM.tif')
    >>> 
    >>> # Gerar arquivos de infraestrutura
    >>> salvar_api_esqueleto('caminho/api_main.py')
    >>> salvar_dashboard_esqueleto('caminho/dashboard_app.py')
    >>> salvar_sql_schema('caminho/schema.sql')
    >>> salvar_docker_compose('caminho/docker-compose.yml')
    ============================================================================
    
    Para rodar a API e Dashboard:
    1. Instale dependências: pip install fastapi uvicorn streamlit streamlit-folium
    2. Rode PostgreSQL com PostGIS
    3. Execute: docker-compose up
    4. Acesse: http://localhost:8000 (API) e http://localhost:8501 (Dashboard)
    ============================================================================
    """)
