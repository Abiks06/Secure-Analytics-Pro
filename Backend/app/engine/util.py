from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any


def finite(v: Any) -> Any:
    """Make a scalar JSON-safe: NaN/inf become None, numpy scalars become Python numbers."""
    if v is None:
        return None
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, Decimal):
        return float(v)
    return v


def to_jsonable(v: Any) -> Any:
    v = finite(v)
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, (date, time)):
        return v.isoformat()
    if isinstance(v, timedelta):
        return v.total_seconds()
    if isinstance(v, bytes):
        return v.hex()
    if isinstance(v, (list, tuple)):
        return [to_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): to_jsonable(x) for k, x in v.items()}
    return v


def granularity_for(lo: Any, hi: Any, target: int = 60) -> str:
    """Pick a calendar bucket size giving roughly ``target`` buckets over [lo, hi]."""
    if isinstance(lo, date) and not isinstance(lo, datetime):
        lo = datetime.combine(lo, time())
        hi = datetime.combine(hi, time())
    span = (hi - lo).total_seconds() if hi and lo else 0
    days = span / 86400
    for every, size in (("1h", 1 / 24), ("1d", 1), ("1w", 7), ("1mo", 30.4), ("1q", 91.3), ("1y", 365.25)):
        if days / size <= target:
            return every
    return "1y"
