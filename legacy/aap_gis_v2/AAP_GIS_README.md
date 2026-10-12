# 🌱 SISTEMA AAP GIS - Agricultura de Precisão com QGIS + SAGA GIS + PyQGIS

Versão 2.0 | 2024

## 📋 Índice

- [Visão Geral](#visão-geral)
- [Estrutura do Sistema](#estrutura-do-sistema)
- [Instalação e Configuração](#instalação-e-configuração)
- [Guia de Uso](#guia-de-uso)
- [Referência de Scripts](#referência-de-scripts)
- [Parâmetros Agronômicos](#parâmetros-agronômicos)
- [Exportação para Monitores](#exportação-para-monitores)
- [Solução de Problemas](#solução-de-problemas)

---

## Visão Geral

O Sistema AAP GIS é uma solução completa de Agricultura de Precisão desenvolvida para QGIS 3.x com integração SAGA GIS e PyQGIS. O sistema automatiza o fluxo completo desde a importação de talhões até a exportação para monitores agrícolas.

### Funcionalidades Principais

✅ **Parte 1** - Ambiente e estrutura do projeto  
✅ **Parte 2** - Importação e limpeza de dados (SHP, KML, GeoJSON, CSV)  
✅ **Parte 3** - Geração automática de bordaduras (headlands)  
✅ **Parte 4** - Geração de linhas de plantio com direção otimizada  
✅ **Parte 5** - Geração de linhas de pulverização com configuração de barra  
✅ **Parte 6** - Análise de terreno (slope, aspecto, curvatura, TWI)  
✅ **Parte 7** - Cruzamento de dados e zonas de manejo  
✅ **Parte 8** - Exportação para monitores e automação one-click  

### Requisitos

- **QGIS 3.x** (LTR recomendado)
- **SAGA GIS 7.x** (para análise de terreno)
- **Python 3.x** (incluído no QGIS)
- **Windows/Linux/macOS**

---

## Estrutura do Sistema

### Pastas do Projeto

```
AAP_Projeto/
├── 01_Entrada/        → SHP, KML, GeoJSON originais
├── 02_Talhoes/        → Talhões processados
├── 03_Bordaduras/     → Polígonos de bordadura
├── 04_Plantio/        → Linhas de plantio por cultura
├── 05_Pulverizacao/   → Linhas de pulverização
├── 06_Relevo/         → DEM, slope, flow, curvature
├── 07_Analise/        → Cruzamentos e zonas de manejo
└── 08_Exportacao/     → Arquivos finais para máquinas
```

### Camadas do GeoPackage

O sistema utiliza um GeoPackage único (`AAP_Base.gpkg`) com 5 camadas:

1. **talhoes** (POLÍGONO) - Talhões com atributos de cultura e safra
2. **bordaduras** (POLÍGONO) - Bordaduras internas/externas
3. **linhas_plantio** (LINHA) - Linhas de plantio paralelas
4. **linhas_pulverizacao** (LINHA) - Linhas de pulverização
5. **linha_ab** (LINHA) - Linha AB de direção

---

## Instalação e Configuração

### 1. Preparar o Ambiente

```bash
# Clone ou copie os scripts para uma pasta
# Ex: C:/Users/seu_usuario/Documents/QGIS_Scripts/AAP_GIS/
```

### 2. Configurar o QGIS

1. Abra o QGIS
2. Vá em **Settings → Options → Python**
3. Adicione o caminho dos scripts ao **Python Path**
4. Reinicie o QGIS

### 3. Verificar SAGA GIS

1. Abra o QGIS Processing Toolbox (Ctrl+Alt+T)
2. Vá em **Options → Providers → SAGA**
3. Verifique se o SAGA está ativado e configurado

---

## Guia de Uso

### Fluxo de Trabalho Padrão

```
Parte 1 → Parte 2 → Parte 3 → Parte 4 → Parte 5
                    ↓
                  Parte 6
                    ↓
         Partes 4+5+6 → Parte 7 → Parte 8
```

### Parte 1: Configurar Projeto

No console Python do QGIS (Ctrl+Alt+P):

```python
import sys
sys.path.insert(0, 'C:/caminho/para/scripts')
from aap_part1_setup import *

configurar_projeto_aap(
    projeto_path='C:/Users/seu_usuario/Desktop/PYTON/AAP_Projeto',
    nome_fazenda='MinhaFazenda',
    ano='2024',
    epsg_utm='EPSG:31981'  # Zona 21S para RS/SC/PR
)
```

### Parte 2: Importar Talhão

```python
from aap_part2_importacao import *

importar_e_processar_talhao(
    caminho_arquivo='C:/caminho/talhao.shp',
    nome_talhao='Talhao_01',
    cultura='soja',
    safra='2024/25',
    projeto_path='C:/Users/seu_usuario/Desktop/PYTON/AAP_Projeto',
    epsg_utm='EPSG:31981'
)
```

### Parte 3: Gerar Bordadura

```python
from aap_part3_bordadura import *

gerar_bordadura(
    id_talhao=1,
    largura_m=9.0,      # Largura da colhedora
    n_passadas=2,
    cultura='soja',
    tipo='interno'
)
```

### Parte 4: Gerar Linhas de Plantio

```python
from aap_part4_plantio import *

gerar_linhas_plantio(
    id_talhao=1,
    cultura='soja',
    espacamento_m=0.45,
    metodo_direcao='auto_eixo',
    centralizar=True
)
```

### Parte 5: Gerar Linhas de Pulverização

```python
from aap_part5_pulverizacao import *

gerar_linhas_pulverizacao(
    id_talhao=1,
    largura_barra_m=30.0,
    sobreposicao_pct=5.0,
    preset_maquina='jd_r4044_30m',
    densidade_calda_l_ha=100,
    velocidade_km_h=15
)
```

### Parte 6: Analisar Terreno (Opcional)

```python
from aap_part6_relevo import *

analisar_terreno(
    dem_path='C:/caminho/DEM.tif',
    talhao_id=1,
    projeto_path='C:/Users/seu_usuario/Desktop/PYTON/AAP_Projeto'
)
```

### Parte 7: Cruzar Dados

```python
from aap_part7_cruzamento import *

analisar_cruzamentos(
    id_talhao=1,
    projeto_path='C:/Users/seu_usuario/Desktop/PYTON/AAP_Projeto'
)
```

### Parte 8: Exportar

```python
from aap_part8_exportacao import *

# Pipeline completo one-click
executar_pipeline_completo(
    arquivo_talhao='C:/caminho/talhao.shp',
    pasta_saida='C:/Users/seu_usuario/Desktop/PYTON/AAP_Projeto',
    config={
        'cultura': 'soja',
        'safra': '2024/25',
        'largura_colhedeira_m': 9.0,
        'largura_barra_m': 30.0,
        'sobreposicao_pct': 5.0,
        'epsg_utm': 'EPSG:31981'
    }
)
```

---

## Referência de Scripts

### aap_part1_setup.py
Configuração inicial do projeto QGIS, criação de estrutura de pastas e GeoPackage base.

### aap_part2_importacao.py
Importação de talhões e DEM de diversos formatos com pipeline de limpeza automática.

### aap_part3_bordadura.py
Geração automática de bordaduras baseada em largura de máquina e restrições culturais.

### aap_part4_plantio.py
Geração de linhas de plantio paralelas com determinação de direção (AB line).

### aap_part5_pulverizacao.py
Geração de linhas de pulverização com configuração de barra e sobreposição.

### aap_part6_relevo.py
Análise completa de terreno usando SAGA GIS (slope, aspecto, curvatura, TWI).

### aap_part7_cruzamento.py
Cruzamento de dados vetoriais e raster para análise integrada e zonas de manejo.

### aap_part8_exportacao.py
Exportação para monitores agrícolas e pipeline de automação completo.

---

## Parâmetros Agronômicos

### Espaçamentos por Cultura

| Cultura   | Espaçamento (m) | Bordadura Mín (m) | Bordadura Ideal (m) |
|-----------|----------------|-------------------|---------------------|
| Soja      | 0.45           | 7.0               | 9.0                 |
| Milho     | 0.90           | 9.0               | 12.0                |
| Algodão   | 0.90 / 0.76    | 12.0              | 15.0                |
| Feijão    | 0.50           | 7.0               | 9.0                 |
| Sorgo     | 0.50           | 7.0               | 9.0                 |

### Classes de Declividade

| Classe | Graus | %     | Descrição         | Recomendação                    |
|--------|-------|-------|-------------------|---------------------------------|
| 0      | 0-2°  | <3.5% | Plano             | Ideal para mecanização          |
| 1      | 2-5°  | <8.7% | Suave ondulado    | Mecanização normal              |
| 2      | 5-8°  | <14%  | Ondulado          | Atenção com equipamentos        |
| 3      | 8-13° | <23%  | Forte ondulado    | Restrições operacionais          |
| 4      | >13°  | >23%  | Montanhoso        | Inapto para mecanização         |

### Presets de Pulverizadoras

| Marca/Modelo           | Barra | Preset               |
|------------------------|-------|----------------------|
| Jacto Uniport 3030     | 24m   | jacto_uniport_3030   |
| Jacto Uniport 4030     | 28m   | jacto_uniport_4030   |
| John Deere R4044       | 24m   | jd_r4044_24m         |
| John Deere R4044       | 30m   | jd_r4044_30m         |
| John Deere R4044       | 36m   | jd_r4044_36m         |
| New Holland Guardian   | 24m   | nh_guardian_24m      |
| New Holland Guardian   | 30m   | nh_guardian_30m      |
| Stara Touro            | 24m   | stara_touro_24m      |
| Stara Touro            | 30m   | stara_touro_30m      |
| Stara Touro            | 36m   | stara_touro_36m      |

---

## Exportação para Monitores

### Jacto (Topper 5500, JD 2630)

- **Formato**: SHP ou KML
- **CRS**: WGS84 obrigatório
- **Importação**: USB ou cartão SD

### John Deere (Operations Center, GS3 2630)

- **Formato**: SHP
- **CRS**: WGS84
- **Limite**: 500 features por arquivo
- **Importação**: myjohndeere.com → Fields → Import

### New Holland (IntelliView IV, PLM Connect)

- **Formato**: SHP compactado em .zip
- **CRS**: WGS84
- **Importação**: PLM Connect

### Stara (Touro, Themis)

- **Formato**: KML ou SHP
- **CRS**: WGS84
- **Importação**: USB no monitor

---

## Solução de Problemas

### Erro Comum: "Camada não encontrada"

**Causa**: O projeto não foi configurado corretamente (Parte 1 não executada).

**Solução**: Execute `configurar_projeto_aap()` primeiro para criar o GeoPackage base.

### Erro Comum: "DEM inválido"

**Causa**: O DEM não está no formato correto ou CRS incompatível.

**Solução**: Verifique se o DEM é GeoTIFF e está reprojeta do para UTM SIRGAS 2000.

### Erro Comum: "Geometria inválida"

**Causa**: O talhão importado tem geometrias corrompidas.

**Solução**: O pipeline de limpeza (Parte 2) corrige automaticamente, mas verifique o relatório de validação.

### Erro Comum: "SAGA não encontrado"

**Causa**: O SAGA GIS não está instalado ou configurado no QGIS.

**Solução**: 
1. Instale o SAGA GIS
2. Configure no QGIS: Processing → Options → Providers → SAGA

### Erro Comum: "Bordadura vazia"

**Causa**: O talhão é muito pequeno para a bordadura desejada.

**Solução**: O sistema ajusta automaticamente para 50% da menor dimensão. Verifique o aviso no console.

---

## Inserção Manual de Medições

O sistema permite inserir manualmente medições em qualquer etapa:

### Exemplo: Inserir medição manual de largura de máquina

```python
# Em vez de usar presets, insira valor manual
gerar_bordadura(
    id_talhao=1,
    largura_m=12.5,  # Valor manual inserido
    n_passadas=2,
    cultura='soja'
)
```

### Exemplo: Inserir medição manual de espaçamento

```python
gerar_linhas_plantio(
    id_talhao=1,
    cultura='soja',
    espacamento_m=0.50,  # Valor manual (diferente do padrão 0.45)
    metodo_direcao='manual',
    azimute_manual=45.0  # Direção manual em graus
)
```

### Exemplo: Inserir medição manual de densidade de calda

```python
gerar_linhas_pulverizacao(
    id_talhao=1,
    largura_barra_m=30.0,
    sobreposicao_pct=5.0,
    densidade_calda_l_ha=150,  # Valor manual
    velocidade_km_h=12.0        # Valor manual
)
```

---

## Suporte

Para dúvidas ou problemas:

1. Verifique a documentação específica de cada parte nos scripts
2. Consulte as tabelas de referência incluídas em cada script
3. Revise o relatório de validação gerado automaticamente

---

## Licença

Sistema AAP GIS v2.0  
Desenvolvido para uso em Agricultura de Precisão  
2024

---

**Nota**: Este sistema foi desenvolvido para o contexto agrícola brasileiro, utilizando o sistema de referência SIRGAS 2000 e parâmetros adaptados às culturas e máquinas comuns no Brasil.
