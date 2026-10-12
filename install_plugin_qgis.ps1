# Copia o plugin FortSmart Precision para o perfil padrao do QGIS (Windows).
$ErrorActionPreference = "Stop"
$src = Join-Path $PSScriptRoot "plugin\fortsmart_precision"
$dstRoot = Join-Path $env:APPDATA "QGIS\QGIS3\profiles\default\python\plugins"
$dst = Join-Path $dstRoot "fortsmart_precision"

if (-not (Test-Path $src)) {
    throw "Pasta de origem nao encontrada: $src"
}
New-Item -ItemType Directory -Force -Path $dstRoot | Out-Null
if (Test-Path $dst) {
    Remove-Item -Recurse -Force $dst
}
Copy-Item -Recurse -Force $src $dst
Write-Host "Plugin instalado em:"
Write-Host $dst
Write-Host ""
Write-Host "Agora: reinicie o QGIS, ative FortSmart Precision em Plugins > Gerenciar, e abra Planejamento Precision Lines."
