#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Установка или обновление Docker Engine (static zip) и Compose plugin на Windows Server.

.DESCRIPTION
  Заменяет Mirantis Container Runtime / Docker 19.x на официальный static Docker Engine.
  Только Windows containers (не Linux).

  Примеры:
    # Online, последняя 29.5.3 из download.docker.com
    .\install-docker-engine.ps1

    # Указать версию и DNS
    .\install-docker-engine.ps1 -DockerVersion 29.5.3 -DnsServers 10.0.0.1,10.0.0.2

    # Offline — zip уже скачан на хост
    .\install-docker-engine.ps1 -ZipPath C:\Install\docker-29.5.3.zip

    # Корпоративный proxy для скачивания zip / compose (на хосте)
    .\install-docker-engine.ps1 -HttpProxy http://proxy.corp:8080 -HttpsProxy http://proxy.corp:8080

    # Proxy + DNS в daemon.json (Docker 20.10+, включая 29.x)
    .\install-docker-engine.ps1 -DnsServers 10.0.0.1 `
      -DaemonHttpProxy http://proxy.corp:8080 -DaemonHttpsProxy http://proxy.corp:8080 `
      -DaemonNoProxy "localhost,127.0.0.1,.corp.local"
#>
param(
    [string] $DockerVersion = "29.5.3",
    [string] $ZipPath = "",
    [string] $InstallDir = "$Env:ProgramFiles\Docker",
    [string] $ComposeVersion = "2.39.4",
    [string[]] $DnsServers = @(),
    [string] $DaemonHttpProxy = "",
    [string] $DaemonHttpsProxy = "",
    [string] $DaemonNoProxy = "localhost,127.0.0.1",
    [string] $HttpProxy = "",
    [string] $HttpsProxy = "",
    [switch] $SkipCompose,
    [switch] $SkipDaemonJson,
    [switch] $Force
)

$ErrorActionPreference = "Stop"

function Write-Step([string] $Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Download {
    param(
        [string] $Url,
        [string] $Destination
    )
    $proxy = if ($HttpsProxy) { $HttpsProxy } elseif ($HttpProxy) { $HttpProxy } else { $null }
    if ($proxy) {
        Write-Host "Downloading via proxy $proxy ..."
        Invoke-WebRequest -Uri $Url -OutFile $Destination -Proxy $proxy
    } else {
        Invoke-WebRequest -Uri $Url -OutFile $Destination
    }
}

function Get-DockerZipUrl([string] $Version) {
    return "https://download.docker.com/win/static/stable/x86_64/docker-$Version.zip"
}

function Get-ComposeUrl([string] $Version) {
    return "https://github.com/docker/compose/releases/download/v$Version/docker-compose-windows-x86_64.exe"
}

function Ensure-Directory([string] $Path) {
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
    }
}

function Add-MachinePathEntry([string] $Directory) {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    if ($machinePath -notlike "*$Directory*") {
        [Environment]::SetEnvironmentVariable("Path", "$machinePath;$Directory", "Machine")
        $env:Path = "$env:Path;$Directory"
        Write-Host "Added to Machine PATH: $Directory"
    }
}

function Stop-DockerServiceSafe {
    $svc = Get-Service -Name docker -ErrorAction SilentlyContinue
    if ($svc) {
        if ($svc.Status -eq "Running") {
            Write-Host "Stopping docker service ..."
            Stop-Service docker -Force
        }
    }
}

function Unregister-DockerService {
    $dockerd = Join-Path $InstallDir "dockerd.exe"
    if (Test-Path $dockerd) {
        Write-Host "Unregistering existing docker service ..."
        & $dockerd --unregister-service 2>$null
    } else {
        $legacy = Get-Command dockerd.exe -ErrorAction SilentlyContinue
        if ($legacy) {
            & $legacy.Source --unregister-service 2>$null
        }
    }
    Start-Sleep -Seconds 2
}

