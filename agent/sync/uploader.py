from __future__ import annotations

import gzip
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Protocol

import httpx

from agent.config import SyncSection
from agent.storage import Event, Storage
from agent.sync.api import IngestEvent, IngestRequest, IngestResponse

logger = logging.getLogger(__name__)


def chunk_events(events: list[Event], max_events: int, max_bytes: int) -> list[list[Event]]:
    """Split events into batches respecting count and approximate-size caps.

    A single oversized event is still placed in its own chunk (best effort;
    events aren't split further since they're the atomic unit of storage).
    """
    chunks: list[list[Event]] = []
    current: list[Event] = []
    current_bytes = 0
    for e in events:
        e_bytes = len(
            json.dumps(
                {"event_id": e.event_id, "collector": e.collector, "ts": e.ts, "duration": e.duration, "data": e.data},
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if current and (len(current) >= max_events or current_bytes + e_bytes > max_bytes):
            chunks.append(current)
            current = []
            current_bytes = 0
        current.append(e)
        current_bytes += e_bytes
    if current:
        chunks.append(current)
    return chunks


class BackoffState:
    """Exponential backoff, with server-supplied Retry-After taking precedence."""

    def __init__(self, initial_secs: float, max_secs: float) -> None:
        self.initial_secs = initial_secs
        self.max_secs = max_secs
        self._current = initial_secs
        self.blocked_until = 0.0

    def on_failure(self, now: float, retry_after: float | None = None) -> None:
        if retry_after is not None:
            self.blocked_until = now + retry_after
        else:
            self.blocked_until = now + self._current
            self._current = min(self._current * 2, self.max_secs)

    def on_success(self) -> None:
        self._current = self.initial_secs
        self.blocked_until = 0.0

    def is_blocked(self, now: float) -> bool:
        return now < self.blocked_until


@dataclass
class SendResult:
    outcome: str  # "ok" | "auth_failed" | "too_large" | "rate_limited" | "network_error"
    accepted: list[str]
    duplicates: list[str]
    retry_after: float | None = None


class TokenProvider(Protocol):
    def __call__(self) -> str: ...


class Uploader:
    def __init__(
        self,
        storage: Storage,
        http_client: httpx.Client,
        sync_cfg: SyncSection,
        server_url: str,
        device_id: str,
        agent_version: str,
        os_name: str,
        os_version: str,
        token_provider: TokenProvider,
        inter_batch_delay_secs: float = 2.0,
        now_fn: Callable[[], float] = time.time,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.storage = storage
        self.http_client = http_client
        self.cfg = sync_cfg
        self.server_url = server_url.rstrip("/")
        self.device_id = device_id
        self.agent_version = agent_version
        self.os_name = os_name
        self.os_version = os_version
        self.token_provider = token_provider
        self.inter_batch_delay_secs = inter_batch_delay_secs
        self.now_fn = now_fn
        self.sleep_fn = sleep_fn
        self.backoff = BackoffState(sync_cfg.backoff_initial_secs, sync_cfg.backoff_max_secs)

    def _next_batch(self) -> tuple[str, list[Event]] | None:
        pending_ids = self.storage.pending_batch_ids()
        if pending_ids:
            batch_id = pending_ids[0]
            return batch_id, self.storage.events_for_batch(batch_id)

        events = self.storage.unassigned_unsynced(self.cfg.batch_max_events)
        if not events:
            return None
        chunks = chunk_events(events, self.cfg.batch_max_events, self.cfg.batch_max_bytes)
        batch = chunks[0]
        batch_id = str(uuid.uuid4())
        self.storage.assign_batch([e.event_id for e in batch], batch_id)
        return batch_id, batch

    def _build_request(self, batch_id: str, events: list[Event]) -> IngestRequest:
        return IngestRequest(
            device_id=self.device_id,
            agent_version=self.agent_version,
            os=self.os_name,
            os_version=self.os_version,
            batch_id=batch_id,
            sent_at=self.now_fn(),
            events=[
                IngestEvent(event_id=e.event_id, collector=e.collector, ts=e.ts, duration=e.duration, data=e.data)
                for e in events
            ],
        )

    def _send(self, batch_id: str, request: IngestRequest) -> SendResult:
        body = request.model_dump_json().encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.token_provider()}",
            "Idempotency-Key": batch_id,
            "Content-Type": "application/json",
        }
        if self.cfg.gzip:
            body = gzip.compress(body)
            headers["Content-Encoding"] = "gzip"

        try:
            resp = self.http_client.post(f"{self.server_url}/v1/ingest", content=body, headers=headers)
        except httpx.RequestError as exc:
            logger.info("Upload network error for batch %s: %s", batch_id, exc)
            return SendResult(outcome="network_error", accepted=[], duplicates=[])

        if resp.status_code == 200:
            parsed = IngestResponse.model_validate(resp.json())
            return SendResult(outcome="ok", accepted=parsed.accepted, duplicates=parsed.duplicates)
        if resp.status_code == 401:
            return SendResult(outcome="auth_failed", accepted=[], duplicates=[])
        if resp.status_code == 413:
            return SendResult(outcome="too_large", accepted=[], duplicates=[])
        if resp.status_code == 429:
            retry_after = None
            try:
                retry_after = float(resp.json().get("retry_after", resp.headers.get("Retry-After", 30)))
            except (ValueError, TypeError):
                retry_after = 30.0
            return SendResult(outcome="rate_limited", accepted=[], duplicates=[], retry_after=retry_after)
        return SendResult(outcome="network_error", accepted=[], duplicates=[])

    def run_tick(self) -> dict:
        """Drain up to `max_batches_per_tick` batches, paced by inter-batch delay.

        Returns a small summary dict useful for logging/tests.
        """
        now = self.now_fn()
        if self.backoff.is_blocked(now):
            return {"sent_batches": 0, "reason": "backoff", "blocked_until": self.backoff.blocked_until}

        sent = 0
        for i in range(self.cfg.max_batches_per_tick):
            next_batch = self._next_batch()
            if next_batch is None:
                break
            batch_id, events = next_batch
            request = self._build_request(batch_id, events)
            result = self._send(batch_id, request)

            if result.outcome == "ok":
                synced_ids = result.accepted + result.duplicates
                self.storage.mark_synced(synced_ids or [e.event_id for e in events])
                self.backoff.on_success()
                sent += 1
                if i < self.cfg.max_batches_per_tick - 1 and self.storage.count_unsynced() > 0:
                    self.sleep_fn(self.inter_batch_delay_secs)
            else:
                retry_after = result.retry_after
                self.backoff.on_failure(self.now_fn(), retry_after)
                return {"sent_batches": sent, "reason": result.outcome, "blocked_until": self.backoff.blocked_until}

        return {"sent_batches": sent, "reason": "drained" if sent else "empty"}
