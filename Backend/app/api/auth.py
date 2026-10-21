"""Account and session endpoints. Sign-up, sign-in, password resets and refresh-token rotation
(with reuse detection) are handled by Supabase Auth directly from the browser; the engine only
verifies tokens and manages the caller's sessions through locked-down database functions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import text

from app.api.deps import Principal, client_ip, current
from app.db.session import is_postgres
from app.services import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me")
async def me(p: Principal = Depends(current)) -> dict[str, Any]:
    return {"id": p.user_id, "email": p.email, "name": p.name, "session_id": p.session_id}


@router.get("/sessions")
async def sessions(p: Principal = Depends(current)) -> list[dict[str, Any]]:
    if not is_postgres:
        return [
            {
                "id": p.session_id,
                "user_agent": "",
                "ip": "",
                "created_at": None,
                "last_used_at": None,
                "aal": "aal1",
                "current": True,
            }
        ]
    rows = (await p.db.execute(text("select * from sap.list_sessions()"))).mappings().all()
    return [{**dict(r), "id": str(r["id"]), "current": str(r["id"]) == p.session_id} for r in rows]


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(session_id: str, request: Request, p: Principal = Depends(current)) -> Response:
    if session_id == p.session_id:
        raise HTTPException(400, detail="Use sign out to end the current session.")
    if is_postgres:
        ok = (await p.db.execute(text("select sap.revoke_session(cast(:sid as uuid))"), {"sid": session_id})).scalar()
        if not ok:
            raise HTTPException(404, detail="Session not found")
    await audit.record(p.db, p.user_id, "auth.session_revoked", target=session_id, ip=client_ip(request))
    await p.db.commit()
    return Response(status_code=204)
