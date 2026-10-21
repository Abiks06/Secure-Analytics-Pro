"""Dataset processing, streamed inside the request that triggers it.

Serverless platforms freeze a function once its response ends, so work is never left running in
the background: ``process_stream`` does the whole job while streaming progress events to the
caller. The browser has already uploaded the file to the user's private Storage folder,
encrypted with a one-time key; here it is downloaded, decrypted in memory, and the encrypted
upload deleted. Plaintext never touches disk or Storage, only the encrypted, cleaned Parquet.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import anyio
from cryptography.exceptions import InvalidTag
from sqlalchemy import select, text, update

from app.core import crypto
from app.core.config import get_settings
from app.db.models import Dataset
from app.db.session import claims_for, is_postgres, tenant_session
from app.engine import pipeline
from app.engine.ingest import IngestError
from app.services import audit, storage

log = logging.getLogger("sap.jobs")

_semaphore: asyncio.Semaphore | None = None
STALE_AFTER_S = 10 * 60


def _sem() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(get_settings().worker_concurrency)
    return _semaphore


def upload_context(dataset_id: str) -> str:
    """AES-GCM associated data binding a browser upload to its dataset."""
    return f"upload:{dataset_id}"


def _event(status: str, stage: str, progress: float, message: str | None = None) -> dict[str, Any]:
    return {"status": status, "stage": stage, "progress": round(progress, 3), "message": message}


async def _claim(owner_id: str, dataset_id: str) -> bool:
    """Atomically move a dataset from queued to processing, so it is processed exactly once."""
    async with tenant_session(claims_for(owner_id)) as s:
        result = await s.execute(
            update(Dataset)
            .where(Dataset.id == dataset_id, Dataset.owner_id == owner_id, Dataset.status == "queued")
            .values(status="processing", stage="validate", progress=0.0)
        )
        await s.commit()
        return bool(result.rowcount)


async def process_stream(
    dataset_id: str, owner_id: str, key: bytes, ip: str, token: str
) -> AsyncIterator[dict[str, Any]]:
    settings = get_settings()
    if not await _claim(owner_id, dataset_id):
        yield _event("failed", "failed", 1.0, "This upload was already processed or is not ready.")
        return

    started = time.perf_counter()
    incoming = storage.incoming_path(owner_id, dataset_id)
    try:
        async with _sem():
            yield _event("processing", "validate", 0.02, "Fetching encrypted upload")
            try:
                blob = await anyio.to_thread.run_sync(storage.get_raw, incoming, token)
                data = crypto.decrypt_blob(key, blob, upload_context(dataset_id))
            except (InvalidTag, ValueError) as e:
                raise IngestError("The upload could not be decrypted. Please upload the file again.") from e
            finally:
                await anyio.to_thread.run_sync(storage.delete_paths, [incoming], token)
            del blob
            if len(data) > settings.max_upload_mb * 1024 * 1024:
                raise IngestError(f"File exceeds the {settings.max_upload_mb} MB limit.")
            digest = hashlib.sha256(data).hexdigest()
            async with tenant_session(claims_for(owner_id)) as s:
                await s.execute(
                    update(Dataset).where(Dataset.id == dataset_id).values(size_bytes=len(data), sha256=digest)
                )
                await audit.record(
                    s,
                    owner_id,
                    "dataset.upload",
                    target=dataset_id,
                    ip=ip,
                    detail={"bytes": len(data), "sha256": digest, "client_encrypted": True},
                )
                await s.commit()

            # Run the CPU-bound pipeline in a worker thread and relay its progress as it happens.
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

            def progress(stage: str, frac: float, message: str | None) -> None:
                loop.call_soon_threadsafe(queue.put_nowait, _event("processing", stage, frac, message))

            work = asyncio.ensure_future(
                anyio.to_thread.run_sync(
                    lambda: pipeline.run(
                        data, max_decompressed=settings.max_decompressed_mb * 1024 * 1024, progress=progress
                    )
                )
            )
            while not (work.done() and queue.empty()):
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=0.25)
                except TimeoutError:
                    continue
            out = work.result()

            yield _event("processing", "secure", 6 / 7, "AES-256-GCM, per-dataset key")
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
            yield _event("ready", "ready", 1.0, f"Done in {elapsed / 1000:.2f}s")
    except IngestError as e:
        await _fail(owner_id, dataset_id, str(e), ip)
        yield _event("failed", "failed", 1.0, str(e))
    except storage.StorageError as e:
        log.warning("storage error for %s: %s", dataset_id, e)
        message = "The encrypted upload could not be read from storage. Please upload again."
        await _fail(owner_id, dataset_id, message, ip)
        yield _event("failed", "failed", 1.0, message)
    except Exception:
        log.exception("processing failed for %s", dataset_id)
        message = "Processing failed unexpectedly. The file may be malformed."
        await _fail(owner_id, dataset_id, message, ip)
        yield _event("failed", "failed", 1.0, message)


async def _fail(owner_id: str, dataset_id: str, message: str, ip: str) -> None:
    async with tenant_session(claims_for(owner_id)) as s:
        await s.execute(
            update(Dataset)
            .where(Dataset.id == dataset_id, Dataset.owner_id == owner_id)
            .values(status="failed", stage="failed", error=message)
        )
        await audit.record(s, owner_id, "dataset.failed", target=dataset_id, ip=ip, detail={"error": message})
        await s.commit()


async def recover_interrupted() -> None:
    """Jobs cut off mid-flight (closed tab, function timeout, restart) cannot resume because
    the plaintext only ever lived in memory; mark long-stalled ones failed."""
    async with tenant_session(None) as s:
        if is_postgres:
            # RLS hides every row from an unscoped session; this one cross-tenant chore goes
            # through a SECURITY DEFINER function that only sap_engine may execute.
            await s.execute(text("select sap.fail_interrupted_jobs(make_interval(secs => :s))"), {"s": STALE_AFTER_S})
        else:
            rows = (await s.execute(select(Dataset).where(Dataset.status == "processing"))).scalars().all()
            for ds in rows:
                ds.status, ds.stage, ds.error = "failed", "failed", "Interrupted. Please upload again."
        await s.commit()
