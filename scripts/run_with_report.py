"""Run the agent in-process, then regenerate telemetry.html + events.json when it exits.

Calls agent.main.main() directly (same argv handling as `python -m agent.main`,
so --data-dir, --dry-run, --no-tray etc. all work as usual) wrapped in a
try/finally. agent.main already installs its own SIGINT/SIGTERM handler and
exits its loop cleanly on Ctrl+C or tray "Stop agent" -- running it in-process
(rather than as a subprocess) means that same Ctrl+C also unwinds this
wrapper's try/finally, so telemetry.html and events.json always get
regenerated against the same --data-dir right after a session ends, instead
of going stale until someone remembers to run the export scripts by hand.

Usage:
    python scripts/run_with_report.py --dry-run --data-dir ./demo_run --no-tray
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import agent.main


def _data_dir_from_args(args: list[str]) -> str:
    for i, arg in enumerate(args):
        if arg == "--data-dir" and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith("--data-dir="):
            return arg.split("=", 1)[1]
    return "."  # same default as agent/main.py's --data-dir


def main() -> None:
    args = sys.argv[1:]
    data_dir = _data_dir_from_args(args)

    try:
        agent.main.main(args)
    finally:
        scripts_dir = Path(__file__).parent
        subprocess.run(
            [sys.executable, str(scripts_dir / "generate_telemetry_html.py"),
             "--data-dir", data_dir, "--out", "telemetry.html"],
            check=True,
        )
        subprocess.run(
            [sys.executable, str(scripts_dir / "export_json.py"),
             "--data-dir", data_dir, "--out", "events.json"],
            check=True,
        )


if __name__ == "__main__":
    main()
