"""Export a data-dir's events.db to a plain, human-readable CSV for manual inspection.

Decrypts the `data` column using the same key the agent itself uses (from the
OS keychain / fallback file under <data-dir>/secrets), so this only works
against a data-dir produced by this same machine's agent runs.

Usage:
    python scripts/export_readable_csv.py --data-dir ./demo_run --out events_readable.csv
"""
from __future__ import annotations

import argparse
import csv
import datetime
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
    parser.add_argument("--out", default="events_readable.csv")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    store = SecretStore(fallback_dir=data_dir / "secrets")
    cipher = FieldCipher(get_or_create_fernet_key(store))

    con = sqlite3.connect(data_dir / "events.db")
    rows = con.execute(
        "SELECT collector, ts, duration, data, synced FROM events ORDER BY ts ASC"
    ).fetchall()

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["time", "collector", "duration_secs", "uploaded", "details"])
        for collector, ts, duration, raw, synced in rows:
            decrypted = cipher.decrypt_json(raw)
            t = datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S")
            details = ", ".join(f"{k}={v}" for k, v in decrypted.items())
            writer.writerow([t, collector, f"{duration:.1f}", "yes" if synced else "no", details])

    print(f"Wrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
