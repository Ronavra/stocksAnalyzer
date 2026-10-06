# Run in PowerShell on the machine hosting the API. No secrets are embedded
# in the task; Python loads the existing services/api/.env at execution time.
$ErrorActionPreference = "Stop"
$ApiDirectory = Split-Path $PSScriptRoot -Parent
$PythonPath = Join-Path $ApiDirectory ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonPath)) { throw "Install the API virtual environment first." }
$Zone = [TimeZoneInfo]::Local
if ($Zone.Id -ne "Israel Standard Time") { throw "Set the Windows time zone to Israel before installing the 08:00 task." }
$ScriptPath = Join-Path $PSScriptRoot "run_scheduled_daily.py"
$TaskAction = New-ScheduledTaskAction -Execute $PythonPath -Argument "`"$ScriptPath`"" -WorkingDirectory $ApiDirectory
$TaskTrigger = New-ScheduledTaskTrigger -Daily -At "08:00"
$TaskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 4)
$TaskPrincipal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName "stocksAnalyzer Daily Refresh" -Action $TaskAction -Trigger $TaskTrigger -Settings $TaskSettings -Principal $TaskPrincipal -Description "Daily market research at 08:00 Israel time; uses the API .env and skips completed daily runs." -Force | Out-Null
Write-Host "Installed daily refresh at 08:00 Israel time. The computer must be on and your account signed in."
