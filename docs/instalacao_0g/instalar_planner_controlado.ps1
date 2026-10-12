# Instalacao controlada do FortSmart Precision Planner no perfil do QGIS (Etapa 0 / 0G).
#
# Sem -Executar o script so mostra o que faria (nada e alterado).
# Com -Executar:
#   1. recusa se o QGIS estiver aberto;
#   2. copia o plugin instalado e o QGIS3.ini do perfil para uma pasta de backup datada;
#   3. confere os hashes do backup;
#   4. instala a copia do repositorio (sem __pycache__ e .pyc) e confere os hashes instalados.
# Nao altera chaves de recurso: todas continuam desligadas ate o teste visual.
# Reversao: reverter_planner_controlado.ps1 -Backup <pasta impressa ao final> -Executar

param(
    [string]$Perfil = "default",
    [string]$PluginsRoot = "",
    [string]$BackupRoot = "",
    [switch]$Executar,
    [switch]$IgnorarQgisAberto
)
$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$src = Join-Path $repo "plugin\fortsmart_precision"
$profileDir = Join-Path $env:APPDATA "QGIS\QGIS3\profiles\$Perfil"
if (-not $PluginsRoot) { $PluginsRoot = Join-Path $profileDir "python\plugins" }
if (-not $BackupRoot) { $BackupRoot = Join-Path $repo "plugin\backups" }
$dst = Join-Path $PluginsRoot "fortsmart_precision"
$ini = Join-Path $profileDir "QGIS\QGIS3.ini"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backup = Join-Path $BackupRoot "perfil_${Perfil}_antes_instalacao_0G_$stamp"

function Get-Manifest([string]$root) {
    $result = @{}
    if (-not (Test-Path $root)) { return $result }
    $base = (Resolve-Path $root).Path
    Get-ChildItem $base -Recurse -File |
        Where-Object { $_.FullName -notmatch '\\__pycache__\\' -and $_.Extension -ne ".pyc" } |
        ForEach-Object { $result[$_.FullName.Substring($base.Length + 1)] = (Get-FileHash $_.FullName -Algorithm SHA256).Hash }
    return $result
}

function Compare-Manifest($expected, $actual, [string]$label) {
    $problems = @()
    foreach ($key in $expected.Keys) {
        if (-not $actual.ContainsKey($key)) { $problems += "faltando: $key" }
        elseif ($actual[$key] -ne $expected[$key]) { $problems += "diferente: $key" }
    }
    foreach ($key in $actual.Keys) { if (-not $expected.ContainsKey($key)) { $problems += "a mais: $key" } }
    if ($problems.Count) { throw "$label nao confere ($($problems.Count) problemas): $($problems | Select-Object -First 10)" }
    Write-Host "$label confere: $($expected.Count) arquivos."
}

if (-not (Test-Path (Join-Path $src "metadata.txt"))) { throw "Plugin do repositorio nao encontrado: $src" }
$source = Get-Manifest $src
$installed = Get-Manifest $dst
$version = (Select-String -Path (Join-Path $src "metadata.txt") -Pattern '^version=').Line

Write-Host "Origem (repositorio): $src  [$version, $($source.Count) arquivos]"
Write-Host "Destino (perfil '$Perfil'): $dst  [$($installed.Count) arquivos instalados]"
Write-Host "Backup sera criado em: $backup"

if (-not $Executar) {
    $new = @($source.Keys | Where-Object { -not $installed.ContainsKey($_) }).Count
    $changed = @($source.Keys | Where-Object { $installed.ContainsKey($_) -and $installed[$_] -ne $source[$_] }).Count
    $gone = @($installed.Keys | Where-Object { -not $source.ContainsKey($_) }).Count
    Write-Host "SIMULACAO: $new arquivo(s) novo(s), $changed alterado(s), $gone removido(s). Nada foi alterado."
    Write-Host "Para instalar: acrescente -Executar (com o QGIS fechado)."
    return
}

if (-not $IgnorarQgisAberto -and (Get-Process -Name "qgis*" -ErrorAction SilentlyContinue)) {
    throw "Feche o QGIS antes de instalar."
}

New-Item -ItemType Directory -Force -Path $backup | Out-Null
if (Test-Path $dst) {
    Copy-Item -Recurse -Force $dst (Join-Path $backup "fortsmart_precision")
    Compare-Manifest $installed (Get-Manifest (Join-Path $backup "fortsmart_precision")) "Backup do plugin instalado"
} else {
    New-Item -ItemType File -Path (Join-Path $backup "SEM_PLUGIN_ANTERIOR.txt") | Out-Null
}
if (Test-Path $ini) { Copy-Item -Force $ini (Join-Path $backup "QGIS3.ini") }
@{ perfil = $Perfil; destino = $dst; origem = $src; versao = $version; criado = $stamp } |
    ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $backup "instalacao.json")

$staging = Join-Path $env:TEMP "fortsmart_precision_staging_$stamp"
Copy-Item -Recurse -Force $src $staging
Get-ChildItem $staging -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Get-ChildItem $staging -Recurse -File -Filter "*.pyc" | Remove-Item -Force
Compare-Manifest $source (Get-Manifest $staging) "Copia de preparo"

New-Item -ItemType Directory -Force -Path $PluginsRoot | Out-Null
if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
Move-Item $staging $dst
Compare-Manifest $source (Get-Manifest $dst) "Plugin instalado"

Write-Host ""
Write-Host "Instalado. Backup: $backup"
Write-Host "Reverter: .\reverter_planner_controlado.ps1 -Backup `"$backup`" -Executar"
