"""Buddy's remembered choices -- muted, hidden, and where it sits on the screen
edge -- in one small JSON file in the agent's data dir (`buddy.json`), so they
survive an agent restart.

Shared by the voice (agent/voice.py) and the robot window (agent/robot.py),
which run on different threads, hence the lock. A missing or unreadable file
just means defaults; a failed save is logged, never raised.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class BuddySettings:
    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else None
        self._lock = threading.Lock()
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if self._path is None or not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            logger.warning("Could not read Buddy's saved settings; using defaults", exc_info=True)
            return {}

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            if self._path is None:
                return
            try:
                self._path.write_text(json.dumps(self._data), encoding="utf-8")
            except OSError:
                logger.warning("Could not save Buddy's settings", exc_info=True)
