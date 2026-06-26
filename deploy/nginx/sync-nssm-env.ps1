# Синхронизирует .env -> AppEnvironmentExtra для всех служб пула NSSM.
param(
    [Parameter(Mandatory = $true)]
    [string] $AppRoot,

    [string] $ConfigPath,
    [string] $EnvFile,
    [string] $NssmPath,
    [string] $Python,
    [switch] $RestartServices
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'pvs-nginx-lib.ps1')

$cfg = Get-PvsNginxConfig -ConfigPath $ConfigPath
$nssmExe = Resolve-NssmExe -NssmPath $NssmPath

if (-not $EnvFile) {
    $EnvFile = Join-Path $AppRoot '.env'
}
if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw ".env not found: $EnvFile"
}

$envVars = Read-PvsDotEnvFile -Path $EnvFile
if (-not $envVars['DATABASE_URL']) {
    throw "DATABASE_URL missing in $EnvFile"
}

if (-not $Python) {
    $Python = Join-Path $AppRoot '.venv\Scripts\python.exe'
}
if (Test-Path -LiteralPath $Python) {
    Test-PvsDatabaseConnection -Python $Python -DatabaseUrl ([string]$envVars['DATABASE_URL'])
} else {
    Write-Warning "Python not found ($Python) - skipping DB connection test"
}

foreach ($port in $cfg.PortPool) {
    $serviceName = Get-PvsServiceName -Config $cfg -Port $port
    $svc = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
    if (-not $svc) {
        Write-Warning "Skip $serviceName (not installed)"
        continue
    }
    Write-Host "Updating AppEnvironmentExtra for $serviceName ..."
    Set-PvsNssmAppEnvironment -NssmExe $nssmExe -ServiceName $serviceName -EnvVars $envVars
    if ($RestartServices) {
        Write-Host "Restarting $serviceName ..."
        Invoke-NssmStopSafe -NssmExe $nssmExe -ServiceName $serviceName | Out-Null
        Start-Sleep -Seconds 2
        Start-PvsNssmService -NssmExe $nssmExe -ServiceName $serviceName -Port $port `
            -WaitSeconds ([int]$cfg.ReadyTimeoutSeconds)
    }
}

Write-Host "NSSM environment synced from $EnvFile"
