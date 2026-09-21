# Starts the backend, the dashboard frontend and the agent -- one of each.
# Safe to run twice: the server, agent and Vite all refuse to start a second
# copy (port / instance-lock guards), so nothing is duplicated.
#
#   .\start.ps1
#
# Each service opens in its own window; close the window (or Ctrl+C) to stop it.

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Error "Missing $py -- create the venv first (python -m venv .venv; .venv\Scripts\pip install -e .)"
    exit 1
}

function Start-Service($title, $workdir, $command) {
    Start-Process powershell -WorkingDirectory $workdir -ArgumentList @(
        "-NoExit", "-Command", "`$Host.UI.RawUI.WindowTitle = '$title'; $command"
    )
}

Start-Service "health-agent server" $root "& '$py' -m server.main"
Start-Sleep -Seconds 4   # let the server bind :8001 before the agent's first poll
Start-Service "health-agent dashboard" (Join-Path $root "dashboard") "npm run dev"
Start-Service "health-agent agent" $root "& '$py' -m agent.main"

Write-Host "Started server (:8001), dashboard (:5173) and agent."
