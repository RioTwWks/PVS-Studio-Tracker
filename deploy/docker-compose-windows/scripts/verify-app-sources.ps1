# Verify required source files before pip install (incomplete git checkout fails fast).
$ErrorActionPreference = "Stop"

$required = @(
    "C:\app\pvs_tracker\main.py",
    "C:\app\pvs_tracker\template_helpers.py",
    "C:\app\pvs_tracker\rule_documentation.py",
    "C:\app\pvs_tracker\startup_state.py",
    "C:\app\pvs_tracker\issue_activity.py"
)

$missing = @()
foreach ($path in $required) {
    if (-not (Test-Path $path)) {
        $missing += $path
    }
}

if ($missing.Count -gt 0) {
    throw "Incomplete source tree. Missing: $($missing -join ', '). Run: git fetch origin && git checkout main && git pull origin main"
}

Write-Host "Source tree verification OK"
