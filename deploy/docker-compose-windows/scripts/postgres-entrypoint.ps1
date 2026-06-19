# Запуск PostgreSQL (zip binaries) в Windows-контейнере.
$ErrorActionPreference = "Stop"

$pgRoot = $env:POSTGRES_ROOT
$pgBin = Join-Path $pgRoot "bin"
$pgData = $env:PGDATA
$pgUser = $env:POSTGRES_USER
$pgPass = $env:POSTGRES_PASSWORD
$pgDb = $env:POSTGRES_DB
$initFlag = Join-Path $pgData ".pvs_tracker_initialized"

if (-not (Test-Path $pgData)) {
    New-Item -ItemType Directory -Force -Path $pgData | Out-Null
}

$pgVersionFile = Join-Path $pgData "PG_VERSION"
if (-not (Test-Path $pgVersionFile)) {
    Write-Host "Initializing PostgreSQL data directory at $pgData ..."
    & (Join-Path $pgBin "initdb.exe") -D $pgData -U postgres -E UTF8 --locale=C -A trust
    if ($LASTEXITCODE -ne 0) {
        throw "initdb failed"
    }
}

$conf = Join-Path $pgData "postgresql.conf"
$hba = Join-Path $pgData "pg_hba.conf"

if (Test-Path $conf) {
    $text = Get-Content -Raw -Path $conf
    if ($text -notmatch "listen_addresses") {
        Add-Content -Path $conf -Value "listen_addresses = '*'"
    } else {
        $text = $text -replace "listen_addresses\s*=\s*'[^']*'", "listen_addresses = '*'"
        Set-Content -Path $conf -Value $text -NoNewline
    }
}

if (Test-Path $hba) {
    $hbaText = Get-Content -Raw -Path $hba
    if ($hbaText -notmatch "0\.0\.0\.0/0") {
        Add-Content -Path $hba -Value "host all all 0.0.0.0/0 md5"
        Add-Content -Path $hba -Value "host all all ::/0 md5"
    }
}

$pgCtl = Join-Path $pgBin "pg_ctl.exe"
$psql = Join-Path $pgBin "psql.exe"
$logFile = Join-Path $pgData "postgresql.log"

& $pgCtl -D $pgData -l $logFile start -w
if ($LASTEXITCODE -ne 0) {
    throw "pg_ctl start failed"
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
