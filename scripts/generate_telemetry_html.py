"""Generate a readable HTML dashboard from a data-dir's events.db history.

The running agent already does this itself on a timer (see the `[reports]`
config section and agent/main.py) as long as it's started without
`--no-reports`, so you normally don't need to run this manually -- and that
live view only ever shows the last `window_days` of history. This script is a
one-shot CLI wrapper around `agent.reports.generate_html` for ad-hoc full-history
(or custom date-range) exports.

Usage:
    python scripts/generate_telemetry_html.py --data-dir ./demo_run --out telemetry.html
    python scripts/generate_telemetry_html.py --data-dir ./demo_run --since 2026-07-20 --out last_week.html
"""
from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.config import Config
from agent.reports import generate_html


def _parse_ts(value: str | None) -> float | None:
    if value is None:
        return None
    return datetime.datetime.fromisoformat(value).timestamp()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="./demo_run")
    parser.add_argument("--out", default="telemetry.html")
    parser.add_argument("--config", default="config.toml", help="Path to config.toml used by the agent run")
    parser.add_argument("--since", default=None, help="ISO date/datetime, e.g. 2026-07-20 -- omit for full history")
    parser.add_argument("--until", default=None, help="ISO date/datetime, e.g. 2026-07-27 -- omit for full history")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = Config.load(config_path) if config_path.exists() else Config.default()

    count = generate_html(
        Path(args.data_dir),
        Path(args.out),
        config,
        since=_parse_ts(args.since),
        until=_parse_ts(args.until),
    )
    print(f"Wrote {count} rows to {args.out}")


if __name__ == "__main__":
    main()
