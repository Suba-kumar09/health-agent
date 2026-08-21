"""SQLAlchemy ORM models.

All timestamps are Unix epoch floats (not DateTime), matching the convention
already used client-side (agent/storage.py's `ts` column, agent/sync/api.py's
`sent_at`). This also sidesteps a real cross-dialect trap: SQLAlchemy's
DateTime(timezone=True) round-trips as a naive datetime on SQLite, which would
make tz-aware comparisons (e.g. checking enrollment-code expiry) raise
TypeError there while working fine on Postgres.
"""
from __future__ import annotations

import time
import uuid

from sqlalchemy import JSON, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from server.db import Base


class Employee(Base):
    __tablename__ = "employees"

    employee_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String, nullable=False)
    system_name: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Device(Base):
    __tablename__ = "devices"

    device_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    device_token_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    device_name: Mapped[str] = mapped_column(String, nullable=False)
    os: Mapped[str] = mapped_column(String, nullable=False)
    os_version: Mapped[str] = mapped_column(String, nullable=False)
    enrolled_at: Mapped[float] = mapped_column(Float, default=time.time)
    last_seen_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    employee_id: Mapped[str | None] = mapped_column(String, ForeignKey("employees.employee_id"), nullable=True)


class EnrollmentCode(Base):
    __tablename__ = "enrollment_codes"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    issued_for: Mapped[str | None] = mapped_column(String, nullable=True)
    issued_at: Mapped[float] = mapped_column(Float, default=time.time)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)
    used_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    used_by_device_id: Mapped[str | None] = mapped_column(String, ForeignKey("devices.device_id"), nullable=True)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_device_id_ts", "device_id", "ts"),)

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    device_id: Mapped[str] = mapped_column(String, ForeignKey("devices.device_id"), nullable=False)
    collector: Mapped[str] = mapped_column(String, nullable=False)
    ts: Mapped[float] = mapped_column(Float, nullable=False)
    duration: Mapped[float] = mapped_column(Float, default=0.0)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    batch_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    received_at: Mapped[float] = mapped_column(Float, default=time.time)


class RateLimitCounter(Base):
    __tablename__ = "rate_limit_counters"

    device_id: Mapped[str] = mapped_column(String, ForeignKey("devices.device_id"), primary_key=True)
    window_start: Mapped[float] = mapped_column(Float, nullable=False)
    count_in_window: Mapped[int] = mapped_column(Integer, default=0)
