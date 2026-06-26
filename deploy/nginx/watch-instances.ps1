# Watchdog: min healthy instances + актуальный nginx upstream.
param(
    [string] $ConfigPath,
    [switch] $StopExcessSpares
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'pvs-nginx-lib.ps1')

$cfg = Get-PvsNginxConfig -ConfigPath $ConfigPath
$drained = @(Get-PvsDrainedPorts -Config $cfg)

if ($StopExcessSpares -and $drained.Count -eq 0) {
    $desired = [int]$cfg.DesiredRunningInstances
    $ready = @(Get-PvsReadyPorts -Config $cfg)
    if ($ready.Count -gt $desired) {
        $toStop = $ready | Sort-Object -Descending | Select-Object -Skip $desired
        foreach ($port in $toStop) {
            Write-Host "Stopping excess spare on port $port"
            Stop-PvsInstanceService -Config $cfg -Port $port
        }
    }
}

& (Join-Path $PSScriptRoot 'ensure-min-instances.ps1') -ConfigPath $ConfigPath -SyncUpstream -ReloadNginx
exit $LASTEXITCODE
