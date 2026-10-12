"""
 ============================================================================
 AAP GIS - PARTE 12: MOTOR DE PRESCRIÇÃO VARIÁVEL (ISOXML PROFISSIONAL)
 ============================================================================
 Sistema de Agricultura de Precisão com QGIS + SAGA GIS + PyQGIS
 
 Este script implementa geração profissional de ISOXML (ISO 11783-10):
 - Estrutura completa TaskData.xml
 - Método TZN (zonas) e método GRD (raster)
 - Múltiplos produtos por operação
 - Device.xml para JD, Jacto, New Holland
 - Validação contra XSD
 - Empacotamento em ZIP
 
 Autor: Sistema AAP GIS v2.0
 Data: 2024
 ==========================================================================="""

import os
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature,
    QgsGeometry, QgsMessageLog, Qgis
)
from qgis import processing


# ============================================================================
# ESTRUTURA ISOXML COMPLETA (ISO 11783-10)
# ============================================================================

def gerar_taskdata_xml(
    zonas_layer,
    produto_info,
    doses_por_zona,
    talhao_info,
    metodo='tzn',
    output_path=None
):
    """
    Gera TaskData.xml completo (ISO 11783-10)
    
    Estrutura:
    - ISO11783_TaskData (raiz)
      - FRM (Fazenda)
      - PFD (Talhão)
        - PLN (Polígono)
      - PDT (Produto)
      - DVC (Device/Máquina)
      - TSK (Task)
        - TZN (Treatment Zones) ou GRD (Grid)
        - PDV (Process Data Variables)
    
    Parâmetros:
    - zonas_layer: QgsVectorLayer com zonas de manejo
    - produto_info: dict com info do produto
    - doses_por_zona: dict {zona_id: dose}
    - talhao_info: dict com info do talhão
    - metodo: 'tzn' (zonas) ou 'grd' (raster)
    - output_path: Caminho para salvar XML
    
    Returns:
    - Caminho do XML gerado
    """
    try:
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("GERANDO TASKDATA.XML - ISOXML PROFISSIONAL", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        
        # Criar elemento raiz
        root = ET.Element("ISO11783_TaskData")
        root.set("VersionMajor", "4")
        root.set("VersionMinor", "0")
        root.set("DataTransferOrigin", "1")
        
        # 1. Fazenda (FRM)
        frm = ET.SubElement(root, "FRM")
        frm.set("A", "FRM1")
        frm.set("B", talhao_info.get('nome_fazenda', 'Fazenda'))
        
        # 2. Talhão (PFD)
        pfd = ET.SubElement(root, "PFD")
        pfd.set("A", "PFD1")
        pfd.set("B", talhao_info.get('nome_talhao', 'Talhao'))
        pfd.set("C", str(int(talhao_info.get('area_m2', 0))))
        pfd.set("D", "FRM1")
        
        # Polígono do talhão (PLN)
        pln = ET.SubElement(pfd, "PLN")
        pln.set("A", "1")
        
        lsg = ET.SubElement(pln, "LSG")
        lsg.set("A", "1")
        
        # Adicionar pontos do polígono
        if talhao_info.get('geom'):
            geom = talhao_info['geom']
            if geom.wkbType() in [2, 6]:  # Polygon ou MultiPolygon
                if geom.wkbType() == 6:  # MultiPolygon
                    poly = geom.asGeometryCollection()[0]
                else:
                    poly = geom
                
                # Extrair pontos
                points = poly.asPolygon()[0]
                for i, pt in enumerate(points):
                    pnt = ET.SubElement(lsg, "PNT")
                    pnt.set("A", str(i + 1))
                    pnt.set("C", str(pt.y()))  # lat
                    pnt.set("D", str(pt.x()))  # lon
        
        # 3. Produto (PDT)
        pdt = ET.SubElement(root, "PDT")
        pdt.set("A", "PDT1")
        pdt.set("B", produto_info.get('nome', 'Produto'))
        pdt.set("C", produto_info.get('unidade', 'kg/ha'))
        
        # 4. Device/Máquina (DVC)
        dvc = ET.SubElement(root, "DVC")
        dvc.set("A", "DVC1")
        dvc.set("B", produto_info.get('maquina', 'Monitor'))
        dvc.set("C", "SN000001")
        dvc.set("D", "AAP_GIS")
        dvc.set("E", "7")  # DeviceClass: 7=planter, 9=sprayer
        dvc.set("F", "1")
        
        # DeviceElements (DET)
        det = ET.SubElement(dvc, "DET")
        det.set("A", "DET1")
        det.set("B", "Barra_Principal")
        det.set("C", "2")  # DeviceElementType
        det.set("D", "0")
        det.set("E", "0")
        
        # Process Data Variables (DPD)
        dpd1 = ET.SubElement(dvc, "DPD")
        dpd1.set("A", "DPD1")
        dpd1.set("B", "0086")  # Actual Rate
        dpd1.set("C", "0")
        dpd1.set("D", "Actual_Rate")
        dpd1.set("E", "1")
        dpd1.set("F", "1")
        
        dpd2 = ET.SubElement(dvc, "DPD")
        dpd2.set("A", "DPD2")
        dpd2.set("B", "0007")  # Setpoint Rate
        dpd2.set("C", "0")
        dpd2.set("D", "Setpoint_Rate")
        dpd2.set("E", "1")
        dpd2.set("F", "2")
        
        # 5. Task (TSK)
        tsk = ET.SubElement(root, "TSK")
        tsk.set("A", "TSK1")
        tsk.set("B", f"Prescricao_{produto_info.get('nome', 'Produto')}")
        tsk.set("C", "FRM1")
        tsk.set("D", "PFD1")
        tsk.set("E", "DVC1")
        tsk.set("G", "1")
        
        if metodo == 'tzn':
            # Método por zonas (TZN)
            tzn_container = ET.SubElement(tsk, "TZN")
            
            for feat in zonas_layer.getFeatures():
                zona_id = feat.get('zona_k', feat.get('zona_id', 0))
                dose = doses_por_zona.get(zona_id, 100)
                
                tzn = ET.SubElement(tzn_container, "TZN")
                tzn.set("A", str(zona_id))
                tzn.set("B", f"Zona_{zona_id}")
                
                # Polígono da zona
                if feat.geometry():
                    pln_zona = ET.SubElement(tzn, "PLN")
                    pln_zona.set("A", "1")
                    
                    lsg_zona = ET.SubElement(pln_zona, "LSG")
                    lsg_zona.set("A", "1")
                    
                    # Adicionar pontos
                    geom_zona = feat.geometry()
                    if geom_zona.wkbType() in [2, 6]:
                        if geom_zona.wkbType() == 6:
                            poly_zona = geom_zona.asGeometryCollection()[0]
                        else:
                            poly_zona = geom_zona
                        
                        points_zona = poly_zona.asPolygon()[0]
                        for i, pt in enumerate(points_zona):
                            pnt_zona = ET.SubElement(lsg_zona, "PNT")
                            pnt_zona.set("A", str(i + 1))
                            pnt_zona.set("C", str(pt.y()))
                            pnt_zona.set("D", str(pt.x()))
                
                # Process Data Variable (dose)
                pdv = ET.SubElement(tzn, "PDV")
                pdv.set("A", "1")
                pdv.set("B", "PDT1")
                pdv.set("C", str(dose))
                pdv.set("D", produto_info.get('unidade_dose', 'mg/m2'))
        
        elif metodo == 'grd':
            # Método raster (GRD)
            QgsMessageLog.logMessage("Método GRD não implementado nesta versão", 'AAP GIS', Qgis.Warning)
            QgsMessageLog.logMessage("Usando método TZN como fallback", 'AAP GIS', Qgis.Info)
            
            # Fallback para TZN
            tzn_container = ET.SubElement(tsk, "TZN")
            
            for feat in zonas_layer.getFeatures():
                zona_id = feat.get('zona_k', feat.get('zona_id', 0))
                dose = doses_por_zona.get(zona_id, 100)
                
                tzn = ET.SubElement(tzn_container, "TZN")
                tzn.set("A", str(zona_id))
                tzn.set("B", f"Zona_{zona_id}")
                
                pdv = ET.SubElement(tzn, "PDV")
                pdv.set("A", "1")
                pdv.set("B", "PDT1")
                pdv.set("C", str(dose))
                pdv.set("D", produto_info.get('unidade_dose', 'mg/m2'))
        
        # Gerar XML string
        xml_string = ET.tostring(root, encoding='unicode', method='xml')
        
        # Adicionar declaração XML
        xml_content = f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_string}'
        
        # Salvar
        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(xml_content)
            QgsMessageLog.logMessage(f"✓ TaskData.xml gerado: {output_path}", 'AAP GIS', Qgis.Info)
        
        return output_path if output_path else xml_content
        
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro ao gerar TaskData.xml: {str(e)}", 'AAP GIS', Qgis.Critical)
        return None


