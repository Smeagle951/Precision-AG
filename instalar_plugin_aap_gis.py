# -*- coding: utf-8 -*-
"""
AAP GIS - Instalador Automático de Plugin

Este script instala automaticamente o plugin AAP GIS no QGIS.
Execute no Console Python do QGIS (Ctrl+Alt+P).
"""

import os
import sys
import shutil

# ============================================================================
# CONFIGURAÇÕES
# ============================================================================

# Origem do plugin (onde está o código fonte)
PLUGIN_ORIGEM = r"c:\Users\fortu\Desktop\PYTON\AAP_GIS_Plugin"

# Destino do plugin (pasta de plugins do QGIS)
# Detectado automaticamente abaixo

# ============================================================================
# FUNÇÕES
# ============================================================================

def detectar_pasta_plugins():
    """Detecta automaticamente a pasta de plugins do QGIS"""
    # Tentar múltiplos caminhos comuns
    caminhos_possiveis = [
        os.path.expanduser(r"~\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins"),
        os.path.expanduser(r"~\.local\share\QGIS\QGIS3\profiles\default\python\plugins"),
        os.path.join(os.environ.get('LOCALAPPDATA', ''), r"QGIS\QGIS3\profiles\default\python\plugins"),
        os.path.join(os.environ.get('APPDATA', ''), r"QGIS\QGIS3\profiles\default\python\plugins"),
    ]
    
    # Tentar detectar via QGIS
    try:
        from qgis.core import QgsApplication
        qgis_plugins_path = os.path.join(QgsApplication.qgisSettingsDirPath(), 'python', 'plugins')
        caminhos_possiveis.insert(0, qgis_plugins_path)
    except:
        pass
    
    for caminho in caminhos_possiveis:
        if os.path.exists(caminho):
            print(f"✅ Pasta de plugins encontrada: {caminho}")
            return caminho
    
    # Se não encontrou, criar no primeiro caminho
    primeiro_caminho = caminhos_possiveis[0]
    os.makedirs(primeiro_caminho, exist_ok=True)
    print(f"📁 Pasta de plugins criada: {primeiro_caminho}")
    return primeiro_caminho


def verificar_plugin_origem():
    """Verifica se a pasta de origem do plugin existe"""
    if not os.path.exists(PLUGIN_ORIGEM):
        print(f"❌ Pasta de origem não encontrada: {PLUGIN_ORIGEM}")
        return False
    
    arquivos_necessarios = ['__init__.py', 'metadata.txt', 'aap_plugin.py']
    for arquivo in arquivos_necessarios:
        caminho = os.path.join(PLUGIN_ORIGEM, arquivo)
        if not os.path.exists(caminho):
            print(f"❌ Arquivo faltando: {arquivo}")
            return False
        print(f"✅ Arquivo encontrado: {arquivo}")
    
    return True


def instalar_plugin():
    """Instala o plugin na pasta de plugins do QGIS"""
    print("="*70)
    print("🚀 INSTALADOR AAP GIS")
    print("="*70)
    
    # 1. Verificar origem
    print("\n🔍 Verificando plugin de origem...")
    if not verificar_plugin_origem():
        print("❌ Plugin de origem incompleto. Abortando.")
        return False
    
    # 2. Detectar pasta de plugins
    print("\n🔍 Detectando pasta de plugins do QGIS...")
    plugins_path = detectar_pasta_plugins()
    
    # 3. Definir destino
    destino = os.path.join(plugins_path, "AAP_GIS_Plugin")
    
    # 4. Remover instalação anterior se existir
    if os.path.exists(destino):
        print(f"\n🗑️  Removendo instalação anterior...")
        try:
            shutil.rmtree(destino)
            print("✅ Instalação anterior removida")
        except Exception as e:
            print(f"⚠️  Erro ao remover: {e}")
    
    # 5. Copiar plugin
    print(f"\n📦 Copiando plugin para: {destino}")
    try:
        shutil.copytree(PLUGIN_ORIGEM, destino)
        print("✅ Plugin copiado com sucesso")
    except Exception as e:
        print(f"❌ Erro ao copiar: {e}")
        return False
    
    # 6. Verificar instalação
    print("\n🔍 Verificando instalação...")
    arquivos = os.listdir(destino)
    print(f"📁 Arquivos instalados: {', '.join(arquivos)}")
    
    # 7. Ativar plugin no QGIS (sem reiniciar)
    print("\n⚡ Ativando plugin no QGIS...")
    try:
        from qgis.core import QgsApplication
        from qgis.utils import loadPlugin, startPlugin, plugins
        
        # Recarregar lista de plugins
        QgsApplication.pluginRegistry().checkCorePlugins()
        
        # Carregar e iniciar plugin
        if loadPlugin("AAP_GIS_Plugin"):
            startPlugin("AAP_GIS_Plugin")
            print("✅ Plugin ativado no QGIS!")
            print("\n🎉 AAP GIS está pronto para usar!")
            print("   Procure no menu: Plugins → AAP GIS")
            print("   Ou clique no ícone na barra de ferramentas")
        else:
            print("⚠️  Plugin carregado, mas pode precisar reiniciar o QGIS")
    except Exception as e:
        print(f"⚠️  Não foi possível ativar automaticamente: {e}")
        print("   Reinicie o QGIS para usar o plugin")
    
    print("\n" + "="*70)
    return True


# ============================================================================
# EXECUÇÃO
# ============================================================================

if __name__ == "__main__":
    sucesso = instalar_plugin()
    
    if sucesso:
        print("\n✅ INSTALAÇÃO CONCLUÍDA")
        print("\n📖 PRÓXIMOS PASSOS:")
        print("   1. Se o plugin não aparecer, reinicie o QGIS")
        print("   2. Vá em: Plugins → Manage and Install Plugins")
        print("   3. Procure por 'AAP GIS' na aba 'Installed'")
        print("   4. Ative o checkbox se estiver desativado")
        print("   5. O botão aparecerá na barra de ferramentas")
    else:
        print("\n❌ INSTALAÇÃO FALHOU")
        print("\n💡 Verifique:")
        print("   - Se a pasta AAP_GIS_Plugin existe em:")
        print(f"     {PLUGIN_ORIGEM}")
        print("   - Se você tem permissão de escrita em:")
        print(f"     {detectar_pasta_plugins()}")
