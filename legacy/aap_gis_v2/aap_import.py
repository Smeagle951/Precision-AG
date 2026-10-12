# AAP GIS - Atalho de Importação
# Cole este código no início de cada sessão do QGIS Console Python

import sys
sys.path.insert(0, r"c:\Users\fortu\Desktop\PYTON")

# Importar funções principais
from aap_part1_setup import configurar_projeto_aap
from aap_part2_importacao import importar_e_processar_talhao
from aap_part3_bordadura import gerar_bordadura
from aap_part4_plantio import gerar_linhas_plantio
from aap_part5_pulverizacao import gerar_linhas_pulverizacao
from aap_part6_relevo import analisar_terreno
from aap_part7_cruzamento import analisar_cruzamentos
from aap_part8_exportacao_expanded import executar_pipeline_completo
from aap_part9_linhas_agronomicas import gerar_linhas_agronomicas
from aap_part10_zonas_dados import gerar_zonas_manejo_dados
from aap_part11_conformidade import analisar_conformidade_completa
from aap_part12_isoxml_profissional import gerar_prescricao_isoxml_completa
from aap_part13_motor_decisao import executar_motor_decisao

# Importar API simples e fluxo único
from aap_simple_api import criar_projeto_plantio, plantar
from aap_single_flow import fluxo_unico_inteligente, mostrar_resultado_usuario

print("✅ AAP GIS carregado com sucesso!")
print("📁 Scripts disponíveis: Partes 1-13")
print("🚀 API simples disponível: criar_projeto_plantio(), plantar()")
print("⚡ Fluxo único disponível: fluxo_unico_inteligente()")
