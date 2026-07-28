"""Export a data-dir's events.db to a plain, human-readable CSV for manual inspection.

The running agent's live reports job only ever shows the last `[reports] window_days`
of history; this is a thin one-shot CLI wrapper around `agent.reports.export_csv` for
ad-hoc full-history (or custom date-range) exports.

Usage:
    python scripts/export_readable_csv.py --data-dir ./demo_run --out events_readable.csv
    python scripts/export_readable_csv.py --data-dir ./demo_run --out last_week.csv --since 2026-07-20
"""
from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.config import Config
from agent.reports import export_csv


def _parse_ts(value: str | None) -> float | None:
    if value is None:
        return None
    return datetime.datetime.fromisoformat(value).timestamp()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="./demo_run")
    parser.add_argument("--out", default="events_readable.csv")
    parser.add_argument("--config", default="config.toml", help="Path to config.toml used by the agent run")
    parser.add_argument("--since", default=None, help="ISO date/datetime, e.g. 2026-07-20 -- omit for full history")
    parser.add_argument("--until", default=None, help="ISO date/datetime, e.g. 2026-07-27 -- omit for full history")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = Config.load(config_path) if config_path.exists() else Config.default()

    count = export_csv(
        Path(args.data_dir),
        Path(args.out),
        config,
        since=_parse_ts(args.since),
        until=_parse_ts(args.until),
    )
    print(f"Wrote {count} rows to {args.out}")


if __name__ == "__main__":
    main()
