"""Automated insight discovery.

Each detector turns a statistical result into a ranked, human-readable finding with the chart
data needed to show it. Scores combine effect size and support so that a strong pattern on many
rows outranks a fluke on a handful. Expensive detectors work on a fixed-seed sample, so results
are reproducible and the cost is bounded regardless of dataset size.
"""

from __future__ import annotations

import math
import re
from typing import Any

import numpy as np
import polars as pl

from app.engine.timeseries import analyse as analyse_timeseries
from app.engine.util import finite, to_jsonable

CORR_SAMPLE = 250_000
MAX_NUMERIC = 24
NONNEG_HINT = re.compile(
    r"price|amount|qty|quantity|age|count|units|cost|revenue|sales|weight|height|salary|duration", re.I
)


def fmt(v: float | None, unit: str | None = None) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "n/a"
    a = abs(v)
    if a >= 1e9:
        s = f"{v / 1e9:.2f}B"
    elif a >= 1e6:
        s = f"{v / 1e6:.2f}M"
    elif a >= 1e4:
        s = f"{v / 1e3:.1f}K"
    elif a >= 100 or float(v).is_integer():
        s = f"{v:,.0f}"
    else:
        s = f"{v:,.2f}"
    if unit and unit.startswith("currency"):
        sym = unit.split(":", 1)[1] if ":" in unit else ""
        return f"{sym}{s}" if len(sym) == 1 else f"{s} {sym}".strip()
    if unit == "percent":
        return f"{s}%"
    return s


def _pct(v: float) -> str:
    return f"{v * 100:.0f}%" if abs(v) >= 0.1 else f"{v * 100:.1f}%"


class Collector:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(
        self, kind: str, severity: str, title: str, body: str, score: float, columns: list[str], chart=None, metric=None
    ):
        self.items.append(
            {
                "id": f"{kind}-{len(self.items)}",
                "kind": kind,
                "severity": severity,
                "title": title,
                "body": body,
                "score": round(float(min(max(score, 0), 1)), 4),
                "columns": columns,
                "chart": chart,
                "metric": metric,
            }
        )


def _numeric_matrix(df: pl.DataFrame, cols: list[str]) -> np.ndarray:
    sample = df.select(cols)
    if sample.height > CORR_SAMPLE:
        sample = sample.sample(CORR_SAMPLE, seed=7)
    return sample.select([pl.col(c).cast(pl.Float64) for c in cols]).to_numpy()


def _pairwise_corr(m: np.ndarray, ranks: bool) -> tuple[np.ndarray, np.ndarray]:
    k = m.shape[1]
    corr = np.full((k, k), np.nan)
    support = np.zeros((k, k), dtype=int)
    finite_mask = np.isfinite(m)
    for i in range(k):
        corr[i, i] = 1.0
        for j in range(i + 1, k):
            mask = finite_mask[:, i] & finite_mask[:, j]
            n = int(mask.sum())
            support[i, j] = support[j, i] = n
            if n < 8:
                continue
            a, b = m[mask, i], m[mask, j]
            if ranks:
                a = pl.Series(a).rank("average").to_numpy()
                b = pl.Series(b).rank("average").to_numpy()
            sa, sb = a.std(), b.std()
            if sa == 0 or sb == 0:
                continue
            r = float(((a - a.mean()) * (b - b.mean())).mean() / (sa * sb))
            corr[i, j] = corr[j, i] = r
    return corr, support


