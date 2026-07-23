"""End-to-end: storage -> uploader -> mock ingest server (FastAPI/ASGI)."""
from fastapi.testclient import TestClient

from agent.config import SyncSection
from agent.crypto import FieldCipher
from agent.storage import Event, Storage
from agent.sync.uploader import Uploader
from tests.mock_server import MockIngestServer


def make_uploader(storage, server, sync_cfg=None, sleep_fn=None, now_fn=None):
    # TestClient wraps the ASGI app with a sync-compatible transport (via an
    # anyio portal), so it can stand in directly for the httpx.Client the
    # Uploader expects -- no real network port needed for this "mock server".
    client = TestClient(server.app, base_url="https://ingest.test")
    return Uploader(
        storage=storage,
        http_client=client,
        sync_cfg=sync_cfg or SyncSection(max_batches_per_tick=5, batch_max_events=3, gzip=True),
        server_url="https://ingest.test",
        device_id="dev-1",
        agent_version="0.1.0",
        os_name="windows",
        os_version="11",
        token_provider=lambda: server.expected_token,
        inter_batch_delay_secs=0.0,
        now_fn=now_fn or (lambda: 1000.0),
        sleep_fn=sleep_fn or (lambda s: None),
    )


def test_offline_then_online_drains_backlog_in_paced_batches(tmp_path):
    storage = Storage(tmp_path / "events.db", cipher=FieldCipher(FieldCipher.generate_key()))
    server = MockIngestServer()

    # Simulate a long offline stretch: events pile up, nothing synced.
    server.force_offline = True
    for i in range(7):
        storage.append(Event(collector="input_watcher", ts=float(i), data={"keypress_count": i}))

    sync_cfg = SyncSection(max_batches_per_tick=5, batch_max_events=3, gzip=True)
    uploader = make_uploader(storage, server, sync_cfg=sync_cfg)
    result = uploader.run_tick()
    assert result["sent_batches"] == 0
    assert storage.count_unsynced() == 7

    # Network restored: backlog should drain, paced at most max_batches_per_tick per tick.
    server.force_offline = False
    sleeps = []
    uploader.sleep_fn = lambda s: sleeps.append(s)
    uploader.backoff.blocked_until = 0

    result = uploader.run_tick()

    assert storage.count_unsynced() == 0
    assert result["sent_batches"] == 3  # ceil(7/3) batches: 3+3+1
    assert len(server.received_requests) == 3
    assert len(sleeps) == 2  # paced between the 3 batches sent


def test_retry_after_partial_failure_is_idempotent_on_server(tmp_path):
    storage = Storage(tmp_path / "events.db", cipher=FieldCipher(FieldCipher.generate_key()))
    server = MockIngestServer()
    for i in range(3):
        storage.append(Event(collector="afk", ts=float(i), data={}))

    sync_cfg = SyncSection(max_batches_per_tick=5, batch_max_events=10, gzip=False)
    uploader = make_uploader(storage, server, sync_cfg=sync_cfg)

    result = uploader.run_tick()
    assert result["sent_batches"] == 1
    assert storage.count_unsynced() == 0
    first_batch_id = list(server.seen_batch_ids)[0]

    # Client retries the *same* batch (e.g. it never saw the 200 due to a dropped
    # response) -- server must dedupe by event_id and the client must still end
    # up with everything marked synced, no duplicates created server-side.
    events = storage.events_for_batch(first_batch_id)
    request = uploader._build_request(first_batch_id, events)
    resend = uploader._send(first_batch_id, request)

    assert resend.outcome == "ok"
    assert resend.duplicates == [e.event_id for e in events]
    assert len(server.received_requests) == 2
    assert len(server.seen_event_ids) == 3  # no duplicate ingestion server-side
