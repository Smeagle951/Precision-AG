# -*- coding: utf-8 -*-
"""
AAP GIS Plugin - Plugin Principal QGIS
"""

import sys
import os
from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QDockWidget, QVBoxLayout, QWidget, QLabel, QLineEdit, QComboBox, QPushButton, QFormLayout, QTextEdit, QProgressBar
from qgis.core import QgsProject

# Adicionar path dos scripts AAP GIS
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))


class AAPGISPlugin:
    """Plugin AAP GIS para QGIS"""
    
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.dock = None
        
    def initGui(self):
        """Inicializa a interface do plugin"""
        # Criar ação
        self.action = QAction("AAP GIS", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu("AAP GIS", self.action)
        self.iface.addToolBarIcon(self.action)
        
    def onClosePlugin(self):
        """Fecha o plugin"""
        self.iface.removePluginMenu("AAP GIS", self.action)
        self.iface.removeToolBarIcon(self.action)
        if self.dock:
            self.iface.removeDockWidget(self.dock)
            
    def run(self):
        """Executa o plugin - abre o painel"""
        if self.dock is None:
            self.dock = AAPGISDock(self.iface)
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        else:
            self.dock.show()


class AAPGISDock(QDockWidget):
    """Painel Lateral AAP GIS"""
    
    def __init__(self, iface):
        super().__init__("AAP GIS - Projetar Plantio", iface.mainWindow())
        self.iface = iface
        self.setup_ui()
        
    def setup_ui(self):
        """Configura a interface do painel"""
        # Widget principal
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Formulário
        form_layout = QFormLayout()
        
        # Talhão
        self.input_talhao = QLineEdit()
        self.input_talhao.setPlaceholderText("Selecione camada de talhão")
        btn_talhao = QPushButton("📁")
        btn_talhao.clicked.connect(self.selecionar_talhao)
        talhao_layout = QVBoxLayout()
        talhao_layout.addWidget(self.input_talhao)
        talhao_layout.addWidget(btn_talhao)
        form_layout.addRow("Talhão:", talhao_layout)
        
        # Cultura
        self.combo_cultura = QComboBox()
        self.combo_cultura.addItems(["soja", "milho", "algodao", "feijao", "sorgo"])
        form_layout.addRow("Cultura:", self.combo_cultura)
        
        # Monitor
        self.combo_monitor = QComboBox()
        self.combo_monitor.addItems(["jd2630", "jacto", "newholland", "stara"])
        form_layout.addRow("Monitor:", self.combo_monitor)
        
        # Largura barra
        self.input_largura = QLineEdit("30.0")
        form_layout.addRow("Largura Barra (m):", self.input_largura)
        
        layout.addLayout(form_layout)
        
        # Botão executar
        self.btn_executar = QPushButton("🚀 EXECUTAR PROJETO")
        self.btn_executar.setStyleSheet("""
            QPushButton {
                background-color: #2ecc71;
                color: white;
                font-weight: bold;
                padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #27ae60;
            }
        """)
        self.btn_executar.clicked.connect(self.executar_projeto)
        layout.addWidget(self.btn_executar)
        
        # Progress bar
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        
        # Área de resultado
        self.txt_resultado = QTextEdit()
        self.txt_resultado.setReadOnly(True)
        self.txt_resultado.setMaximumHeight(200)
        layout.addWidget(QLabel("Resultado:"))
        layout.addWidget(self.txt_resultado)
        
        layout.addStretch()
        widget.setLayout(layout)
        self.setWidget(widget)
        
    def selecionar_talhao(self):
        """Seleciona camada de talhão do QGIS"""
        layers = [layer.name() for layer in QgsProject.instance().mapLayers().values() 
                 if layer.type() == layer.VectorLayer]
        
        if layers:
            self.input_talhao.setText(layers[0])
            self.txt_resultado.append(f"✅ Camada selecionada: {layers[0]}")
        else:
            self.txt_resultado.append("❌ Nenhuma camada vetorial encontrada")
    
    def executar_projeto(self):
        """Executa o projeto de plantio"""
        try:
            self.txt_resultado.clear()
            self.progress.setVisible(True)
            self.progress.setValue(10)
            
            # Obter valores
            talhao_nome = self.input_talhao.text()
            cultura = self.combo_cultura.currentText()
            monitor = self.combo_monitor.currentText()
            largura = float(self.input_largura.text())
            
            self.txt_resultado.append("🚀 Iniciando projeto de plantio...")
            self.txt_resultado.append(f"   Talhão: {talhao_nome}")
            self.txt_resultado.append(f"   Cultura: {cultura}")
            self.txt_resultado.append(f"   Monitor: {monitor}")
            self.txt_resultado.append(f"   Largura: {largura}m")
            
            self.progress.setValue(30)
            
            # Importar API simples
            from aap_simple_api import criar_projeto_plantio
            
            # Buscar camada
            talhao_layer = QgsProject.instance().mapLayersByName(talhao_nome)
            if not talhao_layer:
                self.txt_resultado.append("❌ Camada não encontrada")
                self.progress.setValue(0)
                return
            
            # Salvar temporariamente
            temp_path = os.path.join(os.path.expanduser("~"), "temp_talhao.shp")
            from qgis.core import QgsVectorFileWriter
            QgsVectorFileWriter.writeAsVectorFormat(
                talhao_layer[0],
                temp_path,
                "UTF-8",
                talhao_layer[0].crrs(),
                "ESRI Shapefile"
            )
            
            self.progress.setValue(50)
            
            # Executar
            projeto_path = os.path.join(os.path.expanduser("~"), "AAP_Projeto")
            resultado = criar_projeto_plantio(
                arquivo_talhao=temp_path,
                cultura=cultura,
                maquina=monitor,
                largura_barra_m=largura,
                projeto_path=projeto_path
            )
            
            self.progress.setValue(80)
            
            if resultado['sucesso']:
                self.txt_resultado.append("\n✅ PROJETO CRIADO COM SUCESSO!")
                dados = resultado['dados']
                self.txt_resultado.append(f"   Área: {dados.get('area_ha', 0):.2f} ha")
                self.txt_resultado.append(f"   Linhas plantio: {dados.get('linhas_plantio', 0)}")
                self.txt_resultado.append(f"   Linhas pulverização: {dados.get('linhas_pulverizacao', 0)}")
                
                decisao = dados.get('decisao_automatica', {})
                self.txt_resultado.append("\n🎯 Decisão Automática:")
                for chave, valor in decisao.items():
                    self.txt_resultado.append(f"   {chave}: {valor}")
            else:
                self.txt_resultado.append(f"\n❌ Erro: {resultado['mensagem']}")
            
            self.progress.setValue(100)
            
        except Exception as e:
            self.txt_resultado.append(f"❌ Erro: {str(e)}")
            self.progress.setValue(0)
