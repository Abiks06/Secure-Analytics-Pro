"""In-process token-bucket rate limiting.

Buckets are keyed by (policy, client) and refill continuously, so bursts are allowed up to the
bucket size while the sustained rate stays bounded. Stale buckets are pruned lazily. For a
multi-instance deployment, swap ``_buckets`` for a shared store; the interface stays the same.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request, status


@dataclass(frozen=True)
class Policy:
    name: str
    capacity: int
    per_seconds: float

    @property
    def rate(self) -> float:
        return self.capacity / self.per_seconds


AUTH = Policy("auth", capacity=10, per_seconds=60)
UPLOAD = Policy("upload", capacity=20, per_seconds=300)
QUERY = Policy("query", capacity=60, per_seconds=60)
AI = Policy("ai", capacity=12, per_seconds=60)

_lock = threading.Lock()
_buckets: dict[tuple[str, str], tuple[float, float]] = {}
_last_prune = time.monotonic()


def _prune(now: float) -> None:
    global _last_prune
    if now - _last_prune < 60:
        return
    _last_prune = now
    for key, (_, ts) in list(_buckets.items()):
        if now - ts > 3600:
            del _buckets[key]


def take(policy: Policy, client: str) -> float:
    """Consume one token. Returns 0 when allowed, otherwise seconds until a token is free."""
    now = time.monotonic()
    with _lock:
        _prune(now)
        tokens, ts = _buckets.get((policy.name, client), (float(policy.capacity), now))
        tokens = min(policy.capacity, tokens + (now - ts) * policy.rate)
        if tokens >= 1:
            _buckets[(policy.name, client)] = (tokens - 1, now)
            return 0.0
        _buckets[(policy.name, client)] = (tokens, now)
        return (1 - tokens) / policy.rate


def client_key(request: Request) -> str:
    user = getattr(request.state, "user_id", None)
    if user:
        return f"u:{user}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


def limit(policy: Policy):
    """FastAPI dependency factory enforcing ``policy`` for the current client."""

    def dependency(request: Request) -> None:
        wait = take(policy, client_key(request))
        if wait:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded for {policy.name}. Try again in {math.ceil(wait)}s.",
                headers={"Retry-After": str(math.ceil(wait))},
            )

    return dependency


def reset() -> None:
    with _lock:
        _buckets.clear()
