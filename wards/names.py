"""R7 free-text patient/relative name detection and R8 medical preservation rules."""
from __future__ import annotations

import re
import unicodedata
from bisect import bisect_left

from wards.config import (
    ATTENDANT_ACTION_VERBS,
    CHANNEL_SAFE_WORDS,
    CLINICAL_HEAD_NOUNS,
    COMPLAINT_WORDS,
    DEVA_SYMPTOM_WORDS,
    DEVA_TIME_UNITS,
    DOCUMENT_SUBJECT_NOUNS,
    HINGLISH_SUBJECT_MARKERS,
    KCO_HO_WINDOW_CHARS,
    NAME_LABELS,
    NAME_LABEL_STOP_WORDS,
    NON_NAME_WORDS,
    PLACEHOLDERS,
    PRE_REL_LOOKBACK_CHARS,
    PREFIX_HONORIFICS,
    REFERRAL_CLINICAL_VERBS,
    RELATIVE_LABELS,
    SUFFIX_HONORIFICS,
)

# Token building blocks (horizontal whitespace only so line counts stay unchanged)
_LATIN_TOK = r"(?:[A-Za-z][A-Za-z'.-]{0,30})"
_DEVA_TOK = r"(?:[\u0900-\u097f]{1,30})"
_NAME_TOK = rf"(?:{_LATIN_TOK}|{_DEVA_TOK})"
_TITLE_LATIN = r"(?:[A-Z][A-Za-z'.-]{0,30})"
_CAP_OR_DEVA = rf"(?:{_TITLE_LATIN}|{_DEVA_TOK})"

_PRE_HON_ALT = "|".join(re.escape(h) for h in sorted(PREFIX_HONORIFICS, key=len, reverse=True))
_SUF_HON_ALT = "|".join(re.escape(h) for h in sorted(SUFFIX_HONORIFICS, key=len, reverse=True))
_PAT_LABELS_ALT = "|".join(re.escape(lbl) for lbl in sorted(NAME_LABELS, key=len, reverse=True))
_REL_LABELS_ALT = "|".join(re.escape(lbl) for lbl in sorted(RELATIVE_LABELS, key=len, reverse=True))
_REL_LABELS_CF = frozenset(lbl.casefold() for lbl in RELATIVE_LABELS)
_STOP_WORDS_ALT = "|".join(
    re.escape(w) for w in sorted(set(NAME_LABEL_STOP_WORDS) | set(NAME_LABELS) | set(RELATIVE_LABELS), key=len, reverse=True)
)
_REFERRAL_VERBS_ALT = "|".join(re.escape(v) for v in REFERRAL_CLINICAL_VERBS)
_DOC_NOUNS_ALT = "|".join(re.escape(n) for n in DOCUMENT_SUBJECT_NOUNS)
_ATT_VERBS_ALT = "|".join(re.escape(v) for v in ATTENDANT_ACTION_VERBS)
_DEVA_TIME_ALT = "|".join(re.escape(u) for u in DEVA_TIME_UNITS)
_DEVA_SYMP_ALT = "|".join(re.escape(s) for s in DEVA_SYMPTOM_WORDS)
_HINGLISH_MKR_ALT = "|".join(re.escape(m) for m in HINGLISH_SUBJECT_MARKERS)

