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

# Win10/Server 2016+: RepetitionDuration не указывать (бесконечно).
# Server 2012 R2: Duration обязателен, максимум 4 цифры в днях (9999).
$triggerParams = @{
    Once               = $true
    At                 = (Get-Date)
    RepetitionInterval = (New-TimeSpan -Minutes $IntervalMinutes)
}
if ([environment]::OSVersion.Version.Major -lt 10) {
    $triggerParams.RepetitionDuration = New-TimeSpan -Days 9999
}
$trigger = New-ScheduledTaskTrigger @triggerParams

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew

try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -RunLevel Highest -Force | Out-Null
} catch {
    throw "Failed to register scheduled task '$TaskName': $($_.Exception.Message)"
}

$registered = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $registered) {
    throw "Scheduled task '$TaskName' was not created"
}

Write-Host "Registered scheduled task: $TaskName (every $IntervalMinutes min)"
Write-Host "Test now: powershell -File `"$watchScript`""
