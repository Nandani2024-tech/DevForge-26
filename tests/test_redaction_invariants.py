"""R6/R9 property tests: generated identifiers are redacted in every container, and a base64
decoding path may only add redactions, never remove them.

All values come from a seeded generator (no dev values). Shapes follow public formats:
Aadhaar = 12 digits, first digit 2-9 (UIDAI never issues 0 or 1 as the first digit);
Indian mobile = 10 digits starting 6-9, written bare, with +91 or with a leading 0 (TRAI numbering);
PAN = 5 letters, 4 digits, 1 letter, 4th letter the holder type, P = person (Income Tax Dept).
"""
from __future__ import annotations

import base64
import binascii
import csv
import json
import random
from pathlib import Path

import pytest

from wards.config import load_policy
from wards.pipeline import run_pipeline

_SEED = 20261127
_SECRET = b"redaction-invariant-secret"
_N_AADHAAR = 1000
_N_MOBILE = 1000
_N_PAN = 200
_N_B64_DECODABLE = 20
_B64_SEARCH_CAP = 2_000_000
_DIGITS = "0123456789"
_UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
# Invented neutral prose: no ID label, so detection rests on value shape alone.
_NOTE_TEMPLATE = "Follow-up in OPD after two weeks; {} recorded at the desk."


def _decodes_as_printable_base64(value: str) -> bool:
    """Independent stdlib oracle: strict base64 that decodes to printable UTF-8 text. O(len)."""
    if len(value) % 4 == 1:
        return False
    padded = value + "=" * ((4 - len(value) % 4) % 4)
    try:
        raw = base64.b64decode(padded, validate=True)
        text = raw.decode("utf-8")
    except (binascii.Error, ValueError):
        return False
    return bool(text) and all(ch.isprintable() or ch in "\t\r\n" for ch in text)


def _generate() -> dict[str, list[tuple[str, str]]]:
    """(written value, core that must not survive) per kind, deterministic. O(n)."""
    rng = random.Random(_SEED)

    def aadhaar() -> str:
        return rng.choice("23456789") + "".join(rng.choice(_DIGITS) for _ in range(11))

    aadhaar_vals = [aadhaar() for _ in range(_N_AADHAAR)]
    decodable = [v for v in aadhaar_vals if _decodes_as_printable_base64(v)]
    tries = 0
    while len(decodable) < _N_B64_DECODABLE:
        tries += 1
        assert tries < _B64_SEARCH_CAP, "generator found too few base64-decodable Aadhaar shapes"
        v = aadhaar()
        if _decodes_as_printable_base64(v):
            decodable.append(v)
            aadhaar_vals.append(v)

    mobiles: list[tuple[str, str]] = []
    for i in range(_N_MOBILE):
        core = rng.choice("6789") + "".join(rng.choice(_DIGITS) for _ in range(9))
        written = (core, "+91" + core, "0" + core)[i % 3]
        mobiles.append((written, core))

    pans: list[tuple[str, str]] = []
    for _ in range(_N_PAN):
        pan = (
            "".join(rng.choice(_UPPER) for _ in range(3))
            + "P"
            + rng.choice(_UPPER)
            + "".join(rng.choice(_DIGITS) for _ in range(4))
            + rng.choice(_UPPER)
        )
        pans.append((pan, pan))

    return {
        "aadhaar": [(v, v) for v in aadhaar_vals],
        "mobile": mobiles,
        "pan": pans,
        "aadhaar_b64": [(v, v) for v in decodable],
    }


@pytest.fixture(scope="module")
def generated() -> dict[str, list[tuple[str, str]]]:
    return _generate()


@pytest.fixture(scope="module")
def sanitized(tmp_path_factory: pytest.TempPathFactory, generated: dict[str, list[tuple[str, str]]]) -> Path:
    inp = tmp_path_factory.mktemp("inv_in")
    out = tmp_path_factory.mktemp("inv_out") / "out"
    for kind in ("aadhaar", "mobile", "pan"):
        values = [w for w, _ in generated[kind]]
        # Free-text JSON field holding the bare value.
        (inp / f"{kind}_fields.json").write_text(
            json.dumps({"entries": [{"comment": v} for v in values]}, ensure_ascii=False), encoding="utf-8"
        )
        # CSV free-text cell (prose around the value so the column stays free text).
        with (inp / f"{kind}_cells.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["row", "comment"])
            for i, v in enumerate(values):
                writer.writerow([i, _NOTE_TEMPLATE.format(v)])
        # Text note, one line per value.
        (inp / f"{kind}_note.txt").write_text(
            "\n".join(_NOTE_TEMPLATE.format(v) for v in values) + "\n", encoding="utf-8", newline="\n"
        )
    run_pipeline(inp, out, _SECRET, load_policy())
    return out / "sanitized"


def _survivors(path: Path, pairs: list[tuple[str, str]]) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return sorted({core for _, core in pairs if core in text})


@pytest.mark.parametrize("kind", ["aadhaar", "mobile", "pan"])
@pytest.mark.parametrize(
    "container", ["fields.json", "cells.csv", "note.txt"], ids=["json_field", "csv_cell", "text_note"]
)
def test_r6_generated_identifiers_are_redacted_in_every_container(
    sanitized: Path, generated: dict[str, list[tuple[str, str]]], kind: str, container: str
) -> None:
    out_file = sanitized / f"{kind}_{container}"
    assert out_file.is_file(), f"{out_file.name} was not written to sanitized/"
    left = _survivors(out_file, generated[kind])
    assert not left, f"{len(left)} of {len(generated[kind])} {kind} values survive in {container}"


@pytest.mark.parametrize(
    "container", ["fields.json", "cells.csv", "note.txt"], ids=["json_field", "csv_cell", "text_note"]
)
def test_r6_r9_base64_decodable_ids_are_redacted_like_plain_ids(
    sanitized: Path, generated: dict[str, list[tuple[str, str]]], container: str
) -> None:
    # Subset of the same Aadhaar inputs that are also valid base64 decoding to printable text
    # (stdlib oracle). Whatever plain cleaning redacts for the non-decodable ones must also be
    # redacted for these: a decoding path may only add redactions, never remove them.
    decodable = generated["aadhaar_b64"]
    assert len(decodable) >= _N_B64_DECODABLE
    decodable_set = {c for _, c in decodable}
    plain = [p for p in generated["aadhaar"] if p[1] not in decodable_set]
    out_file = sanitized / f"aadhaar_{container}"
    plain_left = set(_survivors(out_file, plain))
    plain_redacted_share = 1 - len(plain_left) / len(plain)
    b64_left = _survivors(out_file, decodable)
    b64_redacted_share = 1 - len(b64_left) / len(decodable)
    assert b64_redacted_share >= plain_redacted_share, (
        f"{len(b64_left)} of {len(decodable)} base64-decodable Aadhaar values survive in {container} "
        f"while plain cleaning redacts {plain_redacted_share:.1%} of the others"
    )
    assert not b64_left, f"{len(b64_left)} of {len(decodable)} base64-decodable Aadhaar values survive in {container}"
