"""R5 structured column and JSON key semantic classification + column value-shape voting."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any

from wards.config import AGE_LABEL_WORDS, METADATA_PATH_KEY_TOKENS, NON_NAME_WORDS
from wards.patterns import classify_value_shape

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

    if (tok_set & _NAME_TOKENS) or (tok_set & _PERSON_NAME_MODIFIERS and not (tok_set & _DATE_TOKENS)):
        if "patient" in tok_set or tok_set & _NAME_TOKENS:
            return "PATIENT_NAME"

    if tok_set & _FREE_TEXT_TOKENS:
        return "FREE_TEXT"
    if tok_set & _AGE_TOKENS:
        return "AGE"
    if tok_set & _PRESERVE_EXACT_TOKENS or (tok_set & _DATE_TOKENS):
        return "PRESERVE_EXACT"
    return None


def classify_csv_columns(header: list[str], body_rows: list[list[str]]) -> list[str]:
    """Classify every CSV/TSV column using header meaning tokens + per-column value-shape voting.

    Complexity: O(len(body_rows) * len(header)).
    """
    result: list[str] = []
    for col_idx, col_name in enumerate(header):
        semantic = classify_header_tokens(col_name)
        if semantic is not None:
            result.append(semantic)
            continue

        votes: Counter[str] = Counter()
        non_empty = 0
        for row in body_rows:
            if col_idx >= len(row):
                continue
            cell = row[col_idx].strip()
            if not cell:
                continue
            non_empty += 1
            shape = classify_value_shape(cell)
            if shape is not None:
                votes[shape] += 1

        if non_empty == 0 or not votes:
            result.append("FREE_TEXT")
            continue

        top_kind, top_count = sorted(votes.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        if top_count * 2 >= non_empty:
            result.append(top_kind)
        else:
            result.append("FREE_TEXT")

    return result


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
    if parent_tokens & _RELATIVE_TOKENS and key_tokens & _NAME_TOKENS:
        return "RELATIVE"
    if parent_key == "contact" and key_tokens & _NAME_TOKENS:
        return "RELATIVE"
    if key == "contact":
        return "PHONE"
    if key == "patient":
        return "PATIENT_NAME"
    if parent_key == "name" and key_tokens & _PERSON_NAME_MODIFIERS:
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
