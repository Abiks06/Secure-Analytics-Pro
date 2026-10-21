"""Time-series analysis: calendar bucketing, trend significance, anomalies and forecasting.

* Trend: OLS slope for magnitude, Mann-Kendall for significance (robust to non-normal noise).
* Anomalies: residuals against a centred rolling median, flagged beyond 3.5 robust z-scores.
* Seasonality: autocorrelation at the natural period of the bucket size.
* Forecast: Holt's linear (double exponential) smoothing with parameters chosen by one-step-ahead
  SSE over a grid, and prediction intervals that widen with the horizon.
"""

from __future__ import annotations

import math
from datetime import datetime, time
from typing import Any

import numpy as np
import polars as pl

from app.engine.util import finite, granularity_for, to_jsonable

_EVERY_DAYS = {"1h": 1 / 24, "1d": 1, "1w": 7, "1mo": 30.44, "1q": 91.31, "1y": 365.25}
_SEASON = {"1h": 24, "1d": 7, "1w": 52, "1mo": 12, "1q": 4}
ADDITIVE_HINT = (
    "amount",
    "revenue",
    "sales",
    "total",
    "qty",
    "quantity",
    "count",
    "units",
    "cost",
    "profit",
    "spend",
    "orders",
    "income",
    "volume",
)


def mann_kendall(y: np.ndarray) -> tuple[float, float]:
    """Return (z, two-sided p) for the Mann-Kendall monotonic trend test."""
    n = y.size
    if n < 4:
        return 0.0, 1.0
    diffs = np.sign(y[None, :] - y[:, None])
    s = float(np.triu(diffs, 1).sum())
    _, counts = np.unique(y, return_counts=True)
    var = (n * (n - 1) * (2 * n + 5) - np.sum(counts * (counts - 1) * (2 * counts + 5))) / 18
    if var <= 0:
        return 0.0, 1.0
    z = (s - np.sign(s)) / math.sqrt(var)
    p = math.erfc(abs(z) / math.sqrt(2))
    return z, p


def holt_forecast(y: np.ndarray, horizon: int) -> dict[str, Any] | None:
    n = y.size
    if n < 6:
        return None
    best = None
    grid = (0.1, 0.2, 0.3, 0.5, 0.7, 0.9)
    for alpha in grid:
        for beta in (0.05, 0.1, 0.2, 0.3, 0.5):
            level, trend = y[0], y[1] - y[0]
            sse = 0.0
            for t in range(1, n):
                pred = level + trend
                err = y[t] - pred
                sse += err * err
                new_level = alpha * y[t] + (1 - alpha) * (level + trend)
                trend = beta * (new_level - level) + (1 - beta) * trend
                level = new_level
            if best is None or sse < best[0]:
                best = (sse, alpha, beta, level, trend)
    sse, alpha, beta, level, trend = best  # type: ignore[misc]
    sigma = math.sqrt(sse / max(n - 2, 1))
    points, lower, upper = [], [], []
    for h in range(1, horizon + 1):
        f = level + h * trend
        # Var of Holt h-step error: sigma^2 * (1 + sum_{j<h} (alpha*(1+j*beta))^2)
        width = 1.96 * sigma * math.sqrt(1 + sum((alpha * (1 + j * beta)) ** 2 for j in range(1, h)))
        points.append(f)
        lower.append(f - width)
        upper.append(f + width)
    return {"alpha": alpha, "beta": beta, "y": points, "lower": lower, "upper": upper}


