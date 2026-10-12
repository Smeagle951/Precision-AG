# -*- coding: utf-8 -*-
"""
AAP GIS - Interface Completa Profissional
Painel completo com TODAS as opções do sistema
"""

from qgis.PyQt.QtWidgets import (
    QAction, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, 
    QComboBox, QLineEdit, QPushButton, QLabel, QTabWidget,
    QWidget, QGroupBox, QSpinBox, QDoubleSpinBox, QCheckBox,
    QFileDialog, QMessageBox, QProgressBar, QTextEdit, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
    QRadioButton, QButtonGroup, QSlider, QGridLayout
)
from qgis.PyQt.QtGui import QFont, QColor
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject, QgsVectorLayer, QgsRasterLayer
import sys
import os

sys.path.insert(0, r"c:\Users\fortu\Desktop\PYTON")


def criar_interface_aap_gis():
    """Cria a interface completa do AAP GIS"""
    
    dialog = QDialog(iface.mainWindow())
    dialog.setWindowTitle("AAP GIS v2.1 - Sistema Completo de Agricultura de Precisão")
    dialog.setMinimumSize(900, 700)
    
    layout = QVBoxLayout()
    
    # === TÍTULO ===
    titulo = QLabel("🌾 AAP GIS - Agricultura de Precisão Avançada")
    titulo_font = QFont("Arial", 16, QFont.Bold)
    titulo.setFont(titulo_font)
    titulo.setAlignment(Qt.AlignCenter)
    titulo.setStyleSheet("color: #2c3e50; padding: 10px;")
    layout.addWidget(titulo)
    
    # === ABAS ===
    tabs = QTabWidget()
    
    # ==================== ABA 1: PROJETO ====================
    tab_projeto = QWidget()
    layout_proj = QVBoxLayout()
    
    # Grupo: Configuração do Projeto
    grp_proj = QGroupBox("📁 Configuração do Projeto")
    form_proj = QFormLayout()
    
    inp_nome_fazenda = QLineEdit("Minha Fazenda")
    inp_ano = QLineEdit("2024")
    inp_epsg = QComboBox()
    inp_epsg.addItems(["31981 - UTM 21S (RS/SC/PR)", "31982 - UTM 22S (SP/MG)", "31983 - UTM 23S (BA)", "32718 - UTM 18S", "4326 - WGS84"])
    inp_projeto_path = QLineEdit()
    btn_proj_path = QPushButton("📁...")
    
    path_layout = QHBoxLayout()
    path_layout.addWidget(inp_projeto_path)
    path_layout.addWidget(btn_proj_path)
    
    form_proj.addRow("Nome da Fazenda:", inp_nome_fazenda)
    form_proj.addRow("Ano/Safra:", inp_ano)
    form_proj.addRow("Sistema de Coordenadas:", inp_epsg)
    form_proj.addRow("Pasta do Projeto:", path_layout)
    
    grp_proj.setLayout(form_proj)
    layout_proj.addWidget(grp_proj)
    
    # Botão Criar Projeto
    btn_criar_proj = QPushButton("🚀 CRIAR NOVO PROJETO")
    btn_criar_proj.setStyleSheet("""
        QPushButton {
            background-color: #3498db; color: white;
            font-weight: bold; padding: 15px;
            font-size: 14px; border-radius: 5px;
        }
        QPushButton:hover { background-color: #2980b9; }
    """)
    layout_proj.addWidget(btn_criar_proj)
    
    layout_proj.addStretch()
    tab_projeto.setLayout(layout_proj)
    tabs.addTab(tab_projeto, "📁 Projeto")
    
    # ==================== ABA 2: IMPORTAR ====================
    tab_import = QWidget()
    layout_imp = QVBoxLayout()
    
    grp_imp = QGroupBox("📥 Importar Talhão e DEM")
    form_imp = QFormLayout()
    
    # Talhão
    inp_talhao_arq = QLineEdit()
    btn_talhao_arq = QPushButton("📁 Selecionar Talhão (SHP/KML/GeoJSON)")
    talhao_layout = QHBoxLayout()
    talhao_layout.addWidget(inp_talhao_arq)
    talhao_layout.addWidget(btn_talhao_arq)
    form_imp.addRow("Arquivo do Talhão:", talhao_layout)
    
    # Nome do talhão
    inp_nome_talhao = QLineEdit("Talhao_01")
    form_imp.addRow("Nome do Talhão:", inp_nome_talhao)
    
    # DEM
    inp_dem_arq = QLineEdit()
    btn_dem_arq = QPushButton("📁 Selecionar DEM (GeoTIFF)")
    dem_layout = QHBoxLayout()
    dem_layout.addWidget(inp_dem_arq)
    dem_layout.addWidget(btn_dem_arq)
    form_imp.addRow("Arquivo DEM:", dem_layout)
    
    # Opções de importação
    chk_limpar = QCheckBox("Limpar geometria (auto-correção)")
    chk_limpar.setChecked(True)
    chk_simplificar = QCheckBox("Simplificar vértices (< 1cm)")
    chk_simplificar.setChecked(True)
    chk_buffer = QCheckBox("Criar buffer de correção (1cm)")
    chk_buffer.setChecked(True)
    
    form_imp.addRow("", chk_limpar)
    form_imp.addRow("", chk_simplificar)
    form_imp.addRow("", chk_buffer)
    
    grp_imp.setLayout(form_imp)
    layout_imp.addWidget(grp_imp)
    
    btn_importar = QPushButton("📥 IMPORTAR TALHÃO E DEM")
    btn_importar.setStyleSheet("""
        QPushButton {
            background-color: #e67e22; color: white;
            font-weight: bold; padding: 12px;
            font-size: 13px; border-radius: 5px;
        }
        QPushButton:hover { background-color: #d35400; }
    """)
    layout_imp.addWidget(btn_importar)
    
    layout_imp.addStretch()
    tab_import.setLayout(layout_imp)
    tabs.addTab(tab_import, "📥 Importar")
    
    # ==================== ABA 3: BORDADURA ====================
    tab_bord = QWidget()
    layout_bord = QVBoxLayout()
    
    grp_bord = QGroupBox("🚜 Configurar Bordadura")
    form_bord = QFormLayout()
    
    # Selecionar talhão
    combo_talhao_bord = QComboBox()
    combo_talhao_bord.addItem("Selecionar talhão importado...")
    form_bord.addRow("Talhão:", combo_talhao_bord)
    
    # Cultura
    combo_cultura_bord = QComboBox()
    combo_cultura_bord.addItems(["soja", "milho", "algodao", "feijao", "sorgo", "trigo", "aveia", "canola"])
    form_bord.addRow("Cultura:", combo_cultura_bord)
    
    # Largura bordadura
    spin_largura_bord = QDoubleSpinBox()
    spin_largura_bord.setRange(0, 50)
    spin_largura_bord.setValue(9.0)
    spin_largura_bord.setDecimals(1)
    spin_largura_bord.setSuffix(" m")
    form_bord.addRow("Largura da Bordadura:", spin_largura_bord)
    
    # Número de passadas
    spin_passadas_bord = QSpinBox()
    spin_passadas_bord.setRange(1, 10)
    spin_passadas_bord.setValue(2)
    form_bord.addRow("Número de Passadas:", spin_passadas_bord)
    
    # Método de geração
    grp_metodo_bord = QGroupBox("Método de Geração")
    lay_met_bord = QVBoxLayout()
    
    rd_bord_interna = QRadioButton("Interna (padrão)")
    rd_bord_interna.setChecked(True)
    rd_bord_externa = QRadioButton("Externa (proteção de APP)")
    rd_bord_externa.setToolTip("Usar para área de preservação permanente")
    rd_bord_por_lado = QRadioButton("Por lado (N/S/L/O individual)")
    
    lay_met_bord.addWidget(rd_bord_interna)
    lay_met_bord.addWidget(rd_bord_externa)
    lay_met_bord.addWidget(rd_bord_por_lado)
    grp_metodo_bord.setLayout(lay_met_bord)
    
    form_bord.addRow("", grp_metodo_bord)
    
    # Máquinas disponíveis
    grp_maqs = QGroupBox("Maquinário (para cálculo automático)")
    lay_maqs = QGridLayout()
    
    maqs = [
        ("Trator + Plantadeira", 9.0),
        ("Pulverizador 30m", 30.0),
        ("Pulverizador 24m", 24.0),
        ("Colheitadeira", 7.0),
        ("Vagão", 30.0),
        ("Customizado", 0.0)
    ]
    
    for i, (nome, larg) in enumerate(maqs):
        chk = QCheckBox(nome)
        spin = QDoubleSpinBox()
        spin.setRange(1, 100)
        spin.setValue(larg)
        spin.setSuffix(" m")
        lay_maqs.addWidget(chk, i, 0)
        lay_maqs.addWidget(spin, i, 1)
    
    grp_maqs.setLayout(lay_maqs)
    form_bord.addRow("", grp_maqs)
    
    grp_bord.setLayout(form_bord)
    layout_bord.addWidget(grp_bord)
    
    btn_gerar_bord = QPushButton("🚜 GERAR BORDADURA")
    btn_gerar_bord.setStyleSheet("""
        QPushButton {
            background-color: #9b59b6; color: white;
            font-weight: bold; padding: 12px;
            font-size: 13px; border-radius: 5px;
        }
        QPushButton:hover { background-color: #8e44ad; }
    """)
    layout_bord.addWidget(btn_gerar_bord)
    
    layout_bord.addStretch()
    tab_bord.setLayout(layout_bord)
    tabs.addTab(tab_bord, "🚜 Bordadura")
    
    # ==================== ABA 4: PLANTIO ====================
    tab_plant = QWidget()
    layout_plant = QVBoxLayout()
    
    grp_plant = QGroupBox("🌱 Configurar Linhas de Plantio")
    form_plant = QFormLayout()
    
    # Talhão
    combo_talhao_plant = QComboBox()
    combo_talhao_plant.addItem("Selecionar talhão...")
    form_plant.addRow("Talhão:", combo_talhao_plant)
    
    # Cultura
    combo_cultura_plant = QComboBox()
    combo_cultura_plant.addItems(["soja", "milho", "algodao", "feijao", "sorgo", "trigo"])
    form_plant.addRow("Cultura:", combo_cultura_plant)
    
    # Espaçamento
    spin_espac = QDoubleSpinBox()
    spin_espac.setRange(0.1, 2.0)
    spin_espac.setValue(0.5)
    spin_espac.setDecimals(2)
    spin_espac.setSuffix(" m")
    form_plant.addRow("Espaçamento entre Linhas:", spin_espac)
    
    # Método de direção
    grp_dir = QGroupBox("Direção das Linhas")
    lay_dir = QVBoxLayout()
    
    rd_dir_auto = QRadioButton("Automático (eixo principal do talhão)")
    rd_dir_auto.setChecked(True)
    rd_dir_ab = QRadioButton("Linha AB (selecionar 2 pontos)")
    rd_dir_azim = QRadioButton("Azimute específico")
    spin_azim = QDoubleSpinBox()
    spin_azim.setRange(0, 360)
    spin_azim.setValue(45)
    spin_azim.setSuffix("°")
    spin_azim.setEnabled(False)
    rd_dir_curv = QRadioButton("Curvas de nível (terreno)")
    rd_dir_adapt = QRadioButton("Adaptativo (ótimo agronômico)")
    
    lay_dir.addWidget(rd_dir_auto)
    lay_dir.addWidget(rd_dir_ab)
    azim_layout = QHBoxLayout()
    azim_layout.addWidget(rd_dir_azim)
    azim_layout.addWidget(spin_azim)
    lay_dir.addLayout(azim_layout)
    lay_dir.addWidget(rd_dir_curv)
    lay_dir.addWidget(rd_dir_adapt)
    
    grp_dir.setLayout(lay_dir)
    form_plant.addRow("", grp_dir)
    
    # Opções avançadas
    grp_adv_plant = QGroupBox("Opções Avançadas")
    lay_adv = QFormLayout()
    
    chk_usar_bordadura = QCheckBox("Usar área útil (com bordadura)")
    chk_usar_bordadura.setChecked(True)
    chk_curvas_nivel = QCheckBox("Respeitar curvas de nível (slope > 5°)")
    chk_angulo_otimo = QCheckBox("Calcular ângulo ótimo agronômico")
    chk_angulo_otimo.setChecked(True)
    
    lay_adv.addRow("", chk_usar_bordadura)
    lay_adv.addRow("", chk_curvas_nivel)
    lay_adv.addRow("", chk_angulo_otimo)
    
    grp_adv_plant.setLayout(lay_adv)
    form_plant.addRow("", grp_adv_plant)
    
    grp_plant.setLayout(form_plant)
    layout_plant.addWidget(grp_plant)
    
    btn_gerar_plant = QPushButton("🌱 GERAR LINHAS DE PLANTIO")
    btn_gerar_plant.setStyleSheet("""
        QPushButton {
            background-color: #27ae60; color: white;
            font-weight: bold; padding: 12px;
            font-size: 13px; border-radius: 5px;
        }
        QPushButton:hover { background-color: #229954; }
    """)
    layout_plant.addWidget(btn_gerar_plant)
    
    layout_plant.addStretch()
    tab_plant.setLayout(layout_plant)
    tabs.addTab(tab_plant, "🌱 Plantio")
    
    # ==================== ABA 5: PULVERIZACAO ====================
    tab_pulv = QWidget()
    layout_pulv = QVBoxLayout()
    
    grp_pulv = QGroupBox("💨 Configurar Linhas de Pulverização")
    form_pulv = QFormLayout()
    
    combo_talhao_pulv = QComboBox()
    combo_talhao_pulv.addItem("Selecionar talhão...")
    form_pulv.addRow("Talhão:", combo_talhao_pulv)
    
    combo_cultura_pulv = QComboBox()
    combo_cultura_pulv.addItems(["soja", "milho", "algodao", "feijao", "sorgo", "cafe", "citros", "horti"])
    form_pulv.addRow("Cultura:", combo_cultura_pulv)
    
    spin_larg_pulv = QDoubleSpinBox()
    spin_larg_pulv.setRange(1, 50)
    spin_larg_pulv.setValue(30.0)
    spin_larg_pulv.setDecimals(1)
    spin_larg_pulv.setSuffix(" m")
    form_pulv.addRow("Largura da Barra:", spin_larg_pulv)
    
    spin_sobrep = QDoubleSpinBox()
    spin_sobrep.setRange(0, 50)
    spin_sobrep.setValue(10.0)
    spin_sobrep.setSuffix(" %")
    form_pulv.addRow("Sobreposição:", spin_sobrep)
    
    chk_alinhar_plantio = QCheckBox("Alinhar com linhas de plantio")
    chk_alinhar_plantio.setChecked(True)
    form_pulv.addRow("", chk_alinhar_plantio)
    
    # Tipo de aplicação
    grp_tipo_aplic = QGroupBox("Tipo de Aplicação")
    lay_tipo = QVBoxLayout()
    rd_herbicida = QRadioButton("Herbicida")
    rd_herbicida.setChecked(True)
    rd_inseticida = QRadioButton("Inseticida")
    rd_fungicida = QRadioButton("Fungicida")
    rd_fertirrig = QRadioButton("Fertirrigação")
    rd_organico = QRadioButton("Aplicação Orgânica")
    
    lay_tipo.addWidget(rd_herbicida)
    lay_tipo.addWidget(rd_inseticida)
    lay_tipo.addWidget(rd_fungicida)
    lay_tipo.addWidget(rd_fertirrig)
    lay_tipo.addWidget(rd_organico)
    grp_tipo_aplic.setLayout(lay_tipo)
    form_pulv.addRow("", grp_tipo_aplic)
    
    grp_pulv.setLayout(form_pulv)
    layout_pulv.addWidget(grp_pulv)
    
    btn_gerar_pulv = QPushButton("💨 GERAR LINHAS DE PULVERIZAÇÃO")
    btn_gerar_pulv.setStyleSheet("""
        QPushButton {
            background-color: #3498db; color: white;
            font-weight: bold; padding: 12px;
            font-size: 13px; border-radius: 5px;
        }
        QPushButton:hover { background-color: #2980b9; }
    """)
    layout_pulv.addWidget(btn_gerar_pulv)
    
    layout_pulv.addStretch()
    tab_pulv.setLayout(layout_pulv)
    tabs.addTab(tab_pulv, "💨 Pulverização")
    
    # ==================== ABA 6: RELEVO ====================
    tab_rel = QWidget()
    layout_rel = QVBoxLayout()
    
    grp_rel = QGroupBox("🏔️ Análise de Relevo (SAGA GIS)")
    form_rel = QFormLayout()
    
    combo_dem = QComboBox()
    combo_dem.addItem("Selecionar DEM...")
    form_rel.addRow("Camada DEM:", combo_dem)
    
    # Análises disponíveis
    grp_analises = QGroupBox("Análises a Executar")
    lay_anal = QVBoxLayout()
    
    chk_slope = QCheckBox("Slope (Declividade em graus)")
    chk_slope.setChecked(True)
    chk_aspect = QCheckBox("Aspect (Exposição)")
    chk_aspect.setChecked(True)
    chk_curv = QCheckBox("Curvatura")
    chk_curv.setChecked(True)
    chk_flow = QCheckBox("Flow Accumulation (Acúmulo de fluxo)")
    chk_flow.setChecked(True)
    chk_twi = QCheckBox("TWI (Topographic Wetness Index)")
    chk_twi.setChecked(True)
    chk_rugosity = QCheckBox("Rugosidade")
    chk_rugosity.setChecked(True)
    
    lay_anal.addWidget(chk_slope)
    lay_anal.addWidget(chk_aspect)
    lay_anal.addWidget(chk_curv)
    lay_anal.addWidget(chk_flow)
    lay_anal.addWidget(chk_twi)
    lay_anal.addWidget(chk_rugosity)
    
    grp_analises.setLayout(lay_anal)
    form_rel.addRow("", grp_analises)
    
    # Resolução
    spin_res = QDoubleSpinBox()
    spin_res.setRange(1, 50)
    spin_res.setValue(10)
    spin_res.setSuffix(" m")
    form_rel.addRow("Resolução do Raster:", spin_res)
    
    grp_rel.setLayout(form_rel)
    layout_rel.addWidget(grp_rel)
    
    btn_analisar_rel = QPushButton("🏔️ ANALISAR RELEVO")
    btn_analisar_rel.setStyleSheet("""
        QPushButton {
            background-color: #7f8c8d; color: white;
            font-weight: bold; padding: 12px;
            font-size: 13px; border-radius: 5px;
        }
        QPushButton:hover { background-color: #636e72; }
    """)
    layout_rel.addWidget(btn_analisar_rel)
    
    layout_rel.addStretch()
    tab_rel.setLayout(layout_rel)
    tabs.addTab(tab_rel, "🏔️ Relevo")
    
    # ==================== ABA 7: ZONAS ====================
    tab_zonas = QWidget()
    layout_zonas = QVBoxLayout()
    
    grp_zonas = QGroupBox("🗺️ Zonas de Manejo")
    form_zonas = QFormLayout()
    
    combo_talhao_zonas = QComboBox()
    combo_talhao_zonas.addItem("Selecionar talhão...")
    form_zonas.addRow("Talhão:", combo_talhao_zonas)
    
    # Método
    grp_met_zonas = QGroupBox("Método de Geração")
    lay_met_z = QVBoxLayout()
    
    rd_zonas_auto = QRadioButton("Automático (baseado em dados disponíveis)")
    rd_zonas_auto.setChecked(True)
    rd_zonas_terreno = QRadioButton("Terreno apenas (sem dados históricos)")
    rd_zonas_prod = QRadioButton("Com produtividade (colheitadeira)")
    rd_zonas_kmeans = QRadioButton("K-Means (produtividade + NDVI + solo)")
    
    lay_met_z.addWidget(rd_zonas_auto)
    lay_met_z.addWidget(rd_zonas_terreno)
    lay_met_z.addWidget(rd_zonas_prod)
    lay_met_z.addWidget(rd_zonas_kmeans)
    grp_met_zonas.setLayout(lay_met_z)
    form_zonas.addRow("", grp_met_zonas)
    
    # Número de zonas
    spin_n_zonas = QSpinBox()
    spin_n_zonas.setRange(2, 10)
    spin_n_zonas.setValue(3)
    form_zonas.addRow("Número de Zonas:", spin_n_zonas)
    
    # Dados adicionais
    grp_dados_z = QGroupBox("Dados Adicionais (opcional)")
    lay_dados = QFormLayout()
    
    inp_prod = QLineEdit()
    btn_prod = QPushButton("📁")
    lay_prod = QHBoxLayout()
    lay_prod.addWidget(inp_prod)
    lay_prod.addWidget(btn_prod)
    lay_dados.addRow("Mapa de Produtividade:", lay_prod)
    
    inp_ndvi = QLineEdit()
    btn_ndvi = QPushButton("📁")
    lay_ndvi = QHBoxLayout()
    lay_ndvi.addWidget(inp_ndvi)
    lay_ndvi.addWidget(btn_ndvi)
    lay_dados.addRow("NDVI (Série Temporal):", lay_ndvi)
    
    inp_solo = QLineEdit()
    btn_solo = QPushButton("📁")
    lay_solo = QHBoxLayout()
    lay_solo.addWidget(inp_solo)
    lay_solo.addWidget(btn_solo)
    lay_dados.addRow("Análise de Solo:", lay_solo)
    
    grp_dados_z.setLayout(lay_dados)
    form_zonas.addRow("", grp_dados_z)
    
    grp_zonas.setLayout(form_zonas)
    layout_zonas.addWidget(grp_zonas)
    
    btn_gerar_zonas = QPushButton("🗺️ GERAR ZONAS DE MANEJO")
    btn_gerar_zonas.setStyleSheet("""
        QPushButton {
            background-color: #f39c12; color: white;
            font-weight: bold; padding: 12px;
            font-size: 13px; border-radius: 5px;
        }
        QPushButton:hover { background-color: #e67e22; }
    """)
    layout_zonas.addWidget(btn_gerar_zonas)
    
    layout_zonas.addStretch()
    tab_zonas.setLayout(layout_zonas)
    tabs.addTab(tab_zonas, "🗺️ Zonas")
    
    # ==================== ABA 8: EXPORTAR ====================
    tab_exp = QWidget()
    layout_exp = QVBoxLayout()
    
    grp_exp = QGroupBox("📤 Exportar para Monitores Agrícolas")
    form_exp = QFormLayout()
    
    # Monitor
    grp_monitor = QGroupBox("Monitor de Destino")
    lay_mon = QGridLayout()
    
    monitors = [
        ("John Deere", ["GS3 2630", "4640", "Gen 4", "Operations Center"]),
        ("Jacto", ["Uniport", "Topper 5500", "Arbus 4000"]),
        ("New Holland", ["PLM Connect", "Intelliview"]),
        ("Stara", ["Stara", "Bravo 4000"]),
        ("Trimble", ["Field-IQ", "TMX"]),
        ("Raven", ["CR7", "Viper 4"]),
        ("Genérico", ["Shapefile", "GeoJSON", "KML", "ISOXML"])
    ]
    
    for i, (marca, modelos) in enumerate(monitors):
        rd = QRadioButton(marca)
        if i == 0:
            rd.setChecked(True)
        combo = QComboBox()
        combo.addItems(modelos)
        lay_mon.addWidget(rd, i, 0)
        lay_mon.addWidget(combo, i, 1)
    
    grp_monitor.setLayout(lay_mon)
    form_exp.addRow("", grp_monitor)
    
    # Formato
    combo_formato = QComboBox()
    combo_formato.addItems(["Shapefile (.shp)", "GeoPackage (.gpkg)", "KML (.kml)", "ISOXML (.zip)", "GeoJSON (.json)"])
    form_exp.addRow("Formato:", combo_formato)
    
    # Camadas a exportar
    grp_camadas = QGroupBox("Camadas a Exportar")
    lay_cam = QVBoxLayout()
    
    chk_exp_talhao = QCheckBox("Talhão")
    chk_exp_talhao.setChecked(True)
    chk_exp_bord = QCheckBox("Bordadura")
    chk_exp_bord.setChecked(True)
    chk_exp_plant = QCheckBox("Linhas de Plantio")
    chk_exp_plant.setChecked(True)
    chk_exp_pulv = QCheckBox("Linhas de Pulverização")
    chk_exp_pulv.setChecked(True)
    chk_exp_zonas = QCheckBox("Zonas de Manejo")
    chk_exp_zonas.setChecked(True)
    
    lay_cam.addWidget(chk_exp_talhao)
    lay_cam.addWidget(chk_exp_bord)
    lay_cam.addWidget(chk_exp_plant)
    lay_cam.addWidget(chk_exp_pulv)
    lay_cam.addWidget(chk_exp_zonas)
    
    grp_camadas.setLayout(lay_cam)
    form_exp.addRow("", grp_camadas)
    
    # Pasta de saída
    inp_out = QLineEdit()
    btn_out = QPushButton("📁")
    out_layout = QHBoxLayout()
    out_layout.addWidget(inp_out)
    out_layout.addWidget(btn_out)
    form_exp.addRow("Pasta de Saída:", out_layout)
    
    grp_exp.setLayout(form_exp)
    layout_exp.addWidget(grp_exp)
    
    btn_exportar = QPushButton("📤 EXPORTAR PARA MONITOR")
    btn_exportar.setStyleSheet("""
        QPushButton {
            background-color: #e74c3c; color: white;
            font-weight: bold; padding: 12px;
            font-size: 13px; border-radius: 5px;
        }
        QPushButton:hover { background-color: #c0392b; }
    """)
    layout_exp.addWidget(btn_exportar)
    
    layout_exp.addStretch()
    tab_exp.setLayout(layout_exp)
    tabs.addTab(tab_exp, "📤 Exportar")
    
    # ==================== ABA 9: PIPELINE ====================
    tab_pipe = QWidget()
    layout_pipe = QVBoxLayout()
    
    grp_pipe = QGroupBox("⚡ Pipeline Completo Automático")
    lay_pipe = QVBoxLayout()
    
    desc = QLabel("Execute TODAS as etapas automaticamente:")
    desc.setStyleSheet("font-size: 12px; color: #555;")
    lay_pipe.addWidget(desc)
    
    etapas = QLabel("""
    1. 📥 Importar talhão
    2. 🚜 Gerar bordadura
    3. 🌱 Gerar linhas de plantio
    4. 💨 Gerar linhas de pulverização
    5. 🏔️ Analisar relevo
    6. 🗺️ Gerar zonas de manejo
    7. 📤 Exportar para monitor
    """)
    etapas.setStyleSheet("font-family: monospace; padding: 10px; background: #f8f9fa;")
    lay_pipe.addWidget(etapas)
    
    # Configurações do pipeline
    grp_cfg_pipe = QGroupBox("Configurações Rápidas")
    lay_cfg = QFormLayout()
    
    combo_pipe_cult = QComboBox()
    combo_pipe_cult.addItems(["soja", "milho", "algodao", "feijao", "sorgo"])
    lay_cfg.addRow("Cultura:", combo_pipe_cult)
    
    combo_pipe_mon = QComboBox()
    combo_pipe_mon.addItems(["jd2630", "jacto", "newholland", "stara"])
    lay_cfg.addRow("Monitor:", combo_pipe_mon)
    
    spin_pipe_larg = QDoubleSpinBox()
    spin_pipe_larg.setRange(1, 50)
    spin_pipe_larg.setValue(30.0)
    spin_pipe_larg.setSuffix(" m")
    lay_cfg.addRow("Largura Barra:", spin_pipe_larg)
    
    chk_pipe_dem = QCheckBox("Usar DEM para análise de relevo (se disponível)")
    chk_pipe_dem.setChecked(True)
    lay_cfg.addRow("", chk_pipe_dem)
    
    chk_pipe_zonas = QCheckBox("Gerar zonas de manejo")
    chk_pipe_zonas.setChecked(True)
    lay_cfg.addRow("", chk_pipe_zonas)
    
    grp_cfg_pipe.setLayout(lay_cfg)
    lay_pipe.addWidget(grp_cfg_pipe)
    
    grp_pipe.setLayout(lay_pipe)
    layout_pipe.addWidget(grp_pipe)
    
    btn_pipe = QPushButton("⚡ EXECUTAR PIPELINE COMPLETO")
    btn_pipe.setStyleSheet("""
        QPushButton {
            background-color: #2c3e50; color: white;
            font-weight: bold; padding: 15px;
            font-size: 14px; border-radius: 5px;
        }
        QPushButton:hover { background-color: #1a252f; }
    """)
    layout_pipe.addWidget(btn_pipe)
    
    layout_pipe.addStretch()
    tab_pipe.setLayout(layout_pipe)
    tabs.addTab(tab_pipe, "⚡ Pipeline")
    
    # Adicionar tabs ao layout
    layout.addWidget(tabs)
    
    # === ÁREA DE LOG ===
    grp_log = QGroupBox("📝 Log de Operações")
    lay_log = QVBoxLayout()
    
    progress = QProgressBar()
    progress.setVisible(False)
    lay_log.addWidget(progress)
    
    txt_log = QTextEdit()
    txt_log.setReadOnly(True)
    txt_log.setMaximumHeight(150)
    txt_log.setStyleSheet("background-color: #f8f9fa; font-family: monospace;")
    lay_log.addWidget(txt_log)
    
    grp_log.setLayout(lay_log)
    layout.addWidget(grp_log)
    
    # === BOTÕES FINAIS ===
    btn_layout = QHBoxLayout()
    
    btn_doc = QPushButton("📖 Abrir Documentação")
    btn_doc.setStyleSheet("padding: 10px;")
    
    btn_fechar = QPushButton("❌ Fechar")
    btn_fechar.setStyleSheet("padding: 10px;")
    btn_fechar.clicked.connect(dialog.close)
    
    btn_layout.addWidget(btn_doc)
    btn_layout.addStretch()
    btn_layout.addWidget(btn_fechar)
    
    layout.addLayout(btn_layout)
    
    dialog.setLayout(layout)
    
    # === FUNÇÕES DOS BOTÕES ===
    def log(msg):
        txt_log.append(msg)
        txt_log.ensureCursorVisible()
    
    def atualizar_combos_talhoes():
        """Atualiza combos de talhões com camadas do projeto"""
        layers = [l.name() for l in QgsProject.instance().mapLayers().values()
                 if isinstance(l, QgsVectorLayer) and l.geometryType() == 2]
        
        for combo in [combo_talhao_bord, combo_talhao_plant, combo_talhao_pulv, combo_talhao_zonas]:
            combo.clear()
            if layers:
                combo.addItems(layers)
            else:
                combo.addItem("Nenhum talhão importado")
        
        log(f"Talhões disponíveis: {len(layers)}")
    
    def atualizar_combos_dem():
        """Atualiza combos de DEM"""
        layers = [l.name() for l in QgsProject.instance().mapLayers().values()
                 if isinstance(l, QgsRasterLayer)]
        combo_dem.clear()
        if layers:
            combo_dem.addItems(layers)
        else:
            combo_dem.addItem("Nenhum DEM carregado")
    
    # Conectar atualização
    btn_criar_proj.clicked.connect(lambda: atualizar_combos_talhoes())
    
    # Mostrar dialog
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    
    # Atualizar combos iniciais
    atualizar_combos_talhoes()
    atualizar_combos_dem()
    
    log("✅ Interface AAP GIS carregada!")
    log("📁 Selecione uma aba e configure os parâmetros")
    
    return dialog


# === CRIAR BOTÃO NA BARRA DE FERRAMENTAS ===
if '_aap_btn' in globals():
    try:
        iface.removeToolBarIcon(_aap_btn)
    except:
        pass

_aap_btn = QAction("🌾 AAP GIS", iface.mainWindow())
_aap_btn.triggered.connect(criar_interface_aap_gis)
iface.addToolBarIcon(_aap_btn)

print("="*60)
print("✅ AAP GIS Interface Completa Criada!")
print("="*60)
print("Clique no botão '🌾 AAP GIS' na barra de ferramentas")
print("ou execute: criar_interface_aap_gis()")
print("="*60)
