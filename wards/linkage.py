"""R10 cross-record identity clustering with conflict guard + R11 canonical cluster key."""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass

from wards.config import (
    AADHAAR_DIGITS,
    ABHA_DIGITS,
    LINK_CONTACT_ID_TYPES,
    LINK_LIFELONG_ID_TYPES,
    LINK_MIN_ID_DIGITS,
    PREFIX_HONORIFICS,
    SUFFIX_HONORIFICS,
)
from wards.patterns import extract_phone_core, is_email, is_pan, normalise_digits

# Compact Devanagari-to-Latin phonetic table (each value <= 2 ASCII chars; schwa deletion applied in loop)
_DEVA_INDEP_VOWELS: dict[str, str] = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo",
    "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऑ": "o",
}
_DEVA_CONSONANTS: dict[str, str] = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n",
    "च": "ch", "छ": "ch", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v",
    "श": "sh", "ष": "sh", "स": "s", "ह": "h",
    "क़": "k", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "d", "ढ़": "dh", "फ़": "f",
}
_DEVA_MATRAS: dict[str, str] = {
    "ा": "a", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo",
    "ृ": "ri", "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ॉ": "o",
}
_DEVA_VIRAMA = "्"
_DEVA_NASALS = frozenset({"ं", "ँ", "ः"})
_DEVA_HAS_RE = re.compile(r"[\u0900-\u097f]")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_HONORIFIC_WORDS = frozenset(
    w.strip(".").casefold() for w in (*PREFIX_HONORIFICS, *SUFFIX_HONORIFICS) if w.strip(".")
)
_NON_DIGIT_RE = re.compile(r"\D")


@dataclass(frozen=True)
class RecordEvidence:
    """Minimal Pass 1 identity tuple for one record (never retains raw file contents)."""

    record_id: int
    input_rel: str
    loc: str
    strong_ids: tuple[tuple[str, str], ...]
    name_key: str | None = None
    dob_iso: str | None = None
    rel_key: str | None = None


@dataclass(frozen=True)
class LinkageResult:
    """Canonical cluster keys per record_id (None when unlinked/weak-only)."""

    canonical_keys: dict[int, str | None]


def _transliterate_deva_word(word: str) -> str:
    """Transliterate one NFC Devanagari word to Latin with simple schwa deletion. O(len(word))."""
    out: list[str] = []
    n = len(word)
    i = 0
    while i < n:
        ch = word[i]
        # Combine base consonant + nukta when present as 2 code points
        if i + 1 < n and word[i + 1] == "़" and (ch + "़") in _DEVA_CONSONANTS:
            ch = ch + "़"
            step = 2
        else:
            step = 1

        if ch in _DEVA_CONSONANTS:
            out.append(_DEVA_CONSONANTS[ch])
            nxt_idx = i + step
            nxt = word[nxt_idx] if nxt_idx < n else ""
            if nxt == _DEVA_VIRAMA:
                i = nxt_idx + 1
                continue
            if nxt in _DEVA_MATRAS:
                out.append(_DEVA_MATRAS[nxt])
                i = nxt_idx + 1
                continue
            if nxt in _DEVA_NASALS:
                out.append("a")
                out.append("n" if nxt != "ः" else "h")
                i = nxt_idx + 1
                continue
            # Inherent schwa: keep medial/initial unless end of word or followed by consonant+vowel end
            if nxt_idx < n:
                out.append("a")
            i = nxt_idx
        elif ch in _DEVA_INDEP_VOWELS:
            out.append(_DEVA_INDEP_VOWELS[ch])
            i += step
        elif ch in _DEVA_MATRAS:
            out.append(_DEVA_MATRAS[ch])
            i += step
        elif ch in _DEVA_NASALS:
            out.append("n" if ch != "ः" else "h")
            i += step
        else:
            if ch.isascii() and ch.isalnum():
                out.append(ch.lower())
            i += step
    return "".join(out)


