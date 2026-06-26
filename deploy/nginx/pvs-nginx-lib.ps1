# Shared helpers for nginx + NSSM instance pool on Windows Server.

function Resolve-NssmExe {
    param([string] $NssmPath)

    if ($NssmPath) {
        if (-not (Test-Path -LiteralPath $NssmPath)) {
            throw "NSSM not found: $NssmPath"
        }
        return (Resolve-Path -LiteralPath $NssmPath).Path
    }

    $cmd = Get-Command nssm -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) {
        return $cmd.Source
    }

    $candidates = @(
        'C:\nssm\nssm.exe',
        'C:\nssm\win64\nssm.exe',
        'C:\Program Files\nssm\nssm.exe',
        'C:\Program Files\NSSM\nssm.exe',
        (Join-Path $env:ProgramFiles 'nssm\nssm.exe')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw @"
NSSM not found in PATH.

Install (PowerShell as Administrator):
  cd deploy\nginx
  .\install-nssm.ps1

Or download https://nssm.cc/release/nssm-2.24.zip and copy win64\nssm.exe to C:\nssm\nssm.exe

Then re-run install-services.ps1 with:
  -NssmPath C:\nssm\nssm.exe
"@
}

function Invoke-Nssm {
    param(
        [string] $NssmExe,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]] $NssmArgs
    )
    & $NssmExe @NssmArgs
    if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "nssm failed (exit $LASTEXITCODE): $($NssmArgs -join ' ')"
    }
}

function Test-PvsInstanceLive {
    param(
        [int] $Port,
        [int] $TimeoutSec = 3
    )
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health/live" -UseBasicParsing -TimeoutSec $TimeoutSec
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Resume-PvsNssmService {
    param(
        [string] $NssmExe,
        [string] $ServiceName
    )
    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $svc -or $svc.Status -ne 'Paused') {
        return
    }

    try {
        Resume-Service -Name $ServiceName -ErrorAction Stop
        Write-Host "$ServiceName resumed (Resume-Service)"
        return
    } catch {
        Write-Host "$ServiceName Resume-Service failed, trying nssm continue"
    }

    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $lines = @(& $NssmExe continue $ServiceName 2>&1 | ForEach-Object { "$_" })
    } finally {
        $ErrorActionPreference = $prevEap
    }
    foreach ($line in $lines) {
        Write-Host $line
    }
    $text = (($lines -join ' ') -replace '\s+', ' ').ToLowerInvariant()
    if ($text -match 'service_paused|unexpected status') {
        Write-Host "$ServiceName SCM stays Paused (NSSM quirk) - HTTP health is used instead"
    }
}

function Invoke-NssmStartSafe {
    param(
        [string] $NssmExe,
        [string] $ServiceName
    )
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $lines = @(& $NssmExe start $ServiceName 2>&1 | ForEach-Object { "$_" })
    } finally {
        $ErrorActionPreference = $prevEap
    }
    foreach ($line in $lines) {
        Write-Host $line
    }
    $text = (($lines -join ' ') -replace '\s+', ' ').ToLowerInvariant()
    return @{
        AlreadyRunning = ($text -match 'already running')
        Output         = $lines
    }
}

function Test-PvsNssmServiceHealthy {
    param(
        [string] $ServiceName,
        [int] $Port = 0
    )
    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $svc) {
        return $false
    }
    if ($Port -gt 0 -and (Test-PvsInstanceLive -Port $Port)) {
        # Порт отвечает, но SCM Stopped — не наш процесс или зомби; нужен nssm start.
        if ($svc.Status -in @('Running', 'Paused', 'StartPending')) {
            return $true
        }
        return $false
    }
    return ($svc.Status -eq 'Running')
}

