# Скачивает NSSM и ставит nssm.exe в C:\nssm (или -InstallDir).
# PowerShell от администратора:
#   .\install-nssm.ps1
#   .\install-nssm.ps1 -HttpProxy http://proxy.corp.local:8080

param(
    [string] $InstallDir = 'C:\nssm',
    [string] $HttpProxy = '',
    [string] $ZipUrl = 'https://nssm.cc/release/nssm-2.24.zip'
)

$ErrorActionPreference = 'Stop'

if (-not $HttpProxy) {
    if ($env:HTTPS_PROXY) { $HttpProxy = $env:HTTPS_PROXY }
    elseif ($env:HTTP_PROXY) { $HttpProxy = $env:HTTP_PROXY }
}

$zipPath = Join-Path $env:TEMP 'nssm-2.24.zip'
$extractDir = Join-Path $env:TEMP 'nssm-2.24-extract'

Write-Host "Downloading $ZipUrl ..."
if ($HttpProxy) {
    Invoke-WebRequest -Uri $ZipUrl -OutFile $zipPath -Proxy $HttpProxy -UseBasicParsing
} else {
    Invoke-WebRequest -Uri $ZipUrl -OutFile $zipPath -UseBasicParsing
}

if (Test-Path $extractDir) {
    Remove-Item -Recurse -Force $extractDir
}
Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force

$nssmSrc = Get-ChildItem -Path $extractDir -Recurse -Filter 'nssm.exe' |
    Where-Object { $_.FullName -match '\\win64\\' } |
    Select-Object -First 1
if (-not $nssmSrc) {
    $nssmSrc = Get-ChildItem -Path $extractDir -Recurse -Filter 'nssm.exe' | Select-Object -First 1
}
if (-not $nssmSrc) {
    throw "nssm.exe not found inside $zipPath"
}

if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}
$target = Join-Path $InstallDir 'nssm.exe'
Copy-Item -Path $nssmSrc.FullName -Destination $target -Force

Write-Host "Installed: $target"
Write-Host ""
Write-Host "Optional: add to machine PATH (Administrator):"
Write-Host "  [Environment]::SetEnvironmentVariable('Path', `$env:Path + ';$InstallDir', 'Machine')"
Write-Host ""
Write-Host "Next:"
Write-Host "  .\install-services.ps1 -NssmPath `"$target`" -AppRoot ... -Python ..."
