"""Background processing with live progress.

Uploads are processed in a bounded worker pool (CPU work runs in threads, off the event loop).
Progress is fanned out to any number of subscribers through per-dataset queues; late subscribers
immediately receive the latest state. The raw upload only ever lives in memory: plaintext is
never written to disk, only the encrypted, cleaned Parquet.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any

import anyio
from sqlalchemy import select, text, update

from app.core.config import get_settings
from app.db.models import Dataset
from app.db.session import claims_for, is_postgres, tenant_session
from app.engine import pipeline
from app.engine.ingest import IngestError
from app.services import audit, storage

log = logging.getLogger("sap.jobs")


class ProgressHub:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._latest: dict[str, dict[str, Any]] = {}

    def publish(self, dataset_id: str, event: dict[str, Any]) -> None:
        self._latest[dataset_id] = event
        for q in list(self._subs.get(dataset_id, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass
        if event.get("status") in ("ready", "failed"):
            # Keep the terminal state briefly for late subscribers, then forget it.
            asyncio.get_running_loop().call_later(60, self._latest.pop, dataset_id, None)

    async def subscribe(self, dataset_id: str) -> AsyncIterator[dict[str, Any]]:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subs[dataset_id].add(q)
        try:
            if dataset_id in self._latest:
                yield self._latest[dataset_id]
            while True:
                event = await q.get()
                yield event
                if event.get("status") in ("ready", "failed"):
                    return
        finally:
            self._subs[dataset_id].discard(q)
            if not self._subs[dataset_id]:
                self._subs.pop(dataset_id, None)


hub = ProgressHub()
_semaphore: asyncio.Semaphore | None = None
_tasks: set[asyncio.Task] = set()


def _sem() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(get_settings().worker_concurrency)
    return _semaphore


def submit(dataset_id: str, owner_id: str, data: bytes, ip: str, token: str) -> None:
    """Queue processing. ``token`` is the uploader's access token, used only to write the
    encrypted result to their Storage folder (processing takes seconds; tokens last an hour)."""
    hub.publish(dataset_id, {"status": "queued", "stage": "queued", "progress": 0.0, "message": "Waiting for a worker"})
    task = asyncio.create_task(_process(dataset_id, owner_id, data, ip, token))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _set(owner_id: str, dataset_id: str, **values: Any) -> None:
    async with tenant_session(claims_for(owner_id)) as s:
        await s.execute(update(Dataset).where(Dataset.id == dataset_id, Dataset.owner_id == owner_id).values(**values))
        await s.commit()


async def _process(dataset_id: str, owner_id: str, data: bytes, ip: str, token: str) -> None:
    loop = asyncio.get_running_loop()
    settings = get_settings()
    async with _sem():
        started = time.perf_counter()

        def progress(stage: str, frac: float, message: str | None) -> None:
            # Live progress goes to subscribers over SSE only; the database is written at the
            # start and end of a job, keeping round trips to the managed database to a minimum.
            event = {"status": "processing", "stage": stage, "progress": round(frac, 3), "message": message}
            loop.call_soon_threadsafe(hub.publish, dataset_id, event)

        try:
            await _set(owner_id, dataset_id, status="processing", stage="validate", progress=0.0)
            out = await anyio.to_thread.run_sync(
                lambda: pipeline.run(
                    data, max_decompressed=settings.max_decompressed_mb * 1024 * 1024, progress=progress
                )
            )
            hub.publish(
                dataset_id,
                {
                    "status": "processing",
                    "stage": "secure",
                    "progress": round(6 / 7, 3),
                    "message": "AES-256-GCM, per-dataset key",
                },
            )
            t_secure = time.perf_counter()
            wrapped, stored, path = await anyio.to_thread.run_sync(
                storage.save_frame, owner_id, dataset_id, out.frame, token
            )
            out.report["timings_ms"]["secure"] = round((time.perf_counter() - t_secure) * 1000, 1)
            elapsed = int((time.perf_counter() - started) * 1000)
            out.report["timings_ms"]["total"] = elapsed
            async with tenant_session(claims_for(owner_id)) as s:
                await s.execute(
                    update(Dataset)
                    .where(Dataset.id == dataset_id, Dataset.owner_id == owner_id)
                    .values(
                        storage_path=path,
                        status="ready",
                        stage="ready",
                        progress=1.0,
                        error=None,
                        source_format=out.source_format,
                        row_count=out.frame.height,
                        column_count=out.frame.width,
                        quality_score=out.report["quality"]["score"],
                        stored_bytes=stored,
                        wrapped_key=wrapped,
                        report=out.report,
                        highlights={
                            "insight_count": len(out.report["insights"]),
                            "pii_count": len(out.report["privacy"]["findings"]),
                            "top_insights": [
                                {k: i[k] for k in ("title", "kind", "severity")} for i in out.report["insights"][:3]
                            ],
                        },
                        privacy_policy=out.policy,
                        processing_ms=elapsed,
                    )
                )
                await audit.record(
                    s,
                    owner_id,
                    "dataset.processed",
                    target=dataset_id,
                    ip=ip,
                    detail={
                        "rows": out.frame.height,
                        "columns": out.frame.width,
                        "ms": elapsed,
                        "pii_columns": len(out.report["privacy"]["findings"]),
                    },
                )
                await s.commit()
            hub.publish(
                dataset_id,
                {"status": "ready", "stage": "ready", "progress": 1.0, "message": f"Done in {elapsed / 1000:.2f}s"},
            )
        except IngestError as e:
            await _fail(owner_id, dataset_id, str(e), ip)
        except Exception:
            log.exception("processing failed for %s", dataset_id)
            await _fail(owner_id, dataset_id, "Processing failed unexpectedly. The file may be malformed.", ip)


async def _fail(owner_id: str, dataset_id: str, message: str, ip: str) -> None:
    async with tenant_session(claims_for(owner_id)) as s:
        await s.execute(
            update(Dataset)
            .where(Dataset.id == dataset_id, Dataset.owner_id == owner_id)
            .values(status="failed", stage="failed", error=message)
        )
        await audit.record(s, owner_id, "dataset.failed", target=dataset_id, ip=ip, detail={"error": message})
        await s.commit()
    hub.publish(dataset_id, {"status": "failed", "stage": "failed", "progress": 1.0, "message": message})


async def recover_interrupted() -> None:
    """Raw uploads are memory-only, so jobs cut off by a restart cannot resume; mark them failed."""
    async with tenant_session(None) as s:
        if is_postgres:
            # RLS hides every row from an unscoped session; this one cross-tenant chore goes
            # through a SECURITY DEFINER function that only sap_engine may execute.
            await s.execute(text("select sap.fail_interrupted_jobs()"))
        else:
            rows = (
                (await s.execute(select(Dataset).where(Dataset.status.in_(["queued", "processing"])))).scalars().all()
            )
            for ds in rows:
                ds.status, ds.stage, ds.error = (
                    "failed",
                    "failed",
                    "Interrupted by a server restart. Please upload again.",
                )
        await s.commit()


async def drain(timeout: float = 30) -> None:
    if _tasks:
        await asyncio.wait(_tasks, timeout=timeout)