# Protect-mask patterns (R8): run first so medical facts, doctors, and placeholders stay untouched
_FAST_PROTECT_RE = re.compile(
    r"\[[A-Z_]+\]|PSN-[0-9A-Z]{6}|"
    r"(?i:\b(?:Ward|Bed|Department)[ \t]*(?:\([^)\n\r]+\)|of[ \t]+[A-Za-z]+|\d+)?\b)|\bASHA\b|"
    r"(?i:\b\d+(?:\.\d+)?[ \t]*(?:mg|mcg|ug|gm?|kg|ml|dl|l|iu|units?|mmhg|bpm|meq|mmol|/ul|/dl|/l|%)\b|"
    r"\b\d+-\d+-\d+\b|\b(?:BP|Pulse|Temp|SpO2|RBS|Hb|HbA1c|TLC|WBC|Plt)[ \t:]*\d+(?:[./]\d+)?\b)"
)
_KCO_HO_START_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9/])(?:No[ \t]+)?(?:N/K/C/O|K/C/O|H/O)[ \t]*:?[ \t]*"
)
_KCO_HO_STOP_RE = re.compile(
    rf"(?i)[\n\r.;|]|,[ \t]*(?:{_REFERRAL_VERBS_ALT})\b|"
    rf"[ \t]+by\b|(?<![A-Za-z0-9_\u0900-\u097f])(?:{_PRE_HON_ALT})\b|"
    rf"(?<![A-Za-z0-9])[SDWC][ \t]*/[ \t]*[Oo]\b|"
    rf"(?<![A-Za-z0-9_\u0900-\u097f])(?:{_STOP_WORDS_ALT})[ \t]*:"
)
_DOCTOR_PROTECT_RE = re.compile(
    r"(?<![A-Za-z0-9_\u0900-\u097f])(?:Dr\.?|डॉ\.?)[ \t]+"
    rf"(?P<doc>{_NAME_TOK}(?:[ \t]+{_NAME_TOK}){{0,2}})"
    r"(?:[ \t]*\([^)\n\r]{1,40}\))?",
)
_DOCTOR_CHANNEL_PROTECT_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9\u0900-\u097f])(?:Dr\.?|डॉ\.?)[ \t_]+"
    rf"(?P<doc>{_NAME_TOK}(?:[ \t_]+{_NAME_TOK}){{0,2}})"
)
_CHANNEL_DOC_TOK_RE = re.compile(r"[^ \t_]+")
_DOCTOR_STOP_WORDS = frozenset(CHANNEL_SAFE_WORDS) | frozenset(NON_NAME_WORDS) | frozenset(NAME_LABEL_STOP_WORDS)
_POSSESSIVE_EPONYM_RE = re.compile(
    rf"\b(?P<eponym>{_TITLE_LATIN})['\u2019]s?[ \t]+(?P<head>[A-Za-z]+)\b"
)
_CAP_CLINICAL_PAIR_RE = re.compile(
    rf"\b(?P<eponym>{_TITLE_LATIN})[ \t]+(?P<head>[A-Za-z]+)\b"
)

# Boundary precomputation regexes (O(len(text)) once per call)
_NEWLINE_RE = re.compile(r"\n")
_STOP_TRIGGER_RE = re.compile(
    rf"(?i)(?<![A-Za-z0-9_\u0900-\u097f])"
    rf"(?:(?:{_STOP_WORDS_ALT})[ \t]*:|"
    rf"[SDWC][ \t]*/[ \t]*[Oo](?![A-Za-z0-9])|"
    rf"[SDW]\.o\.(?![A-Za-z0-9])|"
    rf"(?:पुत्र|पुत्री|पत्नी|पति|बेटा|बेटी)(?![\u0900-\u097f])|"
    rf"(?:beta|beti|patni|husband|wife|son|daughter)[ \t]+of\b)"
)

# Pass A: Label context (matches ONLY the label/trigger so finditer sees every subsequent label on the same line)
_ANY_LABEL_RE = re.compile(
    rf"(?i)(?<![A-Za-z0-9_\u0900-\u097f])(?P<lbl>{_REL_LABELS_ALT}|{_PAT_LABELS_ALT})[ \t]*:[ \t]*"
)
# Generic clinical prose triggers:
# - "<doc> for/of <Name>": clinical document/visit phrases naming the patient subject
# - "<action> by <Name>": passive-voice clinical/contact verbs naming a caller/attendant/witness
_INLINE_PROSE_LABEL_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_\u0900-\u097f])"
    rf"(?:(?:{_DOC_NOUNS_ALT})[ \t]+(?:for|of)|"
    rf"(?:{_ATT_VERBS_ALT})[ \t]+by)[ \t]+"
)

