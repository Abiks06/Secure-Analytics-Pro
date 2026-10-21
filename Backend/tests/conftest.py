from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

# Tests run offline: tokens are minted with a local P-256 key shaped exactly like Supabase Auth's
# (ES256, kid, iss, aud=authenticated, session_id), and the engine trusts that key's JWKS.
_tmp = Path(tempfile.mkdtemp(prefix="sap-test-"))
_key = ec.generate_private_key(ec.SECP256R1())
KID = "test-key"
ISSUER_BASE = "https://test-project.supabase.co"
_jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(_key.public_key()))
_jwk.update(kid=KID, alg="ES256", use="sig")

os.environ.update(
    SAP_ENV="test",
    SAP_DATA_DIR=str(_tmp),
    SAP_DATABASE_URL=f"sqlite+aiosqlite:///{(_tmp / 'test.db').as_posix()}",
    SAP_CORS_ORIGINS="http://testserver",
    SAP_SUPABASE_URL=ISSUER_BASE,
    SAP_SUPABASE_JWKS_JSON=json.dumps({"keys": [_jwk]}),
    SAP_STORAGE_BACKEND="local",
)
os.environ.pop("ANTHROPIC_API_KEY", None)

import httpx  # noqa: E402

from app.core import ratelimit  # noqa: E402
from app.main import app  # noqa: E402

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "messy_sales.csv"


def mint(sub: str | None = None, *, key=None, kid: str = KID, ttl: int = 3600, **overrides) -> str:
    now = int(time.time())
    sub = sub or str(uuid.uuid4())
    claims = {
        "iss": f"{ISSUER_BASE}/auth/v1",
        "aud": "authenticated",
        "sub": sub,
        "email": f"user-{sub[:8]}@example.test",
        "role": "authenticated",
        "aal": "aal1",
        "session_id": str(uuid.uuid4()),
        "is_anonymous": False,
        "user_metadata": {"name": "Test Analyst"},
        "iat": now,
        "exp": now + ttl,
    }
    claims.update(overrides)
    return jwt.encode(claims, key or _key, algorithm="ES256", headers={"kid": kid})


@pytest.fixture(scope="session")
async def client():
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c
    shutil.rmtree(_tmp, ignore_errors=True)


@pytest.fixture(autouse=True)
def _reset_limits():
    ratelimit.reset()


async def make_user(client: httpx.AsyncClient) -> dict[str, str]:
    token = mint()
    return {"Authorization": f"Bearer {token}"}


async def upload_and_wait(client: httpx.AsyncClient, headers: dict, content: bytes, name: str = "data.csv") -> dict:
    r = await client.post("/api/datasets", files={"file": (name, content, "text/plain")}, headers=headers)
    assert r.status_code == 202, r.text
    ds_id = r.json()["id"]
    for _ in range(300):
        d = (await client.get(f"/api/datasets/{ds_id}", headers=headers)).json()
        if d["status"] in ("ready", "failed"):
            return d
        await asyncio.sleep(0.05)
    raise AssertionError("dataset never finished processing")
