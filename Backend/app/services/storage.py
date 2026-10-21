"""Encrypted dataset storage with a bounded in-memory cache of decrypted frames.

Frames are persisted as zstd-compressed Parquet, encrypted with the dataset's own data key, in
Supabase Storage (private `datasets` bucket, one folder per user). Uploads and downloads use the
caller's own access token, so Storage's RLS policies apply and the server never needs the
service-role key. Only ciphertext ever reaches Storage. A local-disk backend is used offline.

Decryption + decode happens once per cache miss; hot datasets are served from an LRU bounded by
estimated memory, not entry count, so a few huge datasets cannot exhaust RAM.
"""

from __future__ import annotations

import io
import os
import threading
from collections import OrderedDict
from pathlib import Path

import httpx
import polars as pl

from app.core import crypto
from app.core.config import get_keys, get_settings

BUCKET = "datasets"


class StorageError(RuntimeError):
    pass


def object_path(owner_id: str, dataset_id: str) -> str:
    return f"{owner_id}/{dataset_id}.sap"


def _context(dataset_id: str) -> str:
    return f"dataset:{dataset_id}"


# --- backends --------------------------------------------------------------------------------


def _local_file(path: str) -> Path:
    base = (get_settings().data_dir / "blobs").resolve()
    p = (base / path).resolve()
    if base not in p.parents:
        raise StorageError("Invalid object path")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _headers(token: str) -> dict[str, str]:
    s = get_settings()
    return {"Authorization": f"Bearer {token}", "apikey": s.supabase_publishable_key or ""}


def _put(path: str, blob: bytes, token: str) -> None:
    s = get_settings()
    if s.blob_backend == "local":
        f = _local_file(path)
        tmp = f.with_suffix(".tmp")
        tmp.write_bytes(blob)
        os.replace(tmp, f)  # atomic: readers never see a half-written file
        return
    r = httpx.post(
        f"{s.supabase_url}/storage/v1/object/{BUCKET}/{path}",
        content=blob,
        headers={**_headers(token), "Content-Type": "application/octet-stream", "x-upsert": "true"},
        timeout=120,
    )
    if r.status_code >= 300:
        raise StorageError(f"Storage upload failed ({r.status_code})")


def _get(path: str, token: str) -> bytes:
    s = get_settings()
    if s.blob_backend == "local":
        return _local_file(path).read_bytes()
    r = httpx.get(
        f"{s.supabase_url}/storage/v1/object/authenticated/{BUCKET}/{path}", headers=_headers(token), timeout=120
    )
    if r.status_code >= 300:
        raise StorageError(f"Storage download failed ({r.status_code})")
    return r.content


def _delete(path: str, token: str) -> None:
    s = get_settings()
    if s.blob_backend == "local":
        f = _local_file(path)
        if f.exists():
            with f.open("r+b") as fh:
                fh.write(os.urandom(min(f.stat().st_size, 1 << 20)))
            f.unlink()
        return
    r = httpx.request(
        "DELETE",
        f"{s.supabase_url}/storage/v1/object/{BUCKET}",
        json={"prefixes": [path]},
        headers=_headers(token),
        timeout=30,
    )
    if r.status_code >= 300:
        raise StorageError(f"Storage delete failed ({r.status_code})")


# --- public API ------------------------------------------------------------------------------


def save_frame(owner_id: str, dataset_id: str, df: pl.DataFrame, token: str) -> tuple[bytes, int, str]:
    """Encrypt and persist ``df``. Returns (wrapped data key, ciphertext size, object path)."""
    buf = io.BytesIO()
    df.write_parquet(buf, compression="zstd", compression_level=6, statistics=True)
    dek = crypto.new_data_key()
    blob = crypto.encrypt_blob(dek, buf.getvalue(), _context(dataset_id))
    path = object_path(owner_id, dataset_id)
    _put(path, blob, token)
    cache.put(dataset_id, df)
    return crypto.wrap_key(get_keys().kek, dek, _context(dataset_id)), len(blob), path


def data_key(dataset_id: str, wrapped: bytes) -> bytes:
    return crypto.unwrap_key(get_keys().kek, wrapped, _context(dataset_id))


def load_frame(dataset_id: str, wrapped: bytes, path: str, token: str) -> pl.DataFrame:
    hit = cache.get(dataset_id)
    if hit is not None:
        return hit
    dek = data_key(dataset_id, wrapped)
    plain = crypto.decrypt_blob(dek, _get(path, token), _context(dataset_id))
    df = pl.read_parquet(io.BytesIO(plain))
    cache.put(dataset_id, df)
    return df


def shred(dataset_id: str, path: str | None, token: str) -> None:
    """Crypto-shred: drop the cache and delete the ciphertext. The caller deletes the wrapped
    key, after which no copy of the data (including Storage backups) is readable."""
    cache.drop(dataset_id)
    if path:
        _delete(path, token)


class FrameCache:
    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self._items: OrderedDict[str, tuple[pl.DataFrame, int]] = OrderedDict()
        self._size = 0
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> pl.DataFrame | None:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                self.misses += 1
                return None
            self._items.move_to_end(key)
            self.hits += 1
            return item[0]

    def put(self, key: str, df: pl.DataFrame) -> None:
        size = int(df.estimated_size())
        if size > self.max_bytes:
            return
        with self._lock:
            if key in self._items:
                self._size -= self._items.pop(key)[1]
            self._items[key] = (df, size)
            self._size += size
            while self._size > self.max_bytes and self._items:
                _, (_, s) = self._items.popitem(last=False)
                self._size -= s

    def drop(self, key: str) -> None:
        with self._lock:
            for k in [k for k in self._items if k == key or k.startswith(f"{key}:")]:
                self._size -= self._items.pop(k)[1]

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"entries": len(self._items), "bytes": self._size, "hits": self.hits, "misses": self.misses}


cache = FrameCache(get_settings().frame_cache_mb * 1024 * 1024)