# Pass B: Relation markers (matches ONLY the marker, then extracts bounded name span)
_REL_CODE_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?P<marker>[SDWC][ \t]*/[ \t]*[Oo]|[SDW]\.o\.?)[ \t]*:?[ \t]*"
)
_PRE_REL_NAME_RE = re.compile(
    rf"(?P<name>{_CAP_OR_DEVA}(?:[ \t]+{_CAP_OR_DEVA}){{0,3}})"
    r"(?:[ \t]*,[ \t]*|[ \t]+)$"
)
_DEVA_REL_MARKER_RE = re.compile(
    r"(?<![\u0900-\u097f])(?:पुत्र|पुत्री|पत्नी|पति|बेटा|बेटी)[ \t]*(?::|का|की|के)?[ \t]*"
)
_HINGLISH_REL_OF_RE = re.compile(
    r"(?i)\b(?:beta|beti|patni|husband|wife|son|daughter)[ \t]+of[ \t]+"
)

# Pass C: Honorifics & Hinglish/Devanagari subject clues
_BOUNDARY_L = r"(?<![A-Za-z0-9_\u0900-\u097f])"
_BOUNDARY_R = r"(?![A-Za-z0-9_\u0900-\u097f])"
_PREFIX_HONORIFIC_RE = re.compile(
    rf"(?i){_BOUNDARY_L}(?P<hon>{_PRE_HON_ALT})[ \t]+(?P<name_start>)"
)
_SUFFIX_HONORIFIC_RE = re.compile(
    rf"(?i){_BOUNDARY_L}(?P<full>(?P<name>{_CAP_OR_DEVA}(?:[ \t]+{_CAP_OR_DEVA}){{0,1}})"
    rf"[ \t]+(?:{_SUF_HON_ALT})){_BOUNDARY_R}"
)
_ATTENDANT_PAREN_RE = re.compile(
    rf"{_BOUNDARY_L}(?P<name>{_CAP_OR_DEVA}(?:[ \t]+{_CAP_OR_DEVA}){{0,2}})[ \t]*\([ \t]*attendant\b",
    re.IGNORECASE,
)
_DEVA_SUBJECT_KO_RE = re.compile(
    rf"{_BOUNDARY_L}(?P<name>{_DEVA_TOK}(?:[ \t]+{_DEVA_TOK}){{0,2}})[ \t]+को[ \t]+"
    rf"(?:\d+[ \t]+(?:{_DEVA_TIME_ALT})|(?:{_DEVA_SYMP_ALT}))"
)
_HINGLISH_SUBJECT_KA_RE = re.compile(
    rf"{_BOUNDARY_L}(?P<name>{_TITLE_LATIN}(?:[ \t]+{_TITLE_LATIN}){{0,1}})[ \t]+(?:ka|ki|ke)[ \t]+"
    rf"(?:{_HINGLISH_MKR_ALT})\b",
    re.IGNORECASE,
)
_POSSESSIVE_ATTENDANT_RE = re.compile(
    rf"{_BOUNDARY_L}(?P<name>{_CAP_OR_DEVA}(?:[ \t]+{_CAP_OR_DEVA}){{0,2}})['\u2019]s[ \t]+"
    r"(?:attendant|relative|family|mother|father|husband|wife|son|daughter)\b",
    re.IGNORECASE,
)
_AGE_ADJACENT_NAME_RE = re.compile(
    rf"{_BOUNDARY_L}(?P<name>{_CAP_OR_DEVA}(?:[ \t]+{_CAP_OR_DEVA}){{0,2}})"
    r"[ \t]*,?[ \t]+(?=\d{1,3}[ \t]*(?:yrs?|years?|Y[ \t]*/[ \t]*[MF]|वर्ष)\b)"
)
_TRAIL_SUF_HON_RE = re.compile(
    rf"^[ \t]+(?:{_SUF_HON_ALT}){_BOUNDARY_R}",
    re.IGNORECASE,
)
_WORD_TOK_RE = re.compile(r"[^\s,;()]+")
_HAS_DEVA_RE = re.compile(r"[\u0900-\u097f]")

# Table of direct regex rules for Pass C: (pattern, check_group, span_group, kind, gate)
_DIRECT_NAME_RULES: tuple[tuple[re.Pattern[str], str, str, str, str | None], ...] = (
    (_SUFFIX_HONORIFIC_RE, "name", "full", "PATIENT_NAME", None),
    (_ATTENDANT_PAREN_RE, "name", "name", "RELATIVE", "("),
    (_DEVA_SUBJECT_KO_RE, "name", "name", "PATIENT_NAME", "deva"),
    (_HINGLISH_SUBJECT_KA_RE, "name", "name", "PATIENT_NAME", None),
    (_POSSESSIVE_ATTENDANT_RE, "name", "name", "PATIENT_NAME", "apos"),
    (_AGE_ADJACENT_NAME_RE, "name", "name", "PATIENT_NAME", None),
)


