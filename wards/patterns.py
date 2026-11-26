"""R6 identifier and phone regex detection, Devanagari digit normalisation, and Verhoeff check."""
from __future__ import annotations

import re

from wards.config import (
    BASE64_MIN_EXPLICIT_LEN,
    DATA_URI_MIN_LEN,
    DATA_URI_PREFIX,
    PIN_DIGITS,
    PIN_MASK_CHAR,
    PLACEHOLDERS,
)

_DEVA_DIGIT_TRANS = str.maketrans("०१२३४५६७८९", "0123456789")

# Verhoeff tables (Wikipedia worked example: 2363 -> valid, 2364 -> invalid, 9427 -> valid)
_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)

_UNIT_FOLLOW_RE = re.compile(
    r"[ \t]*(?:mg|mcg|ug|g|kg|ml|dl|l|iu|mmhg|bpm|meq|mmol|/ul|/dl|/l|%)(?![A-Za-z])",
    re.IGNORECASE,
)
_NON_DIGIT_RE = re.compile(r"\D")
_PSN_BODY = r"PSN-[0-9A-Z]{6}"
_PSN_RE = re.compile(rf"^{_PSN_BODY}$")
# Tokens a later stage must never rewrite: typed placeholders and pseudonyms.
PROTECTED_TOKEN_RE = re.compile(rf"\[[A-Z_]+\]|{_PSN_BODY}")
_DATE_LIKE_RE = re.compile(r"^\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}$")

# Leading/trailing boundary guards: allow prose punctuation (e.g. trailing '.') unless followed by alphanumeric
_LB = r"(?<![A-Za-z0-9])(?<![A-Za-z0-9][./-])"
_RB = r"(?![A-Za-z0-9])(?![./-][A-Za-z0-9])"

# Precompiled R6 patterns (horizontal whitespace only so line counts stay unchanged; bounded local-part avoids O(n^2) backtracking)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,128}\.[A-Za-z]{2,16}\b")
_ABHA_ADDR_LABEL_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(?:ABHA|ABDM)[ \t]*(?:Address|Addr|ID)?[ \t]*:[ \t]*"
    r"(?P<val>[A-Za-z0-9._-]{2,64}@[A-Za-z0-9_-]{2,64})\b"
)
_ABHA_ADDR_BARE_RE = re.compile(r"\b[A-Za-z0-9._-]{3,64}@(?:abdm|ndhm|sbx)\b", re.IGNORECASE)
_ABHA_NUM_RE = re.compile(
    rf"{_LB}(?:\d{{2}}[ \t-]\d{{4}}[ \t-]\d{{4}}[ \t-]\d{{4}}|\d{{14}}){_RB}"
)
_AADHAAR_MASKED_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[Xx*]{4}[ \t-]?){2}\d{4}(?![A-Za-z0-9])"
)
_AADHAAR_RE = re.compile(
    rf"(?<![+A-Za-z0-9])(?<![A-Za-z0-9][./-])(?:\d{{4}}[ \t-]\d{{4}}[ \t-]\d{{4}}|\d{{4}}[ \t-]\d{{8}}|\d{{12}}){_RB}"
)
_PHONE_RE = re.compile(
    rf"{_LB}(?:\+?91[ \t-]?|0[ \t-]?)?[6-9](?:[ \t-]?\d){{9}}{_RB}"
)
_PAN_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z]{5}\d{4}[A-Z](?![A-Za-z0-9])")


def is_email(value: str) -> bool:
    """True if the whole value has the email shape used by the R6 detector. O(len)."""
    return _EMAIL_RE.fullmatch(value) is not None


def is_pan(value: str) -> bool:
    """True if the whole value has the PAN shape (5 letters, 4 digits, 1 letter). O(len)."""
    return _PAN_RE.fullmatch(value) is not None