def correlations(df: pl.DataFrame, numeric: list[str], out: Collector, units: dict[str, Any]) -> dict[str, Any] | None:
    if len(numeric) < 2:
        return None
    m = _numeric_matrix(df, numeric)
    pearson, support = _pairwise_corr(m, ranks=False)
    spearman, _ = _pairwise_corr(m, ranks=True)
    pairs = []
    for i in range(len(numeric)):
        for j in range(i + 1, len(numeric)):
            r, rho = pearson[i, j], spearman[i, j]
            if np.isnan(r) and np.isnan(rho):
                continue
            pairs.append((numeric[i], numeric[j], finite(r), finite(rho), int(support[i, j]), i, j))
    pairs.sort(key=lambda p: -max(abs(p[2] or 0), abs(p[3] or 0)))

    rng = np.random.default_rng(3)
    emitted = 0
    for a, b, r, rho, n, i, j in pairs:
        strength = max(abs(r or 0), abs(rho or 0))
        if strength < 0.5 or emitted >= 6:
            continue
        mask = np.isfinite(m[:, i]) & np.isfinite(m[:, j])
        xs, ys = m[mask, i], m[mask, j]
        if xs.size > 400:
            idx = rng.choice(xs.size, 400, replace=False)
            xs, ys = xs[idx], ys[idx]
        slope, intercept = np.polyfit(m[mask, i], m[mask, j], 1) if mask.sum() > 2 else (0, 0)
        chart = {
            "type": "scatter",
            "x": a,
            "y": b,
            "points": [[finite(x), finite(y)] for x, y in zip(xs, ys, strict=False)],
            "fit": {"slope": finite(slope), "intercept": finite(intercept)},
        }
        if strength > 0.98:
            out.add(
                "redundancy",
                "warning",
                f"{a} and {b} are near-duplicates",
                f"They move in lockstep (r = {r:.3f}). One of them is likely derived from the other; "
                "keeping both can double-count effects in models and dashboards.",
                0.55,
                [a, b],
                chart,
                {"label": "Pearson r", "value": round(r or 0, 3)},
            )
        else:
            direction = "rises" if (rho or r or 0) > 0 else "falls"
            nonlinear = abs(rho or 0) - abs(r or 0) > 0.15
            body = f"Across {n:,} rows, {b} {direction} as {a} increases (Pearson r = {r:.2f}, Spearman ρ = {rho:.2f})."
            if nonlinear:
                body += " The rank correlation is notably stronger, so the relationship is monotonic but not linear."
            else:
                body += f" Each additional unit of {a} is associated with {fmt(slope, units.get(b))} {b} on average."
            out.add(
                "correlation",
                "notable" if strength >= 0.7 else "info",
                f"{b} {direction} with {a}",
                body,
                0.35 + 0.55 * strength * min(1, math.log10(max(n, 10)) / 3),
                [a, b],
                chart,
                {"label": "correlation", "value": round((rho if nonlinear else r) or 0, 2)},
            )
        emitted += 1
    return {
        "columns": numeric,
        "pearson": [[finite(v) for v in row] for row in pearson],
        "spearman": [[finite(v) for v in row] for row in spearman],
        "top_pairs": [{"a": a, "b": b, "pearson": r, "spearman": rho, "n": n} for a, b, r, rho, n, *_ in pairs[:15]],
    }


def _wilson_hilferty_chi2(k: int, z: float = 3.09) -> float:
    """Approximate chi-square quantile (z=3.09 ~ 99.9th percentile) without SciPy."""
    return k * (1 - 2 / (9 * k) + z * math.sqrt(2 / (9 * k))) ** 3


