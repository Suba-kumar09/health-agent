from __future__ import annotations

import time
from collections.abc import Callable, Hashable


class CoalescingStatePoller:
    """Generic state-diffing poller: coalesces consecutive identical states

    into a single heartbeat-extended event instead of one row per poll
    (ActivityWatch's coalescing technique). Used by both the window watcher
    (state = (app, title)) and the AFK collector (state = "active"/"afk").
    """

    def __init__(
        self,
        state_key_fn: Callable[[dict | None], Hashable | None],
        on_new_state: Callable[[dict, float], str],
        on_extend: Callable[[str, float], None],
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        self.state_key_fn = state_key_fn
        self.on_new_state = on_new_state
        self.on_extend = on_extend
        self.now_fn = now_fn
        self._current_key: Hashable | None = None
        self._current_event_id: str | None = None
        self._current_start: float | None = None

    def poll(self, info: dict | None, now: float | None = None) -> None:
        now = self.now_fn() if now is None else now
        key = self.state_key_fn(info)

        if key == self._current_key and self._current_event_id is not None:
            self.on_extend(self._current_event_id, now - self._current_start)
            return

        self._current_key = key
        self._current_start = now
        if info is not None and key is not None:
            self._current_event_id = self.on_new_state(info, now)
        else:
            self._current_event_id = None
