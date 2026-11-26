"""Deterministic UTF-8 writers for sanitized/, records.jsonl, and report.json."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any


def serialize_csv(rows: list[list[str]], delimiter: str) -> str:
    """Serialize CSV/TSV rows in UTF-8 with LF line endings. O(cells)."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=delimiter, lineterminator="\n")
    writer.writerows(rows)
    return buf.getvalue()


def serialize_json(data: Any) -> str:
    """Serialize JSON preserving structure and types with trailing newline. O(nodes)."""
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def write_sanitized_text(dest: Path, content: str) -> None:
    """Write UTF-8 text atomically to sanitized/<rel>. O(bytes)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8", newline="")


def write_records_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """Write records.jsonl deterministically. O(len(records))."""
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")


def write_report_json(path: Path, report: dict[str, Any]) -> None:
    """Write report.json in UTF-8. O(len(files))."""
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