def outliers(
    df: pl.DataFrame, numeric: list[str], profile_cols: dict[str, dict], out: Collector, units
) -> dict[str, Any]:
    result: dict[str, Any] = {"univariate": [], "multivariate": None}
    for c in numeric:
        st = profile_cols[c].get("stats", {})
        q1, q3, med = st.get("q25"), st.get("q75"), st.get("q50")
        if q1 is None or q3 is None:
            continue
        s = df[c].cast(pl.Float64).drop_nulls()
        n = s.len()
        if n < 20 or q3 == q1:
            continue
        # Strictly positive, right-skewed measures (money, counts) are judged on a log scale, so a
        # legitimately long tail isn't flagged wholesale while 40x entry errors still stand out.
        positive_share = float((s > 0).mean() or 0)
        log_scale = positive_share >= 0.95 and (st.get("skew") or 0) > 1
        if log_scale:
            s = s.filter(s > 0)  # negatives are reported separately as a quality issue
            v = s.log()
            lq1, lq3 = float(v.quantile(0.25)), float(v.quantile(0.75))
        else:
            v, lq1, lq3 = s, q1, q3
        iqr = lq3 - lq1
        lo, hi = lq1 - 3 * iqr, lq3 + 3 * iqr
        mild_lo, mild_hi = lq1 - 1.5 * iqr, lq3 + 1.5 * iqr
        extreme = s.filter((v < lo) | (v > hi))
        mild = int(((v < mild_lo) | (v > mild_hi)).sum())
        entry = {
            "column": c,
            "q1": q1,
            "median": med,
            "q3": q3,
            "whisker_low": finite(s.filter(v >= mild_lo).min()),
            "whisker_high": finite(s.filter(v <= mild_hi).max()),
            "mild": mild,
            "extreme": extreme.len(),
            "log_scale": log_scale,
            "samples": [finite(x) for x in extreme.sort(descending=True).head(20).to_list()],
        }
        result["univariate"].append(entry)
        share = extreme.len() / n
        if extreme.len() and share <= 0.05:
            worst = float(extreme.abs().max() or 0)
            ratio = worst / abs(med) if med else None
            scale = " on a log scale" if log_scale else ""
            body = (
                f"{extreme.len():,} value(s) ({_pct(share)}) lie far outside the typical range "
                f"[{fmt(q1, units.get(c))} – {fmt(q3, units.get(c))}] (beyond 3×IQR{scale})."
            )
            if ratio and ratio > 3:
                body += f" The largest is {ratio:,.0f}× the median. Check for data-entry errors or unit mix-ups before averaging."
            out.add(
                "outlier",
                "warning" if ratio and ratio > 10 else "info",
                f"Extreme values in {c}",
                body,
                0.35 + min(0.25, share * 10) + (0.2 if ratio and ratio > 10 else 0),
                [c],
                {"type": "box", **entry},
                {"label": "extreme values", "value": extreme.len()},
            )

    cols = [c for c in numeric if df[c].null_count() < 0.5 * df.height][:12]
    if len(cols) >= 3 and df.height >= 50:
        sub = df.with_row_index("__row").select(["__row", *cols]).drop_nulls()
        if sub.height > CORR_SAMPLE:
            sub = sub.sample(CORR_SAMPLE, seed=5)
        m = sub.select([pl.col(c).cast(pl.Float64) for c in cols]).to_numpy()
        raw = m.copy()
        # Heavy-tailed positive measures are compared in log space, where their spread is stable.
        for j, c in enumerate(cols):
            st = profile_cols[c].get("stats", {})
            if (st.get("min") or 0) >= 0 and (st.get("skew") or 0) > 1:
                m[:, j] = np.log1p(m[:, j])
        med = np.median(m, axis=0)
        mad = np.median(np.abs(m - med), axis=0) * 1.4826
        mad[mad == 0] = np.std(m, axis=0)[mad == 0]
        keep = mad > 0
        if keep.sum() >= 3 and m.shape[0] >= 50:
            z = (m[:, keep] - med[keep]) / mad[keep]
            z = np.clip(z, -50, 50)
            cov = np.cov(z, rowvar=False)
            inv = np.linalg.pinv(cov)
            d2 = np.einsum("ij,jk,ik->i", z, inv, z)
            k = int(keep.sum())
            threshold = _wilson_hilferty_chi2(k)
            flagged = np.where(d2 > threshold)[0]
            top = flagged[np.argsort(-d2[flagged])][:8]
            rows = sub["__row"].to_numpy()
            kept_cols = [c for c, kk in zip(cols, keep, strict=False) if kk]
            result["multivariate"] = {
                "columns": kept_cols,
                "threshold": threshold,
                "flagged": int(flagged.size),
                "rows": [
                    {
                        "row": int(rows[i]),
                        "distance": finite(math.sqrt(d2[i])),
                        "values": {c: finite(raw[i, idx]) for idx, c in enumerate(cols)},
                        "drivers": [kept_cols[j] for j in np.argsort(-np.abs(z[i]))[:3]],
                    }
                    for i in top
                ],
            }
            share = flagged.size / m.shape[0]
            if flagged.size and share < 0.05:
                out.add(
                    "anomaly",
                    "notable",
                    f"{flagged.size:,} records have an unusual combination of values",
                    f"Robust Mahalanobis distance across {k} numeric columns flags {_pct(share)} of rows as "
                    f"multivariate anomalies: each value may look normal alone, but together they are rare. "
                    f"Most unusual: row {int(rows[top[0]])}, driven by {', '.join(result['multivariate']['rows'][0]['drivers'])}.",
                    0.45 + min(0.3, share * 5),
                    kept_cols,
                    None,
                    {"label": "anomalous rows", "value": int(flagged.size)},
                )
    return result


