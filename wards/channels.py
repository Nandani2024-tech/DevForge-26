"""R9 hidden-channel cleaning: filenames/folders, CSV headers, JSON keys, and path/URL metadata."""
from __future__ import annotations

import base64
import binascii
import codecs
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wards.config import (
    BASE64_MAX_WRAP_WIDTH,
    BASE64_MIN_LEN,
    BASE64_MIN_PRINTABLE_RATIO,
    BASE64_PLACEHOLDER,
    CHANNEL_SAFE_WORDS,
    FILENAME_PLACEHOLDERS,
    MIN_CHANNEL_MRN_DIGITS,
    MIN_CHANNEL_NAME_TOKEN_LEN,
    NAME_LABEL_STOP_WORDS,
    NON_NAME_WORDS,
    PLACEHOLDERS,
)
from wards.names import build_protect_mask, find_doctor_spans, find_name_spans, nfc_with_offset_map
from wards.patterns import (
    B64_URL_TRANSLATE,
    B64_WHITESPACE_RE,
    PROTECTED_TOKEN_RE,
    find_identifier_spans,
    match_base64_shape,
    normalise_digits,
)

_CHANNEL_BLOCKED_WORDS = frozenset(CHANNEL_SAFE_WORDS) | frozenset(NON_NAME_WORDS) | frozenset(NAME_LABEL_STOP_WORDS)

