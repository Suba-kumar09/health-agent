from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from cryptography.fernet import Fernet

from agent.secrets import SecretStore

if TYPE_CHECKING:
    from agent.config import Config


class FieldCipher:
    """Encrypts/decrypts the `data` JSON blob column only.

    Schema columns used for sync/dedup queries (event_id, ts, synced, batch_id)
    stay in plaintext; only the payload is protected.
    """

    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    @staticmethod
    def generate_key() -> bytes:
        return Fernet.generate_key()

    def encrypt_json(self, data: dict[str, Any]) -> bytes:
        raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
        return self._fernet.encrypt(raw)

    def decrypt_json(self, token: bytes) -> dict[str, Any]:
        raw = self._fernet.decrypt(token)
        return json.loads(raw.decode("utf-8"))


class NullCipher:
    """No-op cipher used when encrypt_at_rest is disabled."""

    def encrypt_json(self, data: dict[str, Any]) -> bytes:
        return json.dumps(data, separators=(",", ":")).encode("utf-8")

    def decrypt_json(self, token: bytes) -> dict[str, Any]:
        return json.loads(token.decode("utf-8"))


def get_or_create_fernet_key(secret_store: SecretStore) -> bytes:
    existing = secret_store.get("data_encryption_key")
    if existing:
        return existing.encode("ascii")
    key = FieldCipher.generate_key()
    secret_store.set("data_encryption_key", key.decode("ascii"))
    return key


def cipher_for_config(config: Config, secret_store: SecretStore) -> FieldCipher | NullCipher:
    """Picks the same cipher agent/main.py uses to write events, based on `encrypt_at_rest`.

    Reports/export code must call this instead of hardcoding FieldCipher -- rows written
    with encrypt_at_rest=False are plaintext, and decrypting them as Fernet tokens raises
    InvalidToken.
    """
    if config.privacy.encrypt_at_rest:
        return FieldCipher(get_or_create_fernet_key(secret_store))
    return NullCipher()
