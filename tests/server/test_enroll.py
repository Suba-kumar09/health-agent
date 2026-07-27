from __future__ import annotations

from server.auth import mint_enrollment_code


def _enroll_payload(code: str) -> dict:
    return {
        "enrollment_code": code,
        "device_name": "test-laptop",
        "os": "Windows",
        "os_version": "11",
    }


def test_enroll_success(client, db_session):
    code = mint_enrollment_code(db_session, ttl_hours=24)
    db_session.commit()

    response = client.post("/v1/enroll", json=_enroll_payload(code.code))

    assert response.status_code == 200
    body = response.json()
    assert body["device_id"]
    assert body["device_token"]


def test_enroll_token_works_for_ingest(client, db_session):
    code = mint_enrollment_code(db_session, ttl_hours=24)
    db_session.commit()

    enroll_response = client.post("/v1/enroll", json=_enroll_payload(code.code))
    device_id = enroll_response.json()["device_id"]
    token = enroll_response.json()["device_token"]

    ingest_response = client.post(
        "/v1/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "device_id": device_id,
            "agent_version": "0.1.0",
            "os": "Windows",
            "os_version": "11",
            "batch_id": "batch-1",
            "sent_at": 1732000000.0,
            "events": [],
        },
    )
    assert ingest_response.status_code == 200


def test_enroll_unknown_code_rejected(client):
    response = client.post("/v1/enroll", json=_enroll_payload("does-not-exist"))
    assert response.status_code == 403


def test_enroll_code_is_single_use(client, db_session):
    code = mint_enrollment_code(db_session, ttl_hours=24)
    db_session.commit()

    first = client.post("/v1/enroll", json=_enroll_payload(code.code))
    assert first.status_code == 200

    second = client.post("/v1/enroll", json=_enroll_payload(code.code))
    assert second.status_code == 403


def test_enroll_expired_code_rejected(client, db_session):
    code = mint_enrollment_code(db_session, ttl_hours=-1)
    db_session.commit()

    response = client.post("/v1/enroll", json=_enroll_payload(code.code))
    assert response.status_code == 403
