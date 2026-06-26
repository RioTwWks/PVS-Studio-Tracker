# Поддерживает минимум N healthy экземпляров: запускает spare из пула.
param(
    [string] $ConfigPath,
    [int] $MinHealthy = 0,
    [switch] $SyncUpstream,
    [switch] $ReloadNginx
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'pvs-nginx-lib.ps1')

$cfg = Get-PvsNginxConfig -ConfigPath $ConfigPath
if ($MinHealthy -le 0) {
    $MinHealthy = [int]$cfg.MinHealthyInstances
}

$ready = @(Get-PvsReadyPorts -Config $cfg)
Write-Host "Ready instances: $($ready -join ', ') (min $MinHealthy)"

foreach ($port in $cfg.PortPool) {
    if ($ready.Count -ge $MinHealthy) {
        break
    }
    $st = Get-PvsServiceStatus -Config $cfg -Port $port
    if (-not $st.Exists) {
        continue
    }
    if ($st.Ready) {
        continue
    }
    if (-not $st.Running) {
        Start-PvsInstanceService -Config $cfg -Port $port
    }
    if (Wait-PvsInstanceReady -Port $port -TimeoutSec ([int]$cfg.ReadyTimeoutSeconds)) {
        Write-Host "Port $port is ready"
        $ready = @(Get-PvsReadyPorts -Config $cfg)
    } else {
        Write-Warning "Port $port not ready within $($cfg.ReadyTimeoutSeconds)s"
        $name = Get-PvsServiceName -Config $cfg -Port $port
        try {
            $nssmExe = Resolve-NssmExe
            $appRoot = Get-PvsNssmSetting -NssmExe $nssmExe -ServiceName $name -Setting 'AppDirectory'
            $envFile = if ($appRoot) { Join-Path $appRoot '.env' } else { $null }
            Write-PvsDatabaseUrlHint -NssmExe $nssmExe -ServiceName $name -EnvFile $envFile
        } catch {
            Write-Host 'Hint: run .\sync-nssm-env.ps1 -AppRoot <AppRoot> -RestartServices'
        }
    }
}

$ready = @(Get-PvsReadyPorts -Config $cfg)
if ($ready.Count -lt $MinHealthy) {
    Write-Warning "Only $($ready.Count) ready instance(s); need $MinHealthy"
    exit 1
}

if ($SyncUpstream) {
    Sync-PvsNginxUpstream -Config $cfg -ActivePorts $ready -ReloadNginx:$ReloadNginx
}

exit 0
