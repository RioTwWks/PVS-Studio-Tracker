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

function Get-HostGatewayIpv4 {
    try {
        $route = Get-NetRoute -AddressFamily IPv4 |
            Where-Object { $_.DestinationPrefix -eq '0.0.0.0/0' } |
            Sort-Object RouteMetric |
            Select-Object -First 1
        if ($route -and $route.NextHop -and $route.NextHop -ne '0.0.0.0') {
            return [string]$route.NextHop
        }
    } catch {
        Write-Warning "Get-HostGatewayIpv4 failed: $_"
    }
    return $null
}

function Resolve-DatabaseUrl {
    if (-not $env:DATABASE_URL) {
        Write-Warning "DATABASE_URL is not set"
        return
    }

    # Статический IP postgres (compose network pvs_internal) — без DNS.
    if ($env:POSTGRES_STATIC_IP -and $env:DATABASE_URL -match '@([^:/?#]+):') {
        $dbHost = $Matches[1]
        if ($dbHost -ne $env:POSTGRES_STATIC_IP) {
            $env:DATABASE_URL = $env:DATABASE_URL -replace "@${dbHost}:", "@$($env:POSTGRES_STATIC_IP):"
            Write-Host "DATABASE_URL: ${dbHost} -> static postgres IP $($env:POSTGRES_STATIC_IP)"
        }
    }

    # Опционально: gateway + published port (на Windows Server обычно timeout — оставлено для отладки).
    $useGateway = ($env:USE_HOST_GATEWAY_FOR_POSTGRES -eq '1')
    if ($useGateway -and $env:DATABASE_URL -match '@([^:/?#]+):') {
        $dbHost = $Matches[1]
        if ($dbHost -eq 'postgres' -or $dbHost -eq 'host.docker.internal') {
            $gateway = Get-HostGatewayIpv4
            if ($gateway) {
                $env:DATABASE_URL = $env:DATABASE_URL -replace "@${dbHost}:", "@${gateway}:"
                Write-Host "DATABASE_URL: ${dbHost} -> host gateway ${gateway} (published postgres port)"
            }
        }
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