def _clean_word_key(word: str) -> str:
    return word.strip(".,!?;:\"'()[]{}").casefold()


def _is_non_name_token(word: str) -> bool:
    key = _clean_word_key(word)
    if not key or any(ch.isdigit() for ch in key):
        return True
    return key in NON_NAME_WORDS


def _is_valid_name_phrase(raw: str) -> bool:
    words = raw.split()
    return bool(words) and not any(_is_non_name_token(w) for w in words)


def _extract_name_prefix_span(
    text: str,
    start_offset: int,
    line_ends: list[int],
    stop_starts: list[int],
    allow_comma_order: bool = False,
    max_tokens: int = 4,
) -> tuple[int, int] | None:
    """Extract a bounded name span from start_offset using O(log N) precomputed boundaries.

    Complexity: O(log N + max_tokens).
    """
    li = bisect_left(line_ends, start_offset)
    line_end = line_ends[li] if li < len(line_ends) else len(text)
    si = bisect_left(stop_starts, start_offset)
    next_stop = stop_starts[si] if si < len(stop_starts) else len(text)
    limit = min(line_end, next_stop)
    if limit <= start_offset:
        return None

    comma_used = False
    end_pos = start_offset
    token_count = 0
    pos = start_offset

    while pos < limit and token_count < max_tokens:
        while pos < limit and text[pos] in " \t":
            pos += 1
        if pos >= limit:
            break
        if text[pos] in "\n\r;|()":
            break
        if text[pos] == ",":
            if allow_comma_order and not comma_used and token_count >= 1:
                peek_pos = pos + 1
                while peek_pos < limit and text[peek_pos] in " \t":
                    peek_pos += 1
                m_peek = _WORD_TOK_RE.match(text, peek_pos, limit)
                if m_peek is not None and not _is_non_name_token(m_peek.group(0)):
                    comma_used = True
                    pos = peek_pos
                    continue
            break

        m = _WORD_TOK_RE.match(text, pos, limit)
        if m is None:
            break
        raw_tok = m.group(0)
        tok = raw_tok.rstrip(",;:|()[]")
        if not tok:
            break
        # Stop before sentence-final punctuation while keeping initials like "R."
        has_sentence_end = tok.endswith(("!", "?", "।")) or (
            tok.endswith(".") and len(tok) > 2
        )
        core_tok = tok.rstrip(".!?।") if has_sentence_end else tok
        if _is_non_name_token(core_tok):
            break
        if core_tok.isascii() and core_tok[0].islower() and _clean_word_key(core_tok) not in SUFFIX_HONORIFICS:
            break

        token_count += 1
        end_pos = pos + len(core_tok) if has_sentence_end else pos + len(tok)
        pos = pos + len(raw_tok)
        if has_sentence_end or raw_tok.endswith((",", ";", "|", ")", "(")):
            break

    if token_count == 0 or end_pos <= start_offset:
        return None
    return start_offset, end_pos


def _build_protect_mask(text: str) -> bytearray:
    """Mark R8 clinical/doctor/eponym/dose spans that must never be redacted as names.

    Complexity: O(len(text)).
    """
    protected = bytearray(len(text))

    def _mark(s: int, e: int) -> None:
        if s < e:
            protected[s:e] = b"\x01" * (e - s)

    for rx in (_FAST_PROTECT_RE, _DOCTOR_PROTECT_RE):
        for m in rx.finditer(text):
            _mark(m.start(), m.end())

    # K/C/O and H/O protect only the clinical term list immediately following the marker (bounded window)
    for m in _KCO_HO_START_RE.finditer(text):
        win_end = min(len(text), m.end() + KCO_HO_WINDOW_CHARS)
        stop_m = _KCO_HO_STOP_RE.search(text, m.end(), win_end)
        end = stop_m.start() if stop_m is not None else win_end
        _mark(m.start(), end)

    if "'" in text or "\u2019" in text:
        for m in _POSSESSIVE_EPONYM_RE.finditer(text):
            if m.group("head").casefold() in CLINICAL_HEAD_NOUNS:
                _mark(m.start(), m.end())

    for m in _CAP_CLINICAL_PAIR_RE.finditer(text):
        if m.group("head").casefold() in CLINICAL_HEAD_NOUNS:
            _mark(m.start(), m.end())

    return protected


