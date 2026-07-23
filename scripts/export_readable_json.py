"""Export a data-dir's entire events.db history to a single, plain JSON array.

Decrypts every row (same key the agent itself uses, from the OS keychain /
fallback file under <data-dir>/secrets) and writes it as one JSON array file --
the full accumulated history, same data `telemetry.html` is built from, but as
plain JSON for scripting/external tools instead of a dashboard.

This differs from the live `<data-dir>/events.jsonl` (agent/json_log.py):
that one only contains events written since json logging was turned on and
grows automatically as the agent runs; this script re-derives the complete
history from events.db on demand, any time you run it.

Usage:
    python scripts/export_readable_json.py --data-dir ./demo_run --out events_export.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.crypto import FieldCipher
from agent.main import get_or_create_fernet_key
from agent.secrets import SecretStore


def export(data_dir: Path, out: Path) -> int:
    """Regenerate `out` from `data_dir`'s full events.db history. Returns event count."""
    store = SecretStore(fallback_dir=data_dir / "secrets")
    cipher = FieldCipher(get_or_create_fernet_key(store))

    con = sqlite3.connect(data_dir / "events.db")
    rows = con.execute(
        "SELECT event_id, collector, ts, duration, data, synced FROM events ORDER BY ts ASC"
    ).fetchall()
    con.close()

    events = []
    for event_id, collector, ts, duration, raw, synced in rows:
        events.append(
            {
                "event_id": event_id,
                "collector": collector,
                "ts": ts,
                "time": datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"),
                "duration": round(duration, 1),
                "uploaded": bool(synced),
                "data": cipher.decrypt_json(raw),
            }
        )

    Path(out).write_text(json.dumps(events, indent=2), encoding="utf-8")
    return len(events)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="./demo_run")
    parser.add_argument("--out", default="events_export.json")
    args = parser.parse_args()

    count = export(Path(args.data_dir), Path(args.out))
    print(f"Wrote {count} events to {args.out}")


if __name__ == "__main__":
    main()
