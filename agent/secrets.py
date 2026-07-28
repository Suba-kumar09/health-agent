from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

logger = logging.getLogger(__name__)

SERVICE_NAME = "health-agent"


class SecretStore:
    """Stores small secrets (device_token, data-encryption key).

    Primary backend is the OS keychain via `keyring`. On systems where no
    keychain backend is available (e.g. a headless Linux service with no
    D-Bus session/unlocked Secret Service), falls back to a 0600-permissioned
    file. There is no separate root secret to encrypt that file with in the
    fallback case (the keychain *is* normally that root secret), so the
    fallback's protection is the OS file permission only -- weaker than the
    keychain. The fallback is logged loudly so this is never silent.
    """

    def __init__(self, fallback_dir: str | Path) -> None:
        self._fallback_dir = Path(fallback_dir)
        self._use_fallback = not self._keyring_available()

    @staticmethod
    def _keyring_available() -> bool:
        try:
            keyring.get_password(SERVICE_NAME, "__probe__")
            return True
        except KeyringError:
            return False
        except Exception:  # pragma: no cover - defensive, backend-specific errors vary
            return False

    def get(self, key: str) -> str | None:
        if not self._use_fallback:
            try:
                value = keyring.get_password(SERVICE_NAME, key)
                if value is not None:
                    return value
            except KeyringError:
                logger.warning("Keyring unavailable, falling back to file storage for %r", key)
                self._use_fallback = True
        return self._get_fallback(key)

    def set(self, key: str, value: str) -> None:
        if not self._use_fallback:
            try:
                keyring.set_password(SERVICE_NAME, key, value)
                return
            except KeyringError:
                logger.warning(
                    "Keyring unavailable, falling back to 0600 file storage for %r. "
                    "This is a weaker secret-storage posture than the OS keychain.",
                    key,
                )
                self._use_fallback = True
        self._set_fallback(key, value)

    def delete(self, key: str) -> None:
        """Removes a stored secret, if present. Safe to call when nothing is stored
        under `key` -- used by unpair() to invalidate a bearer token."""
        if not self._use_fallback:
            try:
                keyring.delete_password(SERVICE_NAME, key)
                return
            except PasswordDeleteError:
                return  # nothing was stored under this key
            except KeyringError:
                logger.warning("Keyring unavailable, falling back to file storage for delete of %r", key)
                self._use_fallback = True
        self._fallback_path(key).unlink(missing_ok=True)

    def _fallback_path(self, key: str) -> Path:
        safe_key = "".join(c if c.isalnum() else "_" for c in key)
        return self._fallback_dir / f"{safe_key}.secret"

    def _get_fallback(self, key: str) -> str | None:
        path = self._fallback_path(key)
        if not path.exists():
            return None
        return path.read_bytes().decode("utf-8")

    def _set_fallback(self, key: str, value: str) -> None:
        self._fallback_dir.mkdir(parents=True, exist_ok=True)
        path = self._fallback_path(key)
        path.write_bytes(value.encode("utf-8"))
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass  # best-effort on platforms without POSIX perms (e.g. Windows)
