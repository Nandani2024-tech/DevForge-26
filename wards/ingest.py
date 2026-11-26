"""Multi-encoding input decoding, content-based JSON detection, and safe parsing."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wards.config import SUPPORTED_EXTENSIONS


class QuarantineError(Exception):
    """Raised when an input file cannot be safely parsed and must be quarantined."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class ParsedInput:
    """In-memory representation of a validated input file."""

    kind: str  # "csv" | "json" | "fhir" | "text"
    rel_posix: str
    input_sha256: str
    delimiter: str = ","
    rows: list[list[str]] | None = None
    data: Any = None
    text: str | None = None


def json_pointer_escape(token: str) -> str:
    """Encode one RFC 6901 JSON Pointer reference token (~ then /)."""
    return token.replace("~", "~0").replace("/", "~1")


def json_pointer_unescape(token: str) -> str:
    """Decode one RFC 6901 JSON Pointer reference token (~1 then ~0)."""
    return token.replace("~1", "/").replace("~0", "~")


def decode_bytes(raw: bytes) -> str | None:
    """Decode bytes using BOM -> strict UTF-8 -> strict cp1252. Returns None on failure.

    Complexity: O(len(raw)).
    """
    try:
        if raw.startswith(b"\xef\xbb\xbf"):
            return raw[3:].decode("utf-8", errors="strict")
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            return raw.decode("utf-16", errors="strict")
        for enc in ("utf-8", "cp1252"):
            try:
                return raw.decode(enc, errors="strict")
            except UnicodeDecodeError:
                continue
    except UnicodeError:
        return None
    return None


def is_json_content(text: str) -> bool:
    """Detect JSON by its first non-whitespace character."""
    stripped = text.lstrip()
    return stripped.startswith("{") or stripped.startswith("[")


def read_and_parse(path: Path, rel_posix: str) -> tuple[str, ParsedInput | None, str | None]:
    """Read a file read-only, compute SHA-256, and parse or return a quarantine reason.

    Returns (input_sha256, parsed_or_none, quarantine_reason_or_none).
    Complexity: O(bytes) in file size.
    """
    raw = path.read_bytes()
    input_sha256 = hashlib.sha256(raw).hexdigest()
    ext = path.suffix.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        return input_sha256, None, "unsupported_format"
    if not raw.strip():
        return input_sha256, None, "empty_file"

    text = decode_bytes(raw)
    if text is None:
        return input_sha256, None, "undecodable_text"

    if ext == ".json" or (ext in (".csv", ".tsv") and is_json_content(text)):
        try:
            data = json.loads(text)
        except RecursionError:
            return input_sha256, None, "deep_json"
        except (json.JSONDecodeError, ValueError):
            return input_sha256, None, "invalid_json"
        kind = "fhir" if isinstance(data, dict) and data.get("resourceType") == "Bundle" else "json"
        return input_sha256, ParsedInput(kind=kind, rel_posix=rel_posix, input_sha256=input_sha256, data=data), None

    if ext in (".csv", ".tsv"):
        delimiter = "\t" if ext == ".tsv" else ","
        try:
            rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
        except csv.Error:
            return input_sha256, None, "invalid_csv"
        if not rows:
            return input_sha256, None, "empty_file"
        return (
            input_sha256,
            ParsedInput(
                kind="csv",
                rel_posix=rel_posix,
                input_sha256=input_sha256,
                delimiter=delimiter,
                rows=rows,
            ),
            None,
        )

    normalised_text = text.replace("\r\n", "\n").replace("\r", "\n")
    return (
        input_sha256,
        ParsedInput(kind="text", rel_posix=rel_posix, input_sha256=input_sha256, text=normalised_text),
        None,
    )
