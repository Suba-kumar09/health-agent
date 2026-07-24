"""Run the agent in-process, then force one final report refresh when it exits.

Calls agent.main.main() directly (same argv handling as `python -m agent.main`,
so --data-dir, --dry-run, --no-tray etc. all work as usual) wrapped in a
try/finally. The agent already refreshes telemetry.html + events_export.json
live every `reports.interval_secs` while running (see the `[reports]` config
section and agent/main.py) unless started with --no-reports, so this wrapper's
only job is to guarantee one last refresh right at shutdown -- covering
whatever happened in the gap since the last scheduled tick, or providing a
refresh at all if the agent was run with --no-reports.

Usage:
    python scripts/run_with_report.py --dry-run --data-dir ./demo_run --no-tray
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent.main  # noqa: E402
from agent.reports import refresh_reports  # noqa: E402


def _data_dir_from_args(args: list[str]) -> str:
    for i, arg in enumerate(args):
        if arg == "--data-dir" and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith("--data-dir="):
            return arg.split("=", 1)[1]
    return "."  # same default as agent/main.py's --data-dir


def main() -> None:
    args = sys.argv[1:]
    data_dir = Path(_data_dir_from_args(args))

    try:
        agent.main.main(args)
    finally:
        refresh_reports(data_dir, Path("telemetry.html"), Path("events_export.json"))


if __name__ == "__main__":
    main()
