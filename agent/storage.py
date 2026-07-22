from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from agent.crypto import NullCipher

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id   TEXT PRIMARY KEY,
    collector  TEXT NOT NULL,
    ts         REAL NOT NULL,
    duration   REAL NOT NULL DEFAULT 0,
    data       BLOB NOT NULL,
    synced     INTEGER NOT NULL DEFAULT 0,
    batch_id   TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_synced ON events (synced);
CREATE INDEX IF NOT EXISTS idx_events_batch_id ON events (batch_id);
CREATE INDEX IF NOT EXISTS idx_events_collector_ts ON events (collector, ts);
"""


class Event:
    __slots__ = ("event_id", "collector", "ts", "duration", "data", "synced", "batch_id")

    def __init__(
        self,
        collector: str,
        ts: float,
        data: dict[str, Any],
        duration: float = 0.0,
        event_id: str | None = None,
        synced: bool = False,
        batch_id: str | None = None,
    ) -> None:
        self.event_id = event_id or str(uuid.uuid4())
        self.collector = collector
        self.ts = ts
        self.duration = duration
        self.data = data
        self.synced = synced
        self.batch_id = batch_id


class Storage:
    """SQLite-backed local event buffer (WAL mode).

    Only the `data` payload column is encrypted (via the supplied cipher);
    event_id/collector/ts/duration/synced/batch_id stay plaintext so sync and
    dedup queries don't need to touch the cipher.

    Collectors run on independent threads and all write through this one
    connection (check_same_thread=False), but a single sqlite3.Connection
    is not safe under concurrent execute() calls from multiple threads --
    two threads can each trigger an implicit BEGIN and collide ("cannot
    start a transaction within a transaction"). All access is serialized
    through `_lock`.
    """

    def __init__(self, db_path: str | Path, cipher: Any | None = None) -> None:
        self._path = Path(db_path)
        self._cipher = cipher or NullCipher()
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def append(self, event: Event) -> None:
        blob = self._cipher.encrypt_json(event.data)
        with self._lock:
            self._conn.execute(
                "INSERT INTO events (event_id, collector, ts, duration, data, synced, batch_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (event.event_id, event.collector, event.ts, event.duration, blob, int(event.synced), event.batch_id),
            )
            self._conn.commit()

    def append_many(self, events: Iterable[Event]) -> None:
        rows = [
            (
                e.event_id,
                e.collector,
                e.ts,
                e.duration,
                self._cipher.encrypt_json(e.data),
                int(e.synced),
                e.batch_id,
            )
            for e in events
        ]
        with self._lock:
            self._conn.executemany(
                "INSERT INTO events (event_id, collector, ts, duration, data, synced, batch_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()

    def _row_to_event(self, row: tuple) -> Event:
        event_id, collector, ts, duration, blob, synced, batch_id = row
        data = self._cipher.decrypt_json(blob)
        return Event(
            collector=collector,
            ts=ts,
            data=data,
            duration=duration,
            event_id=event_id,
            synced=bool(synced),
            batch_id=batch_id,
        )

    def unsynced(self, limit: int) -> list[Event]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT event_id, collector, ts, duration, data, synced, batch_id "
                "FROM events WHERE synced = 0 ORDER BY ts ASC LIMIT ?",
                (limit,),
            )
            rows = cur.fetchall()
        return [self._row_to_event(row) for row in rows]

    def unassigned_unsynced(self, limit: int) -> list[Event]:
        """Unsynced events not yet part of an in-flight batch."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT event_id, collector, ts, duration, data, synced, batch_id "
                "FROM events WHERE synced = 0 AND batch_id IS NULL ORDER BY ts ASC LIMIT ?",
                (limit,),
            )
            rows = cur.fetchall()
        return [self._row_to_event(row) for row in rows]

    def pending_batch_ids(self) -> list[str]:
        """batch_ids assigned but not yet confirmed synced -- retry these before

        creating new batches, reusing the same batch_id (idempotency key) so a
        crash-mid-upload doesn't silently duplicate a batch under a new id.
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT batch_id, MIN(ts) AS first_ts FROM events "
                "WHERE synced = 0 AND batch_id IS NOT NULL "
                "GROUP BY batch_id ORDER BY first_ts ASC"
            )
            rows = cur.fetchall()
        return [row[0] for row in rows]

    def count_unsynced(self) -> int:
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) FROM events WHERE synced = 0")
            return cur.fetchone()[0]

    def assign_batch(self, event_ids: list[str], batch_id: str) -> None:
        with self._lock:
            self._conn.executemany(
                "UPDATE events SET batch_id = ? WHERE event_id = ?",
                [(batch_id, eid) for eid in event_ids],
            )
            self._conn.commit()

    def extend_duration(self, event_id: str, duration: float) -> bool:
        """Extend an in-progress heartbeat event's duration.

        Only applies while the event is still unsynced and not yet part of an
        in-flight batch -- once assigned/synced it's immutable, so a state
        that's still "current" when the batch fires just gets finalized as-is
        and a fresh event starts on the next poll.
        """
        with self._lock:
            cur = self._conn.execute(
                "UPDATE events SET duration = ? WHERE event_id = ? AND synced = 0 AND batch_id IS NULL",
                (duration, event_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def mark_synced(self, event_ids: list[str]) -> None:
        with self._lock:
            self._conn.executemany(
                "UPDATE events SET synced = 1 WHERE event_id = ?",
                [(eid,) for eid in event_ids],
            )
            self._conn.commit()

    def events_for_batch(self, batch_id: str) -> list[Event]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT event_id, collector, ts, duration, data, synced, batch_id "
                "FROM events WHERE batch_id = ? ORDER BY ts ASC",
                (batch_id,),
            )
            rows = cur.fetchall()
        return [self._row_to_event(row) for row in rows]

    def purge_synced(self, older_than_secs: float) -> int:
        cutoff = time.time() - older_than_secs
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM events WHERE synced = 1 AND ts < ?",
                (cutoff,),
            )
            self._conn.commit()
            return cur.rowcount
