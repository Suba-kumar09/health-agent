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
    distraction_enabled: bool
    distraction_check_interval_secs: int
    distraction_threshold_secs: int
    distraction_keywords: list[str]
    productivity_enabled: bool
    productivity_idle_threshold_secs: int
    orchestrator_interval_secs: int
    policy_enabled: bool
    policy_cooldown_secs: int
    policy_daily_message_limit: int
    policy_quiet_hours_start: int
    policy_quiet_hours_end: int


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
        distraction_enabled=_bool_env("DISTRACTION_ENABLED", True),
        distraction_check_interval_secs=_int_env("DISTRACTION_CHECK_INTERVAL_SECS", 60),
        distraction_threshold_secs=_int_env("DISTRACTION_THRESHOLD_SECS", 60),
        distraction_keywords=[
            k.strip().lower()
            for k in os.environ.get(
                "DISTRACTION_KEYWORDS",
                "youtube,netflix,instagram,facebook,twitter,tiktok,twitch,reddit,hotstar,prime video",
            ).split(",")
            if k.strip()
        ],
        productivity_enabled=_bool_env("PRODUCTIVITY_ENABLED", True),
        productivity_idle_threshold_secs=_int_env("PRODUCTIVITY_IDLE_THRESHOLD_SECS", 60),
        orchestrator_interval_secs=_int_env("ORCHESTRATOR_INTERVAL_SECS", 60),
        policy_enabled=_bool_env("POLICY_ENABLED", True),
        policy_cooldown_secs=_int_env("POLICY_COOLDOWN_SECS", 30),
        policy_daily_message_limit=_int_env("POLICY_DAILY_MESSAGE_LIMIT", 50),
        # Equal start/end disables the quiet-hours check entirely -- see
        # policy._in_quiet_hours. Off by default since it needs a real
        # timezone/business-hours decision, not a guessed default.
        policy_quiet_hours_start=_int_env("POLICY_QUIET_HOURS_START", 0),
        policy_quiet_hours_end=_int_env("POLICY_QUIET_HOURS_END", 0),
    )
