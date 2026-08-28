"""FastAPI app factory: wires middleware + routes.

`uvicorn server.main:app` (see Dockerfile) is the production entrypoint.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from sqlalchemy import select

from server.config import get_settings
from server.db import Base, engine, session_scope
from server.goals import generate_distraction_reminder_for_device
from server.middleware import GzipAndSizeLimitMiddleware
from server.models import Device
from server.routes import enroll, goals, ingest, messages
from server.wellbeing import generate_for_device

logger = logging.getLogger(__name__)


def run_wellbeing_tick() -> None:
    """One pass over all enrolled devices, generating a new wellbeing message
    for any with fresh activity since their last one. Runs on the background
    scheduler started in `lifespan` -- a slow/unreachable LLM or a bad device
    must not take down the tick for the rest, hence the per-device try/except.
    """
    settings = get_settings()
    with session_scope() as session:
        devices = session.execute(select(Device)).scalars().all()
        for device in devices:
            try:
                generate_for_device(
                    session,
                    device,
                    settings.ollama_url,
                    settings.wellbeing_model,
                    settings.wellbeing_break_threshold_secs,
                )
            except Exception:
                logger.exception("Wellbeing tick failed for device %s", device.device_id)


def run_distraction_tick() -> None:
    """One pass over all enrolled devices, generating a new distraction
    reminder for any currently on a keyword-matching site/app for long
    enough -- independent of whether the device's employee has a goal set
    (a goal only enriches the message, see server/goals.py). Same
    per-device failure isolation as run_wellbeing_tick.
    """
    settings = get_settings()
    with session_scope() as session:
        devices = session.execute(select(Device)).scalars().all()
        for device in devices:
            try:
                generate_distraction_reminder_for_device(
                    session,
                    device,
                    settings.ollama_url,
                    settings.wellbeing_model,
                    settings.distraction_keywords,
                    settings.distraction_threshold_secs,
                )
            except Exception:
                logger.exception("Distraction tick failed for device %s", device.device_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    scheduler = None
    if settings.wellbeing_enabled or settings.distraction_enabled:
        scheduler = BackgroundScheduler()
        if settings.wellbeing_enabled:
            scheduler.add_job(run_wellbeing_tick, "interval", seconds=settings.wellbeing_interval_secs)
            logger.info(
                "Wellbeing scheduler started (every %ds, model=%s)",
                settings.wellbeing_interval_secs,
                settings.wellbeing_model,
            )
        if settings.distraction_enabled:
            scheduler.add_job(run_distraction_tick, "interval", seconds=settings.distraction_check_interval_secs)
            logger.info(
                "Distraction scheduler started (every %ds, threshold=%ds)",
                settings.distraction_check_interval_secs,
                settings.distraction_threshold_secs,
            )
        scheduler.start()
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="health-agent ingest server", lifespan=lifespan)

    if engine.dialect.name == "sqlite":
        # Local dev/test convenience only -- the Postgres production schema is
        # managed exclusively via Alembic migrations (server/alembic/).
        Base.metadata.create_all(bind=engine)

    app.add_middleware(GzipAndSizeLimitMiddleware, max_body_bytes=settings.max_request_bytes)

    app.include_router(ingest.router)
    app.include_router(enroll.router)
    app.include_router(messages.router)
    app.include_router(goals.router)

    return app


app = create_app()


if __name__ == "__main__":
    # `python -m server.main` (or `python server/main.py`) defaults to 8001 --
    # matches every device's configured server_url without needing --port on
    # the command line. `uvicorn server.main:app --reload` still works too,
    # but that invocation goes through uvicorn's own CLI defaults (port 8000)
    # since uvicorn never imports/executes this __main__ block.
    import uvicorn

    uvicorn.run("server.main:app", host="0.0.0.0", port=8001, reload=True)
