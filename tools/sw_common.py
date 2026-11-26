"""Shared helpers for tools/ (measurement only; never imported by main.py or wards/).

Implements the leak-counting rules of Secret-Wards-ToolKit docs/SCORING.md
("How leaks are counted") as far as the published text allows:
normalisation (NFKC, Cyrillic/Greek homoglyph fold, zero-width removal, Indic digits -> ASCII,
Latin diacritics stripped, casefold), hidden-payload decoding (base64, hex, \\uXXXX, HTML
entities, %-encoding) and record location (row:N, JSON pointer, doc, @file/@header/@filename).
"""
from __future__ import annotations

import base64
import binascii
import csv
import html
import io
import json
import re
import unicodedata
import urllib.parse
from pathlib import Path

COUNT_KEYS = ["files_total", "files_sanitized", "files_quarantined", "records_processed",
              "identifiers_detected", "records_linked", "records_generalized", "records_suppressed",
              "records_quarantined"]

# ------------------------------------------------------------------ normalisation
_HOMO = str.maketrans({
    # Cyrillic
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j",
    "ѕ": "s", "ԁ": "d", "һ": "h", "ӏ": "l", "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M",
    "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X", "У": "Y", "І": "I",
    # Greek
    "α": "a", "ο": "o", "ρ": "p", "ν": "v", "ι": "i", "κ": "k", "τ": "t", "υ": "u", "χ": "x",
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N",
    "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
})
_ZW = re.compile("[​‌‍⁠﻿­]")


def _indic_digits(s: str) -> str:
    out = []
    for ch in s:
        if ch.isdigit() and not ("0" <= ch <= "9"):
            try:
                out.append(str(unicodedata.digit(ch)))
                continue
            except ValueError:
                pass
        out.append(ch)
    return "".join(out)


def _strip_latin_diacritics(s: str) -> str:
    d = unicodedata.normalize("NFD", s)
    out = []
    prev_latin = False
    for ch in d:
        if unicodedata.combining(ch) and prev_latin:
            continue
        out.append(ch)
        if not unicodedata.combining(ch):
            prev_latin = ch.isascii() and ch.isalpha()
    return unicodedata.normalize("NFC", "".join(out))


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = _ZW.sub("", s).translate(_HOMO)
    s = _indic_digits(s)
    s = _strip_latin_diacritics(s)
    return s.casefold()


_B64 = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")
_HEX = re.compile(r"\b(?:[0-9a-fA-F]{2}){8,}\b")
_UESC = re.compile(r"(?:\\u[0-9a-fA-F]{4})+")
_PCT = re.compile(r"(?:%[0-9a-fA-F]{2})+")


def decode_hidden(text: str) -> str:
    """Append decoded hidden payloads (base64, hex, \\uXXXX, HTML entities, %-encoding)."""
    extra = []
    for m in _B64.finditer(text):
        t = m.group(0)
        try:
            d = base64.b64decode(t + "=" * (-len(t) % 4), validate=False).decode("utf-8")
            if d.isprintable() or "\n" in d:
                extra.append(d)
        except (binascii.Error, ValueError, UnicodeDecodeError):
            pass
    for m in _HEX.finditer(text):
        try:
            extra.append(bytes.fromhex(m.group(0)).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            pass
    for m in _UESC.finditer(text):
        try:
            extra.append(m.group(0).encode().decode("unicode_escape"))
        except UnicodeDecodeError:
            pass
    if "&" in text:
        u = html.unescape(text)
        if u != text:
            extra.append(u)
    for m in _PCT.finditer(text):
        extra.append(urllib.parse.unquote(m.group(0)))
    return text + ("\n" + "\n".join(extra) if extra else "")


def nz(text: str) -> str:
    """Scorer view of a text: decode hidden payloads, then normalise."""
    return norm(decode_hidden(text))


# ------------------------------------------------------------------ key matching
_WORD = re.compile(r"[\wऀ-ॿ]+")
_DIGRUN = re.compile(r"\d(?:[\s\-./()]{0,2}\d)*")


def digit_runs(ntext: str) -> list[str]:
    return [re.sub(r"\D", "", m.group(0)) for m in _DIGRUN.finditer(ntext)]


def count_key(ntext: str, key: str, match: str, runs: list[str] | None = None,
              words: list[str] | None = None) -> int:
    """Occurrences of one truth key in an already normalised text."""
    if not key:
        return 0
    if match == "digits":
        runs = digit_runs(ntext) if runs is None else runs
        return sum(r.count(key) for r in runs)
    if match == "digits_exact":
        runs = digit_runs(ntext) if runs is None else runs
        return sum(1 for r in runs if r == key)
    if match in ("name", "token"):
        words = _WORD.findall(ntext) if words is None else words
        return sum(1 for w in words if w == key)
    if match == "dob":
        return sum(1 for d in parse_dates(ntext) if d == key)
    return ntext.count(key)


# ------------------------------------------------------------------ dates
_MON = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DATE_TOKEN = re.compile(
    r"\b(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}|"
    r"\d{1,2}[\s\-](?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s\-,]+\d{2,4})\b",
    re.I)


def _mk(y, m, d):
    import datetime
    try:
        y = int(y)
        if y < 100:
            y += 2000 if y < 50 else 1900
        return datetime.date(y, int(m), int(d)).isoformat()
    except ValueError:
        return None


def parse_date(tok: str, hint: str = "dmy") -> str | None:
    t = tok.strip().lower()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", t)
    if m:
        return _mk(*m.groups())
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})", t)
    if m:
        a, b, y = m.groups()
        return _mk(y, a, b) if hint == "mdy" else _mk(y, b, a)
    m = re.fullmatch(r"(\d{1,2})[\s\-]([a-z]{3})[a-z]*[\s\-,]+(\d{2,4})", t)
    if m and m.group(2) in _MON:
        return _mk(m.group(3), _MON[m.group(2)], m.group(1))
    return None


