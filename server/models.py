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


class Message(Base):
    """LLM-generated message for a device, queued for delivery.

    `created_at` also doubles as the high-water mark for how far back the next
    generation tick needs to summarize (see server/wellbeing.py, server/goals.py)
    -- a device's most recent Message row of a given `kind` is "last time we
    told them something about this specific concern."

    `kind` ("break" | "distraction") keeps the two generators' dedup checks
    independent -- a break reminder must not suppress a distraction reminder
    or vice versa, since they track unrelated streaks.
    """

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_device_id_created_at", "device_id", "created_at"),)

    message_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id: Mapped[str] = mapped_column(String, ForeignKey("devices.device_id"), nullable=False)
    text: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, default="break", server_default="break")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    delivered_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class Goal(Base):
    """An employee-stated goal/deadline, submitted via the GET/POST /goal form.

    Deliberately no "completed" flag or edit flow for now (MVP scope) --
    "current goal" for an employee is just their latest row with
    `deadline_at` still in the future (see server/goals.py's current_goal()).
    """

    __tablename__ = "goals"
    __table_args__ = (Index("ix_goals_employee_id_created_at", "employee_id", "created_at"),)

    goal_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    employee_id: Mapped[str] = mapped_column(String, ForeignKey("employees.employee_id"), nullable=False)
    text: Mapped[str] = mapped_column(String, nullable=False)
    deadline_at: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
