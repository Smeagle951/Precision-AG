@echo off
chcp 65001 >nul
title Instalador AAP GIS Plugin
cls

echo ================================================
echo  AAP GIS - Instalador Automatico de Plugin
echo ================================================
echo.

set ORIGEM=C:\Users\fortu\Desktop\PYTON\AAP_GIS_Plugin
set DESTINO=C:\Users\fortu\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\AAP_GIS_Plugin

echo [1/4] Verificando pasta de origem...
if not exist "%ORIGEM%" (
    echo ERRO: Pasta de origem nao encontrada:
    echo %ORIGEM%
    echo.
    echo Certifique-se de que a pasta AAP_GIS_Plugin existe em Desktop\PYTON
    pause
    exit /b 1
)
echo OK: Pasta encontrada
echo.

echo [2/4] Criando pasta de destino...
if not exist "%DESTINO%" mkdir "%DESTINO%"
echo OK: Pasta de destino pronta
echo.

echo [3/4] Copiando arquivos...
xcopy "%ORIGEM%\*" "%DESTINO%\" /E /I /Y >nul
echo OK: Arquivos copiados
echo.

echo [4/4] Verificando instalacao...
dir "%DESTINO%" /b
echo.

echo ================================================
echo  INSTALACAO CONCLUIDA!
echo ================================================
echo.
echo PROXIMOS PASSOS:
echo 1. Feche o QGIS se estiver aberto
echo 2. Abra o QGIS novamente
echo 3. Vá em: Plugins ^> Manage and Install Plugins
echo 4. Clique na aba "Installed"
echo 5. Procure "AAP GIS" e ative o checkbox
echo 6. O botao aparecera na barra de ferramentas
echo.
pause
