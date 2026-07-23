"""Regenerate telemetry.html and events_export.json on a timer while the agent runs.

NOTE: as of the `[reports]` config section, the agent does this itself on a
timer while it's running (unless started with `--no-reports`), so this script
is no longer required for the normal workflow. It's kept for cases where you
want the views refreshed without the agent's own reports job enabled, or want
to regenerate from a data-dir the agent isn't currently running against.

Run this in a second terminal alongside `python -m agent.main ...` -- it doesn't
touch the agent or the database, it just re-reads events.db and rewrites both
output files every `--interval` seconds, so they stay close to live instead of
needing a manual re-run each time you want a fresh view.

Usage:
    python scripts/auto_refresh.py --data-dir ./demo_run --interval 15
    (Ctrl+C to stop)
"""
from __future__ import annotations

import argparse
import datetime
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.reports import export_json as export  # noqa: E402
from agent.reports import generate_html as generate  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="./demo_run")
    parser.add_argument("--html-out", default="telemetry.html")
    parser.add_argument("--json-out", default="events_export.json")
    parser.add_argument("--interval", type=float, default=15.0, help="Seconds between refreshes")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    html_out = Path(args.html_out)
    json_out = Path(args.json_out)

    print(f"Auto-refreshing every {args.interval:.0f}s from {data_dir} -- Ctrl+C to stop", flush=True)
    try:
        while True:
            if (data_dir / "events.db").exists():
                html_count = generate(data_dir, html_out)
                json_count = export(data_dir, json_out)
                t = datetime.datetime.now().strftime("%H:%M:%S")
                print(f"[{t}] refreshed: {html_out} ({html_count} rows), {json_out} ({json_count} events)", flush=True)
            else:
                print(f"waiting for {data_dir / 'events.db'} to exist...", flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