# Precompiled tokenisers and path/filename safety regexes (O(len(text)))
_CHANNEL_TOK_RE = re.compile(
    r"[A-Z]?[a-z']+(?=[A-Z]|[^A-Za-z]|$)|[A-Z]+(?=[A-Z][a-z]|[^A-Za-z]|$)|[\u0900-\u097f]+|\d+"
)
_WORD_EXTRACT_RE = re.compile(r"[a-z']+|\d+|[\u0900-\u097f]+")
_DIGIT_TAIL_RE = re.compile(rf"\d{{{MIN_CHANNEL_MRN_DIGITS},12}}")
_ADJ_SEP_RE = re.compile(r"^[ \t._-]+$")
_UNSAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_WIN_STEMS = frozenset(
    {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
)

_SCHEME_URL_RE = re.compile(r"^(?P<head>[A-Za-z][A-Za-z0-9+.-]*://[^/?#\s]*)(?P<tail>.*)$")
_WIN_DRIVE_RE = re.compile(r"^(?P<drive>[A-Za-z]:[/\\]+)(?P<rest>.*)$")
_POSIX_MULTI_SLASH_RE = re.compile(r"^(?:/[^\s/]+){2,}/?$")
_REL_EXT_PATH_RE = re.compile(r"^[^\s/]+(?:/[^\s/]+)+\.[A-Za-z0-9]{1,6}$")
_PATH_SPLIT_RE = re.compile(r"([/\\]+)")
_QUERY_SPLIT_RE = re.compile(r"([/?#&=]+)")
_EXT_SUFFIX_RE = re.compile(r"^(.+?)(\.[A-Za-z0-9]{1,6})$")


@dataclass
class ChannelEvidence:
    """Run-time PII evidence collected in Pass 1 (tokens and ID cores only, never raw files)."""

    DEFAULT_KIND = "PATIENT_NAME"
    name_tokens: set[str] = field(default_factory=set)
    name_token_kind: dict[str, str] = field(default_factory=dict)
    name_phrases: set[tuple[str, ...]] = field(default_factory=set)
    name_phrase_kind: dict[tuple[str, ...], str] = field(default_factory=dict)
    mrn_full: set[str] = field(default_factory=set)
    mrn_cores: set[str] = field(default_factory=set)
    _mrn_cores_cache: frozenset[str] = field(default_factory=frozenset, repr=False)

    def add_name(self, phrase: str, kind: str = "PATIENT_NAME") -> None:
        """Record normalised name tokens/phrases detected by R5/R7 in content. O(len(phrase))."""
        if not phrase:
            return
        norm = unicodedata.normalize("NFKC", phrase).casefold()
        words = [w.strip("'") for w in _WORD_EXTRACT_RE.findall(norm) if w.strip("'")]
        clean_words = [w for w in words if not any(ch.isdigit() for ch in w)]
        if not clean_words:
            return
        if len(clean_words) >= 2 and not all(w in _CHANNEL_BLOCKED_WORDS for w in clean_words):
            tup = tuple(clean_words)
            self.name_phrases.add(tup)
            if tup not in self.name_phrase_kind or kind == "PATIENT_NAME":
                self.name_phrase_kind[tup] = kind
        for w in clean_words:
            if len(w) >= MIN_CHANNEL_NAME_TOKEN_LEN and w not in _CHANNEL_BLOCKED_WORDS:
                self.name_tokens.add(w)
                if w not in self.name_token_kind or kind == "PATIENT_NAME":
                    self.name_token_kind[w] = kind

    def add_mrn(self, value: str) -> None:
        """Record normalised MRN values and >=5-digit ID cores seen in slots/content. O(len(value))."""
        if not value:
            return
        ascii_cf = unicodedata.normalize("NFKC", normalise_digits(value)).strip().casefold()
        if sum(ch.isdigit() for ch in ascii_cf) >= 4:
            self.mrn_full.add(ascii_cf)
        for core in _DIGIT_TAIL_RE.findall(ascii_cf):
            if core not in self.mrn_cores:
                self.mrn_cores.add(core)
                self._mrn_cores_cache = frozenset()

    @property
    def mrn_cores_frozen(self) -> frozenset[str]:
        """Return cached frozenset of observed >=5-digit MRN cores. O(1) when cached."""
        if not self._mrn_cores_cache and self.mrn_cores:
            self._mrn_cores_cache = frozenset(self.mrn_cores)
        return self._mrn_cores_cache


def looks_like_path_or_url(value: str) -> bool:
    """Detect path- or URL-like strings by value shape (excluding IDs like HSP/26/009999). O(len(value))."""
    if not value or "\n" in value or "\r" in value:
        return False
    s = value.strip()
    if len(s) < 4:
        return False
    if _SCHEME_URL_RE.match(s) or _WIN_DRIVE_RE.match(s):
        return True
    if "\\" in s and not s.startswith("\\u"):
        return True
    if _POSIX_MULTI_SLASH_RE.match(s) or _REL_EXT_PATH_RE.match(s):
        return True
    return False


def _add_if_free(
    s: int,
    e: int,
    kind: str,
    protected: bytearray,
    occupied: bytearray,
    spans: list[tuple[int, int, str]],
) -> None:
    if s < e and not any(protected[s:e]) and not any(occupied[s:e]):
        occupied[s:e] = b"\x01" * (e - s)
        spans.append((s, e, kind))


def _merge_adjacent_name_spans(text: str, spans: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """Coalesce contiguous PERSON name spans joined only by separators into one placeholder. O(len(spans))."""
    if len(spans) <= 1:
        return spans
    merged: list[tuple[int, int, str]] = [spans[0]]
    for s, e, kind in spans[1:]:
        prev_s, prev_e, prev_kind = merged[-1]
        if (
            prev_kind in ("PATIENT_NAME", "RELATIVE")
            and kind in ("PATIENT_NAME", "RELATIVE")
            and _ADJ_SEP_RE.match(text[prev_e:s]) is not None
        ):
            combined_kind = "PATIENT_NAME" if "PATIENT_NAME" in (prev_kind, kind) else "RELATIVE"
            merged[-1] = (prev_s, e, combined_kind)
        else:
            merged.append((s, e, kind))
    return merged


def _collect_evidence_name_spans(
    work: str,
    evidence: ChannelEvidence,
    protected: bytearray,
    occupied: bytearray,
    spans: list[tuple[int, int, str]],
    *,
    allow_single_tokens: bool = True,
) -> list[str]:
    """Scan word tokens against Pass 1 phrases/tokens into spans and return normalised tokens.

    Complexity: O(len(work)).
    """
    raw_toks: list[tuple[int, int, str]] = [
        (m.start(), m.end(), unicodedata.normalize("NFKC", m.group(0)).casefold())
        for m in _CHANNEL_TOK_RE.finditer(work)
    ]
    idx = 0
    while idx < len(raw_toks):
        ts, te, tnorm = raw_toks[idx]
        if any(protected[ts:te]) or any(occupied[ts:te]):
            idx += 1
            continue

        matched_phrase = False
        for plen in (3, 2):
            if idx + plen <= len(raw_toks):
                ptup = tuple(raw_toks[idx + j][2] for j in range(plen))
                if ptup in evidence.name_phrases:
                    ps = raw_toks[idx][0]
                    pe = raw_toks[idx + plen - 1][1]
                    if not any(protected[ps:pe]) and not any(occupied[ps:pe]):
                        pkind = evidence.name_phrase_kind.get(ptup, evidence.DEFAULT_KIND)
                        _add_if_free(ps, pe, pkind, protected, occupied, spans)
                        idx += plen
                        matched_phrase = True
                        break
        if matched_phrase:
            continue

        if (
            allow_single_tokens
            and len(tnorm) >= MIN_CHANNEL_NAME_TOKEN_LEN
            and not any(ch.isdigit() for ch in tnorm)
            and tnorm not in _CHANNEL_BLOCKED_WORDS
            and tnorm in evidence.name_tokens
        ):
            kind = evidence.name_token_kind.get(tnorm, evidence.DEFAULT_KIND)
            _add_if_free(ts, te, kind, protected, occupied, spans)
        idx += 1
    return [tok[2] for tok in raw_toks]


def _render_redacted_spans(
    text: str,
    work: str,
    spans: list[tuple[int, int, str]],
    ph_map: dict[str, str],
    orig_starts: list[int] | None,
    orig_ends: list[int] | None,
) -> tuple[str, int]:
    """Merge adjacent name spans, map NFC offsets back, and splice placeholders. O(len(text))."""
    spans.sort(key=lambda item: item[0])
    spans = _merge_adjacent_name_spans(work, spans)

    if orig_starts is not None and orig_ends is not None:
        mapped = [(orig_starts[s], orig_ends[e - 1], kind) for s, e, kind in spans]
    else:
        mapped = spans

    parts: list[str] = []
    cursor = 0
    for s, e, kind in mapped:
        parts.append(text[cursor:s])
        parts.append(ph_map[kind])
        cursor = e
    parts.append(text[cursor:])
    return "".join(parts), len(mapped)


def clean_channel_text(
    text: str,
    evidence: ChannelEvidence,
    *,
    filename_safe: bool = False,
    key_context: str | None = None,
) -> tuple[str, int]:
    """Clean one hidden-channel token string using R8 doctor protection, R6, R7, and Pass 1 evidence.

    Normalises to NFC only for matching; unmatched characters remain verbatim.
    Complexity: O(len(text)).
    """
    if not text:
        return text, 0

    is_nfc = unicodedata.is_normalized("NFC", text)
    if is_nfc:
        work = text
        orig_starts: list[int] | None = None
        orig_ends: list[int] | None = None
    else:
        work, orig_starts, orig_ends = nfc_with_offset_map(text)

    n = len(work)
    protected = bytearray(n)
    for ds, de in find_doctor_spans(work, allow_underscores=True):
        protected[ds:de] = b"\x01" * (de - ds)

    occupied = bytearray(n)
    spans: list[tuple[int, int, str]] = []

    # Step 1: R6 identifiers & phones (including lowercase MRN shapes and Pass 1 MRN digit cores)
    for s, e, kind in find_identifier_spans(
        work,
        allow_lowercase_mrn=True,
        mrn_cores=evidence.mrn_cores_frozen,
    ):
        _add_if_free(s, e, kind, protected, occupied, spans)

    # Step 2: R7 explicit labels/honorifics/relations (when present in channel text)
    for s, e, kind in find_name_spans(work):
        _add_if_free(s, e, kind, protected, occupied, spans)

    # Step 3: Pass 1 evidence tokens & multi-word phrases across separators and camelCase
    norms = _collect_evidence_name_spans(work, evidence, protected, occupied, spans)

    # Step 4: Parent-dict context fallback (e.g. "by_name": {"Unknown Canary": ...})
    if not spans and key_context is not None and not any(protected):
        if norms and not all(w in _CHANNEL_BLOCKED_WORDS for w in norms):
            spans.append((0, n, key_context))

    if not spans:
        return text, 0

    ph_map = FILENAME_PLACEHOLDERS if filename_safe else PLACEHOLDERS
    return _render_redacted_spans(text, work, spans, ph_map, orig_starts, orig_ends)


def redact_known_names_in_text(
    text: str,
    evidence: ChannelEvidence,
    *,
    allow_single_tokens: bool = True,
) -> tuple[str, int]:
    """Redact Pass 1 patient/relative name phrases & tokens in free/decoded prose while keeping R8
    protected spans (doctors, doses, K/C/O, Ward/Bed, eponyms) and placeholders untouched.

    Complexity: O(len(text)).
    """
    if not text or (not evidence.name_tokens and not evidence.name_phrases):
        return text, 0

    is_nfc = unicodedata.is_normalized("NFC", text)
    if is_nfc:
        work = text
        orig_starts: list[int] | None = None
        orig_ends: list[int] | None = None
    else:
        work, orig_starts, orig_ends = nfc_with_offset_map(text)

    n = len(work)
    protected = build_protect_mask(work)
    occupied = bytearray(n)
    spans: list[tuple[int, int, str]] = []
    _collect_evidence_name_spans(
        work,
        evidence,
        protected,
        occupied,
        spans,
        allow_single_tokens=allow_single_tokens,
    )
    if not spans:
        return text, 0
    return _render_redacted_spans(text, work, spans, PLACEHOLDERS, orig_starts, orig_ends)


def _split_stem_ext(segment: str) -> tuple[str, str]:
    m = _EXT_SUFFIX_RE.match(segment)
    if m is None:
        return segment, ""
    return m.group(1), m.group(2)


def clean_path_or_url(
    value: str,
    evidence: ChannelEvidence,
    *,
    filename_safe: bool = False,
) -> tuple[str, int]:
    """Clean each component of a file path or URL while keeping separators and extensions. O(len(value))."""
    if not value:
        return value, 0

    m_url = _SCHEME_URL_RE.match(value)
    if m_url is not None:
        head, tail = m_url.group("head"), m_url.group("tail")
        pieces = _QUERY_SPLIT_RE.split(tail)
        total = 0
        out_parts: list[str] = [head]
        for idx, piece in enumerate(pieces):
            if idx % 2 == 1 or not piece:
                out_parts.append(piece)
                continue
            stem, ext = _split_stem_ext(piece) if idx == len(pieces) - 1 else (piece, "")
            cleaned_seg, cnt = clean_channel_text(stem, evidence, filename_safe=filename_safe)
            total += cnt
            out_parts.append(cleaned_seg + ext)
        return "".join(out_parts), total

    m_drv = _WIN_DRIVE_RE.match(value)
    prefix = ""
    rest = value
    if m_drv is not None:
        prefix = m_drv.group("drive")
        rest = m_drv.group("rest")

    pieces = _PATH_SPLIT_RE.split(rest)
    total = 0
    out_parts = [prefix]
    last_seg_idx = len(pieces) - 1 if pieces and pieces[-1] else len(pieces) - 2
    for idx, piece in enumerate(pieces):
        if idx % 2 == 1 or not piece:
            out_parts.append(piece)
            continue
        stem, ext = _split_stem_ext(piece) if idx == last_seg_idx else (piece, "")
        cleaned_seg, cnt = clean_channel_text(stem, evidence, filename_safe=filename_safe)
        total += cnt
        out_parts.append(cleaned_seg + ext)
    return "".join(out_parts), total


def _make_safe_segment(seg: str, *, allow_empty: bool = False) -> str:
    safe = _UNSAFE_FILENAME_RE.sub("_", seg).strip()
    if not safe and not allow_empty:
        return "REDACTED"
    return safe


def clean_relative_path(rel_posix: str, evidence: ChannelEvidence) -> str:
    """Clean every folder and filename stem in rel_posix while preserving extension. O(len(rel_posix))."""
    parts = rel_posix.split("/")
    out_parts: list[str] = []
    changed = False

    for folder in parts[:-1]:
        cleaned_folder, cnt = clean_channel_text(folder, evidence, filename_safe=True)
        if cnt > 0:
            changed = True
            out_parts.append(_make_safe_segment(cleaned_folder))
        else:
            out_parts.append(folder)

    filename = parts[-1]
    p = Path(filename)
    ext = p.suffix
    stem = filename[: -len(ext)] if ext else filename
    cleaned_stem, cnt = clean_channel_text(stem, evidence, filename_safe=True)
    if cnt > 0:
        changed = True
        safe_stem = _make_safe_segment(cleaned_stem)
        if safe_stem.casefold() in _RESERVED_WIN_STEMS:
            safe_stem = f"{safe_stem}_file"
        out_parts.append(safe_stem + ext)
    else:
        out_parts.append(filename)

    return "/".join(out_parts) if changed else rel_posix


def build_output_rename_map(rel_paths: list[str], evidence: ChannelEvidence) -> dict[str, str]:
    """Build deterministic collision-free output path map for sorted rel_paths. O(files) amortised."""
    sorted_paths = sorted(rel_paths)
    raw_cleaned = {rel: clean_relative_path(rel, evidence) for rel in sorted_paths}
    reserved = {rel for rel, cand in raw_cleaned.items() if cand == rel}
    used = set(reserved)
    next_suffix: dict[tuple[str, str, str], int] = {}

    mapping: dict[str, str] = {}
    for rel in sorted_paths:
        cand = raw_cleaned[rel]
        if cand == rel:
            mapping[rel] = rel
            continue
        if cand in used:
            p = Path(cand)
            parent = p.parent.as_posix()
            ext = p.suffix
            stem = p.name[: -len(ext)] if ext else p.name
            base_key = (parent, stem, ext)
            n = next_suffix.get(base_key, 2)
            while True:
                numbered = f"{stem}_{n}{ext}"
                next_cand = f"{parent}/{numbered}" if parent and parent != "." else numbered
                if next_cand not in used:
                    cand = next_cand
                    next_suffix[base_key] = n + 1
                    break
                n += 1
        used.add(cand)
        mapping[rel] = cand
    return mapping


def _deduplicate_renamed_labels(
    orig_labels: list[str],
    cleaned_labels: list[str],
) -> list[str]:
    """Resolve collisions on renamed headers/keys in amortised O(len) keeping order and untouched items."""
    reserved = {c for orig, c in zip(orig_labels, cleaned_labels) if orig == c}
    used = set(reserved)
    next_suffix: dict[str, int] = {}
    result: list[str] = []
    for orig, cand in zip(orig_labels, cleaned_labels):
        if orig == cand:
            result.append(orig)
            used.add(orig)
            continue
        final = cand
        if final in used:
            n = next_suffix.get(cand, 2)
            while f"{cand}_{n}" in used:
                n += 1
            final = f"{cand}_{n}"
            next_suffix[cand] = n + 1
        used.add(final)
        result.append(final)
    return result


def clean_csv_header(header: list[str], evidence: ChannelEvidence) -> tuple[list[str], int]:
    """Clean PII from CSV/TSV headers while keeping column count and order. O(sum(len(h)))."""
    cleaned_raw: list[str] = []
    total = 0
    for col in header:
        c, cnt = clean_channel_text(col, evidence, filename_safe=False)
        cleaned_raw.append(c)
        total += cnt
    if total == 0:
        return list(header), 0
    return _deduplicate_renamed_labels(header, cleaned_raw), total


def clean_dict_keys(
    keys: list[str],
    evidence: ChannelEvidence,
    *,
    key_context: str | None = None,
) -> tuple[list[str], int]:
    """Clean PII from sibling JSON dict keys without collisions while keeping order. O(sum(len(k)))."""
    cleaned_raw: list[str] = []
    total = 0
    for k in keys:
        c, cnt = clean_channel_text(k, evidence, filename_safe=False, key_context=key_context)
        cleaned_raw.append(c)
        total += cnt
    if total == 0:
        return list(keys), 0
    return _deduplicate_renamed_labels(keys, cleaned_raw), total


_BINARY_MAGIC_PREFIXES = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"%PDF-",
    b"GIF87a",
    b"GIF89a",
    b"PK\x03\x04",
    b"\x1f\x8b\x08",
)
_PLACEHOLDER_BYTES = codecs.utf_8_encode(BASE64_PLACEHOLDER)[0]


@dataclass(frozen=True)
class Base64Format:
    """Observed base64 wire variant so re-encoding preserves alphabet, padding, and MIME wrap."""

    urlsafe: bool = False
    padded: bool = True
    wrap_width: int = 0
    line_sep: str = ""
    trailing_sep: str = ""


@dataclass(frozen=True)
class DecodedBase64:
    """Successfully decoded base64 payload paired with its original wire format."""

    raw_bytes: bytes
    fmt: Base64Format


def _detect_line_wrap(raw_str: str) -> tuple[int, str, str]:
    """Detect line separator, MIME wrap width, and trailing line ending. O(len(raw_str))."""
    if "\r\n" in raw_str:
        line_sep = "\r\n"
    elif "\n" in raw_str:
        line_sep = "\n"
    else:
        return 0, "", ""

    trailing_sep = line_sep if raw_str.endswith(line_sep) else ""
    body = raw_str[: -len(trailing_sep)] if trailing_sep else raw_str
    lines = body.split(line_sep)
    wrap_width = 0
    if len(lines) >= 2:
        first_len = len(lines[0].strip(" \t"))
        if 1 <= first_len <= BASE64_MAX_WRAP_WIDTH:
            wrap_width = first_len
    return wrap_width, line_sep, trailing_sep


def decode_base64_payload(
    raw_str: str,
    *,
    min_len: int = BASE64_MIN_LEN,
    strict_whitespace: bool = True,
) -> DecodedBase64 | None:
    """Strictly validate and decode base64 text, capturing variant metadata.

    When strict_whitespace is True (plain-JSON heuristic), only CR/LF MIME line breaks
    are stripped so prose with spaces never matches. Never echoes input on error.
    Complexity: O(len(raw_str)).
    """
    if not raw_str:
        return None
    wrap_width, line_sep, trailing_sep = _detect_line_wrap(raw_str)
    if strict_whitespace:
        if " " in raw_str or "\t" in raw_str:
            return None
        compact = raw_str.replace("\r", "").replace("\n", "")
    else:
        compact = B64_WHITESPACE_RE.sub("", raw_str)

    if len(compact) < min_len:
        return None
    shape = match_base64_shape(compact)
    if shape is None:
        return None
    is_urlsafe, had_padding, _ = shape

    rem = len(compact) % 4
    padded_compact = compact if had_padding else (compact + "=" * ((4 - rem) % 4))
    std_b64 = padded_compact.translate(B64_URL_TRANSLATE) if is_urlsafe else padded_compact
    try:
        raw_bytes = base64.b64decode(std_b64, validate=True)
    except (binascii.Error, ValueError):
        return None

    padded_flag = had_padding or (len(compact) % 4 == 0)
    return DecodedBase64(
        raw_bytes=raw_bytes,
        fmt=Base64Format(
            urlsafe=is_urlsafe,
            padded=padded_flag,
            wrap_width=wrap_width,
            line_sep=line_sep,
            trailing_sep=trailing_sep,
        ),
    )


def is_binary_magic(raw_bytes: bytes) -> bool:
    """Return True when raw_bytes starts with a known binary file signature. O(1)."""
    return raw_bytes.startswith(_BINARY_MAGIC_PREFIXES)


def decode_printable_utf8(
    raw_bytes: bytes,
    min_printable_ratio: float = BASE64_MIN_PRINTABLE_RATIO,
) -> str | None:
    """Decode strict UTF-8 bytes and verify printable text share without control chars.

    Complexity: O(len(raw_bytes)).
    """
    try:
        text, _ = codecs.utf_8_decode(raw_bytes, "strict", True)
    except UnicodeError:
        return None
    if not text:
        return ""
    printable = 0
    for ch in text:
        code = ord(ch)
        if (code < 32 and ch not in ("\t", "\n", "\r")) or code == 127:
            return None
        if ch in ("\t", "\n", "\r") or ch.isprintable():
            printable += 1
    if printable / len(text) < min_printable_ratio:
        return None
    return text


def encode_base64_payload(raw_bytes: bytes, fmt: Base64Format | None = None) -> str:
    """Encode raw_bytes to base64 preserving alphabet, padding, and MIME wrap. O(len(raw_bytes))."""
    eff = fmt if fmt is not None else Base64Format()
    b64_bytes = base64.urlsafe_b64encode(raw_bytes) if eff.urlsafe else base64.b64encode(raw_bytes)
    raw_b64, _ = codecs.ascii_decode(b64_bytes, "strict")
    if not eff.padded:
        raw_b64 = raw_b64.rstrip("=")
    if eff.wrap_width > 0 and eff.line_sep:
        wrapped = eff.line_sep.join(
            raw_b64[i : i + eff.wrap_width] for i in range(0, len(raw_b64), eff.wrap_width)
        )
        return wrapped + eff.trailing_sep
    return raw_b64 + eff.trailing_sep


def base64_placeholder_encoded(fmt: Base64Format | None = None) -> str:
    """Return valid base64 encoding of BASE64_PLACEHOLDER using fmt (or standard padded). O(1)."""
    return encode_base64_payload(_PLACEHOLDER_BYTES, fmt)

