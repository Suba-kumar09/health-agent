"""SQLAlchemy engine/session setup and a dialect-portable dedup-insert helper.

Production targets Postgres; tests and local dev without Docker use SQLite
(see server/config.py's DATABASE_URL default). insert_ignore_conflict() picks
the right ON CONFLICT dialect at call time so the same route code works
against either.
"""
from __future__ import annotations

from collections.abc import Sequence
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from server.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str | None = None):
    url = database_url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, future=True, connect_args=connect_args)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def add_missing_sqlite_columns(bind, metadata) -> list[str]:
    """Local-dev convenience for SQLite only: create_all() creates missing
    *tables* but never adds new *columns* to a table that already exists, so
    an older server_dev.db crashes with "no such column" after a model gains
    a field. This adds each missing column (nullable, with its server default)
    so an existing dev database keeps working. Postgres is never touched --
    production schema changes go through Alembic. Returns what it added."""
    from sqlalchemy import inspect, text

    if bind.dialect.name != "sqlite":
        return []
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    added: list[str] = []
    with bind.begin() as conn:
        for table in metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            have = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in have:
                    continue
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column.type.compile(bind.dialect)}'
                default = column.server_default
                if default is not None and isinstance(getattr(default, "arg", None), str):
                    ddl += " DEFAULT '" + default.arg.replace("'", "''") + "'"
                conn.execute(text(ddl))
                added.append(f"{table.name}.{column.name}")
    return added


@contextmanager
def session_scope(session_factory=SessionLocal):
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session():
    """FastAPI dependency: one session per request, closed after the response.
    Commit/rollback is the route handler's responsibility, not this generator's.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def insert_ignore_conflict(
    session: Session,
    table: Any,
    rows: Sequence[dict],
    index_elements: Sequence[str],
) -> set[Any]:
    """Bulk-insert rows, silently skipping any violating the given unique constraint.

    Returns the set of `index_elements[0]` values that were actually inserted
    (i.e. were new, not duplicates). Dialect-aware so it works against both
    the SQLite dev/test database and the production Postgres deployment.
    """
    if not rows:
        return set()

    dialect = session.bind.dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    else:
        raise RuntimeError(f"unsupported database dialect: {dialect}")

    key_col = index_elements[0]
    stmt = dialect_insert(table).values(list(rows))
    stmt = stmt.on_conflict_do_nothing(index_elements=list(index_elements))
    stmt = stmt.returning(table.c[key_col])
    result = session.execute(stmt)
    return {row[0] for row in result}
