"""End-to-end two-pass firewall pipeline: Pass 1 evidence + R10 linkage -> R5-R13 export."""
from __future__ import annotations

import codecs
import json
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from wards.channels import (
    Base64Format,
    ChannelEvidence,
    base64_placeholder_encoded,
    build_output_rename_map,
    clean_channel_text,
    clean_csv_header,
    clean_dict_keys,
    clean_path_or_url,
    decode_base64_payload,
    decode_printable_utf8,
    encode_base64_payload,
    is_binary_magic,
    looks_like_path_or_url,
    redact_known_names_in_text,
)
from wards.columns import (
    build_fhir_fullurl_map,
    classify_address_value_shape,
    classify_csv_columns,
    classify_header_tokens,
    classify_json_key,
    collect_list_preserve_overrides,
    find_non_patient_mrn_cols,
    is_metadata_key,
    json_dict_key_context,
    json_leaf_has_known_meaning,
)
from wards.config import (
    BASE64_BINARY_REASON,
    BASE64_DEPTH_REASON,
    BASE64_INVALID_REASON,
    BASE64_MAX_DEPTH,
    BASE64_MIN_EXPLICIT_LEN,
    BASE64_MIN_LEN,
    COLUMN_VOTE_SAMPLE_CAP,
    LOCATION_DETAIL_KINDS,
    NUMERIC_REDACTION_SENTINEL,
    PLACEHOLDERS,
    REPORT_SCHEMA,
    Policy,
    validate_policy,
)
from wards.dates import (
    DATE_ORDER_DMY,
    count_date_order_votes,
    date_order_evidence,
    infer_date_order,
    parse_dob_iso,
    resolve_date_order,
    shift_dates_in_text,
)
from wards.generalise import (
    generalise_address_field,
    generalise_age_field,
    generalise_age_int,
    generalise_pin_int,
    generalise_pin_str,
    generalise_text_qis,
)
from wards.ingest import ParsedInput, is_json_content, json_pointer_escape, read_and_parse
from wards.linkage import RecordEvidence, link_records, normalise_name_key, normalise_strong_id
from wards.names import extract_name_candidates, redact_names
from wards.patterns import (
    classify_value_shape,
    extract_mrn_tokens,
    find_identifier_spans,
    redact_identifiers,
    split_data_uri_base64,
)
from wards.pseudo import date_shift_days, pseudonym
from wards.resources import MemorySampler
from wards.slots import (
    csv_slot_priorities,
    find_csv_slot,
    find_csv_slot_or_fallback,
    find_text_slot_span,
    inject_psn_into_text,
    is_document_json,
    is_non_patient_id_key,
    select_csv_slot_column,
    write_fhir_slot_psn,
    write_json_slot_psn,
)
from wards.writers import (
    serialize_csv,
    serialize_json,
    write_records_jsonl,
    write_report_json,
    write_sanitized_text,
)

# Structured PII categories redacted by placeholder (excludes DOB/PIN handled by R12/R13)
_STRUCTURED_PII_KINDS = frozenset(PLACEHOLDERS) - frozenset({"DOB", "PIN", "ADDRESS", "AGE"})
_STRONG_ID_KINDS = frozenset(
    {"MRN", "AADHAAR", "ABHA", "ABHA_ADDRESS", "PHONE", "PAN", "INSURANCE", "EMAIL"}
)
_FHIR_PRESERVE_LEAF_KEYS = frozenset(
    {"resourceType", "id", "fullUrl", "reference", "system", "code", "status", "url", "contentType"}
)

_B64_NONE = 0
_B64_TEXT = 1
_B64_JSON = 2
_B64_REDACT = 3


@dataclass(frozen=True)
class _Base64Inspection:
    """Single-pass decoded base64 state shared across date voting, Pass 1, and Pass 2."""

    kind: int
    uri_prefix: str = ""
    fmt: Base64Format | None = None
    text: str | None = None
    json_obj: Any = None
    reason: str | None = None


def _b64_binary_or_depth_reason(b64_depth: int) -> str:
    """Return depth-limit reason when nesting reached BASE64_MAX_DEPTH, else binary reason. O(1)."""
    return BASE64_DEPTH_REASON if b64_depth >= BASE64_MAX_DEPTH else BASE64_BINARY_REASON


def _inspect_base64_leaf(
    raw_str: str,
    *,
    is_attachment: bool,
    b64_depth: int,
) -> _Base64Inspection:
    """Inspect a JSON string leaf for explicit Attachment/data-URI or plain-JSON base64.

    Complexity: O(len(raw_str)).
    """
    uri_parts = split_data_uri_base64(raw_str)
    if uri_parts is not None:
        uri_prefix, b64_part = uri_parts
        explicit_b64 = True
    else:
        uri_prefix, b64_part = "", raw_str
        explicit_b64 = is_attachment

    if not b64_part.strip():
        return _Base64Inspection(kind=_B64_NONE)

    if explicit_b64:
        decoded = decode_base64_payload(b64_part, min_len=BASE64_MIN_EXPLICIT_LEN, strict_whitespace=False)
        if decoded is None:
            return _Base64Inspection(kind=_B64_REDACT, uri_prefix=uri_prefix, reason=BASE64_INVALID_REASON)
    else:
        if len(b64_part) < BASE64_MIN_LEN:
            return _Base64Inspection(kind=_B64_NONE)
        decoded = decode_base64_payload(b64_part, min_len=BASE64_MIN_LEN, strict_whitespace=True)
        if decoded is None:
            return _Base64Inspection(kind=_B64_NONE)

    raw_bytes = decoded.raw_bytes
    fmt = decoded.fmt
    if is_binary_magic(raw_bytes):
        return _Base64Inspection(
            kind=_B64_REDACT,
            uri_prefix=uri_prefix,
            fmt=fmt,
            reason=_b64_binary_or_depth_reason(b64_depth),
        )

    decoded_text = decode_printable_utf8(raw_bytes)
    if decoded_text is None:
        if explicit_b64:
            return _Base64Inspection(
                kind=_B64_REDACT,
                uri_prefix=uri_prefix,
                fmt=fmt,
                reason=_b64_binary_or_depth_reason(b64_depth),
            )
        return _Base64Inspection(kind=_B64_NONE)

    if b64_depth >= BASE64_MAX_DEPTH:
        return _Base64Inspection(kind=_B64_REDACT, uri_prefix=uri_prefix, fmt=fmt, reason=BASE64_DEPTH_REASON)

    if is_json_content(decoded_text):
        try:
            nested = json.loads(decoded_text)
        except RecursionError:
            return _Base64Inspection(kind=_B64_REDACT, uri_prefix=uri_prefix, fmt=fmt, reason=BASE64_DEPTH_REASON)
        except ValueError:
            nested = None
        if isinstance(nested, (dict, list)):
            return _Base64Inspection(
                kind=_B64_JSON,
                uri_prefix=uri_prefix,
                fmt=fmt,
                text=decoded_text,
                json_obj=nested,
            )

    return _Base64Inspection(kind=_B64_TEXT, uri_prefix=uri_prefix, fmt=fmt, text=decoded_text)


