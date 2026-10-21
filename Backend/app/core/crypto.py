"""Envelope encryption for data at rest.

Every dataset gets its own random 256-bit data key (DEK). The DEK encrypts the dataset with
AES-256-GCM and is itself wrapped by the master key-encryption key (KEK). Deleting the
wrapped DEK makes the ciphertext unrecoverable (crypto-shredding), and rotating the KEK only
requires re-wrapping the small DEKs, never re-encrypting the data.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import struct

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_MAGIC = b"SAP1"
_CHUNK = 4 * 1024 * 1024


def new_data_key() -> bytes:
    return AESGCM.generate_key(bit_length=256)


def wrap_key(kek: bytes, dek: bytes, context: str) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(kek).encrypt(nonce, dek, context.encode())


def unwrap_key(kek: bytes, wrapped: bytes, context: str) -> bytes:
    return AESGCM(kek).decrypt(wrapped[:12], wrapped[12:], context.encode())


def encrypt_blob(dek: bytes, plaintext: bytes, context: str) -> bytes:
    """Chunked AES-GCM: each 4 MiB chunk has its own nonce and authenticates its index and the
    final-chunk flag, so chunks cannot be reordered, dropped or truncated undetected."""
    aead = AESGCM(dek)
    out = bytearray(_MAGIC)
    total = max(1, -(-len(plaintext) // _CHUNK))
    for i in range(total):
        chunk = plaintext[i * _CHUNK : (i + 1) * _CHUNK]
        nonce = os.urandom(12)
        aad = context.encode() + struct.pack(">I?", i, i == total - 1)
        ct = aead.encrypt(nonce, chunk, aad)
        out += struct.pack(">I", len(ct)) + nonce + ct
    return bytes(out)


def decrypt_blob(dek: bytes, blob: bytes, context: str) -> bytes:
    if blob[:4] != _MAGIC:
        raise ValueError("Unknown ciphertext format")
    aead = AESGCM(dek)
    pos, i, parts = 4, 0, []
    while pos < len(blob):
        (n,) = struct.unpack_from(">I", blob, pos)
        nonce = blob[pos + 4 : pos + 16]
        ct = blob[pos + 16 : pos + 16 + n]
        pos += 16 + n
        aad = context.encode() + struct.pack(">I?", i, pos >= len(blob))
        parts.append(aead.decrypt(nonce, ct, aad))
        i += 1
    return b"".join(parts)


def pseudonym_key(dek: bytes) -> bytes:
    """Derive a per-dataset HMAC key for deterministic pseudonymisation of PII values."""
    return hmac.new(dek, b"sap/pseudonym/v1", hashlib.sha256).digest()
