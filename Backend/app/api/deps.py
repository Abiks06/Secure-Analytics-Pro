from __future__ import annotations

from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import anyio
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenError, verify_access_token
from app.db.models import AuditEvent
from app.db.session import authorize_request, tenant_session
from app.services import audit

_bearer = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    user_id: str
    email: str
    name: str
    session_id: str
    token: str
    db: AsyncSession
    claims: dict[str, Any] = field(repr=False, default_factory=dict)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"})


# Sessions already recorded in the audit trail (bounded, per process).
_seen_sessions: OrderedDict[str, None] = OrderedDict()


async def _note_session(db: AsyncSession, p_user: str, sid: str, request: Request) -> None:
    """Record the first request of each Supabase session as a sign-in event."""
    if sid in _seen_sessions:
        return
    # Claim it before awaiting, so concurrent first requests don't both log a sign-in.
    _seen_sessions[sid] = None
    exists = (
        await db.execute(
            select(AuditEvent.id).where(
                AuditEvent.owner_id == p_user, AuditEvent.action == "auth.session_started", AuditEvent.target == sid
            )
        )
    ).first()
    if not exists:
        await audit.record(
            db,
            p_user,
            "auth.session_started",
            target=sid,
            ip=client_ip(request),
            detail={"ua": (request.headers.get("user-agent") or "")[:120]},
        )
        await db.commit()
    while len(_seen_sessions) > 10_000:
        _seen_sessions.popitem(last=False)


async def current(
    request: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer)
) -> AsyncIterator[Principal]:
    """Verify the Supabase access token and yield a DB session scoped (RLS) to its claims."""
    if creds is None:
        raise _unauthorized("Not authenticated")
    try:
        claims = await anyio.to_thread.run_sync(verify_access_token, creds.credentials)
    except jwt.ExpiredSignatureError as e:
        raise _unauthorized("Access token expired") from e
    except (TokenError, jwt.PyJWTError) as e:
        raise _unauthorized("Invalid access token") from e

    user_id, sid = claims["sub"], claims["session_id"]
    meta = claims.get("user_metadata") or {}
    async with tenant_session(claims) as db:
        if not await authorize_request(db, claims):
            raise _unauthorized("Session has been revoked")
        await _note_session(db, user_id, sid, request)
        request.state.user_id = user_id
        yield Principal(
            user_id=user_id,
            email=claims.get("email", ""),
            name=meta.get("name") or meta.get("full_name") or claims.get("email", "").split("@")[0],
            session_id=sid,
            token=creds.credentials,
            db=db,
            claims=claims,
        )
