"""Patient-ID slot discovery and replacement (spike for Task 1)."""
from __future__ import annotations

import re
import unicodedata
from collections import deque
from typing import Any, Callable

from wards.columns import NAME_KEY_TOKENS
from wards.config import PLACEHOLDERS

# Generic vocabulary of ID-meaning tokens (no dev-specific header sets)
_DIRECT_PATIENT_ID_TOKENS = frozenset({"uhid", "mrn", "uid"})
_PATIENT_NOUN_TOKENS = frozenset({"patient", "pt", "रोगी", "मरीज़", "मरीज"})
_RECORD_PREFIX_TOKENS = frozenset({"reg", "registration", "ipd", "opd", "adm", "admission", "cr"})
_ID_SUFFIX_TOKENS = frozenset({"id", "ref", "no", "num", "number", "code", "सं", "संख्या", "आईडी"})
_DEVA_ID_PREFIXES = frozenset({"पंजीकरण", "आईपीडी", "ओपीडी"})

_SECONDARY_ID_TOKENS = frozenset(
    {
        "aadhaar",
        "aadhar",
        "abha",
        "pan",
        "pmjay",
        "insurance",
        "policy",
        "mobile",
        "phone",
        "contact",
        "email",
    }
)

# Generic non-patient domain nouns (never represent a patient identifier slot)
_NON_PATIENT_TOKENS = frozenset(
    {
        "visit",
        "bill",
        "sample",
        "order",
        "doctor",
        "facility",
        "package",
        "loinc",
        "test",
        "procedure",
        "diagnosis",
        "date",
        "dob",
        "age",
        "sex",
        "gender",
        "status",
        "amount",
        "ward",
        "bed",
        "unit",
        "range",
        "drug",
        "strength",
        "form",
        "category",
        "schedule",
        "schema",
        "system",
        "hospital",
        "department",
    }
)

# Letters+digits ID-like token (e.g., HSP-001001, CLI/99/00042, REC000042)
_ID_SHAPE_RE = re.compile(
    r"^(?=[A-Za-z0-9/-]{5,24}$)(?=[A-Za-z0-9/-]*[A-Za-z])(?=[A-Za-z0-9/-]*\d)"
    r"[A-Za-z]{2,8}(?:[-/]?\d{2,})+$"
)

# Labelled ID lines in clinical text (Latin + Devanagari; never consumes newlines)
_TEXT_LABEL_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?P<label>"
    r"UHID|Patient[ \t]*ID|Reg(?:istration)?[ \t]*No\.?|IPD[ \t]*No\.?|OPD[ \t]*No\.?|"
    r"MRN|CR[ \t]*No\.?|Admission[ \t]*No\.?|"
    r"पंजीकरण[ \t]*(?:सं\.?|संख्या)|आईपीडी[ \t]*(?:सं\.?|संख्या)|"
    r"ओपीडी[ \t]*(?:सं\.?|संख्या)|रोगी[ \t]*(?:आईडी|सं\.?)"
    r")[ \t]*:[ \t]*(?P<val>[^\s,;|]+)",
    re.IGNORECASE,
)

# Standalone ID-like token in header/first lines (e.g. "Bed 2 - REC000042")
_TEXT_FALLBACK_ID_RE = re.compile(r"(?<![A-Za-z0-9/.-])([A-Z]{2,6}(?:[-/]?\d{2,}){1,3})(?![A-Za-z0-9/.-])")


def normalise_slot_value(value: str) -> str:
    """Normalise an identifier value deterministically for HMAC keying."""
    return " ".join(unicodedata.normalize("NFKC", value).split()).upper()


def _key_tokens(key: str) -> list[str]:
    nfkc = unicodedata.normalize("NFKC", key)
    # Split camelCase / PascalCase boundaries before tokenizing punctuation
    split_camel = re.sub(r"([a-z])([A-Z])", r"\1_\2", nfkc).casefold()
    cleaned = re.sub(r"[^a-z0-9\u0900-\u097f]+", "_", split_camel)
    return [tok for tok in cleaned.split("_") if tok]


def _names_non_patient_thing(tok_set: set[str]) -> bool:
    """True if key tokens name a non-patient thing (visit, bill, sample...) and no patient ID."""
    if not tok_set & _NON_PATIENT_TOKENS:
        return False
    # Allow explicit patient-ID phrases even when combined with other words
    has_patient_id = bool(
        (tok_set & _DIRECT_PATIENT_ID_TOKENS)
        or ((tok_set & _PATIENT_NOUN_TOKENS) and (tok_set & _ID_SUFFIX_TOKENS))
    )
    return not has_patient_id


def is_non_patient_id_key(key: str) -> bool:
    """True if a header/key names a non-patient identifier, so its values are not patient
    evidence (R10). O(len(key))."""
    return _names_non_patient_thing(set(_key_tokens(key)))


