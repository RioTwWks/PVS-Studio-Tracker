# Установка пула экземпляров PVS-Studio Tracker через NSSM.
# Запуск от администратора:
#   .\install-services.ps1 -AppRoot "C:\opt\pvs-tracker" -Python "C:\opt\pvs-tracker\.venv\Scripts\python.exe"
#
# По умолчанию ставит службы на PortPool из instances.config.ps1,
# запускает MinHealthyInstances штук, копирует upstream-active.conf.

param(
    [Parameter(Mandatory = $true)]
    [string] $AppRoot,

    [Parameter(Mandatory = $true)]
    [string] $Python,

    [string] $ConfigPath,
    [string] $EnvFile,
    [string] $NginxConfDir,
    [int[]] $Ports
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'pvs-nginx-lib.ps1')

$cfg = Get-PvsNginxConfig -ConfigPath $ConfigPath
if ($NginxConfDir) {
    $cfg.NginxConfDir = $NginxConfDir
}
if ($Ports) {
    $cfg.PortPool = $Ports
}

if (-not $EnvFile) {
    $EnvFile = Join-Path $AppRoot '.env'
}

$databaseUrl = $null
if (Test-Path $EnvFile) {
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match '^\s*DATABASE_URL\s*=\s*(.+)\s*$') {
            $databaseUrl = $Matches[1].Trim().Trim('"').Trim("'")
            break
        }
    }
}
if (-not $databaseUrl) {
    Write-Warning "DATABASE_URL not found in $EnvFile — set AppEnvironmentExtra manually in NSSM"
    $databaseUrl = 'postgresql+psycopg2://user:pass@localhost/pvs_tracker'
}

$logsDir = Join-Path $AppRoot 'logs'
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
}

$nginxDir = $cfg.NginxConfDir
if (-not (Test-Path $nginxDir)) {
    New-Item -ItemType Directory -Path $nginxDir -Force | Out-Null
}

$upstreamTemplate = Join-Path $PSScriptRoot 'upstream-active.conf'
$upstreamTarget = Get-PvsUpstreamIncludePath -Config $cfg
if (Test-Path $upstreamTemplate) {
    Copy-Item -Path $upstreamTemplate -Destination $upstreamTarget -Force
    Write-Host "Copied upstream template -> $upstreamTarget"
}

$started = 0
$minStart = [int]$cfg.MinHealthyInstances

foreach ($port in $cfg.PortPool) {
    $serviceName = Get-PvsServiceName -Config $cfg -Port $port
    $uvicornArgs = "-m uvicorn pvs_tracker.main:app --host 127.0.0.1 --port $port --timeout-graceful-shutdown 30"

    Write-Host "Installing $serviceName on port $port ..."

    $existing = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "  Service exists, updating NSSM params"
        nssm set $serviceName Application $Python
        nssm set $serviceName AppParameters $uvicornArgs
    } else {
        nssm install $serviceName $Python $uvicornArgs
    }

    nssm set $serviceName AppDirectory $AppRoot
    nssm set $serviceName AppEnvironmentExtra "DATABASE_URL=$databaseUrl"
    nssm set $serviceName AppStdout (Join-Path $logsDir "uvicorn-$port.log")
    nssm set $serviceName AppStderr (Join-Path $logsDir "uvicorn-$port.err.log")
    nssm set $serviceName AppRotateFiles 1
    nssm set $serviceName AppRotateBytes 10485760
    nssm set $serviceName AppExit Default Restart
    nssm set $serviceName AppRestartDelay 5000
    nssm set $serviceName Start SERVICE_AUTO_START

    if ($started -lt $minStart) {
        nssm start $serviceName
        $started++
    } else {
        Write-Host "  Installed as hot spare (manual or watchdog start)"
    }
}

Write-Host ""
Write-Host "Installed pool ports: $($cfg.PortPool -join ', ')"
Write-Host "Started $started instance(s); min healthy = $minStart"
Write-Host "Next:"
Write-Host "  1. Copy nginx.conf to $($cfg.NginxConfDir) (include upstream-active.conf)"
Write-Host "  2. .\sync-upstream.ps1 -ReloadNginx"
Write-Host "  3. .\register-watchdog.ps1"
