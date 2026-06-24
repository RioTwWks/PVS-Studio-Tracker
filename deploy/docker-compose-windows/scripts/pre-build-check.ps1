# Запускать на хосте Windows ПЕРЕД docker compose build.
# Пример: .\scripts\pre-build-check.ps1
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$required = @(
    "pvs_tracker\rule_documentation.py",
    "pvs_tracker\issue_activity.py",
    "pvs_tracker\template_helpers.py",
    "pvs_tracker\startup_state.py"
)

Write-Host "Repo: $repoRoot"
$missing = @()
foreach ($rel in $required) {
    $path = Join-Path $repoRoot $rel
    if (Test-Path $path) {
        Write-Host "  OK  $rel"
    } else {
        Write-Host "  MISSING  $rel"
        $missing += $rel
    }
}

if ($missing.Count -gt 0) {
    Write-Host ""
    Write-Host "Incomplete git checkout. Fix:" -ForegroundColor Red
    Write-Host "  cd $repoRoot"
    Write-Host "  git fetch origin"
    Write-Host "  git checkout main"
    Write-Host "  git reset --hard origin/main"
    Write-Host "  git pull origin main"
    exit 1
}

Write-Host ""
Write-Host "Source tree OK — safe to run docker compose build" -ForegroundColor Green
