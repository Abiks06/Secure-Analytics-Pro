"""Verification of Supabase Auth access tokens.

The project signs tokens with an asymmetric key (ES256), so the engine verifies them with the
public JWKS and never holds a signing secret. Beyond the signature we pin the algorithm,
issuer and audience, require the claims we rely on, and refuse anonymous sessions.
"""

from __future__ import annotations

import json
from functools import lru_cache

import jwt

from app.core.config import get_settings

ALGORITHMS = ["ES256", "RS256"]


class TokenError(Exception):
    pass


@lru_cache
def _jwk_client() -> jwt.PyJWKClient | None:
    s = get_settings()
    if s.supabase_jwks_json:
        return None
    return jwt.PyJWKClient(f"{s.jwt_issuer}/.well-known/jwks.json", cache_keys=True, lifespan=600, timeout=10)


@lru_cache
def _static_jwks() -> jwt.PyJWKSet | None:
    raw = get_settings().supabase_jwks_json
    return jwt.PyJWKSet.from_dict(json.loads(raw)) if raw else None


def _signing_key(token: str):
    static = _static_jwks()
    if static is not None:
        kid = jwt.get_unverified_header(token).get("kid")
        for key in static.keys:
            if key.key_id == kid:
                return key.key
        raise TokenError("Unknown signing key")
    try:
        return _jwk_client().get_signing_key_from_jwt(token).key  # type: ignore[union-attr]
    except jwt.PyJWKClientError as e:
        raise TokenError("Could not resolve the token's signing key") from e


def verify_access_token(token: str) -> dict:
    """Return the verified claims, or raise ``TokenError`` / ``jwt.ExpiredSignatureError``."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:
        raise TokenError("Malformed token") from e
    if header.get("alg") not in ALGORITHMS:
        raise TokenError("Unexpected signing algorithm")
    claims = jwt.decode(
        token,
        _signing_key(token),
        algorithms=ALGORITHMS,
        audience="authenticated",
        issuer=get_settings().jwt_issuer,
        options={"require": ["exp", "iat", "sub", "session_id"]},
        leeway=10,
    )
    if claims.get("role") != "authenticated" or claims.get("is_anonymous"):
        raise TokenError("A signed-in account is required")
    return claims