@dataclass
class PipelineStats:
    """Mutable counters and active run context shared during pipeline execution."""

    identifiers_detected: int = 0
    records_processed: int = 0
    records_linked: int = 0
    records_generalized: int = 0
    records_suppressed: int = 0
    records_quarantined: int = 0
    reason_counts: dict[str, int] = field(default_factory=dict)
    policy: Policy | None = None
    active_psn: str | None = None
    active_offset: int = 0
    active_date_order: str = DATE_ORDER_DMY


@dataclass(frozen=True)
class PipelineResult:
    """Outputs and summary counts returned by run_pipeline."""

    report: dict[str, Any]
    records: list[dict[str, Any]]


def clean_text(
    text: str,
    stats: PipelineStats,
    *,
    offset_days: int | None = None,
    date_order: str | None = None,
    policy: Policy | None = None,
) -> str:
    """Apply R12 date shift + R6 IDs + R7 names + R13 age/PIN generalisation cleanly. O(len(text))."""
    eff_policy = policy if policy is not None else stats.policy
    eff_offset = offset_days if offset_days is not None else stats.active_offset
    eff_order = date_order if date_order is not None else stats.active_date_order

    working = text
    if eff_offset != 0:
        working, _ = shift_dates_in_text(
            working,
            eff_offset,
            order=eff_order,
            reason_counts=stats.reason_counts,
        )

    cleaned, id_count = redact_identifiers(
        working,
        redact_dob=(eff_policy is None),
        pin_prefix_digits=(eff_policy.pin_prefix_digits if eff_policy is not None else None),
    )
    cleaned, name_count = redact_names(cleaned)
    qi_count = 0
    if eff_policy is not None:
        cleaned, qi_count = generalise_text_qis(
            cleaned,
            width=eff_policy.age_band_years,
            top_code=eff_policy.age_top_code,
            prefix_digits=eff_policy.pin_prefix_digits,
        )
    stats.identifiers_detected += id_count + name_count + qi_count
    return cleaned


