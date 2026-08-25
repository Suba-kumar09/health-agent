"""Env-driven settings for the ingest server.

Everything here is read from the environment so the same image/codebase runs
locally (docker-compose), in CI (SQLite, no external DB needed), and on the
managed-Postgres deployment target -- only DATABASE_URL changes.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    return value.strip().lower() in ("1", "true", "yes") if value else default


@dataclass(frozen=True)
class Settings:
    database_url: str
    max_request_bytes: int
    rate_limit_window_secs: int
    rate_limit_max_requests: int
    enrollment_code_ttl_hours: int
    wellbeing_enabled: bool
    ollama_url: str
    wellbeing_model: str
    wellbeing_interval_secs: int
    wellbeing_break_threshold_secs: int


def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("DATABASE_URL", "sqlite:///./server_dev.db"),
        max_request_bytes=_int_env("MAX_REQUEST_BYTES", 2 * 1024 * 1024),
        rate_limit_window_secs=_int_env("RATE_LIMIT_WINDOW_SECS", 60),
        rate_limit_max_requests=_int_env("RATE_LIMIT_MAX_REQUESTS", 30),
        enrollment_code_ttl_hours=_int_env("ENROLLMENT_CODE_TTL_HOURS", 36),
        wellbeing_enabled=_bool_env("WELLBEING_ENABLED", True),
        ollama_url=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"),
        wellbeing_model=os.environ.get("WELLBEING_MODEL", "qwen2.5:3b"),
        wellbeing_interval_secs=_int_env("WELLBEING_INTERVAL_SECS", 300),
        wellbeing_break_threshold_secs=_int_env("WELLBEING_BREAK_THRESHOLD_SECS", 1800),
    )
