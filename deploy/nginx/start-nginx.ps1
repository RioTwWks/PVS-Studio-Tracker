# Запуск или reload nginx (reverse proxy :8080 -> uvicorn pool).
# PowerShell от администратора:
#   .\start-nginx.ps1
#   .\start-nginx.ps1 -CopyConf

param(
    [string] $ConfigPath,
    [switch] $CopyConf
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'pvs-nginx-lib.ps1')

$cfg = Get-PvsNginxConfig -ConfigPath $ConfigPath
$paths = Get-PvsNginxPaths -Config $cfg

$srcConf = Join-Path $PSScriptRoot 'nginx.conf'
$dstConf = Join-Path $paths.ConfDir 'nginx.conf'
if ($CopyConf -or -not (Test-Path -LiteralPath $dstConf)) {
    if (-not (Test-Path -LiteralPath $srcConf)) {
        throw "Template not found: $srcConf"
    }
    Copy-Item -LiteralPath $srcConf -Destination $dstConf -Force
    Write-Host "Copied nginx.conf -> $dstConf"
}

Start-PvsNginx -Config $cfg

try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8080/health/ready' -UseBasicParsing -TimeoutSec 10
    Write-Host "OK: http://127.0.0.1:8080/health/ready -> $($r.StatusCode) $($r.Content)"
} catch {
    Write-Warning "nginx listens but /health/ready failed: $($_.Exception.Message)"
}

Write-Host "UI: http://localhost:8080/"
