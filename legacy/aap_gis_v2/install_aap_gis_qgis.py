"""
 ============================================================================
 AAP GIS - SCRIPT DE INSTALAÇÃO PARA QGIS
 ============================================================================
 Sistema de Agricultura de Precisão com QGIS + SAGA GIS + PyQGIS
 
 Este script deve ser executado no Console Python do QGIS (Ctrl+Alt+P)
 para configurar automaticamente o Sistema AAP GIS.
 
 AUTOR: Sistema AAP GIS v2.0
 DATA: 2024
 ============================================================================
 
 INSTRUÇÕES DE USO:
 1. Abra o QGIS
 2. Pressione Ctrl+Alt+P para abrir o Console Python
 3. Copie e cole todo este script
 4. Pressione Enter para executar
 5. Siga as instruções que aparecerem
 ============================================================================
"""

import os
import sys
from qgis.core import QgsMessageLog, Qgis

# ============================================================================
# CONFIGURAÇÕES
# ============================================================================

# Diretório onde os scripts AAP GIS estão localizados
# Altere este caminho se seus scripts estão em outro local
SCRIPTS_PATH = r"c:\Users\fortu\Desktop\PYTON"

# Caminho do projeto AAP GIS
PROJETO_PATH = os.path.join(SCRIPTS_PATH, "AAP_Projeto")

# Lista de scripts AAP GIS
AAP_SCRIPTS = [
    "aap_part1_setup.py",
    "aap_part2_importacao.py",
    "aap_part3_bordadura.py",
    "aap_part4_plantio.py",
    "aap_part5_pulverizacao.py",
    "aap_part6_relevo.py",
    "aap_part7_cruzamento.py",
    "aap_part8_exportacao.py",
    "aap_part8_exportacao_expanded.py",
    "aap_part9_linhas_agronomicas.py",
    "aap_part10_zonas_dados.py",
    "aap_part11_conformidade.py",
    "aap_part12_isoxml_profissional.py",
    "aap_part13_motor_decisao.py"
]


# ============================================================================
# FUNÇÕES DE INSTALAÇÃO
# ============================================================================

def print_banner():
    """Imprime banner de boas-vindas"""
    banner = """
    ╔══════════════════════════════════════════════════════════════════════╗
    ║                                                                    ║
    ║              🌱 SISTEMA AAP GIS - INSTALADOR 🌱                     ║
    ║              Agricultura de Precisão com QGIS                     ║
    ║              Versão 2.0 - 2024                                   ║
    ║                                                                    ║
    ╚══════════════════════════════════════════════════════════════════════╝
    """
    print(banner)


def verificar_scripts():
    """Verifica se todos os scripts AAP GIS existem"""
    print("\n🔍 VERIFICANDO SCRIPTS AAP GIS...")
    print(f"📁 Diretório de scripts: {SCRIPTS_PATH}")
    
    scripts_faltando = []
    scripts_encontrados = []
    
    for script in AAP_SCRIPTS:
        caminho_script = os.path.join(SCRIPTS_PATH, script)
        if os.path.exists(caminho_script):
            scripts_encontrados.append(script)
            print(f"  ✅ {script}")
        else:
            scripts_faltando.append(script)
            print(f"  ❌ {script} (NÃO ENCONTRADO)")
    
    print(f"\n📊 Resumo:")
    print(f"  Scripts encontrados: {len(scripts_encontrados)}/{len(AAP_SCRIPTS)}")
    
    if scripts_faltando:
        print(f"  ⚠️  Scripts faltando: {len(scripts_faltando)}")
        print(f"\n⚠️  AVISO: Alguns scripts não foram encontrados.")
        print(f"   Certifique-se de que todos os arquivos estão em: {SCRIPTS_PATH}")
        return False
    else:
        print(f"  ✅ Todos os scripts encontrados!")
        return True


def configurar_python_path():
    """Configura o Python Path no QGIS"""
    print("\n⚙️  CONFIGURANDO PYTHON PATH NO QGIS...")
    
    # Adicionar diretório de scripts ao sys.path
    if SCRIPTS_PATH not in sys.path:
        sys.path.insert(0, SCRIPTS_PATH)
        print(f"  ✅ Adicionado ao sys.path: {SCRIPTS_PATH}")
    else:
        print(f"  ℹ️  Já está no sys.path: {SCRIPTS_PATH}")
    
    # Verificar se pode importar scripts
    try:
        import aap_part1_setup
        print(f"  ✅ Teste de importação: aap_part1_setup ✓")
        return True
    except ImportError as e:
        print(f"  ❌ Erro ao importar scripts: {e}")
        return False


