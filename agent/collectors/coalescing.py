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
        on_extend: Callable[[str, float], bool],
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
            extended = self.on_extend(self._current_event_id, now - self._current_start)
            if extended:
                return
            # The row got frozen by an in-flight batch upload (see
            # Storage.extend_duration's synced=0/batch_id IS NULL guard) --
            # the state itself hasn't changed, but without minting a fresh
            # event here, a long-unbroken streak would silently stop growing
            # from the server's perspective the moment the first batch caught
            # it, forever, since this same key never triggers the "state
            # changed" branch below on its own.
            self._current_start = now
            self._current_event_id = self.on_new_state(info, now)
            return

        self._current_key = key
        self._current_start = now
        if info is not None and key is not None:
            self._current_event_id = self.on_new_state(info, now)
        else:
            self._current_event_id = None
