"""Generate a readable HTML dashboard from a data-dir's full events.db history.

The running agent already does this itself on a timer (see the `[reports]`
config section and agent/main.py) as long as it's started without
`--no-reports`, so you normally don't need to run this manually. This script
is a one-shot CLI wrapper around `agent.reports.generate_html` for ad-hoc use
(e.g. regenerating after the agent has been stopped).

Usage:
    python scripts/generate_telemetry_html.py --data-dir ./demo_run --out telemetry.html
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.reports import generate_html


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="./demo_run")
    parser.add_argument("--out", default="telemetry.html")
    args = parser.parse_args()

    count = generate_html(Path(args.data_dir), Path(args.out))
    print(f"Wrote {count} rows to {args.out}")


if __name__ == "__main__":
    main()