def segments(
    df: pl.DataFrame, categorical: list[str], numeric: list[str], out: Collector, units
) -> list[dict[str, Any]]:
    results = []
    candidates = []
    targets = sorted(numeric, key=lambda c: df[c].null_count())[:8]
    for g in categorical:
        k = df[g].drop_nulls().n_unique()
        if not 2 <= k <= 30:
            continue
        for y in targets:
            sub = df.select(pl.col(g).cast(pl.String), pl.col(y).cast(pl.Float64)).drop_nulls()
            n = sub.height
            if n < 20:
                continue
            grand = sub[y].mean()
            ss_total = float(((sub[y] - grand) ** 2).sum())
            if not ss_total:
                continue
            groups = sub.group_by(g).agg(pl.col(y).mean().alias("mean"), pl.len().alias("n")).filter(pl.col("n") >= 3)
            if groups.height < 2:
                continue
            ss_between = float((groups["n"] * (groups["mean"] - grand) ** 2).sum())
            eta2 = ss_between / ss_total
            results.append({"group": g, "target": y, "eta2": eta2, "n": n})
            if eta2 < 0.06:
                continue
            groups = groups.sort("mean", descending=True)
            top, bottom = groups.row(0, named=True), groups.row(-1, named=True)
            ratio = top["mean"] / bottom["mean"] if bottom["mean"] else None
            comparison = (
                f"'{top[g]}' averages {fmt(top['mean'], units.get(y))} versus {fmt(bottom['mean'], units.get(y))} for '{bottom[g]}'"
                + (f" ({ratio:.1f}×)." if ratio and ratio > 0 else ".")
            )
            if eta2 > 0.95:
                title = f"{y} is set by {g}"
                body = f"{g} accounts for virtually all variation in {y}: it behaves like a lookup, not a driver. {comparison}"
                score = 0.4
            else:
                title = f"{g} is a key driver of {y}"
                body = f"{g} explains {_pct(eta2)} of the variation in {y} (η² across {groups.height} groups, {n:,} rows). {comparison}"
                score = 0.35 + 0.6 * min(1, eta2 / 0.4) * min(1, math.log10(n) / 3)
            shown = groups.head(15)
            candidates.append((score, g, y, title, body, eta2, shown, grand))
    per_group: dict[str, int] = {}
    for score, g, y, title, body, eta2, shown, grand in sorted(candidates, key=lambda c: -c[0]):
        if per_group.get(g, 0) >= 2 or sum(per_group.values()) >= 6:
            continue
        per_group[g] = per_group.get(g, 0) + 1
        out.add(
            "segment",
            "notable" if 0.14 <= eta2 <= 0.95 else "info",
            title,
            body,
            score,
            [g, y],
            {
                "type": "bar",
                "x": g,
                "y": y,
                "categories": [to_jsonable(v) for v in shown[g].to_list()],
                "values": [finite(v) for v in shown["mean"].to_list()],
                "counts": shown["n"].to_list(),
                "baseline": finite(grand),
            },
            {"label": "η² (effect size)", "value": round(eta2, 3)},
        )
    results.sort(key=lambda r: -r["eta2"])
    return results[:30]