def parse_dates(ntext: str, hint: str = "dmy") -> list[str]:
    out = []
    for m in DATE_TOKEN.finditer(ntext):
        for h in ((hint,) if hint else ()) + (("mdy",) if hint == "dmy" else ("dmy",)):
            d = parse_date(m.group(0), h)
            if d:
                out.append(d)
                break
    return out


# ------------------------------------------------------------------ IO
def decode_bytes(b: bytes, enc: str | None = None) -> str:
    if b.startswith(b"\xef\xbb\xbf"):
        return b[3:].decode("utf-8", "replace")
    if b.startswith((b"\xff\xfe", b"\xfe\xff")):
        return b.decode("utf-16", "replace")
    for e in ([enc] if enc else []) + ["utf-8"]:
        try:
            return b.decode(e.replace("utf-8-bom", "utf-8-sig"))
        except (UnicodeDecodeError, LookupError):
            pass
    return b.decode("cp1252", "replace")


def read_any(p: Path, enc: str | None = None) -> str:
    try:
        return decode_bytes(p.read_bytes()[: 50 * 1024 * 1024], enc)
    except OSError:
        return ""


def load_truth(kit: Path) -> dict:
    return json.loads((kit / "dev" / "truth" / "truth.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ record location
def json_pointer(doc, ptr: str):
    cur = doc
    for part in ptr.split("/")[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, list):
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            cur = cur[part]
        else:
            raise KeyError(ptr)
    return cur


def flatten(obj, prefix="") -> list[tuple[str, object]]:
    """(key path, leaf) pairs; keys are kept so key-channel PII is visible."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.append((f"{prefix}/{k}", "\x00KEY"))
            out += flatten(v, f"{prefix}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += flatten(v, f"{prefix}/{i}")
    else:
        out.append((prefix, obj))
    return out


def obj_text(obj) -> str:
    parts = []
    for path, v in flatten(obj):
        if v == "\x00KEY":
            parts.append(path.rsplit("/", 1)[-1])
        elif v is not None:
            parts.append(str(v))
    return "\n".join(parts)


class ParsedFile:
    """One file parsed for record lookup: CSV rows, JSON tree or plain text."""

    def __init__(self, path: Path, fmt: str, delimiter: str | None, enc: str | None):
        self.path, self.fmt = path, fmt
        self.exists = path.is_file()
        self.raw = read_any(path, enc) if self.exists else ""
        self.rows = self.header = self.tree = None
        self.ok = False
        if not self.exists:
            return
        try:
            if fmt in ("csv", "tsv"):
                delim = delimiter or ("\t" if fmt == "tsv" else ",")
                rows = list(csv.reader(io.StringIO(self.raw, newline=""), delimiter=delim))
                self.header, self.rows = (rows[0] if rows else []), rows[1:]
                self.ok = True
            elif fmt in ("json", "fhir"):
                self.tree = json.loads(self.raw)
                self.ok = True
            else:
                self.ok = fmt == "text"
        except (ValueError, csv.Error, RecursionError):
            self.ok = False

    def record(self, loc: str):
        """Return (text, fields dict or None, located bool)."""
        if not self.exists:
            return "", None, False
        if loc in ("doc", "@file"):
            fields = ({pp: v for pp, v in flatten(self.tree) if v != "\x00KEY"}
                      if self.tree is not None else None)
            return (obj_text(self.tree) if self.tree is not None else self.raw), fields, True
        if loc == "@header":
            return (self.raw.splitlines() or [""])[0], None, True
        if loc.startswith("row:") and self.rows is not None:
            i = int(loc[4:])
            if 0 <= i < len(self.rows):
                row = self.rows[i]
                fields = {h: (row[j] if j < len(row) else "") for j, h in enumerate(self.header)}
                fields.update({f"#{j}": c for j, c in enumerate(row)})
                return "\n".join(row), fields, True
            return self.raw, None, False
        if loc.startswith("/") and self.tree is not None:
            try:
                sub = json_pointer(self.tree, loc)
                fields = {p: v for p, v in flatten(sub) if v != "\x00KEY"}
                return obj_text(sub), fields, True
            except (KeyError, IndexError, ValueError, TypeError):
                return self.raw, None, False
        return self.raw, None, False


def field_value(fields: dict | None, path: str | None, in_header: list | None = None,
                out_header: list | None = None):
    """Value of a truth `path` (col:<name> or JSON sub-pointer) inside a located record."""
    if not fields or not path:
        return None
    if path.startswith("col:"):
        name = path[4:]
        if name in fields:
            return fields[name]
        if in_header and name in in_header:      # header renamed in the output: use the index
            return fields.get(f"#{in_header.index(name)}")
        return None
    if path in fields:
        return fields[path]
    for k, v in fields.items():                  # relative pointer match
        if k.endswith(path):
            return v
    return None


# ------------------------------------------------------------------ side-channel scan
class SideChannelScanner:
    """Direct identifiers, full patient names and canaries from truth.json; reports file:line only."""

    def __init__(self, truth: dict, min_digits: int = 6):
        self.digit_keys, self.text_keys, self.full_names, self.canary = set(), set(), set(), set()
        for f in truth["files"].values():
            for u in f["units"].values():
                for e in u["entities"]:
                    is_can = e.get("canary") or e["type"] == "CANARY"
                    if e.get("match") == "name":
                        toks = tuple(norm(t) for t in e.get("tokens") or [] if t)
                        if (e.get("full") or is_can) and len(toks) >= 2:
                            (self.canary if is_can else self.full_names).add(toks)
                        elif is_can and toks:
                            self.canary.add(toks)
                        continue
                    if not (e.get("critical") or is_can):
                        continue
                    k = norm(str(e.get("key") or e["surface"]))
                    if e["match"] in ("digits", "digits_exact"):
                        if len(k) >= min_digits:
                            self.digit_keys.add(k)
                            if is_can:
                                self.canary.add((("#", k),))
                    elif len(k) >= 4:
                        self.text_keys.add(k)
                        if is_can:
                            self.canary.add((("$", k),))

    def scan_text(self, text: str, label: str) -> list[str]:
        hits = []
        for i, line in enumerate(text.splitlines() or [text], 1):
            n = nz(line)
            runs = digit_runs(n)
            words = set(_WORD.findall(n))
            hit = any(k in r for r in runs for k in self.digit_keys) \
                or any(k in n for k in self.text_keys) \
                or any(all(t in words for t in toks) for toks in self.full_names)
            if hit:
                hits.append(f"{label}:{i}")
        return hits

    def canaries_in(self, text: str) -> int:
        n = nz(text)
        runs, words = digit_runs(n), set(_WORD.findall(n))
        found = 0
        for c in self.canary:
            if c and isinstance(c[0], tuple):
                kind, k = c[0]
                found += (any(k in r for r in runs) if kind == "#" else k in n)
            else:
                found += all(t in words for t in c)
        return found
