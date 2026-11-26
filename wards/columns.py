"""R5 structured column and JSON key semantic classification + column value-shape voting."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import TYPE_CHECKING, Any

from wards.config import (
    ADDRESS_VALUE_MAX_LEN,
    AGE_LABEL_WORDS,
    AGE_UNIT_WORDS,
    COLUMN_ID_MIN_CARDINALITY_RATIO,
    COLUMN_ID_MIN_DISTINCT,
    COLUMN_ID_MIN_VALUES,
    COLUMN_NAME_MAX_TOKENS,
    COLUMN_VOTE_MIN_RATIO,
    COLUMN_VOTE_SAMPLE_CAP,
    DISTRICT_MARKER_WORDS,
    LINK_ANCHOR_ID_KINDS,
    LOCATION_DETAIL_KINDS,
    METADATA_PATH_KEY_TOKENS,
    MIN_CHANNEL_NAME_TOKEN_LEN,
    NON_NAME_WORDS,
    SEX_VALUE_WORDS,
    TEHSIL_MARKER_WORDS,
)
from wards.names import is_r8_medical_value
from wards.patterns import classify_strict_id_shape, classify_value_shape, normalise_digits

if TYPE_CHECKING:
    from wards.channels import ChannelEvidence

# Generic meaning vocabulary per semantic category (never dev-specific column sets)
_PRESERVE_EXACT_TOKENS = frozenset(
    {
        "doctor",
        "dr",
        "consultant",
        "physician",
        "referred",
        "reviewer",
        "reviewed",
        "clinician",
        "diagnosis",
        "icd",
        "loinc",
        "test",
        "result",
        "results",
        "unit",
        "range",
        "drug",
        "medication",
        "rx",
        "dose",
        "dosage",
        "frequency",
        "strength",
        "form",
        "department",
        "dept",
        "ward",
        "bed",
        "district",
        "jila",
        "जिला",
        "tehsil",
        "taluka",
        "state",
        "country",
        "hospital",
        "clinic",
        "lab",
        "facility",
        "amount",
        "status",
        "gender",
        "sex",
        "ling",
        "लिंग",
        "collected",
        "reported",
        "registered",
        "exported",
        "schema",
        "system",
        "procedure",
        "package",
        "vitals",
        "bp",
        "pulse",
        "temp",
        "spo2",
        "weight",
        "category",
        "schedule",
        "relation",
    }
)
_FREE_TEXT_TOKENS = frozenset({"notes", "note", "remarks", "remark", "complaints", "complaint", "history", "div"})
_CLINICAL_CONTAINERS = frozenset(
    {
        "facility",
        "hospital",
        "lab",
        "panels",
        "panel",
        "diagnosis",
        "rx",
        "vitals",
        "department",
        "ward",
        "organization",
        "clinic",
        "practitioner",
    }
)

_EMAIL_TOKENS = frozenset({"email", "mail", "ईमेल"})
_PHONE_TOKENS = frozenset(
    {"phone", "mobile", "mob", "cell", "tel", "telephone", "whatsapp", "callback", "contact", "फ़ोन", "मोबाइल", "संपर्क"}
)
_AADHAAR_TOKENS = frozenset({"aadhaar", "aadhar", "uidai", "आधार"})
_ABHA_TOKENS = frozenset({"abha", "abdm"})
_PAN_TOKENS = frozenset({"pan", "पैन"})
_INSURANCE_TOKENS = frozenset({"insurance", "pmjay", "policy", "tpa", "बीमा"})
_DOB_TOKENS = frozenset({"dob", "birth", "birthdate", "janm", "जन्म"})
_PIN_TOKENS = frozenset({"pin", "pincode", "zip", "zipcode", "postal", "postalcode", "पिन"})
_HOUSE_TOKENS = frozenset({"house", "hno", "makan", "flat", "मकान"})
_LOCALITY_TOKENS = frozenset({"locality", "mohalla", "street", "colony", "sector", "tola", "मोहल्ला", "टोला"})
_LANDMARK_TOKENS = frozenset({"landmark", "near", "opp"})
_VILLAGE_TOKENS = frozenset({"village", "gaon", "gram", "city", "town", "गाँव", "गांव", "ग्राम"})
_ADDRESS_TOKENS = frozenset({"address", "addr", "pata", "पता"})
_RELATIVE_TOKENS = frozenset(
    {
        "relative",
        "guardian",
        "father",
        "fathers",
        "mother",
        "mothers",
        "husband",
        "wife",
        "spouse",
        "kin",
        "pita",
        "pati",
        "पिता",
        "पति",
        "माता",
        "अभिभावक",
    }
)
_NAME_TOKENS = frozenset({"name", "naam", "fname", "lname", "नाम"})
# Public alias: the one name-meaning key vocabulary, reused by wards.slots.
NAME_KEY_TOKENS = _NAME_TOKENS
_PERSON_NAME_MODIFIERS = frozenset({"patient", "pt", "first", "last", "full", "given", "family", "local", "मरीज़", "मरीज", "रोगी"})
_DIRECT_ID_TOKENS = frozenset({"uhid", "mrn"})
_PATIENT_ID_PREFIXES = frozenset({"patient", "pt", "reg", "registration", "ipd", "opd", "adm", "admission", "cr"})
_ID_SUFFIXES = frozenset({"id", "ref", "no", "num", "number", "code", "सं", "संख्या", "आईडी"})
_DATE_TOKENS = frozenset({"date", "dt", "tithi", "तारीख"})
_AGE_TOKENS = frozenset(AGE_LABEL_WORDS)

_FHIR_CODE_CONTAINERS = frozenset({"coding", "code", "type", "clinicalstatus", "verificationstatus", "qualification", "relationship"})
_MAP_ID_TOKENS = frozenset({"uhid", "mrn", "id", "ref", "phone", "mobile", "aadhaar", "aadhar", "abha", "pan"})
CHANNEL_ID_PREFIXES = _DIRECT_ID_TOKENS | _PATIENT_ID_PREFIXES
_META_CONTAINER_EXTRA_TOKENS = frozenset({"meta", "exported"})
_META_LEAF_KEY_TOKENS = frozenset({"by", "path", "file", "source", "user"})


def _alt_tokens(words: Any) -> str:
    return "|".join(re.escape(w) for w in sorted(words, key=lambda s: (-len(s), s)))


_W_EDGE_L = r"(?<![A-Za-z0-9_\u0900-\u097f])"
_W_EDGE_R = r"(?![A-Za-z0-9_\u0900-\u097f])"
_HOUSE_UNIT_VALUE = r"(?:[ \t]*(?:no\.?|number|नं\.?))?[ \t.:#-]*[A-Za-z\u0900-\u097f0-9/-]*\d[A-Za-z\u0900-\u097f0-9/-]*"
# Built purely from locked _HOUSE_TOKENS; _HOUSE_ABBR_CUE_RE matches "<letter>[. ]?<token>" when joined in _HOUSE_TOKENS (e.g. H.No. -> hno).
_HOUSE_CUE_RE = re.compile(
    rf"(?i){_W_EDGE_L}(?:{_alt_tokens(_HOUSE_TOKENS)}){_HOUSE_UNIT_VALUE}{_W_EDGE_R}"
)
_HOUSE_ABBR_CUE_RE = re.compile(
    rf"(?i){_W_EDGE_L}(?P<ltr>[A-Za-z])(?:\.[ \t]*|[ \t]+|(?=[A-Za-z]))(?P<nxt>[A-Za-z]+)\.?{_HOUSE_UNIT_VALUE}{_W_EDGE_R}"
)
_PLACE_NAME_TOK = r"(?:[A-Z][A-Za-z0-9'.-]*|[\u0900-\u097f]{2,}|[A-Za-z0-9-]*\d[A-Za-z0-9-]*)"
_LOCALITY_CUE_RE = re.compile(
    rf"{_W_EDGE_L}(?:(?i:{_alt_tokens(_LOCALITY_TOKENS)})[ \t.:#-]+{_PLACE_NAME_TOK}|{_PLACE_NAME_TOK}[ \t]+(?i:{_alt_tokens(_LOCALITY_TOKENS)})){_W_EDGE_R}"
)
_LANDMARK_PLACE_TOK = r"(?:[A-Z][A-Za-z0-9'.-]*|[\u0900-\u097f]{2,}|[0-9]+[A-Za-z-]*)"
_LANDMARK_CUE_RE = re.compile(
    rf"(?:^|,[ \t]*)(?i:{_alt_tokens(_LANDMARK_TOKENS)})[.:]?[ \t]+{_LANDMARK_PLACE_TOK}"
)
_VILLAGE_CUE_RE = re.compile(
    rf"{_W_EDGE_L}(?i:{_alt_tokens(_VILLAGE_TOKENS)})[ \t.:#-]+{_PLACE_NAME_TOK}{_W_EDGE_R}"
)
_DIST_NAME_TOK = r"([A-Z][A-Za-z'.-]*|[\u0900-\u097f]{2,})"
_DISTRICT_CUE_RE = re.compile(
    rf"{_W_EDGE_L}(?i:{_alt_tokens(DISTRICT_MARKER_WORDS)})[ \t.:#-]+{_DIST_NAME_TOK}{_W_EDGE_R}"
)
_TEHSIL_CUE_RE = re.compile(
    rf"{_W_EDGE_L}(?i:{_alt_tokens(TEHSIL_MARKER_WORDS)})[ \t.:#-]+{_DIST_NAME_TOK}{_W_EDGE_R}"
)
_PIN_EMBED_RE = re.compile(r"(?<!\d)[1-9]\d{5}(?!\d)")
_AGE_VALUE_SHAPE_RE = re.compile(
    rf"(?i)^\d{{1,3}}(?:[ \t]*(?:{_alt_tokens(AGE_UNIT_WORDS)})[ \t]*/[ \t]*(?:{_alt_tokens(SEX_VALUE_WORDS)})|"
    rf"[ \t]*/[ \t]*(?:{_alt_tokens(SEX_VALUE_WORDS)})|"
    rf"[ \t]+(?:{_alt_tokens(AGE_UNIT_WORDS)}))$"
)
_HOUSE_NUM_SHAPE_RE = re.compile(r"^(?:[A-Za-z]-?)?\d{1,5}(?:[/-][A-Za-z0-9]{1,4})?$")
_PIN_6_SHAPE_RE = re.compile(r"^[1-9]\d{5}$")
_DATE_LIKE_GUARD_RE = re.compile(r"^\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}$")
_NAME_WORD_RE = re.compile(r"[A-Za-z']+|[\u0900-\u097f]+")


def _has_house_cue(value: str) -> bool:
    """True when value carries a house token or abbreviated house token (e.g. H.No.) followed by a unit number. O(len(value))."""
    if _HOUSE_CUE_RE.search(value) is not None:
        return True
    for m in _HOUSE_ABBR_CUE_RE.finditer(value):
        if (m.group("ltr") + m.group("nxt")).casefold() in _HOUSE_TOKENS:
            return True
    return False


def classify_address_value_shape(value: str) -> str | None:
    """Detect Indian structured addresses and address parts from value cues paired with place values. O(len(value))."""
    s = value.strip()
    if not s or len(s) > ADDRESS_VALUE_MAX_LEN:
        return None
    has_house = _has_house_cue(s)
    has_locality = _LOCALITY_CUE_RE.search(s) is not None
    has_landmark = _LANDMARK_CUE_RE.search(s) is not None
    has_village = _VILLAGE_CUE_RE.search(s) is not None
    dist_match = _DISTRICT_CUE_RE.search(s)
    has_district = dist_match is not None and dist_match.group(1).casefold() not in _CLINICAL_CONTAINERS
    tehsil_match = _TEHSIL_CUE_RE.search(s)
    has_tehsil = tehsil_match is not None and tehsil_match.group(1).casefold() not in _CLINICAL_CONTAINERS
    has_pin = _PIN_EMBED_RE.search(s) is not None

    cues = (
        int(has_house)
        + int(has_locality)
        + int(has_landmark)
        + int(has_village)
        + int(has_district)
        + int(has_tehsil)
        + int(has_pin)
    )
    if cues >= 2 and "," in s:
        return "ADDRESS"
    if len(s.split()) <= COLUMN_NAME_MAX_TOKENS:
        if has_house:
            return "HOUSE"
        if has_locality:
            return "LOCALITY"
        if has_landmark:
            return "LANDMARK"
    return None


def _vote_name_evidence(value: str, evidence: ChannelEvidence | None) -> str | None:
    """Match a cell against Pass 1 run-time name tokens/phrases without matching non-names. O(len(value))."""
    if evidence is None or (not evidence.name_tokens and not evidence.name_phrases):
        return None
    s = value.strip()
    if not s or any(ch.isdigit() for ch in s):
        return None
    words = _NAME_WORD_RE.findall(unicodedata.normalize("NFKC", s).casefold())
    if not words or len(words) > COLUMN_NAME_MAX_TOKENS:
        return None
    clean = [w.strip("'") for w in words if w.strip("'")]
    if not clean or any(w in NON_NAME_WORDS for w in clean):
        return None
    if len(clean) >= 2:
        tup = tuple(clean)
        if tup in evidence.name_phrases:
            return evidence.name_phrase_kind.get(tup, evidence.DEFAULT_KIND)
    matched_kinds = [
        evidence.name_token_kind.get(w, evidence.DEFAULT_KIND)
        for w in clean
        if len(w) >= MIN_CHANNEL_NAME_TOKEN_LEN and w in evidence.name_tokens
    ]
    if matched_kinds and len(matched_kinds) * 2 >= len(clean):
        return matched_kinds[0]
    return None


def tokenize_header(name: str) -> list[str]:
    """Split a header or key into normalised tokens across case, punctuation, and script. O(len(name))."""
    nfkc = unicodedata.normalize("NFKC", name)
    split_camel = re.sub(r"([a-z])([A-Z])", r"\1_\2", nfkc).casefold()
    cleaned = re.sub(r"[^a-z0-9\u0900-\u097f]+", "_", split_camel)
    return [tok for tok in cleaned.split("_") if tok]


def build_fhir_fullurl_map(bundle: Any) -> dict[str, str]:
    """Build a fullUrl/relative-id -> resourceType lookup table for a FHIR Bundle. O(entries)."""
    ref_map: dict[str, str] = {}
    if not isinstance(bundle, dict):
        return ref_map
    entries = bundle.get("entry")
    if not isinstance(entries, list):
        return ref_map
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        res = entry.get("resource")
        if not isinstance(res, dict):
            continue
        rtype = res.get("resourceType")
        if not isinstance(rtype, str) or not rtype:
            continue
        full_url = entry.get("fullUrl")
        if isinstance(full_url, str) and full_url:
            ref_map[full_url] = rtype
        res_id = res.get("id")
        if isinstance(res_id, str) and res_id:
            ref_map[f"{rtype}/{res_id}"] = rtype
    return ref_map


def classify_header_tokens(name: str) -> str | None:
    """Map a column header or JSON key to a PII category, PRESERVE_EXACT, FREE_TEXT, or None.

    Complexity: O(len(name)).
    """
    tokens = tokenize_header(name)
    if not tokens:
        return None
    tok_set = set(tokens)

    # Purely numeric headers (e.g. "0", "123") must fall back to value-shape voting
    if all(tok.isdigit() for tok in tokens):
        return None

    if tok_set & _DOB_TOKENS:
        return "DOB"
    if (tok_set & _ABHA_TOKENS) and (tok_set & _ADDRESS_TOKENS or "addr" in tok_set):
        return "ABHA_ADDRESS"
    if tok_set & _ABHA_TOKENS or ({"health", "id"} <= tok_set):
        return "ABHA"
    if tok_set & _AADHAAR_TOKENS:
        return "AADHAAR"
    if tok_set & _EMAIL_TOKENS:
        return "EMAIL"
    if tok_set & _PAN_TOKENS:
        return "PAN"
    if tok_set & _INSURANCE_TOKENS:
        return "INSURANCE"
    if tok_set & _PHONE_TOKENS:
        return "PHONE"
    if tok_set & _PIN_TOKENS:
        return "PIN"
    if tok_set & _RELATIVE_TOKENS:
        return "RELATIVE"

    # Doctor/clinician/facility headers must be preserved even if they contain "name" or "ref"
    if tok_set & {"doctor", "dr", "consultant", "physician", "referred", "reviewer", "reviewed", "clinician"}:
        return "PRESERVE_EXACT"
    if tok_set & _CLINICAL_CONTAINERS:
        return "PRESERVE_EXACT"

    if (tok_set & _DIRECT_ID_TOKENS) or ((tok_set & _PATIENT_ID_PREFIXES) and (tok_set & _ID_SUFFIXES)):
        return "MRN"

    has_village = bool(tok_set & _VILLAGE_TOKENS)
    has_locality = bool(tok_set & _LOCALITY_TOKENS)
    has_house = bool(tok_set & _HOUSE_TOKENS)
    has_landmark = bool(tok_set & _LANDMARK_TOKENS)
    if has_village:
        return "VILLAGE"
    if has_locality:
        return "LOCALITY"
    if has_house:
        return "HOUSE"
    if has_landmark:
        return "LANDMARK"
    if tok_set & _ADDRESS_TOKENS:
        return "ADDRESS"

    if tok_set & _FREE_TEXT_TOKENS:
        return "FREE_TEXT"
    if tok_set & _AGE_TOKENS:
        return "AGE"
    if tok_set & _PRESERVE_EXACT_TOKENS or (tok_set & _DATE_TOKENS):
        return "PRESERVE_EXACT"
    if tok_set & _NAME_TOKENS:
        return "PATIENT_NAME"
    return None


def resolve_preserve_exact_override(cells: list[str]) -> tuple[str | None, bool]:
    """Apply medical > strict R6 ID with high cardinality > header precedence over sampled cells.

    Returns ``(id_kind_override, is_medical)``. Medical columns are never overridden; low-cardinality
    repeated facility/department codes are preserved. Complexity: O(sum(len(c) for c in cells)).
    """
    non_empty = len(cells)
    if non_empty == 0:
        return None, False

    medical_hits = sum(1 for cell in cells if is_r8_medical_value(cell))
    if medical_hits >= COLUMN_VOTE_MIN_RATIO * non_empty:
        return None, True

    id_votes: Counter[str] = Counter()
    for cell in cells:
        id_kind = classify_strict_id_shape(cell)
        if id_kind is not None:
            id_votes[id_kind] += 1

    if not id_votes:
        return None, False

    best_id, best_count = sorted(id_votes.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    if best_count < COLUMN_VOTE_MIN_RATIO * non_empty:
        return None, False

    if non_empty < COLUMN_ID_MIN_VALUES:
        return None, False  # one value carries no cardinality evidence: keep the header meaning
    distinct_count = len({normalise_digits(cell).casefold() for cell in cells})
    if distinct_count < COLUMN_ID_MIN_CARDINALITY_RATIO * non_empty and distinct_count < COLUMN_ID_MIN_DISTINCT:
        return None, False

    return best_id, False


def resolve_id_slot_override(key: str, cells: list[str]) -> str | None:
    """Return strict R6 ID kind when a PRESERVE_EXACT key holds non-medical, high-cardinality IDs.

    Complexity: O(len(key) + sum(len(c) for c in cells)).
    """
    if classify_header_tokens(key) != "PRESERVE_EXACT":
        return None
    override_kind, _ = resolve_preserve_exact_override(cells)
    return override_kind


def collect_list_preserve_overrides(items: list[dict[str, Any]]) -> dict[str, str | None]:
    """Compute column-level PRESERVE_EXACT -> ID override decisions across a JSON list of record dicts.

    Complexity: O(min(len(items), COLUMN_VOTE_SAMPLE_CAP) * keys_per_item).
    """
    per_key_vals: dict[str, list[str]] = {}
    for item in items[:COLUMN_VOTE_SAMPLE_CAP]:
        if not isinstance(item, dict):
            continue
        for k, v in item.items():
            if isinstance(v, str):
                s = v.strip()
                if s and classify_header_tokens(k) == "PRESERVE_EXACT":
                    per_key_vals.setdefault(k, []).append(s)
    return {
        k: resolve_preserve_exact_override(vals)[0]
        for k, vals in per_key_vals.items()
    }


def classify_csv_columns(
    header: list[str],
    body_rows: list[list[str]],
    evidence: ChannelEvidence,
) -> list[str]:
    """Classify every CSV/TSV column using header meaning + medical/ID precedence & cardinality
    + adjacent-column address-part promotion.

    Precedence: medical > strict R6 ID with high cardinality > header meaning.
    Complexity: O(min(len(body_rows), COLUMN_VOTE_SAMPLE_CAP) * len(header)).
    """
    n_cols = len(header)
    if n_cols == 0:
        return []
    sampled_rows = body_rows[:COLUMN_VOTE_SAMPLE_CAP]

    result: list[str] = []
    hdr_semantics: list[str | None] = []
    sampled_cells: list[list[str]] = [[] for _ in range(n_cols)]

    for col_idx, col_name in enumerate(header):
        hdr_sem = classify_header_tokens(col_name)
        hdr_semantics.append(hdr_sem)

        cells = [
            row[col_idx].strip()
            for row in sampled_rows
            if col_idx < len(row) and row[col_idx].strip()
        ]
        sampled_cells[col_idx] = cells
        non_empty = len(cells)

        top_id_kind, is_medical_col = resolve_preserve_exact_override(cells)

        top_other_kind: str | None = None
        if not is_medical_col and top_id_kind is None and hdr_sem is None and non_empty > 0:
            other_votes: Counter[str] = Counter()
            for cell in cells:
                shape = classify_value_shape(cell)
                if shape is None:
                    shape = classify_address_value_shape(cell)
                if shape is None and _AGE_VALUE_SHAPE_RE.match(cell):
                    shape = "AGE"
                if shape is None and evidence is not None:
                    shape = _vote_name_evidence(cell, evidence)
                if shape is not None:
                    other_votes[shape] += 1
            if other_votes:
                best_other, best_other_count = sorted(other_votes.items(), key=lambda kv: (-kv[1], kv[0]))[0]
                if best_other_count >= COLUMN_VOTE_MIN_RATIO * non_empty:
                    top_other_kind = best_other

        if is_medical_col:
            result.append(hdr_sem if hdr_sem is not None else "FREE_TEXT")
        elif hdr_sem == "PRESERVE_EXACT":
            result.append(top_id_kind if top_id_kind is not None else "PRESERVE_EXACT")
        elif hdr_sem is not None:
            result.append(hdr_sem)
        elif top_id_kind is not None:
            result.append(top_id_kind)
        elif top_other_kind is not None:
            result.append(top_other_kind)
        else:
            result.append("FREE_TEXT")

    # Pass 2: promote unknown FREE_TEXT columns adjacent to address/village/district columns
    district_tehsil_words = frozenset(w.rstrip(".").casefold() for w in (*DISTRICT_MARKER_WORDS, *TEHSIL_MARKER_WORDS))
    is_loc_anchor = [
        (res == "ADDRESS")
        or (res in LOCATION_DETAIL_KINDS)
        or bool(set(tokenize_header(header[i])) & (_PIN_TOKENS | district_tehsil_words))
        for i, res in enumerate(result)
    ]
    for col_idx, res in enumerate(result):
        if res != "FREE_TEXT" or hdr_semantics[col_idx] is not None:
            continue
        has_adj_anchor = (col_idx > 0 and is_loc_anchor[col_idx - 1]) or (
            col_idx + 1 < n_cols and is_loc_anchor[col_idx + 1]
        )
        if not has_adj_anchor:
            continue
        cells = sampled_cells[col_idx]
        if not cells:
            continue
        house_hits = sum(
            1
            for c in cells
            if (
                _has_house_cue(c)
                or (
                    _HOUSE_NUM_SHAPE_RE.match(c) is not None
                    and not _PIN_6_SHAPE_RE.match(c)
                    and not _DATE_LIKE_GUARD_RE.match(c)
                )
            )
        )
        if house_hits >= COLUMN_VOTE_MIN_RATIO * len(cells):
            result[col_idx] = "HOUSE"
            continue
        loc_hits = sum(1 for c in cells if _LOCALITY_CUE_RE.search(c) is not None)
        if loc_hits >= COLUMN_VOTE_MIN_RATIO * len(cells):
            result[col_idx] = "LOCALITY"
            continue
        land_hits = sum(1 for c in cells if _LANDMARK_CUE_RE.search(c) is not None)
        if land_hits >= COLUMN_VOTE_MIN_RATIO * len(cells):
            result[col_idx] = "LANDMARK"

    return result


def find_non_patient_mrn_cols(
    header: list[str],
    body_rows: list[list[str]],
    col_types: list[str],
) -> set[int]:
    """Identify unknown-header MRN-shaped columns that behave as transaction/event IDs (D9).

    Excludes any unlabeled MRN column when the table already has a header-identified MRN column,
    or when a repeated patient maps to multiple distinct values in that column.
    Complexity: O(min(len(body_rows), COLUMN_VOTE_SAMPLE_CAP) * len(header)).
    """
    unknown_mrns = [
        idx
        for idx, kind in enumerate(col_types)
        if kind == "MRN" and idx < len(header) and classify_header_tokens(header[idx]) != "MRN"
    ]
    if not unknown_mrns:
        return set()

    has_named_mrn = any(
        kind == "MRN" and idx < len(header) and classify_header_tokens(header[idx]) == "MRN"
        for idx, kind in enumerate(col_types)
    )
    if has_named_mrn:
        return set(unknown_mrns)

    anchor_cols = [
        idx
        for idx, kind in enumerate(col_types)
        if kind in LINK_ANCHOR_ID_KINDS
    ]
    if not anchor_cols:
        return set()

    sampled = body_rows[:COLUMN_VOTE_SAMPLE_CAP]
    excluded: set[int] = set()
    for col_idx in unknown_mrns:
        per_anchor: dict[tuple[int, str], set[str]] = {}
        for row in sampled:
            if col_idx >= len(row):
                continue
            val = normalise_digits(row[col_idx]).strip().upper()
            if not val:
                continue
            for anc_idx in anchor_cols:
                if anc_idx == col_idx or anc_idx >= len(row):
                    continue
                anc_val = row[anc_idx].strip().casefold()
                if not anc_val:
                    continue
                seen = per_anchor.setdefault((anc_idx, anc_val), set())
                seen.add(val)
                if len(seen) > 1:
                    excluded.add(col_idx)
                    break
            if col_idx in excluded:
                break
    return excluded


def classify_json_key(
    parent_key: str | None,
    key: str,
    resource_type: str | None = None,
    ref_target_type: str | None = None,
    parent_path: tuple[str, ...] = (),
) -> str:
    """Classify a JSON leaf key using parent element path, FHIR Reference target, and key tokens.

    Complexity: O(len(key) + len(parent_key)).
    """
    parent_tokens = set(tokenize_header(parent_key)) if parent_key else set()
    key_tokens = set(tokenize_header(key))

    # FHIR Reference.display is classified by what its reference resolves to, never by enclosing resourceType
    if key == "display" and ref_target_type is not None:
        if ref_target_type == "Patient":
            return "PATIENT_NAME"
        if ref_target_type == "RelatedPerson":
            return "RELATIVE"
        return "PRESERVE_EXACT"

    if resource_type is not None:
        if resource_type in ("Practitioner", "Organization") and key in (
            "name", "text", "given", "family", "line", "city", "district", "state", "postalCode"
        ):
            return "PRESERVE_EXACT"
        if parent_key and parent_key.casefold() in _FHIR_CODE_CONTAINERS:
            return "PRESERVE_EXACT"
        if resource_type in ("Patient", "RelatedPerson"):
            in_contact = "contact" in parent_path
            in_name = "name" in parent_path
            in_address = "address" in parent_path
            if in_contact and (key == "name" or (in_name and key in ("text", "given", "family"))):
                return "RELATIVE"
            if key == "name" or (in_name and key in ("text", "given", "family")):
                return "PATIENT_NAME" if resource_type == "Patient" else "RELATIVE"
            if in_address and key == "text":
                return "ADDRESS"
            if key == "birthDate":
                return "DOB"
            if key == "postalCode":
                return "PIN"
            if key == "city":
                return "VILLAGE"
            if key == "line":
                return "ADDRESS"
            if key in ("district", "state", "country", "gender"):
                return "PRESERVE_EXACT"
            if key == "div":
                return "FREE_TEXT"
            if parent_key and parent_key.casefold() in ("maritalstatus", "language", "communication"):
                return "PRESERVE_EXACT"
        elif key in ("title", "unit", "system", "code"):
            return "PRESERVE_EXACT"
        elif key == "div":
            return "FREE_TEXT"

    if parent_tokens & _CLINICAL_CONTAINERS:
        return "PRESERVE_EXACT"
    if parent_tokens & _RELATIVE_TOKENS and key_tokens & (_NAME_TOKENS | _PERSON_NAME_MODIFIERS):
        return "RELATIVE"
    if parent_key == "contact" and key_tokens & _NAME_TOKENS:
        return "RELATIVE"
    if key == "contact":
        return "PHONE"
    if key == "patient":
        return "PATIENT_NAME"
    if (parent_tokens & _NAME_TOKENS) and (key_tokens & _PERSON_NAME_MODIFIERS):
        return "PATIENT_NAME"
    if parent_tokens & _ADDRESS_TOKENS and key == "line":
        return "ADDRESS"

    semantic = classify_header_tokens(key)
    return semantic if semantic is not None else "FREE_TEXT"


def json_dict_key_context(parent_key: str | None) -> str | None:
    """Infer whether sibling keys of a dict hold person names or IDs based on parent key tokens.

    For example, 'by_name' -> 'PATIENT_NAME', 'by_uhid' -> 'MRN'. Returns None otherwise.
    Complexity: O(len(parent_key)).
    """
    if not parent_key:
        return None
    tokens = set(tokenize_header(parent_key))
    if "by" not in tokens and not parent_key.casefold().endswith("_map"):
        return None
    if tokens & _RELATIVE_TOKENS:
        return "RELATIVE"
    if tokens & (_NAME_TOKENS | _PERSON_NAME_MODIFIERS):
        return "PATIENT_NAME"
    if tokens & _PHONE_TOKENS:
        return "PHONE"
    if tokens & _MAP_ID_TOKENS:
        return "MRN"
    return None


def json_leaf_has_known_meaning(parent_key: str | None, key: str | None) -> bool:
    """Return True when a JSON leaf's key already maps to a known category (incl. FREE_TEXT). O(len(key))."""
    eff_key = key if key is not None else parent_key
    if eff_key is None:
        return False
    return classify_header_tokens(eff_key) is not None


def is_metadata_key(parent_key: str | None, key: str) -> bool:
    """Return True if key or parent container denotes export/source path metadata. O(len(key))."""
    key_toks = set(tokenize_header(key))
    if key_toks & METADATA_PATH_KEY_TOKENS:
        return True
    if parent_key:
        p_toks = set(tokenize_header(parent_key))
        if (p_toks & (METADATA_PATH_KEY_TOKENS | _META_CONTAINER_EXTRA_TOKENS)) and (key_toks & _META_LEAF_KEY_TOKENS):
            return True
    return False
