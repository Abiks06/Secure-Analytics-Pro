"""Personal-data discovery and privacy transforms.

Detection combines value patterns (with checksum validation where one exists: Luhn for card
numbers, ISO 7064 mod-97 for IBANs) and column-name semantics. Each finding carries a risk level
and a recommended policy; critical and high-risk columns are protected by default, so raw
identifiers never reach previews, queries, exports or the AI assistant unless the owner opts out.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Any, Literal

import polars as pl

Policy = Literal["none", "mask", "hash", "redact"]

RISK = {
    "credit_card": "critical",
    "ssn": "critical",
    "iban": "critical",
    "national_id": "critical",
    "passport": "critical",
    "email": "high",
    "phone": "high",
    "person_name": "high",
    "address": "high",
    "date_of_birth": "high",
    "ip_address": "medium",
    "postal_code": "low",
    "geolocation": "medium",
}
DEFAULT_POLICY: dict[str, Policy] = {"critical": "redact", "high": "mask", "medium": "hash", "low": "none"}

LABELS = {
    "credit_card": "Payment card number",
    "ssn": "US Social Security number",
    "iban": "Bank account (IBAN)",
    "national_id": "National ID",
    "passport": "Passport number",
    "email": "Email address",
    "phone": "Phone number",
    "person_name": "Person name",
    "address": "Street address",
    "date_of_birth": "Date of birth",
    "ip_address": "IP address",
    "postal_code": "Postal code",
    "geolocation": "Geolocation",
}

_EMAIL = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
_PHONE = re.compile(r"^\+?[\d\s().\-]{7,22}$")
_SSN = re.compile(r"^(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}$")
_IPV4 = re.compile(r"^((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)$")
_IPV6 = re.compile(r"^[0-9a-fA-F:]{2,39}$")
_IBAN = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$")
_CARD = re.compile(r"^[\d\s-]{13,23}$")

_HINTS: list[tuple[str, re.Pattern[str]]] = [
    ("email", re.compile(r"e-?mail", re.I)),
    ("phone", re.compile(r"phone|mobile|cell|tel\b|telephone|msisdn", re.I)),
    ("ssn", re.compile(r"\bssn\b|social.?security", re.I)),
    ("national_id", re.compile(r"national.?id|nin\b|\bnid\b|tax.?id|\btin\b|ghana.?card|aadhaar|bvn", re.I)),
    ("passport", re.compile(r"passport", re.I)),
    ("credit_card", re.compile(r"card.?(num|no)|\bpan\b|credit.?card|\bcc.?num", re.I)),
    ("iban", re.compile(r"iban|account.?(num|no)", re.I)),
    ("date_of_birth", re.compile(r"\bdob\b|birth", re.I)),
    ("address", re.compile(r"address|street|addr\b", re.I)),
    ("postal_code", re.compile(r"zip|postal|postcode", re.I)),
    ("ip_address", re.compile(r"\bip\b|ip.?addr", re.I)),
    ("geolocation", re.compile(r"\blat(itude)?\b|\blon(g|gitude)?\b|\bgeo", re.I)),
    (
        "person_name",
        re.compile(
            r"^(full.?|first.?|last.?|middle.?|sur|given.?|family.?|customer.?|patient.?|employee.?|contact.?)?name$",
            re.I,
        ),
    ),
]


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _iban_ok(v: str) -> bool:
    s = v[4:] + v[:4]
    return int("".join(str(int(c, 36)) for c in s)) % 97 == 1


def _match(kind: str, v: str) -> bool:
    if kind == "email":
        return bool(_EMAIL.match(v))
    if kind == "ssn":
        return bool(_SSN.match(v))
    if kind == "ip_address":
        return bool(_IPV4.match(v)) or (v.count(":") >= 2 and bool(_IPV6.match(v)))
    if kind == "credit_card":
        if not _CARD.match(v):
            return False
        digits = re.sub(r"\D", "", v)
        return 13 <= len(digits) <= 19 and _luhn(digits)
    if kind == "iban":
        compact = v.replace(" ", "").upper()
        return bool(_IBAN.match(compact)) and _iban_ok(compact)
    if kind == "phone":
        if not _PHONE.match(v):
            return False
        digits = re.sub(r"\D", "", v)
        return 7 <= len(digits) <= 15 and (v.startswith("+") or bool(re.search(r"[\s().-]", v.strip())))
    return False


VALUE_KINDS = ["email", "credit_card", "ssn", "iban", "ip_address", "phone"]


def detect(df: pl.DataFrame, kinds: dict[str, str], sample_size: int = 2000) -> list[dict[str, Any]]:
    findings = []
    for col in df.columns:
        hint = next((k for k, rx in _HINTS if rx.search(col)), None)
        s = df[col]
        best_kind, best_ratio = None, 0.0
        if s.dtype == pl.String:
            values = s.drop_nulls()
            if values.len() > sample_size:
                values = values.sample(sample_size, seed=11)
            vals = values.to_list()
            if vals:
                for kind in VALUE_KINDS:
                    hits = sum(1 for v in vals if _match(kind, v))
                    ratio = hits / len(vals)
                    if ratio > best_ratio:
                        best_kind, best_ratio = kind, ratio
        confidence = 0.0
        kind = None
        if best_kind and (best_ratio >= 0.6 or (best_ratio >= 0.3 and hint == best_kind)):
            kind = best_kind
            confidence = min(1.0, best_ratio + (0.15 if hint == best_kind else 0))
        elif hint and kinds.get(col) not in ("boolean",):
            if hint == "person_name" and kinds.get(col) not in ("text", "identifier", "categorical"):
                continue
            if hint == "geolocation" and kinds.get(col) != "numeric":
                continue
            if hint in VALUE_KINDS and best_ratio < 0.3:
                # Name says "email" but values don't look like it: weak signal only.
                confidence = 0.4
            else:
                confidence = 0.7
            kind = hint
        if not kind:
            continue
        risk = RISK[kind]
        findings.append(
            {
                "column": col,
                "type": kind,
                "label": LABELS[kind],
                "risk": risk,
                "confidence": round(confidence, 2),
                "match_ratio": round(best_ratio, 3) if best_kind == kind else None,
                "evidence": "value pattern" + (" + column name" if hint == kind else "")
                if best_kind == kind
                else "column name",
                "recommended": DEFAULT_POLICY[risk] if confidence >= 0.6 else "none",
            }
        )
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return sorted(findings, key=lambda f: (order[f["risk"]], -f["confidence"]))


def default_policy(findings: list[dict[str, Any]]) -> dict[str, Policy]:
    return {f["column"]: f["recommended"] for f in findings if f["recommended"] != "none"}


def _mask_expr(col: str, kind: str | None) -> pl.Expr:
    c = pl.col(col).cast(pl.String)
    if kind == "email":
        return c.str.replace(r"^(.)[^@]*@(.)[^.]*(\..*)$", "${1}•••@${2}•••${3}")
    if kind in ("phone", "credit_card", "iban", "ssn", "national_id", "passport"):
        return pl.concat_str(pl.lit("•••• "), c.str.replace_all(r"[^0-9A-Za-z]", "").str.slice(-4))
    if kind == "ip_address":
        return c.str.replace(r"^(\d+\.\d+)\.\d+\.\d+$", "${1}.•.•")
    if kind == "date_of_birth":
        return pl.concat_str(c.str.slice(0, 4), pl.lit("-••-••"))
    if kind == "person_name":
        return c.str.split(" ").list.eval(pl.concat_str(pl.element().str.slice(0, 1), pl.lit("•••"))).list.join(" ")
    return pl.concat_str(c.str.slice(0, 1), pl.lit("•••"), c.str.slice(-1))


def apply_policy(
    df: pl.DataFrame,
    policy: dict[str, str],
    findings: list[dict[str, Any]],
    pseudonym_key: bytes,
) -> pl.DataFrame:
    if not policy:
        return df
    kinds = {f["column"]: f["type"] for f in findings}
    exprs = []
    for col, mode in policy.items():
        if col not in df.columns or mode == "none":
            continue
        not_null = pl.col(col).is_not_null()
        if mode == "redact":
            exprs.append(pl.when(not_null).then(pl.lit("[REDACTED]")).otherwise(None).alias(col))
        elif mode == "mask":
            exprs.append(pl.when(not_null).then(_mask_expr(col, kinds.get(col))).otherwise(None).alias(col))
        elif mode == "hash":
            uniques = df[col].drop_nulls().cast(pl.String).unique().to_list()
            mapping = {
                v: "anon_" + hmac.new(pseudonym_key, v.encode(), hashlib.sha256).hexdigest()[:12] for v in uniques
            }
            exprs.append(
                pl.col(col).cast(pl.String).replace_strict(mapping, default=None, return_dtype=pl.String).alias(col)
            )
    return df.with_columns(exprs) if exprs else df
