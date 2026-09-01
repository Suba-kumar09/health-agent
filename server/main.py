"""FastAPI app factory: wires middleware + routes.

`uvicorn server.main:app` (see Dockerfile) is the production entrypoint.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI

from server.config import get_settings
from server.db import Base, engine
from server.middleware import GzipAndSizeLimitMiddleware
from server.orchestrator import run_orchestrator_tick
from server.routes import enroll, goals, ingest, messages

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    scheduler = None
    if settings.wellbeing_enabled or settings.distraction_enabled or settings.productivity_enabled:
        scheduler = BackgroundScheduler()
        scheduler.add_job(run_orchestrator_tick, "interval", seconds=settings.orchestrator_interval_secs)
        logger.info(
            "Orchestrator scheduler started (every %ds; break=%s distraction=%s idle=%s, model=%s)",
            settings.orchestrator_interval_secs,
            settings.wellbeing_enabled,
            settings.distraction_enabled,
            settings.productivity_enabled,
            settings.wellbeing_model,
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