_INSURANCE_LABEL_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(?:PMJAY|Insurance|Policy|TPA|Scheme)[ \t]*(?:ID|No\.?|Number)?[ \t]*:[ \t]*"
    r"(?P<val>[A-Za-z0-9/-]*[A-Za-z0-9])(?![A-Za-z0-9])(?![./-][A-Za-z0-9])"
)
_MRN_LABEL_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])"
    r"(?:UHID|Patient[ \t]*ID|Reg(?:istration)?[ \t]*No\.?|IPD[ \t]*No\.?|OPD[ \t]*No\.?|"
    r"MRN|CR[ \t]*No\.?|Admission[ \t]*No\.?|"
    r"पंजीकरण[ \t]*(?:सं\.?|संख्या)|आईपीडी[ \t]*(?:सं\.?|संख्या)|"
    r"ओपीडी[ \t]*(?:सं\.?|संख्या)|रोगी[ \t]*(?:आईडी|सं\.?))"
    r"[ \t]*:[ \t]*(?P<val>[^\s,;|]+)"
)
# Generic letters + separators + digits ID shape (covers unlabelled MRNs, policy/scheme IDs, etc.)
_MRN_SHAPE_RE = re.compile(
    rf"{_LB}(?:[A-Z]{{2,8}}[-/]){{1,3}}\d{{2,12}}(?:[-/]\d{{2,10}})?{_RB}|"
    rf"{_LB}[A-Z]{{2,8}}[-/]?\d{{4,12}}(?:[-/]\d{{2,10}})?{_RB}"
)
_MRN_SHAPE_CI_RE = re.compile(_MRN_SHAPE_RE.pattern, re.IGNORECASE)
_YEAR_SUFFIX_RE = re.compile(r"^([A-Za-z]+)[-/]((?:19|20)\d{2})$")
_DIGIT_RUN_RE = re.compile(r"(?<![A-Za-z0-9])\d{5,12}(?![A-Za-z0-9])")
_DOB_LABEL_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_\u0900-\u097f])"
    r"(?:DOB|Date[ \t]+of[ \t]+Birth|Birth[ \t]+Date|जन्म[ \t]*(?:तिथि|दिनांक))"
    r"[ \t]*:[ \t]*(?P<val>[^\n\r;|]+)"
)
_VILLAGE_LABEL_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_\u0900-\u097f])"
    r"(?:Village|Gram|Gaon|ग्राम|गाँव|गांव|Mohalla|मोहल्ला)"
    r"[ \t]*:[ \t]*(?P<val>[^\n\r;|]+)"
)
_ADDRESS_LABEL_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_\u0900-\u097f])"
    r"(?:Address|पता)(?:[ \t]*\([^)\n\r]*\))?"
    r"[ \t]*:[ \t]*(?P<val>[^\n\r]+)"
)
_ADDRESS_DISTRICT_RE = re.compile(r"(?i)\b(?:Tehsil|Distt\.?|District)\b|(?:तहसील|जिला)")
_ADDRESS_WARD_RE = re.compile(r"(?i)\bWard\b")
_ADDRESS_PIN_RE = re.compile(r"(?<!\d)[1-9]\d{5}(?!\d)")
_PIN_SHAPE_RE = re.compile(r"^[1-9]\d{5}$")


def normalise_digits(text: str) -> str:
    """Convert Devanagari digits (U+0966-U+096F) to ASCII digits 0-9. O(len(text))."""
    return text.translate(_DEVA_DIGIT_TRANS)


def verhoeff_valid(digits: str) -> bool:
    """Return True iff digits passes the Verhoeff check-digit algorithm. O(len(digits))."""
    if not digits or not digits.isdigit():
        return False
    c = 0
    for idx, ch in enumerate(reversed(digits)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[idx % 8][int(ch)]]
    return c == 0


def _strip_phone_prefix(raw_ascii: str) -> str | None:
    """Normalise a candidate phone string to its 10-digit core, or None if invalid."""
    stripped = raw_ascii.strip()
    if stripped.count(" ") + stripped.count("\t") + stripped.count("-") > 3:
        return None
    digits = _NON_DIGIT_RE.sub("", stripped)
    if stripped.startswith("+91"):
        core = digits[2:]
    elif len(digits) == 12 and digits.startswith("91"):
        core = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        core = digits[1:]
    elif len(digits) == 10:
        core = digits
    else:
        return None
    if len(core) == 10 and core[0] in "6789":
        return core
    return None


