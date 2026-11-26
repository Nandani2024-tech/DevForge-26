"""R11-R13 acceptance on the kit dev input (01-ps sec 2), measured against dev truth.

truth.json is read only to measure: it supplies each unit's true dates and ages, and the
assertions are the spec targets (100% claims in record, 100% exact intervals, shifts inside
policy bounds, 0 bands excluding the true age). No expected value is copied from it into code.
The kit must be present: kit_dir fails the test when it is missing, it never skips.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

from wards.config import load_policy
from wards.dates import parse_dob_iso
from wards.ingest import decode_bytes, json_pointer_unescape
from wards.pipeline import run_pipeline

_BAND_RE = re.compile(r"(?P<lo>\d+)\s*-\s*(?P<hi>\d+)|(?P<top>\d+)\+")


def _pointer(node: Any, pointer: str) -> Any:
    for raw in pointer.split("/")[1:]:
        part = json_pointer_unescape(raw)
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


@pytest.fixture(scope="module")
def dev_run(tmp_path_factory: pytest.TempPathFactory, kit_dir: Path) -> dict[str, Any]:
    dev = kit_dir / "dev"
    truth_path = dev / "truth" / "truth.json"
    assert truth_path.is_file(), f"Missing dev truth fixture: {truth_path}"
    out = tmp_path_factory.mktemp("acc_out")
    res = run_pipeline(dev / "input", out, b"practice", load_policy())
    return {
        "dev": dev,
        "out": out,
        "records": res.records,
        "report": json.loads((out / "report.json").read_text(encoding="utf-8")),
        "truth": json.loads(truth_path.read_text(encoding="utf-8")),
    }


def _output_of(run: dict[str, Any]) -> dict[str, str]:
    return {f["input_sha256"]: f["output"] for f in run["report"]["files"] if f.get("output")}


def _unit_reader(run: dict[str, Any], in_rel: str, fe: dict[str, Any], out_rel: str):
    """Return (value_at(loc, path), output_text) for one truth file."""
    text = (run["out"] / out_rel).read_text(encoding="utf-8")
    if fe["format"] in ("csv", "tsv"):
        delim = fe.get("delimiter") or ","
        raw = decode_bytes((run["dev"] / "input" / in_rel).read_bytes())
        raw_text = raw[0] if isinstance(raw, tuple) else raw
        header = next(csv.reader(io.StringIO(raw_text, newline=""), delimiter=delim))
        rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delim))

        def value_at(loc: str, path: str) -> str:
            return rows[int(loc.split(":", 1)[1]) + 1][header.index(path.split(":", 1)[1])]

        return value_at, text
    data = json.loads(text) if fe["format"] in ("json", "fhir") else None

    def value_at(loc: str, path: str) -> str:
        return str(_pointer(data, ("" if loc == "doc" else loc) + path))

    return value_at, text


def test_r11_every_claim_is_inside_its_record(dev_run: dict[str, Any]) -> None:
    claims = [r for r in dev_run["records"] if r["patient"]]
    assert claims, "no linked records to check"
    missing = 0
    for r in claims:
        text = (dev_run["out"] / r["file"]).read_text(encoding="utf-8")
        loc = r.get("out", r["loc"])
        if loc.startswith("row:"):
            delim = "\t" if r["file"].endswith(".tsv") else ","
            rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delim))
            segment = "|".join(rows[int(loc.split(":", 1)[1]) + 1])
        elif loc.startswith("/"):
            segment = json.dumps(_pointer(json.loads(text), loc), ensure_ascii=False)
        else:
            segment = text
        missing += r["patient"] not in segment
    assert missing == 0, f"{missing} of {len(claims)} claims not found in their record"


def test_r12_intervals_exact_and_shifts_within_policy(dev_run: dict[str, Any]) -> None:
    policy = load_policy()
    out_of = _output_of(dev_run)
    offsets_by_unit: dict[tuple[str, str], list[int]] = defaultdict(list)
    for in_rel, fe in sorted(dev_run["truth"]["files"].items()):
        out_rel = out_of.get(fe["sha256"])
        if out_rel is None:
            continue
        value_at, text = _unit_reader(dev_run, in_rel, fe, out_rel)
        for loc, unit in fe["units"].items():
            for d in unit.get("dates") or []:
                if "path" in d:
                    shown = value_at(loc, d["path"])
                else:
                    m = re.search(re.escape(d["anchor"]) + r"\s*([^\n]+)", text)
                    shown = m.group(1) if m else ""
                iso = parse_dob_iso(shown, order=d["hint"])
                if iso is not None:
                    offset = (dt.date.fromisoformat(iso) - dt.date.fromisoformat(d["true"])).days
                    offsets_by_unit[(in_rel, loc)].append(offset)
    all_offsets = [o for offs in offsets_by_unit.values() for o in offs]
    assert all_offsets, "no shifted dates found"
    multi = [offs for offs in offsets_by_unit.values() if len(offs) > 1]
    broken = sum(len(set(offs)) > 1 for offs in multi)
    assert broken == 0, f"{broken} of {len(multi)} multi-date records lost an interval"
    out_of_bounds = sum(
        not policy.date_shift_min_abs_days <= abs(o) <= policy.date_shift_max_days for o in all_offsets
    )
    assert out_of_bounds == 0, f"{out_of_bounds} of {len(all_offsets)} shifts outside policy bounds"


def test_r13_no_age_band_excludes_the_true_age(dev_run: dict[str, Any]) -> None:
    out_of = _output_of(dev_run)
    checked = wrong = 0
    for in_rel, fe in sorted(dev_run["truth"]["files"].items()):
        out_rel = out_of.get(fe["sha256"])
        if out_rel is None or fe["format"] == "text":
            continue
        value_at, _ = _unit_reader(dev_run, in_rel, fe, out_rel)
        for loc, unit in fe["units"].items():
            for f in unit.get("fields") or []:
                if f["kind"] != "age" or not f.get("path"):
                    continue  # text fields are located by anchor, not by path
                m = _BAND_RE.search(value_at(loc, f["path"]))
                if m is None:
                    continue  # placeholder or exact value: no band claims a range
                checked += 1
                if m.group("top"):
                    wrong += f["true"] < int(m.group("top"))
                else:
                    wrong += not int(m.group("lo")) <= f["true"] <= int(m.group("hi"))
    assert checked > 0, "no age bands found"
    assert wrong == 0, f"{wrong} of {checked} age bands exclude the true age"
