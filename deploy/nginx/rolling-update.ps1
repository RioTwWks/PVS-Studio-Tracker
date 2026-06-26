# Rolling update одного экземпляра: spare + drain + restart + sync upstream.
#
# Пример:
#   .\rolling-update.ps1 -Port 8081
#
# Перед запуском обновите код в AppRoot (git pull, pip install).

param(
    [Parameter(Mandatory = $true)]
    [int] $Port,

    [string] $ConfigPath,
    [string] $NginxConf,
    [string] $ServiceName,
    [string] $NginxExe,
    [int] $DrainSeconds = 0,
    [int] $ReadyTimeoutSeconds = 0,
    [switch] $StopSpareAfterUpdate
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'pvs-nginx-lib.ps1')

$cfg = Get-PvsNginxConfig -ConfigPath $ConfigPath
if ($NginxConf) { $cfg.NginxConfDir = Split-Path $NginxConf -Parent }
if ($NginxExe) { $cfg.NginxExe = $NginxExe }
if ($DrainSeconds -gt 0) { $cfg.DrainSeconds = $DrainSeconds }
if ($ReadyTimeoutSeconds -gt 0) { $cfg.ReadyTimeoutSeconds = $ReadyTimeoutSeconds }

if (-not $ServiceName) {
    $ServiceName = Get-PvsServiceName -Config $cfg -Port $Port
}

$minHealthy = [int]$cfg.MinHealthyInstances
Write-Host "Step 0: ensure $($minHealthy + 1) healthy instances (spare for drain) ..."
& (Join-Path $PSScriptRoot 'ensure-min-instances.ps1') `
    -ConfigPath $ConfigPath `
    -MinHealthy ($minHealthy + 1) `
    -SyncUpstream `
    -ReloadNginx
if ($LASTEXITCODE -ne 0) {
    throw "Could not start spare instance before rolling update"
}

Write-Host "Step 1: drain port $Port ..."
Add-PvsDrainedPort -Config $cfg -Port $Port
& (Join-Path $PSScriptRoot 'sync-upstream.ps1') -ConfigPath $ConfigPath -ReloadNginx

Write-Host "Waiting $($cfg.DrainSeconds)s for in-flight requests ..."
Start-Sleep -Seconds ([int]$cfg.DrainSeconds)

Write-Host "Step 2: restart $ServiceName ..."
Restart-Service -Name $ServiceName -Force

Write-Host "Step 3: wait for readiness on port $Port ..."
if (-not (Wait-PvsInstanceReady -Port $Port -TimeoutSec ([int]$cfg.ReadyTimeoutSeconds))) {
    throw "Instance on port $Port did not become ready"
}

Write-Host "Step 4: undrain port $Port ..."
Remove-PvsDrainedPort -Config $cfg -Port $Port
& (Join-Path $PSScriptRoot 'sync-upstream.ps1') -ConfigPath $ConfigPath -ReloadNginx

if ($StopSpareAfterUpdate) {
    Write-Host "Step 5: stop excess spares ..."
    & (Join-Path $PSScriptRoot 'watch-instances.ps1') -ConfigPath $ConfigPath -StopExcessSpares
} else {
    & (Join-Path $PSScriptRoot 'ensure-min-instances.ps1') -ConfigPath $ConfigPath -SyncUpstream -ReloadNginx
}

Write-Host "Rolling update for port $Port completed."
