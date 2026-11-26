"""R13 truthful quasi-identifier generalisation: age bands, district location, and PIN prefix."""
from __future__ import annotations

import re

from wards.config import (
    AGE_LABEL_WORDS,
    AGE_UNIT_WORDS,
    DISTRICT_MARKER_WORDS,
    LOCATION_LEVEL_TEHSIL,
    MAX_VALID_AGE,
    PIN_DIGITS,
    PIN_LABEL_WORDS,
    PLACEHOLDERS,
    SEX_LABEL_WORDS,
    SEX_VALUE_WORDS,
    TEHSIL_MARKER_WORDS,
)
from wards.patterns import PROTECTED_TOKEN_RE, normalise_digits, pin_prefix_mask
from wards.pseudo import age_band

_WORD_EDGE = r"(?<![A-Za-z0-9_ऀ-ॿ])"
_WORD_END = r"(?![A-Za-z0-9_ऀ-ॿ])"


def _alt(words: tuple[str, ...]) -> str:
    """Regex alternation of words, longest first; a space matches any run of blanks."""
    return "|".join(re.escape(w).replace(r"\ ", r"[ 	]+") for w in sorted(words, key=lambda w: (-len(w), w)))


_STRUCTURED_AGE_NUM_RE = re.compile(r"(?<!\d)(?P<age>\d{1,3})(?!\d)")
# "Age: 48", "Age/Sex: 48/F": a number right after an age label.
_LABELLED_AGE_RE = re.compile(
    rf"(?i){_WORD_EDGE}(?:{_alt(AGE_LABEL_WORDS)})(?:[ 	]*/[ 	]*(?:{_alt(SEX_LABEL_WORDS)}))?"
    r"[ 	]*:[ 	]*(?P<age>\d{1,3})(?![ 	]*[-/.]\d)"
)
# "48/F", "48 Y / M", "52 वर्ष / पुरुष": a number, an optional age unit, then a sex value.
# Durations ("x 12 yrs"), rates ("78/min") and ratios ("120/80") have no sex value, so they never match.
_AGE_SEX_RE = re.compile(
    rf"(?i)(?<![A-Za-z0-9./-])(?P<age>\d{{1,3}})(?:[ 	]*(?:{_alt(AGE_UNIT_WORDS)}))?"
    rf"[ 	]*/[ 	]*(?:{_alt(SEX_VALUE_WORDS)}){_WORD_END}"
)
_PIN_6_RE = re.compile(rf"(?<!\d)(?P<pin>[1-9]\d{{{PIN_DIGITS - 1}}})(?!\d)")
_PIN_LABEL_RE = re.compile(
    rf"(?i){_WORD_EDGE}(?:{_alt(PIN_LABEL_WORDS)})"
    rf"[ 	]*:?[ 	]*(?P<pin>[1-9]\d{{{PIN_DIGITS - 1}}})(?!\d)"
)
_DISTRICT_MARKER_RE = re.compile(rf"(?i){_WORD_EDGE}(?:{_alt(DISTRICT_MARKER_WORDS)})(?![A-Za-z0-9_])")
_TEHSIL_MARKER_RE = re.compile(rf"(?i){_WORD_EDGE}(?:{_alt(TEHSIL_MARKER_WORDS)})(?![A-Za-z0-9_])")


def _apply_edits(text: str, edits: list[tuple[int, int, str]]) -> str:
    if not edits:
        return text
    edits.sort(key=lambda item: item[0])
    parts: list[str] = []
    cursor = 0
    for s, e, repl in edits:
        parts.append(text[cursor:s])
        parts.append(repl)
        cursor = e
    parts.append(text[cursor:])
    return "".join(parts)


