"""R12 format-preserving date parsing, convention voting, and per-patient shifting."""
from __future__ import annotations

import calendar
import datetime as dt
import re
from typing import Iterable

from wards.config import (
    DATE_MAX_YEAR,
    DATE_MIN_YEAR,
    MONTH_ABBR_VARIANTS,
    PLACEHOLDERS,
    TWO_DIGIT_YEAR_PIVOT,
    YEARLESS_REFERENCE_YEAR,
)
from wards.patterns import PROTECTED_TOKEN_RE, normalise_digits
from wards.pseudo import shift_date

DATE_ORDER_DMY = "dmy"
DATE_ORDER_MDY = "mdy"
DATE_ORDER_ISO = "ymd"

_MONTHS_PER_YEAR = len(calendar.month_name) - 1
_MAX_DAY_IN_MONTH = max(calendar.mdays)
_CENTURY = 100

_MONTH_LOOKUP: dict[str, tuple[int, bool]] = {}
for _m_idx in range(1, _MONTHS_PER_YEAR + 1):
    _MONTH_LOOKUP[calendar.month_name[_m_idx].casefold()] = (_m_idx, False)
    _MONTH_LOOKUP[calendar.month_abbr[_m_idx].casefold()] = (_m_idx, True)
for _variant, _m_idx in sorted(MONTH_ABBR_VARIANTS.items()):
    _MONTH_LOOKUP.setdefault(_variant, (_m_idx, True))

_MONTH_NAMES_ALT = "|".join(re.escape(k) for k in sorted(_MONTH_LOOKUP, key=len, reverse=True))

