from __future__ import annotations

import numpy as np
import polars as pl
import pytest
from cryptography.exceptions import InvalidTag

from app.core import crypto
from app.engine import pii
from app.engine.clean import clean
from app.engine.ingest import IngestError, read_dataset
from app.engine.timeseries import holt_forecast, mann_kendall


def _clean(text: str):
    return clean(read_dataset(text.encode(), max_decompressed=10**8).frame)


def test_messy_numbers_and_currency():
    r = _clean('amount,price\n"$1,200.50","1.234,50"\n(300),"2.000,00"\n450,"99,90"\nN/A,"10,00"\n')
    assert r.frame["amount"].to_list() == [1200.5, -300.0, 450.0, None]
    assert r.meta["amount"].unit == "currency:$"
    assert r.frame["price"].to_list() == [1234.5, 2000.0, 99.9, 10.0]  # European separators


def test_mixed_date_formats_and_identifiers():
    r = _clean('order_date,zip\n2024-01-03,02134\n01/15/2024,10001\n"Mar 05, 2024",00501\n2024-02-20,94105\n')
    assert r.frame["order_date"].dtype == pl.Date
    assert r.frame["order_date"].null_count() == 0
    assert r.frame["zip"].to_list()[0] == "02134"  # leading zeros preserved


def test_booleans_categories_duplicates():
    r = _clean("paid,region\nyes,West\nNO, west \nY,WEST\nyes,West\nn,East\n")
    assert r.frame["paid"].dtype == pl.Boolean
    assert set(r.frame["region"].unique().to_list()) == {"West", "East"}
    assert r.duplicates_removed == 2  # "Y,WEST" becomes a duplicate once normalised


def test_ingest_rejects_garbage():
    with pytest.raises(IngestError):
        read_dataset(b"\x00\x01\x02" * 1000, max_decompressed=10**6)
    with pytest.raises(IngestError):
        read_dataset(b"   ", max_decompressed=10**6)


def test_semicolon_and_latin1():
    data = "nom;ville;montant\nRené;Zürich;12,5\nAnaïs;Genève;7,25\n".encode("latin-1")
    r = clean(read_dataset(data, max_decompressed=10**6).frame)
    assert r.frame["ville"].to_list() == ["Zürich", "Genève"]
    assert r.frame["montant"].to_list() == [12.5, 7.25]


def test_pii_detection_and_masking():
    df = pl.DataFrame(
        {
            "contact": ["ann@corp.com", "bob@x.org", "c@y.io"],
            "cc": ["4111 1111 1111 1111", "5500 0000 0000 0004", "4012 8888 8888 1881"],
            "notes": ["hello", "world", "again"],
        }
    )
    findings = pii.detect(df, {"contact": "text", "cc": "identifier", "notes": "text"})
    kinds = {f["column"]: f["type"] for f in findings}
    assert kinds == {"contact": "email", "cc": "credit_card"}
    masked = pii.apply_policy(df, {"contact": "mask", "cc": "mask"}, findings, b"k" * 32)
    assert masked["contact"][0] == "a•••@c•••.com"
    assert masked["cc"][0] == "•••• 1111"
    hashed = pii.apply_policy(df, {"contact": "hash"}, findings, b"k" * 32)
    again = pii.apply_policy(df, {"contact": "hash"}, findings, b"k" * 32)
    assert hashed["contact"].to_list() == again["contact"].to_list()


def test_envelope_encryption_detects_tampering():
    dek = crypto.new_data_key()
    blob = crypto.encrypt_blob(dek, b"secret" * 1000, "dataset:1")
    assert crypto.decrypt_blob(dek, blob, "dataset:1") == b"secret" * 1000
    with pytest.raises(InvalidTag):
        crypto.decrypt_blob(dek, blob, "dataset:2")  # bound to its context
    tampered = bytearray(blob)
    tampered[-1] ^= 1
    with pytest.raises(InvalidTag):
        crypto.decrypt_blob(dek, bytes(tampered), "dataset:1")
    kek = crypto.new_data_key()
    assert crypto.unwrap_key(kek, crypto.wrap_key(kek, dek, "c"), "c") == dek


def test_trend_statistics():
    rng = np.random.default_rng(0)
    up = np.arange(40, dtype=float) + rng.normal(0, 2, 40)
    z, p = mann_kendall(up)
    assert z > 0 and p < 0.001
    _, p_flat = mann_kendall(rng.normal(0, 1, 40))
    assert p_flat > 0.01
    fc = holt_forecast(up, 6)
    assert fc and len(fc["y"]) == 6 and fc["y"][-1] > up[-5:].mean()
    assert all(lo < y < hi for lo, y, hi in zip(fc["lower"], fc["y"], fc["upper"], strict=True))
