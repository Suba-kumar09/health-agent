from __future__ import annotations

import logging
import platform as platform_module
import threading
import time
from collections.abc import Callable

from agent.collectors.base import Collector
from agent.collectors.coalescing import CoalescingStatePoller

logger = logging.getLogger(__name__)


def _afk_state_key(info: dict | None) -> str | None:
    return info.get("state") if info else None


def _resolve_is_locked_backend() -> Callable[[], bool]:
    system = platform_module.system()
    try:
        if system == "Windows":
            from agent.platform.windows import is_workstation_locked
            return is_workstation_locked
        if system == "Darwin":
            from agent.platform.macos import is_workstation_locked
            return is_workstation_locked
        if system == "Linux":
            from agent.platform.linux import is_workstation_locked
            return is_workstation_locked
    except ImportError as exc:
        logger.error("lock-state backend unavailable on %s: %s", system, exc)
        return lambda: False
    logger.error("lock-state: unsupported platform %s", system)
    return lambda: False


class AfkCollector(Collector):
    """Derives active/idle/locked state from the input watcher's last-activity
    timestamp plus the OS workstation-lock state.

    Locked always wins (checked first) since input can't happen on a locked
    session; otherwise no input for `threshold_secs` -> "afk" (idle).
    Brackets other collectors' events so downstream processing can exclude
    activity attributed while away.
    """

    name = "afk"

    def __init__(
        self,
        get_last_activity_ts: Callable[[], float],
        on_new_state: Callable[[dict, float], str],
        on_extend: Callable[[str, float], bool],
        threshold_secs: float = 120.0,
        poll_interval_secs: float = 5.0,
        now_fn: Callable[[], float] = time.time,
        is_locked_fn: Callable[[], bool] | None = None,
    ) -> None:
        self.get_last_activity_ts = get_last_activity_ts
        self.threshold_secs = threshold_secs
        self.poll_interval_secs = poll_interval_secs
        self.now_fn = now_fn
        self.is_locked_fn = is_locked_fn or _resolve_is_locked_backend()
        self.poller = CoalescingStatePoller(_afk_state_key, on_new_state, on_extend, now_fn=now_fn)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def current_state(self, now: float | None = None) -> str:
        now = self.now_fn() if now is None else now
        if self.is_locked_fn():
            return "locked"
        idle_for = now - self.get_last_activity_ts()
        return "afk" if idle_for >= self.threshold_secs else "active"

    def poll_once(self, now: float | None = None) -> None:
        now = self.now_fn() if now is None else now
        self.poller.poll({"state": self.current_state(now)}, now=now)

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self.poll_interval_secs * 2)

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            self.poll_once()
            self._stop_event.wait(self.poll_interval_secs)
