# Rolling update Windows-контейнера app-1/app-2 за nginx на хосте (zero-downtime).
#
# Пример (PostgreSQL на хосте):
#   .\rolling-update.ps1 -Service app-1 -NginxConf "C:\nginx\conf\nginx.conf"
#   .\rolling-update.ps1 -Service app-2 -NginxConf "C:\nginx\conf\nginx.conf"
#
# С PostgreSQL в контейнере добавьте -WithPostgresContainer

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("app-1", "app-2")]
    [string] $Service,

    [Parameter(Mandatory = $true)]
    [string] $NginxConf,

    [int] $Port = 0,

    [string] $ComposeDir = "",

    [switch] $WithPostgresContainer,

    [string] $NginxExe = "nginx",

    [int] $DrainSeconds = 35,

    [int] $ReadyTimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"

$PortMap = @{
    "app-1" = 8081
    "app-2" = 8082
}

if ($Port -eq 0) {
    $Port = $PortMap[$Service]
}

if (-not $ComposeDir) {
    $ComposeDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}

$BaseCompose = Join-Path $ComposeDir "docker-compose.yml"
$PostgresCompose = Join-Path $ComposeDir "docker-compose.postgres.yml"

if (-not (Test-Path $BaseCompose)) {
    throw "Compose file not found: $BaseCompose"
}

$ComposeArgs = @("-f", $BaseCompose)
if ($WithPostgresContainer) {
    if (-not (Test-Path $PostgresCompose)) {
        throw "Postgres override not found: $PostgresCompose"
    }
    $ComposeArgs += @("-f", $PostgresCompose)
}

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

function Wait-ContainerHealthy {
    param([string] $Svc, [int] $TimeoutSec)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $cid = docker compose @ComposeArgs ps -q $Svc 2>$null
        if ($cid) {
            $status = docker inspect --format='{{.State.Health.Status}}' $cid 2>$null
            if ($status -eq "healthy") { return $true }
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Set-NginxBackendDown {
    param([int] $BackendPort, [bool] $Down)
    $conf = Get-Content -Raw -Path $NginxConf
    $marker = "server 127.0.0.1:$BackendPort"
    if ($conf -notmatch [regex]::Escape($marker)) {
        throw "Upstream entry not found: $marker"
    }

    if ($Down) {
        $updated = $conf -replace "($([regex]::Escape($marker)))(?! down)", '$1 down'
    } else {
        $updated = $conf -replace "server 127\.0\.0\.1:$BackendPort down", "server 127.0.0.1:$BackendPort"
    }

    if ($updated -ne $conf) {
        Set-Content -Path $NginxConf -Value $updated -NoNewline
        & $NginxExe -s reload
    }
}

Write-Host "Step 1: drain backend 127.0.0.1:$Port in nginx ..."
Set-NginxBackendDown -BackendPort $Port -Down $true
Write-Host "Waiting $DrainSeconds s for in-flight requests ..."
Start-Sleep -Seconds $DrainSeconds

Write-Host "Step 2: rebuild and restart container $Service ..."
Push-Location $ComposeDir
try {
    docker compose @ComposeArgs up -d --no-deps --build $Service
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose up failed for $Service"
    }
} finally {
    Pop-Location
}

Write-Host "Step 3: wait for readiness on host port $Port ..."
if (-not (Wait-Ready -TargetPort $Port -TimeoutSec $ReadyTimeoutSeconds)) {
    if (-not (Wait-ContainerHealthy -Svc $Service -TimeoutSec 30)) {
        throw "Container $Service did not become ready on port $Port"
    }
    if (-not (Wait-Ready -TargetPort $Port -TimeoutSec 60)) {
        throw "Container $Service is healthy but /health/ready on port $Port failed"
    }
}

Write-Host "Step 4: return backend to nginx upstream ..."
Set-NginxBackendDown -BackendPort $Port -Down $false

Write-Host "Rolling update for $Service (port $Port) completed."
Write-Host "Public URL: http://localhost:8080/webhook/inbound"
