"""Check the live Supabase project's isolation guarantees as the engine role.

    uv run python scripts/check_supabase.py

Uses SAP_DATABASE_URL from Backend/.env. Every check must print OK.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path

import asyncpg


def _dsn() -> dict:
    env = dict(
        line.split("=", 1) for line in Path(".env").read_text().splitlines() if "=" in line and not line.startswith("#")
    )
    m = re.match(r"postgresql\+asyncpg://([^:]+):([^@]+)@([^:/]+):(\d+)/(\w+)", env["SAP_DATABASE_URL"].strip())
    if not m:
        raise SystemExit("SAP_DATABASE_URL is not a postgresql+asyncpg URL")
    user, password, host, port, db = m.groups()
    return {"user": user, "password": password, "host": host, "port": int(port), "database": db, "ssl": "require"}


async def expect_denied(
    con: asyncpg.Connection, label: str, sql: str, expect: type[Exception] = asyncpg.PostgresError
) -> None:
    try:
        async with con.transaction():
            await con.execute(sql)
    except expect as e:
        print(f"OK    {label}: refused ({type(e).__name__}: {str(e).splitlines()[0][:70]})")
        return
    raise SystemExit(f"FAIL  {label}: statement was allowed")


async def main() -> None:
    con = await asyncpg.connect(**_dsn())
    try:
        role = await con.fetchrow(
            "select rolsuper, rolbypassrls, rolinherit from pg_roles where rolname = current_user"
        )
        assert not role["rolsuper"] and not role["rolbypassrls"], "engine role must not bypass RLS"
        print(f"OK    connected as {await con.fetchval('select current_user')} (no superuser, no BYPASSRLS)")

        async with con.transaction():
            n = await con.fetchval("select count(*) from sap.datasets")
            assert n == 0, f"unscoped session saw {n} datasets"
        print("OK    no claims -> RLS hides every dataset")

        async with con.transaction():
            await con.execute(
                "select set_config('request.jwt.claims', $1, true)", json.dumps({"sub": str(uuid.uuid4())})
            )
            n = await con.fetchval("select count(*) from sap.datasets")
            assert n == 0, f"a stranger saw {n} datasets"
            assert not await con.fetchval("select sap.session_is_active($1)", uuid.uuid4())
        print("OK    unknown user -> sees nothing, has no live session")

        denied = asyncpg.InsufficientPrivilegeError
        await expect_denied(con, "read auth.users", "select * from auth.users limit 1", denied)
        await expect_denied(con, "edit audit trail", "update sap.audit_events set ip = 'x'", denied)
        await expect_denied(con, "delete audit trail", "delete from sap.audit_events", denied)
        me, other = uuid.uuid4(), uuid.uuid4()
        await expect_denied(
            con,
            "insert a row owned by another tenant",
            f"select set_config('request.jwt.claims', '{{\"sub\": \"{me}\"}}', true); "
            f"insert into sap.datasets (owner_id, name) values ('{other}', 'x')",
            expect=asyncpg.InsufficientPrivilegeError,
        )
        await expect_denied(con, "drop table", "drop table sap.datasets", denied)
        print("All isolation checks passed.")
    finally:
        await con.close()


if __name__ == "__main__":
    asyncio.run(main())