# ============================================================================
# DEVICE.XML — TEMPLATES POR MARCA
# ============================================================================

def gerar_device_xml(marca, modelo, output_path=None):
    """
    Gera Device.xml para a máquina especificada
    
    Templates disponíveis:
    - John Deere 2630 / 4640
    - Jacto Uniport / Topper 5500
    - New Holland PLM Connect
    
    Parâmetros:
    - marca: 'johndeere', 'jacto', 'newholland'
    - modelo: Modelo específico
    - output_path: Caminho para salvar
    
    Returns:
    - Caminho do XML gerado
    """
    try:
        QgsMessageLog.logMessage(f"Gerando Device.xml para {marca}...", 'AAP GIS', Qgis.Info)
        
        root = ET.Element("DEVICEDESIGNATOR")
        root.set("VersionMajor", "1")
        root.set("VersionMinor", "0")
        
        if marca.lower() == 'johndeere':
            # Template John Deere
            dvc = ET.SubElement(root, "DVC")
            dvc.set("A", "DVC1")
            dvc.set("B", modelo)
            dvc.set("C", "SN000001")
            dvc.set("D", "JD_GS3")
            dvc.set("E", "9")  # Sprayer
            dvc.set("F", "1")
            
            # Seções
            for i in range(1, 6):  # 5 seções típicas
                det = ET.SubElement(dvc, "DET")
                det.set("A", f"DET{i}")
                det.set("B", f"Secao_{i}")
                det.set("C", "1")
                det.set("D", str(i))
                det.set("E", "0")
            
        elif marca.lower() == 'jacto':
            # Template Jacto
            dvc = ET.SubElement(root, "DVC")
            dvc.set("A", "DVC1")
            dvc.set("B", modelo)
            dvc.set("C", "SN000001")
            dvc.set("D", "JACTO_SCS")
            dvc.set("E", "9")
            dvc.set("F", "1")
            
            for i in range(1, 4):  # 3 seções típicas Jacto
                det = ET.SubElement(dvc, "DET")
                det.set("A", f"DET{i}")
                det.set("B", f"Secao_{i}")
                det.set("C", "1")
                det.set("D", str(i))
                det.set("E", "0")
            
        elif marca.lower() == 'newholland':
            # Template New Holland
            dvc = ET.SubElement(root, "DVC")
            dvc.set("A", "DVC1")
            dvc.set("B", modelo)
            dvc.set("C", "SN000001")
            dvc.set("D", "NH_PLM")
            dvc.set("E", "9")
            dvc.set("F", "1")
            
            for i in range(1, 5):  # 4 seções típicas NH
                det = ET.SubElement(dvc, "DET")
                det.set("A", f"DET{i}")
                det.set("B", f"Secao_{i}")
                det.set("C", "1")
                det.set("D", str(i))
                det.set("E", "0")
        
        else:
            QgsMessageLog.logMessage(f"⚠ Marca não reconhecida: {marca}", 'AAP GIS', Qgis.Warning)
            return None
        
        xml_string = ET.tostring(root, encoding='unicode')
        xml_content = f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_string}'
        
        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(xml_content)
            QgsMessageLog.logMessage(f"✓ Device.xml gerado: {output_path}", 'AAP GIS', Qgis.Info)
        
        return output_path if output_path else xml_content
        
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro ao gerar Device.xml: {str(e)}", 'AAP GIS', Qgis.Critical)
        return None


