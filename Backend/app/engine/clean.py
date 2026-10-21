"""Automated cleaning for messy real-world data.

Every column arrives as text (or already typed from JSON/Parquet). For text columns the cleaner
decides the most plausible type from a sample, then converts the full column in one vectorised
pass. It understands currency symbols, thousands separators (US and European), accounting
negatives "(1,234)", percentages, booleans in many spellings, and dates written in several
formats inside the same column. Every change is recorded so users can audit what happened.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

import polars as pl

NULL_TOKENS = [
    "",
    "na",
    "n/a",
    "n.a.",
    "nan",
    "null",
    "none",
    "nil",
    "-",
    "--",
    "?",
    "missing",
    "#n/a",
    "#null!",
    "#value!",
    "#div/0!",
    "undefined",
    "not available",
    "unknown",
]
TRUE_TOKENS = {"true", "t", "yes", "y", "1", "on"}
FALSE_TOKENS = {"false", "f", "no", "n", "0", "off"}
CURRENCY_RE = r"[\$€£¥₦₹₩₽¢]|\b(?:USD|EUR|GBP|NGN|JPY|INR|CAD|AUD|GHS|KES|ZAR)\b"

DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S%.f",
    "%Y-%m-%d %H:%M:%S%.f",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
    "%Y/%m/%d",
    "%Y/%m/%d %H:%M:%S",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d/%m/%Y %H:%M",
    "%m/%d/%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %I:%M %p",
    "%d-%m-%Y",
    "%m-%d-%Y",
    "%d.%m.%Y",
    "%d/%m/%y",
    "%m/%d/%y",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%b %d %Y",
    "%B %d %Y",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%b %Y",
    "%B %Y",
    "%Y-%m",
    "%Y-%m-%dT%H:%M:%S%#z",
    "%Y-%m-%dT%H:%M:%S%.f%#z",
    "%Y-%m-%d %H:%M:%S%#z",
    "%Y%m%d",
]
_DATE_HINT = re.compile(r"date|time|day|month|year|period|_at$|_on$|dob|birth|created|updated", re.I)
_DATEISH = re.compile(r"[-/.:]|[A-Za-z]{3}")
_ID_HINT = re.compile(
    r"(?i:(?:^|[\s_.-])(id|code|zip|postal|postcode|phone|mobile|tel|card|iban|account|acct|ssn|sku|isbn|ean|upc)(?:$|[\s_.-]))"
    r"|[a-z]Id$"
)

SAMPLE = 20_000


@dataclass
class CleanAction:
    column: str | None
    action: str
    count: int
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ColumnMeta:
    original_name: str
    inferred: str = "text"
    invalid: int = 0
    unit: str | None = None
    formats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CleanResult:
    frame: pl.DataFrame
    actions: list[CleanAction]
    meta: dict[str, ColumnMeta]
    rows_before: int
    duplicates_removed: int


def _normalise_headers(df: pl.DataFrame, actions: list[CleanAction]) -> tuple[pl.DataFrame, dict[str, str]]:
    seen: dict[str, int] = {}
    mapping: dict[str, str] = {}
    for i, col in enumerate(df.columns):
        name = re.sub(r"\s+", " ", col.replace("﻿", "")).strip().strip('"').strip()
        if not name or re.fullmatch(r"_duplicated_\d+|column_\d+", name):
            name = f"column_{i + 1}"
        base = name
        while name.lower() in seen:
            seen[base.lower()] += 1
            name = f"{base}_{seen[base.lower()]}"
        seen[name.lower()] = 1
        mapping[col] = name
    renamed = {k: v for k, v in mapping.items() if k != v}
    if renamed:
        actions.append(
            CleanAction(None, "rename_columns", len(renamed), "Trimmed, filled or de-duplicated column headers.")
        )
    return df.rename(mapping), {v: k for k, v in mapping.items()}


def _sample(s: pl.Series) -> pl.Series:
    s = s.drop_nulls()
    return s.sample(SAMPLE, seed=7) if s.len() > SAMPLE else s


def _numeric_expr(name: str, european: bool) -> pl.Expr:
    s = pl.col(name).str.strip_chars()
    negative = s.str.contains(r"^\(.*\)$") | s.str.contains(r"^[^-]*\d-$")
    s = (
        s.str.replace_all(CURRENCY_RE, "")
        .str.replace_all(r"[\s '’]", "")
        .str.replace(r"%$", "")
        .str.replace_all(r"^\((.*)\)$", "$1")
        .str.replace(r"-$", "")
    )
    s = s.str.replace_all(r"\.", "").str.replace(",", ".") if european else s.str.replace_all(",", "")
    num = s.cast(pl.Float64, strict=False)
    return pl.when(negative).then(-num).otherwise(num)


def _numeric_plan(sample: pl.Series) -> tuple[float, bool, str | None]:
    """Return (parse rate, european, unit) for a text sample."""
    if sample.len() == 0:
        return 0.0, False, None
    euro = sample.str.contains(r"^-?\d{1,3}(\.\d{3})+(,\d+)?$|^-?\d+,\d{1,2}$").sum()
    us = sample.str.contains(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$|^-?\d+\.\d+$").sum()
    european = euro > us
    parsed = pl.DataFrame({"v": sample}).select(_numeric_expr("v", european)).to_series()
    rate = parsed.is_not_null().sum() / sample.len()
    unit = None
    if sample.str.contains(r"%\s*$").mean() > 0.5:
        unit = "percent"
    elif sample.str.contains(CURRENCY_RE).mean() > 0.3:
        symbol = sample.str.extract(f"({CURRENCY_RE})", 1).drop_nulls().mode()
        unit = f"currency:{symbol[0]}" if symbol.len() else "currency"
    return rate, european, unit


def _date_expr(name: str, fmt: str) -> pl.Expr:
    e = pl.col(name).str.strip_chars().str.to_datetime(fmt, strict=False, time_unit="us")
    if "z" in fmt:
        e = e.dt.convert_time_zone("UTC").dt.replace_time_zone(None)
    return e


def _parse_dates(name: str, formats: list[str]) -> pl.Expr:
    return pl.coalesce([_date_expr(name, f) for f in formats])


def _date_plan(sample: pl.Series, colname: str) -> tuple[float, list[str]]:
    if sample.len() == 0:
        return 0.0, []
    stripped = sample.str.strip_chars()
    if stripped.str.contains(_DATEISH.pattern).mean() < 0.8 and not _DATE_HINT.search(colname):
        return 0.0, []
    frame = pl.DataFrame({"v": stripped})
    candidates = DATE_FORMATS if _DATE_HINT.search(colname) else DATE_FORMATS[:-1]
    parsed: dict[str, pl.Series] = {}
    for fmt in candidates:
        try:
            s = frame.select(_date_expr("v", fmt)).to_series()
        except Exception:
            continue
        if s.is_not_null().any():
            parsed[fmt] = s
    if not parsed:
        return 0.0, []
    # Greedy set cover: add the format that parses the most still-unparsed values.
    covered = pl.Series([False] * sample.len())
    chosen: list[str] = []
    for _ in range(6):
        best, gain = None, 0
        for fmt, s in parsed.items():
            if fmt in chosen:
                continue
            g = int((s.is_not_null() & ~covered).sum())
            if g > gain:
                best, gain = fmt, g
        if best is None or gain < max(1, 0.02 * sample.len()):
            break
        chosen.append(best)
        covered = covered | parsed[best].is_not_null()
    return float(covered.mean()), chosen


def clean(df: pl.DataFrame) -> CleanResult:
    actions: list[CleanAction] = []
    rows_before = df.height
    df, original = _normalise_headers(df, actions)
    meta = {c: ColumnMeta(original_name=original.get(c, c)) for c in df.columns}

    text_cols = [c for c, t in df.schema.items() if t == pl.String]

    # 1. Whitespace and null-token normalisation (single pass over all text columns).
    if text_cols:
        stats = df.select(
            [
                (pl.col(c).is_not_null() & (pl.col(c) != pl.col(c).str.strip_chars())).sum().alias(f"ws::{c}")
                for c in text_cols
            ]
            + [
                (pl.col(c).is_not_null() & pl.col(c).str.strip_chars().str.to_lowercase().is_in(NULL_TOKENS))
                .sum()
                .alias(f"null::{c}")
                for c in text_cols
            ]
        ).row(0, named=True)
        df = df.with_columns(
            [
                pl.when(pl.col(c).str.strip_chars().str.to_lowercase().is_in(NULL_TOKENS))
                .then(None)
                .otherwise(pl.col(c).str.strip_chars())
                .alias(c)
                for c in text_cols
            ]
        )
        for c in text_cols:
            if stats[f"ws::{c}"]:
                actions.append(
                    CleanAction(c, "trim_whitespace", stats[f"ws::{c}"], "Removed leading/trailing whitespace.")
                )
            if stats[f"null::{c}"]:
                actions.append(
                    CleanAction(
                        c,
                        "normalise_nulls",
                        stats[f"null::{c}"],
                        "Converted placeholders like 'N/A', '-', 'null' to missing.",
                    )
                )

    # 2. Drop columns and rows with no data at all.
    empty_cols = [c for c in df.columns if df[c].null_count() == df.height]
    if empty_cols and len(empty_cols) < df.width:
        df = df.drop(empty_cols)
        for c in empty_cols:
            meta.pop(c, None)
        actions.append(
            CleanAction(
                None, "drop_empty_columns", len(empty_cols), f"Dropped empty columns: {', '.join(empty_cols[:8])}."
            )
        )
    before = df.height
    df = df.filter(~pl.all_horizontal(pl.all().is_null()))
    if df.height < before:
        actions.append(CleanAction(None, "drop_empty_rows", before - df.height, "Dropped rows with no values."))

    # 3. Type inference and conversion.
    conversions: list[pl.Expr] = []
    for c in [c for c in text_cols if c in df.columns]:
        sample = _sample(df[c])
        n = sample.len()
        if n == 0:
            continue
        lowered = sample.str.to_lowercase()
        uniq = set(lowered.unique().to_list())
        if uniq <= (TRUE_TOKENS | FALSE_TOKENS) and uniq - {"0", "1"} and len(uniq) <= 4:
            expr = (
                pl.when(pl.col(c).str.to_lowercase().is_in(list(TRUE_TOKENS)))
                .then(True)
                .when(pl.col(c).str.to_lowercase().is_in(list(FALSE_TOKENS)))
                .then(False)
                .otherwise(None)
            )
            conversions.append(expr.alias(c))
            meta[c].inferred = "boolean"
            actions.append(
                CleanAction(
                    c, "cast_boolean", df[c].drop_nulls().len(), "Unified yes/no/true/false spellings into booleans."
                )
            )
            continue

        digit_len = sample.str.replace_all(r"\D", "").str.len_chars().median() or 0
        leading_zero_ids = (
            sample.str.contains(r"^0\d+$").mean() > 0.1
            or digit_len >= 12
            or bool(_ID_HINT.search(c))
            or sample.str.contains(r"\d[\s-]\d{3,4}[\s-]\d").mean() > 0.5
        )
        rate, european, unit = _numeric_plan(sample)
        if rate >= 0.9 and not leading_zero_ids:
            num = df.select(_numeric_expr(c, european).alias(c)).to_series()
            nonnull = num.drop_nulls()
            integral = nonnull.len() > 0 and bool(((nonnull % 1) == 0).all()) and nonnull.abs().max() < 2**53
            num = num.cast(pl.Int64) if integral else num
            invalid = int(df[c].is_not_null().sum() - num.is_not_null().sum())
            df = df.with_columns(num.alias(c))
            meta[c].inferred = "integer" if integral else "float"
            meta[c].unit = unit
            meta[c].invalid = invalid
            detail = "Parsed numbers"
            if unit:
                detail += f" ({unit.replace('currency:', 'currency ')})"
            if european:
                detail += " using European separators"
            if invalid:
                detail += f"; {invalid} unparseable value(s) set to missing"
            actions.append(CleanAction(c, "cast_numeric", int(num.is_not_null().sum()), detail + "."))
            continue
        if leading_zero_ids and rate >= 0.9:
            actions.append(
                CleanAction(
                    c, "preserve_identifier", 0, "Kept as text: values are codes or identifiers, not quantities."
                )
            )
            meta[c].inferred = "identifier"
            continue

        drate, formats = _date_plan(sample, c)
        if drate >= 0.85 and formats:
            parsed = df.select(_parse_dates(c, formats).alias(c)).to_series()
            nonnull = parsed.drop_nulls()
            if nonnull.len() and bool((nonnull.dt.truncate("1d") == nonnull).all()):
                parsed = parsed.dt.date()
            invalid = int(df[c].is_not_null().sum() - parsed.is_not_null().sum())
            df = df.with_columns(parsed.alias(c))
            meta[c].inferred = "date" if parsed.dtype == pl.Date else "datetime"
            meta[c].formats = formats
            meta[c].invalid = invalid
            detail = f"Parsed dates using {len(formats)} format(s): {', '.join(formats)}"
            if invalid:
                detail += f"; {invalid} unparseable value(s) set to missing"
            actions.append(CleanAction(c, "cast_datetime", int(parsed.is_not_null().sum()), detail + "."))
            continue

        # Categorical text: unify case/spacing variants ("usa", "USA ", "Usa") to the most common form.
        nonnull = df[c].drop_nulls()
        distinct = nonnull.n_unique()
        if distinct <= max(50, int(0.2 * df.height)) and distinct <= 0.8 * nonnull.len():
            key = pl.col(c).str.to_lowercase().str.replace_all(r"\s+", " ")
            canon = (
                df.select(c, key.alias("__k"))
                .drop_nulls()
                .group_by("__k", c)
                .len()
                .sort(["__k", "len", c], descending=[False, True, False])
                .unique("__k", keep="first", maintain_order=True)
                .select("__k", pl.col(c).alias("__canon"))
            )
            if canon.height < distinct:
                mapped = df.select(key.alias("__k"), pl.col(c)).join(canon, on="__k", how="left", maintain_order="left")
                changed = int((mapped["__canon"] != mapped[c]).sum())
                if changed:
                    df = df.with_columns(mapped["__canon"].alias(c))
                    actions.append(
                        CleanAction(
                            c,
                            "unify_categories",
                            changed,
                            f"Merged case/spacing variants into {canon.height} canonical values.",
                        )
                    )
            meta[c].inferred = "categorical"
        else:
            meta[c].inferred = "text"

    if conversions:
        df = df.with_columns(conversions)

    for c, t in df.schema.items():
        if c in meta and c not in text_cols:
            meta[c].inferred = _dtype_kind(t)

    # 4. Exact duplicate rows.
    before = df.height
    df = df.unique(maintain_order=True)
    dupes = before - df.height
    if dupes:
        actions.append(CleanAction(None, "drop_duplicates", dupes, "Removed exact duplicate rows."))

    return CleanResult(df, actions, meta, rows_before, dupes)


def _dtype_kind(t: pl.DataType) -> str:
    if t.is_integer():
        return "integer"
    if t.is_float() or t.is_decimal():
        return "float"
    if t == pl.Boolean:
        return "boolean"
    if t == pl.Date:
        return "date"
    if isinstance(t, pl.Datetime):
        return "datetime"
    return "text"