def _collect_name_spans(text: str) -> list[tuple[int, int, str]]:
    """Collect non-overlapping R7 name spans in O(len(text)) time."""
    protected = _build_protect_mask(text)
    occupied = bytearray(len(text))
    spans: list[tuple[int, int, str]] = []
    has_deva = bool(_HAS_DEVA_RE.search(text))
    has_apos = "'" in text or "\u2019" in text
    has_paren = "(" in text

    line_ends = [m.start() for m in _NEWLINE_RE.finditer(text)]
    stop_starts = [m.start() for m in _STOP_TRIGGER_RE.finditer(text)]

    def _add(s: int, e: int, kind: str) -> None:
        if s < e and not any(protected[s:e]) and not any(occupied[s:e]):
            occupied[s:e] = b"\x01" * (e - s)
            spans.append((s, e, kind))

    # Pass A: Explicit patient & relative labels + generic inline prose triggers
    for m in _ANY_LABEL_RE.finditer(text):
        span = _extract_name_prefix_span(text, m.end(), line_ends, stop_starts, allow_comma_order=True)
        if span is not None:
            kind = "RELATIVE" if m.group("lbl").casefold() in _REL_LABELS_CF else "PATIENT_NAME"
            _add(span[0], span[1], kind)

    for m in _INLINE_PROSE_LABEL_RE.finditer(text):
        span = _extract_name_prefix_span(text, m.end(), line_ends, stop_starts, allow_comma_order=False)
        if span is not None:
            _add(span[0], span[1], "PATIENT_NAME")

    # Pass B: Relation markers (S/o, D/o, W/o, C/O disambiguated, Hindi/Hinglish relations)
    for m in _REL_CODE_RE.finditer(text):
        marker = m.group("marker").replace(" ", "").replace("\t", "").casefold()
        span = _extract_name_prefix_span(text, m.end(), line_ends, stop_starts, allow_comma_order=False, max_tokens=3)
        if span is None:
            continue
        captured = text[span[0]:span[1]]
        cap_words = [_clean_word_key(w) for w in captured.split()]
        if marker == "c/o":
            if any(w in COMPLAINT_WORDS for w in cap_words):
                continue
            if all(w.isascii() and captured.split()[idx][0].islower() for idx, w in enumerate(cap_words) if w):
                continue
        _add(span[0], span[1], "RELATIVE")

        # Also capture a patient name immediately preceding S/o, D/o, W/o; trim leading role words
        if marker.startswith(("s", "d", "w")):
            li = bisect_left(line_ends, m.start())
            line_start = line_ends[li - 1] + 1 if li > 0 else 0
            win_start = max(line_start, m.start() - PRE_REL_LOOKBACK_CHARS)
            pre_m = _PRE_REL_NAME_RE.search(text, win_start, m.start())
            if pre_m is not None:
                raw_pre = pre_m.group("name")
                words = raw_pre.split()
                trim_off = 0
                while words and _is_non_name_token(words[0]):
                    w_idx = raw_pre.find(words[0], trim_off)
                    trim_off = w_idx + len(words[0])
                    while trim_off < len(raw_pre) and raw_pre[trim_off] in " \t":
                        trim_off += 1
                    words.pop(0)
                if words and not any(_is_non_name_token(w) for w in words):
                    _add(pre_m.start("name") + trim_off, pre_m.end("name"), "PATIENT_NAME")

    if has_deva:
        for m in _DEVA_REL_MARKER_RE.finditer(text):
            span = _extract_name_prefix_span(text, m.end(), line_ends, stop_starts, allow_comma_order=False, max_tokens=3)
            if span is not None:
                _add(span[0], span[1], "RELATIVE")

    for m in _HINGLISH_REL_OF_RE.finditer(text):
        span = _extract_name_prefix_span(text, m.end(), line_ends, stop_starts, allow_comma_order=False, max_tokens=3)
        if span is not None:
            _add(span[0], span[1], "RELATIVE")

    # Pass C: Prefix honorifics + rule-table matches
    for m in _PREFIX_HONORIFIC_RE.finditer(text):
        span = _extract_name_prefix_span(text, m.end(), line_ends, stop_starts, allow_comma_order=False, max_tokens=3)
        if span is not None:
            end = span[1]
            suf_m = _TRAIL_SUF_HON_RE.match(text, end)
            if suf_m is not None:
                end = suf_m.end()
            _add(m.start("hon"), end, "PATIENT_NAME")

    for rx, check_grp, span_grp, kind, gate in _DIRECT_NAME_RULES:
        if gate == "deva" and not has_deva:
            continue
        if gate == "apos" and not has_apos:
            continue
        if gate == "(" and not has_paren:
            continue
        for m in rx.finditer(text):
            if _is_valid_name_phrase(m.group(check_grp)):
                _add(m.start(span_grp), m.end(span_grp), kind)

    spans.sort(key=lambda item: item[0])
    return spans


