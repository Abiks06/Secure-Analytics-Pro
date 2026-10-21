from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.deps import Principal, current
from app.core.config import get_settings
from app.db.models import AuditEvent, Dataset
from app.services import ai, audit, storage

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/system")
async def system_info(p: Principal = Depends(current)) -> dict[str, Any]:
    s = get_settings()
    stats = (
        await p.db.execute(
            select(
                func.count(Dataset.id),
                func.coalesce(func.sum(Dataset.row_count), 0),
                func.coalesce(func.sum(Dataset.stored_bytes), 0),
                func.avg(Dataset.quality_score),
            ).where(Dataset.owner_id == p.user.id, Dataset.status == "ready")
        )
    ).one()
    return {
        "ai_enabled": ai.available(),
        "ai_model": s.anthropic_model if ai.available() else None,
        "max_upload_mb": s.max_upload_mb,
        "query_row_limit": s.query_row_limit,
        "query_timeout_s": s.query_timeout_s,
        "database": "postgresql+rls" if s.is_postgres else "sqlite",
        "encryption": "AES-256-GCM envelope (per-dataset DEK, wrapped by KEK)",
        "token_signing": "EdDSA (Ed25519)",
        "password_hashing": "Argon2id",
        "cache": storage.cache.stats(),
        "usage": {
            "datasets": stats[0],
            "rows": int(stats[1]),
            "stored_bytes": int(stats[2]),
            "avg_quality": round(float(stats[3]), 1) if stats[3] is not None else None,
        },
    }


@router.get("/audit")
async def audit_log(
    p: Principal = Depends(current), limit: int = Query(50, ge=1, le=200), before: int | None = None
) -> list[dict[str, Any]]:
    q = select(AuditEvent).where(AuditEvent.owner_id == p.user.id)
    if before:
        q = q.where(AuditEvent.seq < before)
    rows = (await p.db.execute(q.order_by(AuditEvent.seq.desc()).limit(limit))).scalars().all()
    return [
        {
            "seq": e.seq,
            "action": e.action,
            "target": e.target,
            "ip": e.ip,
            "detail": e.detail,
            "created_at": e.created_at,
            "hash": e.hash,
            "prev_hash": e.prev_hash,
        }
        for e in rows
    ]


@router.get("/audit/verify")
async def audit_verify(p: Principal = Depends(current)) -> dict[str, Any]:
    return await audit.verify(p.db, p.user.id)
