"""Tamper-evident audit trail.

Events form a per-user hash chain: ``hash = SHA-256(prev_hash || canonical(event))``. Editing,
deleting or reordering any stored event changes every hash after it, which ``verify`` detects
and pinpoints. A unique (owner, seq) index prevents two writers from forking the chain.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditEvent

GENESIS = "0" * 64


def _utc_naive(ts: datetime) -> datetime:
    # SQLite returns naive datetimes (stored as UTC); PostgreSQL returns aware ones.
    return ts if ts.tzinfo is None else ts.astimezone(UTC).replace(tzinfo=None)


def _digest(
    prev: str, owner_id: str, seq: int, action: str, target: str | None, ip: str, detail: dict, ts: datetime
) -> str:
    payload = json.dumps(
        {
            "owner": owner_id,
            "seq": seq,
            "action": action,
            "target": target,
            "ip": ip,
            "detail": detail,
            "ts": _utc_naive(ts).isoformat(timespec="microseconds"),
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256((prev + payload).encode()).hexdigest()


async def record(
    session: AsyncSession,
    owner_id: str,
    action: str,
    *,
    target: str | None = None,
    ip: str = "",
    detail: dict[str, Any] | None = None,
) -> AuditEvent:
    detail = detail or {}
    for _ in range(5):
        last = (
            await session.execute(
                select(AuditEvent).where(AuditEvent.owner_id == owner_id).order_by(AuditEvent.seq.desc()).limit(1)
            )
        ).scalar_one_or_none()
        seq = (last.seq + 1) if last else 1
        prev = last.hash if last else GENESIS
        ts = datetime.now(UTC)
        event = AuditEvent(
            owner_id=owner_id,
            seq=seq,
            action=action,
            target=target,
            ip=ip,
            detail=detail,
            created_at=ts,
            prev_hash=prev,
            hash=_digest(prev, owner_id, seq, action, target, ip, detail, ts),
        )
        try:
            async with session.begin_nested():
                session.add(event)
            return event
        except IntegrityError:
            continue  # a concurrent writer took this seq; re-read the head and retry
    raise RuntimeError("Could not append audit event")


async def verify(session: AsyncSession, owner_id: str) -> dict[str, Any]:
    rows = (
        (await session.execute(select(AuditEvent).where(AuditEvent.owner_id == owner_id).order_by(AuditEvent.seq)))
        .scalars()
        .all()
    )
    prev = GENESIS
    for i, e in enumerate(rows, start=1):
        expected = _digest(prev, e.owner_id, e.seq, e.action, e.target, e.ip, e.detail, e.created_at)
        if e.seq != i or e.prev_hash != prev or e.hash != expected:
            return {"valid": False, "events": len(rows), "broken_at": e.seq, "head": prev}
        prev = e.hash
    return {"valid": True, "events": len(rows), "broken_at": None, "head": prev}
