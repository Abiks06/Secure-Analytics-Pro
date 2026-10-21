from __future__ import annotations

import gzip
import json

from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import update

from app.db.models import AuditEvent
from app.db.session import claims_for, tenant_session
from tests.conftest import SAMPLE, make_user, mint, upload_and_wait


async def test_security_headers(client):
    r = await client.get("/api/health")
    assert r.json() == {"status": "ok"}
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"


async def test_requires_valid_supabase_token(client):
    assert (await client.get("/api/datasets")).status_code == 401
    bad = {
        "garbage": "not-a-jwt",
        "forged (unknown key)": mint(key=ec.generate_private_key(ec.SECP256R1())),
        "forged (unknown kid)": mint(kid="other"),
        "expired": mint(ttl=-120),
        "wrong audience": mint(aud="anon"),
        "wrong issuer": mint(iss="https://evil.example/auth/v1"),
        "anonymous user": mint(is_anonymous=True),
        "service role": mint(role="service_role"),
    }
    for label, token in bad.items():
        r = await client.get("/api/datasets", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401, label


async def test_me_and_sign_in_is_audited(client):
    h = await make_user(client)
    me = (await client.get("/api/auth/me", headers=h)).json()
    assert me["name"] == "Test Analyst"
    log = (await client.get("/api/audit", headers=h)).json()
    assert [e["action"] for e in log] == ["auth.session_started"]


async def test_full_pipeline_and_privacy(client):
    h = await make_user(client)
    d = await upload_and_wait(client, h, SAMPLE.read_bytes(), "messy_sales.csv")
    assert d["status"] == "ready", d
    assert d["row_count"] == 5000  # 50 exact duplicates removed
    assert 0 < d["quality_score"] <= 100

    rep = (await client.get(f"/api/datasets/{d['id']}/report", headers=h)).json()["report"]
    kinds = {c["name"]: c["kind"] for c in rep["columns"]}
    assert kinds["Order Date"] == "datetime"
    assert kinds["Revenue"] == "numeric"
    assert kinds["Returned"] == "boolean"
    pii = {f["column"]: f["type"] for f in rep["privacy"]["findings"]}
    assert pii["Card Number"] == "credit_card" and pii["Email"] == "email"
    assert any(i["kind"] == "trend" for i in rep["insights"])
    assert rep["timeseries"]["series"][0]["forecast"]["y"]
    # Statistics in the report respect the privacy policy too.
    cols = {c["name"]: c for c in rep["columns"]}
    assert all(t["value"] == "[REDACTED]" for t in cols["Card Number"].get("top", []))
    assert all("•••" in str(t["value"]) for t in cols["Customer Name"].get("top", []))

    rows = (await client.get(f"/api/datasets/{d['id']}/rows?limit=5", headers=h)).json()
    names = [c["name"] for c in rows["columns"]]
    assert rows["rows"][0][names.index("Card Number")] == "[REDACTED]"
    assert "•••@" in rows["rows"][0][names.index("Email")]

    # Pseudonymise instead: deterministic, joinable tokens.
    r = await client.put(f"/api/datasets/{d['id']}/privacy", json={"policy": {"Email": "hash"}}, headers=h)
    assert r.status_code == 200
    rows = (await client.get(f"/api/datasets/{d['id']}/rows?limit=5", headers=h)).json()
    assert rows["rows"][0][names.index("Email")].startswith("anon_")
    assert rows["rows"][0][names.index("Card Number")] != "[REDACTED]"  # policy replaced wholesale


async def test_query_sandbox(client):
    h = await make_user(client)
    d = await upload_and_wait(client, h, b"region,sales\nWest,10\nEast,5\nWest,7\n")
    url = f"/api/datasets/{d['id']}/query"
    r = await client.post(
        url, json={"sql": "select region, sum(sales) s from data group by 1 order by 2 desc"}, headers=h
    )
    assert r.status_code == 200, r.text
    assert r.json()["rows"][0] == ["West", 17]
    for bad in [
        "select * from read_csv_auto('/etc/passwd')",
        "drop table data",
        "select 1; select 2",
        "copy data to 'x.csv'",
    ]:
        r = await client.post(url, json={"sql": bad}, headers=h)
        assert r.status_code == 400, bad


async def test_tenant_isolation(client):
    a = await make_user(client)
    b = await make_user(client)
    d = await upload_and_wait(client, a, b"x,y\n1,2\n3,4\n")
    assert (await client.get(f"/api/datasets/{d['id']}", headers=b)).status_code == 404
    assert (await client.get(f"/api/datasets/{d['id']}/rows", headers=b)).status_code == 404
    assert (await client.delete(f"/api/datasets/{d['id']}", headers=b)).status_code == 404
    assert (await client.get("/api/datasets", headers=b)).json() == []


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
    rep = (await client.get(f"/api/datasets/{d['id']}/report", headers=h)).json()["report"]
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
    d = await upload_and_wait(client, h, b'name,note\nann,"=HYPERLINK(""http://x"")"\nbob,ok\n')
    r = await client.get(f"/api/datasets/{d['id']}/export?format=csv", headers=h)
    assert r.status_code == 200
    assert "'=HYPERLINK" in r.text


async def test_audit_chain_detects_tampering(client):
    h = await make_user(client)
    await upload_and_wait(client, h, b"a,b\n1,2\n")
    v = (await client.get("/api/audit/verify", headers=h)).json()
    assert v["valid"] and v["events"] >= 3
    owner = (await client.get("/api/auth/me", headers=h)).json()["id"]
    # On Supabase this UPDATE is refused outright (append-only trigger + no UPDATE grant);
    # the hash chain is the second line of defence, simulated here on SQLite.
    async with tenant_session(claims_for(owner)) as s:
        await s.execute(
            update(AuditEvent).where(AuditEvent.owner_id == owner, AuditEvent.seq == 2).values(ip="6.6.6.6")
        )
        await s.commit()
    v = (await client.get("/api/audit/verify", headers=h)).json()
    assert not v["valid"] and v["broken_at"] == 2


async def test_delete_crypto_shreds(client):
    from app.services import storage

    h = await make_user(client)
    owner = (await client.get("/api/auth/me", headers=h)).json()["id"]
    d = await upload_and_wait(client, h, b"a,b\n1,2\n")
    path = storage._local_file(storage.object_path(owner, d["id"]))
    assert path.exists() and b"a,b" not in path.read_bytes()
    assert (await client.delete(f"/api/datasets/{d['id']}", headers=h)).status_code == 204
    assert not path.exists()
    assert (await client.get(f"/api/datasets/{d['id']}", headers=h)).status_code == 404


async def test_upload_rejects_wrong_key_and_double_processing(client):
    import base64
    import secrets

    from app.core import crypto
    from app.services import storage

    h = await make_user(client)
    created = (await client.post("/api/datasets", json={"name": "a.csv", "size_bytes": 8}, headers=h)).json()
    blob = crypto.encrypt_blob(secrets.token_bytes(32), b"a,b\n1,2\n", created["upload_context"])
    storage.put_raw(created["upload_path"], blob, "t")
    wrong = base64.b64encode(secrets.token_bytes(32)).decode()
    r = await client.post(f"/api/datasets/{created['id']}/process", json={"key": wrong}, headers=h)
    assert '"status": "failed"' in r.text and "decrypted" in r.text
    assert not storage._local_file(created["upload_path"]).exists()
    # A dataset can only be processed once.
    r = await client.post(f"/api/datasets/{created['id']}/process", json={"key": wrong}, headers=h)
    assert r.status_code == 409


async def test_upload_size_limit(client):
    h = await make_user(client)
    r = await client.post("/api/datasets", json={"name": "big.csv", "size_bytes": 10**10}, headers=h)
    assert r.status_code == 413
