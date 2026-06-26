# Пересобирает upstream-active.conf из ready backend'ов (кроме drained).
param(
    [string] $ConfigPath,
    [switch] $ReloadNginx
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'pvs-nginx-lib.ps1')

$cfg = Get-PvsNginxConfig -ConfigPath $ConfigPath
$ready = @(Get-PvsReadyPorts -Config $cfg)
$drained = @(Get-PvsDrainedPorts -Config $cfg)

if ($ready.Count -eq 0) {
    Write-Error 'No ready instances for upstream'
}

# В upstream включаем ready; drained помечаются down в файле.
$active = @($ready)
foreach ($p in $drained) {
    if ($active -notcontains $p) {
        # Drain без running процесса — не добавляем мёртвый backend.
        $st = Get-PvsServiceStatus -Config $cfg -Port $p
        if ($st.Running) {
            $active += $p
        }
    }
}

$null = Sync-PvsNginxUpstream -Config $cfg -ActivePorts $active -ReloadNginx:$ReloadNginx
Write-Host "Upstream backends: $($active -join ', ')"
