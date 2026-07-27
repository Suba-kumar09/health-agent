"""Per-device fixed-window rate limiting, backed by the same database as
everything else (not a separate Redis cluster -- disproportionate for the
handful of devices this server is sized for). Keeping the counter in
Postgres/SQLite rather than in-process memory means it stays correct even if
the web service is scaled to more than one instance.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.models import RateLimitCounter


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after: float = 0.0


def check_and_increment(
    session: Session,
    device_id: str,
    window_secs: int,
    max_requests: int,
) -> RateLimitResult:
    now = time.time()
    row = (
        session.execute(
            select(RateLimitCounter).where(RateLimitCounter.device_id == device_id).with_for_update()
        )
        .scalar_one_or_none()
    )

    if row is None:
        session.add(RateLimitCounter(device_id=device_id, window_start=now, count_in_window=1))
        return RateLimitResult(allowed=True)

    window_elapsed = now - row.window_start
    if window_elapsed >= window_secs:
        row.window_start = now
        row.count_in_window = 1
        return RateLimitResult(allowed=True)

    if row.count_in_window < max_requests:
        row.count_in_window += 1
        return RateLimitResult(allowed=True)

    retry_after = window_secs - window_elapsed
    return RateLimitResult(allowed=False, retry_after=max(retry_after, 0.0))
