# Скачивает nginx for Windows и распаковывает в C:\nginx (или -InstallDir).
# PowerShell от администратора:
#   .\install-nginx.ps1
#   .\install-nginx.ps1 -HttpProxy http://proxy.corp.local:8080

param(
    [string] $InstallDir = 'C:\nginx',
    [string] $Version = '1.27.5',
    [string] $HttpProxy = '',
    [switch] $SkipStart
)

$ErrorActionPreference = 'Stop'

if (-not $HttpProxy) {
    if ($env:HTTPS_PROXY) { $HttpProxy = $env:HTTPS_PROXY }
    elseif ($env:HTTP_PROXY) { $HttpProxy = $env:HTTP_PROXY }
}

$zipName = "nginx-$Version.zip"
$zipUrl = "https://nginx.org/download/$zipName"
$zipPath = Join-Path $env:TEMP $zipName
$extractDir = Join-Path $env:TEMP "nginx-$Version-extract"

$nginxExe = Join-Path $InstallDir 'nginx.exe'
if (Test-Path -LiteralPath $nginxExe) {
    Write-Host "nginx already present: $nginxExe"
} else {
    Write-Host "Downloading $zipUrl ..."
    if ($HttpProxy) {
        Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -Proxy $HttpProxy -UseBasicParsing
    } else {
        Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing
    }

    if (Test-Path $extractDir) {
        Remove-Item -Recurse -Force $extractDir
    }
    Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force

    $inner = Join-Path $extractDir "nginx-$Version"
    if (-not (Test-Path -LiteralPath $inner)) {
        throw "Unexpected archive layout: $inner"
    }

    if (-not (Test-Path $InstallDir)) {
        New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    }

    Write-Host "Installing to $InstallDir ..."
    Copy-Item -Path (Join-Path $inner '*') -Destination $InstallDir -Recurse -Force
    Write-Host "Installed: $nginxExe"
}

if (-not $SkipStart) {
    & (Join-Path $PSScriptRoot 'start-nginx.ps1') -CopyConf
}
