# Запуск PostgreSQL (zip binaries) в Windows-контейнере.
$ErrorActionPreference = "Stop"

function Update-PostgresConfig {
    param([Parameter(Mandatory)][string]$DataDir)

    $conf = Join-Path $DataDir "postgresql.conf"
    $autoConf = Join-Path $DataDir "postgresql.auto.conf"
    $hba = Join-Path $DataDir "pg_hba.conf"

    # initdb leaves listen_addresses commented out; force listen on all interfaces.
    if (Test-Path $conf) {
        $lines = Get-Content -Path $conf
        $filtered = $lines | Where-Object { $_ -notmatch "^\s*#?\s*listen_addresses\s*=" }
        $filtered += "listen_addresses = '*'"
        Set-Content -Path $conf -Value $filtered
    }
    Set-Content -Path $autoConf -Value "listen_addresses = '*'" -Encoding Ascii

    if (Test-Path $hba) {
        $hbaText = Get-Content -Raw -Path $hba
        if ($hbaText -notmatch "127\.0\.0\.1/32") {
            Add-Content -Path $hba -Value "host all all 127.0.0.1/32 trust"
        }
        if ($hbaText -notmatch "172\.28\.100\.0/24") {
            Add-Content -Path $hba -Value "host all all 172.28.100.0/24 md5"
        }
        if ($hbaText -notmatch "172\.(1[6-9]|2[0-9]|3[0-1])\.\d+\.\d+/12") {
            Add-Content -Path $hba -Value "host all all 172.16.0.0/12 md5"
        }
        if ($hbaText -notmatch "0\.0\.0\.0/0") {
            Add-Content -Path $hba -Value "host all all 0.0.0.0/0 md5"
            Add-Content -Path $hba -Value "host all all ::/0 md5"
        }
    }
}

function Enable-PostgresFirewall {
    # Windows-контейнер: firewall часто блокирует :5432 (в т.ч. через published port).
    $netsh = Join-Path $env:SystemRoot "System32\netsh.exe"
    & $netsh advfirewall set allprofiles state off | Out-Null
    Write-Host "Windows Firewall disabled in postgres container (dev)"
    $ruleName = "PVS PostgreSQL 5432"
    & $netsh advfirewall firewall add rule name="$ruleName" dir=in action=allow protocol=TCP localport=5432 | Out-Null
}

function Initialize-PostgresDataDir {
    param(
        [Parameter(Mandatory)][string]$TargetDir,
        [Parameter(Mandatory)][string]$InitdbExe,
        [Parameter(Mandatory)][string]$TempParent
    )

    $initTmp = Join-Path $TempParent ".initdb-tmp"
    if (Test-Path $initTmp) {
        Remove-Item $initTmp -Recurse -Force
    }

    Write-Host "Running initdb in $initTmp (temp; Docker volume ACL workaround) ..."
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $initLines = & $InitdbExe -D $initTmp -U postgres -E UTF8 -A trust 2>&1
    $initExit = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    $initLines | ForEach-Object { Write-Host $_ }
    if ($initExit -ne 0) {
        if (Test-Path $initTmp) {
            Remove-Item $initTmp -Recurse -Force -ErrorAction SilentlyContinue
        }
        throw "initdb failed with exit code $initExit"
    }

    Update-PostgresConfig -DataDir $initTmp

    New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
    Get-ChildItem -Path $TargetDir -Force -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

    Write-Host "Copying initialized cluster to $TargetDir ..."
    & robocopy.exe $initTmp $TargetDir /E /NFL /NDL /NJH /NJS /NC /NS | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy to data dir failed with exit code $LASTEXITCODE"
    }

    Remove-Item $initTmp -Recurse -Force
}

$pgRoot = $env:POSTGRES_ROOT
$pgBin = Join-Path $pgRoot "bin"
$env:Path = "$pgBin;" + $env:Path
$pgData = $env:PGDATA
$pgUser = $env:POSTGRES_USER
$pgPass = $env:POSTGRES_PASSWORD
$pgDb = $env:POSTGRES_DB
$initFlag = Join-Path $pgData ".pvs_tracker_initialized"

New-Item -ItemType Directory -Force -Path $pgData | Out-Null

$pgVersionFile = Join-Path $pgData "PG_VERSION"
if (-not (Test-Path $pgVersionFile)) {
    $initdb = Join-Path $pgBin "initdb.exe"
    if (-not (Test-Path $initdb)) {
        throw "initdb.exe not found at $initdb"
    }
    Initialize-PostgresDataDir -TargetDir $pgData -InitdbExe $initdb -TempParent $pgRoot
}

Update-PostgresConfig -DataDir $pgData
Enable-PostgresFirewall

$pgCtl = Join-Path $pgBin "pg_ctl.exe"
$psql = Join-Path $pgBin "psql.exe"
$logFile = Join-Path $pgData "postgresql.log"

# pg_ctl -c forces listen on all interfaces (required for Docker service DNS).
& $pgCtl -D $pgData -l $logFile -o '-c listen_addresses=*' start -w
if ($LASTEXITCODE -ne 0) {
    throw "pg_ctl start failed with exit code $LASTEXITCODE"
}

$listenCheck = & (Join-Path $env:SystemRoot "System32\netstat.exe") -an | Select-String "5432"
Write-Host "Listening sockets for 5432:"
$listenCheck | ForEach-Object { Write-Host $_.Line.Trim() }
$listeningAll = @($listenCheck | Where-Object { $_.Line -like "*0.0.0.0:5432*" })
if ($listeningAll.Count -eq 0) {
    Write-Host "WARN: PostgreSQL is not listening on 0.0.0.0:5432"
}

if (-not (Test-Path $initFlag)) {
    Write-Host "Creating role $pgUser and database $pgDb ..."
    & $psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c "ALTER USER postgres WITH PASSWORD '$pgPass';"
    & $psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c "DO `$`$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$pgUser') THEN CREATE ROLE $pgUser LOGIN PASSWORD '$pgPass'; END IF; END `$`$;"
    $createDb = & $psql -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$pgDb'"
    if (-not $createDb) {
        & $psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE $pgDb OWNER $pgUser;"
    }
    New-Item -ItemType File -Force -Path $initFlag | Out-Null
}

Write-Host "PostgreSQL ready on 0.0.0.0:5432 (db=$pgDb user=$pgUser)"
while ($true) {
    Start-Sleep -Seconds 3600
}
