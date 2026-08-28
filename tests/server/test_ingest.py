from __future__ import annotations

import gzip
import json
import uuid

from server.auth import mint_enrollment_code
from server.models import Employee


def _enroll(client, db_session) -> tuple[str, str]:
    if db_session.query(Employee).filter_by(system_name="test-laptop").first() is None:
        db_session.add(Employee(name="Test Employee", system_name="test-laptop"))
        db_session.commit()
    code = mint_enrollment_code(db_session, ttl_hours=24)
    db_session.commit()
    response = client.post(
        "/v1/enroll",
        json={
            "enrollment_code": code.code,
            "device_name": "test-laptop",
            "os": "Windows",
            "os_version": "11",
        },
    )
    body = response.json()
    return body["device_id"], body["device_token"]


def _batch(device_id: str, batch_id: str, n_events: int = 2) -> dict:
    return {
        "device_id": device_id,
        "agent_version": "0.1.0",
        "os": "Windows",
        "os_version": "11",
        "batch_id": batch_id,
        "sent_at": 1732000000.0,
        "events": [
            {
                "event_id": str(uuid.uuid4()),
                "collector": "input_watcher",
                "ts": 1732000000.0 + i,
                "duration": 30.0,
                "data": {"keypress_count": 10},
            }
            for i in range(n_events)
        ],
    }


def test_ingest_requires_auth_header(client):
    response = client.post(
        "/v1/ingest",
        json=_batch("some-device", "batch-1", n_events=0),
    )
    assert response.status_code == 401


def test_ingest_rejects_bad_token(client):
    response = client.post(
        "/v1/ingest",
        headers={"Authorization": "Bearer not-a-real-token"},
        json=_batch("some-device", "batch-1", n_events=0),
    )
    assert response.status_code == 401


def test_ingest_rejects_device_id_mismatch(client, db_session):
    device_id, token = _enroll(client, db_session)

    response = client.post(
        "/v1/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json=_batch("someone-elses-device-id", "batch-1", n_events=0),
    )
    assert response.status_code == 401


def test_ingest_accepts_new_events(client, db_session):
    device_id, token = _enroll(client, db_session)
    batch = _batch(device_id, "batch-1", n_events=2)

    response = client.post("/v1/ingest", headers={"Authorization": f"Bearer {token}"}, json=batch)

    assert response.status_code == 200
    body = response.json()
    assert set(body["accepted"]) == {e["event_id"] for e in batch["events"]}
    assert body["duplicates"] == []


def test_ingest_retry_of_same_batch_is_idempotent(client, db_session):
    """Mirrors the client's crash-recovery contract: retrying the exact same
    batch_id/event_id set must come back entirely as duplicates, with no new
    rows created (docs/API.md's idempotency section)."""
    device_id, token = _enroll(client, db_session)
    batch = _batch(device_id, "batch-1", n_events=2)
    event_ids = {e["event_id"] for e in batch["events"]}

    first = client.post("/v1/ingest", headers={"Authorization": f"Bearer {token}"}, json=batch)
    assert set(first.json()["accepted"]) == event_ids

    second = client.post("/v1/ingest", headers={"Authorization": f"Bearer {token}"}, json=batch)
    assert second.status_code == 200
    assert second.json()["accepted"] == []
    assert set(second.json()["duplicates"]) == event_ids

    from sqlalchemy import select

    from server.models import Event

    rows = db_session.execute(select(Event).where(Event.event_id.in_(event_ids))).scalars().all()
    assert len(rows) == len(event_ids)


def test_ingest_gzip_body_is_decompressed(client, db_session):
    device_id, token = _enroll(client, db_session)
    batch = _batch(device_id, "batch-1", n_events=1)
    compressed = gzip.compress(json.dumps(batch).encode("utf-8"))

    response = client.post(
        "/v1/ingest",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Encoding": "gzip",
            "Content-Type": "application/json",
        },
        content=compressed,
    )

    assert response.status_code == 200
    assert set(response.json()["accepted"]) == {batch["events"][0]["event_id"]}


def test_ingest_rate_limited_returns_429_with_retry_after(monkeypatch, make_client, db_session):
    # Enroll before tightening the limit -- /v1/enroll isn't rate-limited
    # (no device is resolved yet), but keeping enrollment on default settings
    # avoids conflating it with the ingest-specific limit under test.
    setup_client = make_client()
    device_id, token = _enroll(setup_client, db_session)

    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECS", "60")
    monkeypatch.setenv("RATE_LIMIT_MAX_REQUESTS", "1")
    limited_client = make_client()

    first = limited_client.post(
        "/v1/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json=_batch(device_id, "batch-1", n_events=1),
    )
    assert first.status_code == 200

    second = limited_client.post(
        "/v1/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json=_batch(device_id, "batch-2", n_events=1),
    )
    assert second.status_code == 429
    assert "retry_after" in second.json()


def test_ingest_oversized_body_returns_413(monkeypatch, make_client, db_session):
    # Enroll before shrinking the limit -- the enroll payload itself would
    # otherwise also get rejected by the tightened size cap.
    setup_client = make_client()
    device_id, token = _enroll(setup_client, db_session)

    monkeypatch.setenv("MAX_REQUEST_BYTES", "10")
    small_limit_client = make_client()

    response = small_limit_client.post(
        "/v1/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json=_batch(device_id, "batch-1", n_events=1),
    )
    assert response.status_code == 413
