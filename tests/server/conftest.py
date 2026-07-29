"""Shared fixtures for the real server/main.py app, backed by a temp-file
SQLite database (not an in-memory one, since each SQLAlchemy connection would
otherwise see its own separate in-memory DB). Postgres-only behavior (the
actual production target) is exercised by the dialect-aware code paths in
server/db.py and server/ratelimit.py, but isn't itself run against a live
Postgres here -- this repo's existing CI matrix runs on windows-latest and
ubuntu-latest, and GitHub Actions service containers (the usual way to get a
throwaway Postgres in CI) are Linux-only, so SQLite is what keeps these tests
portable across both.
"""
from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix=".db")
os.close(_fd)
os.remove(_TEST_DB_PATH)
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"

from server.db import Base, SessionLocal, engine  # noqa: E402
from server.main import create_app  # noqa: E402


@pytest.fixture()
def db_session():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def make_client():
    Base.metadata.create_all(bind=engine)
    clients: list[TestClient] = []

    def _make() -> TestClient:
        app = create_app()
        test_client = TestClient(app)
        clients.append(test_client)
        return test_client

    yield _make

    for test_client in clients:
        test_client.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(make_client):
    return make_client()