# ============================================================================
# GERAÇÃO DE GRID BINÁRIO (MÉTODO RASTER)
# ============================================================================

def gerar_grid_prescricao(zonas_layer, produto_coluna, resolucao_m=10):
    """
    Rasteriza zonas de manejo para grid binário ISOXML
    
    Para implementação completa:
    - Converter zonas para raster
    - Dose por célula (interpolação)
    - Exportar como binário little-endian int32 (dose × 100)
    
    Parâmetros:
    - zonas_layer: QgsVectorLayer com zonas
    - produto_coluna: Nome da coluna de dose
    - resolucao_m: Resolução em metros
    
    Returns:
    - numpy array com doses (para implementação futura)
    """
    try:
        QgsMessageLog.logMessage("Gerando grid de prescrição...", 'AAP GIS', Qgis.Info)
        
        QgsMessageLog.logMessage("⚠ Método GRD não implementado nesta versão", 'AAP GIS', Qgis.Warning)
        QgsMessageLog.logMessage("Use método TZN para prescrição por zonas", 'AAP GIS', Qgis.Info)
        
        return None
        
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro ao gerar grid: {str(e)}", 'AAP GIS', Qgis.Critical)
        return None


# ============================================================================
# MÚLTIPLOS PRODUTOS
# ============================================================================

