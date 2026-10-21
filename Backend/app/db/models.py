"""ORM mappings for the `sap` schema.

The schema itself (tables, RLS policies, grants, triggers) is owned by the Supabase migrations
in ``supabase/migrations``; these mappings mirror it. Users live in Supabase Auth.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Index, Integer, LargeBinary, MetaData, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

_JSON = JSON().with_variant(JSONB(), "postgresql")
_ID = Uuid(as_uuid=False)


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(schema="sap")
    type_annotation_map = {dict[str, Any]: _JSON}


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(_ID, primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(_ID)
    name: Mapped[str] = mapped_column(Text)
    source_format: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(Text, default="queued")  # queued|processing|ready|failed
    stage: Mapped[str] = mapped_column(Text, default="queued")
    progress: Mapped[float] = mapped_column(default=0.0)
    error: Mapped[str | None] = mapped_column(Text)

    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    stored_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    sha256: Mapped[str] = mapped_column(Text, default="")
    row_count: Mapped[int] = mapped_column(BigInteger, default=0)
    column_count: Mapped[int] = mapped_column(Integer, default=0)
    quality_score: Mapped[float | None] = mapped_column()
    processing_ms: Mapped[int | None] = mapped_column(Integer)

    # Large or sensitive columns are deferred: list views load only `highlights`.
    wrapped_key: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    storage_path: Mapped[str | None] = mapped_column(Text)
    report: Mapped[dict[str, Any] | None] = mapped_column(_JSON, deferred=True)
    highlights: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict)
    privacy_policy: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (Index("datasets_owner_created_idx", "owner_id", "created_at"),)


class AuditEvent(Base):
    """Append-only, hash-chained audit trail. Each event commits to the previous event's hash
    for the same user, so any edit or deletion breaks verification from that point on. On
    Supabase the table also rejects UPDATE/DELETE outright."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(_ID)
    seq: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(Text)
    target: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[dict[str, Any]] = mapped_column(_JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    prev_hash: Mapped[str] = mapped_column(Text)
    hash: Mapped[str] = mapped_column(Text)

    __table_args__ = (Index("audit_events_owner_id_seq_key", "owner_id", "seq", unique=True),)