function Start-PvsNssmService {
    <#
    NSSM on Windows Server may leave SCM in Paused while uvicorn is already listening.
    Prefer HTTP /health/live over nssm start when the process is up.
    #>
    param(
        [string] $NssmExe,
        [string] $ServiceName,
        [int] $Port = 0,
        [int] $WaitSeconds = 30
    )

    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $svc) {
        throw "Service not found: $ServiceName"
    }

    if (Test-PvsNssmServiceHealthy -ServiceName $ServiceName -Port $Port) {
        if ($svc.Status -eq 'Paused') {
            Write-Host "$ServiceName OK on port $Port (SCM Paused - normal for NSSM, resume skipped)"
        } else {
            Write-Host "$ServiceName already healthy (SCM: $($svc.Status), port: $Port)"
        }
        return
    }

    if ($svc.Status -eq 'Running') {
        Write-Host "$ServiceName SCM Running; waiting for /health/live on port $Port"
    } elseif ($svc.Status -eq 'Paused') {
        Write-Host "$ServiceName is Paused - resume before start"
        Resume-PvsNssmService -NssmExe $NssmExe -ServiceName $ServiceName
        if (Test-PvsNssmServiceHealthy -ServiceName $ServiceName -Port $Port) {
            return
        }
    } else {
        Write-Host "Starting $ServiceName ..."
        $startResult = Invoke-NssmStartSafe -NssmExe $NssmExe -ServiceName $ServiceName
        if ($startResult.AlreadyRunning) {
            Write-Host "$ServiceName nssm reports already running"
            if (Test-PvsNssmServiceHealthy -ServiceName $ServiceName -Port $Port) {
                return
            }
            if ($svc.Status -eq 'Paused') {
                Resume-PvsNssmService -NssmExe $NssmExe -ServiceName $ServiceName
            }
        }
    }

    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    while ((Get-Date) -lt $deadline) {
        $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
        if (-not $svc) {
            throw "Service disappeared: $ServiceName"
        }
        if (Test-PvsNssmServiceHealthy -ServiceName $ServiceName -Port $Port) {
            Write-Host "$ServiceName is healthy (SCM: $($svc.Status))"
            return
        }
        if ($svc.Status -eq 'Paused') {
            Resume-PvsNssmService -NssmExe $NssmExe -ServiceName $ServiceName
        }
        if ($svc.Status -eq 'Stopped') {
            Start-Sleep -Seconds 2
            Invoke-NssmStartSafe -NssmExe $NssmExe -ServiceName $ServiceName | Out-Null
        }
        Start-Sleep -Seconds 1
    }

    $svc = Get-Service -Name $ServiceName
    throw "Service $ServiceName did not become healthy (SCM: $($svc.Status), port: $Port). Check logs in AppRoot\logs\"
}

function Get-PvsNginxConfig {
    param([string] $ConfigPath)

    if (-not $ConfigPath) {
        $ConfigPath = Join-Path $PSScriptRoot 'instances.config.ps1'
    }
    if (-not (Test-Path $ConfigPath)) {
        throw "Config not found: $ConfigPath"
    }
    $cfg = . $ConfigPath
    if ($cfg -isnot [hashtable]) {
        throw "instances.config.ps1 must return a hashtable"
    }
    return $cfg
}

function Get-PvsServiceName {
    param(
        [hashtable] $Config,
        [int] $Port
    )
    return "{0}-{1}" -f $Config.ServicePrefix, $Port
}

function Get-PvsNginxPaths {
    param([hashtable] $Config)

    $confDir = $Config.NginxConfDir
    $root = if ($Config.NginxRoot) { $Config.NginxRoot } else { Split-Path $confDir -Parent }

    $exe = $Config.NginxExe
    if (-not $exe -or -not (Test-Path -LiteralPath $exe)) {
        $candidate = Join-Path $root 'nginx.exe'
        if (Test-Path -LiteralPath $candidate) {
            $exe = $candidate
        } else {
            $exe = 'nginx'
        }
    }

    return @{
        Root    = $root
        Exe     = $exe
        ConfDir = $confDir
        LogsDir = Join-Path $root 'logs'
    }
}

function Test-PvsNginxListening {
    param([int] $Port = 8080)
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health/live" -UseBasicParsing -TimeoutSec 3
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Invoke-PvsNginxTest {
    param([hashtable] $Config)
    $paths = Get-PvsNginxPaths -Config $Config
    if (-not (Test-Path -LiteralPath $paths.Exe)) {
        throw "nginx.exe not found: $($paths.Exe)"
    }
    & $paths.Exe -t -p $paths.Root
    if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "nginx -t failed (exit $LASTEXITCODE)"
    }
}

function Invoke-PvsNginxReload {
    param([hashtable] $Config)
    $paths = Get-PvsNginxPaths -Config $Config
    if (-not (Test-Path -LiteralPath $paths.Exe)) {
        throw "nginx.exe not found: $($paths.Exe)"
    }
    & $paths.Exe -s reload -p $paths.Root
    if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "nginx reload failed (exit $LASTEXITCODE)"
    }
}

