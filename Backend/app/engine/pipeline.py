"""The analysis pipeline: bytes in, cleaned frame + full report out.

Pure and synchronous on purpose: it runs in a worker thread, reports progress through a
callback, and has no I/O or database dependencies, which keeps it trivially testable.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import polars as pl

from app.engine import clean as cleaning
from app.engine import insights, pii
from app.engine.ingest import read_dataset
from app.engine.profile import profile

STAGES = [
    ("validate", "Validating file signature"),
    ("parse", "Parsing & decoding"),
    ("clean", "Cleaning & type inference"),
    ("profile", "Profiling columns"),
    ("privacy", "Scanning for personal data"),
    ("insights", "Discovering insights"),
    ("secure", "Encrypting & storing"),
]

Progress = Callable[[str, float, str | None], None]


@dataclass
class PipelineOutput:
    frame: pl.DataFrame
    report: dict[str, Any]
    policy: dict[str, str]
    source_format: str


def run(data: bytes, *, max_decompressed: int, progress: Progress | None = None) -> PipelineOutput:
    timings: dict[str, float] = {}
    notify = progress or (lambda *_: None)
    total = len(STAGES)

    def stage(i: int, msg: str | None = None):
        notify(STAGES[i][0], i / total, msg)
        return time.perf_counter()

    t = stage(0)
    t = stage(1)
    timings["validate"] = 0.0
    ingested = read_dataset(data, max_decompressed=max_decompressed)
    timings["parse"] = time.perf_counter() - t
    if ingested.frame.height == 0 or ingested.frame.width == 0:
        from app.engine.ingest import IngestError

        raise IngestError("No rows or columns were found in the file.")

    t = stage(2, f"{ingested.frame.height:,} rows × {ingested.frame.width} columns")
    cleaned = cleaning.clean(ingested.frame)
    timings["clean"] = time.perf_counter() - t

    t = stage(3)
    prof = profile(cleaned)
    timings["profile"] = time.perf_counter() - t

    t = stage(4)
    kinds = {c["name"]: c["kind"] for c in prof["columns"]}
    findings = pii.detect(cleaned.frame, kinds)
    timings["privacy"] = time.perf_counter() - t

    t = stage(5)
    units = {c: m.unit for c, m in cleaned.meta.items()}
    discovered = insights.generate(cleaned.frame, prof, units)
    if findings:
        critical = [f for f in findings if f["risk"] in ("critical", "high")]
        if critical:
            discovered["insights"].insert(
                0,
                {
                    "id": "privacy-0",
                    "kind": "privacy",
                    "severity": "critical" if any(f["risk"] == "critical" for f in critical) else "warning",
                    "title": f"{len(critical)} column(s) contain sensitive personal data",
                    "body": "Detected "
                    + ", ".join(f"{f['label'].lower()} in '{f['column']}'" for f in critical[:4])
                    + ". These are masked or redacted by default in previews, queries, exports and AI answers.",
                    "score": 1.0,
                    "columns": [f["column"] for f in critical],
                    "chart": None,
                    "metric": {"label": "sensitive columns", "value": len(critical)},
                },
            )
    timings["insights"] = time.perf_counter() - t

    report = {
        "ingest": {
            "format": ingested.format,
            "encoding": ingested.encoding,
            "delimiter": ingested.delimiter,
            "compressed": ingested.compressed,
            "notes": ingested.notes,
        },
        "cleaning": {
            "actions": [a.to_dict() for a in cleaned.actions],
            "columns": {c: m.to_dict() for c, m in cleaned.meta.items()},
        },
        **prof,
        "privacy": {"findings": findings},
        **discovered,
        "timings_ms": {k: round(v * 1000, 1) for k, v in timings.items()},
    }
    return PipelineOutput(cleaned.frame, report, pii.default_policy(findings), ingested.format)
