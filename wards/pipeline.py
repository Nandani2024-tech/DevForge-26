"""End-to-end scaffold pipeline: ingest -> slot PSN + baseline clean -> export & report."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wards.config import REPORT_SCHEMA, Policy, validate_policy
from wards.ingest import ParsedInput, json_pointer_escape, read_and_parse
from wards.pseudo import pseudonym, slot_patient_key
from wards.resources import MemorySampler
from wards.slots import (
    find_csv_slot,
    find_text_slot_span,
    is_document_json,
    normalise_slot_value,
    replace_fhir_slot,
    replace_json_slot,
    select_csv_slot_column,
)
from wards.writers import (
    serialize_csv,
    serialize_json,
    write_records_jsonl,
    write_report_json,
    write_sanitized_text,
)

# Baseline regexes carried from starter (horizontal whitespace only so line counts stay exact)
_BASELINE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("PHONE", re.compile(r"(?<!\d)(?:\+?91[ \t-]?)?[6-9]\d{4}[ \t-]?\d{5}(?!\d)")),
    ("AADHAAR", re.compile(r"(?<!\d)\d{4}[ \t-]?\d{4}[ \t-]?\d{4}(?!\d)")),
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("NAME", re.compile(r"(?i)(?<=name:)[ \t]*[^\n,;|]+")),
)


@dataclass
class PipelineStats:
    """Mutable counters aggregated during a single pipeline run."""

    identifiers_detected: int = 0
    records_processed: int = 0
    records_linked: int = 0
    records_generalized: int = 0
    records_suppressed: int = 0
    records_quarantined: int = 0


@dataclass(frozen=True)
class PipelineResult:
    """Outputs and summary counts returned by run_pipeline."""

    report: dict[str, Any]
    records: list[dict[str, Any]]


def clean_text(text: str, stats: PipelineStats) -> str:
    """Replace baseline identifiers in text while preserving line count. O(len(text))."""
    for kind, rx in _BASELINE_PATTERNS:
        repl = f"[{kind}]" if kind != "NAME" else " [NAME]"
        text, n = rx.subn(repl, text)
        stats.identifiers_detected += n
    return text


def _clean_json_values(
    value: Any,
    stats: PipelineStats,
    protected: set[tuple[int, str]],
    preserve_fhir_refs: bool = False,
) -> Any:
    """Clean string leaves in JSON while preserving keys, structure, value types, and PSN slots."""
    if isinstance(value, str):
        return clean_text(value, stats)
    if isinstance(value, list):
        return [_clean_json_values(item, stats, protected, preserve_fhir_refs) for item in value]
    if isinstance(value, dict):
        container_id = id(value)
        cleaned: dict[str, Any] = {}
        for k, v in value.items():
            if (container_id, k) in protected:
                cleaned[k] = v
            elif preserve_fhir_refs and k in ("resourceType", "id", "fullUrl", "reference"):
                cleaned[k] = v
            else:
                cleaned[k] = _clean_json_values(v, stats, protected, preserve_fhir_refs)
        return cleaned
    return value


def _process_csv(
    parsed: ParsedInput,
    make_psn: Any,
    stats: PipelineStats,
) -> tuple[str, list[dict[str, Any]]]:
    assert parsed.rows is not None
    header = parsed.rows[0]
    body = parsed.rows[1:]
    preferred_col = select_csv_slot_column(header, body)
    out_rows: list[list[str]] = [list(header)]
    recs: list[dict[str, Any]] = []

    for row_idx, row in enumerate(body):
        slot = find_csv_slot(header, row, preferred_col=preferred_col)
        if slot is not None:
            col_idx, raw_val = slot
            psn = make_psn(normalise_slot_value(raw_val))
            out_row = [
                psn if idx == col_idx else clean_text(cell, stats)
                for idx, cell in enumerate(row)
            ]
        else:
            psn = None
            out_row = [clean_text(cell, stats) for cell in row]
        out_rows.append(out_row)
        recs.append({"file": f"sanitized/{parsed.rel_posix}", "loc": f"row:{row_idx}", "patient": psn})
        stats.records_processed += 1
        if psn is not None:
            stats.records_linked += 1

    return serialize_csv(out_rows, parsed.delimiter), recs


def _process_json(
    parsed: ParsedInput,
    make_psn: Any,
    stats: PipelineStats,
) -> tuple[str, list[dict[str, Any]]]:
    data = parsed.data
    protected: set[tuple[int, str]] = set()
    recs: list[dict[str, Any]] = []
    is_fhir = parsed.kind == "fhir"

    if is_fhir:
        psn, prot = replace_fhir_slot(data, make_psn)
        if prot is not None:
            protected.add(prot)
        recs.append({"file": f"sanitized/{parsed.rel_posix}", "loc": "doc", "patient": psn})
        stats.records_processed += 1
        if psn is not None:
            stats.records_linked += 1
    elif is_document_json(data):
        psn, prot = replace_json_slot(data, make_psn)
        if prot is not None:
            protected.add(prot)
        recs.append({"file": f"sanitized/{parsed.rel_posix}", "loc": "doc", "patient": psn})
        stats.records_processed += 1
        if psn is not None:
            stats.records_linked += 1
    else:
        for key, val in data.items():
            if isinstance(val, list) and val and all(isinstance(item, dict) for item in val):
                escaped_key = json_pointer_escape(str(key))
                for idx, item in enumerate(val):
                    psn, prot = replace_json_slot(item, make_psn)
                    if prot is not None:
                        protected.add(prot)
                    recs.append(
                        {
                            "file": f"sanitized/{parsed.rel_posix}",
                            "loc": f"/{escaped_key}/{idx}",
                            "patient": psn,
                        }
                    )
                    stats.records_processed += 1
                    if psn is not None:
                        stats.records_linked += 1

    cleaned = _clean_json_values(data, stats, protected, preserve_fhir_refs=is_fhir)
    return serialize_json(cleaned), recs


def _process_text(
    parsed: ParsedInput,
    make_psn: Any,
    stats: PipelineStats,
) -> tuple[str, list[dict[str, Any]]]:
    assert parsed.text is not None
    text = parsed.text
    span = find_text_slot_span(text)

    if span is not None:
        start, end, raw_val = span
        psn = make_psn(normalise_slot_value(raw_val))
        sanitized_text = clean_text(text[:start], stats) + psn + clean_text(text[end:], stats)
    else:
        psn = None
        sanitized_text = clean_text(text, stats)

    rec = {"file": f"sanitized/{parsed.rel_posix}", "loc": "doc", "patient": psn}
    stats.records_processed += 1
    if psn is not None:
        stats.records_linked += 1
    return sanitized_text, [rec]


def run_pipeline(inp: Path, out: Path, secret: bytes, policy: Policy) -> PipelineResult:
    """Run the end-to-end firewall pipeline on inp and write outputs into out.

    Complexity: O(total input bytes).
    """
    validate_policy(policy)
    t0 = time.monotonic()
    san_dir = out / "sanitized"
    san_dir.mkdir(parents=True, exist_ok=True)

    def make_psn(norm_value: str) -> str:
        return pseudonym(slot_patient_key(norm_value), secret)

    stats = PipelineStats()
    file_entries: list[dict[str, Any]] = []
    all_records: list[dict[str, Any]] = []

    with MemorySampler() as sampler:
        input_files = sorted(
            (p for p in inp.rglob("*") if p.is_file()),
            key=lambda p: p.relative_to(inp).as_posix(),
        )
        for path in input_files:
            rel_posix = path.relative_to(inp).as_posix()
            sha256_hex, parsed, reason = read_and_parse(path, rel_posix)
            entry: dict[str, Any] = {"input_sha256": sha256_hex}

            if parsed is None:
                entry.update(output=None, status="quarantined", reason=reason or "quarantined")
                file_entries.append(entry)
                continue

            if parsed.kind == "csv":
                content, file_recs = _process_csv(parsed, make_psn, stats)
            elif parsed.kind in ("json", "fhir"):
                content, file_recs = _process_json(parsed, make_psn, stats)
            else:
                content, file_recs = _process_text(parsed, make_psn, stats)

            write_sanitized_text(san_dir / rel_posix, content)
            entry.update(output=f"sanitized/{rel_posix}", status="sanitized")
            file_entries.append(entry)
            all_records.extend(file_recs)

        write_records_jsonl(out / "records.jsonl", all_records)
        peak_rss_mb = sampler.stop()

    n_san = sum(1 for e in file_entries if e["status"] == "sanitized")
    n_quar = len(file_entries) - n_san
    report = {
        "schema": REPORT_SCHEMA,
        "files": file_entries,
        "counts": {
            "files_total": len(file_entries),
            "files_sanitized": n_san,
            "files_quarantined": n_quar,
            "records_processed": len(all_records),
            "identifiers_detected": stats.identifiers_detected,
            "records_linked": sum(1 for r in all_records if r["patient"] is not None),
            "records_generalized": stats.records_generalized,
            "records_suppressed": stats.records_suppressed,
            "records_quarantined": stats.records_quarantined,
        },
        "timing": {"seconds": round(time.monotonic() - t0, 2)},
        "resources": {"peak_rss_mb": peak_rss_mb},
    }
    write_report_json(out / "report.json", report)

    return PipelineResult(report=report, records=all_records)