def extract_phone_core(text: str) -> str | None:
    """Extract a 10-digit Indian mobile core from text (supports Devanagari digits). O(len(text))."""
    ascii_text = normalise_digits(text)
    m = _PHONE_RE.search(ascii_text)
    if m is None:
        return None
    if _UNIT_FOLLOW_RE.match(ascii_text, m.end()):
        return None
    return _strip_phone_prefix(m.group(0))


def _is_valid_mrn_token(token: str) -> bool:
    if _PSN_RE.match(token) or _DATE_LIKE_RE.match(token):
        return False
    if token.startswith("[") and token.endswith("]"):
        return False
    return sum(ch.isdigit() for ch in token) >= 4


def _trim_sentence_punct(text: str, start: int, end: int) -> tuple[int, str]:
    """Strip trailing sentence-final punctuation from a captured label value without touching ID chars."""
    while end > start and text[end - 1] in ".!?;,":
        end -= 1
    return end, text[start:end]


def _collect_spans(
    ascii_text: str,
    *,
    allow_lowercase_mrn: bool = False,
    mrn_cores: frozenset[str] = frozenset(),
    redact_dob: bool = True,
) -> list[tuple[int, int, str]]:
    """Collect non-overlapping R6 PII spans in priority order using an O(bytes) occupancy mask.

    Complexity: O(len(ascii_text)).
    """
    spans: list[tuple[int, int, str]] = []
    occupied = bytearray(len(ascii_text))

    def _add(s: int, e: int, kind: str) -> None:
        if s < e and not any(occupied[s:e]):
            occupied[s:e] = b"\x01" * (e - s)
            spans.append((s, e, kind))

    if "@" in ascii_text:
        for m in _EMAIL_RE.finditer(ascii_text):
            _add(m.start(), m.end(), "EMAIL")

        for m in _ABHA_ADDR_LABEL_RE.finditer(ascii_text):
            _add(m.start("val"), m.end("val"), "ABHA_ADDRESS")
        for m in _ABHA_ADDR_BARE_RE.finditer(ascii_text):
            _add(m.start(), m.end(), "ABHA_ADDRESS")

    for m in _ABHA_NUM_RE.finditer(ascii_text):
        _add(m.start(), m.end(), "ABHA")

    for m in _AADHAAR_MASKED_RE.finditer(ascii_text):
        _add(m.start(), m.end(), "AADHAAR_MASKED")

    for m in _AADHAAR_RE.finditer(ascii_text):
        digits = _NON_DIGIT_RE.sub("", m.group(0))
        if len(digits) == 12:
            # 12 contiguous digits starting with 91[6-9] that fail Verhoeff may be a 91-prefixed phone
            is_contiguous = m.group(0).isdigit()
            if is_contiguous and digits.startswith("91") and digits[2] in "6789" and not verhoeff_valid(digits):
                continue
            _add(m.start(), m.end(), "AADHAAR")

    for m in _PHONE_RE.finditer(ascii_text):
        if _UNIT_FOLLOW_RE.match(ascii_text, m.end()):
            continue
        if _strip_phone_prefix(m.group(0)) is not None:
            _add(m.start(), m.end(), "PHONE")

    for m in _PAN_RE.finditer(ascii_text):
        _add(m.start(), m.end(), "PAN")

    for m in _INSURANCE_LABEL_RE.finditer(ascii_text):
        end, val = _trim_sentence_punct(ascii_text, m.start("val"), m.end("val"))
        if not _PSN_RE.match(val) and any(ch.isdigit() for ch in val) and len(val) >= 4:
            _add(m.start("val"), end, "INSURANCE")

    for m in _MRN_LABEL_RE.finditer(ascii_text):
        end, val = _trim_sentence_punct(ascii_text, m.start("val"), m.end("val"))
        if not _PSN_RE.match(val) and not (val.startswith("[") and val.endswith("]")):
            if any(ch.isdigit() for ch in val):
                _add(m.start("val"), end, "MRN")

    mrn_rx = _MRN_SHAPE_CI_RE if allow_lowercase_mrn else _MRN_SHAPE_RE
    id_prefixes: frozenset[str] = frozenset()
    if allow_lowercase_mrn:
        from wards.columns import CHANNEL_ID_PREFIXES

        id_prefixes = CHANNEL_ID_PREFIXES
    for m in mrn_rx.finditer(ascii_text):
        tok = m.group(0)
        if allow_lowercase_mrn:
            ym = _YEAR_SUFFIX_RE.match(tok)
            if ym is not None:
                prefix = ym.group(1).casefold()
                year_digits = ym.group(2)
                if prefix not in id_prefixes and year_digits not in mrn_cores:
                    continue
        if _is_valid_mrn_token(tok):
            _add(m.start(), m.end(), "MRN")

    if mrn_cores:
        for m in _DIGIT_RUN_RE.finditer(ascii_text):
            if m.group(0) in mrn_cores:
                _add(m.start(), m.end(), "MRN")

    if redact_dob:
        for m in _DOB_LABEL_RE.finditer(ascii_text):
            end, val = _trim_sentence_punct(ascii_text, m.start("val"), m.end("val"))
            if any(ch.isdigit() for ch in val):
                _add(m.start("val"), end, "DOB")

    for m in _VILLAGE_LABEL_RE.finditer(ascii_text):
        end, val = _trim_sentence_punct(ascii_text, m.start("val"), m.end("val"))
        if val.strip():
            _add(m.start("val"), end, "VILLAGE")

    for m in _ADDRESS_LABEL_RE.finditer(ascii_text):
        val = m.group("val")
        val_start = m.start("val")
        # Preserve Tehsil/District suffixes (or trailing hospital Ward) while redacting street/village and PIN
        keep_m = _ADDRESS_DISTRICT_RE.search(val) or _ADDRESS_WARD_RE.search(val)
        if keep_m is not None:
            if keep_m.start() > 0:
                prefix = val[: keep_m.start()].rstrip(" ,;-")
                if prefix:
                    _add(val_start, val_start + len(prefix), "ADDRESS")
            for pin_m in _ADDRESS_PIN_RE.finditer(val, pos=keep_m.start()):
                _add(val_start + pin_m.start(), val_start + pin_m.end(), "PIN")
        elif val.strip():
            _add(val_start, m.end("val"), "ADDRESS")

    spans.sort(key=lambda item: item[0])
    return spans