def _autocorr(y: np.ndarray, lag: int) -> float | None:
    if y.size < lag * 2 + 2:
        return None
    a, b = y[:-lag] - y.mean(), y[lag:] - y.mean()
    denom = math.sqrt(float((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / denom) if denom else None


def _future_index(last: datetime, every: str, h: int) -> list[str]:
    s = pl.Series([last]).dt.offset_by(every)
    out = []
    cur = s
    for _ in range(h):
        out.append(to_jsonable(cur[0]))
        cur = cur.dt.offset_by(every)
    return out


def pick_time_column(df: pl.DataFrame, kinds: dict[str, str]) -> str | None:
    best, best_n = None, 0
    for c, k in kinds.items():
        if k != "datetime":
            continue
        s = df[c].drop_nulls()
        if s.n_unique() >= 8 and s.len() > best_n:
            best, best_n = c, s.len()
    return best


def analyse(df: pl.DataFrame, kinds: dict[str, str], units: dict[str, str | None]) -> dict[str, Any] | None:
    tcol = pick_time_column(df, kinds)
    if not tcol:
        return None
    numeric = [c for c, k in kinds.items() if k == "numeric"]
    # Business measures first (revenue, units, ...), then the most complete columns.
    numeric = sorted(numeric, key=lambda c: (not any(h in c.lower() for h in ADDITIVE_HINT), df[c].null_count()))[:5]

    frame = df.select([pl.col(tcol).cast(pl.Datetime("us")).alias("__t"), *numeric]).drop_nulls("__t").sort("__t")
    lo, hi = frame["__t"].min(), frame["__t"].max()
    every = granularity_for(lo, hi, target=48)
    aggs: list[pl.Expr] = [pl.len().alias("Records")]
    methods = {"Records": "count"}
    for c in numeric:
        negatives = float((frame[c] < 0).mean() or 0)
        additive = negatives < 0.05 and units.get(c) != "percent" and any(h in c.lower() for h in ADDITIVE_HINT)
        aggs.append((pl.col(c).sum() if additive else pl.col(c).mean()).alias(c))
        methods[c] = "sum" if additive else "mean"
    buckets = frame.group_by_dynamic("__t", every=every).agg(aggs)
    if buckets.height < 6:
        return None

    # A trailing bucket that covers less than half its period would fake a drop: leave it out.
    last_start = buckets["__t"][-1]
    hi_dt = hi if isinstance(hi, datetime) else datetime.combine(hi, time())
    covered_days = (hi_dt - last_start).total_seconds() / 86400 + 1
    partial = every not in ("1h", "1d") and covered_days < 0.5 * _EVERY_DAYS[every]
    if partial:
        buckets = buckets.head(-1)

    t_labels = [to_jsonable(v) for v in buckets["__t"].to_list()]
    series = []
    for name in ["Records", *numeric]:
        y = buckets[name].cast(pl.Float64).fill_null(strategy="forward").fill_null(0).to_numpy()
        n = y.size
        x = np.arange(n, dtype=float)
        slope, intercept = np.polyfit(x, y, 1) if n >= 2 else (0.0, float(y[0]) if n else 0.0)
        z, p = mann_kendall(y)
        k = max(1, min(3, n // 4))
        first, last = float(np.mean(y[:k])), float(np.mean(y[-k:]))
        change = (last - first) / abs(first) if first else None

        med = pl.Series(y).rolling_median(window_size=5, center=True, min_samples=1).to_numpy()
        resid = y - med
        mad = float(np.median(np.abs(resid - np.median(resid)))) or float(np.std(resid)) or 1.0
        rz = 0.6745 * resid / mad
        anomalies = [
            {"t": t_labels[i], "value": finite(y[i]), "expected": finite(med[i]), "z": finite(rz[i])}
            for i in np.argsort(-np.abs(rz))[:5]
            # Robust z alone over-fires on very smooth series; also require a material deviation.
            if methods[name] != "mean" and abs(rz[i]) > 4 and n >= 8 and abs(resid[i]) > 0.35 * max(abs(med[i]), 1e-9)
        ]

        season_lag = _SEASON.get(every)
        acf = _autocorr(y, season_lag) if season_lag else None

        horizon = min(12, max(3, n // 4))
        fc = holt_forecast(y, horizon)
        if fc:
            fc["t"] = _future_index(buckets["__t"][n - 1], every, horizon)
            fc = {
                k2: ([finite(v) for v in val] if isinstance(val, list) and k2 != "t" else val) for k2, val in fc.items()
            }

        series.append(
            {
                "name": name,
                "method": methods[name],
                "unit": units.get(name),
                "y": [finite(v) for v in y],
                "trend": {
                    "slope": finite(slope),
                    "intercept": finite(intercept),
                    "mk_z": finite(z),
                    "p_value": finite(p),
                    "direction": "up" if z > 0 else "down" if z < 0 else "flat",
                    "significant": p < 0.05,
                    "change_pct": finite(change),
                    "from": finite(first),
                    "to": finite(last),
                },
                "seasonality": {"lag": season_lag, "acf": finite(acf), "detected": bool(acf and acf > 0.5)},
                "anomalies": anomalies,
                "forecast": fc,
                "peak": {"t": t_labels[int(np.argmax(y))], "value": finite(float(np.max(y)))} if n else None,
            }
        )
    return {
        "time_column": tcol,
        "granularity": every,
        "partial_last": partial,
        "t": t_labels,
        "series": series,
        "start": to_jsonable(lo),
        "end": to_jsonable(hi),
    }
