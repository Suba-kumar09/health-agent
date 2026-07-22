from __future__ import annotations

from pathlib import Path
from typing import Literal

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

from pydantic import BaseModel, Field


class AgentSection(BaseModel):
    device_id: str = ""
    server_url: str = "https://ingest.example.com"
    sync_interval_secs: int = 5400
    capture_mode: Literal["aggregate", "detailed"] = "aggregate"
    bucket_seconds: int = 30
    browser_bridge_port: int = 0


class SyncSection(BaseModel):
    max_batches_per_tick: int = 5
    batch_max_events: int = 500
    batch_max_bytes: int = 1_048_576
    gzip: bool = True
    backoff_initial_secs: int = 5
    backoff_max_secs: int = 900


class RetentionSection(BaseModel):
    mode: Literal["delete_after_sync", "keep_days"] = "delete_after_sync"
    grace_secs: int = 3600
    keep_days: int = 30


class CollectorsSection(BaseModel):
    input_watcher: bool = True
    window_watcher: bool = True
    afk: bool = True
    browser_bridge: bool = True


class PrivacySection(BaseModel):
    encrypt_at_rest: bool = True
    afk_threshold_secs: int = 120


class Config(BaseModel):
    agent: AgentSection = Field(default_factory=AgentSection)
    sync: SyncSection = Field(default_factory=SyncSection)
    retention: RetentionSection = Field(default_factory=RetentionSection)
    collectors: CollectorsSection = Field(default_factory=CollectorsSection)
    privacy: PrivacySection = Field(default_factory=PrivacySection)

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return cls.model_validate(data)

    @classmethod
    def default(cls) -> "Config":
        return cls()
