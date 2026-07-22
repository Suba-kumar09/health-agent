from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

BASIC_CONSENT_TEXT = """
This agent monitors keyboard/mouse activity, the foreground app/window, and
(with a companion browser extension) the active browser tab, to infer
wellbeing signals such as typing intensity, break patterns, and screen time.

By default it only records COUNTS (keypresses, clicks, scrolls, active
seconds) -- never which keys were pressed or any typed content.

Continue? [y/N]: """

DETAILED_CONSENT_TEXT = """
You are enabling DETAILED capture mode. In addition to the counts above,
this will record individual key CODES (not reconstructed text, but still a
more sensitive log of keyboard activity) for every keystroke.

This requires a separate, explicit acknowledgement from basic monitoring.
Every session where detailed mode is active is written to a local audit log.

Enable detailed capture mode? [y/N]: """


class ConsentManager:
    """Tracks first-run consent state and the detailed-mode audit trail.

    Basic monitoring consent and detailed-mode consent are recorded
    separately -- accepting the former never implicitly grants the latter.
    """

    def __init__(self, data_dir: str | Path, now_fn: Callable[[], float] = time.time) -> None:
        self.marker_path = Path(data_dir) / "consent.json"
        self.audit_log_path = Path(data_dir) / "detailed_mode_audit.log"
        self.now_fn = now_fn

    def _load(self) -> dict:
        if self.marker_path.exists():
            return json.loads(self.marker_path.read_text(encoding="utf-8"))
        return {}

    def _save(self, data: dict) -> None:
        self.marker_path.parent.mkdir(parents=True, exist_ok=True)
        self.marker_path.write_text(json.dumps(data), encoding="utf-8")

    def has_basic_consent(self) -> bool:
        return "basic_consented_at" in self._load()

    def has_detailed_consent(self) -> bool:
        return "detailed_consented_at" in self._load()

    def record_basic_consent(self) -> None:
        data = self._load()
        data["basic_consented_at"] = self.now_fn()
        self._save(data)

    def record_detailed_consent(self) -> None:
        data = self._load()
        data["detailed_consented_at"] = self.now_fn()
        self._save(data)

    def log_detailed_mode_audit(self) -> None:
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.audit_log_path, "a", encoding="utf-8") as f:
            f.write(f"{self.now_fn()} detailed_mode_active\n")


def resolve_capture_mode(requested_mode: str, consent: ConsentManager) -> str:
    """Downgrade detailed->aggregate if detailed-mode consent isn't on record."""
    if requested_mode == "detailed" and not consent.has_detailed_consent():
        return "aggregate"
    return requested_mode


def ensure_first_run_consent(consent: ConsentManager, prompt_fn: Callable[[str], str]) -> bool:
    """Returns True once basic monitoring consent is in place (existing or new)."""
    if consent.has_basic_consent():
        return True
    answer = prompt_fn(BASIC_CONSENT_TEXT)
    if answer.strip().lower() in ("y", "yes"):
        consent.record_basic_consent()
        return True
    return False


def run_detailed_consent_flow(consent: ConsentManager, prompt_fn: Callable[[str], str]) -> bool:
    """Explicit, separate opt-in flow for detailed capture mode."""
    answer = prompt_fn(DETAILED_CONSENT_TEXT)
    if answer.strip().lower() in ("y", "yes"):
        consent.record_detailed_consent()
        return True
    return False
