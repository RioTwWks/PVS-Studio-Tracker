# Rolling update одного экземпляра uvicorn за nginx без потери веб-хуков.
#
# Пример:
#   .\rolling-update.ps1 -Port 8081 -NginxConf "C:\nginx\conf\nginx.conf" -ServiceName "PVS-Tracker-8081"
#
# Перед запуском обновите код в $AppRoot (git pull, pip install и т.д.) — скрипт только перезапускает службу.

param(
    [Parameter(Mandatory = $true)]
    [int] $Port,

    [Parameter(Mandatory = $true)]
    [string] $NginxConf,

    [Parameter(Mandatory = $true)]
    [string] $ServiceName,

    [string] $NginxExe = "nginx",
    [int] $DrainSeconds = 35,
    [int] $ReadyTimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"

function Wait-Ready {
    param([int] $TargetPort, [int] $TimeoutSec)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:$TargetPort/health/ready" -UseBasicParsing -TimeoutSec 5
            if ($r.StatusCode -eq 200) { return $true }
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    return $false
}

Write-Host "Step 1: drain backend 127.0.0.1:$Port in nginx ..."
$conf = Get-Content -Raw -Path $NginxConf
$marker = "server 127.0.0.1:$Port"
if ($conf -notmatch [regex]::Escape($marker)) {
    throw "Upstream entry not found: $marker"
}

$drained = $conf -replace "($([regex]::Escape($marker)))(?! down)", '$1 down'
if ($drained -eq $conf) {
    Write-Host "Backend already marked down."
} else {
    Set-Content -Path $NginxConf -Value $drained -NoNewline
    & $NginxExe -s reload
    Write-Host "Waiting $DrainSeconds s for in-flight requests ..."
    Start-Sleep -Seconds $DrainSeconds
}

Write-Host "Step 2: restart $ServiceName ..."
Restart-Service -Name $ServiceName -Force

Write-Host "Step 3: wait for readiness on port $Port ..."
if (-not (Wait-Ready -TargetPort $Port -TimeoutSec $ReadyTimeoutSeconds)) {
    throw "Instance on port $Port did not become ready"
}

Write-Host "Step 4: return backend to upstream ..."
$conf = Get-Content -Raw -Path $NginxConf
$restored = $conf -replace "server 127\.0\.0\.1:$Port down", "server 127.0.0.1:$Port"
Set-Content -Path $NginxConf -Value $restored -NoNewline
& $NginxExe -s reload

Write-Host "Rolling update for port $Port completed."
