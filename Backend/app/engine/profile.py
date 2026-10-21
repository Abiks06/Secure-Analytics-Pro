"""Column profiling and data-quality scoring.

All scalar statistics for every column are computed in a single multi-threaded Polars ``select``
so the frame is scanned once; histograms reuse the same pass's min/max.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import polars as pl

from app.engine.clean import CleanResult
from app.engine.util import finite, granularity_for, to_jsonable

NUMERIC_QUANTILES = [0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]


def column_kind(s: pl.Series, inferred: str) -> str:
    t = s.dtype
    if t == pl.Boolean:
        return "boolean"
    if t in (pl.Date,) or isinstance(t, pl.Datetime):
        return "datetime"
    nonnull = s.len() - s.null_count()
    if t.is_numeric():
        if t.is_integer() and nonnull > 20 and s.n_unique() == s.len() and s.is_sorted():
            return "identifier"
        return "numeric"
    if inferred == "identifier":
        return "identifier"
    distinct = s.drop_nulls().n_unique()
    if nonnull and distinct <= max(50, int(0.2 * s.len())) and distinct <= 0.8 * nonnull:
        return "categorical"
    if nonnull > 20 and distinct >= 0.95 * nonnull:
        avg_len = s.drop_nulls().str.len_chars().mean() or 0
        return "identifier" if avg_len <= 40 and not s.drop_nulls().str.contains(" ").any() else "text"
    return "categorical" if distinct <= 0.5 * max(nonnull, 1) else "text"


def _histogram(values: np.ndarray) -> dict[str, Any]:
    if values.size == 0:
        return {"bins": [], "counts": []}
    lo, hi = float(values.min()), float(values.max())
    if lo == hi:
        return {"bins": [lo, hi], "counts": [int(values.size)]}
    q75, q25 = np.percentile(values, [75, 25])
    iqr = q75 - q25
    width = 2 * iqr / math.cbrt(values.size) if iqr > 0 else (hi - lo) / 20
    bins = int(np.clip(math.ceil((hi - lo) / width) if width > 0 else 20, 8, 40))
    counts, edges = np.histogram(values, bins=bins)
    return {"bins": [float(e) for e in edges], "counts": [int(c) for c in counts]}


def _numeric_exprs(c: str) -> list[pl.Expr]:
    col = pl.col(c).cast(pl.Float64)
    exprs = [
        col.mean().alias(f"{c}::mean"),
        col.std().alias(f"{c}::std"),
        col.min().alias(f"{c}::min"),
        col.max().alias(f"{c}::max"),
        col.sum().alias(f"{c}::sum"),
        col.skew().alias(f"{c}::skew"),
        col.kurtosis().alias(f"{c}::kurtosis"),
        (col == 0).sum().alias(f"{c}::zeros"),
        (col < 0).sum().alias(f"{c}::negatives"),
    ]
    exprs += [col.quantile(q, "linear").alias(f"{c}::q{int(q * 100):02d}") for q in NUMERIC_QUANTILES]
    return exprs


def profile(clean: CleanResult) -> dict[str, Any]:
    df = clean.frame
    n = df.height
    kinds = {c: column_kind(df[c], clean.meta[c].inferred if c in clean.meta else "text") for c in df.columns}

    base = df.select(
        [pl.col(c).null_count().alias(f"{c}::nulls") for c in df.columns]
        + [pl.col(c).n_unique().alias(f"{c}::distinct") for c in df.columns]
        + [e for c, k in kinds.items() if k == "numeric" for e in _numeric_exprs(c)]
    ).row(0, named=True)

    columns = []
    for c in df.columns:
        s = df[c]
        kind = kinds[c]
        meta = clean.meta.get(c)
        nulls = int(base[f"{c}::nulls"])
        distinct = int(base[f"{c}::distinct"]) - (1 if nulls else 0)
        nonnull = n - nulls
        col: dict[str, Any] = {
            "name": c,
            "original_name": meta.original_name if meta else c,
            "kind": kind,
            "dtype": str(s.dtype),
            "unit": meta.unit if meta else None,
            "count": nonnull,
            "nulls": nulls,
            "null_pct": nulls / n if n else 0,
            "distinct": distinct,
            "distinct_pct": distinct / nonnull if nonnull else 0,
            "invalid": meta.invalid if meta else 0,
        }
        if kind == "numeric":
            stats = {k.split("::")[1]: finite(v) for k, v in base.items() if k.startswith(f"{c}::")}
            stats.pop("nulls", None)
            stats.pop("distinct", None)
            col["stats"] = stats
            values = s.drop_nulls().cast(pl.Float64).to_numpy()
            values = values[np.isfinite(values)]
            if values.size > 1_000_000:
                values = np.random.default_rng(7).choice(values, 1_000_000, replace=False)
            col["histogram"] = _histogram(values)
        elif kind == "datetime":
            nn = s.drop_nulls()
            if nn.len():
                lo, hi = nn.min(), nn.max()
                every = granularity_for(lo, hi)
                buckets = (
                    nn.to_frame("t")
                    .with_columns(pl.col("t").cast(pl.Datetime("us")))
                    .sort("t")
                    .group_by_dynamic("t", every=every)
                    .agg(pl.len().alias("n"))
                )
                col["stats"] = {"min": to_jsonable(lo), "max": to_jsonable(hi), "granularity": every}
                col["timeline"] = {
                    "t": [to_jsonable(v) for v in buckets["t"].to_list()],
                    "n": buckets["n"].to_list(),
                }
        elif kind in ("categorical", "boolean", "text", "identifier"):
            vc = s.drop_nulls().value_counts(sort=True)
            top = vc.head(12)
            col["top"] = [{"value": to_jsonable(v), "count": int(k)} for v, k in top.iter_rows()]
            col["other_count"] = int(nonnull - top["count"].sum()) if nonnull else 0
            if nonnull and distinct > 1 and kind != "identifier":
                p = vc["count"].cast(pl.Float64) / nonnull
                col["entropy"] = finite(float(-(p * p.log(2)).sum()) / math.log2(distinct))
            if s.dtype == pl.String:
                lens = s.drop_nulls().str.len_chars()
                col["length"] = {"min": lens.min(), "mean": finite(lens.mean()), "max": lens.max()}
        col["health"] = {
            "completeness": 1 - (nulls / n if n else 0),
            "validity": 1 - ((meta.invalid if meta else 0) / max(nonnull + (meta.invalid if meta else 0), 1)),
        }
        columns.append(col)

    total_cells = max(n * df.width, 1)
    missing = sum(c["nulls"] for c in columns)
    invalid = sum(c["invalid"] for c in columns)
    completeness = 1 - missing / total_cells
    validity = 1 - invalid / max(total_cells - missing + invalid, 1)
    # Duplicates are penalised super-linearly: 1% duplicated rows already skews counts and sums.
    uniqueness = max(0.0, 1 - 10 * clean.duplicates_removed / max(clean.rows_before, 1))
    # Consistency is judged per column (how uniformly was it written?), then averaged, so one badly
    # formatted column is not diluted by many clean ones.
    fixes_by_col: dict[str, int] = {}
    for a in clean.actions:
        if a.column and a.action in ("trim_whitespace", "unify_categories"):
            fixes_by_col[a.column] = fixes_by_col.get(a.column, 0) + a.count
    col_consistency = []
    for c in columns:
        meta = clean.meta.get(c["name"])
        penalty = min(1.0, 3 * fixes_by_col.get(c["name"], 0) / max(c["count"], 1))
        if meta and len(meta.formats) > 1:
            penalty += 0.25 * (len(meta.formats) - 1)
        if meta and meta.unit and meta.unit.startswith("currency"):
            penalty += 0.1  # numbers stored as text with symbols/separators
        col_consistency.append(max(0.0, 1 - penalty))
    consistency = sum(col_consistency) / len(col_consistency) if col_consistency else 1.0
    score = 100 * (0.35 * completeness + 0.25 * validity + 0.2 * uniqueness + 0.2 * consistency)

    kind_counts: dict[str, int] = {}
    for c in columns:
        kind_counts[c["kind"]] = kind_counts.get(c["kind"], 0) + 1

    return {
        "overview": {
            "rows": n,
            "rows_raw": clean.rows_before,
            "columns": df.width,
            "missing_cells": missing,
            "missing_pct": missing / total_cells,
            "duplicates_removed": clean.duplicates_removed,
            "memory_bytes": int(df.estimated_size()),
            "kinds": kind_counts,
        },
        "quality": {
            "score": round(score, 1),
            "completeness": completeness,
            "validity": validity,
            "uniqueness": uniqueness,
            "consistency": consistency,
        },
        "columns": columns,
    }
