"""Database engine, sessions and PostgreSQL Row Level Security.

On PostgreSQL, tenant tables have RLS forced on, and every transaction sets
``app.user_id`` via ``set_config(..., is_local => true)``. Even a bug that forgets an
``owner_id`` filter cannot read another tenant's rows. The application filters by owner too, so
SQLite (dev) keeps the same behaviour minus the database-level backstop.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models import Base

_settings = get_settings()
if _settings.database_url.startswith("sqlite"):
    (_settings.data_dir).mkdir(parents=True, exist_ok=True)

engine = create_async_engine(
    _settings.database_url,
    pool_pre_ping=True,
    **({} if _settings.database_url.startswith("sqlite") else {"pool_size": 10, "max_overflow": 20}),
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

if engine.dialect.name == "sqlite":

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()


RLS_TABLES = {"datasets": "owner_id", "audit_events": "owner_id", "auth_sessions": "user_id"}


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.dialect.name == "postgresql":
            for table, column in RLS_TABLES.items():
                await conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
                await conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
                await conn.execute(text(f"DROP POLICY IF EXISTS tenant_isolation ON {table}"))
                await conn.execute(
                    text(
                        f"CREATE POLICY tenant_isolation ON {table} USING "
                        f"({column} = current_setting('app.user_id', true) "
                        f"OR current_setting('app.bypass_rls', true) = 'on') "
                        f"WITH CHECK ({column} = current_setting('app.user_id', true) "
                        f"OR current_setting('app.bypass_rls', true) = 'on')"
                    )
                )


@asynccontextmanager
async def tenant_session(user_id: str | None = None, *, system: bool = False) -> AsyncIterator[AsyncSession]:
    """A session whose every transaction is scoped to ``user_id`` under RLS.

    ``system=True`` is reserved for auth bootstrap paths (login, refresh-token lookup before
    the user is known) and is never reachable from data endpoints.
    """
    async with SessionLocal() as session:
        if engine.dialect.name == "postgresql":

            @event.listens_for(session.sync_session, "after_begin")
            def _scope(_session, _transaction, connection) -> None:
                if user_id:
                    connection.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": user_id})
                if system:
                    connection.execute(text("SELECT set_config('app.bypass_rls', 'on', true)"))

        yield session
