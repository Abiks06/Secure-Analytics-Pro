from __future__ import annotations

import hashlib
import io
import json
import re
from typing import Any, Literal

import anyio
import polars as pl
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import undefer
from sse_starlette.sse import EventSourceResponse

from app.api.deps import Principal, client_ip, current
from app.core import ratelimit
from app.core.config import get_settings
from app.core.crypto import pseudonym_key
from app.db.models import Dataset
from app.engine import pii
from app.engine import query as sql_engine
from app.engine.util import to_jsonable
from app.services import ai, audit, jobs, storage

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


def summary(ds: Dataset) -> dict[str, Any]:
    h = ds.highlights or {}
    return {
        "id": ds.id,
        "name": ds.name,
        "status": ds.status,
        "stage": ds.stage,
        "progress": ds.progress,
        "error": ds.error,
        "source_format": ds.source_format,
        "size_bytes": ds.size_bytes,
        "stored_bytes": ds.stored_bytes,
        "sha256": ds.sha256,
        "row_count": ds.row_count,
        "column_count": ds.column_count,
        "quality_score": ds.quality_score,
        "processing_ms": ds.processing_ms,
        "insight_count": h.get("insight_count", 0),
        "pii_count": h.get("pii_count", 0),
        "top_insights": h.get("top_insights", []),
        "privacy_policy": ds.privacy_policy or {},
        "created_at": ds.created_at,
        "updated_at": ds.updated_at,
    }


async def _get(p: Principal, dataset_id: str, *, ready: bool = False) -> Dataset:
    """Fetch one of the caller's datasets. ``ready=True`` also loads the deferred report and
    wrapped key, which every analysis endpoint needs and list views never do."""
    q = select(Dataset).where(Dataset.id == dataset_id, Dataset.owner_id == p.user_id)
    if ready:
        q = q.options(undefer(Dataset.report), undefer(Dataset.wrapped_key))
    ds = (await p.db.execute(q)).scalar_one_or_none()
    if ds is None:
        raise HTTPException(404, detail="Dataset not found")
    if ready and ds.status != "ready":
        raise HTTPException(409, detail=f"Dataset is {ds.status}")
    return ds


