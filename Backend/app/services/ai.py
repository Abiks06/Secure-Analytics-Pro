"""Natural-language analytics with Claude.

Privacy model: Claude never receives the raw dataset. It sees the table schema, aggregate column
statistics, and at most a small sample of *query results* computed over the privacy-filtered
frame, so masked/redacted PII stays masked. Generated SQL runs in the same DuckDB sandbox as
user-written SQL.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic
import polars as pl

from app.core.config import get_settings
from app.engine import query as sql_engine

_SQL_SCHEMA = {
    "type": "object",
    "properties": {
        "sql": {"type": "string", "description": "One DuckDB SELECT over the table `data`."},
        "rationale": {"type": "string", "description": "One sentence on how the query answers the question."},
        "chart": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["bar", "line", "scatter", "table", "metric"]},
                "x": {"type": ["string", "null"]},
                "y": {"type": ["string", "null"]},
            },
            "required": ["type", "x", "y"],
            "additionalProperties": False,
        },
    },
    "required": ["sql", "rationale", "chart"],
    "additionalProperties": False,
}

_SQL_SYSTEM = """You translate analytics questions into DuckDB SQL over a single table named `data`.
Rules:
- Exactly one read-only SELECT (CTEs are fine). Never reference other tables, files or URLs.
- Quote every column name with double quotes exactly as given in the schema.
- Aggregate where the question implies it, ORDER results meaningfully, and LIMIT to at most 200 rows.
- For time trends use date_trunc on the date column. Round floats to 2 decimals.
- Some text columns are masked or redacted for privacy; do not try to unmask or infer identities.
- Pick the chart that best shows the result: line for time series, bar for category comparisons,
  scatter for two numeric measures, metric for a single number, table otherwise. x/y must be
  output column names of your query (or null)."""

_ANSWER_SYSTEM = """You are a precise data analyst. Answer the user's question in 1-3 short sentences
using only the query result provided. Lead with the number or finding, mention units when known,
and say plainly if the result cannot answer the question. No markdown headings, no preamble."""

_NARRATIVE_SYSTEM = """You are a senior data analyst writing an executive summary of an automated
analysis. Use only the findings and statistics provided; never invent numbers. Write 3 short
paragraphs: what the data is and its quality, the most important patterns, and recommended next
steps. Plain prose, no headings, under 220 words."""


class AIUnavailable(RuntimeError):
    pass


def available() -> bool:
    return bool(get_settings().anthropic_api_key)


def _client() -> anthropic.AsyncAnthropic:
    key = get_settings().anthropic_api_key
    if not key:
        raise AIUnavailable("Set ANTHROPIC_API_KEY on the server to enable the AI analyst.")
    return anthropic.AsyncAnthropic(api_key=key, timeout=90.0, max_retries=2)


async def _create(**kwargs: Any) -> str:
    """Run one request with server-side refusal fallback and return its text."""
    try:
        response = await _client().beta.messages.create(
            model=get_settings().anthropic_model,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            **kwargs,
        )
    except anthropic.RateLimitError as e:
        raise AIUnavailable("The AI analyst is busy right now. Try again in a minute.") from e
    except anthropic.AuthenticationError as e:
        raise AIUnavailable("The server's Anthropic API key was rejected.") from e
    except anthropic.APIConnectionError as e:
        raise AIUnavailable("Could not reach the AI service.") from e
    except anthropic.APIStatusError as e:
        raise AIUnavailable(f"AI service error ({e.status_code}).") from e
    if response.stop_reason == "refusal":
        raise AIUnavailable("The AI analyst declined this request.")
    return "".join(b.text for b in response.content if b.type == "text").strip()


def _column_brief(report: dict[str, Any]) -> str:
    lines = []
    for c in report.get("columns", []):
        bits = [f'"{c["name"]}" ({c["kind"]}', f"{c['null_pct']:.0%} missing)"]
        st = c.get("stats") or {}
        if c["kind"] == "numeric":
            bits.append(f"min={st.get('min')}, median={st.get('q50')}, max={st.get('max')}")
        elif c["kind"] == "datetime":
            bits.append(f"range {st.get('min')} to {st.get('max')}")
        elif c.get("top"):
            bits.append("values: " + ", ".join(str(t["value"]) for t in c["top"][:6]))
        if c.get("unit"):
            bits.append(f"unit={c['unit']}")
        lines.append(" ".join(bits))
    return "\n".join(lines)


async def ask(question: str, frame: pl.DataFrame, report: dict[str, Any], privacy: dict[str, str]) -> dict[str, Any]:
    settings = get_settings()
    ddl = sql_engine.schema_ddl(frame)
    protected = ", ".join(f'"{c}" ({m})' for c, m in privacy.items() if m != "none") or "none"
    context = (
        f"Schema:\n{ddl}\n\nRows: {frame.height}\nColumn profile:\n{_column_brief(report)}\n\n"
        f"Privacy-protected columns: {protected}"
    )
    messages: list[dict[str, Any]] = [{"role": "user", "content": f"{context}\n\nQuestion: {question}"}]
    plan: dict[str, Any] = {}
    result: dict[str, Any] | None = None
    error = None
    for _attempt in range(2):
        text = await _create(
            max_tokens=4000,
            system=_SQL_SYSTEM,
            messages=messages,
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": _SQL_SCHEMA}},
        )
        plan = json.loads(text)
        try:
            result = sql_engine.execute(
                frame, plan["sql"], row_limit=min(settings.query_row_limit, 500), timeout_s=settings.query_timeout_s
            )
            break
        except sql_engine.QueryError as e:
            error = str(e)
            messages += [
                {"role": "assistant", "content": text},
                {"role": "user", "content": f"That query failed: {error}\nReturn a corrected query."},
            ]
    if result is None:
        return {"question": question, "sql": plan.get("sql"), "error": error, "answer": None, "result": None}

    preview = {"columns": [c["name"] for c in result["columns"]], "rows": result["rows"][:50]}
    answer = await _create(
        max_tokens=2000,
        system=_ANSWER_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": f"Question: {question}\nSQL: {plan['sql']}\n"
                f"Result ({result['row_count']} rows{', truncated' if result['truncated'] else ''}):\n"
                f"{json.dumps(preview, default=str)}",
            }
        ],
        output_config={"effort": "low"},
    )
    return {
        "question": question,
        "sql": plan["sql"],
        "rationale": plan.get("rationale"),
        "chart": plan.get("chart"),
        "answer": answer,
        "result": result,
        "error": None,
    }


async def narrative(name: str, report: dict[str, Any]) -> str:
    findings = [
        {"title": i["title"], "detail": i["body"], "severity": i["severity"]} for i in report.get("insights", [])[:14]
    ]
    payload = {
        "dataset": name,
        "overview": report.get("overview"),
        "quality": report.get("quality"),
        "cleaning": [a["detail"] for a in report.get("cleaning", {}).get("actions", [])][:12],
        "findings": findings,
    }
    return await _create(
        max_tokens=4000,
        system=_NARRATIVE_SYSTEM,
        messages=[{"role": "user", "content": json.dumps(payload, default=str)}],
        output_config={"effort": "medium"},
    )
