param(
    [string]$ArchivePath = (Join-Path $env:LOCALAPPDATA "stocksAnalyzer\market-history.sqlite3"),
    [string]$BackupPath = (Join-Path $env:LOCALAPPDATA "stocksAnalyzer\backups\market-history.sqlite3")
)
$ErrorActionPreference = "Stop"
$ApiDirectory = Split-Path $PSScriptRoot -Parent
$PythonPath = Join-Path $ApiDirectory ".venv\Scripts\python.exe"
$EnvPath = Join-Path $ApiDirectory ".env"
if (-not (Test-Path $PythonPath)) { throw "Install the API virtual environment first." }
if ([TimeZoneInfo]::Local.Id -ne "Israel Standard Time") { throw "Set the Windows time zone to Israel before installing the schedules." }
if (-not (Test-Path $EnvPath)) { throw "Configure services/api/.env first." }
if (-not (Select-String -Path $EnvPath -Pattern '^\s*SUPABASE_DB_URL\s*=' -Quiet)) {
    throw "Add SUPABASE_DB_URL to services/api/.env using Supabase Dashboard > Connect > Session pooler (port 5432). Enter the database password locally."
}
& $PythonPath -m pip install -r (Join-Path $ApiDirectory "requirements-archive.txt")
if ($LASTEXITCODE -ne 0) { throw "Archive dependency installation failed." }
& $PythonPath (Join-Path $PSScriptRoot "archive_market_history.py") --archive $ArchivePath --backup $BackupPath --prune --compact --configure
if ($LASTEXITCODE -ne 0) { throw "Migration did not finish. Review the report; do not delete either archive file." }
& (Join-Path $PSScriptRoot "install_windows_schedule.ps1")
& (Join-Path $PSScriptRoot "install_windows_model_schedule.ps1")
Write-Host "Verified archives saved, expired cloud history pruned, and local daily/weekly tasks installed. Restart the API to load the archive paths. Existing egress restrictions still require quota renewal or account action."