def verificar_projeto():
    """Verifica se o projeto existe"""
    print("\n📁 VERIFICANDO ESTRUTURA DO PROJETO...")
    
    if os.path.exists(PROJETO_PATH):
        print(f"  ✅ Projeto encontrado: {PROJETO_PATH}")
        
        # Listar subpastas
        subpastas = ["01_Entrada", "02_Talhoes", "03_Bordaduras", "04_Plantio", 
                    "05_Pulverizacao", "06_Relevo", "07_Analise", "08_Exportacao"]
        
        for subpasta in subpastas:
            caminho = os.path.join(PROJETO_PATH, subpasta)
            if os.path.exists(caminho):
                print(f"  ✅ {subpasta}/")
            else:
                print(f"  ❌ {subpasta}/ (NÃO ENCONTRADO)")
        
        return True
    else:
        print(f"  ❌ Projeto não encontrado: {PROJETO_PATH}")
        print(f"\n💡 O projeto será criado ao executar a Parte 1.")
        return False


def executar_configuracao_inicial():
    """Executa a configuração inicial (Parte 1)"""
    print("\n🚀 EXECUTANDO CONFIGURAÇÃO INICIAL (PARTE 1)...")
    
    try:
        from aap_part1_setup import configurar_projeto_aap
        
        resultado = configurar_projeto_aap(
            projeto_path=PROJETO_PATH,
            nome_fazenda="MinhaFazenda",
            ano="2024",
            epsg_utm="EPSG:31981"  # Zona 21S (RS/SC/PR)
        )
        
        if resultado:
            print("  ✅ Configuração inicial concluída com sucesso!")
            return True
        else:
            print("  ❌ Erro na configuração inicial")
            return False
            
    except Exception as e:
        print(f"  ❌ Erro ao executar configuração: {e}")
        return False


def criar_atalho_console():
    """Cria um arquivo de atalho para facilitar importações"""
    print("\n📝 CRIANDO ARQUIVO DE ATALHO...")
    
    atalho_path = os.path.join(SCRIPTS_PATH, "aap_import.py")
    
    atalho_conteudo = f'''"""
# AAP GIS - Atalho de Importação
# Cole este código no início de cada sessão do QGIS Console Python

import sys
sys.path.insert(0, r"{SCRIPTS_PATH}")

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

print("✅ AAP GIS carregado com sucesso!")
print("📁 Scripts disponíveis: Partes 1-13")
'''
    
    try:
        with open(atalho_path, 'w', encoding='utf-8') as f:
            f.write(atalho_conteudo)
        
        print(f"  ✅ Atalho criado: {atalho_path}")
        print(f"  💡 Use: exec(open(r'{atalho_path}').read())")
        return True
        
    except Exception as e:
        print(f"  ❌ Erro ao criar atalho: {e}")
        return False


def imprimir_instrucoes_uso():
    """Imprime instruções de uso"""
    print("\n" + "="*70)
    print("📖 INSTRUÇÕES DE USO")
    print("="*70)
    
    print("""
🎯 USO RÁPIDO:
   1. Importe o atalho no Console Python:
      exec(open(r"c:\\Users\\fortu\\Desktop\\PYTON\\aap_import.py").read())
   
   2. Execute o pipeline completo:
      executar_pipeline_completo(
          arquivo_talhao='caminho/talhao.shp',
          pasta_saida='caminho/AAP_Projeto',
          config={'cultura': 'soja', 'largura_barra_m': 30.0}
      )

📚 USO POR PARTE:
   - Parte 1: configurar_projeto_aap(projeto_path, nome_fazenda, ano)
   - Parte 2: importar_e_processar_talhao(arquivo, nome, cultura, projeto_path)
   - Parte 3: gerar_bordadura(id_talhao, largura_m, n_passadas, cultura)
   - Parte 4: gerar_linhas_plantio(id_talhao, cultura, metodo_direcao)
   - Parte 5: gerar_linhas_pulverizacao(id_talhao, largura_barra_m, sobreposicao_pct)
   - Parte 6: analisar_terreno(dem_path, id_talhao, projeto_path)
   - Parte 7: analisar_cruzamentos(id_talhao, projeto_path)
   - Parte 8: executar_pipeline_completo(arquivo_talhao, pasta_saida, config)
   - Parte 9: gerar_linhas_agronomicas(id_talhao, dem_path, cultura, estrategia)
   - Parte 10: gerar_zonas_manejo_dados(id_talhao, dem_path, modo)
   - Parte 11: analisar_conformidade_completa(id_talhao, zip_jd_path, tipo_operacao)
   - Parte 12: gerar_prescricao_isoxml_completa(zonas, produto, doses, talhao)
   - Parte 13: executar_motor_decisao(id_talhao, cultura, safra, dem_path, projeto_path)

📄 DOCUMENTAÇÃO:
   - AAP_GIS_README.md - Guia completo do sistema
   - AAP_GIS_GUIA_IMPORTACAO_MONITORES.md - Guia por monitor

🔧 CONFIGURAÇÃO ADICIONAL:
   - Verifique se o SAGA GIS está configurado no Processing Toolbox
   - Configure o CRS padrão para SIRGAS 2000 UTM (EPSG:31981 para zona 21S)
""")


