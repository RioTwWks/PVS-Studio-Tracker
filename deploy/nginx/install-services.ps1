# Установка двух экземпляров PVS-Studio Tracker через NSSM (требуется NSSM в PATH).
# Запуск от администратора:
#   .\install-services.ps1 -AppRoot "C:\opt\pvs-tracker" -Python "C:\opt\pvs-tracker\.venv\Scripts\python.exe"

param(
    [Parameter(Mandatory = $true)]
    [string] $AppRoot,

    [Parameter(Mandatory = $true)]
    [string] $Python,

    [int[]] $Ports = @(8081, 8082)
)

$ErrorActionPreference = "Stop"
$UvicornArgs = "-m uvicorn pvs_tracker.main:app --host 127.0.0.1 --port {0} --timeout-graceful-shutdown 30"

foreach ($port in $Ports) {
    $serviceName = "PVS-Tracker-$port"
    $args = $UvicornArgs -f $port

    Write-Host "Installing $serviceName on port $port ..."

    nssm install $serviceName $Python $args
    nssm set $serviceName AppDirectory $AppRoot
    nssm set $serviceName AppEnvironmentExtra "DATABASE_URL=postgresql+psycopg2://user:pass@localhost/pvs_tracker"
    nssm set $serviceName AppStdout "$AppRoot\logs\uvicorn-$port.log"
    nssm set $serviceName AppStderr "$AppRoot\logs\uvicorn-$port.err.log"
    nssm set $serviceName AppRotateFiles 1
    nssm set $serviceName AppRotateBytes 10485760
    nssm set $serviceName Start SERVICE_AUTO_START

    nssm start $serviceName
}

Write-Host "Done. Point nginx upstream to ports: $($Ports -join ', ')"