def normalise_name_key(raw: str) -> str | None:
    """Normalise a person name across NFC/case/honorifics/word-order (+ Deva->Latin). O(len(raw))."""
    if not raw or not raw.strip():
        return None
    nfc = unicodedata.normalize("NFC", raw).casefold()
    # Remove punctuation and split tokens
    tokens = [t for t in re.split(r"[\s,.;:()\"'/\\_-]+", nfc) if t]
    cleaned_tokens: list[str] = []
    for tok in tokens:
        if tok in _HONORIFIC_WORDS or any(ch.isdigit() for ch in tok):
            continue
        if _DEVA_HAS_RE.search(tok):
            lat = _transliterate_deva_word(tok)
            if lat:
                cleaned_tokens.append(lat)
        else:
            alpha = _NON_ALNUM_RE.sub("", tok)
            if alpha:
                cleaned_tokens.append(alpha)
    if not cleaned_tokens:
        return None
    cleaned_tokens.sort()
    return " ".join(cleaned_tokens)


def normalise_strong_id(id_type: str, raw_value: str) -> tuple[str, str] | None:
    """Normalise a structured/free-text strong ID into (type, canonical_value). O(len(raw_value))."""
    if not raw_value or not raw_value.strip():
        return None
    t = id_type.casefold().strip()
    ascii_val = unicodedata.normalize("NFKC", normalise_digits(raw_value)).strip()
    if ascii_val.startswith("[") and ascii_val.endswith("]"):
        return None

    if t == "phone":
        core = extract_phone_core(ascii_val)
        return ("phone", core) if core is not None else None

    if t == "aadhaar":
        digits = _NON_DIGIT_RE.sub("", ascii_val)
        return ("aadhaar", digits) if len(digits) == AADHAAR_DIGITS else None

    if t == "abha":
        digits = _NON_DIGIT_RE.sub("", ascii_val)
        return ("abha", digits) if len(digits) == ABHA_DIGITS else None

    if t == "abha_address":
        low = ascii_val.casefold()
        return ("abha_address", low) if "@" in low else None

    if t == "pan":
        up = ascii_val.upper()
        return ("pan", up) if is_pan(up) else None

    if is_email(ascii_val):
        return (t, ascii_val.casefold())

    # Per-issuer IDs (MRN/UHID/IPD, insurance): the digit core, so separator and prefix
    # spellings of one ID match (02-domain R6/R11).
    core = _NON_DIGIT_RE.sub("", ascii_val)
    if len(core) < LINK_MIN_ID_DIGITS:
        return None
    return (t, core)


class _UnionFind:
    """Disjoint-set with path compression and union by rank. O(alpha(N)) per op."""

    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            nxt = self.parent[x]
            self.parent[x] = root
            x = nxt
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


def _cluster_indices(
    indices: list[int],
    by_id: dict[int, RecordEvidence],
    *,
    use_weak: bool,
    exclude_types: frozenset[str] = frozenset(),
) -> list[list[int]]:
    """Cluster a subset of records via dict index + union-find. O(R * alpha(R))."""
    pos_map = {rid: idx for idx, rid in enumerate(indices)}
    uf = _UnionFind(len(indices))

    strong_idx: dict[tuple[str, str], int] = {}
    name_dob_idx: dict[tuple[str, str], int] = {}
    name_rel_idx: dict[tuple[str, str], int] = {}

    for rid in indices:
        rec = by_id[rid]
        p_idx = pos_map[rid]
        for id_pair in rec.strong_ids:
            if id_pair[0] in exclude_types:
                continue
            prev = strong_idx.get(id_pair)
            if prev is None:
                strong_idx[id_pair] = p_idx
            else:
                uf.union(prev, p_idx)
        if use_weak and rec.name_key:
            if rec.dob_iso:
                k_dob = (rec.name_key, rec.dob_iso)
                prev_d = name_dob_idx.get(k_dob)
                if prev_d is None:
                    name_dob_idx[k_dob] = p_idx
                else:
                    uf.union(prev_d, p_idx)
            if rec.rel_key:
                k_rel = (rec.name_key, rec.rel_key)
                prev_r = name_rel_idx.get(k_rel)
                if prev_r is None:
                    name_rel_idx[k_rel] = p_idx
                else:
                    uf.union(prev_r, p_idx)

    groups: dict[int, list[int]] = defaultdict(list)
    for rid in indices:
        groups[uf.find(pos_map[rid])].append(rid)
    return [groups[root] for root in sorted(groups)]


