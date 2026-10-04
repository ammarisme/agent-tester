"""Engine, sessions and a small additive migrator.

``init_db`` creates missing tables, then adds any model columns missing from
existing tables (``ALTER TABLE … ADD COLUMN``). That covers every schema change
so far; a change that renames or drops columns needs a real migration.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.models import Base

log = logging.getLogger(__name__)


def _make_engine(url: str) -> AsyncEngine:
    eng = create_async_engine(url, echo=False)
    if eng.dialect.name == "sqlite":

        @event.listens_for(eng.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record) -> None:  # pragma: no cover - driver hook
            cur = dbapi_conn.cursor()
            # WAL lets the UI read while a run writes results; FKs make cascades real.
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return eng


engine = _make_engine(settings.sqlalchemy_url())
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _add_missing_columns(conn: Connection) -> None:
    insp = inspect(conn)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            col_type = column.type.compile(dialect=conn.dialect)
            ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'
            if column.server_default is not None:
                ddl += f" DEFAULT '{column.server_default.arg}'"
            log.info("migrating: %s", ddl)
            conn.execute(text(ddl))


async def init_db(eng: AsyncEngine | None = None) -> None:
    async with (eng or engine).begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