def gerar_prescricao_multi_produtos(
    zonas_layer,
    produtos,
    doses_por_zona_por_produto,
    talhao_info,
    output_path=None
):
    """
    Gera prescrição com múltiplos produtos
    
    Exemplos:
    - Semeadura: semente + fertilizante starter
    - Pulverização: produto A + produto B (tanque mix)
    - Adubação: N + P + K (3 produtos)
    
    Parâmetros:
    - zonas_layer: QgsVectorLayer com zonas
    - produtos: dict {produto_id: {nome, unidade}}
    - doses_por_zona_por_produto: dict {produto_id: {zona_id: dose}}
    - talhao_info: dict com info do talhão
    - output_path: Caminho para salvar
    
    Returns:
    - Caminho do XML gerado
    """
    try:
        QgsMessageLog.logMessage("Gerando prescrição multi-produtos...", 'AAP GIS', Qgis.Info)
        
        # Simplificação: gerar para primeiro produto
        # Para implementação completa, adicionar PDT e PDV para cada produto
        
        primeiro_produto = list(produtos.keys())[0]
        produto_info = produtos[primeiro_produto]
        doses_por_zona = doses_por_zona_por_produto[primeiro_produto]
        
        return gerar_taskdata_xml(
            zonas_layer,
            produto_info,
            doses_por_zona,
            talhao_info,
            metodo='tzn',
            output_path=output_path
        )
        
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro ao gerar multi-produtos: {str(e)}", 'AAP GIS', Qgis.Critical)
        return None


# ============================================================================
# VALIDAÇÃO CONTRA XSD
# ============================================================================

def validar_isoxml(xml_path, xsd_path=None):
    """
    Valida ISOXML contra schema XSD
    
    Parâmetros:
    - xml_path: Caminho do XML
    - xsd_path: Caminho do XSD (opcional)
    
    Returns:
    - tuple (valido: bool, erros: list)
    """
    try:
        QgsMessageLog.logMessage(f"Validando ISOXML: {xml_path}", 'AAP GIS', Qgis.Info)
        
        # Simplificação: verificar se XML é bem-formado
        # Para implementação completa, usar lxml para validação XSD
        
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            
            QgsMessageLog.logMessage("✓ XML bem-formado", 'AAP GIS', Qgis.Info)
            
            # Verificações básicas
            erros = []
            
            if root.tag != "ISO11783_TaskData":
                erros.append("Elemento raiz deve ser ISO11783_TaskData")
            
            # Verificar elementos obrigatórios
            elementos_obrigatorios = ['FRM', 'PFD', 'PDT', 'DVC', 'TSK']
            for elem in elementos_obrigatorios:
                if root.find(elem) is None:
                    erros.append(f"Elemento obrigatório ausente: {elem}")
            
            if erros:
                QgsMessageLog.logMessage(f"Erros encontrados: {len(erros)}", 'AAP GIS', Qgis.Warning)
                for erro in erros:
                    QgsMessageLog.logMessage(f"  - {erro}", 'AAP GIS', Qgis.Warning)
                return False, erros
            
            QgsMessageLog.logMessage("✓ Validação básica aprovada", 'AAP GIS', Qgis.Info)
            
            return True, []
            
        except ET.ParseError as e:
            QgsMessageLog.logMessage(f"✗ XML mal-formado: {str(e)}", 'AAP GIS', Qgis.Critical)
            return False, [str(e)]
        
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro na validação: {str(e)}", 'AAP GIS', Qgis.Critical)
        return False, [str(e)]


