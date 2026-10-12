# -*- coding: utf-8 -*-
"""
AAP GIS - Projetar Plantio (Processing Toolbox)

Este script aparece no Processing Toolbox do QGIS.
Caminho: Processing → Scripts → AAP GIS → Projetar Plantio
"""

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsProcessing, QgsProcessingAlgorithm,
                       QgsProcessingParameterVectorLayer,
                       QgsProcessingParameterString,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterFolderDestination,
                       QgsVectorFileWriter)
import sys
import os

# Adicionar path dos scripts AAP GIS
sys.path.insert(0, r"c:\Users\fortu\Desktop\PYTON")


class ProjetarPlantioAlgorithm(QgsProcessingAlgorithm):
    """
    Algoritmo para Projetar Plantio - AAP GIS
    """
    
    INPUT_TALHAO = 'INPUT_TALHAO'
    CULTURA = 'CULTURA'
    MAQUINA = 'MAQUINA'
    LARGURA_BARRA = 'LARGURA_BARRA'
    OUTPUT_FOLDER = 'OUTPUT_FOLDER'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def name(self):
        return 'projetar_plantio'

    def displayName(self):
        return self.tr('Projetar Plantio')

    def group(self):
        return 'AAP GIS'

    def groupId(self):
        return 'aapgis'

    def shortHelpString(self):
        return self.tr("""
        <b>Projetar Plantio - AAP GIS</b>
        
        Cria automaticamente:
        - Bordaduras otimizadas
        - Linhas de plantio
        - Linhas de pulverização
        - Exportação para monitor
        
        O sistema analisa o terreno e escolhe a melhor estratégia automaticamente.
        """)

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT_TALHAO,
                self.tr('Talhão (SHP)'),
                [QgsProcessing.TypeVectorPolygon]
            )
        )
        
        self.addParameter(
            QgsProcessingParameterString(
                self.CULTURA,
                self.tr('Cultura'),
                defaultValue='soja',
                optional=False
            )
        )
        
        self.addParameter(
            QgsProcessingParameterString(
                self.MAQUINA,
                self.tr('Monitor (jd2630, jacto, newholland, stara)'),
                defaultValue='jd2630',
                optional=False
            )
        )
        
        self.addParameter(
            QgsProcessingParameterNumber(
                self.LARGURA_BARRA,
                self.tr('Largura da Barra (metros)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=30.0,
                minValue=1.0,
                maxValue=100.0
            )
        )
        
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_FOLDER,
                self.tr('Pasta de Saída')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        try:
            feedback.pushInfo('='*70)
            feedback.pushInfo('AAP GIS - PROJETAR PLANTIO')
            feedback.pushInfo('='*70)
            
            # Obter parâmetros
            talhao_layer = self.parameterAsVectorLayer(parameters, self.INPUT_TALHAO, context)
            cultura = self.parameterAsString(parameters, self.CULTURA, context)
            maquina = self.parameterAsString(parameters, self.MAQUINA, context)
            largura_barra = self.parameterAsDouble(parameters, self.LARGURA_BARRA, context)
            output_folder = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)
            
            feedback.pushInfo(f'Talhão: {talhao_layer.name()}')
            feedback.pushInfo(f'Cultura: {cultura}')
            feedback.pushInfo(f'Monitor: {maquina}')
            feedback.pushInfo(f'Largura barra: {largura_barra}m')
            
            # Importar API simples
            from aap_simple_api import criar_projeto_plantio
            
            # Salvar camada temporariamente
            temp_path = os.path.join(output_folder, "temp_talhao.shp")
            QgsVectorFileWriter.writeAsVectorFormat(
                talhao_layer,
                temp_path,
                "UTF-8",
                talhao_layer.crs(),
                "ESRI Shapefile"
            )
            
            # Executar fluxo
            resultado = criar_projeto_plantio(
                arquivo_talhao=temp_path,
                cultura=cultura,
                maquina=maquina,
                largura_barra_m=largura_barra,
                projeto_path=output_folder
            )
            
            if resultado['sucesso']:
                feedback.pushInfo('='*70)
                feedback.pushInfo('✅ PROJETO CRIADO COM SUCESSO')
                feedback.pushInfo('='*70)
                
                dados = resultado['dados']
                feedback.pushInfo(f'Área: {dados.get("area_ha", 0):.2f} ha')
                feedback.pushInfo(f'Linhas plantio: {dados.get("linhas_plantio", 0)}')
                feedback.pushInfo(f'Linhas pulverização: {dados.get("linhas_pulverizacao", 0)}')
                
                decisao = dados.get('decisao_automatica', {})
                feedback.pushInfo('Decisão Automática:')
                for chave, valor in decisao.items():
                    feedback.pushInfo(f'  {chave}: {valor}')
            else:
                feedback.reportError(resultado['mensagem'])
            
            return {self.OUTPUT_FOLDER: output_folder}
            
        except Exception as e:
            feedback.reportError(f'Erro: {str(e)}')
            raise

    def createInstance(self):
        return ProjetarPlantioAlgorithm()


# Registrar algoritmo no Processing
def register_algorithm():
    from qgis.core import QgsApplication
    from qgis.processing import Processing
    
    alg = ProjetarPlantioAlgorithm()
    QgsApplication.processingRegistry().addAlgorithm(alg)


# Para usar: cole no Console Python do QGIS
if __name__ == '__main__':
    register_algorithm()
