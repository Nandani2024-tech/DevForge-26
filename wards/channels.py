"""R9 hidden-channel cleaning: filenames/folders, CSV headers, JSON keys, and path/URL metadata."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wards.config import (
    CHANNEL_SAFE_WORDS,
    FILENAME_PLACEHOLDERS,
    MIN_CHANNEL_MRN_DIGITS,
    MIN_CHANNEL_NAME_TOKEN_LEN,
    NAME_LABEL_STOP_WORDS,
    NON_NAME_WORDS,
    PLACEHOLDERS,
)
from wards.names import find_doctor_spans, find_name_spans, nfc_with_offset_map
from wards.patterns import find_identifier_spans, normalise_digits

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

        # Try 3-token and 2-token phrases first (handles short initials like R_K_Bhatia)
        matched_phrase = False
        for plen in (3, 2):
            if idx + plen <= len(raw_toks):
                ptup = tuple(raw_toks[idx + j][2] for j in range(plen))
                if ptup in evidence.name_phrases:
                    ps = raw_toks[idx][0]
                    pe = raw_toks[idx + plen - 1][1]
                    if not any(protected[ps:pe]) and not any(occupied[ps:pe]):
                        pkind = evidence.name_phrase_kind.get(ptup, "PATIENT_NAME")
                        _add_if_free(ps, pe, pkind, protected, occupied, spans)
                        idx += plen
                        matched_phrase = True
                        break
        if matched_phrase:
            continue

        if (
            len(tnorm) >= MIN_CHANNEL_NAME_TOKEN_LEN
            and not any(ch.isdigit() for ch in tnorm)
            and tnorm not in _CHANNEL_BLOCKED_WORDS
            and tnorm in evidence.name_tokens
        ):
            kind = evidence.name_token_kind.get(tnorm, "PATIENT_NAME")
            _add_if_free(ts, te, kind, protected, occupied, spans)
        idx += 1

    # Step 4: Parent-dict context fallback (e.g. "by_name": {"Unknown Canary": ...})
    if not spans and key_context is not None and not any(protected):
        norms = [tok[2] for tok in raw_toks]
        if norms and not all(w in _CHANNEL_BLOCKED_WORDS for w in norms):
            spans.append((0, n, key_context))

    if not spans:
        return text, 0

    spans.sort(key=lambda item: item[0])
    spans = _merge_adjacent_name_spans(work, spans)

    if orig_starts is not None and orig_ends is not None:
        mapped = [(orig_starts[s], orig_ends[e - 1], kind) for s, e, kind in spans]
    else:
        mapped = spans

    ph_map = FILENAME_PLACEHOLDERS if filename_safe else PLACEHOLDERS
    parts: list[str] = []
    cursor = 0
    for s, e, kind in mapped:
        parts.append(text[cursor:s])
        parts.append(ph_map[kind])
        cursor = e
    parts.append(text[cursor:])
    return "".join(parts), len(mapped)


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
