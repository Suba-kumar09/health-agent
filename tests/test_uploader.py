import json

import httpx
import pytest

from agent.config import SyncSection
from agent.crypto import NullCipher
from agent.storage import Event, Storage
from agent.sync.uploader import Uploader, chunk_events


def make_storage(tmp_path):
    return Storage(tmp_path / "events.db", cipher=NullCipher())


def make_uploader(storage, transport, sync_cfg=None, now_fn=None, sleep_fn=None, inter_batch_delay=0.0):
    client = httpx.Client(transport=transport)
    return Uploader(
        storage=storage,
        http_client=client,
        sync_cfg=sync_cfg or SyncSection(max_batches_per_tick=5, batch_max_events=10, gzip=False),
        server_url="https://ingest.test",
        device_id="dev-1",
        agent_version="0.1.0",
        os_name="windows",
        os_version="11",
        token_provider=lambda: "test-token",
        inter_batch_delay_secs=inter_batch_delay,
        now_fn=now_fn or (lambda: 1000.0),
        sleep_fn=sleep_fn or (lambda secs: None),
    )


def test_chunk_events_respects_max_events():
    events = [Event(collector="c", ts=i, data={}) for i in range(5)]
    chunks = chunk_events(events, max_events=2, max_bytes=10_000)
    assert [len(c) for c in chunks] == [2, 2, 1]


def test_chunk_events_respects_max_bytes():
    events = [Event(collector="c", ts=i, data={"x": "a" * 50}) for i in range(3)]
    chunks = chunk_events(events, max_events=100, max_bytes=120)
    assert len(chunks) >= 2


def test_successful_upload_marks_events_synced(tmp_path):
    storage = make_storage(tmp_path)
    e = Event(collector="input_watcher", ts=1.0, data={"keypress_count": 3})
    storage.append(e)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        event_ids = [ev["event_id"] for ev in body["events"]]
        return httpx.Response(200, json={"accepted": event_ids, "duplicates": []})

    uploader = make_uploader(storage, httpx.MockTransport(handler))
    result = uploader.run_tick()

    assert result["sent_batches"] == 1
    assert storage.count_unsynced() == 0


def test_auth_failure_leaves_events_unsynced_and_triggers_backoff(tmp_path):
    storage = make_storage(tmp_path)
    storage.append(Event(collector="afk", ts=1.0, data={}))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    uploader = make_uploader(storage, httpx.MockTransport(handler))
    result = uploader.run_tick()

    assert result["reason"] == "auth_failed"
    assert storage.count_unsynced() == 1
    assert uploader.backoff.is_blocked(1000.0)


def test_rate_limit_uses_server_retry_after(tmp_path):
    storage = make_storage(tmp_path)
    storage.append(Event(collector="afk", ts=1.0, data={}))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"retry_after": 42})

    uploader = make_uploader(storage, httpx.MockTransport(handler), now_fn=lambda: 1000.0)
    result = uploader.run_tick()

    assert result["reason"] == "rate_limited"
    assert uploader.backoff.blocked_until == pytest.approx(1042.0)


def test_network_error_backs_off_without_losing_events(tmp_path):
    storage = make_storage(tmp_path)
    storage.append(Event(collector="afk", ts=1.0, data={}))

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    uploader = make_uploader(storage, httpx.MockTransport(handler))
    result = uploader.run_tick()

    assert result["reason"] == "network_error"
    assert storage.count_unsynced() == 1


def test_backlog_pacing_caps_batches_per_tick(tmp_path):
    storage = make_storage(tmp_path)
    for i in range(9):
        storage.append(Event(collector="afk", ts=float(i), data={}))

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        event_ids = [ev["event_id"] for ev in body["events"]]
        return httpx.Response(200, json={"accepted": event_ids, "duplicates": []})

    sleeps: list[float] = []
    sync_cfg = SyncSection(max_batches_per_tick=2, batch_max_events=3, gzip=False)
    uploader = make_uploader(
        storage, httpx.MockTransport(handler), sync_cfg=sync_cfg, sleep_fn=lambda s: sleeps.append(s), inter_batch_delay=5.0
    )

    result = uploader.run_tick()

    assert result["sent_batches"] == 2
    assert storage.count_unsynced() == 3  # 9 - (2 batches * 3 events)
    assert sleeps == [5.0]  # paced once between the two batches sent this tick


def test_idempotent_retry_reuses_same_batch_id(tmp_path):
    storage = make_storage(tmp_path)
    storage.append(Event(collector="afk", ts=1.0, data={}))

    seen_batch_ids = []
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        seen_batch_ids.append(request.headers["Idempotency-Key"])
        if call_count["n"] == 1:
            raise httpx.ConnectError("simulated drop", request=request)
        body = json.loads(request.content)
        event_ids = [ev["event_id"] for ev in body["events"]]
        return httpx.Response(200, json={"accepted": event_ids, "duplicates": []})

    uploader = make_uploader(storage, httpx.MockTransport(handler))
    uploader.run_tick()  # fails, batch_id persisted on the row
    uploader.backoff.blocked_until = 0  # simulate backoff having elapsed
    uploader.run_tick()  # retries

    assert seen_batch_ids[0] == seen_batch_ids[1]
    assert storage.count_unsynced() == 0