def generalise_age_field(value: str, width: int, top_code: int) -> tuple[str, int]:
    """Band the age inside a structured age or age/sex string (e.g. '48/F' -> '45-49/F'). O(len(value))."""
    if not value or not value.strip():
        return value, 0
    ascii_val = normalise_digits(value)
    m = _STRUCTURED_AGE_NUM_RE.search(ascii_val)
    if m is None:
        return value, 0
    age_num = int(m.group("age"))
    if age_num > MAX_VALID_AGE:
        return value, 0
    band = age_band(age_num, width=width, top_code=top_code)
    return value[: m.start("age")] + band + value[m.end("age") :], 1


def generalise_age_int(age: int, width: int, top_code: int) -> str:
    """Band an integer age value cleanly using policy width and top-code. O(1)."""
    return age_band(max(0, age), width=width, top_code=top_code)


def generalise_pin_str(value: str, prefix_digits: int) -> tuple[str, int]:
    """Keep leading prefix_digits of each 6-digit PIN and mask trailing digits. O(len(value))."""
    if not value or not value.strip():
        return value, 0
    ascii_val = normalise_digits(value)
    edits: list[tuple[int, int, str]] = []
    for m in _PIN_6_RE.finditer(ascii_val):
        edits.append((m.start("pin"), m.end("pin"), pin_prefix_mask(m.group("pin"), prefix_digits)))
    if not edits:
        return value, 0
    return _apply_edits(value, edits), len(edits)


def generalise_pin_int(value: int, prefix_digits: int) -> int:
    """Truncate a numeric PIN integer to its leading prefix_digits (keeps JSON int type). O(1)."""
    keep = max(1, min(PIN_DIGITS, prefix_digits))
    factor = 10 ** (PIN_DIGITS - keep)
    return (value // factor) * factor


def generalise_address_field(
    value: str,
    location_level: str,
    prefix_digits: int,
) -> tuple[str, int]:
    """Strip house/locality/village prefix while keeping district and PIN prefix. O(len(value))."""
    if not value or not value.strip():
        return value, 0
    ascii_val = normalise_digits(value)
    marker = _DISTRICT_MARKER_RE.search(ascii_val)
    if marker is None and location_level == LOCATION_LEVEL_TEHSIL:
        marker = _TEHSIL_MARKER_RE.search(ascii_val)

    if marker is None:
        return PLACEHOLDERS["ADDRESS"], 1

    suffix = value[marker.start() :]
    suffix, _ = generalise_pin_str(suffix, prefix_digits)
    if marker.start() > 0:
        return f"{PLACEHOLDERS['ADDRESS']}, {suffix}", 1
    return suffix, 1


def generalise_text_qis(
    text: str,
    width: int,
    top_code: int,
    prefix_digits: int,
) -> tuple[str, int]:
    """Generalise free-text age expressions and labelled/address PINs while preserving clinical durations.

    Complexity: O(len(text)).
    """
    if not text:
        return text, 0

    ascii_text = normalise_digits(text)
    n = len(ascii_text)
    occupied = bytearray(n)
    edits: list[tuple[int, int, str]] = []

    for m in PROTECTED_TOKEN_RE.finditer(ascii_text):
        occupied[m.start() : m.end()] = b"\x01" * (m.end() - m.start())

    def _claim(s: int, e: int, repl: str) -> None:
        if s < e and not any(occupied[s:e]):
            occupied[s:e] = b"\x01" * (e - s)
            edits.append((s, e, repl))

    for rx in (_LABELLED_AGE_RE, _AGE_SEX_RE):
        for m in rx.finditer(ascii_text):
            s, e = m.start("age"), m.end("age")
            if any(occupied[s:e]):
                continue
            age_num = int(m.group("age"))
            if age_num > MAX_VALID_AGE:
                continue
            _claim(s, e, age_band(age_num, width=width, top_code=top_code))

    for m in _PIN_LABEL_RE.finditer(ascii_text):
        _claim(m.start("pin"), m.end("pin"), pin_prefix_mask(m.group("pin"), prefix_digits))

    if not edits:
        return text, 0
    return _apply_edits(text, edits), len(edits)
