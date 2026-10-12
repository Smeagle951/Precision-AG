# -*- coding: utf-8 -*-
"""
AAP GIS - Copiar Plugin Automaticamente para Pasta do QGIS
"""

import os
import shutil

# Origem (onde está o código do plugin)
origem = r"c:\Users\fortu\Desktop\PYTON\AAP_GIS_Plugin"

# Destino (pasta de plugins do QGIS)
destino = r"C:\Users\fortu\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\AAP_GIS_Plugin"

print("="*70)
print("📦 COPIANDO PLUGIN AAP GIS")
print("="*70)

# Verificar se origem existe
if not os.path.exists(origem):
    print(f"❌ Pasta de origem não encontrada: {origem}")
    print("\n💡 Crie primeiro o plugin com:")
    print("   Plugins → Create New Plugin...")
else:
    print(f"✅ Origem encontrada: {origem}")
    print(f"   Arquivos: {os.listdir(origem)}")

    # Criar pasta destino se não existir
    os.makedirs(os.path.dirname(destino), exist_ok=True)

    # Remover instalação anterior
    if os.path.exists(destino):
        print(f"\n🗑️  Removendo instalação anterior...")
        shutil.rmtree(destino)
        print("✅ Removido")

    # Copiar pasta
    print(f"\n📤 Copiando para: {destino}")
    shutil.copytree(origem, destino)
    print("✅ Plugin copiado com sucesso!")

    # Verificar
    print(f"\n🔍 Verificando instalação...")
    arquivos = os.listdir(destino)
    for arquivo in arquivos:
        print(f"   ✅ {arquivo}")

    print("\n" + "="*70)
    print("🎉 PLUGIN INSTALADO!")
    print("="*70)
    print("\n📖 PRÓXIMOS PASSOS:")
    print("   1. Reinicie o QGIS")
    print("   2. Vá em: Plugins → Manage and Install Plugins")
    print("   3. Clique na aba 'Installed'")
    print("   4. Procure 'AAP GIS' e ative o checkbox")
    print("   5. O botão aparecerá na barra de ferramentas")
    print("\n⚡ Ou execute no Console Python:")
    print("   from qgis.utils import loadPlugin, startPlugin")
    print("   loadPlugin('AAP_GIS_Plugin')")
    print("   startPlugin('AAP_GIS_Plugin')")
