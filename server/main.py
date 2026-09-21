"""FastAPI app factory: wires middleware + routes.

`uvicorn server.main:app` (see Dockerfile) is the production entrypoint.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent.single_instance import ORCHESTRATOR_LOCK_PORT, InstanceLock, port_is_free
from server.config import get_settings
from server.db import Base, engine
from server.middleware import GzipAndSizeLimitMiddleware
from server.orchestrator import run_orchestrator_tick
from server.routes import dashboard, enroll, goals, ingest, messages

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    scheduler = None
    orchestrator_lock = InstanceLock(ORCHESTRATOR_LOCK_PORT)
    wants_orchestrator = settings.wellbeing_enabled or settings.distraction_enabled or settings.productivity_enabled
    if wants_orchestrator and not orchestrator_lock.acquire():
        # A second server process running the orchestrator makes every device
        # get duplicate messages (both pass the dedup check before either
        # commits). Only one process per machine may run it.
        logger.warning("Another server already runs the orchestrator -- not starting a second scheduler here")
        wants_orchestrator = False
    if wants_orchestrator:
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            run_orchestrator_tick,
            "interval",
            seconds=settings.orchestrator_interval_secs,
            max_instances=1,  # a slow LLM call must never overlap the next tick
            coalesce=True,
        )
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
    orchestrator_lock.release()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="health-agent ingest server", lifespan=lifespan)

    if engine.dialect.name == "sqlite":
        # Local dev/test convenience only -- the Postgres production schema is
        # managed exclusively via Alembic migrations (server/alembic/).
        Base.metadata.create_all(bind=engine)

    app.add_middleware(GzipAndSizeLimitMiddleware, max_body_bytes=settings.max_request_bytes)
    # dashboard/ is a separate origin (Vite dev server) with no auth/session
    # system to piggyback on (see server/routes/dashboard.py) -- GET-only,
    # read-only endpoints, so a permissive dev CORS policy doesn't expose any
    # mutation. Tighten this before any real deployment.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.dashboard_origins,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    app.include_router(ingest.router)
    app.include_router(enroll.router)
    app.include_router(messages.router)
    app.include_router(goals.router)
    app.include_router(dashboard.router)

    return app


app = create_app()


if __name__ == "__main__":
    # `python -m server.main` (or `python server/main.py`) defaults to 8001 --
    # matches every device's configured server_url without needing --port on
    # the command line. `uvicorn server.main:app --reload` still works too,
    # but that invocation goes through uvicorn's own CLI defaults (port 8000)
    # since uvicorn never imports/executes this __main__ block.
    import sys

    import uvicorn

    # uvicorn's own bind uses SO_REUSEADDR, which on Windows lets a second
    # server silently share :8001 with the first -- two servers, two
    # orchestrators, duplicate messages. Refuse to start instead.
    if not port_is_free(8001):
        print("Port 8001 is already in use -- a server is probably already running. Not starting a second one.")
        sys.exit(1)

    uvicorn.run("server.main:app", host="0.0.0.0", port=8001, reload=True)
