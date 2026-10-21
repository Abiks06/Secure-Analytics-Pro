from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="sap-test-"))
os.environ.update(
    SAP_ENV="test",
    SAP_DATA_DIR=str(_tmp),
    # CI points this at PostgreSQL (as a non-superuser) to exercise Row Level Security.
    SAP_DATABASE_URL=os.environ.get("SAP_TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{(_tmp / 'test.db').as_posix()}",
    SAP_CORS_ORIGINS="http://testserver",
)
os.environ.pop("ANTHROPIC_API_KEY", None)

import httpx  # noqa: E402

from app.core import ratelimit  # noqa: E402
from app.main import app  # noqa: E402

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "messy_sales.csv"
PASSWORD = "Correct-Horse-42!"


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


_counter = {"n": 0}


async def make_user(client: httpx.AsyncClient) -> dict[str, str]:
    _counter["n"] += 1
    email = f"analyst{_counter['n']}@example.org"
    r = await client.post("/api/auth/register", json={"email": email, "password": PASSWORD, "name": "Test Analyst"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}", "email": email}


async def upload_and_wait(client: httpx.AsyncClient, headers: dict, content: bytes, name: str = "data.csv") -> dict:
    auth = {"Authorization": headers["Authorization"]}
    r = await client.post("/api/datasets", files={"file": (name, content, "text/plain")}, headers=auth)
    assert r.status_code == 202, r.text
    ds_id = r.json()["id"]
    for _ in range(300):
        d = (await client.get(f"/api/datasets/{ds_id}", headers=auth)).json()
        if d["status"] in ("ready", "failed"):
            return d
        await asyncio.sleep(0.05)
    raise AssertionError("dataset never finished processing")
