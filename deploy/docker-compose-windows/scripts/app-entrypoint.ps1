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

$defaultCmd = @(
    "C:\Program Files\Python312\python.exe",
    "-m",
    "uvicorn",
    "pvs_tracker.main:app",
    "--host",
    "0.0.0.0",
    "--port",
    "8080",
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

Write-Host "Starting: $exe $($cmdArgs -join ' ')"
& $exe @cmdArgs
$exitCode = if ($null -ne $LASTEXITCODE) { $LASTEXITCODE } else { 0 }
exit $exitCode
