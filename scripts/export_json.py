"""Export a data-dir's events.db to a JSON array, one object per captured event.

Decrypts the `data` column using the same key the agent itself uses (from the
OS keychain / fallback file under <data-dir>/secrets), so this only works
against a data-dir produced by this same machine's agent runs.

Usage:
    python scripts/export_json.py --data-dir ./demo_run --out events.json
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="./demo_run")
    parser.add_argument("--out", default="events.json")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    store = SecretStore(fallback_dir=data_dir / "secrets")
    cipher = FieldCipher(get_or_create_fernet_key(store))

    con = sqlite3.connect(data_dir / "events.db")
    rows = con.execute(
        "SELECT event_id, collector, ts, duration, data, synced, batch_id FROM events ORDER BY ts ASC"
    ).fetchall()

    events = []
    for event_id, collector, ts, duration, raw, synced, batch_id in rows:
        events.append(
            {
                "event_id": event_id,
                "collector": collector,
                "ts": ts,
                "time": datetime.datetime.fromtimestamp(ts).isoformat(timespec="seconds"),
                "duration": round(duration, 3),
                "synced": bool(synced),
                "batch_id": batch_id,
                "data": cipher.decrypt_json(raw),
            }
        )

    Path(args.out).write_text(json.dumps(events, indent=2), encoding="utf-8")
    print(f"Wrote {len(events)} events to {args.out}")


if __name__ == "__main__":
    main()