def distributions(df: pl.DataFrame, profile_cols: dict[str, dict], out: Collector, units) -> None:
    for c, p in profile_cols.items():
        kind = p["kind"]
        n = p["count"]
        if p["null_pct"] >= 0.3 and kind != "identifier":
            out.add(
                "quality",
                "warning" if p["null_pct"] < 0.7 else "critical",
                f"{c} is {_pct(p['null_pct'])} empty",
                f"{p['nulls']:,} of {p['nulls'] + n:,} rows have no value. Aggregates over {c} describe only the rows where it was recorded.",
                0.3 + 0.4 * p["null_pct"],
                [c],
                None,
                {"label": "missing", "value": round(p["null_pct"], 3)},
            )
        if p.get("invalid"):
            out.add(
                "quality",
                "warning",
                f"{p['invalid']:,} malformed value(s) in {c}",
                f"These could not be read as {p['kind']} and were set to missing during cleaning.",
                0.35 + min(0.3, p["invalid"] / max(n, 1)),
                [c],
                None,
                {"label": "invalid", "value": p["invalid"]},
            )
        if n and p["distinct"] == 1 and df.width > 1:
            out.add(
                "quality",
                "info",
                f"{c} has a single value",
                "It carries no information for analysis and can be dropped.",
                0.2,
                [c],
            )
            continue
        if kind == "numeric":
            st = p.get("stats", {})
            skew, mean, med = st.get("skew"), st.get("mean"), st.get("q50")
            if skew is not None and abs(skew) > 2 and n >= 30:
                side = "right" if skew > 0 else "left"
                out.add(
                    "distribution",
                    "info",
                    f"{c} is heavily {side}-skewed",
                    f"The mean ({fmt(mean, units.get(c))}) is pulled away from the median ({fmt(med, units.get(c))}) by a long tail "
                    f"(skewness {skew:.1f}). Prefer the median for 'typical' values and a log scale for charts.",
                    0.25 + min(0.25, abs(skew) / 40),
                    [c],
                    {"type": "histogram", "column": c, **p.get("histogram", {})},
                    {"label": "skewness", "value": round(skew, 2)},
                )
            if (st.get("negatives") or 0) > 0 and NONNEG_HINT.search(c) and (st.get("negatives") or 0) < 0.2 * n:
                out.add(
                    "quality",
                    "warning",
                    f"Negative values in {c}",
                    f"{st['negatives']:,} row(s) are below zero, which is unusual for a column named '{c}'. "
                    "They may be refunds, corrections or entry errors.",
                    0.4,
                    [c],
                    None,
                    {"label": "negative rows", "value": st["negatives"]},
                )
            additive = re.search(
                r"revenue|sales|amount|spend|cost|profit|income|total|volume|units|qty|quantity", c, re.I
            )
            if additive and (st.get("min") or 0) >= 0 and (st.get("sum") or 0) > 0 and n >= 20:
                values = df[c].cast(pl.Float64).drop_nulls().sort(descending=True).to_numpy()
                cum = np.cumsum(values) / values.sum()
                top20 = float(cum[max(0, int(math.ceil(0.2 * values.size)) - 1)])
                if top20 >= 0.6:
                    xs = np.linspace(0, 1, 41)
                    idx = np.clip((xs * values.size).astype(int) - 1, 0, values.size - 1)
                    out.add(
                        "pareto",
                        "notable",
                        f"Top 20% of rows hold {_pct(top20)} of total {c}",
                        f"{c} is highly concentrated: a small share of records drives most of the total "
                        f"({fmt(float(values.sum()), units.get(c))}). Prioritise the head of the distribution.",
                        0.4 + 0.5 * (top20 - 0.6) / 0.4,
                        [c],
                        {
                            "type": "pareto",
                            "column": c,
                            "x": xs.tolist(),
                            "y": [0.0, *[float(cum[i]) for i in idx[1:]]],
                        },
                        {"label": "share of total", "value": round(top20, 3)},
                    )
        elif kind in ("categorical", "boolean") and p.get("top") and n >= 20:
            top = p["top"][0]
            share = top["count"] / n
            if share >= 0.8 and p["distinct"] > 1:
                out.add(
                    "distribution",
                    "info",
                    f"{c} is dominated by '{top['value']}'",
                    f"{_pct(share)} of rows share this value, so comparisons across {c} rest on very few rows for the other groups.",
                    0.2 + 0.2 * share,
                    [c],
                    {
                        "type": "bar",
                        "x": c,
                        "categories": [t["value"] for t in p["top"][:8]],
                        "values": [t["count"] for t in p["top"][:8]],
                    },
                    {"label": "share", "value": round(share, 3)},
                )


