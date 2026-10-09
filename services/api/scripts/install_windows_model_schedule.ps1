# Weekly research uses the verified local archive and the existing .env.
$ErrorActionPreference = "Stop"
$ApiDirectory = Split-Path $PSScriptRoot -Parent
$PythonPath = Join-Path $ApiDirectory ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonPath)) { throw "Install the API virtual environment first." }
if ([TimeZoneInfo]::Local.Id -ne "Israel Standard Time") { throw "Set the Windows time zone to Israel." }
$ScriptPath = Join-Path $PSScriptRoot "run_local_model_validation.py"
$TaskAction = New-ScheduledTaskAction -Execute $PythonPath -Argument "`"$ScriptPath`"" -WorkingDirectory $ApiDirectory
$TaskTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At "18:00"
$TaskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 6)
$TaskPrincipal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName "stocksAnalyzer Local Model Validation" -Action $TaskAction -Trigger $TaskTrigger -Settings $TaskSettings -Principal $TaskPrincipal -Description "Friday 18:00 Israel time; full-history model validation from the verified local archive." -Force | Out-Null
Write-Host "Installed Friday model validation at 18:00 Israel time. The archive must be configured and this computer on with your account signed in."