def find_identifier_spans(
    text: str,
    *,
    allow_lowercase_mrn: bool = False,
    mrn_cores: frozenset[str] = frozenset(),
) -> list[tuple[int, int, str]]:
    """Return sorted non-overlapping R6 spans for text without mutating it. O(len(text))."""
    if not text:
        return []
    return _collect_spans(
        normalise_digits(text),
        allow_lowercase_mrn=allow_lowercase_mrn,
        mrn_cores=mrn_cores,
    )


def extract_mrn_tokens(text: str) -> list[str]:
    """Extract MRN strings detected by R6 patterns in text. O(len(text))."""
    if not text:
        return []
    return [text[s:e] for s, e, kind in find_identifier_spans(text) if kind == "MRN"]


def pin_prefix_mask(pin: str, prefix_digits: int) -> str:
    """Keep the leading prefix_digits of a 6-digit PIN and mask the rest (R13). O(1)."""
    keep = max(1, min(PIN_DIGITS, prefix_digits))
    return pin[:keep] + PIN_MASK_CHAR * (PIN_DIGITS - keep)


def redact_identifiers(
    text: str,
    *,
    redact_dob: bool = True,
    pin_prefix_digits: int | None = None,
) -> tuple[str, int]:
    """Replace R6 identifiers and phones in text with typed placeholders.

    PINs are always detected; with pin_prefix_digits set (R13 policy) they keep that prefix
    instead of the placeholder.

    Devanagari digits are mapped 1-to-1 to ASCII so character offsets match original text.
    Preserves PSN-XXXXXX tokens, doses, frequencies, and lab values.
    Complexity: O(len(text)).
    """
    if not text:
        return text, 0
    ascii_text = normalise_digits(text)
    spans = _collect_spans(ascii_text, redact_dob=redact_dob)
    if not spans:
        return text, 0

    parts: list[str] = []
    cursor = 0
    for start, end, kind in spans:
        parts.append(text[cursor:start])
        if kind == "PIN" and pin_prefix_digits is not None:
            parts.append(pin_prefix_mask(ascii_text[start:end], pin_prefix_digits))
        else:
            parts.append(PLACEHOLDERS[kind])
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts), len(spans)