def _key_priority(key: str) -> int:
    """Return 1 for primary patient-ID meaning, 2 for secondary ID, -1 for excluded, 0 neutral."""
    tokens = _key_tokens(key)
    if not tokens:
        return -1
    tok_set = set(tokens)
    if _names_non_patient_thing(tok_set):
        return -1
    if tok_set & _DIRECT_PATIENT_ID_TOKENS:
        return 1
    if (tok_set & _PATIENT_NOUN_TOKENS) and (tok_set & _ID_SUFFIX_TOKENS):
        return 1
    if (tok_set & _RECORD_PREFIX_TOKENS) and (tok_set & _ID_SUFFIX_TOKENS):
        return 1
    if (tok_set & _DEVA_ID_PREFIXES) and (tok_set & _ID_SUFFIX_TOKENS):
        return 1
    # Bare "id" without a patient/record qualifier is ambiguous
    if tok_set == {"id"}:
        return -1
    if tok_set & _SECONDARY_ID_TOKENS:
        return 2
    return 0


def _looks_like_patient_id(value: str) -> bool:
    return bool(_ID_SHAPE_RE.match(value.strip()))


def select_csv_slot_column(header: list[str], body_rows: list[list[str]]) -> int | None:
    """Select the best patient-ID column using meaning tokens + column-level value-shape vote.

    Complexity: O(len(body_rows) * len(header)).
    """
    best_secondary: int | None = None
    best_shape: tuple[float, int] | None = None

    for idx, col_name in enumerate(header):
        non_empty = 0
        id_shaped = 0
        for row in body_rows:
            if idx < len(row) and row[idx].strip():
                non_empty += 1
                if _looks_like_patient_id(row[idx]):
                    id_shaped += 1
        if non_empty == 0:
            continue

        prio = _key_priority(col_name)
        if prio == 1:
            return idx
        if prio == 2 and best_secondary is None:
            best_secondary = idx
        elif prio == 0 and id_shaped * 2 >= non_empty:
            ratio = id_shaped / non_empty
            if best_shape is None or ratio > best_shape[0]:
                best_shape = (ratio, idx)

    if best_secondary is not None:
        return best_secondary
    return best_shape[1] if best_shape is not None else None


def find_csv_slot(header: list[str], row: list[str], preferred_col: int | None = None) -> tuple[int, str] | None:
    """Locate the patient-ID column index and raw value in a CSV/TSV row."""
    if preferred_col is not None and preferred_col < len(row):
        val = row[preferred_col].strip()
        if val:
            return preferred_col, val

    best_secondary: tuple[int, str] | None = None
    best_shape: tuple[int, str] | None = None

    for idx, raw_val in enumerate(row):
        if idx >= len(header):
            break
        val = raw_val.strip()
        if not val:
            continue
        prio = _key_priority(header[idx])
        if prio == 1:
            return idx, val
        if prio == 2 and best_secondary is None:
            best_secondary = (idx, val)
        elif prio == 0 and best_shape is None and _looks_like_patient_id(val):
            best_shape = (idx, val)

    return best_secondary if best_secondary is not None else best_shape


def find_csv_slot_or_fallback(
    header: list[str],
    row: list[str],
    col_types: list[str],
    preferred_col: int | None = None,
    *,
    allow_name_fallback: bool = False,
) -> int | None:
    """Locate CSV patient slot index, falling back to PATIENT_NAME column when linked without ID."""
    found = find_csv_slot(header, row, preferred_col=preferred_col)
    if found is not None:
        return found[0]
    if allow_name_fallback:
        for idx, cell in enumerate(row):
            if idx < len(col_types) and col_types[idx] == "PATIENT_NAME" and cell.strip():
                return idx
    return None


def _find_json_slot_target(obj: dict[str, Any]) -> tuple[dict[str, Any], str, str] | None:
    """Find the best string-valued patient-ID slot inside a JSON record dict via BFS."""
    best_secondary: tuple[dict[str, Any], str, str] | None = None
    best_shape: tuple[dict[str, Any], str, str] | None = None

    queue: deque[dict[str, Any]] = deque([obj])
    while queue:
        cur = queue.popleft()
        for k, v in cur.items():
            if isinstance(v, str):
                val = v.strip()
                if not val:
                    continue
                prio = _key_priority(k)
                if prio == 1:
                    return cur, k, val
                if prio == 2 and best_secondary is None:
                    best_secondary = (cur, k, val)
                elif prio == 0 and best_shape is None and _looks_like_patient_id(val):
                    best_shape = (cur, k, val)
            elif isinstance(v, dict):
                queue.append(v)

    return best_secondary if best_secondary is not None else best_shape


