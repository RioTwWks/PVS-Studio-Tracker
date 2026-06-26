# Shared helpers for nginx + NSSM instance pool on Windows Server.

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

function Get-PvsUpstreamIncludePath {
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
    $ready = $false
    if ($svc.Status -eq 'Running') {
        $ready = Test-PvsInstanceReady -Port $Port
    }
    return @{
        Name    = $name
        Exists  = $true
        Running = ($svc.Status -eq 'Running')
        Ready   = $ready
        Port    = $Port
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
        [int] $Port
    )
    $name = Get-PvsServiceName -Config $Config -Port $Port
    $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
    if (-not $svc) {
        throw "Service not found: $name (run install-services.ps1 first)"
    }
    if ($svc.Status -ne 'Running') {
        Write-Host "Starting $name ..."
        Start-Service -Name $name
    }
}

function Stop-PvsInstanceService {
    param(
        [hashtable] $Config,
        [int] $Port
    )
    $name = Get-PvsServiceName -Config $Config -Port $Port
    $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -eq 'Running') {
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

    if ($ReloadNginx -and $changed) {
        $nginxConf = Get-PvsNginxConfPath -Config $Config
        if (-not (Test-Path $nginxConf)) {
            throw "nginx.conf not found: $nginxConf"
        }
        & $Config.NginxExe -s reload
        Write-Host "nginx reloaded"
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
