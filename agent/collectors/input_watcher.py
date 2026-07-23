from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from agent.collectors.base import Collector

logger = logging.getLogger(__name__)


@dataclass
class InputBucket:
    bucket_start: float
    keypress_count: int = 0
    click_count: int = 0
    scroll_count: int = 0
    mouse_dist_px: float = 0.0
    active_seconds: set[int] = field(default_factory=set)
    key_codes: list[str] = field(default_factory=list)  # only populated in "detailed" mode

    def to_data(self, detailed: bool) -> dict:
        data = {
            "keypress_count": self.keypress_count,
            "click_count": self.click_count,
            "scroll_count": self.scroll_count,
            "mouse_dist_px": round(self.mouse_dist_px, 1),
            "active_secs": len(self.active_seconds),
        }
        if detailed:
            data["key_codes"] = list(self.key_codes)
        return data


class InputBucketAggregator:
    """Pure bucketing logic for keyboard/mouse activity -- no OS hooks here.

    Kept independent of pynput so the bucketing math (the trickiest part) is
    unit-testable without a real keyboard/mouse or display session.
    """

    def __init__(self, bucket_seconds: int, capture_mode: str, now_fn: Callable[[], float] = time.time) -> None:
        self.bucket_seconds = bucket_seconds
        self.capture_mode = capture_mode  # "aggregate" | "detailed"
        self.now_fn = now_fn
        self._bucket = InputBucket(bucket_start=self.now_fn())
        self._last_pos: tuple[float, float] | None = None
        self.last_activity_ts: float = self._bucket.bucket_start

    def _mark_active(self, ts: float) -> None:
        self._bucket.active_seconds.add(int(ts - self._bucket.bucket_start))
        self.last_activity_ts = ts

    def on_key_press(self, key_code: str, ts: float | None = None) -> None:
        ts = self.now_fn() if ts is None else ts
        self._bucket.keypress_count += 1
        if self.capture_mode == "detailed":
            self._bucket.key_codes.append(key_code)
        self._mark_active(ts)

    def on_click(self, ts: float | None = None) -> None:
        ts = self.now_fn() if ts is None else ts
        self._bucket.click_count += 1
        self._mark_active(ts)

    def on_scroll(self, ts: float | None = None) -> None:
        ts = self.now_fn() if ts is None else ts
        self._bucket.scroll_count += 1
        self._mark_active(ts)

    def on_move(self, x: float, y: float, ts: float | None = None) -> None:
        ts = self.now_fn() if ts is None else ts
        if self._last_pos is not None:
            dx = x - self._last_pos[0]
            dy = y - self._last_pos[1]
            self._bucket.mouse_dist_px += (dx * dx + dy * dy) ** 0.5
        self._last_pos = (x, y)
        self._mark_active(ts)

    def maybe_flush(self, now: float | None = None) -> InputBucket | None:
        """Return and reset the current bucket once bucket_seconds has elapsed."""
        now = self.now_fn() if now is None else now
        if now - self._bucket.bucket_start >= self.bucket_seconds:
            return self.force_flush(now)
        return None

    def force_flush(self, now: float | None = None) -> InputBucket:
        now = self.now_fn() if now is None else now
        completed = self._bucket
        self._bucket = InputBucket(bucket_start=now)
        return completed


class InputWatcherCollector(Collector):
    """Global keyboard/mouse listener (pynput) feeding an InputBucketAggregator.

    A background poll thread flushes completed buckets (including all-zero,
    idle buckets -- the AFK collector needs those too) into storage on the
    aggregator's own cadence, independent of listener callback timing.
    """

    name = "input_watcher"

    def __init__(
        self,
        bucket_seconds: int,
        capture_mode: str,
        on_bucket: Callable[[InputBucket], None],
        poll_interval_secs: float = 1.0,
    ) -> None:
        self.aggregator = InputBucketAggregator(bucket_seconds, capture_mode)
        self.on_bucket = on_bucket
        self.poll_interval_secs = poll_interval_secs
        self._keyboard_listener = None
        self._mouse_listener = None
        self._poll_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        try:
            from pynput import keyboard, mouse
        except ImportError as exc:  # pragma: no cover - environment-dependent
            logger.error("pynput unavailable, input_watcher disabled: %s", exc)
            return

        def on_press(key):
            code = self._key_code(key)
            self.aggregator.on_key_press(code)

        def on_click(x, y, button, pressed):
            if pressed:
                self.aggregator.on_click()

        def on_scroll(x, y, dx, dy):
            self.aggregator.on_scroll()

        def on_move(x, y):
            self.aggregator.on_move(x, y)

        self._keyboard_listener = keyboard.Listener(on_press=on_press)
        self._mouse_listener = mouse.Listener(on_click=on_click, on_scroll=on_scroll, on_move=on_move)
        self._keyboard_listener.start()
        self._mouse_listener.start()

        self._stop_event.clear()
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=self.poll_interval_secs * 2)
        if self._keyboard_listener is not None:
            self._keyboard_listener.stop()
        if self._mouse_listener is not None:
            self._mouse_listener.stop()
        completed = self.aggregator.force_flush()
        self.on_bucket(completed)

    def _poll_loop(self) -> None:
        while not self._stop_event.wait(self.poll_interval_secs):
            completed = self.aggregator.maybe_flush()
            if completed is not None:
                self.on_bucket(completed)

    @staticmethod
    def _key_code(key) -> str:
        try:
            return key.char or str(key)
        except AttributeError:
            return str(key)
