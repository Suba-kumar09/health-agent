import httpx
import pytest

from agent.sync.enroll import EnrollmentError, enroll


def test_enroll_success():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"device_id": "dev-123", "device_token": "tok-abc"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    resp = enroll(client, "https://ingest.test", "one-time-code", "my-laptop", "Windows", "11")

    assert resp.device_id == "dev-123"
    assert resp.device_token == "tok-abc"


def test_enroll_failure_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="invalid code")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(EnrollmentError):
        enroll(client, "https://ingest.test", "bad-code", "my-laptop", "Windows", "11")
