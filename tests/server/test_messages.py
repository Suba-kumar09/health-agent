from __future__ import annotations

import uuid

from server.auth import mint_enrollment_code
from server.models import Employee, Message


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


def test_pending_messages_requires_auth(client):
    response = client.get("/v1/messages/pending")
    assert response.status_code == 401


def test_pending_messages_rejects_bad_token(client):
    response = client.get("/v1/messages/pending", headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401


def test_pending_messages_empty_when_none_queued(client, db_session):
    _device_id, token = _enroll(client, db_session)

    response = client.get("/v1/messages/pending", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {"messages": []}


def test_pending_messages_are_not_marked_delivered_until_acked(client, db_session):
    device_id, token = _enroll(client, db_session)
    message = Message(message_id=str(uuid.uuid4()), device_id=device_id, text="take a break!", created_at=1000.0)
    db_session.add(message)
    db_session.commit()
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get("/v1/messages/pending", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert len(body["messages"]) == 1
    assert body["messages"][0]["text"] == "take a break!"

    # Fetching must NOT consume it: if the popup fails the agent never acks,
    # and the message has to come back on the next poll.
    db_session.refresh(message)
    assert message.delivered_at is None
    assert len(client.get("/v1/messages/pending", headers=headers).json()["messages"]) == 1

    ack = client.post("/v1/messages/ack", headers=headers, json={"message_ids": [message.message_id]})
    assert ack.status_code == 200
    assert ack.json() == {"acknowledged": 1}
    db_session.refresh(message)
    assert message.delivered_at is not None
    assert client.get("/v1/messages/pending", headers=headers).json() == {"messages": []}


def test_ack_requires_auth(client):
    assert client.post("/v1/messages/ack", json={"message_ids": ["x"]}).status_code == 401


def test_ack_is_idempotent_and_ignores_unknown_ids(client, db_session):
    device_id, token = _enroll(client, db_session)
    message = Message(message_id=str(uuid.uuid4()), device_id=device_id, text="hi", created_at=1000.0)
    db_session.add(message)
    db_session.commit()
    headers = {"Authorization": f"Bearer {token}"}
    body = {"message_ids": [message.message_id, "does-not-exist"]}

    assert client.post("/v1/messages/ack", headers=headers, json=body).json() == {"acknowledged": 1}
    assert client.post("/v1/messages/ack", headers=headers, json=body).json() == {"acknowledged": 0}
    assert client.post("/v1/messages/ack", headers=headers, json={"message_ids": []}).json() == {"acknowledged": 0}


def test_ack_cannot_acknowledge_another_devices_message(client, db_session):
    device_a, _token_a = _enroll(client, db_session)
    db_session.add(Employee(name="Other", system_name="other-laptop"))
    db_session.commit()
    code_b = mint_enrollment_code(db_session, ttl_hours=24)
    db_session.commit()
    token_b = client.post(
        "/v1/enroll",
        json={"enrollment_code": code_b.code, "device_name": "other-laptop", "os": "Windows", "os_version": "11"},
    ).json()["device_token"]
    message = Message(message_id=str(uuid.uuid4()), device_id=device_a, text="for A", created_at=1000.0)
    db_session.add(message)
    db_session.commit()

    response = client.post(
        "/v1/messages/ack", headers={"Authorization": f"Bearer {token_b}"}, json={"message_ids": [message.message_id]}
    )

    assert response.json() == {"acknowledged": 0}
    db_session.refresh(message)
    assert message.delivered_at is None


def test_pending_messages_scoped_to_own_device(client, db_session):
    device_a, token_a = _enroll(client, db_session)
    db_session.add(Employee(name="Other", system_name="other-laptop"))
    db_session.commit()
    code_b = mint_enrollment_code(db_session, ttl_hours=24)
    db_session.commit()
    response = client.post(
        "/v1/enroll",
        json={"enrollment_code": code_b.code, "device_name": "other-laptop", "os": "Windows", "os_version": "11"},
    )
    token_b = response.json()["device_token"]

    db_session.add(
        Message(message_id=str(uuid.uuid4()), device_id=device_a, text="for device A only", created_at=1000.0)
    )
    db_session.commit()

    response = client.get("/v1/messages/pending", headers={"Authorization": f"Bearer {token_b}"})
    assert response.json() == {"messages": []}
