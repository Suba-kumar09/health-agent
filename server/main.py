"""FastAPI app factory: wires middleware + routes.

`uvicorn server.main:app` (see Dockerfile) is the production entrypoint.
"""
from __future__ import annotations

from fastapi import FastAPI

from server.config import get_settings
from server.db import Base, engine
from server.middleware import GzipAndSizeLimitMiddleware
from server.routes import enroll, ingest


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="health-agent ingest server")

    if engine.dialect.name == "sqlite":
        # Local dev/test convenience only -- the Postgres production schema is
        # managed exclusively via Alembic migrations (server/alembic/).
        Base.metadata.create_all(bind=engine)

    app.add_middleware(GzipAndSizeLimitMiddleware, max_body_bytes=settings.max_request_bytes)

    app.include_router(ingest.router)
    app.include_router(enroll.router)

    return app


app = create_app()
