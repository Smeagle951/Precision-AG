# -*- coding: utf-8 -*-
"""
AAP GIS - Botão na Barra de Ferramentas do QGIS

Execute este script no Console Python do QGIS (Ctrl+Alt+P).
Cria um botão "AAP GIS" na barra de ferramentas.
"""

from qgis.PyQt.QtWidgets import (
    QAction, QDialog, QVBoxLayout, QFormLayout, 
    QComboBox, QLineEdit, QPushButton, QLabel,
    QFileDialog, QMessageBox, QProgressBar, QTextEdit
)
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject, QgsVectorLayer, QgsMessageLog, Qgis
import os
import sys

# Adicionar path
sys.path.insert(0, r"c:\Users\fortu\Desktop\PYTON")

# Verificar se já existe ação
if '_aap_action' in globals():
    try:
        iface.removeToolBarIcon(_aap_action)
        print("Botão anterior removido")
    except:
        pass

def abrir_dialogo_aap():
    """Abre a janela do AAP GIS"""
    dialog = QDialog(iface.mainWindow())
    dialog.setWindowTitle("AAP GIS - Projetar Plantio")
    dialog.setMinimumWidth(400)
    
    layout = QVBoxLayout()
    
    # Título
    titulo = QLabel("<h2>AAP GIS v2.1</h2><p>Sistema de Agricultura de Precisão</p>")
    layout.addWidget(titulo)
    
    # Formulário
    form = QFormLayout()
    
    # Cultura
    combo_cultura = QComboBox()
    combo_cultura.addItems(["soja", "milho", "algodao", "feijao", "sorgo"])
    form.addRow("Cultura:", combo_cultura)
    
    # Monitor
    combo_monitor = QComboBox()
    combo_monitor.addItems(["jd2630", "jacto", "newholland", "stara", "padrao"])
    form.addRow("Monitor:", combo_monitor)
    
    # Largura barra
    input_largura = QLineEdit("30.0")
    form.addRow("Largura Barra (m):", input_largura)
    
    layout.addLayout(form)
    
    # Área de log
    log = QTextEdit()
    log.setReadOnly(True)
    log.setMaximumHeight(150)
    layout.addWidget(QLabel("Log:"))
    layout.addWidget(log)
    
    # Barra de progresso
    progress = QProgressBar()
    progress.setVisible(False)
    layout.addWidget(progress)
    
    def executar():
        try:
            log.clear()
            progress.setVisible(True)
            progress.setValue(10)
            
            cultura = combo_cultura.currentText()
            monitor = combo_monitor.currentText()
            largura = float(input_largura.text())
            
            log.append(f"Cultura: {cultura}")
            log.append(f"Monitor: {monitor}")
            log.append(f"Largura: {largura}m")
            
            # Importar e executar
            progress.setValue(30)
            from aap_simple_api import criar_projeto_plantio
            
            log.append("Importando módulos...")
            progress.setValue(50)
            
            # Buscar talhão do projeto
            layers = [l for l in QgsProject.instance().mapLayers().values() 
                     if isinstance(l, QgsVectorLayer) and l.geometryType() == 2]
            
            if not layers:
                QMessageBox.warning(dialog, "Aviso", 
                    "Nenhum talhão encontrado no projeto.\n"
                    "Importe um talhão primeiro (Parte 2).")
                progress.setVisible(False)
                return
            
            talhao = layers[0]
            log.append(f"Talhão: {talhao.name()}")
            progress.setValue(70)
            
            log.append("Executando projeto...")
            resultado = criar_projeto_plantio(
                arquivo_talhao=talhao.source(),
                cultura=cultura,
                maquina=monitor,
                largura_barra_m=largura
            )
            
            progress.setValue(100)
            
            if resultado and resultado.get('sucesso'):
                dados = resultado['dados']
                log.append(f"\n✅ PROJETO CRIADO!")
                log.append(f"Área: {dados.get('area_ha', 0):.2f} ha")
                log.append(f"Linhas plantio: {dados.get('linhas_plantio', 0)}")
                log.append(f"Status: {dados.get('status', 'OK')}")
                QMessageBox.information(dialog, "Sucesso", 
                    f"Projeto criado com sucesso!\n"
                    f"Área: {dados.get('area_ha', 0):.2f} ha\n"
                    f"Verifique as camadas no QGIS.")
            else:
                log.append(f"\n❌ Erro: {resultado.get('mensagem', 'Desconhecido')}")
                QMessageBox.critical(dialog, "Erro", 
                    f"Falha ao criar projeto:\n{resultado.get('mensagem', 'Erro desconhecido')}")
            
        except Exception as e:
            log.append(f"\n❌ Erro: {str(e)}")
            QMessageBox.critical(dialog, "Erro", str(e))
        finally:
            progress.setVisible(False)
    
    # Botão executar
    btn_executar = QPushButton("🚀 EXECUTAR PROJETO")
    btn_executar.setStyleSheet("""
        QPushButton {
            background-color: #27ae60;
            color: white;
            font-weight: bold;
            padding: 15px;
            font-size: 14px;
            border-radius: 5px;
        }
        QPushButton:hover {
            background-color: #2ecc71;
        }
    """)
    btn_executar.clicked.connect(executar)
    layout.addWidget(btn_executar)
    
    # Botão fechar
    btn_fechar = QPushButton("Fechar")
    btn_fechar.clicked.connect(dialog.close)
    layout.addWidget(btn_fechar)
    
    dialog.setLayout(layout)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()

# Criar ação
_aap_action = QAction("AAP GIS", iface.mainWindow())
_aap_action.triggered.connect(abrir_dialogo_aap)

# Adicionar à barra de ferramentas
iface.addToolBarIcon(_aap_action)

print("="*60)
print("✅ BOTÃO AAP GIS CRIADO!")
print("="*60)
print("Botão 'AAP GIS' adicionado à barra de ferramentas")
print("Clique no botão para abrir a interface")
print("="*60)
