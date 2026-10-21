"""Password hashing (Argon2id) and token handling (EdDSA access JWTs, opaque refresh tokens)."""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_keys, get_settings

_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)
# Verified against when the account does not exist, so response timing does not reveal
# which emails are registered.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash or _DUMMY_HASH, password) and stored_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)


def password_problems(password: str, email: str) -> list[str]:
    problems = []
    if len(password) < 10:
        problems.append("at least 10 characters")
    if len(password) > 256:
        problems.append("at most 256 characters")
    classes = sum(
        [
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        ]
    )
    if classes < 3:
        problems.append("at least three of: lowercase, uppercase, digits, symbols")
    local = email.split("@")[0].lower()
    if len(local) >= 4 and local in password.lower():
        problems.append("must not contain your email name")
    return problems


def create_access_token(user_id: str, session_id: str) -> tuple[str, int]:
    settings = get_settings()
    now = int(time.time())
    exp = now + settings.access_token_ttl_s
    token = jwt.encode(
        {
            "sub": user_id,
            "sid": session_id,
            "iss": settings.jwt_issuer,
            "aud": "sap-api",
            "iat": now,
            "nbf": now,
            "exp": exp,
            "jti": uuid.uuid4().hex,
        },
        get_keys().jwt_private,
        algorithm="EdDSA",
    )
    return token, exp


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    return jwt.decode(
        token,
        get_keys().jwt_public,
        algorithms=["EdDSA"],
        audience="sap-api",
        issuer=settings.jwt_issuer,
        options={"require": ["exp", "iat", "sub", "sid"]},
        leeway=10,
    )


def new_refresh_token() -> tuple[str, str]:
    """Return (token, sha256 digest). Only the digest is stored server-side."""
    token = secrets.token_urlsafe(48)
    return token, hash_refresh_token(token)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
