from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet


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
