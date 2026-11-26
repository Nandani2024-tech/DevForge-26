"""Slot detection on unseen header names (generic meaning tokens + value shape, R22 guard for R3/R15)."""
from __future__ import annotations

import csv
import io
from pathlib import Path

from wards.config import load_policy
from wards.pipeline import run_pipeline


def _run_csv(tmp_path: Path, text: str) -> list[list[str]]:
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    (inp / "t.csv").write_text(text, encoding="utf-8")
    run_pipeline(inp=inp, out=out, secret=b"s", policy=load_policy())
    return list(csv.reader(io.StringIO((out / "sanitized" / "t.csv").read_text(encoding="utf-8"), newline="")))


def test_r22_renamed_patient_id_header_is_pseudonymised(tmp_path: Path) -> None:
    # Header never seen in dev: "Pt. Registration Number" -> tokens pt + registration + number.
    rows = _run_csv(tmp_path, "Pt. Registration Number,Hb\nQRS-77001,12.4\nQRS-77002,11.9\n")
    assert rows[0] == ["Pt. Registration Number", "Hb"]
    assert rows[1][0].startswith("PSN-") and rows[2][0].startswith("PSN-")
    assert rows[1][0] != rows[2][0]
    assert [r[1] for r in rows[1:]] == ["12.4", "11.9"]  # medical values untouched


def test_r22_unknown_header_found_by_value_shape(tmp_path: Path) -> None:
    # Header has no ID meaning; the column is chosen because every value is ID-shaped.
    rows = _run_csv(tmp_path, "Kaartu,Hb\nZZQ/41/00017,13.0\nZZQ/41/00018,12.0\n")
    assert rows[1][0].startswith("PSN-") and rows[2][0].startswith("PSN-")


def test_r22_non_patient_id_column_is_not_used_as_slot(tmp_path: Path) -> None:
    # "visit id" is a non-patient identifier; the patient column "MRN" must win even when it is second.
    rows = _run_csv(tmp_path, "Visit ID,MRN,Hb\nVS-00001,MRX00991,10.1\n")
    assert rows[1][1].startswith("PSN-")
    assert not rows[1][0].startswith("PSN-")