function Write-DaemonJson {
    param(
        [string[]] $Dns,
        [string] $HttpProxyValue,
        [string] $HttpsProxyValue,
        [string] $NoProxyValue
    )
    $configDir = "C:\ProgramData\docker\config"
    Ensure-Directory $configDir
    $configPath = Join-Path $configDir "daemon.json"

    if ((Test-Path $configPath) -and -not $Force) {
        $backup = "$configPath.bak.$(Get-Date -Format yyyyMMddHHmmss)"
        Copy-Item $configPath $backup
        Write-Host "Backed up existing daemon.json -> $backup"
    }

    $obj = [ordered]@{}
    if ($Dns -and $Dns.Count -gt 0) {
        $obj["dns"] = @($Dns)
    }
    if ($HttpProxyValue -or $HttpsProxyValue) {
        $obj["proxies"] = [ordered]@{
            default = [ordered]@{
                httpProxy  = $HttpProxyValue
                httpsProxy = if ($HttpsProxyValue) { $HttpsProxyValue } else { $HttpProxyValue }
                noProxy    = $NoProxyValue
            }
        }
    }

    if ($obj.Count -eq 0) {
        if (Test-Path $configPath) {
            Write-Host "daemon.json left unchanged (no DNS/proxy specified)."
        }
        return
    }

    $json = ($obj | ConvertTo-Json -Depth 4)
    # ConvertTo-Json may omit empty; ensure UTF-8 without BOM
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($configPath, $json, $utf8NoBom)
    Write-Host "Wrote $configPath"
    Write-Host $json
}

Write-Step "Docker Engine install / upgrade (Windows containers)"
Write-Host "Target version: $DockerVersion"
Write-Host "Install dir:    $InstallDir"

if (-not $ZipPath) {
    $zipFileName = "docker-$DockerVersion.zip"
    $ZipPath = Join-Path $Env:TEMP $zipFileName
    if (-not (Test-Path $ZipPath)) {
        $url = Get-DockerZipUrl -Version $DockerVersion
        Write-Step "Download $url"
        Invoke-Download -Url $url -Destination $ZipPath
    } else {
        Write-Host "Using existing zip: $ZipPath"
    }
} elseif (-not (Test-Path $ZipPath)) {
    throw "Zip not found: $ZipPath"
}

Write-Step "Stop and unregister old Docker service"
Stop-DockerServiceSafe
Unregister-DockerService

if (Test-Path $InstallDir) {
    $backupDir = "$InstallDir.backup.$(Get-Date -Format yyyyMMddHHmmss)"
    Write-Host "Backing up $InstallDir -> $backupDir"
    Rename-Item $InstallDir $backupDir
}

Write-Step "Extract Docker binaries to $InstallDir"
Ensure-Directory $InstallDir
Expand-Archive -Path $ZipPath -DestinationPath $InstallDir -Force

$dockerd = Join-Path $InstallDir "dockerd.exe"
$dockerCli = Join-Path $InstallDir "docker.exe"
if (-not (Test-Path $dockerd)) {
    throw "dockerd.exe not found after extract. Check zip layout."
}

Add-MachinePathEntry -Directory $InstallDir

if (-not $SkipDaemonJson) {
    Write-Step "Write daemon.json"
    Write-DaemonJson -Dns $DnsServers `
        -HttpProxyValue $DaemonHttpProxy `
        -HttpsProxyValue $DaemonHttpsProxy `
        -NoProxyValue $DaemonNoProxy
} else {
    Write-Host "Skipping daemon.json (--SkipDaemonJson)."
}

Write-Step "Register and start docker service"
& $dockerd --register-service
Start-Service docker
Start-Sleep -Seconds 3

$svc = Get-Service docker
if ($svc.Status -ne "Running") {
    throw "Docker service failed to start. Check: Get-EventLog -LogName Application -Source docker -Newest 5"
}

if (-not $SkipCompose) {
    Write-Step "Install Docker Compose CLI plugin v$ComposeVersion"
    $pluginDir = Join-Path $InstallDir "cli-plugins"
    Ensure-Directory $pluginDir
    $composeExe = Join-Path $pluginDir "docker-compose.exe"
    $composeUrl = Get-ComposeUrl -Version $ComposeVersion
    Invoke-Download -Url $composeUrl -Destination $composeExe
}

Write-Step "Verify installation"
& $dockerCli version
if (-not $SkipCompose) {
    & $dockerCli compose version
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "Windows containers test:"
Write-Host "  docker run --rm mcr.microsoft.com/windows/nanoserver:ltsc2019 cmd /c echo OK"
Write-Host ""
Write-Host "PVS-Tracker compose:"
Write-Host "  cd deploy\docker-compose-windows"
Write-Host "  copy .env.example .env"
Write-Host "  docker compose up -d --build"
