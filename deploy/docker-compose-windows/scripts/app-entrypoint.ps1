# Entrypoint for app/worker Windows containers: firewall + exec CMD.
# Не используем Test-NetConnection — на Windows Docker он может зависать на DNS (host.docker.internal).
$ErrorActionPreference = "Continue"

function Enable-AppFirewall {
    try {
        $netsh = Join-Path $env:SystemRoot "System32\netsh.exe"
        & $netsh advfirewall set allprofiles state off 2>$null | Out-Null
        & $netsh advfirewall firewall add rule name="PVS App 8080" dir=in action=allow protocol=TCP localport=8080 2>$null | Out-Null
        Write-Host "Windows Firewall: inbound TCP 8080 allowed in app container"
    } catch {
        Write-Warning "Firewall setup skipped: $_"
    }
}

function Resolve-DatabaseUrl {
    if (-not $env:DATABASE_URL) {
        Write-Warning "DATABASE_URL is not set"
        return
    }

    # Windows Server Docker: host.docker.internal отсутствует (нет DNS). Заменяем без Test-NetConnection.
    if ($env:DATABASE_URL -match '@host\.docker\.internal:') {
        $target = $env:POSTGRES_HOST
        if (-not $target -or $target -eq 'host.docker.internal') {
            $target = 'postgres'
        }
        $env:DATABASE_URL = $env:DATABASE_URL -replace '@host\.docker\.internal:', "@${target}:"
        Write-Host "DATABASE_URL: host.docker.internal replaced with $target"
    }

    $masked = $env:DATABASE_URL -replace '^([^:]+://[^:]+:)[^@]+', '$1***'
    Write-Host "DATABASE_URL: $masked"
}

$defaultCmd = @(
    "C:\Program Files\Python312\python.exe",
    "-u",
    "-m",
    "uvicorn",
    "pvs_tracker.main:app",
    "--host",
    "0.0.0.0",
    "--port",
    "8080",
    "--log-level",
    "info",
    "--timeout-graceful-shutdown",
    "30"
)

Enable-AppFirewall

if ($args.Count -eq 0) {
    Write-Host "No CMD args from Docker; using default uvicorn command"
    $args = $defaultCmd
}

$exe = $args[0]
$cmdArgs = @()
if ($args.Count -gt 1) {
    $cmdArgs = $args[1..($args.Count - 1)]
}

Write-Host "Python:"
& $exe --version 2>&1 | ForEach-Object { Write-Host $_ }

Resolve-DatabaseUrl

Write-Host "Starting: $exe $($cmdArgs -join ' ')"
& $exe @cmdArgs
$exitCode = if ($null -ne $LASTEXITCODE) { $LASTEXITCODE } else { 0 }
exit $exitCode