function Start-PvsNginx {
    param([hashtable] $Config)
    $paths = Get-PvsNginxPaths -Config $Config
    if (-not (Test-Path -LiteralPath $paths.Exe)) {
        throw @"
nginx.exe not found: $($paths.Exe)

Скачайте nginx for Windows и распакуйте в $($paths.Root), либо:
  cd deploy\nginx
  .\install-nginx.ps1
"@
    }

    if (-not (Test-Path $paths.LogsDir)) {
        New-Item -ItemType Directory -Path $paths.LogsDir -Force | Out-Null
    }
    if (-not (Test-Path $paths.ConfDir)) {
        New-Item -ItemType Directory -Path $paths.ConfDir -Force | Out-Null
    }

    Invoke-PvsNginxTest -Config $Config

    if (Test-PvsNginxListening) {
        Write-Host 'nginx already listens on :8080 - reload'
        Invoke-PvsNginxReload -Config $Config
        return
    }

    Write-Host "Starting nginx (prefix $($paths.Root)) ..."
    Push-Location -LiteralPath $paths.Root
    try {
        & $paths.Exe -p $paths.Root
    } finally {
        Pop-Location
    }
    if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "nginx start failed (exit $LASTEXITCODE)"
    }

    Start-Sleep -Seconds 2
    if (-not (Test-PvsNginxListening)) {
        $errLog = Join-Path $paths.LogsDir 'pvs-tracker-error.log'
        throw "nginx did not open :8080. Check $errLog and $($paths.ConfDir)\nginx.conf"
    }
    Write-Host 'nginx is listening on http://127.0.0.1:8080'
}

    param([hashtable] $Config)
    return Join-Path $Config.NginxConfDir 'upstream-active.conf'
}

function Get-PvsDrainedPortsPath {
    param([hashtable] $Config)
    return Join-Path $Config.NginxConfDir 'drained-ports.txt'
}

function Get-PvsNginxConfPath {
    param([hashtable] $Config)
    return Join-Path $Config.NginxConfDir 'nginx.conf'
}

