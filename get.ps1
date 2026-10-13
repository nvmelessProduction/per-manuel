# Comando unico: scarica l'ultima versione da GitHub e avvia l'installazione.
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/nvmelessproduction/per-manuel/telegram-mt5-copier/get.ps1 | iex"

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$zipUrl = 'https://github.com/nvmelessproduction/per-manuel/archive/refs/heads/telegram-mt5-copier.zip'
$zip = Join-Path $env:TEMP 'seers_copier.zip'
$dir = Join-Path $env:TEMP 'seers_copier_src'

Write-Host 'Scarico il programma da GitHub...' -ForegroundColor Cyan
Invoke-WebRequest -Uri $zipUrl -OutFile $zip -UseBasicParsing
if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }
Expand-Archive -Path $zip -DestinationPath $dir -Force
$src = (Get-ChildItem $dir -Directory | Select-Object -First 1).FullName
Get-ChildItem $src -Recurse | Unblock-File

& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $src 'install.ps1')