def _traverse_json(
    value: Any,
    *,
    is_fhir: bool,
    ref_types: dict[str, str] | None,
    ref_key: str,
    on_leaf: Callable[..., Any],
    on_dict_keys: Callable[[list[str], str | None], list[str]] | None = None,
    protected: set[tuple[int, str]] | None = None,
    transform: bool = False,
    parent_key: str | None = None,
    resource_type: str | None = None,
    parent_path: tuple[str, ...] = (),
) -> Any:
    """Single JSON tree walker shared by Pass 1 harvesting and Pass 2 cleaning/generalisation.

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
        res = on_leaf(semantic, value, parent_key, None, is_attachment=False)
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
            is_attachment = (
                isinstance(v, str)
                and k == "data"
                and (parent_key == "attachment" or "contentType" in value)
            )
            res = on_leaf(semantic, v, parent_key, k, is_attachment=is_attachment)
            if cleaned is not None:
                cleaned[out_k] = res
        return cleaned

    return value if transform else None


def _collect_json_strings(node: Any, *, b64_depth: int = 0) -> list[str]:
    """Collect string leaves (including decoded base64 text/JSON) for date-order voting. O(nodes)."""
    samples: list[str] = []

    def _on_leaf(
        _sem: str,
        leaf_val: Any,
        _pk: str | None,
        _k: str | None,
        *,
        is_attachment: bool = False,
    ) -> Any:
        if isinstance(leaf_val, str) and leaf_val.strip():
            insp = _inspect_base64_leaf(leaf_val, is_attachment=is_attachment, b64_depth=b64_depth)
            if insp.kind == _B64_TEXT and insp.text is not None:
                samples.append(insp.text)
            elif insp.kind == _B64_JSON and insp.json_obj is not None:
                samples.extend(_collect_json_strings(insp.json_obj, b64_depth=b64_depth + 1))
            elif insp.kind == _B64_NONE:
                samples.append(leaf_val)
        return leaf_val

    _traverse_json(node, is_fhir=False, ref_types=None, ref_key="reference", on_leaf=_on_leaf, transform=False)
    return samples


def _harvest_json_record_and_channels(
    node: Any,
    evidence: ChannelEvidence,
    *,
    is_fhir: bool,
    ref_types: dict[str, str] | None,
    date_order: str,
    record_id: int,
    input_rel: str,
    loc: str,
    parent_key: str | None = None,
    preserve_overrides: dict[str, str | None] | None = None,
) -> RecordEvidence:
    """Walk one JSON record/document to feed Pass 1 ChannelEvidence and build RecordEvidence.

    parent_key is the input key holding node when a top-level value is walked on its own. O(nodes).
    """
    strong_set: set[tuple[str, str]] = set()
    name_parts: list[str] = []
    rel_parts: list[str] = []
    dob_iso: str | None = None

    def _add_strong(kind: str, raw_val: str, key: str | None = None) -> None:
        if key is not None and is_non_patient_id_key(key, preserve_overrides=preserve_overrides):
            return  # visit/bill/sample IDs are not patient evidence (R10)
        norm = normalise_strong_id(kind, raw_val)
        if norm is not None:
            strong_set.add(norm)

    def _harvest_free_text(text_val: str) -> None:
        nonlocal dob_iso
        for surf, kind in extract_name_candidates(text_val):
            evidence.add_name(surf, kind)
            if kind == "PATIENT_NAME":
                name_parts.append(surf)
            else:
                rel_parts.append(surf)
        for s, e, kind in find_identifier_spans(text_val):
            sub = text_val[s:e]
            if kind == "MRN":
                evidence.add_mrn(sub)
            if kind in _STRONG_ID_KINDS:
                _add_strong(kind, sub)
            elif kind == "DOB" and dob_iso is None:
                dob_iso = parse_dob_iso(sub, order=date_order)

    def _walk_harvest(
        cur_node: Any,
        *,
        cur_depth: int,
        cur_is_fhir: bool,
        cur_ref_types: dict[str, str] | None,
        cur_parent_key: str | None,
        cur_parent_path: tuple[str, ...],
    ) -> None:
        def _on_leaf(
            semantic: str,
            leaf_val: Any,
            p_key: str | None,
            key: str | None,
            *,
            is_attachment: bool = False,
        ) -> Any:
            nonlocal dob_iso
            if isinstance(leaf_val, int) and not isinstance(leaf_val, bool):
                eff_sem = semantic
                if eff_sem == "FREE_TEXT":
                    int_shape = classify_value_shape(str(leaf_val))
                    if int_shape is not None:
                        eff_sem = int_shape
                if eff_sem in _STRONG_ID_KINDS:
                    _add_strong(eff_sem, str(leaf_val), key)
                return leaf_val
            if not isinstance(leaf_val, str) or not leaf_val.strip():
                return leaf_val
            if cur_depth == 0 and key is None and not p_key:
                return leaf_val

            is_data_uri = split_data_uri_base64(leaf_val) is not None
            explicit_b64 = is_attachment or is_data_uri
            if explicit_b64 or (semantic == "FREE_TEXT" and not looks_like_path_or_url(leaf_val)):
                insp = _inspect_base64_leaf(leaf_val, is_attachment=is_attachment, b64_depth=cur_depth)
                if insp.kind == _B64_JSON and insp.json_obj is not None:
                    _walk_harvest(
                        insp.json_obj,
                        cur_depth=cur_depth + 1,
                        cur_is_fhir=False,
                        cur_ref_types=None,
                        cur_parent_key=None,
                        cur_parent_path=(),
                    )
                    if explicit_b64:
                        return leaf_val
                elif insp.kind == _B64_TEXT and insp.text is not None:
                    _harvest_free_text(insp.text)
                    if explicit_b64:
                        return leaf_val
                elif insp.kind == _B64_REDACT and explicit_b64:
                    return leaf_val

            eff_sem = semantic
            if eff_sem == "PRESERVE_EXACT" and not cur_is_fhir and key is not None:
                # decided once per key over its container's values; a lone value keeps the header meaning
                ov = preserve_overrides.get(key) if preserve_overrides is not None else None
                if ov is not None:
                    eff_sem = ov

            if eff_sem == "PATIENT_NAME":
                evidence.add_name(leaf_val, eff_sem)
                name_parts.append(leaf_val)
            elif eff_sem == "RELATIVE":
                evidence.add_name(leaf_val, eff_sem)
                rel_parts.append(leaf_val)
            elif eff_sem in _STRONG_ID_KINDS:
                if eff_sem == "MRN":
                    evidence.add_mrn(leaf_val)
                _add_strong(eff_sem, leaf_val, key)
            elif eff_sem == "DOB":
                if dob_iso is None:
                    dob_iso = parse_dob_iso(leaf_val, order=date_order)
            elif (
                eff_sem == "FREE_TEXT"
                and not looks_like_path_or_url(leaf_val)
                and (key is None or not is_metadata_key(p_key, key))
            ):
                _harvest_free_text(leaf_val)
            return leaf_val

        _traverse_json(
            cur_node,
            is_fhir=cur_is_fhir,
            ref_types=cur_ref_types,
            ref_key="reference",
            on_leaf=_on_leaf,
            transform=False,
            parent_key=cur_parent_key,
            parent_path=cur_parent_path,
        )

    _walk_harvest(
        node,
        cur_depth=0,
        cur_is_fhir=is_fhir,
        cur_ref_types=ref_types,
        cur_parent_key=parent_key,
        cur_parent_path=(parent_key,) if parent_key else (),
    )

    name_key = normalise_name_key(" ".join(name_parts)) if name_parts else None
    rel_key = normalise_name_key(" ".join(rel_parts)) if rel_parts else None
    return RecordEvidence(
        record_id=record_id,
        input_rel=input_rel,
        loc=loc,
        strong_ids=tuple(sorted(strong_set)),
        name_key=name_key,
        dob_iso=dob_iso,
        rel_key=rel_key,
    )


def _harvest_parsed_evidence(
    parsed: ParsedInput,
    evidence: ChannelEvidence,
    next_record_id: int,
) -> tuple[list[RecordEvidence], int]:
    """Pass 1: harvest channel evidence and compact RecordEvidence tuples for one file.

    Complexity: O(bytes in parsed).
    """
    recs: list[RecordEvidence] = []

    if parsed.kind == "csv":
        assert parsed.rows is not None
        header = parsed.rows[0]
        body = parsed.rows[1:]
        col_priorities = csv_slot_priorities(header, body)
        preferred_col = select_csv_slot_column(header, body, col_priorities)
        col_types = classify_csv_columns(header, body, evidence)
        non_patient_cols = find_non_patient_mrn_cols(header, body, col_types)
        if preferred_col in non_patient_cols:
            preferred_col = None
        # Per-column decision, made once before the row loop: values of these columns are not patient evidence
        sampled_body = body[:COLUMN_VOTE_SAMPLE_CAP]
        non_evidence_cols = non_patient_cols | {
            i
            for i in range(len(header))
            if is_non_patient_id_key(
                header[i], [row[i].strip() for row in sampled_body if i < len(row) and row[i].strip()]
            )
        }
        file_order = infer_date_order(cell for row in body for cell in row)
        col_orders = [
            infer_date_order(row[idx] for row in body if idx < len(row))
            if any(idx < len(row) and row[idx].strip() for row in body)
            else file_order
            for idx in range(len(header))
        ]

        for row_idx, row in enumerate(body):
            strong_set: set[tuple[str, str]] = set()
            name_parts: list[str] = []
            rel_parts: list[str] = []
            dob_iso: str | None = None

            slot = find_csv_slot(
                header, row, preferred_col=preferred_col, col_priorities=col_priorities, excluded_cols=non_patient_cols
            )
            if slot is not None and slot[0] not in non_patient_cols:
                evidence.add_mrn(slot[1])
                slot_kind = col_types[slot[0]] if slot[0] < len(col_types) else "MRN"
                id_type = slot_kind if slot_kind in _STRONG_ID_KINDS else "MRN"
                norm = normalise_strong_id(id_type, slot[1])
                if norm is not None:
                    strong_set.add(norm)

            for idx, cell in enumerate(row):
                if not cell.strip():
                    continue
                col_kind = col_types[idx] if idx < len(col_types) else "FREE_TEXT"
                if col_kind == "PATIENT_NAME":
                    evidence.add_name(cell, col_kind)
                    name_parts.append(cell)
                elif col_kind == "RELATIVE":
                    evidence.add_name(cell, col_kind)
                    rel_parts.append(cell)
                elif col_kind in _STRONG_ID_KINDS:
                    if col_kind == "MRN":
                        evidence.add_mrn(cell)
                    if idx in non_evidence_cols:
                        continue  # visit/bill/sample IDs are not patient evidence (R10)
                    norm = normalise_strong_id(col_kind, cell)
                    if norm is not None:
                        strong_set.add(norm)
                elif col_kind == "DOB":
                    if dob_iso is None:
                        order = col_orders[idx] if idx < len(col_orders) else file_order
                        dob_iso = parse_dob_iso(cell, order=order)
                elif col_kind == "FREE_TEXT":
                    for surf, kind in extract_name_candidates(cell):
                        evidence.add_name(surf, kind)
                        if kind == "PATIENT_NAME":
                            name_parts.append(surf)
                        else:
                            rel_parts.append(surf)
                    for s, e, kind in find_identifier_spans(cell):
                        sub = cell[s:e]
                        if kind == "MRN":
                            evidence.add_mrn(sub)
                        if kind in _STRONG_ID_KINDS:
                            norm = normalise_strong_id(kind, sub)
                            if norm is not None:
                                strong_set.add(norm)
                        elif kind == "DOB" and dob_iso is None:
                            dob_iso = parse_dob_iso(sub, order=file_order)

            recs.append(
                RecordEvidence(
                    record_id=next_record_id,
                    input_rel=parsed.rel_posix,
                    loc=f"row:{row_idx}",
                    strong_ids=tuple(sorted(strong_set)),
                    name_key=normalise_name_key(" ".join(name_parts)) if name_parts else None,
                    dob_iso=dob_iso,
                    rel_key=normalise_name_key(" ".join(rel_parts)) if rel_parts else None,
                )
            )
            next_record_id += 1
        return recs, next_record_id

    if parsed.kind in ("json", "fhir"):
        is_fhir = parsed.kind == "fhir"
        ref_types = build_fhir_fullurl_map(parsed.data) if is_fhir else None
        date_order = infer_date_order(_collect_json_strings(parsed.data))

        if is_fhir or is_document_json(parsed.data):
            recs.append(
                _harvest_json_record_and_channels(
                    parsed.data,
                    evidence,
                    is_fhir=is_fhir,
                    ref_types=ref_types,
                    date_order=date_order,
                    record_id=next_record_id,
                    input_rel=parsed.rel_posix,
                    loc="doc",
                )
            )
            next_record_id += 1
        else:
            for key, val in parsed.data.items():
                if isinstance(val, list) and val and all(isinstance(item, dict) for item in val):
                    list_overrides = collect_list_preserve_overrides(val)
                    for idx, item in enumerate(val):
                        recs.append(
                            _harvest_json_record_and_channels(
                                item,
                                evidence,
                                is_fhir=False,
                                ref_types=None,
                                date_order=date_order,
                                record_id=next_record_id,
                                input_rel=parsed.rel_posix,
                                loc=f"/{key}/{idx}",
                                parent_key=key,
                                preserve_overrides=list_overrides,
                            )
                        )
                        next_record_id += 1
                else:
                    # Not a record list (index map, export metadata): channel evidence only,
                    # it is not a patient record, so its RecordEvidence is not kept.
                    _harvest_json_record_and_channels(
                        val,
                        evidence,
                        is_fhir=False,
                        ref_types=None,
                        date_order=date_order,
                        record_id=next_record_id,
                        input_rel=parsed.rel_posix,
                        loc=f"/{key}",
                        parent_key=key,
                    )
        return recs, next_record_id

    assert parsed.text is not None
    text = parsed.text
    date_order = infer_date_order([text])
    strong_set = set()
    name_parts = []
    rel_parts = []
    dob_iso = None

    span = find_text_slot_span(text)
    if span is not None:
        evidence.add_mrn(span[2])
        norm = normalise_strong_id("MRN", span[2])
        if norm is not None:
            strong_set.add(norm)
    for mrn_tok in extract_mrn_tokens(text):
        evidence.add_mrn(mrn_tok)
    for s, e, kind in find_identifier_spans(text):
        sub = text[s:e]
        if kind in _STRONG_ID_KINDS:
            norm = normalise_strong_id(kind, sub)
            if norm is not None:
                strong_set.add(norm)
        elif kind == "DOB" and dob_iso is None:
            dob_iso = parse_dob_iso(sub, order=date_order)
    for surf, kind in extract_name_candidates(text):
        evidence.add_name(surf, kind)
        if kind == "PATIENT_NAME":
            name_parts.append(surf)
        else:
            rel_parts.append(surf)

    recs.append(
        RecordEvidence(
            record_id=next_record_id,
            input_rel=parsed.rel_posix,
            loc="doc",
            strong_ids=tuple(sorted(strong_set)),
            name_key=normalise_name_key(" ".join(name_parts)) if name_parts else None,
            dob_iso=dob_iso,
            rel_key=normalise_name_key(" ".join(rel_parts)) if rel_parts else None,
        )
    )
    return recs, next_record_id + 1


def _clean_json_values(
    value: Any,
    stats: PipelineStats,
    protected: set[tuple[int, str]],
    evidence: ChannelEvidence,
    policy: Policy,
    offset_days: int,
    date_order: str,
    preserve_fhir_refs: bool = False,
    ref_types: dict[str, str] | None = None,
    parent_key: str | None = None,
    b64_depth: int = 0,
    use_name_evidence: bool = False,
    preserve_overrides: dict[str, str | None] | None = None,
) -> Any:
    """Clean JSON keys, shift dates, generalise QIs, and clean text/base64 via shared walker. O(nodes).

    parent_key is the input key that holds value when a top-level value is cleaned on its own,
    so its keys and leaves keep their meaning context (R5, R9).
    """
    generalised = False

    def _clean_text_step(text_val: str, *, apply_evidence: bool) -> str:
        cleaned_txt = clean_text(text_val, stats, offset_days=offset_days, date_order=date_order, policy=policy)
        if apply_evidence:
            cleaned_txt, ev_cnt = redact_known_names_in_text(cleaned_txt, evidence)
            stats.identifiers_detected += ev_cnt
        return cleaned_txt

    def _clean_b64_leaf(raw_val: str, *, is_attachment: bool) -> tuple[bool, str]:
        insp = _inspect_base64_leaf(raw_val, is_attachment=is_attachment, b64_depth=b64_depth)
        if insp.kind == _B64_NONE:
            return False, raw_val
        if insp.kind == _B64_REDACT:
            stats.identifiers_detected += 1
            if insp.reason is not None:
                stats.reason_counts[insp.reason] = stats.reason_counts.get(insp.reason, 0) + 1
            return True, insp.uri_prefix + base64_placeholder_encoded(insp.fmt)
        if insp.kind == _B64_JSON:
            cleaned_nested = _clean_json_values(
                insp.json_obj,
                stats,
                set(),
                evidence,
                policy,
                offset_days,
                date_order,
                preserve_fhir_refs=False,
                b64_depth=b64_depth + 1,
                use_name_evidence=True,
            )
            if cleaned_nested == insp.json_obj:
                return True, raw_val
            serialized = json.dumps(cleaned_nested, ensure_ascii=False)
            return True, insp.uri_prefix + encode_base64_payload(codecs.utf_8_encode(serialized)[0], insp.fmt)
        assert insp.text is not None
        cleaned_txt = _clean_text_step(insp.text, apply_evidence=True)
        if cleaned_txt == insp.text:
            return True, raw_val
        return True, insp.uri_prefix + encode_base64_payload(codecs.utf_8_encode(cleaned_txt)[0], insp.fmt)

    def _on_leaf(
        semantic: str,
        leaf_val: Any,
        p_key: str | None,
        key: str | None,
        *,
        is_attachment: bool = False,
    ) -> Any:
        nonlocal generalised
        if isinstance(leaf_val, str):
            if not leaf_val.strip():
                return leaf_val
            if is_attachment or split_data_uri_base64(leaf_val) is not None:
                handled, b64_out = _clean_b64_leaf(leaf_val, is_attachment=is_attachment)
                if handled:
                    return b64_out
            if semantic == "DOB":
                shifted, _ = shift_dates_in_text(
                    leaf_val,
                    offset_days,
                    order=date_order,
                    reason_counts=stats.reason_counts,
                )
                generalised = True
                return shifted
            if semantic == "AGE":
                banded, cnt = generalise_age_field(leaf_val, policy.age_band_years, policy.age_top_code)
                if cnt > 0:
                    stats.identifiers_detected += cnt
                    generalised = True
                return banded
            if semantic == "PIN":
                masked, cnt = generalise_pin_str(leaf_val, policy.pin_prefix_digits)
                if cnt > 0:
                    stats.identifiers_detected += cnt
                    generalised = True
                return masked
            if semantic == "ADDRESS":
                addr, cnt = generalise_address_field(leaf_val, policy.location_level, policy.pin_prefix_digits)
                if cnt > 0:
                    stats.identifiers_detected += cnt
                    generalised = True
                return addr
            if semantic in _STRUCTURED_PII_KINDS:
                stats.identifiers_detected += 1
                if semantic in LOCATION_DETAIL_KINDS:
                    generalised = True
                return PLACEHOLDERS[semantic]
            if semantic == "PRESERVE_EXACT":
                if not preserve_fhir_refs and key is not None:
                    # decided once per key over its container's values; a lone value keeps the header meaning
                    ov = preserve_overrides.get(key) if preserve_overrides is not None else None
                    if ov is not None and ov in PLACEHOLDERS:
                        stats.identifiers_detected += 1
                        return PLACEHOLDERS[ov]
                shifted, _ = shift_dates_in_text(
                    leaf_val,
                    offset_days,
                    order=date_order,
                    reason_counts=stats.reason_counts,
                )
                return shifted
            if looks_like_path_or_url(leaf_val):
                c_val, cnt = clean_path_or_url(leaf_val, evidence, filename_safe=False)
                stats.identifiers_detected += cnt
                return c_val
            if key is not None and is_metadata_key(p_key, key):
                c_val, cnt = clean_channel_text(leaf_val, evidence, filename_safe=False)
                stats.identifiers_detected += cnt
                raw_cleaned = _clean_text_step(c_val, apply_evidence=use_name_evidence)
            else:
                raw_cleaned = _clean_text_step(leaf_val, apply_evidence=use_name_evidence)
            handled, b64_out = _clean_b64_leaf(raw_cleaned, is_attachment=False)
            if handled:
                return b64_out
            if not json_leaf_has_known_meaning(p_key, key):
                addr_shape = classify_address_value_shape(raw_cleaned)
                if addr_shape == "ADDRESS":
                    addr, cnt = generalise_address_field(raw_cleaned, policy.location_level, policy.pin_prefix_digits)
                    if cnt > 0:
                        stats.identifiers_detected += cnt
                        generalised = True
                    return addr
                if addr_shape in LOCATION_DETAIL_KINDS:
                    generalised = True
                    stats.identifiers_detected += 1
                    return PLACEHOLDERS[addr_shape]
            return raw_cleaned

        if isinstance(leaf_val, int) and not isinstance(leaf_val, bool):
            if semantic == "AGE":
                generalised = True
                stats.identifiers_detected += 1
                return generalise_age_int(leaf_val, policy.age_band_years, policy.age_top_code)
            if semantic == "PIN":
                generalised = True
                stats.identifiers_detected += 1
                return generalise_pin_int(leaf_val, policy.pin_prefix_digits)
            if semantic in _STRUCTURED_PII_KINDS or semantic == "DOB":
                stats.identifiers_detected += 1
                return NUMERIC_REDACTION_SENTINEL
            if semantic == "FREE_TEXT":
                int_shape = classify_value_shape(str(leaf_val))
                if int_shape in _STRONG_ID_KINDS:
                    stats.identifiers_detected += 1
                    return NUMERIC_REDACTION_SENTINEL
        return leaf_val

    def _on_dict_keys(orig_keys: list[str], p_key: str | None) -> list[str]:
        key_ctx = json_dict_key_context(p_key) if not preserve_fhir_refs else None
        out_keys, key_clean_count = clean_dict_keys(orig_keys, evidence, key_context=key_ctx)
        stats.identifiers_detected += key_clean_count
        return out_keys

    result = _traverse_json(
        value,
        is_fhir=preserve_fhir_refs,
        ref_types=ref_types,
        ref_key="reference",
        on_leaf=_on_leaf,
        on_dict_keys=_on_dict_keys,
        protected=protected,
        transform=True,
        parent_key=parent_key,
        parent_path=(parent_key,) if parent_key else (),
    )
    if generalised and b64_depth == 0:
        stats.records_generalized += 1
    return result


def _process_csv(
    parsed: ParsedInput,
    make_psn: Any,
    stats: PipelineStats,
    evidence: ChannelEvidence,
    *,
    link_map: dict[tuple[str, str], tuple[str | None, int]] | None = None,
    policy: Policy | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Process one CSV/TSV file with linkage PSNs, R12 date shifts, and R13 QI generalisation."""
    assert parsed.rows is not None
    eff_policy = policy if policy is not None else stats.policy
    assert eff_policy is not None
    header = parsed.rows[0]
    body = parsed.rows[1:]
    col_priorities = csv_slot_priorities(header, body)
    preferred_col = select_csv_slot_column(header, body, col_priorities)
    col_types = classify_csv_columns(header, body, evidence)
    non_patient_cols = find_non_patient_mrn_cols(header, body, col_types)
    if preferred_col in non_patient_cols:
        preferred_col = None
    file_order = infer_date_order(cell for row in body for cell in row)
    col_orders = [
        infer_date_order(row[idx] for row in body if idx < len(row))
        if any(idx < len(row) and row[idx].strip() for row in body)
        else file_order
        for idx in range(len(header))
    ]
    cleaned_header, hdr_cnt = clean_csv_header(header, evidence)
    stats.identifiers_detected += hdr_cnt

    out_rows: list[list[str]] = [cleaned_header]
    recs: list[dict[str, Any]] = []

    for row_idx, row in enumerate(body):
        raw_loc = f"row:{row_idx}"
        if link_map is not None and (parsed.rel_posix, raw_loc) in link_map:
            psn, offset_days = link_map[(parsed.rel_posix, raw_loc)]
        else:
            slot = find_csv_slot(
                header, row, preferred_col=preferred_col, col_priorities=col_priorities, excluded_cols=non_patient_cols
            )
            psn = make_psn(slot[1]) if slot is not None else None
            offset_days = 0

        slot_col = find_csv_slot_or_fallback(
            header,
            row,
            col_types,
            preferred_col=preferred_col,
            col_priorities=col_priorities,
            excluded_cols=non_patient_cols,
            allow_name_fallback=(psn is not None),
        )

        row_generalised = False
        out_row: list[str] = []
        for idx, cell in enumerate(row):
            if idx == slot_col:
                out_row.append(_slot_value(psn))
                continue
            col_kind = col_types[idx] if idx < len(col_types) else "FREE_TEXT"
            col_order = col_orders[idx] if idx < len(col_orders) else file_order
            if col_kind == "DOB":
                shifted, _ = shift_dates_in_text(
                    cell,
                    offset_days,
                    order=col_order,
                    reason_counts=stats.reason_counts,
                )
                if cell.strip():
                    row_generalised = True
                out_row.append(shifted)
            elif col_kind == "AGE":
                banded, cnt = generalise_age_field(cell, eff_policy.age_band_years, eff_policy.age_top_code)
                if cnt > 0:
                    stats.identifiers_detected += cnt
                    row_generalised = True
                out_row.append(banded)
            elif col_kind == "PIN":
                masked, cnt = generalise_pin_str(cell, eff_policy.pin_prefix_digits)
                if cnt > 0:
                    stats.identifiers_detected += cnt
                    row_generalised = True
                out_row.append(masked)
            elif col_kind == "ADDRESS":
                addr, cnt = generalise_address_field(
                    cell,
                    eff_policy.location_level,
                    eff_policy.pin_prefix_digits,
                )
                if cnt > 0:
                    stats.identifiers_detected += cnt
                    row_generalised = True
                out_row.append(addr)
            elif col_kind in _STRUCTURED_PII_KINDS:
                if cell.strip():
                    stats.identifiers_detected += 1
                    if col_kind in LOCATION_DETAIL_KINDS:
                        row_generalised = True
                    out_row.append(PLACEHOLDERS[col_kind])
                else:
                    out_row.append(cell)
            elif col_kind == "PRESERVE_EXACT":
                shifted, _ = shift_dates_in_text(
                    cell,
                    offset_days,
                    order=col_order,
                    reason_counts=stats.reason_counts,
                )
                out_row.append(shifted)
            elif looks_like_path_or_url(cell):
                c_val, cnt = clean_path_or_url(cell, evidence, filename_safe=False)
                stats.identifiers_detected += cnt
                out_row.append(c_val)
            else:
                out_row.append(
                    clean_text(cell, stats, offset_days=offset_days, date_order=file_order, policy=eff_policy)
                )

        if row_generalised:
            stats.records_generalized += 1
        out_rows.append(out_row)
        recs.append({"file": f"sanitized/{parsed.rel_posix}", "loc": raw_loc, "patient": psn})
        stats.records_processed += 1
        if psn is not None:
            stats.records_linked += 1

    return serialize_csv(out_rows, parsed.delimiter), recs


