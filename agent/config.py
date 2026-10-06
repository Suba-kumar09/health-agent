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
    messages_poll_interval_secs: int = 300


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


class VoiceSection(BaseModel):
    """Buddy, the robot voice assistant (agent/voice.py, agent/robot.py). It only
    speaks reminders the server sends, so it is silent unless the server is running."""

    enabled: bool = True  # speak reminders aloud
    robot: bool = True  # show the small animated robot while speaking
    greet_on_start: bool = True  # say hello once the server first answers
    rate: int = Field(default=1, ge=-10, le=10)  # SAPI speed, -10 (slow) .. 10 (fast)
    pitch: int = Field(default=6, ge=-10, le=10)  # SAPI pitch; higher sounds more "robot"
    volume: int = Field(default=90, ge=0, le=100)
    voice_name: str = ""  # part of an installed Windows voice name, e.g. "Zira"; "" = default


class Config(BaseModel):
    agent: AgentSection = Field(default_factory=AgentSection)
    sync: SyncSection = Field(default_factory=SyncSection)
    retention: RetentionSection = Field(default_factory=RetentionSection)
    collectors: CollectorsSection = Field(default_factory=CollectorsSection)
    privacy: PrivacySection = Field(default_factory=PrivacySection)
    voice: VoiceSection = Field(default_factory=VoiceSection)

    @classmethod
    def load(cls, path: str | Path) -> Config:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return cls.model_validate(data)

    @classmethod
    def default(cls) -> Config:
        return cls()
