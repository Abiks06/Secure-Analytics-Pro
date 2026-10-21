from __future__ import annotations

import gzip
import json

from sqlalchemy import update

from app.db.models import AuditEvent
from app.db.session import tenant_session
from tests.conftest import PASSWORD, SAMPLE, make_user, upload_and_wait

CSRF = {"X-SAP-CSRF": "1"}


async def test_security_headers(client):
    r = await client.get("/api/health")
    assert r.json() == {"status": "ok"}
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"


async def test_weak_password_rejected(client):
    r = await client.post("/api/auth/register", json={"email": "weak@example.org", "password": "password", "name": "W"})
    assert r.status_code == 422
    assert "at least 10 characters" in r.json()["detail"]


async def test_requires_auth(client):
    assert (await client.get("/api/datasets")).status_code == 401
    bad = {"Authorization": "Bearer not-a-jwt"}
    assert (await client.get("/api/datasets", headers=bad)).status_code == 401


async def test_login_lockout(client):
    h = await make_user(client)
    for _ in range(5):
        r = await client.post("/api/auth/login", json={"email": h["email"], "password": "Wrong-password-1"})
        assert r.status_code == 401
    r = await client.post("/api/auth/login", json={"email": h["email"], "password": PASSWORD})
    assert r.status_code == 423


async def test_refresh_rotation_and_reuse_detection(client):
    h = await make_user(client)
    first = client.cookies.get("sap_refresh")
    assert first
    assert (await client.post("/api/auth/refresh")).status_code == 403  # CSRF header required
    r = await client.post("/api/auth/refresh", headers=CSRF)
    assert r.status_code == 200
    assert client.cookies.get("sap_refresh") != first
    # Replay the old token: the whole session must be revoked.
    client.cookies.set("sap_refresh", first, path="/api/auth")
    assert (await client.post("/api/auth/refresh", headers=CSRF)).status_code == 401
    me = await client.get("/api/auth/me", headers={"Authorization": h["Authorization"]})
    assert me.status_code == 401, "access tokens of a revoked session must stop working"
    client.cookies.clear()


async def test_full_pipeline_and_privacy(client):
    h = await make_user(client)
    auth = {"Authorization": h["Authorization"]}
    d = await upload_and_wait(client, h, SAMPLE.read_bytes(), "messy_sales.csv")
    assert d["status"] == "ready", d
    assert d["row_count"] == 5000  # 50 exact duplicates removed
    assert 0 < d["quality_score"] <= 100

    rep = (await client.get(f"/api/datasets/{d['id']}/report", headers=auth)).json()["report"]
    kinds = {c["name"]: c["kind"] for c in rep["columns"]}
    assert kinds["Order Date"] == "datetime"
    assert kinds["Revenue"] == "numeric"
    assert kinds["Returned"] == "boolean"
    pii = {f["column"]: f["type"] for f in rep["privacy"]["findings"]}
    assert pii["Card Number"] == "credit_card" and pii["Email"] == "email"
    assert any(i["kind"] == "trend" for i in rep["insights"])
    assert rep["timeseries"]["series"][0]["forecast"]["y"]

    rows = (await client.get(f"/api/datasets/{d['id']}/rows?limit=5", headers=auth)).json()
    cols = [c["name"] for c in rows["columns"]]
    card = rows["rows"][0][cols.index("Card Number")]
    email = rows["rows"][0][cols.index("Email")]
    assert card == "[REDACTED]"
    assert "•••@" in email

    # Pseudonymise instead: deterministic, joinable tokens.
    r = await client.put(f"/api/datasets/{d['id']}/privacy", json={"policy": {"Email": "hash"}}, headers=auth)
    assert r.status_code == 200
    rows = (await client.get(f"/api/datasets/{d['id']}/rows?limit=5", headers=auth)).json()
    assert rows["rows"][0][cols.index("Email")].startswith("anon_")
    assert rows["rows"][0][cols.index("Card Number")] != "[REDACTED]"  # policy replaced wholesale


async def test_query_sandbox(client):
    h = await make_user(client)
    auth = {"Authorization": h["Authorization"]}
    d = await upload_and_wait(client, h, b"region,sales\nWest,10\nEast,5\nWest,7\n")
    url = f"/api/datasets/{d['id']}/query"
    r = await client.post(
        url, json={"sql": "select region, sum(sales) s from data group by 1 order by 2 desc"}, headers=auth
    )
    assert r.status_code == 200, r.text
    assert r.json()["rows"][0] == ["West", 17]
    for bad in [
        "select * from read_csv_auto('/etc/passwd')",
        "drop table data",
        "select 1; select 2",
        "copy data to 'x.csv'",
    ]:
        r = await client.post(url, json={"sql": bad}, headers=auth)
        assert r.status_code == 400, bad


