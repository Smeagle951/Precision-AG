# 📱 GUIA DE IMPORTAÇÃO POR MONITOR AGRÍCOLA

Sistema AAP GIS v2.0 - Parte 8

---

## Índice

- [Jacto](#jacto)
- [John Deere](#john-deere)
- [New Holland](#new-holland)
- [Stara](#stara)
- [Tabela Comparativa](#tabela-comparativa)
- [Solução de Problemas](#solução-de-problemas)

---

## Jacto

### Monitores Compatíveis

- Topper 5500
- JD 2630 (via Jacto)
- Outros monitores compatíveis Jacto

### Formato Suportado

- **Shapefile (.shp)** - Principal formato
- **KML (.kml)** - Alternativo

### Requisitos

- **CRS**: WGS84 (EPSG:4326) - OBRIGATÓRIO
- **Encoding**: UTF-8 ou Latin-1
- **Nomes de arquivo**: TAL_[NOME].shp (talhão), LIN_[NOME].shp (linhas)
- **Limite de vértices**: Sem limite conhecido

### Passo a Passo - Importação via USB

1. **Preparar o arquivo**
   - Exportar do QGIS usando `exportar_para_jacto()`
   - Verificar se o arquivo está em WGS84
   - Nomear arquivo conforme padrão: TAL_[NOME].shp

2. **Copiar para USB**
   - Inserir pendrive no computador
   - Copiar arquivo .shp + arquivos auxiliares (.dbf, .shx, .prj)
   - Ejetar pendrive com segurança

3. **Importar no monitor**
   - Inserir pendrive no monitor Jacto
   - Navegar até menu "Arquivos" ou "Importar"
   - Selecionar o arquivo .shp
   - Confirmar importação
   - Verificar se o talhão aparece no mapa

4. **Validar no monitor**
   - Abrir mapa do talhão
   - Verificar se geometria está correta
   - Conferir área se disponível
   - Testar uma passada simulada

### Passo a Passo - Importação via Cartão SD

1. **Preparar cartão SD**
   - Formatar cartão em FAT32
   - Criar pasta "TALHOES" se necessário

2. **Copiar arquivos**
   - Copiar arquivos .shp para cartão
   - Garantir todos os arquivos auxiliares estão presentes

3. **Importar no monitor**
   - Inserir cartão SD no monitor
   - Seguir procedimento similar ao USB

### Dicas Jacto

- **Verificar CRS**: Sempre confirme que o arquivo está em WGS84 antes de exportar
- **Nomes curtos**: Use nomes de arquivo curtos (máximo 8 caracteres antes da extensão)
- **Backup**: Mantenha cópia dos arquivos originais
- **Teste**: Faça um teste com um talhão pequeno primeiro

---

## John Deere

### Monitores Compatíveis

- GS3 2630
- GS2 1800/2600
- 4640 Universal Display
- Gen 4 Displays

### Formato Suportado

- **Shapefile (.shp)** - Via MyJohnDeere Operations Center
- **ISOXML (.xml)** - Para prescrição de aplicação variada

### Requisitos

- **CRS**: WGS84 (EPSG:4326) - OBRIGATÓRIO
- **Encoding**: Latin-1 (ISO 8859-1)
- **Limite**: 500 features por arquivo
- **Atributos**: Máximo 10 caracteres, sem acento

### Passo a Passo - MyJohnDeere Operations Center

#### 1. Criar Conta (se necessário)

1. Acesse https://myjohndeere.com
2. Clique em "Sign Up"
3. Preencha dados da organização
4. Verifique e-mail
5. Faça login

#### 2. Preparar Arquivo

1. Exportar do QGIS usando `exportar_para_johndeere()`
2. Verificar validação com `validar_exportacao_final()`
3. Confirmar que features ≤ 500
4. Compactar em .zip se necessário

#### 3. Upload no Operations Center

1. Faça login em myjohndeere.com
2. Navegue até "Fields & Crops"
3. Clique em "Fields"
4. Clique em "Import Field"
5. Selecione o arquivo .shp ou .zip
6. Aguarde upload
7. Verifique status de processamento

#### 4. Sincronizar com Monitor

1. No monitor John Deere, vá em "Machine Applications"
2. Selecione "JDLink" ou "Operations Center"
3. Inicie sincronização
4. Aguarde download dos dados
5. Verifique se talhão aparece na lista

#### 5. Validar no Monitor

1. Abra o talhão no monitor
2. Verifique geometria no mapa
3. Confirme área calculada
4. Teste AB Line se disponível

### Passo a Passo - Importação Direta via USB

1. **Exportar arquivo**
   - Usar formato SHP
   - Garantir WGS84
   - Verificar limite de 500 features

2. **Copiar para USB**
   - Copiar .shp + arquivos auxiliares
   - Organizar em pastas por safra

3. **Importar no monitor**
   - Inserir USB no monitor
   - Navegar até "Data Management"
   - Selecionar "Import Shapefile"
   - Escolher arquivo
   - Confirmar

### Prescrição de Aplicação Variada (ISOXML)

#### 1. Gerar ISOXML

```python
from aap_part8_exportacao_expanded import gerar_prescricao_isoxml

gerar_prescricao_isoxml(
    zonas_layer=zonas_manejo,
    produto="Fertilizante_N",
    doses_por_zona={1: 100, 2: 150, 3: 200},
    caminho_saida="prescricao.xml"
)
```

#### 2. Upload no Operations Center

1. Acesse "Prescriptions" no Operations Center
2. Clique em "Upload Prescription"
3. Selecione arquivo .xml
4. Associe ao talhão correto
5. Sincronize com monitor

### Dicas John Deere

- **Dividir arquivos grandes**: Se > 500 features, divida em múltiplos arquivos
- **Validar ISOXML**: Use validador XML antes de upload
- **Sincronização**: Aguarde sincronização completa antes de usar no campo
- **Backup**: Mantenha cópias no Operations Center

---

## New Holland

### Monitores Compatíveis

- IntelliView IV
- IntelliView III
- PLM Connect
- NH Display

### Formato Suportado

- **Shapefile (.shp)** - Compactado em .zip

### Requisitos

- **CRS**: WGS84 (EPSG:4326) - OBRIGATÓRIO
- **Encoding**: Latin-1
- **Compactação**: OBRIGATÓRIA em .zip

### Passo a Passo - PLM Connect

#### 1. Acessar PLM Connect

1. Acesse https://plmconnect.caseih.com
2. Faça login com credenciais
3. Navegue até "Field Management"

#### 2. Preparar Arquivo

1. Exportar do QGIS usando `exportar_para_newholland()`
2. O sistema compacta automaticamente em .zip
3. Verificar que .zip contém: .shp, .dbf, .shx, .prj

#### 3. Upload no PLM Connect

1. Clique em "Import Field"
2. Selecione arquivo .zip
3. Aguarde upload
4. Verifique status de processamento

#### 4. Sincronizar com Monitor

1. No monitor, vá em "PLM Connect"
2. Inicie sincronização
3. Aguarde download
4. Verifique talhão na lista

### Passo a Passo - Importação Direta via USB

1. **Preparar arquivo compactado**
   - Exportar do QGIS
   - Compactar manualmente se necessário
   - Incluir todos os arquivos (.shp, .dbf, .shx, .prj, .cpg)

2. **Copiar para USB**
   - Copiar arquivo .zip
   - Organizar por safra/ano

3. **Importar no monitor**
   - Inserir USB
   - Navegar até "Data Management"
   - Selecionar "Import ZIP"
   - Escolher arquivo
   - Confirmar

### Dicas New Holland

- **Compactação obrigatória**: Sempre use .zip
- **Verificar conteúdo**: Confirme que todos os arquivos estão no ZIP
- **PLM Connect**: Use portal web para melhor gerenciamento
- **Sincronização**: Aguarde conclusão completa

---

## Stara

### Monitores Compatíveis

- Touro
- Themis
- Topper (versões Stara)
- Outros monitores Stara

### Formato Suportado

- **KML (.kml)** - Principal formato
- **Shapefile (.shp)** - Alternativo

### Requisitos

- **CRS**: WGS84 (EPSG:4326) - OBRIGATÓRIO
- **Encoding**: UTF-8

### Passo a Passo - Importação via USB

#### 1. Preparar Arquivo KML

1. Exportar do QGIS usando `exportar_para_stara()`
2. O sistema gera automaticamente .kml
3. Verificar arquivo com visualizador KML (Google Earth)

#### 2. Copiar para USB

1. Inserir pendrive
2. Copiar arquivo .kml
3. Organizar em pastas por safra

#### 3. Importar no Monitor

1. Inserir USB no monitor Stara
2. Navegar até menu "Arquivos" ou "Mapas"
3. Selecionar "Importar"
4. Escolher arquivo .kml
5. Confirmar importação
6. Verificar no mapa

#### 4. Configurar no Monitor

1. Abrir talhão importado
2. Configurar AB Line se necessário
3. Ajustar parâmetros de operação
4. Salvar configuração

### Passo a Passo - Importação Shapefile

1. **Exportar SHP**
   - Usar `exportar_para_shapefile()` com CRS WGS84
   - Verificar atributos

2. **Copiar arquivos**
   - Copiar .shp + auxiliares
   - Garantir todos os arquivos presentes

3. **Importar**
   - Seguir procedimento similar ao KML
   - Selecionar formato SHP no monitor

### Dicas Stara

- **KML preferencial**: Monitores Stara preferem KML
- **Validar visualmente**: Use Google Earth para verificar KML
- **AB Line**: Configure AB Line no monitor após importação
- **Suporte**: Consulte suporte Stara para dúvidas específicas

---

## Tabela Comparativa

| Monitor/Marca      | Formato | CRS   | Limite    | Nome Arquivo | Método Importação     |
|--------------------|---------|-------|-----------|--------------|-----------------------|
| Jacto Topper 5500  | SHP/KML | WGS84 | -         | TAL_NOME.shp | USB/SD               |
| JD Operations Ctr  | SHP     | WGS84 | 500 feat  | JD_NOME.shp   | Web + Sincronização  |
| JD GS3 2630        | SHP     | WGS84 | 500 feat  | JD_NOME.shp   | USB/Operations Ctr   |
| NH IntelliView IV  | SHP     | WGS84 | -         | NH_NOME.zip   | PLM Connect / USB    |
| NH PLM Connect     | SHP     | WGS84 | -         | NH_NOME.zip   | Web + Sincronização  |
| Stara Touro        | KML/SHP | WGS84 | -         | ST_NOME.kml   | USB                  |
| Stara Themis       | KML/SHP | WGS84 | -         | ST_NOME.kml   | USB                  |

### Regras Obrigatórias (Todos)

- ✅ CRS: WGS84 (EPSG:4326)
- ✅ Encoding: Latin-1 ou UTF-8
- ✅ Atributos: máximo 10 caracteres, sem acento
- ✅ Geometrias: simples (sem multipart)
- ✅ Arquivo .prj: obrigatório

---

## Solução de Problemas

### Problema: Arquivo não aparece no monitor

**Possíveis causas:**
- CRS incorreto (não WGS84)
- Encoding incompatível
- Arquivo corrompido
- Formato não suportado

**Solução:**
1. Validar com `validar_exportacao_final()`
2. Reprojetar para WGS84
3. Exportar novamente com encoding Latin-1
4. Testar com visualizador (QGIS, Google Earth)

### Problema: Geometria distorcida no monitor

**Possíveis causas:**
- CRS errado durante exportação
- Reprojeção incorreta
- Unidades erradas

**Solução:**
1. Verificar CRS original do projeto
2. Confirmar reprojeção para WGS84
3. Reexportar
4. Validar em QGIS antes de enviar

### Problema: Atributos não aparecem

**Possíveis causas:**
- Nomes de atributos > 10 caracteres
- Acentos nos nomes
- Encoding incompatível

**Solução:**
1. Usar `renomear_atributos_exportacao()`
2. Verificar tabela de atributos
3. Remover acentos manualmente se necessário
4. Reexportar

### Problema: Limite de features excedido (John Deere)

**Possíveis causas:**
- Linhas de plantio/pulverização com muitas features
- Talhão complexo com muitos vértices

**Solução:**
1. Simplificar geometrias (`simplifygeometries`)
2. Dividir em múltiplos arquivos
3. Reduzir resolução de linhas
4. Exportar por setor

### Problema: Arquivo .prj não criado

**Possíveis causas:**
- Processing não gerou automaticamente
- Permissões de arquivo

**Solução:**
1. Criar .prj manualmente com texto do CRS
2. Verificar permissões da pasta
3. Usar `gdal:translate` com opção de criar .prj

### Problema: Monitor não reconhece USB

**Possíveis causas:**
- Formato do USB (NTFS vs FAT32)
- USB corrompido
- Porta USB defeituosa

**Solução:**
1. Formatar USB em FAT32
2. Testar em outra porta USB
3. Tentar outro pendrive
4. Usar cartão SD como alternativa

### Problema: Sincronização falha (JD/NH)

**Possíveis causas:**
- Sem conexão internet
- Servidor indisponível
- Credenciais incorretas

**Solução:**
1. Verificar conexão internet
2. Confirmar login/senha
3. Tentar sincronização manual
4. Usar importação via USB como alternativa

---

## Checklist Antes de Exportar

### Para Qualquer Monitor

- [ ] Validar com `validar_exportacao_final()`
- [ ] Confirmar CRS = WGS84 (EPSG:4326)
- [ ] Verificar encoding = Latin-1
- [ ] Confirmar atributos ≤ 10 caracteres
- [ ] Remover acentos dos nomes
- [ ] Verificar geometrias válidas
- [ ] Confirmar sem multipart
- [ ] Verificar arquivo .prj presente
- [ ] Testar em QGIS antes de enviar
- [ ] Fazer backup dos arquivos

### Específico John Deere

- [ ] Verificar features ≤ 500
- [ ] Se > 500, dividir arquivo
- [ ] Validar ISOXML se aplicação variada
- [ ] Confirmar login no Operations Center

### Específico New Holland

- [ ] Compactar em .zip
- [ ] Verificar conteúdo do ZIP
- [ ] Confirmar todos os arquivos presentes

### Específico Stara

- [ ] Preferir formato KML
- [ ] Validar em Google Earth
- [ ] Configurar AB Line no monitor

---

## Suporte

Para dúvidas específicas:

- **QGIS**: https://qgis.org/en/site/forums.html
- **John Deere**: Suporte local ou myjohndeere.com
- **New Holland**: Suporte local ou PLM Connect
- **Jacto**: Suporte local do fabricante
- **Stara**: Suporte local do fabricante

---

**Sistema AAP GIS v2.0**  
*Agricultura de Precisão com QGIS + SAGA GIS + PyQGIS*  
*2024*
