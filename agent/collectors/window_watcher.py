from __future__ import annotations

import logging
import platform as platform_module
import threading
import time
from typing import Callable

from agent.collectors.base import Collector
from agent.collectors.coalescing import CoalescingStatePoller

logger = logging.getLogger(__name__)


def _window_state_key(info: dict | None) -> tuple | None:
    return (info.get("app"), info.get("title")) if info else None


class WindowWatcherCollector(Collector):
    """Polls the foreground app/window (~2s default) via a per-OS backend."""

    name = "window_watcher"

    def __init__(
        self,
        on_new_window: Callable[[dict, float], str],
        on_extend: Callable[[str, float], None],
        poll_interval_secs: float = 2.0,
        get_active_window_fn: Callable[[], dict | None] | None = None,
    ) -> None:
        self.poller = CoalescingStatePoller(_window_state_key, on_new_window, on_extend)
        self.poll_interval_secs = poll_interval_secs
        self._get_active_window = get_active_window_fn or self._resolve_backend()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @staticmethod
    def _resolve_backend() -> Callable[[], dict | None] | None:
        system = platform_module.system()
        try:
            if system == "Windows":
                from agent.platform.windows import get_active_window
                return get_active_window
            if system == "Darwin":
                from agent.platform.macos import get_active_window
                return get_active_window
            if system == "Linux":
                from agent.platform.linux import is_wayland, get_active_window
                if is_wayland():
                    logger.warning("Wayland session detected -- window_watcher is unavailable (known Phase-1 limitation)")
                    return None
                return get_active_window
        except ImportError as exc:
            logger.error("window_watcher backend unavailable on %s: %s", system, exc)
            return None
        logger.error("window_watcher: unsupported platform %s", system)
        return None

    def start(self) -> None:
        if self._get_active_window is None:
            logger.warning("window_watcher disabled: no backend available")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self.poll_interval_secs * 2)

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                info = self._get_active_window()
                self.poller.poll(info)
            except Exception:
                logger.exception("window_watcher poll failed")
            self._stop_event.wait(self.poll_interval_secs)