async def test_tenant_isolation(client):
    a = await make_user(client)
    b = await make_user(client)
    d = await upload_and_wait(client, a, b"x,y\n1,2\n3,4\n")
    other = {"Authorization": b["Authorization"]}
    assert (await client.get(f"/api/datasets/{d['id']}", headers=other)).status_code == 404
    assert (await client.get(f"/api/datasets/{d['id']}/rows", headers=other)).status_code == 404
    assert (await client.delete(f"/api/datasets/{d['id']}", headers=other)).status_code == 404
    assert (await client.get("/api/datasets", headers=other)).json() == []


async def test_formats_json_ndjson_gzip(client):
    h = await make_user(client)
    nested = json.dumps(
        {
            "data": [
                {"id": i, "user": {"name": f"u{i}", "plan": "pro"}, "tags": ["a", "b"], "amount": i * 1.5}
                for i in range(30)
            ]
        }
    )
    d = await upload_and_wait(client, h, nested.encode(), "api.json")
    assert d["status"] == "ready" and d["source_format"] == "json"
    rep = (await client.get(f"/api/datasets/{d['id']}/report", headers={"Authorization": h["Authorization"]})).json()[
        "report"
    ]
    assert "user.name" in {c["name"] for c in rep["columns"]}

    nd = "\n".join(json.dumps({"k": i, "v": i * 2}) for i in range(25)).encode()
    d = await upload_and_wait(client, h, gzip.compress(nd), "events.ndjson.gz")
    assert d["status"] == "ready" and d["source_format"] == "ndjson" and d["row_count"] == 25


async def test_rejects_binary(client):
    h = await make_user(client)
    d = await upload_and_wait(client, h, b"\x7fELF" + bytes(2000), "evil.csv")
    assert d["status"] == "failed"
    assert "binary" in d["error"].lower()


async def test_export_neutralises_formulas(client):
    h = await make_user(client)
    auth = {"Authorization": h["Authorization"]}
    d = await upload_and_wait(client, h, b'name,note\nann,"=HYPERLINK(""http://x"")"\nbob,ok\n')
    r = await client.get(f"/api/datasets/{d['id']}/export?format=csv", headers=auth)
    assert r.status_code == 200
    assert "'=HYPERLINK" in r.text


async def test_audit_chain_detects_tampering(client):
    h = await make_user(client)
    auth = {"Authorization": h["Authorization"]}
    await upload_and_wait(client, h, b"a,b\n1,2\n")
    v = (await client.get("/api/audit/verify", headers=auth)).json()
    assert v["valid"] and v["events"] >= 3
    log = (await client.get("/api/audit", headers=auth)).json()
    owner = (await client.get("/api/auth/me", headers=auth)).json()["id"]
    async with tenant_session(owner) as s:
        await s.execute(
            update(AuditEvent).where(AuditEvent.owner_id == owner, AuditEvent.seq == 2).values(ip="6.6.6.6")
        )
        await s.commit()
    v = (await client.get("/api/audit/verify", headers=auth)).json()
    assert not v["valid"] and v["broken_at"] == 2
    assert log[0]["seq"] > log[-1]["seq"]


async def test_delete_crypto_shreds(client):
    from app.services import storage

    h = await make_user(client)
    auth = {"Authorization": h["Authorization"]}
    d = await upload_and_wait(client, h, b"a,b\n1,2\n")
    path = storage._blob_path(d["id"])
    assert path.exists() and b"a,b" not in path.read_bytes()
    assert (await client.delete(f"/api/datasets/{d['id']}", headers=auth)).status_code == 204
    assert not path.exists()
    assert (await client.get(f"/api/datasets/{d['id']}", headers=auth)).status_code == 404


async def test_postgres_row_level_security_blocks_unscoped_reads(client):
    """Even a query with no owner filter only sees the scoped tenant's rows (PostgreSQL only)."""
    import pytest
    from sqlalchemy import func, select

    from app.db.models import Dataset
    from app.db.session import engine

    if engine.dialect.name != "postgresql":
        pytest.skip("RLS is enforced by PostgreSQL; SQLite relies on application filters")
    a = await make_user(client)
    b = await make_user(client)
    await upload_and_wait(client, a, b"x,y\n1,2\n")
    b_id = (await client.get("/api/auth/me", headers={"Authorization": b["Authorization"]})).json()["id"]
    async with tenant_session(b_id) as s:
        visible = (await s.execute(select(func.count()).select_from(Dataset))).scalar_one()
    assert visible == 0
    async with tenant_session(None) as s:
        assert (await s.execute(select(func.count()).select_from(Dataset))).scalar_one() == 0