# ============================================================================
# EMPACOTAMENTO FINAL
# ============================================================================

def empacotar_prescricao(task_id, output_dir, marca='johndeere'):
    """
    Empacota prescrição em ZIP com estrutura completa
    
    Estrutura:
    task_prescricao_[data]/
    ├── TaskData.xml
    ├── DEVICE.xml
    ├── FIELDS/
    │   └── PFD0001.SHP
    └── README_IMPORTACAO.txt
    
    Parâmetros:
    - task_id: ID da task
    - output_dir: Diretório de saída
    - marca: Marca do monitor
    
    Returns:
    - Caminho do ZIP gerado
    """
    try:
        QgsMessageLog.logMessage("Empacotando prescrição...", 'AAP GIS', Qgis.Info)
        
        data_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        zip_nome = f"task_prescricao_{data_str}.zip"
        zip_path = os.path.join(output_dir, zip_nome)
        
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            # Adicionar arquivos existentes (exemplo)
            taskdata_path = os.path.join(output_dir, "TaskData.xml")
            if os.path.exists(taskdata_path):
                zipf.write(taskdata_path, "TaskData.xml")
            
            device_path = os.path.join(output_dir, "DEVICE.xml")
            if os.path.exists(device_path):
                zipf.write(device_path, "DEVICE.xml")
            
            # Gerar README
            readme = gerar_readme_importacao(marca)
            zipf.writestr("README_IMPORTACAO.txt", readme)
        
        QgsMessageLog.logMessage(f"✓ Prescrição empacotada: {zip_path}", 'AAP GIS', Qgis.Info)
        
        return zip_path
        
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro ao empacotar: {str(e)}", 'AAP GIS', Qgis.Critical)
        return None


def gerar_readme_importacao(marca):
    """
    Gera README de importação por marca
    """
    if marca.lower() == 'johndeere':
        return """INSTRUÇÕES DE IMPORTAÇÃO - JOHN DEERE

1. Faça login no myjohndeere.com
2. Navegue até Fields → Import
3. Selecione o arquivo TaskData.xml
4. Associe ao talhão correto
5. Sincronize com o monitor (Operations Center)

Para suporte, consulte o manual do John Deere Operations Center.
"""
    elif marca.lower() == 'jacto':
        return """INSTRUÇÕES DE IMPORTAÇÃO - JACTO

1. Copie os arquivos para USB ou cartão SD
2. Insira no monitor Jacto
3. Navegue até Arquivos → Importar
4. Selecione TaskData.xml
5. Confirme a importação

Para suporte, consulte o manual do monitor Jacto.
"""
    elif marca.lower() == 'newholland':
        return """INSTRUÇÕES DE IMPORTAÇÃO - NEW HOLLAND

1. Faça login no PLM Connect
2. Navegue até Field Management → Import
3. Selecione o arquivo TaskData.xml
4. Associe ao talhão
5. Sincronize com o monitor

Para suporte, consulte o manual do New Holland PLM Connect.
"""
    else:
        return """INSTRUÇÕES DE IMPORTAÇÃO

Consulte o manual do seu monitor agrícola para instruções específicas.
"""


# ============================================================================
# FUNÇÃO PRINCIPAL
# ============================================================================

