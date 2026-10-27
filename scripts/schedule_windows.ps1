# Sets up the automatic runs on Windows (METHODS.md, 2026-10-27): Task Scheduler starts
# `python run.py auto --log` every 3 hours, and when you log on, catching up on anything missed
# while the computer was off. It runs only while you are logged on, because the agents use the
# Claude login of your Windows account, and it shows no window.
#
# Set up or update:  powershell -ExecutionPolicy Bypass -File scripts\schedule_windows.ps1
# Check it:          Get-ScheduledTask -TaskName "FPL experiment" | Get-ScheduledTaskInfo
# Remove it:         Unregister-ScheduledTask -TaskName "FPL experiment" -Confirm:$false
# (On macOS or Linux, a cron line does the same: 0 */3 * * * cd /path/to/repo && python run.py auto --log)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python).Source
$pythonw = Join-Path (Split-Path -Parent $python) "pythonw.exe"   # the same Python, without a console window

$action = New-ScheduledTaskAction -Execute $pythonw -Argument "run.py auto --log" -WorkingDirectory $root
$every3Hours = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Hours 3)
$atLogOn = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 6)

Register-ScheduledTask -TaskName "FPL experiment" -Action $action -Trigger @($every3Hours, $atLogOn) `
    -Settings $settings -Description "FPL agents experiment: scoring, weekly picks and website updates (run.py auto)" `
    -Force | Out-Null
Write-Host "Scheduled: $pythonw run.py auto --log, every 3 hours and at log-on, in $root"