def classify_value_shape(value: str) -> str | None:
    """Classify a single non-empty cell value by R6 shape for column voting. O(len(value))."""
    s = normalise_digits(value.strip())
    if not s:
        return None
    if _EMAIL_RE.fullmatch(s):
        return "EMAIL"
    if _ABHA_ADDR_BARE_RE.fullmatch(s):
        return "ABHA_ADDRESS"
    if _PAN_RE.fullmatch(s):
        return "PAN"
    if _ABHA_NUM_RE.fullmatch(s):
        return "ABHA"
    if _AADHAAR_MASKED_RE.fullmatch(s):
        return "AADHAAR_MASKED"
    if _AADHAAR_RE.fullmatch(s):
        digits = _NON_DIGIT_RE.sub("", s)
        if not (s.isdigit() and digits.startswith("91") and digits[2] in "6789" and not verhoeff_valid(digits)):
            return "AADHAAR"
    if _PHONE_RE.fullmatch(s) and _strip_phone_prefix(s) is not None:
        return "PHONE"
    if _MRN_SHAPE_RE.fullmatch(s) and _is_valid_mrn_token(s):
        return "MRN"
    if _PIN_SHAPE_RE.fullmatch(s):
        return "PIN"
    return None


# Precompiled R9 base64 / RFC 2397 data: URI shape patterns (single regex per shape; O(len))
_DATA_URI_B64_RE = re.compile(r"^(?P<prefix>data:[^,]*;base64,)(?P<body>.*)$", re.IGNORECASE | re.DOTALL)
B64_WHITESPACE_RE = re.compile(r"[ \t\r\n]+")
_B64_STD_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
_B64_URL_RE = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")
B64_URL_TRANSLATE = str.maketrans("-_", "+/")


def split_data_uri_base64(value: str) -> tuple[str, str] | None:
    """Split an RFC 2397 ``data:...;base64,`` URI into (prefix, body), or None. O(len(value))."""
    if len(value) < DATA_URI_MIN_LEN or not value[: len(DATA_URI_PREFIX)].lower() == DATA_URI_PREFIX:
        return None
    m = _DATA_URI_B64_RE.match(value)
    if m is None:
        return None
    return m.group("prefix"), m.group("body")


def match_base64_shape(compact: str) -> tuple[bool, bool, bool] | None:
    """Validate base64 alphabet, length, and padding rules on whitespace-free text.

    Returns ``(is_urlsafe, had_padding, is_std_chars)`` or None when shape/padding is invalid.
    Complexity: O(len(compact)).
    """
    n = len(compact)
    if n < BASE64_MIN_EXPLICIT_LEN:
        return None
    had_padding = compact.endswith("=")
    if had_padding:
        if n % 4 != 0:
            return None
    elif n % 4 == 1:
        return None

    if _B64_STD_RE.fullmatch(compact) is not None:
        return False, had_padding, True
    if _B64_URL_RE.fullmatch(compact) is not None:
        return True, had_padding, False
    return None