def _has_conflict(members: list[int], by_id: dict[int, RecordEvidence]) -> bool:
    """True if a component holds two DOBs or two values of one lifelong ID type. O(len(members))."""
    dobs = {by_id[rid].dob_iso for rid in members if by_id[rid].dob_iso}
    if len(dobs) > 1:
        return True
    vals_by_type: dict[str, set[str]] = defaultdict(set)
    for rid in members:
        for id_type, id_val in by_id[rid].strong_ids:
            if id_type in LINK_LIFELONG_ID_TYPES:
                vals_by_type[id_type].add(id_val)
    return any(len(vals) > 1 for vals in vals_by_type.values())


def _canonical_key_for_group(
    members: list[int],
    by_id: dict[int, RecordEvidence],
    *,
    exclude_types: frozenset[str],
    use_weak: bool,
) -> str | None:
    """Canonical cluster key for a conflict-free component (Design Decision (a)). O(len(members)).

    Only edge types used to build the component count, so two components of one stage can
    never share a key (a shared value would have joined them).
    """
    strong_strs = sorted(
        f"{id_type}:{id_val}"
        for rid in members
        for id_type, id_val in by_id[rid].strong_ids
        if id_type not in exclude_types
    )
    if strong_strs:
        return strong_strs[0]

    if use_weak and len(members) >= 2:
        # Weak link only when at least 2 records share (name + corroborator)
        for rid in sorted(members):
            rec = by_id[rid]
            corr = rec.dob_iso or rec.rel_key
            if rec.name_key and corr:
                return f"nm:{rec.name_key}|{corr}"
    return None


# Conflict guard stages: each later stage drops one more edge kind (weak name edges, then
# contact handles, then per-issuer IDs), leaving lifelong-ID edges only.
_GUARD_STAGES: tuple[tuple[bool, frozenset[str] | None], ...] = (
    (True, frozenset()),
    (False, frozenset()),
    (False, LINK_CONTACT_ID_TYPES),
    (False, None),  # None = keep lifelong ID edges only
)


def _stage_excludes(ids: list[int], by_id: dict[int, RecordEvidence], spec: frozenset[str] | None) -> frozenset[str]:
    if spec is not None:
        return spec
    return frozenset(
        t for rid in ids for t, _ in by_id[rid].strong_ids if t not in LINK_LIFELONG_ID_TYPES
    )


def link_records(records: list[RecordEvidence]) -> LinkageResult:
    """Cluster records on strong-ID and name+corroborator edges, with a conflict guard.

    A component with a conflict (two DOBs, or two values of one lifelong ID type) is
    re-clustered with fewer edge kinds (see _GUARD_STAGES); conflict-free parts are kept,
    the rest go to the next stage. A part that still conflicts on lifelong IDs alone gets
    patient null. Weak-only singletons get null via _canonical_key_for_group.
    Complexity: O(S * R * alpha(R)) for S = len(_GUARD_STAGES) stages (constant).
    """
    sorted_recs = sorted(records, key=lambda r: r.record_id)
    by_id = {r.record_id: r for r in sorted_recs}
    canonical_keys: dict[int, str | None] = {}

    pending = [[r.record_id for r in sorted_recs]] if sorted_recs else []
    for use_weak, spec in _GUARD_STAGES:
        next_pending: list[list[int]] = []
        for ids in pending:
            excludes = _stage_excludes(ids, by_id, spec)
            for comp in _cluster_indices(ids, by_id, use_weak=use_weak, exclude_types=excludes):
                if _has_conflict(comp, by_id):
                    next_pending.append(comp)
                    continue
                ck = _canonical_key_for_group(comp, by_id, exclude_types=excludes, use_weak=use_weak)
                for rid in comp:
                    canonical_keys[rid] = ck
        pending = next_pending
    for ids in pending:
        for rid in ids:
            canonical_keys[rid] = None
    return LinkageResult(canonical_keys=canonical_keys)
