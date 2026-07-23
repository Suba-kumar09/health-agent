"""Export a data-dir's entire events.db history to a single, plain JSON array.

The running agent already does this itself on a timer (see the `[reports]`
config section and agent/main.py) as long as it's started without
`--no-reports`, so you normally don't need to run this manually. This script
is a one-shot CLI wrapper around `agent.reports.export_json` for ad-hoc use
(e.g. regenerating after the agent has been stopped).

Usage:
    python scripts/export_readable_json.py --data-dir ./demo_run --out events_export.json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.reports import export_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="./demo_run")
    parser.add_argument("--out", default="events_export.json")
    args = parser.parse_args()

    count = export_json(Path(args.data_dir), Path(args.out))
    print(f"Wrote {count} events to {args.out}")


if __name__ == "__main__":
    main()