def _slot_value(psn: str | None) -> str:
    """Value written into a record's patient-ID slot: the PSN, or the ID placeholder when the
    patient is null, so an original ID never survives in its slot (R11, R6). O(1)."""
    return psn if psn is not None else PLACEHOLDERS["MRN"]


def _claim_json_slot(
    slot_writer: Callable[..., tuple[int, str] | None],
    target: Any,
    psn: str | None,
    protected: set[tuple[int, str]],
    *,
    preserve_overrides: dict[str, str | None] | None = None,
) -> str | None:
    """Write PSN (or null-slot placeholder) and return emitted PSN only if a slot holds it (R11). O(1)."""
    if preserve_overrides is not None:
        prot = slot_writer(target, _slot_value(psn), allow_name_fallback=psn is not None, preserve_overrides=preserve_overrides)
    else:
        prot = slot_writer(target, _slot_value(psn), allow_name_fallback=psn is not None)
    if prot is not None:
        protected.add(prot)
        return psn
    return None


def _process_json(
    parsed: ParsedInput,
    make_psn: Any,
    stats: PipelineStats,
    evidence: ChannelEvidence,
    *,
    link_map: dict[tuple[str, str], tuple[str | None, int]] | None = None,
    policy: Policy | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Process one JSON or FHIR Bundle file with cluster PSNs, R12 date shifts, and R13 QIs."""
    eff_policy = policy if policy is not None else stats.policy
    assert eff_policy is not None
    data = parsed.data
    date_order = infer_date_order(_collect_json_strings(data))
    protected: set[tuple[int, str]] = set()
    recs: list[dict[str, Any]] = []
    is_fhir = parsed.kind == "fhir"
    ref_types = build_fhir_fullurl_map(data) if is_fhir else None

    if is_fhir:
        psn, offset_days = (
            link_map[(parsed.rel_posix, "doc")]
            if link_map is not None and (parsed.rel_posix, "doc") in link_map
            else (None, 0)
        )
        emitted_psn = _claim_json_slot(write_fhir_slot_psn, data, psn, protected)
        recs.append({"file": f"sanitized/{parsed.rel_posix}", "loc": "doc", "patient": emitted_psn})
        stats.records_processed += 1
        if emitted_psn is not None:
            stats.records_linked += 1
        cleaned = _clean_json_values(
            data,
            stats,
            protected,
            evidence,
            eff_policy,
            offset_days,
            date_order,
            preserve_fhir_refs=True,
            ref_types=ref_types,
        )
        return serialize_json(cleaned), recs

    if is_document_json(data):
        psn, offset_days = (
            link_map[(parsed.rel_posix, "doc")]
            if link_map is not None and (parsed.rel_posix, "doc") in link_map
            else (None, 0)
        )
        emitted_psn = _claim_json_slot(write_json_slot_psn, data, psn, protected)
        recs.append({"file": f"sanitized/{parsed.rel_posix}", "loc": "doc", "patient": emitted_psn})
        stats.records_processed += 1
        if emitted_psn is not None:
            stats.records_linked += 1
        cleaned = _clean_json_values(
            data,
            stats,
            protected,
            evidence,
            eff_policy,
            offset_days,
            date_order,
            preserve_fhir_refs=False,
        )
        return serialize_json(cleaned), recs

    # Multi-record JSON: each record item gets its own cluster PSN and per-patient date shift
    orig_top_keys = list(data.keys())
    cleaned_top_keys, key_clean_count = clean_dict_keys(orig_top_keys, evidence)
    stats.identifiers_detected += key_clean_count
    top_key_map = dict(zip(orig_top_keys, cleaned_top_keys))

    cleaned_root: dict[str, Any] = {}
    for key, val in data.items():
        out_key = top_key_map[key]
        if isinstance(val, list) and val and all(isinstance(item, dict) for item in val):
            list_overrides = collect_list_preserve_overrides(val)
            # Never emit a raw PII key into a records.jsonl pointer (SPEC sec 6 / D5)
            escaped_key = json_pointer_escape(str(out_key))
            out_items: list[Any] = []
            for idx, item in enumerate(val):
                raw_loc = f"/{key}/{idx}"
                psn, offset_days = (
                    link_map[(parsed.rel_posix, raw_loc)]
                    if link_map is not None and (parsed.rel_posix, raw_loc) in link_map
                    else (None, 0)
                )
                item_prot: set[tuple[int, str]] = set()
                emitted_psn = _claim_json_slot(
                    write_json_slot_psn,
                    item,
                    psn,
                    item_prot,
                    preserve_overrides=list_overrides,
                )
                cleaned_item = _clean_json_values(
                    item,
                    stats,
                    item_prot,
                    evidence,
                    eff_policy,
                    offset_days,
                    date_order,
                    preserve_fhir_refs=False,
                    parent_key=key,
                    preserve_overrides=list_overrides,
                )
                out_items.append(cleaned_item)
                recs.append(
                    {
                        "file": f"sanitized/{parsed.rel_posix}",
                        "loc": f"/{escaped_key}/{idx}",
                        "patient": emitted_psn,
                    }
                )
                stats.records_processed += 1
                if emitted_psn is not None:
                    stats.records_linked += 1
            cleaned_root[out_key] = out_items
        else:
            # Not a record list (e.g. an index or export metadata): no patient, so no date offset
            cleaned_root[out_key] = _clean_json_values(
                val,
                stats,
                set(),
                evidence,
                eff_policy,
                0,
                date_order,
                preserve_fhir_refs=False,
                parent_key=key,
            )

    return serialize_json(cleaned_root), recs


def _process_text(
    parsed: ParsedInput,
    make_psn: Any,
    stats: PipelineStats,
) -> tuple[str, list[dict[str, Any]]]:
    """Process one plain-text file preserving line count, PSN placement, R12 shifts, and R13 QIs."""
    assert parsed.text is not None
    text = parsed.text
    psn = stats.active_psn
    span = find_text_slot_span(text)

    if span is not None:
        start, end, _ = span
        sanitized_text = clean_text(text[:start], stats) + _slot_value(psn) + clean_text(text[end:], stats)
    else:
        sanitized_text = clean_text(text, stats)
        if psn is not None:
            sanitized_text = inject_psn_into_text(sanitized_text, psn)

    rec = {"file": f"sanitized/{parsed.rel_posix}", "loc": "doc", "patient": psn}
    stats.records_processed += 1
    if psn is not None:
        stats.records_linked += 1
    return sanitized_text, [rec]


_DIGIT_RUN_RE = re.compile(r"\d+")


def _source_family_key(rel_posix: str) -> str:
    """Files exported from one template: same folder and same name once digit runs are masked
    (e.g. a numbered series). Internal grouping only, never written out. O(len(rel_posix))."""
    rel = PurePosixPath(rel_posix)
    return f"{rel.parent.as_posix()}/{_DIGIT_RUN_RE.sub('#', rel.name)}"


def _record_text(parsed: ParsedInput, loc: str) -> str:
    """The input text of one record (table row, JSON record, or whole document), for date
    evidence only. Chosen by which ParsedInput field holds the content. O(record size)."""
    if parsed.rows is not None:
        return " | ".join(parsed.rows[int(loc.split(":", 1)[1]) + 1])
    if parsed.text is not None:
        return parsed.text
    node = parsed.data
    if loc != "doc":
        key, idx = loc[1:].rsplit("/", 1)
        node = node[key][int(idx)]
    return json.dumps(node, ensure_ascii=False)


def _decide_text_date_orders(
    text_votes: dict[str, tuple[tuple[int, int], list[tuple[str, str]], int]],
    record_dates: dict[int, list[str]],
    canonical_keys: dict[int, str | None],
) -> dict[str, str]:
    """R12 date order per text file: its own dates first; if they prove nothing, the certain
    dates of records linked to the same patient (which reading of an ambiguous date they
    contain); then the other files of the same export family; day-first only without evidence.

    Complexity: O(R + total dates) with dict/set lookups.
    """
    cluster_dates: dict[str, set[str]] = defaultdict(set)
    for rid in sorted(record_dates):
        ck = canonical_keys.get(rid)
        if ck is not None:
            cluster_dates[ck].update(record_dates[rid])
    family_votes: dict[str, Counter[str]] = defaultdict(Counter)
    for rel, (own, _, _) in sorted(text_votes.items()):
        family_votes[_source_family_key(rel)].update({"dmy": own[0], "mdy": own[1]})

    orders: dict[str, str] = {}
    for rel, (own, readings, rid) in sorted(text_votes.items()):
        ck = canonical_keys.get(rid)
        known = cluster_dates.get(ck, set()) if ck is not None else set()
        linked = (sum(d in known for d, _ in readings), sum(m in known for _, m in readings))
        fam = family_votes[_source_family_key(rel)]
        family = (fam["dmy"] - own[0], fam["mdy"] - own[1])
        orders[rel] = resolve_date_order(own, linked, family)
    return orders


def run_pipeline(inp: Path, out: Path, secret: bytes, policy: Policy) -> PipelineResult:
    """Run the two-pass firewall pipeline: Pass 1 evidence + R10 clustering -> Pass 2 R5-R13 export.

    Complexity: O(total input bytes + R * alpha(R)).
    """
    validate_policy(policy)
    t0 = time.monotonic()
    san_dir = out / "sanitized"
    san_dir.mkdir(parents=True, exist_ok=True)

    stats = PipelineStats(policy=policy)
    evidence = ChannelEvidence()
    record_evidences: list[RecordEvidence] = []
    record_dates: dict[int, list[str]] = {}
    text_votes: dict[str, tuple[tuple[int, int], list[tuple[str, str]], int]] = {}
    next_record_id = 0
    quarantined_map: dict[str, tuple[str, str]] = {}
    sanitizable_paths: list[tuple[Path, str, str]] = []

    with MemorySampler() as sampler:
        input_files = sorted(
            (p for p in inp.rglob("*") if p.is_file()),
            key=lambda p: p.relative_to(inp).as_posix(),
        )

        # Pass 1: validate files and harvest channel + record linkage evidence
        for path in input_files:
            rel_posix = path.relative_to(inp).as_posix()
            sha256_hex, parsed, reason = read_and_parse(path, rel_posix)
            if parsed is None:
                quarantined_map[rel_posix] = (sha256_hex, reason or "quarantined")
                continue
            try:
                file_recs, next_record_id = _harvest_parsed_evidence(parsed, evidence, next_record_id)
            except (ValueError, UnicodeError, RecursionError):
                quarantined_map[rel_posix] = (sha256_hex, "processing_error")
                continue
            record_evidences.extend(file_recs)
            for rec in file_recs:
                certain, ambiguous = date_order_evidence(_record_text(parsed, rec.loc))
                record_dates[rec.record_id] = certain
                if parsed.kind == "text":
                    text_votes[rel_posix] = (count_date_order_votes([parsed.text]), ambiguous, rec.record_id)
            sanitizable_paths.append((path, rel_posix, sha256_hex))

        # Cluster records across files/hospitals/scripts and cache keyed PSN + date offset
        linkage_res = link_records(record_evidences)
        text_date_orders = _decide_text_date_orders(text_votes, record_dates, linkage_res.canonical_keys)
        psn_cache: dict[str, str] = {}
        offset_cache: dict[str, int] = {}
        link_map: dict[tuple[str, str], tuple[str | None, int]] = {}
        for rec in record_evidences:
            ck = linkage_res.canonical_keys.get(rec.record_id)
            if ck is not None:
                psn = psn_cache.get(ck)
                if psn is None:
                    psn = pseudonym(ck, secret)
                    psn_cache[ck] = psn
                offset = offset_cache.get(ck)
                if offset is None:
                    offset = date_shift_days(
                        ck,
                        secret,
                        policy.date_shift_max_days,
                        policy.date_shift_min_abs_days,
                    )
                    offset_cache[ck] = offset
                link_map[(rec.input_rel, rec.loc)] = (psn, offset)
            else:
                internal_key = f"{rec.input_rel}|{rec.loc}"
                offset = date_shift_days(
                    internal_key,
                    secret,
                    policy.date_shift_max_days,
                    policy.date_shift_min_abs_days,
                )
                link_map[(rec.input_rel, rec.loc)] = (None, offset)

        rename_map = build_output_rename_map([rel for _, rel, _ in sanitizable_paths], evidence)
        pass2_lookup = {rel: (path, sha256_hex) for path, rel, sha256_hex in sanitizable_paths}

        file_entries: list[dict[str, Any]] = []
        all_records: list[dict[str, Any]] = []

        def _make_psn_unused(_norm: str) -> str:
            return ""

        # Pass 2: clean content + channels, shift dates, generalise QIs, and export
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
                    content, file_recs = _process_csv(
                        parsed,
                        _make_psn_unused,
                        stats,
                        evidence,
                        link_map=link_map,
                        policy=policy,
                    )
                elif parsed.kind in ("json", "fhir"):
                    content, file_recs = _process_json(
                        parsed,
                        _make_psn_unused,
                        stats,
                        evidence,
                        link_map=link_map,
                        policy=policy,
                    )
                else:
                    assert parsed.text is not None
                    psn, offset_days = link_map.get((rel_posix, "doc"), (None, 0))
                    stats.active_psn = psn
                    stats.active_offset = offset_days
                    stats.active_date_order = text_date_orders[rel_posix]
                    content, file_recs = _process_text(parsed, _make_psn_unused, stats)
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
        "reason_counts": dict(sorted(stats.reason_counts.items())),
    }
    write_report_json(out / "report.json", report)

    return PipelineResult(report=report, records=all_records)
