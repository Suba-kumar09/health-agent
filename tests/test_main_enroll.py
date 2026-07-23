import httpx
from keyring.errors import KeyringError

from agent.main import maybe_enroll
from agent.secrets import SecretStore


class RaisingBackend:
    def get_password(self, service, key):
        raise KeyringError("no backend available")

    def set_password(self, service, key, value):
        raise KeyringError("no backend available")


def _isolated_store(tmp_path, monkeypatch):
    import agent.secrets as secrets_module

    monkeypatch.setattr(secrets_module.keyring, "get_password", RaisingBackend().get_password)
    monkeypatch.setattr(secrets_module.keyring, "set_password", RaisingBackend().set_password)
    return SecretStore(fallback_dir=tmp_path)


def test_maybe_enroll_skips_when_already_enrolled(tmp_path, monkeypatch):
    store = _isolated_store(tmp_path, monkeypatch)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))

    device_id, device_token = maybe_enroll(
        secret_store=store,
        http_client=client,
        server_url="https://ingest.test",
        enrollment_code="unused-code",
        device_name="my-laptop",
        os_name="Windows",
        os_version="11",
        device_id="existing-device",
        device_token="already-a-real-token",
    )

    assert (device_id, device_token) == ("existing-device", "already-a-real-token")


def test_maybe_enroll_skips_when_no_code_provided(tmp_path, monkeypatch):
    store = _isolated_store(tmp_path, monkeypatch)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))

    device_id, device_token = maybe_enroll(
        secret_store=store,
        http_client=client,
        server_url="https://ingest.test",
        enrollment_code=None,
        device_name="my-laptop",
        os_name="Windows",
        os_version="11",
        device_id="local-device",
        device_token="unenrolled",
    )

    assert (device_id, device_token) == ("local-device", "unenrolled")


def test_maybe_enroll_success_updates_ids_and_persists_token(tmp_path, monkeypatch):
    store = _isolated_store(tmp_path, monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"device_id": "server-issued-id", "device_token": "real-token"})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    device_id, device_token = maybe_enroll(
        secret_store=store,
        http_client=client,
        server_url="https://ingest.test",
        enrollment_code="one-time-code",
        device_name="my-laptop",
        os_name="Windows",
        os_version="11",
        device_id="local-device",
        device_token="unenrolled",
    )

    assert device_id == "server-issued-id"
    assert device_token == "real-token"
    assert store.get("device_token") == "real-token"


def test_maybe_enroll_failure_keeps_unenrolled(tmp_path, monkeypatch):
    store = _isolated_store(tmp_path, monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="invalid code")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    device_id, device_token = maybe_enroll(
        secret_store=store,
        http_client=client,
        server_url="https://ingest.test",
        enrollment_code="bad-code",
        device_name="my-laptop",
        os_name="Windows",
        os_version="11",
        device_id="local-device",
        device_token="unenrolled",
    )

    assert (device_id, device_token) == ("local-device", "unenrolled")
    assert store.get("device_token") is None
