import json

import pytest
from keyring.errors import KeyringError

import agent.reports as reports_module
from agent.config import Config
from agent.crypto import FieldCipher, NullCipher, get_or_create_fernet_key
from agent.reports import export_csv, export_json, generate_html, refresh_reports
from agent.secrets import SecretStore
from agent.storage import Event, Storage


class RaisingBackend:
    def get_password(self, service, key):
        raise KeyringError("no backend available")

    def set_password(self, service, key, value):
        raise KeyringError("no backend available")


@pytest.fixture(autouse=True)
def _force_fallback_secret_store(monkeypatch):
    """Keep these tests off the real OS keychain -- force the file fallback."""
    import agent.secrets as secrets_module

    monkeypatch.setattr(secrets_module.keyring, "get_password", RaisingBackend().get_password)
    monkeypatch.setattr(secrets_module.keyring, "set_password", RaisingBackend().set_password)


def _seed(data_dir):
    """Write two events the same way the real agent does: via a cipher keyed
    from data_dir's own SecretStore, so reports.py's independent key lookup
    (against the same store) can decrypt them."""
    store = SecretStore(fallback_dir=data_dir / "secrets")
    cipher = FieldCipher(get_or_create_fernet_key(store))
    storage = Storage(data_dir / "events.db", cipher=cipher)
    storage.append(
        Event(
            collector="input_watcher",
            ts=1000.0,
            duration=30.0,
            data={"active_secs": 20, "keypress_count": 5, "click_count": 2, "scroll_count": 1, "mouse_dist_px": 10.0},
        )
    )
    storage.append(
        Event(collector="window_watcher", ts=1030.0, duration=5.0, data={"app": "Code", "title": "main.py"})
    )
    storage.close()


def test_generate_html_embeds_decrypted_events(tmp_path):
    _seed(tmp_path)
    out = tmp_path / "telemetry.html"

    count = generate_html(tmp_path, out)

    assert count == 2
    html = out.read_text(encoding="utf-8")
    assert '"keypress_count": 5' in html
    assert "Code" in html


def test_export_json_writes_full_decrypted_history(tmp_path):
    _seed(tmp_path)
    out = tmp_path / "events_export.json"

    count = export_json(tmp_path, out)

    assert count == 2
    events = json.loads(out.read_text(encoding="utf-8"))
    assert events[0]["collector"] == "input_watcher"
    assert events[0]["data"]["keypress_count"] == 5
    assert events[1]["data"]["app"] == "Code"
    assert events[1]["uploaded"] is False


def test_refresh_reports_writes_both_files(tmp_path):
    _seed(tmp_path)
    html_out = tmp_path / "telemetry.html"
    json_out = tmp_path / "events_export.json"

    refresh_reports(tmp_path, html_out, json_out)

    assert html_out.exists()
    assert json_out.exists()


def test_generate_html_and_export_json_work_with_encrypt_at_rest_disabled(tmp_path):
    """Regression test: rows written with NullCipher (encrypt_at_rest=false) must not
    make the reports job crash by assuming they're Fernet-encrypted."""
    config = Config.default()
    config.privacy.encrypt_at_rest = False

    storage = Storage(tmp_path / "events.db", cipher=NullCipher())
    storage.append(
        Event(
            collector="input_watcher",
            ts=1000.0,
            duration=30.0,
            data={"active_secs": 20, "keypress_count": 5, "click_count": 2, "scroll_count": 1, "mouse_dist_px": 10.0},
        )
    )
    storage.close()

    html_out = tmp_path / "telemetry.html"
    json_out = tmp_path / "events_export.json"

    assert generate_html(tmp_path, html_out, config) == 1
    assert export_json(tmp_path, json_out, config) == 1
    events = json.loads(json_out.read_text(encoding="utf-8"))
    assert events[0]["data"]["keypress_count"] == 5


def test_export_json_since_until_bound_results(tmp_path):
    _seed(tmp_path)  # events at ts=1000.0 (input_watcher) and ts=1030.0 (window_watcher)
    out = tmp_path / "events_export.json"

    count = export_json(tmp_path, out, since=1020.0)
    assert count == 1
    events = json.loads(out.read_text(encoding="utf-8"))
    assert events[0]["collector"] == "window_watcher"

    count = export_json(tmp_path, out, until=1010.0)
    assert count == 1
    events = json.loads(out.read_text(encoding="utf-8"))
    assert events[0]["collector"] == "input_watcher"


def test_export_csv_writes_decrypted_history(tmp_path):
    _seed(tmp_path)
    out = tmp_path / "events.csv"

    count = export_csv(tmp_path, out)

    assert count == 2
    text = out.read_text(encoding="utf-8")
    assert "keypress_count=5" in text
    assert "app=Code" in text


def test_refresh_reports_bounds_to_window_days(tmp_path, monkeypatch):
    """The recurring job path must only show the last window_days -- old rows outside
    that window are excluded, unlike a direct/CLI call to export_json/generate_html."""
    store = SecretStore(fallback_dir=tmp_path / "secrets")
    cipher = FieldCipher(get_or_create_fernet_key(store))
    storage = Storage(tmp_path / "events.db", cipher=cipher)
    storage.append(Event(collector="afk", ts=1000.0, duration=1.0, data={"state": "active"}))
    storage.append(Event(collector="afk", ts=699000.0, duration=1.0, data={"state": "idle"}))
    storage.close()

    monkeypatch.setattr(reports_module.time, "time", lambda: 700000.0)

    config = Config.default()
    config.reports.window_days = 7  # since = 700000 - 7*86400 = 95200 -> excludes ts=1000

    json_out = tmp_path / "events_export.json"
    refresh_reports(tmp_path, tmp_path / "telemetry.html", json_out, config)

    events = json.loads(json_out.read_text(encoding="utf-8"))
    assert len(events) == 1
    assert events[0]["data"]["state"] == "idle"


def test_regenerating_after_more_events_grows_the_report(tmp_path):
    _seed(tmp_path)
    out = tmp_path / "events_export.json"
    export_json(tmp_path, out)

    store = SecretStore(fallback_dir=tmp_path / "secrets")
    cipher = FieldCipher(get_or_create_fernet_key(store))
    storage = Storage(tmp_path / "events.db", cipher=cipher)
    storage.append(Event(collector="afk", ts=1100.0, duration=10.0, data={"state": "idle"}))
    storage.close()

    count = export_json(tmp_path, out)

    assert count == 3