def nfc_with_offset_map(text: str) -> tuple[str, list[int], list[int]]:
    """Normalise text to NFC for matching and build 1-to-1 char index bounds back to text.

    Complexity: O(len(text)).
    """
    nfc_parts: list[str] = []
    orig_starts: list[int] = []
    orig_ends: list[int] = []
    n = len(text)
    idx = 0
    while idx < n:
        end = idx + 1
        while end < n and unicodedata.combining(text[end]) != 0:
            end += 1
        cluster_nfc = unicodedata.normalize("NFC", text[idx:end])
        for ch in cluster_nfc:
            nfc_parts.append(ch)
            orig_starts.append(idx)
            orig_ends.append(end)
        idx = end
    return "".join(nfc_parts), orig_starts, orig_ends


def find_doctor_spans(text: str, *, allow_underscores: bool = False) -> list[tuple[int, int]]:
    """Return R8 doctor-name character spans (start, end) to preserve in text. O(len(text))."""
    if not text:
        return []
    if not allow_underscores:
        return [(m.start(), m.end()) for m in _DOCTOR_PROTECT_RE.finditer(text)]

    spans: list[tuple[int, int]] = []
    for m in _DOCTOR_CHANNEL_PROTECT_RE.finditer(text):
        doc_start = m.start("doc")
        doc_str = m.group("doc")
        doc_end = doc_start
        kept_tokens = 0
        for part_m in _CHANNEL_DOC_TOK_RE.finditer(doc_str):
            tok = part_m.group(0)
            if _clean_word_key(tok) in _DOCTOR_STOP_WORDS:
                break
            doc_end = doc_start + part_m.end()
            kept_tokens += 1
        if kept_tokens > 0:
            spans.append((m.start(), doc_end))
    return spans


def find_name_spans(text: str) -> list[tuple[int, int, str]]:
    """Return R7 (start, end, kind) name spans mapped back to input offsets. O(len(text))."""
    if not text:
        return []
    if unicodedata.is_normalized("NFC", text):
        return _collect_name_spans(text)
    nfc_text, orig_starts, orig_ends = nfc_with_offset_map(text)
    spans = _collect_name_spans(nfc_text)
    return [(orig_starts[s], orig_ends[e - 1], kind) for s, e, kind in spans]


def extract_name_candidates(text: str) -> list[tuple[str, str]]:
    """Extract (surface, kind) name candidates detected by R7 rules without mutating text. O(len(text))."""
    return [(text[s:e], kind) for s, e, kind in find_name_spans(text)]


def redact_names(text: str) -> tuple[str, int]:
    """Redact patient and relative names in free text while preserving R8 medical context.

    Normalises to NFC only for matching; unmatched input text is kept verbatim.
    Complexity: O(len(text)).
    """
    if not text:
        return text, 0

    mapped_spans = find_name_spans(text)
    if not mapped_spans:
        return text, 0

    parts: list[str] = []
    cursor = 0
    for start, end, kind in mapped_spans:
        parts.append(text[cursor:start])
        parts.append(PLACEHOLDERS[kind])
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts), len(mapped_spans)