def imprimir_estrutura_projeto():
    """Imprime a estrutura de pastas do projeto"""
    print("\n📁 ESTRUTURA DO PROJETO:")
    print("""
    AAP_Projeto/
    ├── 01_Entrada/        → Arquivos originais (SHP, KML, GeoJSON, DEM)
    ├── 02_Talhoes/        → Talhões processados
    ├── 03_Bordaduras/     → Polígonos de bordadura
    ├── 04_Plantio/        → Linhas de plantio
    ├── 05_Pulverizacao/   → Linhas de pulverização
    ├── 06_Relevo/         → DEM, slope, flow, curvature
    ├── 07_Analise/        → Cruzamentos e zonas
    ├── 08_Exportacao/     → Arquivos para monitores
    └── AAP_Base.gpkg      → GeoPackage com 5 camadas
""")


def imprimir_checklist_instalacao():
    """Imprime checklist de verificação"""
    print("\n" + "="*70)
    print("✅ CHECKLIST DE INSTALAÇÃO")
    print("="*70)
    
    checklist = [
        "QGIS 3.x instalado",
        "SAGA GIS configurado no Processing Toolbox",
        "Todos os 14 scripts AAP GIS presentes",
        "Python Path configurado no QGIS",
        "Estrutura de pastas criada",
        "GeoPackage AAP_Base.gpkg criado",
        "Teste de importação bem-sucedido"
    ]
    
    for item in checklist:
        print(f"  ☐ {item}")
    
    print("\n💡 Execute cada parte do sistema e marque os itens conforme avança.")


# ============================================================================
# EXECUÇÃO PRINCIPAL
# ============================================================================

def main():
    """Função principal de instalação"""
    
    print_banner()
    
    # 1. Verificar scripts
    scripts_ok = verificar_scripts()
    
    if not scripts_ok:
        print("\n⚠️  Instalação não pode continuar sem todos os scripts.")
        print("   Por favor, verifique se todos os arquivos estão no diretório correto.")
        return
    
    # 2. Configurar Python Path
    path_ok = configurar_python_path()
    
    if not path_ok:
        print("\n⚠️  Não foi possível configurar o Python Path.")
        return
    
    # 3. Verificar projeto
    projeto_existe = verificar_projeto()
    
    # 4. Criar atalho
    atalho_ok = criar_atalho_console()
    
    # 5. Executar configuração inicial (se projeto não existe)
    if not projeto_existe:
        resposta = input("\n🤔 Deseja criar o projeto agora? (s/n): ")
        if resposta.lower() == 's':
            config_ok = executar_configuracao_inicial()
            if not config_ok:
                print("\n⚠️  Configuração inicial falhou, mas pode ser executada depois.")
    else:
        resposta = input("\n🤔 Projeto já existe. Deseja reconfigurar? (s/n): ")
        if resposta.lower() == 's':
            config_ok = executar_configuracao_inicial()
    
    # 6. Imprimir instruções
    imprimir_instrucoes_uso()
    imprimir_estrutura_projeto()
    imprimir_checklist_instalacao()
    
    # 7. Mensagem final
    print("\n" + "="*70)
    print("✅ INSTALAÇÃO AAP GIS CONCLUÍDA!")
    print("="*70)
    print("""
    🎉 O Sistema AAP GIS está pronto para uso!
    
    Próximos passos:
    1. Importe o atalho no Console Python
    2. Importe seu primeiro talhão (Parte 2)
    3. Gere bordaduras e linhas (Partes 3-5)
    4. Exporte para o monitor (Parte 8)
    
    Para dúvidas, consulte AAP_GIS_README.md
    """)


# ============================================================================
# EXECUTAR INSTALAÇÃO
# ============================================================================

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Instalação cancelada pelo usuário.")
    except Exception as e:
        print(f"\n❌ Erro durante instalação: {e}")
        print("\n💡 Se o erro persistir, verifique:")
        print("   - Se o QGIS está rodando como administrador")
        print("   - Se os scripts estão no caminho correto")
        print("   - Se as dependências do QGIS estão instaladas")
