from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.models import AuthSession, User
from app.db.session import tenant_session

_bearer = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    user: User
    session_id: str
    db: AsyncSession


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"})


async def current(
    request: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer)
) -> AsyncIterator[Principal]:
    """Authenticate the bearer token and yield a DB session scoped (RLS) to that user."""
    if creds is None:
        raise _unauthorized("Not authenticated")
    try:
        claims = decode_access_token(creds.credentials)
    except jwt.ExpiredSignatureError as e:
        raise _unauthorized("Access token expired") from e
    except jwt.PyJWTError as e:
        raise _unauthorized("Invalid access token") from e

    user_id, sid = claims["sub"], claims["sid"]
    async with tenant_session(user_id) as db:
        row = (
            await db.execute(
                select(User, AuthSession.revoked)
                .join(AuthSession, AuthSession.user_id == User.id)
                .where(User.id == user_id, AuthSession.id == sid)
            )
        ).first()
        if row is None or row[1]:
            raise _unauthorized("Session has been revoked")
        request.state.user_id = user_id
        yield Principal(user=row[0], session_id=sid, db=db)


def require_csrf_header(request: Request) -> None:
    """Cookie-authenticated endpoints require a custom header. Browsers cannot attach one to a
    cross-site request without a CORS preflight, which our CORS policy refuses."""
    if request.headers.get("x-sap-csrf") != "1":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Missing CSRF header")
