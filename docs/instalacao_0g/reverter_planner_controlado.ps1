# Reverte a instalacao controlada da 0G: devolve o plugin e (opcionalmente) o QGIS3.ini do backup.
#
# Sem -Executar o script so mostra o que faria.
# -RestaurarIni tambem devolve o QGIS3.ini do backup (desfaz chaves ligadas durante o teste visual,
#  mas tambem qualquer outra configuracao do QGIS alterada depois do backup).

param(
    [Parameter(Mandatory = $true)][string]$Backup,
    [string]$PluginsRoot = "",
    [switch]$RestaurarIni,
    [switch]$Executar,
    [switch]$IgnorarQgisAberto
)
$ErrorActionPreference = "Stop"

$info = Get-Content (Join-Path $Backup "instalacao.json") -Raw | ConvertFrom-Json
$dst = if ($PluginsRoot) { Join-Path $PluginsRoot "fortsmart_precision" } else { $info.destino }
$saved = Join-Path $Backup "fortsmart_precision"
$ini = Join-Path $env:APPDATA "QGIS\QGIS3\profiles\$($info.perfil)\QGIS\QGIS3.ini"

function Get-Manifest([string]$root) {
    $result = @{}
    if (-not (Test-Path $root)) { return $result }
    $base = (Resolve-Path $root).Path
    Get-ChildItem $base -Recurse -File |
        Where-Object { $_.FullName -notmatch '\\__pycache__\\' -and $_.Extension -ne ".pyc" } |
        ForEach-Object { $result[$_.FullName.Substring($base.Length + 1)] = (Get-FileHash $_.FullName -Algorithm SHA256).Hash }
    return $result
}

$hadPlugin = Test-Path $saved
Write-Host "Backup: $Backup"
Write-Host "Destino: $dst"
Write-Host ($(if ($hadPlugin) { "Sera restaurado o plugin anterior ($((Get-Manifest $saved).Count) arquivos)." } else { "Nao havia plugin anterior: a pasta instalada sera removida." }))
if ($RestaurarIni) { Write-Host "O QGIS3.ini do backup sera restaurado em: $ini" }

if (-not $Executar) {
    Write-Host "SIMULACAO: nada foi alterado. Para reverter: acrescente -Executar (com o QGIS fechado)."
    return
}
if (-not $IgnorarQgisAberto -and (Get-Process -Name "qgis*" -ErrorAction SilentlyContinue)) {
    throw "Feche o QGIS antes de reverter."
}

if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
if ($hadPlugin) {
    Copy-Item -Recurse -Force $saved $dst
    $expected = Get-Manifest $saved
    $actual = Get-Manifest $dst
    $bad = @($expected.Keys | Where-Object { $actual[$_] -ne $expected[$_] }).Count + [Math]::Abs($expected.Count - $actual.Count)
    if ($bad) { throw "Restauracao nao confere ($bad diferencas)." }
    Write-Host "Plugin anterior restaurado e conferido: $($expected.Count) arquivos."
}
if ($RestaurarIni -and (Test-Path (Join-Path $Backup "QGIS3.ini"))) {
    Copy-Item -Force (Join-Path $Backup "QGIS3.ini") $ini
    Write-Host "QGIS3.ini restaurado."
}
Write-Host "Reversao concluida."
