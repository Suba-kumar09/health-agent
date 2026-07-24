from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.storage import Event


class JsonEventLogger:
    """Append-only, plain-text JSON Lines mirror of every captured event.

    Unlike `events.db`, this is deliberately NOT encrypted -- it exists so the
    captured data is directly readable (e.g. for scripting, external tools)
    without needing the Fernet key. That means the file itself is sensitive
    (real window titles, browsing activity, activity counts) and must never
    be committed to git -- see .gitignore.

    One JSON object per line (not one big JSON array) so appending is O(1)
    and a crash mid-write only ever corrupts the last, still-in-flight line
    rather than the whole file.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def append(self, event: Event) -> None:
        record = {
            "event_id": event.event_id,
            "collector": event.collector,
            "ts": event.ts,
            "duration": event.duration,
            "data": event.data,
        }
        line = json.dumps(record, separators=(",", ":"))
        with self._lock:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
