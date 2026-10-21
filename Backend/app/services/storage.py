"""Encrypted dataset storage with a bounded in-memory cache of decrypted frames.

Frames are persisted as zstd-compressed Parquet, encrypted with the dataset's own data key.
Decryption + decode happens once per cache miss; hot datasets are served from an LRU bounded by
estimated memory, not entry count, so a few huge datasets cannot exhaust RAM.
"""

from __future__ import annotations

import io
import os
import threading
from collections import OrderedDict
from pathlib import Path

import polars as pl

from app.core import crypto
from app.core.config import get_keys, get_settings


def _blob_path(dataset_id: str) -> Path:
    d = get_settings().data_dir / "blobs"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{dataset_id}.sap"


def _context(dataset_id: str) -> str:
    return f"dataset:{dataset_id}"


def save_frame(dataset_id: str, df: pl.DataFrame) -> tuple[bytes, int]:
    """Encrypt and persist ``df``. Returns (wrapped data key, ciphertext size)."""
    buf = io.BytesIO()
    df.write_parquet(buf, compression="zstd", compression_level=6, statistics=True)
    dek = crypto.new_data_key()
    blob = crypto.encrypt_blob(dek, buf.getvalue(), _context(dataset_id))
    path = _blob_path(dataset_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(blob)
    os.replace(tmp, path)  # atomic: readers never see a half-written file
    cache.put(dataset_id, df)
    return crypto.wrap_key(get_keys().kek, dek, _context(dataset_id)), len(blob)


def data_key(dataset_id: str, wrapped: bytes) -> bytes:
    return crypto.unwrap_key(get_keys().kek, wrapped, _context(dataset_id))


def load_frame(dataset_id: str, wrapped: bytes) -> pl.DataFrame:
    hit = cache.get(dataset_id)
    if hit is not None:
        return hit
    dek = data_key(dataset_id, wrapped)
    plain = crypto.decrypt_blob(dek, _blob_path(dataset_id).read_bytes(), _context(dataset_id))
    df = pl.read_parquet(io.BytesIO(plain))
    cache.put(dataset_id, df)
    return df


def shred(dataset_id: str) -> None:
    """Crypto-shred: drop cache, overwrite and delete the ciphertext. The caller deletes the
    wrapped key, after which no copy of the data (including backups of the blob) is readable."""
    cache.drop(dataset_id)
    path = _blob_path(dataset_id)
    if path.exists():
        size = path.stat().st_size
        with path.open("r+b") as f:
            f.write(os.urandom(min(size, 1 << 20)))
        path.unlink()


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
            item = self._items.pop(key, None)
            if item:
                self._size -= item[1]

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"entries": len(self._items), "bytes": self._size, "hits": self.hits, "misses": self.misses}


cache = FrameCache(get_settings().frame_cache_mb * 1024 * 1024)