# Four-digit years in [DATE_MIN_YEAR, DATE_MAX_YEAR], as their century prefixes ("19|20").
_YEAR4 = (
    "(?:"
    + "|".join(str(c) for c in range(DATE_MIN_YEAR // _CENTURY, DATE_MAX_YEAR // _CENTURY + 1))
    + r")\d{2}"
)

# A '.', '/' or '-' after a date blocks the match only when an alphanumeric follows it, so a
# sentence-final full stop still ends a date (MISTAKES: ID regexes and prose punctuation).
_DATE_END = r"(?![A-Za-z0-9]|[/.-][A-Za-z0-9])"

_ISO_DATE_RE = re.compile(
    r"(?<![A-Za-z0-9/.-])"
    rf"(?P<y>{_YEAR4})-(?P<m>\d{{2}})-(?P<d>\d{{2}})"
    r"(?P<tail>(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?)"
    + _DATE_END
)
_NUM_4Y_RE = re.compile(
    r"(?<![A-Za-z0-9/.-])"
    rf"(?P<a>\d{{1,2}})(?P<sep>[-/])(?P<b>\d{{1,2}})(?P=sep)(?P<y>{_YEAR4})"
    + _DATE_END
)
_NUM_2Y_RE = re.compile(
    r"(?<![A-Za-z0-9/.-])"
    r"(?P<a>\d{1,2})(?P<sep>[-/])(?P<b>\d{1,2})(?P=sep)(?P<y>\d{2})"
    + _DATE_END
)
_DAY_MONTH_NAME_RE = re.compile(
    rf"(?<![A-Za-z0-9/.-])"
    rf"(?P<d>\d{{1,2}})(?P<sep>[ \t-]+)(?P<mon>{_MONTH_NAMES_ALT})"
    rf"(?:(?P<ysep>[ \t,-]+)(?P<y>{_YEAR4}))?"
    + _DATE_END,
    re.IGNORECASE,
)
_MONTH_DAY_NAME_RE = re.compile(
    rf"(?<![A-Za-z0-9/.-])"
    rf"(?P<mon>{_MONTH_NAMES_ALT})(?P<sep>[ \t.-]+)(?P<d>\d{{1,2}})"
    rf"(?:(?P<ysep>[ \t,.-]+)(?P<y>{_YEAR4}))?"
    + _DATE_END,
    re.IGNORECASE,
)


def infer_date_order(samples: Iterable[str]) -> str:
    """Vote between day-first ('dmy') and month-first ('mdy') numeric dates. O(total chars)."""
    dmy_votes = 0
    mdy_votes = 0
    for text in samples:
        if not text:
            continue
        ascii_text = normalise_digits(text)
        for rx in (_NUM_4Y_RE, _NUM_2Y_RE):
            for m in rx.finditer(ascii_text):
                a = int(m.group("a"))
                b = int(m.group("b"))
                if a > _MONTHS_PER_YEAR and 1 <= b <= _MONTHS_PER_YEAR:
                    dmy_votes += 1
                elif b > _MONTHS_PER_YEAR and 1 <= a <= _MONTHS_PER_YEAR:
                    mdy_votes += 1
    return DATE_ORDER_MDY if mdy_votes > dmy_votes else DATE_ORDER_DMY


def _expand_two_digit_year(yy: int) -> int:
    century = DATE_MIN_YEAR if yy >= TWO_DIGIT_YEAR_PIVOT else DATE_MIN_YEAR + _CENTURY
    return century + yy


def _safe_date(year: int, month: int, day: int) -> dt.date | None:
    if not (
        DATE_MIN_YEAR <= year <= DATE_MAX_YEAR
        and 1 <= month <= _MONTHS_PER_YEAR
        and 1 <= day <= _MAX_DAY_IN_MONTH
    ):
        return None
    max_day = calendar.monthrange(year, month)[1]
    if day > max_day:
        return None
    return dt.date(year, month, day)


def _format_month_word(orig_mon: str, new_month: int, is_abbr: bool) -> str:
    base = calendar.month_abbr[new_month] if is_abbr else calendar.month_name[new_month]
    if orig_mon.isupper():
        return base.upper()
    if orig_mon.islower():
        return base.lower()
    return base


def _resolve_numeric_date(a: int, b: int, year: int, order: str) -> tuple[dt.date | None, str]:
    """Resolve (a, b, year) using voted order, falling back cleanly when one field > 12."""
    if order == DATE_ORDER_MDY:
        primary = _safe_date(year, a, b)
        if primary is not None:
            return primary, DATE_ORDER_MDY
        if a > _MONTHS_PER_YEAR and 1 <= b <= _MONTHS_PER_YEAR:
            fallback = _safe_date(year, b, a)
            if fallback is not None:
                return fallback, DATE_ORDER_DMY
        return None, DATE_ORDER_MDY

    primary = _safe_date(year, b, a)
    if primary is not None:
        return primary, DATE_ORDER_DMY
    if b > _MONTHS_PER_YEAR and 1 <= a <= _MONTHS_PER_YEAR:
        fallback = _safe_date(year, a, b)
        if fallback is not None:
            return fallback, DATE_ORDER_MDY
    return None, DATE_ORDER_DMY


def parse_dob_iso(text: str, *, order: str = DATE_ORDER_DMY) -> str | None:
    """Parse a DOB string in ISO, numeric, or named-month format to 'YYYY-MM-DD'. O(len(text))."""
    if not text or not text.strip():
        return None
    s = normalise_digits(text.strip())

    m_iso = _ISO_DATE_RE.search(s)
    if m_iso is not None:
        d = _safe_date(int(m_iso.group("y")), int(m_iso.group("m")), int(m_iso.group("d")))
        if d is not None:
            return d.isoformat()

    m4 = _NUM_4Y_RE.search(s)
    if m4 is not None:
        d, _ = _resolve_numeric_date(int(m4.group("a")), int(m4.group("b")), int(m4.group("y")), order)
        if d is not None:
            return d.isoformat()

    m2 = _NUM_2Y_RE.search(s)
    if m2 is not None:
        yr = _expand_two_digit_year(int(m2.group("y")))
        d, _ = _resolve_numeric_date(int(m2.group("a")), int(m2.group("b")), yr, order)
        if d is not None:
            return d.isoformat()

    md = _DAY_MONTH_NAME_RE.search(s)
    if md is not None and md.group("y"):
        mon_num, _ = _MONTH_LOOKUP[md.group("mon").casefold()]
        d = _safe_date(int(md.group("y")), mon_num, int(md.group("d")))
        if d is not None:
            return d.isoformat()

    md2 = _MONTH_DAY_NAME_RE.search(s)
    if md2 is not None and md2.group("y"):
        mon_num, _ = _MONTH_LOOKUP[md2.group("mon").casefold()]
        d = _safe_date(int(md2.group("y")), mon_num, int(md2.group("d")))
        if d is not None:
            return d.isoformat()

    return None


def _context_year(ascii_text: str) -> int:
    """Year for dates written without one: the first full date's year in the same text,
    else YEARLESS_REFERENCE_YEAR. O(len(text))."""
    starts = [
        (m.start(), int(m.group("y")))
        for m in (rx.search(ascii_text) for rx in (_ISO_DATE_RE, _NUM_4Y_RE))
        if m is not None
    ]
    return min(starts)[1] if starts else YEARLESS_REFERENCE_YEAR


def _fmt_part(val: int, orig: str) -> str:
    return f"{val:02d}" if len(orig) == 2 else str(val)


def shift_dates_in_text(
    text: str,
    offset_days: int,
    *,
    order: str = DATE_ORDER_DMY,
    reason_counts: dict[str, int] | None = None,
) -> tuple[str, int]:
    """Shift every calendar date in text by offset_days, keeping original formats.

    Returns (shifted_text, count_shifted). Uses occupancy mask for O(len(text)) complexity.
    Never leaves a recognisable invalid numeric date in place.
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

    yearless_year = _context_year(ascii_text)

    # 1. ISO YYYY-MM-DD (+ optional time/timezone suffix)
    for m in _ISO_DATE_RE.finditer(ascii_text):
        s, e = m.start(), m.end()
        if any(occupied[s:e]):
            continue
        parsed = _safe_date(int(m.group("y")), int(m.group("m")), int(m.group("d")))
        if parsed is not None:
            shifted = shift_date(parsed, offset_days)
            _claim(s, e, f"{shifted.year:04d}-{shifted.month:02d}-{shifted.day:02d}{m.group('tail')}")
        else:
            if reason_counts is not None:
                reason_counts["ambiguous_or_invalid_date"] = reason_counts.get("ambiguous_or_invalid_date", 0) + 1
            _claim(s, e, PLACEHOLDERS["DOB"])

    # 2. Numeric D/M/YYYY or M/D/YYYY
    for m in _NUM_4Y_RE.finditer(ascii_text):
        s, e = m.start(), m.end()
        if any(occupied[s:e]):
            continue
        a_str, b_str, sep, y_str = m.group("a"), m.group("b"), m.group("sep"), m.group("y")
        parsed, eff_order = _resolve_numeric_date(int(a_str), int(b_str), int(y_str), order)
        if parsed is not None:
            shifted = shift_date(parsed, offset_days)
            if eff_order == DATE_ORDER_MDY:
                repl = f"{_fmt_part(shifted.month, a_str)}{sep}{_fmt_part(shifted.day, b_str)}{sep}{shifted.year:04d}"
            else:
                repl = f"{_fmt_part(shifted.day, a_str)}{sep}{_fmt_part(shifted.month, b_str)}{sep}{shifted.year:04d}"
            _claim(s, e, repl)
        else:
            if reason_counts is not None:
                reason_counts["ambiguous_or_invalid_date"] = reason_counts.get("ambiguous_or_invalid_date", 0) + 1
            _claim(s, e, PLACEHOLDERS["DOB"])

    # 3. Numeric DD/MM/YY (e.g. chat/export timestamps)
    for m in _NUM_2Y_RE.finditer(ascii_text):
        s, e = m.start(), m.end()
        if any(occupied[s:e]):
            continue
        a_str, b_str, sep, y_str = m.group("a"), m.group("b"), m.group("sep"), m.group("y")
        a_val, b_val = int(a_str), int(b_str)
        # Skip single-digit-only frequency shapes like 1-0-1 already guardable via 0 check
        if a_val == 0 or b_val == 0:
            continue
        yr = _expand_two_digit_year(int(y_str))
        parsed, eff_order = _resolve_numeric_date(a_val, b_val, yr, order)
        if parsed is not None:
            shifted = shift_date(parsed, offset_days)
            yy_out = f"{shifted.year % _CENTURY:02d}"
            if eff_order == DATE_ORDER_MDY:
                repl = f"{_fmt_part(shifted.month, a_str)}{sep}{_fmt_part(shifted.day, b_str)}{sep}{yy_out}"
            else:
                repl = f"{_fmt_part(shifted.day, a_str)}{sep}{_fmt_part(shifted.month, b_str)}{sep}{yy_out}"
            _claim(s, e, repl)

    # 4. Named months: "5 September" / "28 Mar 2026"
    for m in _DAY_MONTH_NAME_RE.finditer(ascii_text):
        s, e = m.start(), m.end()
        if any(occupied[s:e]):
            continue
        d_str, sep, mon_str = m.group("d"), m.group("sep"), m.group("mon")
        mon_num, is_abbr = _MONTH_LOOKUP[mon_str.casefold()]
        has_year = bool(m.group("y"))
        yr = int(m.group("y")) if has_year else yearless_year
        parsed = _safe_date(yr, mon_num, int(d_str))
        if parsed is not None:
            shifted = shift_date(parsed, offset_days)
            new_mon = _format_month_word(mon_str, shifted.month, is_abbr)
            repl = f"{_fmt_part(shifted.day, d_str)}{sep}{new_mon}"
            if has_year and m.group("ysep"):
                repl += f"{m.group('ysep')}{shifted.year:04d}"
            _claim(s, e, repl)

    for m in _MONTH_DAY_NAME_RE.finditer(ascii_text):
        s, e = m.start(), m.end()
        if any(occupied[s:e]):
            continue
        mon_str, sep, d_str = m.group("mon"), m.group("sep"), m.group("d")
        mon_num, is_abbr = _MONTH_LOOKUP[mon_str.casefold()]
        has_year = bool(m.group("y"))
        yr = int(m.group("y")) if has_year else yearless_year
        parsed = _safe_date(yr, mon_num, int(d_str))
        if parsed is not None:
            shifted = shift_date(parsed, offset_days)
            new_mon = _format_month_word(mon_str, shifted.month, is_abbr)
            repl = f"{new_mon}{sep}{_fmt_part(shifted.day, d_str)}"
            if has_year and m.group("ysep"):
                repl += f"{m.group('ysep')}{shifted.year:04d}"
            _claim(s, e, repl)

    if not edits:
        return text, 0

    edits.sort(key=lambda item: item[0])
    parts: list[str] = []
    cursor = 0
    for s, e, repl in edits:
        parts.append(text[cursor:s])
        parts.append(repl)
        cursor = e
    parts.append(text[cursor:])
    return "".join(parts), len(edits)