def _policy_key(policy: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()[:16]


def visible_frame(ds: Dataset, token: str) -> pl.DataFrame:
    """The dataset as the owner may see it: privacy policy applied, cached per policy version."""
    policy = ds.privacy_policy or {}
    key = f"{ds.id}:{_policy_key(policy)}"
    hit = storage.cache.get(key)
    if hit is not None:
        return hit
    frame = storage.load_frame(ds.id, ds.wrapped_key, ds.storage_path or "", token)
    if policy:
        findings = (ds.report or {}).get("privacy", {}).get("findings", [])
        frame = pii.apply_policy(frame, policy, findings, pseudonym_key(storage.data_key(ds.id, ds.wrapped_key)))
        storage.cache.put(key, frame)
    return frame


async def _visible(ds: Dataset, token: str) -> pl.DataFrame:
    try:
        return await anyio.to_thread.run_sync(visible_frame, ds, token)
    except storage.StorageError as e:
        raise HTTPException(502, detail="Encrypted dataset could not be fetched from storage.") from e


def scrubbed_report(ds: Dataset) -> dict[str, Any]:
    """The stored report with the privacy policy applied to any raw values it quotes (column top
    values, category labels in insight charts and text), so protected data never leaks via stats."""
    report = ds.report or {}
    policy = {c: m for c, m in (ds.privacy_policy or {}).items() if m != "none"}
    if not policy:
        return report
    report = json.loads(json.dumps(report))
    findings = report.get("privacy", {}).get("findings", [])
    key = pseudonym_key(storage.data_key(ds.id, ds.wrapped_key))
    replacements: dict[str, str] = {}
    for col in report.get("columns", []):
        mode = policy.get(col["name"])
        if not mode or not col.get("top"):
            continue
        raw = [str(t["value"]) for t in col["top"]]
        masked = pii.apply_policy(pl.DataFrame({col["name"]: raw}), {col["name"]: mode}, findings, key)[
            col["name"]
        ].to_list()
        for t, m in zip(col["top"], masked, strict=True):
            replacements[str(t["value"])] = m
            t["value"] = m
        col.pop("length", None)
    for ins in report.get("insights", []):
        if not set(ins.get("columns", [])) & set(policy):
            continue
        for raw, m in replacements.items():
            if len(raw) >= 2:
                ins["title"] = ins["title"].replace(f"'{raw}'", f"'{m}'")
                ins["body"] = ins["body"].replace(f"'{raw}'", f"'{m}'")
        chart = ins.get("chart") or {}
        if chart.get("type") == "bar" and chart.get("x") in policy:
            chart["categories"] = [replacements.get(str(c), "[protected]") for c in chart.get("categories", [])]
    return report


@router.post("", status_code=202)
async def upload(
    request: Request,
    file: UploadFile = File(...),
    p: Principal = Depends(current),
    _rl: None = Depends(ratelimit.limit(ratelimit.UPLOAD)),
) -> dict[str, Any]:
    limit = get_settings().max_upload_mb * 1024 * 1024
    digest = hashlib.sha256()
    buf = bytearray()
    while chunk := await file.read(1 << 20):
        buf += chunk
        digest.update(chunk)
        if len(buf) > limit:
            raise HTTPException(413, detail=f"File exceeds the {get_settings().max_upload_mb} MB limit.")
    if not buf:
        raise HTTPException(400, detail="The file is empty.")
    name = (
        re.sub(r"[^\w .()\-]+", "_", (file.filename or "dataset").rsplit("/", 1)[-1].rsplit("\\", 1)[-1])[:200]
        or "dataset"
    )
    ds = Dataset(owner_id=p.user_id, name=name, size_bytes=len(buf), sha256=digest.hexdigest())
    p.db.add(ds)
    await p.db.flush()
    await audit.record(
        p.db,
        p.user_id,
        "dataset.upload",
        target=ds.id,
        ip=client_ip(request),
        detail={"name": name, "bytes": len(buf), "sha256": ds.sha256},
    )
    await p.db.commit()
    jobs.submit(ds.id, p.user_id, bytes(buf), client_ip(request), p.token)
    return summary(ds)


@router.get("")
async def list_datasets(p: Principal = Depends(current)) -> list[dict[str, Any]]:
    rows = (
        (await p.db.execute(select(Dataset).where(Dataset.owner_id == p.user_id).order_by(Dataset.created_at.desc())))
        .scalars()
        .all()
    )
    return [summary(d) for d in rows]


@router.get("/{dataset_id}")
async def get_dataset(dataset_id: str, p: Principal = Depends(current)) -> dict[str, Any]:
    return summary(await _get(p, dataset_id))


@router.get("/{dataset_id}/report")
async def get_report(dataset_id: str, p: Principal = Depends(current)) -> dict[str, Any]:
    ds = await _get(p, dataset_id, ready=True)
    report = await anyio.to_thread.run_sync(scrubbed_report, ds)
    return {"dataset": summary(ds), "report": report}


@router.get("/{dataset_id}/events")
async def events(dataset_id: str, p: Principal = Depends(current)) -> EventSourceResponse:
    ds = await _get(p, dataset_id)
    initial = {"status": ds.status, "stage": ds.stage, "progress": ds.progress, "message": ds.error}
    terminal = ds.status in ("ready", "failed")
    await p.db.close()

    async def stream():
        yield {"event": "progress", "data": json.dumps(initial)}
        if terminal:
            return
        async for event in jobs.hub.subscribe(dataset_id):
            yield {"event": "progress", "data": json.dumps(event)}

    return EventSourceResponse(stream(), ping=15)


class RenameBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@router.patch("/{dataset_id}")
async def rename(dataset_id: str, body: RenameBody, p: Principal = Depends(current)) -> dict[str, Any]:
    ds = await _get(p, dataset_id)
    ds.name = body.name.strip()
    await p.db.commit()
    return summary(ds)


@router.get("/{dataset_id}/rows")
async def rows(
    dataset_id: str,
    request: Request,
    p: Principal = Depends(current),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    sort: str | None = None,
    desc: bool = False,
    q: str | None = Query(None, max_length=200),
) -> dict[str, Any]:
    ds = await _get(p, dataset_id, ready=True)
    frame = await _visible(ds, p.token)

    def page() -> dict[str, Any]:
        df = frame.with_row_index("__row")
        if q:
            needle = q.lower()
            text_cols = [c for c, t in frame.schema.items() if t == pl.String]
            if text_cols:
                df = df.filter(
                    pl.any_horizontal(
                        [pl.col(c).str.to_lowercase().str.contains(needle, literal=True) for c in text_cols]
                    )
                )
        if sort and sort in frame.columns:
            df = df.sort(sort, descending=desc, nulls_last=True)
        total = df.height
        out = df.slice(offset, limit)
        return {
            "columns": [{"name": c, "type": str(t)} for c, t in frame.schema.items()],
            "index": out["__row"].to_list(),
            "rows": [[to_jsonable(v) for v in r] for r in out.drop("__row").iter_rows()],
            "total": total,
            "offset": offset,
        }

    return await anyio.to_thread.run_sync(page)


class QueryBody(BaseModel):
    sql: str = Field(min_length=1, max_length=20_000)


@router.post("/{dataset_id}/query")
async def run_query(
    dataset_id: str,
    body: QueryBody,
    request: Request,
    p: Principal = Depends(current),
    _rl: None = Depends(ratelimit.limit(ratelimit.QUERY)),
) -> dict[str, Any]:
    ds = await _get(p, dataset_id, ready=True)
    frame = await _visible(ds, p.token)
    s = get_settings()
    try:
        result = await anyio.to_thread.run_sync(
            lambda: sql_engine.execute(frame, body.sql, row_limit=s.query_row_limit, timeout_s=s.query_timeout_s)
        )
    except sql_engine.QueryError as e:
        raise HTTPException(400, detail=str(e)) from e
    await audit.record(
        p.db,
        p.user_id,
        "dataset.query",
        target=ds.id,
        ip=client_ip(request),
        detail={"sql_sha256": hashlib.sha256(body.sql.encode()).hexdigest()[:16], "rows": result["row_count"]},
    )
    await p.db.commit()
    return result


class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


@router.post("/{dataset_id}/ask")
async def ask(
    dataset_id: str,
    body: AskBody,
    request: Request,
    p: Principal = Depends(current),
    _rl: None = Depends(ratelimit.limit(ratelimit.AI)),
) -> dict[str, Any]:
    ds = await _get(p, dataset_id, ready=True)
    frame = await _visible(ds, p.token)
    try:
        result = await ai.ask(body.question, frame, ds.report or {}, ds.privacy_policy or {})
    except ai.AIUnavailable as e:
        raise HTTPException(503, detail=str(e)) from e
    await audit.record(
        p.db,
        p.user_id,
        "dataset.ask",
        target=ds.id,
        ip=client_ip(request),
        detail={"question": body.question[:200], "ok": result["error"] is None},
    )
    await p.db.commit()
    return result


@router.post("/{dataset_id}/narrative")
async def narrative(
    dataset_id: str, p: Principal = Depends(current), _rl: None = Depends(ratelimit.limit(ratelimit.AI))
) -> dict[str, str]:
    ds = await _get(p, dataset_id, ready=True)
    report = dict(ds.report or {})
    if report.get("narrative"):
        return {"narrative": report["narrative"]}
    try:
        text = await ai.narrative(ds.name, report)
    except ai.AIUnavailable as e:
        raise HTTPException(503, detail=str(e)) from e
    report["narrative"] = text
    ds.report = report
    await p.db.commit()
    return {"narrative": text}


class PrivacyBody(BaseModel):
    policy: dict[str, Literal["none", "mask", "hash", "redact"]]


@router.put("/{dataset_id}/privacy")
async def set_privacy(
    dataset_id: str, body: PrivacyBody, request: Request, p: Principal = Depends(current)
) -> dict[str, Any]:
    ds = await _get(p, dataset_id, ready=True)
    columns = {c["name"] for c in (ds.report or {}).get("columns", [])}
    unknown = set(body.policy) - columns
    if unknown:
        raise HTTPException(422, detail=f"Unknown column(s): {', '.join(sorted(unknown))}")
    before = ds.privacy_policy or {}
    after = {c: m for c, m in body.policy.items() if m != "none"}
    storage.cache.drop(f"{ds.id}:{_policy_key(before)}")
    ds.privacy_policy = after
    changes = {
        c: [before.get(c, "none"), after.get(c, "none")]
        for c in columns
        if before.get(c, "none") != after.get(c, "none")
    }
    await audit.record(
        p.db, p.user_id, "privacy.update", target=ds.id, ip=client_ip(request), detail={"changes": changes}
    )
    await p.db.commit()
    return summary(ds)


_FORMULA = re.compile(r"^[=+\-@\t\r]")


@router.get("/{dataset_id}/export")
async def export(
    dataset_id: str,
    request: Request,
    p: Principal = Depends(current),
    format: Literal["csv", "parquet", "json"] = "csv",
) -> StreamingResponse:
    ds = await _get(p, dataset_id, ready=True)
    frame = await _visible(ds, p.token)

    def render() -> bytes:
        buf = io.BytesIO()
        if format == "parquet":
            frame.write_parquet(buf, compression="zstd")
        elif format == "json":
            frame.write_json(buf)
        else:
            # Neutralise spreadsheet formula injection (CWE-1236) in text cells.
            safe = frame.with_columns(
                [
                    pl.when(pl.col(c).str.contains(_FORMULA.pattern))
                    .then(pl.lit("'") + pl.col(c))
                    .otherwise(pl.col(c))
                    .alias(c)
                    for c, t in frame.schema.items()
                    if t == pl.String
                ]
            )
            safe.write_csv(buf)
        return buf.getvalue()

    data = await anyio.to_thread.run_sync(render)
    await audit.record(
        p.db,
        p.user_id,
        "dataset.export",
        target=ds.id,
        ip=client_ip(request),
        detail={"format": format, "rows": frame.height, "policy": ds.privacy_policy},
    )
    await p.db.commit()
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", ds.name)
    media = {"csv": "text/csv", "parquet": "application/vnd.apache.parquet", "json": "application/json"}[format]
    return StreamingResponse(
        iter([data]),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{stem}-clean.{format}"'},
    )


@router.delete("/{dataset_id}", status_code=204)
async def delete(dataset_id: str, request: Request, p: Principal = Depends(current)) -> None:
    ds = await _get(p, dataset_id)
    if ds.status in ("queued", "processing"):
        raise HTTPException(409, detail="Wait for processing to finish before deleting.")
    try:
        await anyio.to_thread.run_sync(storage.shred, ds.id, ds.storage_path, p.token)
    except storage.StorageError as e:
        raise HTTPException(502, detail="Could not delete the encrypted file from storage; nothing was removed.") from e
    await audit.record(
        p.db,
        p.user_id,
        "dataset.delete",
        target=ds.id,
        ip=client_ip(request),
        detail={"name": ds.name, "sha256": ds.sha256},
    )
    await p.db.delete(ds)
    await p.db.commit()
