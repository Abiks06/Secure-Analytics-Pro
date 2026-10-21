"""Sandboxed SQL over a single dataset, powered by DuckDB.

Defence in depth:
1. Parse with DuckDB's own parser; exactly one statement, and it must be a SELECT.
2. A fresh in-memory database per query with external access (files, HTTP, extensions)
   disabled and the configuration locked, so SQL cannot re-enable it.
3. The only table is ``data``, a zero-copy Arrow view of the *privacy-filtered* frame.
4. Hard limits: row cap, memory cap, thread cap and a wall-clock timeout via ``interrupt()``.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any

import duckdb
import polars as pl

from app.engine.util import to_jsonable


class QueryError(ValueError):
    pass


_FORBIDDEN = re.compile(r"\b(read_\w+|glob|attach|install|load|copy|export|import|pragma|call|set)\b", re.I)


def validate(sql: str) -> str:
    sql = sql.strip().rstrip(";").strip()
    if not sql:
        raise QueryError("Query is empty.")
    if len(sql) > 20_000:
        raise QueryError("Query is too long.")
    try:
        statements = duckdb.extract_statements(sql)
    except duckdb.Error as e:
        raise QueryError(_clean_error(e)) from e
    if len(statements) != 1:
        raise QueryError("Exactly one statement is allowed.")
    if statements[0].type != duckdb.StatementType.SELECT:
        raise QueryError("Only read-only SELECT queries are allowed.")
    if _FORBIDDEN.search(re.sub(r"'[^']*'", "''", sql)):
        raise QueryError("This function or keyword is not available in the sandbox.")
    return sql


def _clean_error(e: Exception) -> str:
    msg = str(e).split("\n")[0]
    return re.sub(r"^\w+ Error: ", "", msg)[:400]


def execute(df: pl.DataFrame, sql: str, *, row_limit: int, timeout_s: float) -> dict[str, Any]:
    sql = validate(sql)
    con = duckdb.connect(
        ":memory:",
        config={
            "enable_external_access": False,
            "autoinstall_known_extensions": False,
            "autoload_known_extensions": False,
            "threads": 2,
            "memory_limit": "1GB",
        },
    )
    try:
        con.register("data", df.to_arrow())
        con.execute("SET lock_configuration = true")
        timer = threading.Timer(timeout_s, con.interrupt)
        timer.start()
        started = time.perf_counter()
        try:
            table = con.sql(f"SELECT * FROM ({sql}) AS q LIMIT {row_limit + 1}").to_arrow_table()
        except duckdb.InterruptException as e:
            raise QueryError(f"Query exceeded the {timeout_s:g}s time limit.") from e
        except duckdb.Error as e:
            raise QueryError(_clean_error(e)) from e
        finally:
            timer.cancel()
        elapsed = (time.perf_counter() - started) * 1000
    finally:
        con.close()

    out = pl.from_arrow(table)
    assert isinstance(out, pl.DataFrame)
    truncated = out.height > row_limit
    out = out.head(row_limit)
    return {
        "columns": [{"name": c, "type": str(t)} for c, t in out.schema.items()],
        "rows": [[to_jsonable(v) for v in row] for row in out.iter_rows()],
        "row_count": out.height,
        "truncated": truncated,
        "elapsed_ms": round(elapsed, 2),
    }


def schema_ddl(df: pl.DataFrame) -> str:
    """Describe the ``data`` table as DuckDB types (used to ground the AI assistant)."""
    con = duckdb.connect(":memory:", config={"enable_external_access": False})
    try:
        con.register("data", df.head(0).to_arrow())
        cols = con.execute("DESCRIBE data").fetchall()
    finally:
        con.close()
    return "CREATE TABLE data (\n" + ",\n".join(f'  "{c[0]}" {c[1]}' for c in cols) + "\n);"
