# Регистрирует задачу планировщика: watchdog каждую минуту.
param(
    [string] $ConfigPath,
    [string] $TaskName = 'PVS-Tracker-Nginx-Watchdog',
    [int] $IntervalMinutes = 1
)

$ErrorActionPreference = 'Stop'

$watchScript = Join-Path $PSScriptRoot 'watch-instances.ps1'
if (-not (Test-Path $watchScript)) {
    throw "Not found: $watchScript"
}

$argList = "-NoProfile -ExecutionPolicy Bypass -File `"$watchScript`" -StopExcessSpares"
if ($ConfigPath) {
    $argList += " -ConfigPath `"$ConfigPath`""
}

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argList
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration ([TimeSpan]::MaxValue)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -RunLevel Highest -Force | Out-Null

Write-Host "Registered scheduled task: $TaskName (every $IntervalMinutes min)"
Write-Host "Test now: powershell -File `"$watchScript`""