function Test-PvsInstanceReady {
    param(
        [int] $Port,
        [int] $TimeoutSec = 5
    )
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health/ready" -UseBasicParsing -TimeoutSec $TimeoutSec
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Get-PvsServiceStatus {
    param(
        [hashtable] $Config,
        [int] $Port
    )
    $name = Get-PvsServiceName -Config $Config -Port $Port
    $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
    if (-not $svc) {
        return @{ Name = $name; Exists = $false; Running = $false; Ready = $false }
    }
    $alive = Test-PvsInstanceLive -Port $Port
    $scmRunning = ($svc.Status -eq 'Running')
    $running = $scmRunning -or (($svc.Status -eq 'Paused') -and $alive)
    $ready = $false
    if ($running -or $alive) {
        $ready = Test-PvsInstanceReady -Port $Port
    }
    return @{
        Name       = $name
        Exists     = $true
        Running    = $running
        Ready      = $ready
        Port       = $Port
        ScmStatus  = $svc.Status
        Alive      = $alive
    }
}

function Get-PvsDrainedPorts {
    param([hashtable] $Config)
    $path = Get-PvsDrainedPortsPath -Config $Config
    if (-not (Test-Path $path)) {
        return @()
    }
    $ports = @()
    foreach ($line in Get-Content -Path $path -ErrorAction SilentlyContinue) {
        $t = $line.Trim()
        if ($t -match '^\d+$') {
            $ports += [int]$t
        }
    }
    return $ports
}

function Set-PvsDrainedPorts {
    param(
        [hashtable] $Config,
        [int[]] $Ports
    )
    $path = Get-PvsDrainedPortsPath -Config $Config
    $dir = Split-Path $path -Parent
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    if ($Ports.Count -eq 0) {
        if (Test-Path $path) {
            Remove-Item $path -Force
        }
        return
    }
    $Ports | ForEach-Object { [string]$_ } | Set-Content -Path $path -Encoding ascii
}

function Add-PvsDrainedPort {
    param(
        [hashtable] $Config,
        [int] $Port
    )
    $current = @(Get-PvsDrainedPorts -Config $Config)
    if ($current -notcontains $Port) {
        $current += $Port
    }
    Set-PvsDrainedPorts -Config $Config -Ports $current
}

function Remove-PvsDrainedPort {
    param(
        [hashtable] $Config,
        [int] $Port
    )
    $current = @(Get-PvsDrainedPorts -Config $Config) | Where-Object { $_ -ne $Port }
    Set-PvsDrainedPorts -Config $Config -Ports $current
}

function Wait-PvsInstanceReady {
    param(
        [int] $Port,
        [int] $TimeoutSec = 120
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-PvsInstanceReady -Port $Port) {
            return $true
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Start-PvsInstanceService {
    param(
        [hashtable] $Config,
        [int] $Port,
        [string] $NssmExe
    )
    $name = Get-PvsServiceName -Config $Config -Port $Port
    $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
    if (-not $svc) {
        throw "Service not found: $name (run install-services.ps1 first)"
    }
    if (Test-PvsNssmServiceHealthy -ServiceName $name -Port $Port) {
        return
    }
    if (-not $NssmExe) {
        try {
            $NssmExe = Resolve-NssmExe
        } catch {
            $NssmExe = $null
        }
    }
    if ($NssmExe) {
        Start-PvsNssmService -NssmExe $NssmExe -ServiceName $name -Port $Port
        return
    }
    Write-Host "Starting $name ..."
    Start-Service -Name $name
    $svc = Get-Service -Name $name
    if ($svc.Status -eq 'Paused') {
        Resume-Service -Name $name
    }
}

function Stop-PvsInstanceService {
    param(
        [hashtable] $Config,
        [int] $Port
    )
    $name = Get-PvsServiceName -Config $Config -Port $Port
    $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
    if ($svc -and ($svc.Status -eq 'Running' -or $svc.Status -eq 'Paused')) {
        Write-Host "Stopping $name ..."
        Stop-Service -Name $name -Force
    }
}

function Get-PvsPoolStatuses {
    param([hashtable] $Config)
    foreach ($port in $Config.PortPool) {
        Get-PvsServiceStatus -Config $Config -Port $port
    }
}

function Build-PvsUpstreamBlock {
    param(
        [hashtable] $Config,
        [int[]] $ActivePorts,
        [int[]] $DrainedPorts
    )
    $lines = @('upstream pvs_tracker {')
    foreach ($port in $ActivePorts | Sort-Object) {
        $suffix = ''
        if ($DrainedPorts -contains $port) {
            $suffix = ' down'
        }
        $lines += "    server 127.0.0.1:$port max_fails=3 fail_timeout=30s$suffix;"
    }
    if ($ActivePorts.Count -eq 0) {
        throw 'No active upstream backends (pool empty)'
    }
    $lines += '    keepalive 32;'
    $lines += '}'
    return ($lines -join "`r`n")
}

function Sync-PvsNginxUpstream {
    param(
        [hashtable] $Config,
        [int[]] $ActivePorts,
        [switch] $ReloadNginx
    )
    $drained = @(Get-PvsDrainedPorts -Config $Config)
    $block = Build-PvsUpstreamBlock -Config $Config -ActivePorts $ActivePorts -DrainedPorts $drained
    $path = Get-PvsUpstreamIncludePath -Config $Config
    $dir = Split-Path $path -Parent
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }

    $changed = $true
    if (Test-Path $path) {
        $old = Get-Content -Raw -Path $path
        if ($old.Trim() -eq $block.Trim()) {
            $changed = $false
        }
    }

    if ($changed) {
        Set-Content -Path $path -Value $block -Encoding ascii -NoNewline
        Write-Host "Updated upstream: $path"
        Write-Host $block
    }

    if ($ReloadNginx) {
        $nginxConf = Get-PvsNginxConfPath -Config $Config
        if (-not (Test-Path $nginxConf)) {
            throw "nginx.conf not found: $nginxConf"
        }
        if (-not (Test-PvsNginxListening)) {
            Write-Host 'nginx is not running on :8080 - start it with .\start-nginx.ps1'
        } elseif ($changed) {
            Invoke-PvsNginxReload -Config $Config
            Write-Host 'nginx reloaded'
        } else {
            Write-Host 'upstream unchanged; nginx already running'
        }
    }

    return $changed
}

function Get-PvsReadyPorts {
    param([hashtable] $Config)
    $ready = @()
    foreach ($st in Get-PvsPoolStatuses -Config $Config) {
        if ($st.Ready) {
            $ready += $st.Port
        }
    }
    return $ready
}

function Get-PvsRunningPorts {
    param([hashtable] $Config)
    $running = @()
    foreach ($st in Get-PvsPoolStatuses -Config $Config) {
        if ($st.Running) {
            $running += $st.Port
        }
    }
    return $running
}
