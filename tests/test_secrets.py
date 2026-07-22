from keyring.errors import KeyringError

from agent.secrets import SecretStore


class RaisingBackend:
    def get_password(self, service, key):
        raise KeyringError("no backend available")

    def set_password(self, service, key, value):
        raise KeyringError("no backend available")


def test_falls_back_to_file_when_keyring_unavailable(tmp_path, monkeypatch):
    import agent.secrets as secrets_module

    monkeypatch.setattr(secrets_module.keyring, "get_password", RaisingBackend().get_password)
    monkeypatch.setattr(secrets_module.keyring, "set_password", RaisingBackend().set_password)

    store = SecretStore(fallback_dir=tmp_path)
    store.set("device_token", "abc123")

    assert store.get("device_token") == "abc123"
    fallback_file = tmp_path / "device_token.secret"
    assert fallback_file.exists()


def test_fallback_file_round_trip(tmp_path, monkeypatch):
    import agent.secrets as secrets_module

    monkeypatch.setattr(secrets_module.keyring, "get_password", RaisingBackend().get_password)
    monkeypatch.setattr(secrets_module.keyring, "set_password", RaisingBackend().set_password)

    store = SecretStore(fallback_dir=tmp_path)
    assert store.get("missing_key") is None

    store.set("fernet_key", "supersecretkey")
    assert store.get("fernet_key") == "supersecretkey"
