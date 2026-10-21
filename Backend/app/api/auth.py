"""Authentication: registration, login with lockout, rotating refresh tokens, session management."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update

from app.api.deps import Principal, client_ip, current, require_csrf_header
from app.core import ratelimit, security
from app.core.config import get_settings
from app.db.models import AuthSession, User
from app.db.session import tenant_session
from app.services import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE = "sap_refresh"
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
MAX_FAILS = 5


class Credentials(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL.match(v):
            raise ValueError("Enter a valid email address")
        return v


class Registration(Credentials):
    name: str = Field(min_length=1, max_length=120)


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    expires_at: int
    user: UserOut


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


def _user_out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, name=u.name, created_at=u.created_at)


def _set_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        COOKIE,
        token,
        max_age=s.refresh_token_ttl_s,
        httponly=True,
        secure=s.cookie_secure,
        samesite="strict",
        path="/api/auth",
    )


async def _start_session(db, user: User, request: Request, response: Response) -> TokenOut:
    refresh, digest = security.new_refresh_token()
    sess = AuthSession(
        user_id=user.id,
        refresh_hash=digest,
        user_agent=(request.headers.get("user-agent") or "")[:300],
        ip=client_ip(request),
        expires_at=datetime.now(UTC) + timedelta(seconds=get_settings().refresh_token_ttl_s),
    )
    db.add(sess)
    await db.flush()
    access, exp = security.create_access_token(user.id, sess.id)
    _set_cookie(response, refresh)
    return TokenOut(access_token=access, expires_at=exp, user=_user_out(user))


@router.post(
    "/register", response_model=TokenOut, status_code=201, dependencies=[Depends(ratelimit.limit(ratelimit.AUTH))]
)
async def register(body: Registration, request: Request, response: Response) -> TokenOut:
    problems = security.password_problems(body.password, body.email)
    if problems:
        raise HTTPException(422, detail="Password needs " + "; ".join(problems) + ".")
    async with tenant_session(system=True) as db:
        if (await db.execute(select(User.id).where(User.email == body.email))).first():
            raise HTTPException(409, detail="An account with this email already exists.")
        user = User(email=body.email, name=body.name.strip(), password_hash=security.hash_password(body.password))
        db.add(user)
        await db.flush()
        out = await _start_session(db, user, request, response)
        await audit.record(db, user.id, "auth.register", ip=client_ip(request))
        await db.commit()
    return out


@router.post("/login", response_model=TokenOut, dependencies=[Depends(ratelimit.limit(ratelimit.AUTH))])
async def login(body: Credentials, request: Request, response: Response) -> TokenOut:
    generic = HTTPException(401, detail="Incorrect email or password.")
    async with tenant_session(system=True) as db:
        user = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
        now = datetime.now(UTC)
        if user and _aware(user.locked_until) and _aware(user.locked_until) > now:
            wait = int((_aware(user.locked_until) - now).total_seconds() // 60) + 1
            raise HTTPException(423, detail=f"Too many failed attempts. Account locked for {wait} more minute(s).")
        if not security.verify_password(user.password_hash if user else None, body.password):
            if user:
                user.failed_logins += 1
                if user.failed_logins >= MAX_FAILS:
                    minutes = min(60, 2 ** (user.failed_logins - MAX_FAILS))
                    user.locked_until = now + timedelta(minutes=minutes)
                await audit.record(
                    db, user.id, "auth.login_failed", ip=client_ip(request), detail={"attempt": user.failed_logins}
                )
                await db.commit()
            raise generic
        if security.needs_rehash(user.password_hash):
            user.password_hash = security.hash_password(body.password)
        user.failed_logins, user.locked_until, user.last_login_at = 0, None, now
        out = await _start_session(db, user, request, response)
        await audit.record(
            db,
            user.id,
            "auth.login",
            ip=client_ip(request),
            detail={"ua": (request.headers.get("user-agent") or "")[:80]},
        )
        await db.commit()
    return out


@router.post(
    "/refresh",
    response_model=TokenOut,
    dependencies=[Depends(require_csrf_header), Depends(ratelimit.limit(ratelimit.AUTH))],
)
async def refresh(request: Request, response: Response) -> TokenOut:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, detail="No refresh token")
    digest = security.hash_refresh_token(token)
    async with tenant_session(system=True) as db:
        sess = (await db.execute(select(AuthSession).where(AuthSession.refresh_hash == digest))).scalar_one_or_none()
        if sess is None:
            reused = (
                await db.execute(select(AuthSession).where(AuthSession.previous_hash == digest))
            ).scalar_one_or_none()
            if reused and not reused.revoked:
                # A rotated-out token came back: someone else holds a copy. Kill the session.
                reused.revoked = True
                await audit.record(
                    db, reused.user_id, "auth.refresh_reuse_detected", target=reused.id, ip=client_ip(request)
                )
                await db.commit()
            response.delete_cookie(COOKIE, path="/api/auth")
            raise HTTPException(401, detail="Refresh token is no longer valid")
        if sess.revoked or _aware(sess.expires_at) < datetime.now(UTC):
            raise HTTPException(401, detail="Session expired")
        user = await db.get(User, sess.user_id)
        new_token, new_digest = security.new_refresh_token()
        sess.previous_hash, sess.refresh_hash = sess.refresh_hash, new_digest
        sess.last_used_at = datetime.now(UTC)
        access, exp = security.create_access_token(sess.user_id, sess.id)
        await db.commit()
    _set_cookie(response, new_token)
    return TokenOut(access_token=access, expires_at=exp, user=_user_out(user))


@router.post("/logout", status_code=204, dependencies=[Depends(require_csrf_header)])
async def logout(request: Request, response: Response) -> Response:
    token = request.cookies.get(COOKIE)
    if token:
        async with tenant_session(system=True) as db:
            sess = (
                await db.execute(
                    select(AuthSession).where(AuthSession.refresh_hash == security.hash_refresh_token(token))
                )
            ).scalar_one_or_none()
            if sess:
                sess.revoked = True
                await audit.record(db, sess.user_id, "auth.logout", target=sess.id, ip=client_ip(request))
                await db.commit()
    response.delete_cookie(COOKIE, path="/api/auth")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserOut)
async def me(p: Principal = Depends(current)) -> UserOut:
    return _user_out(p.user)


@router.get("/sessions")
async def sessions(p: Principal = Depends(current)) -> list[dict]:
    rows = (
        (
            await p.db.execute(
                select(AuthSession)
                .where(AuthSession.user_id == p.user.id, AuthSession.revoked.is_(False))
                .order_by(AuthSession.last_used_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": s.id,
            "user_agent": s.user_agent,
            "ip": s.ip,
            "created_at": s.created_at,
            "last_used_at": s.last_used_at,
            "current": s.id == p.session_id,
        }
        for s in rows
    ]


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(session_id: str, request: Request, p: Principal = Depends(current)) -> Response:
    result = await p.db.execute(
        update(AuthSession).where(AuthSession.id == session_id, AuthSession.user_id == p.user.id).values(revoked=True)
    )
    if not result.rowcount:
        raise HTTPException(404, detail="Session not found")
    await audit.record(p.db, p.user.id, "auth.session_revoked", target=session_id, ip=client_ip(request))
    await p.db.commit()
    return Response(status_code=204)
