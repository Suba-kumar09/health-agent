# Loads .env and runs the ingest server against it (local Postgres by default).
# Usage: powershell -ExecutionPolicy Bypass -File scripts\run_server.ps1

$envFile = Join-Path $PSScriptRoot "..\.env"
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*([^#=]+)=(.*)$') {
        [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), 'Process')
    }
}

& (Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe") -m uvicorn server.main:app --host 127.0.0.1 --port 8000