def is_document_json(data: Any) -> bool:
    """Decide whether JSON is a single document ('doc') or has top-level record lists."""
    if not isinstance(data, dict) or data.get("resourceType") == "Bundle":
        return True
    list_fields = [
        v for v in data.values()
        if isinstance(v, list) and v and all(isinstance(item, dict) for item in v)
    ]
    if not list_fields:
        return True

    for items in list_fields:
        for item in items[:5]:
            if _find_json_slot_target(item) is not None:
                return False

    root_only = {
        k: v for k, v in data.items()
        if not (isinstance(v, list) and v and all(isinstance(item, dict) for item in v))
    }
    if _find_json_slot_target(root_only) is not None:
        return True

    return False


def _find_json_name_fallback(obj: dict[str, Any]) -> tuple[dict[str, Any], str] | None:
    """Find a person-name leaf in a JSON record dict via BFS when no ID slot exists. O(nodes)."""
    queue: deque[dict[str, Any]] = deque([obj])
    while queue:
        cur = queue.popleft()
        for k, v in cur.items():
            if isinstance(v, str) and v.strip():
                toks = set(_key_tokens(k))
                if toks & NAME_KEY_TOKENS or k == "patient":
                    return cur, k
            elif isinstance(v, dict):
                queue.append(v)
    return None


def write_json_slot_psn(
    obj: Any,
    value: str,
    *,
    allow_name_fallback: bool = False,
) -> tuple[int, str] | None:
    """Write the PSN (or, for a null patient, the ID placeholder) into the JSON patient-ID slot.

    The name-leaf fallback is only for a linked record (value is a PSN). O(nodes).
    """
    if not isinstance(obj, dict):
        return None
    target = _find_json_slot_target(obj)
    if target is not None:
        container, key, _ = target
        container[key] = value
        return id(container), key
    if allow_name_fallback:
        fb = _find_json_name_fallback(obj)
        if fb is not None:
            container, key = fb
            container[key] = value
            return id(container), key
    return None


def write_fhir_slot_psn(bundle: Any, value: str, *, allow_name_fallback: bool) -> tuple[int, str] | None:
    """Write the PSN (or the ID placeholder for a null patient) into Patient.identifier[].value.

    Patient.name[0].text is the fallback slot only for a linked record (value is a PSN).
    """
    if not isinstance(bundle, dict):
        return None
    entries = bundle.get("entry")
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        res = entry.get("resource")
        if not isinstance(res, dict) or res.get("resourceType") != "Patient":
            continue
        identifiers = res.get("identifier")
        if isinstance(identifiers, list):
            for ident in identifiers:
                if isinstance(ident, dict) and isinstance(ident.get("value"), str) and ident["value"].strip():
                    ident["value"] = value
                    return id(ident), "value"
        names = res.get("name")
        if allow_name_fallback and isinstance(names, list) and names and isinstance(names[0], dict):
            if isinstance(names[0].get("text"), str) and names[0]["text"].strip():
                names[0]["text"] = value
                return id(names[0]), "text"
    return None


# Placeholder kinds, in preference order, that may carry the PSN of a linked text document.
_PSN_TEXT_SLOT_KINDS = ("PATIENT_NAME", "PHONE", "MRN")


def inject_psn_into_text(cleaned_text: str, psn: str) -> str:
    """Place PSN into the first person/phone placeholder of a linked free-text document. O(len(text))."""
    for kind in _PSN_TEXT_SLOT_KINDS:
        placeholder = PLACEHOLDERS[kind]
        if placeholder in cleaned_text:
            return cleaned_text.replace(placeholder, psn, 1)
    return cleaned_text


def find_text_slot_span(text: str) -> tuple[int, int, str] | None:
    """Locate the patient-ID value span (start, end, raw_value) in free text."""
    matches = list(_TEXT_LABEL_RE.finditer(text))
    if matches:
        def _rank(m: re.Match[str]) -> tuple[int, int]:
            tokens = set(_key_tokens(m.group("label")))
            if tokens & (_DIRECT_PATIENT_ID_TOKENS | _PATIENT_NOUN_TOKENS | {"reg", "registration", "पंजीकरण"}):
                return (0, m.start())
            return (1, m.start())

        best = min(matches, key=_rank)
        return best.start("val"), best.end("val"), best.group("val")

    # Fallback: check the first 5 lines for a standalone ID-like token (e.g. REC000042)
    header_end = 0
    for idx, line in enumerate(text.splitlines(keepends=True)):
        if idx >= 5:
            break
        header_end += len(line)
    header_slice = text[:header_end]
    for m in _TEXT_FALLBACK_ID_RE.finditer(header_slice):
        token = m.group(1)
        if _looks_like_patient_id(token):
            return m.start(1), m.end(1), token

    return None
