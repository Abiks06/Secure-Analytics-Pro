"""Format detection and parsing.

The file extension and the client-supplied content type are never trusted: the format is decided
from the bytes themselves (magic numbers, structure sniffing). Text is transcoded to UTF-8 using
statistical charset detection, the delimiter is sniffed, and compressed uploads are inflated with
a hard ceiling to defuse decompression bombs.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import zipfile
from dataclasses import dataclass, field

import polars as pl
from charset_normalizer import from_bytes


class IngestError(ValueError):
    """The upload is not a dataset we can safely parse. The message is safe to show users."""


@dataclass
class IngestResult:
    frame: pl.DataFrame
    format: str
    encoding: str | None = None
    delimiter: str | None = None
    compressed: bool = False
    notes: list[str] = field(default_factory=list)


_DELIMITERS = [",", ";", "\t", "|"]


def _inflate(data: bytes, limit: int) -> bytes:
    out = bytearray()
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
        while chunk := gz.read(1 << 20):
            out += chunk
            if len(out) > limit:
                raise IngestError("Decompressed size exceeds the allowed limit.")
    return bytes(out)


def detect_format(data: bytes) -> str:
    head = data[:8]
    if head.startswith(b"PAR1"):
        return "parquet"
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = zf.namelist()
        except zipfile.BadZipFile as e:
            raise IngestError("Corrupt ZIP container.") from e
        if any(n.startswith("xl/") for n in names):
            return "xlsx"
        raise IngestError("ZIP archives are only accepted as Excel workbooks.")
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        raise IngestError("Legacy .xls is not supported. Save the workbook as .xlsx or CSV.")
    sample = data[:65536]
    if sample.count(b"\x00") > len(sample) // 100 and not sample.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise IngestError("This looks like a binary file, not a dataset.")
    stripped = sample.lstrip(b"\xef\xbb\xbf \t\r\n")
    if stripped[:1] == b"[":
        return "json"
    if stripped[:1] == b"{":
        lines = [ln.strip() for ln in stripped.splitlines()[:5] if ln.strip()]
        if len(lines) > 1 and all(ln.startswith(b"{") and ln.endswith(b"}") for ln in lines[:-1]):
            return "ndjson"
        return "json"
    return "delimited"


def _decode(data: bytes) -> tuple[str, str]:
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace"), "utf-8-sig"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    match = from_bytes(data[: 1 << 20]).best()
    enc = match.encoding if match else "cp1252"
    # Single-byte code pages are hard to tell apart on short samples; most non-UTF-8 CSVs come
    # from Excel on Western Windows, so prefer cp1252 whenever it decodes the bytes cleanly.
    if enc.startswith(("cp125", "iso8859", "latin", "mac_")) and enc != "cp1252":
        try:
            return data.decode("cp1252"), "cp1252"
        except UnicodeDecodeError:
            pass
    return data.decode(enc, errors="replace"), enc


def _sniff_delimiter(text: str) -> str:
    sample = "\n".join(text[:65536].splitlines()[:50])
    try:
        return csv.Sniffer().sniff(sample, delimiters="".join(_DELIMITERS)).delimiter
    except csv.Error:
        lines = [ln for ln in sample.splitlines() if ln.strip()][:20]
        best, best_score = ",", -1.0
        for d in _DELIMITERS:
            counts = [ln.count(d) for ln in lines]
            if not counts or max(counts) == 0:
                continue
            mean = sum(counts) / len(counts)
            consistency = sum(1 for c in counts if c == counts[0]) / len(counts)
            score = mean * consistency
            if score > best_score:
                best, best_score = d, score
        return best


def _flatten(df: pl.DataFrame, max_depth: int = 3) -> pl.DataFrame:
    """Unnest struct columns into ``parent.child`` columns; render lists as JSON text."""
    for _ in range(max_depth):
        structs = [c for c, t in df.schema.items() if isinstance(t, pl.Struct)]
        if not structs:
            break
        for c in structs:
            fields = df[c].struct.fields
            df = df.with_columns([pl.col(c).struct.field(f).alias(f"{c}.{f}") for f in fields]).drop(c)
    lists = [c for c, t in df.schema.items() if isinstance(t, (pl.List, pl.Array, pl.Struct))]
    if lists:
        df = df.with_columns(
            [
                pl.col(c).map_elements(
                    lambda v: json.dumps(v.to_list() if hasattr(v, "to_list") else v, default=str),
                    return_dtype=pl.String,
                )
                for c in lists
            ]
        )
    return df


def _read_json(text: str, ndjson: bool) -> pl.DataFrame:
    try:
        if ndjson:
            records = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
        else:
            payload = json.loads(text)
            if isinstance(payload, dict):
                # Common API shape: {"data": [...]} / {"results": [...]}; else a single record.
                arrays = [v for v in payload.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
                records = max(arrays, key=len) if arrays else [payload]
            else:
                records = payload
    except json.JSONDecodeError as e:
        raise IngestError(f"Invalid JSON at line {e.lineno}, column {e.colno}.") from e
    if not isinstance(records, list) or not records:
        raise IngestError("JSON must contain an array of records.")
    if not all(isinstance(r, dict) for r in records):
        records = [{"value": r} for r in records]
    try:
        df = pl.from_dicts(records, infer_schema_length=None)
    except Exception:
        # Heterogeneous types across records: fall back to string columns.
        keys = list(dict.fromkeys(k for r in records for k in r))
        df = pl.DataFrame(
            {
                k: [
                    None if r.get(k) is None else (r[k] if isinstance(r[k], str) else json.dumps(r[k])) for r in records
                ]
                for k in keys
            },
            schema={k: pl.String for k in keys},
        )
    return _flatten(df)


def read_dataset(data: bytes, *, max_decompressed: int) -> IngestResult:
    if not data.strip():
        raise IngestError("The file is empty.")
    compressed = data[:2] == b"\x1f\x8b"
    if compressed:
        data = _inflate(data, max_decompressed)
    fmt = detect_format(data)
    notes: list[str] = []

    if fmt == "parquet":
        try:
            df = pl.read_parquet(io.BytesIO(data))
        except Exception as e:
            raise IngestError("Corrupt or unsupported Parquet file.") from e
        return IngestResult(_flatten(df), fmt, compressed=compressed)

    if fmt == "xlsx":
        try:
            sheets = pl.read_excel(io.BytesIO(data), sheet_id=0, engine="calamine", infer_schema_length=0)
        except Exception as e:
            raise IngestError("Could not read the Excel workbook.") from e
        name, df = max(sheets.items(), key=lambda kv: kv[1].height)
        if len(sheets) > 1:
            notes.append(f"Workbook has {len(sheets)} sheets; analysed the largest, '{name}'.")
        return IngestResult(df, fmt, compressed=compressed, notes=notes)

    text, encoding = _decode(data)
    if encoding not in ("utf-8", "utf-8-sig", "ascii"):
        notes.append(f"Transcoded from {encoding} to UTF-8.")

    if fmt in ("json", "ndjson"):
        return IngestResult(_read_json(text, fmt == "ndjson"), fmt, encoding, compressed=compressed, notes=notes)

    delimiter = _sniff_delimiter(text)
    try:
        df = pl.read_csv(
            io.StringIO(text),
            separator=delimiter,
            infer_schema=False,  # Everything as text; the cleaner infers types robustly.
            truncate_ragged_lines=True,
            ignore_errors=True,
            quote_char='"',
        )
    except Exception as e:
        raise IngestError("Could not parse the file as delimited text.") from e
    if df.width == 1 and delimiter == ",":
        notes.append("Only one column detected; the file may not be delimited.")
    return IngestResult(
        df,
        "csv" if delimiter == "," else "tsv" if delimiter == "\t" else "delimited",
        encoding,
        delimiter,
        compressed,
        notes,
    )
