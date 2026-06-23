# Entrypoint for app/worker Windows containers: open port 8080 for Docker NAT.
$ErrorActionPreference = "Stop"

$netsh = Join-Path $env:SystemRoot "System32\netsh.exe"
& $netsh advfirewall set allprofiles state off | Out-Null
& $netsh advfirewall firewall add rule name="PVS App 8080" dir=in action=allow protocol=TCP localport=8080 | Out-Null
Write-Host "Windows Firewall: allow inbound TCP 8080 in app container"

if ($args.Count -eq 0) {
    throw "No command specified for app entrypoint"
}

$exe = $args[0]
$cmdArgs = @()
if ($args.Count -gt 1) {
    $cmdArgs = $args[1..($args.Count - 1)]
}
& $exe @cmdArgs
exit $LASTEXITCODE