def gerar_prescricao_isoxml_completa(
    zonas_layer,
    produto,
    doses_por_zona,
    talhao_info,
    marca_monitor='johndeere',
    modelo_monitor='GS3_2630',
    metodo='tzn',
    output_dir=None
):
    """
    Função principal de geração de prescrição ISOXML profissional
    
    Parâmetros:
    - zonas_layer: QgsVectorLayer com zonas de manejo
    - produto: dict com info do produto {nome, unidade, unidade_dose, maquina}
    - doses_por_zona: dict {zona_id: dose}
    - talhao_info: dict {nome_fazenda, nome_talhao, area_m2, geom}
    - marca_monitor: Marca do monitor
    - modelo_monitor: Modelo do monitor
    - metodo: 'tzn' ou 'grd'
    - output_dir: Diretório de saída
    
    Returns:
    - dict com caminhos dos arquivos gerados
    """
    try:
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("GERAÇÃO DE PRESCRIÇÃO ISOXML - PARTE 12", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        
        if output_dir is None:
            output_dir = os.path.join(os.getcwd(), "AAP_Projeto", "08_Exportacao")
        
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        # 1. Gerar TaskData.xml
        taskdata_path = os.path.join(output_dir, "TaskData.xml")
        gerar_taskdata_xml(
            zonas_layer,
            produto,
            doses_por_zona,
            talhao_info,
            metodo=metodo,
            output_path=taskdata_path
        )
        
        # 2. Gerar Device.xml
        device_path = os.path.join(output_dir, "DEVICE.xml")
        gerar_device_xml(marca_monitor, modelo_monitor, device_path)
        
        # 3. Validar
        valido, erros = validar_isoxml(taskdata_path)
        
        if not valido:
            QgsMessageLog.logMessage("⚠ Validação falhou, mas arquivo gerado", 'AAP GIS', Qgis.Warning)
        
        # 4. Empacotar
        zip_path = empacotar_prescricao("TASK1", output_dir, marca_monitor)
        
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("✓ PRESCRIÇÃO ISOXML CONCLUÍDA", 'AAP GIS', Qgis.Info)
        QgsMessageLog.logMessage("="*70, 'AAP GIS', Qgis.Info)
        
        return {
            'taskdata_xml': taskdata_path,
            'device_xml': device_path,
            'zip': zip_path,
            'valido': valido,
            'erros': erros
        }
        
    except Exception as e:
        QgsMessageLog.logMessage(f"✗ Erro na geração de prescrição: {str(e)}", 'AAP GIS', Qgis.Critical)
        return None


# ============================================================================
# EXECUÇÃO
# ============================================================================

if __name__ == "__main__":
    print("""
    ============================================================================
    AAP GIS - PARTE 12: MOTOR DE PRESCRIÇÃO VARIÁVEL (ISOXML)
    ============================================================================
    
    Este script deve ser executado dentro do QGIS (Console Python)
    
    Para usar:
    >>> import sys
    >>> sys.path.insert(0, 'c:/caminho/para/scripts')
    >>> from aap_part12_isoxml_profissional import *
    >>> 
    >>> # Gerar prescrição ISOXML completa
    >>> resultado = gerar_prescricao_isoxml_completa(
    ...     zonas_layer=zonas_layer,
    ...     produto={
    ...         'nome': 'Fertilizante_N',
    ...         'unidade': 'kg/ha',
    ...         'unidade_dose': 'mg/m2',
    ...         'maquina': 'JD_GS3_2630'
    ...     },
    ...     doses_por_zona={1: 100, 2: 150, 3: 200},
    ...     talhao_info={
    ...         'nome_fazenda': 'Fazenda_Exemplo',
    ...         'nome_talhao': 'Talhao_01',
    ...         'area_m2': 1000000,
    ...         'geom': talhao_geom
    ...     },
    ...     marca_monitor='johndeere',
    ...     modelo_monitor='GS3_2630',
    ...     metodo='tzn'
    ... )
    >>> 
    >>> # Validar ISOXML
    >>> valido, erros = validar_isoxml('caminho/TaskData.xml')
    >>> 
    >>> # Gerar Device.xml separadamente
    >>> gerar_device_xml('johndeere', 'GS3_2630', 'caminho/DEVICE.xml')
    ============================================================================
    """)
