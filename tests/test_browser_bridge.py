import httpx
import pytest
from keyring.errors import KeyringError

import agent.secrets as secrets_module
from agent.collectors.browser_bridge import BrowserBridgeCollector
from agent.secrets import SecretStore

EXT_ORIGIN = "chrome-extension://abcdefghijklmnop"


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    # Force the file-fallback path -- tests must never touch the real OS
    # keychain (it's shared, global, per-user state, not test-isolated).
    def raise_keyring_error(*args, **kwargs):
        raise KeyringError("keyring disabled for tests")

    monkeypatch.setattr(secrets_module.keyring, "get_password", raise_keyring_error)
    monkeypatch.setattr(secrets_module.keyring, "set_password", raise_keyring_error)

    secret_store = SecretStore(fallback_dir=tmp_path / "secrets")
    events = []
    clock = {"t": 1000.0}
    b = BrowserBridgeCollector(
        secret_store=secret_store,
        on_tab_event=lambda e: events.append(e),
        port=0,
        now_fn=lambda: clock["t"],
    )
    b.start()
    b.events = events
    b.clock = clock
    yield b
    b.stop()


def base_url(bridge) -> str:
    return f"http://127.0.0.1:{bridge.port}"


def test_pairing_with_correct_code_issues_token(bridge):
    code = bridge.issue_pairing_code()

    resp = httpx.post(f"{base_url(bridge)}/pair", json={"code": code}, headers={"Origin": EXT_ORIGIN})

    assert resp.status_code == 200
    token = resp.json()["token"]
    assert bridge.paired_token == token


def test_pairing_with_wrong_code_rejected(bridge):
    bridge.issue_pairing_code()

    resp = httpx.post(f"{base_url(bridge)}/pair", json={"code": "000000"}, headers={"Origin": EXT_ORIGIN})

    assert resp.status_code == 401
    assert bridge.paired_token is None


def test_pairing_code_is_single_use(bridge):
    code = bridge.issue_pairing_code()
    httpx.post(f"{base_url(bridge)}/pair", json={"code": code}, headers={"Origin": EXT_ORIGIN})

    resp = httpx.post(f"{base_url(bridge)}/pair", json={"code": code}, headers={"Origin": EXT_ORIGIN})

    assert resp.status_code == 401


def test_pairing_code_expires(bridge):
    code = bridge.issue_pairing_code()
    bridge.clock["t"] += 301  # past PAIRING_CODE_TTL_SECS

    resp = httpx.post(f"{base_url(bridge)}/pair", json={"code": code}, headers={"Origin": EXT_ORIGIN})

    assert resp.status_code == 401


def test_pairing_rejected_from_non_extension_origin(bridge):
    code = bridge.issue_pairing_code()

    resp = httpx.post(f"{base_url(bridge)}/pair", json={"code": code}, headers={"Origin": "https://evil.example"})

    assert resp.status_code == 403
    assert bridge.paired_token is None


def test_tab_event_requires_valid_token(bridge):
    resp = httpx.post(
        f"{base_url(bridge)}/tab-event",
        json={"url": "https://example.com", "title": "Example", "ts": 1.0},
        headers={"Origin": EXT_ORIGIN, "Authorization": "Bearer wrong-token"},
    )

    assert resp.status_code == 401
    assert bridge.events == []


def test_tab_event_with_valid_token_dispatches_to_callback(bridge):
    code = bridge.issue_pairing_code()
    pair_resp = httpx.post(f"{base_url(bridge)}/pair", json={"code": code}, headers={"Origin": EXT_ORIGIN})
    token = pair_resp.json()["token"]

    resp = httpx.post(
        f"{base_url(bridge)}/tab-event",
        json={"url": "https://example.com", "title": "Example", "ts": 1.0},
        headers={"Origin": EXT_ORIGIN, "Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    assert bridge.events == [{"url": "https://example.com", "title": "Example", "ts": 1.0}]


def test_tab_event_rejected_from_non_extension_origin_even_with_valid_token(bridge):
    code = bridge.issue_pairing_code()
    pair_resp = httpx.post(f"{base_url(bridge)}/pair", json={"code": code}, headers={"Origin": EXT_ORIGIN})
    token = pair_resp.json()["token"]

    resp = httpx.post(
        f"{base_url(bridge)}/tab-event",
        json={"url": "https://example.com"},
        headers={"Origin": "https://evil.example", "Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 403
    assert bridge.events == []
