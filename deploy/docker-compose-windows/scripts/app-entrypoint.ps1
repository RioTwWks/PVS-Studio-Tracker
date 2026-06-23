# Entrypoint for app/worker Windows containers: open port 8080 for Docker NAT, then exec CMD.
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

function Test-DatabaseTcp {
    param([string]$HostName, [int]$Port = 5432)

    try {
        $tcp = Test-NetConnection -ComputerName $HostName -Port $Port -WarningAction SilentlyContinue
        Write-Host "TCP probe ${HostName}:${Port} -> TcpTestSucceeded=$($tcp.TcpTestSucceeded)"
        return [bool]$tcp.TcpTestSucceeded
    } catch {
        Write-Warning "TCP probe ${HostName}:${Port} failed: $_"
        return $false
    }
}

function Resolve-DatabaseUrl {
    $pgUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "pvs" }
    $pgPass = if ($env:POSTGRES_PASSWORD) { $env:POSTGRES_PASSWORD } else { "pvs" }
    $pgDb = if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "pvs_tracker" }

    $candidates = New-Object System.Collections.Generic.List[string]
    [void]$candidates.Add("host.docker.internal")

    try {
        $route = Get-NetRoute -AddressFamily IPv4 |
            Where-Object { $_.DestinationPrefix -eq "0.0.0.0/0" } |
            Select-Object -First 1
        if ($route -and $route.NextHop -and $route.NextHop -ne "0.0.0.0") {
            [void]$candidates.Add([string]$route.NextHop)
        }
    } catch {
        Write-Warning "Could not detect default gateway: $_"
    }

    [void]$candidates.Add("postgres")

    foreach ($hostName in $candidates) {
        if (-not $hostName) { continue }
        if (Test-DatabaseTcp -HostName $hostName) {
            $env:DATABASE_URL = "postgresql+psycopg2://${pgUser}:${pgPass}@${hostName}:5432/${pgDb}"
            Write-Host "DATABASE_URL set to host $hostName"
            return
        }
    }

    Write-Warning "Database TCP probe failed for all candidates: $($candidates -join ', ')"
    if ($env:DATABASE_URL) {
        Write-Host "Keeping existing DATABASE_URL from environment"
    }
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

Write-Host "Smoke test: import pvs_tracker.main"
& $exe -u -c "import pvs_tracker.main; print('import ok')" 2>&1 | ForEach-Object { Write-Host $_ }
if ($LASTEXITCODE -ne 0) {
    Write-Error "Import pvs_tracker.main failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "Starting: $exe $($cmdArgs -join ' ')"
& $exe @cmdArgs
$exitCode = if ($null -ne $LASTEXITCODE) { $LASTEXITCODE } else { 0 }
exit $exitCode