def trends(ts: dict[str, Any] | None, out: Collector) -> None:
    if not ts:
        return
    before = len(out.items)
    seen_anomaly_t: set[str] = set()
    for s in ts["series"]:
        tr = s["trend"]
        label = "row count" if s["name"] == "Records" else f"{s['method']} of {s['name']}"
        chart = {
            "type": "line",
            "t": ts["t"],
            "y": s["y"],
            "series": s["name"],
            "forecast": s["forecast"],
            "anomalies": s["anomalies"],
        }
        if tr["significant"] and tr["change_pct"] is not None and abs(tr["change_pct"]) >= 0.05:
            up = tr["direction"] == "up"
            out.add(
                "trend",
                "positive" if up else "warning",
                f"{s['name'] if s['name'] != 'Records' else 'Activity'} is trending {'up' if up else 'down'} {_pct(abs(tr['change_pct']))}",
                f"The {label} per {ts['granularity']} moved from {fmt(tr['from'], s['unit'])} to {fmt(tr['to'], s['unit'])} "
                f"between {ts['start'][:10]} and {ts['end'][:10]}. The trend is statistically significant "
                f"(Mann-Kendall p = {tr['p_value']:.3g}).",
                0.5 + min(0.4, abs(tr["change_pct"]) / 2),
                [ts["time_column"], s["name"]],
                chart,
                {"label": "change", "value": round(tr["change_pct"], 3)},
            )
        for a in s["anomalies"][:2]:
            # One card per period: the same spike usually shows up in every additive measure.
            if a["t"] in seen_anomaly_t:
                continue
            seen_anomaly_t.add(a["t"])
            spike = (a["value"] or 0) > (a["expected"] or 0)
            out.add(
                "anomaly",
                "notable",
                f"{'Spike' if spike else 'Drop'} in {s['name'] if s['name'] != 'Records' else 'activity'} at {str(a['t'])[:10]}",
                f"The {label} was {fmt(a['value'], s['unit'])} against an expected {fmt(a['expected'], s['unit'])} "
                f"from neighbouring periods ({abs(a['z'] or 0):.1f} robust σ).",
                0.45 + min(0.3, abs(a["z"] or 0) / 30),
                [ts["time_column"], s["name"]],
                chart,
            )
        if s["seasonality"]["detected"]:
            out.add(
                "seasonality",
                "info",
                f"Recurring {s['seasonality']['lag']}-period cycle in {s['name']}",
                f"Autocorrelation at lag {s['seasonality']['lag']} is {s['seasonality']['acf']:.2f}, indicating a seasonal pattern.",
                0.35,
                [ts["time_column"], s["name"]],
                chart,
            )
    # Keep the three strongest trend cards; parallel series rarely add information.
    trend_cards = sorted((i for i in out.items[before:] if i["kind"] == "trend"), key=lambda i: -i["score"])
    drop = {i["id"] for i in trend_cards[3:]}
    out.items = [i for i in out.items if i["id"] not in drop]


def generate(df: pl.DataFrame, prof: dict[str, Any], units: dict[str, str | None]) -> dict[str, Any]:
    out = Collector()
    cols = {c["name"]: c for c in prof["columns"]}
    kinds = {c: p["kind"] for c, p in cols.items()}
    numeric = [c for c, k in kinds.items() if k == "numeric"]
    numeric = sorted(numeric, key=lambda c: cols[c]["nulls"])[:MAX_NUMERIC]
    categorical = [c for c, k in kinds.items() if k in ("categorical", "boolean")]

    corr = correlations(df, numeric, out, units)
    outl = outliers(df, numeric, cols, out, units)
    segs = segments(df, categorical, numeric, out, units)
    distributions(df, cols, out, units)
    ts = analyse_timeseries(df, kinds, units)
    trends(ts, out)

    items = sorted(out.items, key=lambda i: -i["score"])
    return {"insights": items, "correlations": corr, "outliers": outl, "segments": segs, "timeseries": ts}
