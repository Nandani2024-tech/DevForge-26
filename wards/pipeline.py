"""End-to-end firewall pipeline: Pass 1 evidence harvest -> R5/R6/R7/R9 redaction -> export & report."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from wards.channels import (
    ChannelEvidence,
    build_output_rename_map,
    clean_channel_text,
    clean_csv_header,
    clean_dict_keys,
    clean_path_or_url,
    looks_like_path_or_url,
)
from wards.columns import (
    build_fhir_fullurl_map,
    classify_csv_columns,
    classify_header_tokens,
    classify_json_key,
    is_metadata_key,
    json_dict_key_context,
)
from wards.config import NUMERIC_REDACTION_SENTINEL, PLACEHOLDERS, REPORT_SCHEMA, Policy, validate_policy
from wards.ingest import ParsedInput, json_pointer_escape, read_and_parse
from wards.names import extract_name_candidates, redact_names
from wards.patterns import extract_mrn_tokens, redact_identifiers
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

# Structured PII categories whose non-empty cells/leaves are replaced by placeholder constants
_STRUCTURED_PII_KINDS = frozenset(PLACEHOLDERS)
_FHIR_PRESERVE_LEAF_KEYS = frozenset(
    {"resourceType", "id", "fullUrl", "reference", "system", "code", "status", "url"}
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
    """Replace R6 identifiers/phones and R7 names in free text while preserving line count. O(len(text))."""
    cleaned, id_count = redact_identifiers(text)
    cleaned, name_count = redact_names(cleaned)
    stats.identifiers_detected += id_count + name_count
    return cleaned


def _traverse_json(
    value: Any,
    *,
    is_fhir: bool,
    ref_types: dict[str, str] | None,
    ref_key: str,
    on_leaf: Callable[[str, Any, str | None, str | None], Any],
    on_dict_keys: Callable[[list[str], str | None], list[str]] | None = None,
    protected: set[tuple[int, str]] | None = None,
    transform: bool = False,
    parent_key: str | None = None,
    resource_type: str | None = None,
    parent_path: tuple[str, ...] = (),
) -> Any:
    """Single JSON tree walker shared by Pass 1 evidence harvest and Pass 2 redaction.

    Complexity: O(number of JSON nodes).
    """
    if isinstance(value, str):
        if not value.strip():
            return value if transform else None
        semantic = (
            classify_json_key(parent_key, parent_key or "", resource_type, parent_path=parent_path)
            if parent_key
            else "FREE_TEXT"
        )
        res = on_leaf(semantic, value, parent_key, None)
        return res if transform else None

    if isinstance(value, list):
        if transform:
            return [
                _traverse_json(
                    item,
                    is_fhir=is_fhir,
                    ref_types=ref_types,
                    ref_key=ref_key,
                    on_leaf=on_leaf,
                    on_dict_keys=on_dict_keys,
                    protected=protected,
                    transform=True,
                    parent_key=parent_key,
                    resource_type=resource_type,
                    parent_path=parent_path,
                )
                for item in value
            ]
        for item in value:
            _traverse_json(
                item,
                is_fhir=is_fhir,
                ref_types=ref_types,
                ref_key=ref_key,
                on_leaf=on_leaf,
                transform=False,
                parent_key=parent_key,
                resource_type=resource_type,
                parent_path=parent_path,
            )
        return None

    if isinstance(value, dict):
        container_id = id(value)
        cur_res_type = (
            value.get("resourceType")
            if is_fhir and isinstance(value.get("resourceType"), str)
            else resource_type
        )
        ref_target_type: str | None = None
        if is_fhir and ref_types is not None and isinstance(value.get(ref_key), str):
            ref_target_type = ref_types.get(value[ref_key])
        ext_semantic: str | None = None
        if is_fhir and isinstance(value.get("url"), str) and "valueString" in value:
            ext_semantic = classify_header_tokens(value["url"].rsplit("/", 1)[-1])

        orig_keys = list(value.keys())
        out_keys = on_dict_keys(orig_keys, parent_key) if transform and on_dict_keys is not None else orig_keys
        cleaned: dict[str, Any] | None = {} if transform else None

        for k, out_k in zip(orig_keys, out_keys):
            v = value[k]
            if protected is not None and (container_id, k) in protected:
                if cleaned is not None:
                    cleaned[out_k] = v
                continue
            if is_fhir and k in _FHIR_PRESERVE_LEAF_KEYS:
                if cleaned is not None:
                    cleaned[out_k] = v
                continue

            if isinstance(v, (dict, list)):
                sub = _traverse_json(
                    v,
                    is_fhir=is_fhir,
                    ref_types=ref_types,
                    ref_key=ref_key,
                    on_leaf=on_leaf,
                    on_dict_keys=on_dict_keys,
                    protected=protected,
                    transform=transform,
                    parent_key=k,
                    resource_type=cur_res_type,
                    parent_path=(*parent_path[-2:], k),
                )
                if cleaned is not None:
                    cleaned[out_k] = sub
                continue

            if k == "valueString" and ext_semantic is not None:
                semantic = ext_semantic
            else:
                semantic = classify_json_key(
                    parent_key,
                    k,
                    cur_res_type,
                    ref_target_type=ref_target_type,
                    parent_path=parent_path,
                )
            res = on_leaf(semantic, v, parent_key, k)
            if cleaned is not None:
                cleaned[out_k] = res
        return cleaned

    return value if transform else None


def _harvest_json_evidence(
    value: Any,
    evidence: ChannelEvidence,
    *,
    is_fhir: bool = False,
    ref_types: dict[str, str] | None = None,
) -> None:
    """Pass 1: harvest R5/R6/R7 patient/relative name tokens and MRNs via the shared JSON walker."""

    def _on_leaf(semantic: str, leaf_val: Any, p_key: str | None, key: str | None) -> Any:
        if not isinstance(leaf_val, str) or not leaf_val.strip():
            return leaf_val
        if key is None and not p_key:
            return leaf_val
        if semantic in ("PATIENT_NAME", "RELATIVE"):
            evidence.add_name(leaf_val, semantic)
        elif semantic == "MRN":
            evidence.add_mrn(leaf_val)
        elif (
            semantic == "FREE_TEXT"
            and not looks_like_path_or_url(leaf_val)
            and (key is None or not is_metadata_key(p_key, key))
        ):
            for surf, kind in extract_name_candidates(leaf_val):
                evidence.add_name(surf, kind)
            for mrn_tok in extract_mrn_tokens(leaf_val):
                evidence.add_mrn(mrn_tok)
        return leaf_val

    _traverse_json(
        value,
        is_fhir=is_fhir,
        ref_types=ref_types,
        ref_key="reference",
        on_leaf=_on_leaf,
        transform=False,
    )


def _harvest_parsed_evidence(parsed: ParsedInput, evidence: ChannelEvidence) -> None:
    """Pass 1: collect verified patient/relative name tokens and MRN cores from one parsed file.

    Never harvests doctor tokens. Keeps only tokens/cores in memory.
    Complexity: O(bytes in parsed).
    """
    if parsed.kind == "csv":
        assert parsed.rows is not None
        header = parsed.rows[0]
        body = parsed.rows[1:]
        preferred_col = select_csv_slot_column(header, body)
        col_types = classify_csv_columns(header, body)
        for row in body:
            slot = find_csv_slot(header, row, preferred_col=preferred_col)
            if slot is not None:
                evidence.add_mrn(slot[1])
            for idx, cell in enumerate(row):
                if not cell.strip():
                    continue
                col_kind = col_types[idx] if idx < len(col_types) else "FREE_TEXT"
                if col_kind in ("PATIENT_NAME", "RELATIVE"):
                    evidence.add_name(cell, col_kind)
                elif col_kind == "MRN":
                    evidence.add_mrn(cell)
                elif col_kind == "FREE_TEXT":
                    for surf, kind in extract_name_candidates(cell):
                        evidence.add_name(surf, kind)
                    for mrn_tok in extract_mrn_tokens(cell):
                        evidence.add_mrn(mrn_tok)
        return

    if parsed.kind in ("json", "fhir"):
        is_fhir = parsed.kind == "fhir"
        ref_types = build_fhir_fullurl_map(parsed.data) if is_fhir else None
        _harvest_json_evidence(parsed.data, evidence, is_fhir=is_fhir, ref_types=ref_types)
        return

    assert parsed.text is not None
    span = find_text_slot_span(parsed.text)
    if span is not None:
        evidence.add_mrn(span[2])
    for mrn_tok in extract_mrn_tokens(parsed.text):
        evidence.add_mrn(mrn_tok)
    for surf, kind in extract_name_candidates(parsed.text):
        evidence.add_name(surf, kind)


def _clean_json_values(
    value: Any,
    stats: PipelineStats,
    protected: set[tuple[int, str]],
    evidence: ChannelEvidence,
    preserve_fhir_refs: bool = False,
    ref_types: dict[str, str] | None = None,
) -> Any:
    """Clean JSON keys, path/URL metadata, and leaves via the shared JSON walker.

    Complexity: O(number of JSON nodes + total string bytes).
    """

    def _on_leaf(semantic: str, leaf_val: Any, p_key: str | None, key: str | None) -> Any:
        if isinstance(leaf_val, str):
            if not leaf_val.strip():
                return leaf_val
            if semantic in _STRUCTURED_PII_KINDS:
                stats.identifiers_detected += 1
                return PLACEHOLDERS[semantic]
            if semantic == "PRESERVE_EXACT":
                return leaf_val
            if looks_like_path_or_url(leaf_val):
                c_val, cnt = clean_path_or_url(leaf_val, evidence, filename_safe=False)
                stats.identifiers_detected += cnt
                return c_val
            if key is not None and is_metadata_key(p_key, key):
                c_val, cnt = clean_channel_text(leaf_val, evidence, filename_safe=False)
                stats.identifiers_detected += cnt
                return clean_text(c_val, stats)
            return clean_text(leaf_val, stats)
        if isinstance(leaf_val, int) and not isinstance(leaf_val, bool):
            # Preserve integer JSON value type while removing numeric PII (e.g. integer Aadhaar/PIN)
            if semantic in _STRUCTURED_PII_KINDS:
                stats.identifiers_detected += 1
                return NUMERIC_REDACTION_SENTINEL
        return leaf_val

    def _on_dict_keys(orig_keys: list[str], p_key: str | None) -> list[str]:
        key_ctx = json_dict_key_context(p_key) if not preserve_fhir_refs else None
        out_keys, key_clean_count = clean_dict_keys(orig_keys, evidence, key_context=key_ctx)
        stats.identifiers_detected += key_clean_count
        return out_keys

    return _traverse_json(
        value,
        is_fhir=preserve_fhir_refs,
        ref_types=ref_types,
        ref_key="reference",
        on_leaf=_on_leaf,
        on_dict_keys=_on_dict_keys,
        protected=protected,
        transform=True,
    )


def _process_csv(
    parsed: ParsedInput,
    make_psn: Any,
    stats: PipelineStats,
    evidence: ChannelEvidence,
) -> tuple[str, list[dict[str, Any]]]:
    """Process one CSV/TSV file with column classification, header cleaning, and slot PSN. O(cells)."""
    assert parsed.rows is not None
    header = parsed.rows[0]
    body = parsed.rows[1:]
    preferred_col = select_csv_slot_column(header, body)
    col_types = classify_csv_columns(header, body)
    cleaned_header, hdr_cnt = clean_csv_header(header, evidence)
    stats.identifiers_detected += hdr_cnt

    out_rows: list[list[str]] = [cleaned_header]
    recs: list[dict[str, Any]] = []

    for row_idx, row in enumerate(body):
        slot = find_csv_slot(header, row, preferred_col=preferred_col)
        slot_col = slot[0] if slot is not None else None
        psn = make_psn(normalise_slot_value(slot[1])) if slot is not None else None

        out_row: list[str] = []
        for idx, cell in enumerate(row):
            if idx == slot_col and psn is not None:
                out_row.append(psn)
                continue
            col_kind = col_types[idx] if idx < len(col_types) else "FREE_TEXT"
            if col_kind in _STRUCTURED_PII_KINDS:
                if cell.strip():
                    stats.identifiers_detected += 1
                    out_row.append(PLACEHOLDERS[col_kind])
                else:
                    out_row.append(cell)
            elif col_kind == "PRESERVE_EXACT":
                out_row.append(cell)
            elif looks_like_path_or_url(cell):
                c_val, cnt = clean_path_or_url(cell, evidence, filename_safe=False)
                stats.identifiers_detected += cnt
                out_row.append(c_val)
            else:
                out_row.append(clean_text(cell, stats))

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
    evidence: ChannelEvidence,
) -> tuple[str, list[dict[str, Any]]]:
    """Process one JSON or FHIR Bundle file. O(nodes)."""
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
        orig_top_keys = list(data.keys())
        cleaned_top_keys, _ = clean_dict_keys(orig_top_keys, evidence)
        top_key_map = dict(zip(orig_top_keys, cleaned_top_keys))
        for key, val in data.items():
            if isinstance(val, list) and val and all(isinstance(item, dict) for item in val):
                # Never emit a raw PII key into a records.jsonl pointer (SPEC sec 6 / R17)
                escaped_key = json_pointer_escape(str(top_key_map[key]))
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

    ref_types = build_fhir_fullurl_map(data) if is_fhir else None
    cleaned = _clean_json_values(
        data,
        stats,
        protected,
        evidence,
        preserve_fhir_refs=is_fhir,
        ref_types=ref_types,
    )
    return serialize_json(cleaned), recs


def _process_text(
    parsed: ParsedInput,
    make_psn: Any,
    stats: PipelineStats,
) -> tuple[str, list[dict[str, Any]]]:
    """Process one plain-text file preserving line count. O(len(text))."""
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
    """Run the two-pass firewall pipeline on inp and write outputs into out.

    Pass 1 harvests name tokens and MRN cores only (never keeping file contents).
    Pass 2 computes collision-free renames and exports sanitized files, records, and report.
    Complexity: O(total input bytes).
    """
    validate_policy(policy)
    t0 = time.monotonic()
    san_dir = out / "sanitized"
    san_dir.mkdir(parents=True, exist_ok=True)

    def make_psn(norm_value: str) -> str:
        return pseudonym(slot_patient_key(norm_value), secret)

    stats = PipelineStats()
    evidence = ChannelEvidence()
    quarantined_map: dict[str, tuple[str, str]] = {}
    sanitizable_paths: list[tuple[Path, str, str]] = []

    with MemorySampler() as sampler:
        input_files = sorted(
            (p for p in inp.rglob("*") if p.is_file()),
            key=lambda p: p.relative_to(inp).as_posix(),
        )

        # Pass 1: validate files and harvest run-time token/MRN evidence
        for path in input_files:
            rel_posix = path.relative_to(inp).as_posix()
            sha256_hex, parsed, reason = read_and_parse(path, rel_posix)
            if parsed is None:
                quarantined_map[rel_posix] = (sha256_hex, reason or "quarantined")
                continue
            try:
                _harvest_parsed_evidence(parsed, evidence)
            except (ValueError, UnicodeError, RecursionError):
                quarantined_map[rel_posix] = (sha256_hex, "processing_error")
                continue
            sanitizable_paths.append((path, rel_posix, sha256_hex))

        rename_map = build_output_rename_map([rel for _, rel, _ in sanitizable_paths], evidence)
        pass2_lookup = {rel: (path, sha256_hex) for path, rel, sha256_hex in sanitizable_paths}

        file_entries: list[dict[str, Any]] = []
        all_records: list[dict[str, Any]] = []

        # Pass 2: clean content + hidden channels in deterministic sorted order
        for path in input_files:
            rel_posix = path.relative_to(inp).as_posix()
            if rel_posix in quarantined_map:
                sha256_hex, reason = quarantined_map[rel_posix]
                file_entries.append(
                    {"input_sha256": sha256_hex, "output": None, "status": "quarantined", "reason": reason}
                )
                continue

            _, expected_sha = pass2_lookup[rel_posix]
            sha256_hex, parsed, reason = read_and_parse(path, rel_posix)
            if parsed is None:
                file_entries.append(
                    {
                        "input_sha256": sha256_hex or expected_sha,
                        "output": None,
                        "status": "quarantined",
                        "reason": reason or "quarantined",
                    }
                )
                continue

            out_rel_posix = rename_map[rel_posix]
            try:
                if parsed.kind == "csv":
                    content, file_recs = _process_csv(parsed, make_psn, stats, evidence)
                elif parsed.kind in ("json", "fhir"):
                    content, file_recs = _process_json(parsed, make_psn, stats, evidence)
                else:
                    content, file_recs = _process_text(parsed, make_psn, stats)
            except (ValueError, UnicodeError, RecursionError):
                file_entries.append(
                    {
                        "input_sha256": sha256_hex,
                        "output": None,
                        "status": "quarantined",
                        "reason": "processing_error",
                    }
                )
                continue

            for rec in file_recs:
                rec["file"] = f"sanitized/{out_rel_posix}"
            write_sanitized_text(san_dir / out_rel_posix, content)
            file_entries.append(
                {
                    "input_sha256": sha256_hex,
                    "output": f"sanitized/{out_rel_posix}",
                    "status": "sanitized",
                }
            )
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
