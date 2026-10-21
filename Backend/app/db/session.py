"""Database engine and tenant-scoped sessions.

On Supabase the engine connects as `sap_engine`, a role with no superuser or BYPASSRLS rights,
and every transaction sets ``request.jwt.claims`` to the caller's verified token claims (the
same mechanism Supabase's Data API uses). The RLS policies key on ``sap.uid()``, so even a
query that forgets its ``owner_id`` filter only ever sees the caller's rows. The application
filters by owner as well, which keeps the offline SQLite test database equally correct.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models import Base

_settings = get_settings()
_sqlite = _settings.database_url.startswith("sqlite")

engine = create_async_engine(
    _settings.database_url,
    # SQLite has no schemas: map `sap.*` onto the main database.
    execution_options={"schema_translate_map": {"sap": None}} if _sqlite else {},
    # No pre-ping on Postgres: every request already starts with a query, and each ping is a
    # full round trip to the managed database. Recycling keeps pooled connections fresh.
    **({} if _sqlite else {"pool_size": 5, "max_overflow": 5, "pool_recycle": 240, "pool_use_lifo": True}),
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
is_postgres = engine.dialect.name == "postgresql"

if _sqlite:

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()


async def init_db() -> None:
    async with engine.begin() as conn:
        if is_postgres:
            exists = (await conn.execute(text("select to_regclass('sap.datasets') is not null"))).scalar()
            if not exists:
                raise RuntimeError("Schema `sap` is missing: apply the migrations in supabase/migrations first")
        else:
            await conn.run_sync(Base.metadata.create_all)


def claims_for(user_id: str) -> dict[str, Any]:
    """Minimal claims for work done on a user's behalf outside a request (background jobs)."""
    return {"sub": user_id, "role": "authenticated"}


@asynccontextmanager
async def tenant_session(claims: dict[str, Any] | None) -> AsyncIterator[AsyncSession]:
    """A session whose every transaction runs with ``request.jwt.claims`` = ``claims``.
    ``None`` means no tenant: RLS then hides every row."""
    async with SessionLocal() as session:
        if is_postgres:
            payload = json.dumps(claims or {})

            @event.listens_for(session.sync_session, "after_begin")
            def _scope(sync_session, _transaction, connection) -> None:
                # `authorize_request` scopes its own first transaction in the same round trip.
                if sync_session.info.pop("scoped_inline", False):
                    return
                connection.execute(text("select set_config('request.jwt.claims', :c, true)"), {"c": payload})

        yield session


async def authorize_request(session: AsyncSession, claims: dict[str, Any]) -> bool:
    """Scope the session's transaction to ``claims`` and confirm the Supabase session is still
    live, in a single round trip (see ``sap.authorize``)."""
    if not is_postgres:
        return True
    session.sync_session.info["scoped_inline"] = True
    result = await session.execute(text("select sap.authorize(cast(:c as jsonb))"), {"c": json.dumps(claims)})
    return bool(result.scalar())
